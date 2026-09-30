"""Session lifecycle routes.

The backend owns ``sessionId``: clients never supply one.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status

from backend.logging_config import SESSION_STARTED, get_logger
from backend.mocks.mock_stream import stream_mock_transcripts
from backend.schemas import (
    ErrorCode,
    SessionEvent,
    SessionEventStatus,
    SessionStateResponse,
    SessionStatus,
    StartSessionRequest,
    StartSessionResponse,
)
from backend.session_manager import SessionNotFoundError
from backend.websocket_manager import WebSocketManager

router = APIRouter(prefix="/session", tags=["session"])
logger = get_logger("routes.session")


def _state(
    session, websocket_manager: WebSocketManager, request: Request
) -> SessionStateResponse:
    """Build a session snapshot including live connection counts."""
    return SessionStateResponse(
        **session.to_dict(
            connected_clients=websocket_manager.connection_count(session.sessionId),
            ws_url=str(
                request.url_for("session_websocket", session_id=session.sessionId)
            ).replace("http", "ws", 1),
        )
    )


@router.post(
    "/start",
    response_model=StartSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_session(
    request: Request, body: Optional[StartSessionRequest] = None
) -> StartSessionResponse:
    """Create a session and return its id plus the WebSocket URL to connect to.

    The body is optional. When ``startMockPipeline`` is true, the deterministic
    mock transcript -> claim -> verification flow is pushed through the session
    in the background, which needs no API keys.
    """
    settings = request.app.state.settings
    session_manager = request.app.state.session_manager
    websocket_manager = request.app.state.websocket_manager
    router_instance = request.app.state.router

    options = body or StartSessionRequest()
    session = await session_manager.create()

    response = StartSessionResponse(
        **session.to_dict(
            connected_clients=websocket_manager.connection_count(session.sessionId),
            ws_url=str(
                request.url_for("session_websocket", session_id=session.sessionId)
            ).replace("http", "ws", 1),
        )
    )

    # Announce the new session to any client that attached to this id already.
    await router_instance.broadcast(
        session.sessionId,
        SessionEvent(
            type="session",
            sessionId=session.sessionId,
            status=SessionEventStatus.STARTED,
        ),
    )

    if options.startMockPipeline:
        if not settings.use_mock_engines:
            logger.warning(
                "startMockPipeline requested but use_mock_engines is disabled; "
                "the mock stream will not run.",
                extra={"trace": SESSION_STARTED, "sessionId": session.sessionId},
            )
        else:
            # The session owns this task: `POST /session/stop` cancels and awaits
            # it, so nothing keeps streaming (or 409-ing) after a stop.
            # The websocket manager is passed so the stream waits for the
            # browser to attach; otherwise the first events would be emitted
            # into a session with no listener and lost.
            task = asyncio.create_task(
                stream_mock_transcripts(
                    router_instance,
                    session_manager,
                    session.sessionId,
                    websocket_manager=websocket_manager,
                )
            )
            session_manager.track_background_task(session.sessionId, task)

    # Persistent session history. Failures are swallowed by the router helper,
    # so a database problem cannot prevent the session from being returned.
    await router_instance._persist(
        "record_session",
        session_id=session.sessionId,
        status=SessionStatus.STARTED.value,
        created_at=session.createdAt,
        updated_at=session.updatedAt,
    )

    return response


@router.post("/stop")
async def stop_session(request: Request, sessionId: str) -> SessionStateResponse:
    """Stop a running session and close its WebSocket clients."""
    session_manager = request.app.state.session_manager
    websocket_manager = request.app.state.websocket_manager
    router_instance = request.app.state.router

    try:
        await session_manager.require(sessionId)
    except SessionNotFoundError:
        await router_instance.emit_error(
            sessionId,
            ErrorCode.SESSION_NOT_FOUND,
            f"No active session with id {sessionId}.",
            recoverable=False,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.SESSION_NOT_FOUND.value, "message": "Session not found."},
        )

    session = await session_manager.stop(sessionId)
    closed = await websocket_manager.disconnect_all(sessionId)

    await router_instance.broadcast(
        sessionId,
        SessionEvent(
            type="session",
            sessionId=sessionId,
            status=SessionEventStatus.STOPPED,
        ),
    )

    logger.info(
        "Session stopped and %d websocket client(s) closed",
        closed,
        extra={"trace": "SESSION_STOPPED", "sessionId": sessionId},
    )

    await router_instance._persist(
        "record_session",
        session_id=sessionId,
        status=SessionStatus.STOPPED.value,
        created_at=session.createdAt,
        updated_at=session.updatedAt,
        ended_at=session.updatedAt,
        transcript_count=session.transcriptCount,
        claim_count=session.claimCount,
        verification_count=session.verificationCount,
        error_count=session.errorCount,
    )

    return _state(session, websocket_manager, request)


@router.get("/{session_id}", response_model=SessionStateResponse)
async def get_session(session_id: str, request: Request) -> SessionStateResponse:
    """Return the current state of a session."""
    session_manager = request.app.state.session_manager
    websocket_manager = request.app.state.websocket_manager
    router_instance = request.app.state.router

    try:
        session = await session_manager.require(session_id)
    except SessionNotFoundError:
        await router_instance.emit_error(
            session_id,
            ErrorCode.SESSION_NOT_FOUND,
            f"No active session with id {session_id}.",
            recoverable=False,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.SESSION_NOT_FOUND.value, "message": "Session not found."},
        )

    return _state(session, websocket_manager, request)
