"""In-memory session registry.

The backend owns ``sessionId`` generation and lifecycle. Sessions are held in
process memory, which is appropriate for the hackathon demo but means:

    * state is **not** shared between worker processes or replicas
    * state is **lost** on restart
    * a horizontally scaled deployment would need a shared store (Redis, etc.)

The manager also owns two per-session registries that make the pipeline
idempotent and lifecycle-safe:

* ``claimId -> claim`` and ``claimId -> verification``, so a claim is verified
  exactly once no matter which ingress path delivered it
* ``sessionId -> background task``, so a running mock pipeline is cancelled
  when the session stops

Deployments must therefore run a single backend instance. See the README.

Session IDs are cryptographically secure random strings to prevent session
hijacking via prediction.
"""

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.logging_config import SESSION_STARTED, SESSION_STOPPED, get_logger, log_trace
from backend.schemas import ClaimEvent, SessionStatus, VerificationEvent

logger = get_logger("session_manager")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_session_id() -> str:
    """Generate a cryptographically secure session ID.

    Uses URL-safe base64 encoding of 24 random bytes (192 bits of entropy),
    yielding a 32-character string that is unpredictable and collision-resistant.
    """
    return secrets.token_urlsafe(24)


@dataclass
class Session:
    """A single fact-check session and its counters."""

    sessionId: str
    status: SessionStatus = SessionStatus.STARTED
    createdAt: str = field(default_factory=_utc_now)
    updatedAt: str = field(default_factory=_utc_now)
    transcriptCount: int = 0
    claimCount: int = 0
    verificationCount: int = 0
    errorCount: int = 0

    def touch(self) -> None:
        self.updatedAt = _utc_now()

    def is_active(self) -> bool:
        return self.status is not SessionStatus.STOPPED

    def to_dict(self, connected_clients: int = 0, ws_url: Optional[str] = None) -> Dict:
        return {
            "sessionId": self.sessionId,
            "status": self.status.value,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
            "connectedClients": connected_clients,
            "transcriptCount": self.transcriptCount,
            "claimCount": self.claimCount,
            "verificationCount": self.verificationCount,
            "errorCount": self.errorCount,
            "wsUrl": ws_url,
        }


async def _settle(task: "asyncio.Task[None]", session_id: str) -> None:
    """Cancel a background task and consume its outcome.

    Awaiting the cancelled task is what stops asyncio reporting ``Task was
    destroyed but it is pending`` / ``exception was never retrieved`` when a
    session stops or the app shuts down.
    """
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info(
            "Background task for %s cancelled",
            session_id,
            extra={"trace": SESSION_STOPPED, "sessionId": session_id},
        )
    except Exception as exc:  # noqa: BLE001 - a failed task must not raise here
        logger.warning(
            "Background task for %s failed: %s",
            session_id,
            type(exc).__name__,
            extra={
                "trace": "BACKGROUND_TASK_FAILED",
                "sessionId": session_id,
                "errorType": type(exc).__name__,
            },
        )


class SessionNotFoundError(KeyError):
    """Raised when a session id is unknown to the registry."""

    def __init__(self, session_id: str) -> None:
        super().__init__(session_id)
        self.session_id = session_id

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Unknown session: {self.session_id}"


