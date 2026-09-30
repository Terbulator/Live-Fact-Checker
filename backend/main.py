"""Application entry point for the Live Fact-Checker backend.

Wires configuration, structured logging, CORS, the session manager, the
WebSocket manager, the pipeline adapters and the event router into a single
ASGI application.

Run locally::

    uvicorn backend.main:app --reload
"""

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.adapters.claim_engine import ClaimEngine, LLMClaimEngine
from backend.adapters.verification import (
    UnavailableVerificationEngine,
    VerificationEngine,
    VerificationServiceEngine,
)
from backend.config import Settings, get_settings
from backend.logging_config import configure_logging, get_logger
from backend.mocks.mock_stream import MockClaimEngine, MockVerificationEngine
from backend.router import EventRouter
from backend.routes import assemblyai as assemblyai_routes
from backend.routes import events as events_routes
from backend.routes import health as health_routes
from backend.routes import session as session_routes
from backend.schemas import (
    ErrorCode,
    ErrorEvent,
    SessionEvent,
    SessionEventStatus,
)
from backend.session_manager import SessionManager, SessionNotFoundError
from backend.websocket_manager import WebSocketManager

logger = get_logger("main")

DESCRIPTION = """
Backend for the Live Fact-Checker hackathon project.

Pipeline served by this service:

    Audio -> AssemblyAI realtime STT (Tushar) -> TranscriptEvent
          -> Claim intelligence (Atif)              -> ClaimEvent
          -> Verification (Nayanika)                -> VerificationEvent
          -> WebSocket broadcast                    -> Frontend (Rupan)
"""


def _default_claim_engine(settings: Settings) -> ClaimEngine:
    """Pick the claim engine from the single ``use_mock_engines`` switch.

    * mock mode -> :class:`MockClaimEngine`, fully offline
    * real mode  -> :class:`LLMClaimEngine` against the configured
      OpenAI-compatible LLM Gateway

    The real path is deliberately never downgraded to
    :class:`UnavailableClaimEngine`: a missing credential or an unreachable
    gateway must surface as a structured ``CLAIM_EXTRACTION_FAILED`` event
    rather than as a pipeline that quietly emits no claims and looks healthy.

    ``strict=True`` makes the engine fail loudly instead of silently falling
    back to the offline rule-based extractor, which would otherwise broadcast
    fabricated claims as if the model had produced them. The app still starts,
    so ``GET /health`` stays reachable for diagnosis.
    """
    if settings.use_mock_engines:
        return MockClaimEngine()
    return LLMClaimEngine(settings, strict=True)


