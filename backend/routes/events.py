"""Event ingestion routes.

These are the inbound boundaries for the other modules:

* ``POST /events/transcript``   — Tushar (AssemblyAI realtime STT)
* ``POST /events/claim``        — Atif (claim intelligence)
* ``POST /events/verification`` — Nayanika (verification engine, when it runs
  out of process)

Bodies are read as raw JSON so the backend controls its own validation and can
report contract drift as a structured ``error`` event instead of FastAPI's
default 422 shape. Every accepted event is validated, routed, and broadcast to
the session's WebSocket clients before the response returns.
"""

from typing import Any, Dict, Optional, Type, TypeVar

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

from backend.logging_config import SCHEMA_VALIDATION_FAILED, get_logger
from backend.schemas import (
    ClaimAcceptedResponse,
    ClaimEvent,
    ErrorCode,
    TranscriptAcceptedResponse,
    TranscriptEvent,
    VerificationAcceptedResponse,
    VerificationEvent,
    unknown_fields,
)
from backend.session_manager import SessionNotFoundError

router = APIRouter(prefix="/events", tags=["events"])
logger = get_logger("routes.events")

# Spelled numerically: the starlette constant for this code was renamed, and
# the numeric literal is stable across versions.
HTTP_422_UNPROCESSABLE = 422

ModelT = TypeVar("ModelT", bound=BaseModel)


async def _read_json(request: Request) -> Dict[str, Any]:
    """Read the request body as a JSON object."""
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001 - malformed body is a client error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.MALFORMED_EVENT.value,
                "message": "Request body must be valid JSON.",
            },
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.MALFORMED_EVENT.value,
                "message": "Request body must be a JSON object.",
            },
        )
    return payload


async def _validate(
    request: Request, model: Type[ModelT], session_id_hint: Optional[str] = None
) -> ModelT:
    """Validate an inbound event, raising the API's standard 422 on failure."""
    router_instance = request.app.state.router
    payload = await _read_json(request)

    event_type = payload.get("type")
    if event_type is not None and event_type != _expected_type(model):
        await router_instance.emit_error(
            session_id_hint or payload.get("sessionId"),
            ErrorCode.UNSUPPORTED_EVENT_TYPE,
            f"Expected type '{_expected_type(model)}' but received '{event_type}'.",
            recoverable=False,
        )
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": ErrorCode.UNSUPPORTED_EVENT_TYPE.value,
                "message": f"Expected type '{_expected_type(model)}'.",
            },
        )

    try:
        event = model.model_validate(payload)
    except ValidationError as exc:
        await router_instance.emit_error(
            session_id_hint or payload.get("sessionId"),
            ErrorCode.SCHEMA_VALIDATION_FAILED,
            f"Inbound event failed {model.__name__} validation.",
            detail=_summarize(exc),
        )
        raise HTTPException(
            status_code=HTTP_422_UNPROCESSABLE,
            detail={
                "code": ErrorCode.SCHEMA_VALIDATION_FAILED.value,
                "message": f"Inbound event failed {model.__name__} validation.",
                "errors": _summarize(exc),
            },
        ) from exc

    extra = unknown_fields(payload, model)
    if extra:
        logger.warning(
            "Ignoring unknown field(s) on %s: %s",
            model.__name__,
            ", ".join(extra),
            extra={
                "trace": SCHEMA_VALIDATION_FAILED,
                "eventType": _expected_type(model),
                "sessionId": event.sessionId,
                "unknownFields": extra,
            },
        )

    return event


def _expected_type(model: Type[BaseModel]) -> str:
    return str(model.model_fields["type"].default)


def _summarize(exc: ValidationError) -> str:
    """Render a pydantic error into one short, log-safe line."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ())) or "body"
        parts.append(f"{location}: {error.get('msg', 'invalid')}")
    return "; ".join(parts)


async def _require_active_session(request: Request, session_id: str) -> None:
    """Reject events for unknown or stopped sessions with 409/404."""
    session_manager = request.app.state.session_manager
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
            detail={
                "code": ErrorCode.SESSION_NOT_FOUND.value,
                "message": "Session not found. POST /session/start first.",
            },
        )

    if not session.is_active():
        await router_instance.emit_error(
            session_id,
            ErrorCode.SESSION_STOPPED,
            f"Session {session_id} has been stopped.",
            recoverable=False,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": ErrorCode.SESSION_STOPPED.value,
                "message": "Session has been stopped.",
            },
        )


@router.post(
    "/transcript", response_model=TranscriptAcceptedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def ingest_transcript(request: Request) -> TranscriptAcceptedResponse:
    """Accept a transcript event, run claim extraction and verification.

    This is the single boundary Tushar's AssemblyAI realtime code calls. Post one
    normalized JSON ``TranscriptEvent`` per segment::

        POST /events/transcript
        {"type": "transcript", "sessionId": "...", "speaker": null,
         "text": "...", "timestamp": 1.2, "isFinal": false}

    ``isFinal: false`` interim segments are accepted, broadcast and counted but
    are never claim-checked; only a finalized line enters claim extraction and
    verification. Requires the session from ``POST /session/start``.

    Returns 202 with the counts/claims/verifications this event produced, 404
    for an unknown session, 409 for a stopped one, and 422 for a malformed or
    mistyped event. The transcript is broadcast first, then any claim (as a
    pending card), then the verification result — so the frontend renders
    progressively.
    """
    router_instance = request.app.state.router
    event: TranscriptEvent = await _validate(request, TranscriptEvent)
    await _require_active_session(request, event.sessionId)

    counts, claims, verifications = await router_instance.handle_transcript(event)
    return TranscriptAcceptedResponse(
        accepted=True,
        sessionId=event.sessionId,
        transcript=event,
        counts=counts,
        claims=claims,
        verifications=verifications,
        # A claimId already verified in this session is skipped, so fewer
        # claims were newly processed than the engine extracted.
        idempotent=counts.claims != len(claims),
    )


@router.post(
    "/claim", response_model=ClaimAcceptedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def ingest_claim(request: Request) -> ClaimAcceptedResponse:
    """Accept a claim event from claim intelligence and verify it."""
    router_instance = request.app.state.router
    event: ClaimEvent = await _validate(request, ClaimEvent)
    await _require_active_session(request, event.sessionId)

    counts, verifications = await router_instance.handle_claim(event)
    return ClaimAcceptedResponse(
        accepted=True,
        sessionId=event.sessionId,
        claim=event,
        counts=counts,
        verifications=verifications,
        # A duplicate claim is counted zero times, so nothing new was verified.
        idempotent=counts.claims == 0,
    )


@router.post(
    "/verification",
    response_model=VerificationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_verification(request: Request) -> VerificationAcceptedResponse:
    """Accept a verification event and broadcast it to the frontend.

    Use this when the verification engine runs outside the backend process and
    posts its result back. The verdict must be one of ``TRUE``, ``FALSE`` or
    ``UNVERIFIABLE``.
    """
    router_instance = request.app.state.router
    event: VerificationEvent = await _validate(request, VerificationEvent)
    await _require_active_session(request, event.sessionId)

    verification, delivered, duplicate = await router_instance.handle_verification(event)
    return VerificationAcceptedResponse(
        accepted=True,
        sessionId=event.sessionId,
        verification=verification,
        broadcastTo=delivered,
        idempotent=duplicate,
    )