class SessionManager:
    """Async-safe, in-memory session store.

    All mutations happen under an :class:`asyncio.Lock` so the registry stays
    consistent when several WebSocket clients and HTTP requests interleave.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()
        # (sessionId, claimId) -> event. Keyed by both because a claim id
        # minted by a teammate or by the mock engine recurs across sessions.
        self._claims: Dict[Tuple[str, str], ClaimEvent] = {}
        self._verifications: Dict[Tuple[str, str], VerificationEvent] = {}
        self._background: Dict[str, "asyncio.Task[None]"] = {}

    # -- id generation ----------------------------------------------------
    @staticmethod
    def _next_session_id() -> str:
        """Return a cryptographically secure random session id."""
        return _generate_session_id()

    # -- lifecycle --------------------------------------------------------
    async def create(self) -> Session:
        """Create and register a new session."""
        async with self._lock:
            session_id = self._next_session_id()
            session = Session(sessionId=session_id)
            self._sessions[session_id] = session
        log_trace(
            SESSION_STARTED,
            sessionId=session.sessionId,
            createdAt=session.createdAt,
        )
        return session

    async def get(self, session_id: str) -> Optional[Session]:
        """Return a session, or ``None`` when it does not exist."""
        async with self._lock:
            return self._sessions.get(session_id)

    async def require(self, session_id: str) -> Session:
        """Return a session or raise :class:`SessionNotFoundError`."""
        session = await self.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    async def stop(self, session_id: str) -> Session:
        """Mark a session as stopped and cancel its background task.

        Stopping twice is a no-op. The task is awaited outside the lock on
        purpose: a cancelled mock pipeline may already be parked waiting for
        this lock, so awaiting it while holding the lock would deadlock.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.status is not SessionStatus.STOPPED:
                session.status = SessionStatus.STOPPED
                session.touch()
            task = self._background.pop(session_id, None)
        if task is not None:
            await _settle(task, session_id)
        log_trace(SESSION_STOPPED, sessionId=session_id)
        return session

    # -- background tasks -------------------------------------------------
    def track_background_task(self, session_id: str, task: "asyncio.Task[None]") -> None:
        """Remember a task so :meth:`stop` can cancel it.

        Not locked: the event loop is single-threaded and the caller assigns the
        task immediately after creating it, with no await in between.
        """
        self._background[session_id] = task

    async def background_task(self, session_id: str) -> Optional["asyncio.Task[None]"]:
        """Return the tracked background task, if any."""
        async with self._lock:
            return self._background.get(session_id)

    async def cancel_all_background_tasks(self) -> None:
        """Cancel every tracked task. Used on shutdown and by tests."""
        async with self._lock:
            tasks = list(self._background.items())
            self._background.clear()
        for session_id, task in tasks:
            await _settle(task, session_id)

    # -- claim identity (exactly-once verification) ----------------------
    async def register_claim(self, session_id: str, claim: ClaimEvent) -> bool:
        """Claim a ``claimId`` for a session.

        Returns ``True`` only the first time the id is seen for that session, so
        the caller can verify it exactly once. A claim delivered by the
        transcript pipeline and then again via ``POST /events/claim`` with the
        same id is therefore verified once, not twice.
        """
        key = (session_id, claim.claimId)
        async with self._lock:
            if key in self._claims:
                return False
            self._claims[key] = claim
            return True

    async def store_verification(
        self, session_id: str, verification: VerificationEvent
    ) -> None:
        """Record the authoritative verification for a claim id."""
        async with self._lock:
            self._verifications[(session_id, verification.claimId)] = verification

    async def get_verification(
        self, session_id: str, claim_id: str
    ) -> Optional[VerificationEvent]:
        """Return the verification already produced for this claim id."""
        async with self._lock:
            return self._verifications.get((session_id, claim_id))

    async def mark_connected(self, session_id: str) -> Session:
        """Record that a frontend client attached to the session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if session.status is SessionStatus.STARTED:
                session.status = SessionStatus.CONNECTED
            session.touch()
            return session

    async def remove(self, session_id: str) -> Optional[Session]:
        """Delete a session from the registry entirely."""
        async with self._lock:
            return self._sessions.pop(session_id, None)

    # -- counters ---------------------------------------------------------
    async def bump(self, session_id: str, field: str, count: int = 1) -> Optional[Session]:
        """Increment one counter on a session and refresh its ``updatedAt``.

        Args:
            session_id: Session to update.
            field: Name of the counter attribute on :class:`Session`.
            count: Amount to add. Defaults to 1.

        Returns:
            The updated session, or ``None`` when the session is unknown.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                setattr(session, field, getattr(session, field) + count)
                session.touch()
            return session

    # -- listing ----------------------------------------------------------
    async def count(self) -> int:
        async with self._lock:
            return len(self._sessions)