def _default_verification_engine(settings: Settings) -> VerificationEngine:
    """Pick the verification engine from the single ``use_mock_engines`` switch.

    * mock mode -> :class:`MockVerificationEngine`, fully offline
    * real mode  -> :class:`VerificationServiceEngine`, which runs the existing
      ``verification`` package and needs no code change to activate

    If the ``verification`` package cannot be imported the backend degrades to
    :class:`UnavailableVerificationEngine` instead of failing to start, so every
    failure surfaces as a structured ``VERIFICATION_FAILED`` event.
    """
    if settings.use_mock_engines:
        return MockVerificationEngine()
    try:
        return VerificationServiceEngine()
    except Exception as exc:  # noqa: BLE001 - a missing module must not kill startup
        logger.warning(
            "Real verification unavailable, falling back to the stub engine: %s",
            type(exc).__name__,
            extra={
                "trace": "VERIFICATION_ENGINE_FALLBACK",
                "errorType": type(exc).__name__,
            },
        )
        return UnavailableVerificationEngine()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Configure logging on startup and tear down state on shutdown."""
    settings: Settings = app.state.settings
    configure_logging(
        level=settings.log_level,
        json_output=settings.log_json,
        secret_values=[
            value.get_secret_value()
            for value in (
                settings.assemblyai_api_key,
                settings.llm_gateway_api_key,
                settings.search_api_key,
            )
            if value is not None
        ],
    )
    logger.info(
        "Backend starting: service=%s version=%s environment=%s mockEngines=%s",
        settings.app_name,
        settings.app_version,
        settings.environment,
        settings.use_mock_engines,
        extra={"trace": "BACKEND_STARTING", "mockEngines": settings.use_mock_engines},
    )
    try:
        yield
    finally:
        # Settle the mock pipelines first so no task is left pending.
        await app.state.session_manager.cancel_all_background_tasks()
        await app.state.websocket_manager.clear()
        logger.info("Backend stopped", extra={"trace": "BACKEND_STOPPED"})


def create_app(
    settings: Optional[Settings] = None,
    claim_engine: Optional[ClaimEngine] = None,
    verification_engine: Optional[VerificationEngine] = None,
) -> FastAPI:
    """Build the ASGI application.

    Every collaborator is injectable so tests can supply deterministic engines
    without touching module-level state.
    """
    resolved_settings = settings or get_settings()

    session_manager = SessionManager()
    websocket_manager = WebSocketManager()
    resolved_claim_engine = claim_engine or _default_claim_engine(resolved_settings)
    resolved_verification_engine = verification_engine or _default_verification_engine(
        resolved_settings
    )
    event_router = EventRouter(
        session_manager=session_manager,
        websocket_manager=websocket_manager,
        claim_engine=resolved_claim_engine,
        verification_engine=resolved_verification_engine,
    )

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=DESCRIPTION,
        lifespan=_lifespan,
    )

    app.state.settings = resolved_settings
    app.state.session_manager = session_manager
    app.state.websocket_manager = websocket_manager
    app.state.claim_engine = resolved_claim_engine
    app.state.verification_engine = resolved_verification_engine
    app.state.router = event_router

    # CORS: explicit origins only. A wildcard is rejected in production by
    # Settings.resolved_cors_origins().
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.resolved_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_routes.router)
    app.include_router(session_routes.router)
    app.include_router(events_routes.router)
    app.include_router(assemblyai_routes.router)

    _register_exception_handlers(app)
    _register_websocket_route(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """Return structured error payloads for unexpected server failures."""

    @app.exception_handler(SessionNotFoundError)
    async def _session_not_found(request: Request, exc: SessionNotFoundError):
        return JSONResponse(
            status_code=404,
            content={
                "code": ErrorCode.SESSION_NOT_FOUND.value,
                "message": "Session not found.",
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception(
            "Unhandled backend error: %s",
            type(exc).__name__,
            extra={"trace": "UNHANDLED_ERROR", "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "Internal backend error.",
                "recoverable": True,
            },
        )


def _register_websocket_route(app: FastAPI) -> None:
    """Attach ``WS /ws/session/{session_id}`` to the application."""

    @app.websocket("/ws/session/{session_id}", name="session_websocket")
    async def session_websocket(websocket: WebSocket, session_id: str) -> None:
        session_manager: SessionManager = app.state.session_manager
        websocket_manager: WebSocketManager = app.state.websocket_manager

        session = await session_manager.get(session_id)

        await websocket_manager.connect(websocket, session_id)

        if session is None:
            # A frontend connecting to a session that was never started still
            # gets a clean structured error. The socket is registered so it is
            # still cleaned up, but no further events can ever reach it.
            await websocket_manager.send_to_client(
                websocket,
                ErrorEvent(
                    type="error",
                    sessionId=session_id,
                    code=ErrorCode.SESSION_NOT_FOUND,
                    message=f"No active session with id {session_id}.",
                    recoverable=False,
                ),
            )
        else:
            await session_manager.mark_connected(session_id)
            # Sent only to the newly connected client; other clients of this
            # session must not receive a duplicate `connected` event.
            await websocket_manager.send_to_client(
                websocket,
                SessionEvent(
                    type="session",
                    sessionId=session_id,
                    status=SessionEventStatus.CONNECTED,
                ),
            )

        try:
            while True:
                message = await websocket.receive_text()
                await _handle_client_message(websocket, session_id, message)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001 - a broken client is not a server fault
            logger.debug(
                "WebSocket loop ended for %s: %s",
                session_id,
                type(exc).__name__,
                extra={"trace": "WS_LOOP_ENDED", "sessionId": session_id},
            )
        finally:
            await websocket_manager.disconnect(websocket, session_id)


async def _handle_client_message(
    websocket: WebSocket, session_id: str, message: str
) -> None:
    """Handle a message sent by a frontend client.

    Only liveness is supported today. Confirm/dispute (PRD FR-8) will be added
    here later, keyed on ``claimId``.
    """
    try:
        payload = json.loads(message)
    except (TypeError, ValueError):
        await websocket.send_json(
            {
                "type": "error",
                "sessionId": session_id,
                "code": ErrorCode.MALFORMED_EVENT.value,
                "message": "Client message must be valid JSON.",
                "recoverable": True,
            }
        )
        return

    if isinstance(payload, dict) and payload.get("type") == "ping":
        await websocket.send_json({"type": "pong", "sessionId": session_id})


app = create_app()
