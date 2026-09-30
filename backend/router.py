"""Event routing.

The router is the only place that knows the pipeline order::

    TranscriptEvent --(ClaimEngine)--> ClaimEvent
    ClaimEvent      --(VerificationEngine)--> VerificationEvent
    VerificationEvent -----------------------------> frontend WebSocket

Responsibilities kept deliberately narrow:

* preserve ``sessionId`` and ``claimId`` end to end
* broadcast every produced event to the session's frontend clients
* convert any downstream failure into a structured ``error`` event
* never contain LLM, search or AssemblyAI logic itself

Counters per event type are returned so the HTTP ingest routes can report what
the pipeline produced, while the same events are simultaneously pushed to the
WebSocket.

Exactly-once verification
-------------------------
``claimId`` is the identity key, and the two ingress paths share one registry
owned by :class:`~backend.session_manager.SessionManager`:

* ``POST /events/transcript`` verifies only the claims it has just extracted
* ``POST /events/claim`` verifies an externally produced claim once
* a claim id already seen for this session is never verified or broadcast a
  second time, whichever path delivers it again
"""

from typing import Any, List, Optional, Tuple

from backend.adapters.claim_engine import (
    ClaimEngine,
    ClaimEngineError,
    LLMRateLimitError,
)
from backend.adapters.verification import VerificationEngine, VerificationEngineError
from backend.logging_config import (
    CLAIM_CREATED,
    TRANSCRIPT_RECEIVED,
    VERIFICATION_COMPLETED,
    VERIFICATION_STARTED,
    get_logger,
    log_trace,
)
from backend.schemas import (
    ClaimEvent,
    ErrorCode,
    ErrorEvent,
    PipelineCounts,
    TranscriptEvent,
    VerificationEvent,
)
from backend.session_manager import SessionManager
from backend.websocket_manager import WebSocketManager

logger = get_logger("router")


class EventRouter:
    """Routes validated events between the pipeline stages and the frontend."""

    def __init__(
        self,
        session_manager: SessionManager,
        websocket_manager: WebSocketManager,
        claim_engine: ClaimEngine,
        verification_engine: VerificationEngine,
        store: Any = None,
    ) -> None:
        self.sessions = session_manager
        self.websockets = websocket_manager
        self.claim_engine = claim_engine
        self.verification_engine = verification_engine
        # Optional persistent history sink. Absent or null stores make these
        # calls no-ops, so persistence never affects the pipeline's behaviour.
        self.store = store

    async def _persist(self, coro_name: str, *args: Any, **kwargs: Any) -> None:
        """Fire a history write, swallowing every failure.

        Persistence must never delay or break a live pipeline, so this both
        bounds the wait and discards errors. The store's own methods already
        fail soft; this guards the call itself.
        """
        store = self.store
        if store is None:
            return
        method = getattr(store, coro_name, None)
        if method is None:
            return
        try:
            await method(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - history is never fatal
            logger.warning(
                "Persistence call %s failed (ignored): %s",
                coro_name,
                type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # Transcript -> Claim -> Verification
    # ------------------------------------------------------------------
    async def handle_transcript(
        self, transcript: TranscriptEvent
    ) -> Tuple[PipelineCounts, List[ClaimEvent], List[VerificationEvent]]:
        """Run one transcript event through the full pipeline.

        The transcript itself is broadcast first so the frontend can render the
        live line immediately, then any claim is broadcast (rendered as
        ``CLAIM_PENDING``) before its verification result arrives.

        Returns:
            ``(counts, claims, verifications)``.
        """
        session_id = transcript.sessionId
        await self.sessions.bump(session_id, "transcriptCount")
        log_trace(
            TRANSCRIPT_RECEIVED,
            sessionId=session_id,
            speaker=transcript.speaker,
            isFinal=transcript.isFinal,
            textLength=len(transcript.text),
        )
        await self.broadcast(session_id, transcript)

        # An AssemblyAI realtime stream sends growing interim segments. They are
        # broadcast and counted, but only a finalized line may be claim-checked.
        if not transcript.isFinal:
            return PipelineCounts(), [], []

        try:
            claims = await self.claim_engine.extract_claims(transcript)
        except LLMRateLimitError as exc:
            # Caught before ClaimEngineError, which it subclasses: a 429 is
            # transient and self-healing, so it gets its own code rather than
            # being reported as a broken claim engine.
            await self.emit_error(
                session_id,
                ErrorCode.LLM_RATE_LIMITED,
                "The LLM Gateway is rate limiting requests. "
                "Claims were skipped for this segment.",
                claimId=None,
                recoverable=True,
                detail=str(exc),
            )
            return PipelineCounts(errors=1), [], []
        except ClaimEngineError as exc:
            await self.emit_error(
                session_id,
                ErrorCode.CLAIM_EXTRACTION_FAILED,
                "Claim extraction failed for the incoming transcript.",
                claimId=None,
                detail=str(exc),
            )
            return PipelineCounts(errors=1), [], []
        except Exception as exc:  # noqa: BLE001 - never break the live stream
            await self.emit_error(
                session_id,
                ErrorCode.CLAIM_EXTRACTION_FAILED,
                "Claim extraction failed for the incoming transcript.",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return PipelineCounts(errors=1), [], []

        verifications: List[VerificationEvent] = []
        errors = 0
        fresh = 0

        for claim in claims:
            # Backend owns sessionId: force the claim into this session even if
            # a downstream engine returned a stale or missing value.
            claim = claim.model_copy(update={"sessionId": session_id})
            # An id already seen for this session was verified (or is being
            # verified) via another path, so it is neither re-broadcast nor
            # re-verified.
            if not await self.sessions.register_claim(session_id, claim):
                log_trace(
                    "CLAIM_DUPLICATE",
                    sessionId=session_id,
                    claimId=claim.claimId,
                )
                continue
            fresh += 1
            await self.sessions.bump(session_id, "claimCount")
            log_trace(
                CLAIM_CREATED,
                sessionId=session_id,
                claimId=claim.claimId,
                claimType=claim.claimType,
                speaker=claim.speaker,
            )
            await self.broadcast(session_id, claim)
            await self._persist("record_claim", claim)

            verification, failed = await self._verify_claim(claim)
            if verification is not None:
                verifications.append(verification)
            if failed:
                errors += 1

        return (
            PipelineCounts(claims=fresh, verifications=len(verifications), errors=errors),
            claims,
            verifications,
        )

    async def _verify_claim(
        self, claim: ClaimEvent
    ) -> Tuple[Optional[VerificationEvent], bool]:
        """Verify one claim. Returns ``(verification_or_None, had_error)``."""
        session_id = claim.sessionId
        log_trace(
            VERIFICATION_STARTED,
            sessionId=session_id,
            claimId=claim.claimId,
            engine=getattr(self.verification_engine, "name", "unknown"),
        )
        try:
            verification = await self.verification_engine.verify(claim)
        except VerificationEngineError as exc:
            await self.emit_error(
                session_id,
                ErrorCode.VERIFICATION_FAILED,
                "Unable to verify the claim.",
                claimId=claim.claimId,
                detail=str(exc),
            )
            return None, True
        except Exception as exc:  # noqa: BLE001 - never break the live stream
            await self.emit_error(
                session_id,
                ErrorCode.VERIFICATION_FAILED,
                "Unable to verify the claim.",
                claimId=claim.claimId,
                detail=f"{type(exc).__name__}: {exc}",
            )
            return None, True

        if verification is None:
            await self.emit_error(
                session_id,
                ErrorCode.VERIFICATION_FAILED,
                "The verification engine returned no result for the claim.",
                claimId=claim.claimId,
            )
            return None, True

        # Preserve identity across the boundary: the frontend matches on
        # claimId, and the backend owns sessionId.
        verification = verification.model_copy(
            update={"claimId": claim.claimId, "sessionId": session_id}
        )
        await self.sessions.store_verification(session_id, verification)
        await self.sessions.bump(session_id, "verificationCount")
        log_trace(
            VERIFICATION_COMPLETED,
            sessionId=session_id,
            claimId=verification.claimId,
            verdict=verification.verdict.value,
        )
        await self.broadcast(session_id, verification)
        await self._persist(
            "record_verification",
            verification,
            from_cache=bool(getattr(verification, "fromCache", False)),
        )
        return verification, False

    # ------------------------------------------------------------------
    # Claims supplied directly (Atif -> backend, no transcript)
    # ------------------------------------------------------------------
    async def handle_claim(
        self, claim: ClaimEvent
    ) -> Tuple[PipelineCounts, List[VerificationEvent]]:
        """Route an already-extracted claim to verification and the frontend.

        A claim id already seen for this session is idempotent: it is not
        re-broadcast, not re-verified, and the verification produced the first
        time is returned to the caller.
        """
        session_id = claim.sessionId
        if not await self.sessions.register_claim(session_id, claim):
            log_trace(
                "CLAIM_DUPLICATE",
                sessionId=session_id,
                claimId=claim.claimId,
            )
            existing = await self.sessions.get_verification(session_id, claim.claimId)
            return PipelineCounts(claims=0), (
                [existing] if existing is not None else []
            )

        await self.sessions.bump(session_id, "claimCount")
        log_trace(
            CLAIM_CREATED,
            sessionId=session_id,
            claimId=claim.claimId,
            claimType=claim.claimType,
            speaker=claim.speaker,
            source="inbound",
        )
        await self.broadcast(session_id, claim)
        await self._persist("record_claim", claim)

        verification, failed = await self._verify_claim(claim)
        return (
            PipelineCounts(
                claims=1,
                verifications=1 if verification is not None else 0,
                errors=1 if failed else 0,
            ),
            [verification] if verification is not None else [],
        )

    # ------------------------------------------------------------------
    # Verifications supplied directly (verification engine -> backend)
    # ------------------------------------------------------------------
    async def handle_verification(
        self, verification: VerificationEvent
    ) -> Tuple[VerificationEvent, int, bool]:
        """Accept a verification produced elsewhere and broadcast it.

        Used when verification runs out of process, e.g. when Nayanika's engine
        calls ``POST /events/verification`` from a separate service. Idempotent
        on ``claimId``: a claim already verified in this session keeps its first
        result, so a repeated post neither re-broadcasts nor re-counts. The
        response carries the *stored* verdict, so a client that retries with a
        different verdict is told the truth rather than echoing its own input.

        Returns ``(effective_verification, delivered, was_duplicate)``.
        """
        session_id = verification.sessionId
        existing = await self.sessions.get_verification(
            session_id, verification.claimId
        )
        if existing is not None:
            log_trace(
                "VERIFICATION_DUPLICATE",
                sessionId=session_id,
                claimId=verification.claimId,
            )
            return existing, 0, True

        await self.sessions.store_verification(session_id, verification)
        await self.sessions.bump(session_id, "verificationCount")
        log_trace(
            VERIFICATION_COMPLETED,
            sessionId=session_id,
            claimId=verification.claimId,
            verdict=verification.verdict.value,
            source="inbound",
        )
        delivered = await self.broadcast(session_id, verification)
        await self._persist(
            "record_verification",
            verification,
            from_cache=bool(getattr(verification, "fromCache", False)),
        )
        return verification, delivered, False

    # ------------------------------------------------------------------
    # Broadcasting and errors
    # ------------------------------------------------------------------
    async def broadcast(self, session_id: str, event) -> int:
        """Broadcast any event to a session's frontend clients."""
        return await self.websockets.send_to_session(session_id, event)

    async def emit_error(
        self,
        session_id: Optional[str],
        code: ErrorCode,
        message: str,
        claimId: Optional[str] = None,
        recoverable: bool = True,
        detail: Optional[str] = None,
    ) -> ErrorEvent:
        """Build, count and broadcast a structured error event."""
        event = ErrorEvent(
            type="error",
            sessionId=session_id,
            code=code,
            message=message,
            recoverable=recoverable,
            claimId=claimId,
            detail=detail,
        )
        if session_id:
            await self.sessions.bump(session_id, "errorCount")
            await self.broadcast(session_id, event)
        logger.warning(
            "Backend error event emitted: %s (%s)",
            code.value,
            message,
            extra={
                "trace": "ERROR_EVENT",
                "sessionId": session_id,
                "claimId": claimId,
                "code": code.value,
            },
        )
        return event
