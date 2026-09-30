"""External backend event contracts.

These are the wire formats exchanged with the rest of the team:

* Tushar  -> backend : :class:`TranscriptEvent`
* Atif    -> backend : :class:`ContractClaimEvent`
* Nayanika-> backend : :class:`ContractVerificationEvent`
* backend -> Rupan   : every one of the events below, over the WebSocket

Two deliberate design notes:

1. **Verdict casing is uppercase on the wire** (``TRUE`` / ``FALSE`` /
   ``UNVERIFIABLE``). The existing ``verification`` module uses ``True`` /
   ``False`` / ``Unverifiable``. The translation happens in
   :mod:`backend.adapters.verification`, never by editing that module.

2. **Unknown fields are ignored, not rejected.** Every field present in the
   contract is still validated strictly, but an additional field from a
   teammate logs a ``SCHEMA_VALIDATION_FAILED``-style warning instead of
   breaking the live demo. See :func:`unknown_fields`.

3. **Every event carries an ``eventId``** for deduplication and tracing.
   The backend generates one if not provided by the sender.
"""

from datetime import datetime, timezone
from enum import Enum
import secrets
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

#: Default websocket path template, exposed so the frontend and docs agree.
WS_PATH_TEMPLATE = "/ws/session/{session_id}"


def _generate_event_id() -> str:
    """Generate a cryptographically secure event ID."""
    return secrets.token_urlsafe(16)


class Verdict(str, Enum):
    """External verdict values allowed on the backend wire format."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNVERIFIABLE = "UNVERIFIABLE"


class SessionStatus(str, Enum):
    """Lifecycle status of a backend session."""

    STARTED = "started"
    CONNECTED = "connected"
    STOPPED = "stopped"


class SessionEventStatus(str, Enum):
    """Status values carried by a :class:`SessionEvent`."""

    STARTED = "started"
    CONNECTED = "connected"
    STOPPED = "stopped"
    ERROR = "error"


class ErrorCode(str, Enum):
    """Stable error codes surfaced to clients through :class:`ErrorEvent`."""

    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_STOPPED = "SESSION_STOPPED"
    SESSION_ALREADY_STOPPED = "SESSION_ALREADY_STOPPED"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    UNSUPPORTED_EVENT_TYPE = "UNSUPPORTED_EVENT_TYPE"
    MALFORMED_EVENT = "MALFORMED_EVENT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    CLAIM_EXTRACTION_FAILED = "CLAIM_EXTRACTION_FAILED"
    #: The LLM Gateway answered 429 and the bounded retries were exhausted.
    #: Kept distinct from CLAIM_EXTRACTION_FAILED so the frontend can tell a
    #: transient rate limit apart from a genuine extraction fault.
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    BROADCAST_FAILED = "BROADCAST_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def _require_non_blank(value: str, field_name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{field_name} cannot be empty or whitespace-only.")
    return trimmed


class EventModel(BaseModel):
    """Base class for every event on the wire."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    def to_wire(self) -> Dict[str, Any]:
        """Return a JSON-serialisable payload with enum members as strings."""
        return self.model_dump(mode="json")


class TranscriptEvent(EventModel):
    """Realtime speech-to-text segment produced by Tushar's AssemblyAI module.

    Example::

        {
            "type": "transcript",
            "sessionId": "session_001",
            "speaker": "Speaker 1",
            "text": "India won the 2011 Cricket World Cup.",
            "timestamp": 12.4,
            "isFinal": true
        }
    """

    type: str = Field(default="transcript")
    eventId: str = Field(default_factory=_generate_event_id)
    sessionId: str = Field(..., min_length=1)
    speaker: Optional[str] = Field(default="Speaker 1")
    text: str = Field(..., min_length=1)
    timestamp: float = Field(..., ge=0.0)
    isFinal: bool = Field(default=True)

    @field_validator("type")
    @classmethod
    def _type_must_be_transcript(cls, value: str) -> str:
        if value != "transcript":
            raise ValueError("type must be 'transcript'.")
        return value

    @field_validator("sessionId", "text")
    @classmethod
    def _non_blank(cls, value: str, info: Any) -> str:
        return _require_non_blank(value, info.field_name or "field")

    @field_validator("speaker")
    @classmethod
    def _speaker_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ClaimEvent(EventModel):
    """Checkable factual claim extracted by Atif's claim intelligence module.

    Example::

        {
            "type": "claim",
            "claimId": "claim_001",
            "sessionId": "session_001",
            "speaker": "Speaker 1",
            "timestamp": 12.4,
            "claim": "India won the 2011 Cricket World Cup.",
            "claimType": "historical_fact"
        }
    """

    type: str = Field(default="claim")
    eventId: str = Field(default_factory=_generate_event_id)
    claimId: str = Field(..., min_length=1)
    sessionId: str = Field(..., min_length=1)
    speaker: Optional[str] = Field(default="Speaker 1")
    timestamp: float = Field(..., ge=0.0)
    claim: str = Field(..., min_length=1)
    claimType: str = Field(default="unspecified")

    @field_validator("type")
    @classmethod
    def _type_must_be_claim(cls, value: str) -> str:
        if value != "claim":
            raise ValueError("type must be 'claim'.")
        return value

    @field_validator("claimId", "sessionId", "claim")
    @classmethod
    def _non_blank(cls, value: str, info: Any) -> str:
        return _require_non_blank(value, info.field_name or "field")


#: Alias clarifying that this is the backend-facing claim contract, distinct
#: from the internal ``verification.models.ClaimEvent``.
ContractClaimEvent = ClaimEvent


class VerificationEvent(EventModel):
    """Verdict, reason and citation for a single claim.

    Example::

        {
            "type": "verification",
            "claimId": "claim_001",
            "sessionId": "session_001",
            "speaker": "Speaker 1",
            "timestamp": 12.4,
            "verdict": "TRUE",
            "reason": "India defeated Sri Lanka in the 2011 final.",
            "source": "https://example.com/source"
        }
    """

    type: str = Field(default="verification")
    eventId: str = Field(default_factory=_generate_event_id)
    claimId: str = Field(..., min_length=1)
    sessionId: str = Field(..., min_length=1)
    speaker: Optional[str] = Field(default="Speaker 1")
    timestamp: float = Field(..., ge=0.0)
    verdict: Verdict = Field(...)
    reason: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)

    @field_validator("type")
    @classmethod
    def _type_must_be_verification(cls, value: str) -> str:
        if value != "verification":
            raise ValueError("type must be 'verification'.")
        return value

    @field_validator("claimId", "sessionId", "reason", "source")
    @classmethod
    def _non_blank(cls, value: str, info: Any) -> str:
        return _require_non_blank(value, info.field_name or "field")

    @model_validator(mode="after")
    def _reject_lowercase_verdict(self) -> "VerificationEvent":
        """Accept only the uppercase external verdict values."""
        if isinstance(self.verdict, str) and self.verdict not in {
            Verdict.TRUE.value,
            Verdict.FALSE.value,
            Verdict.UNVERIFIABLE.value,
        }:
            raise ValueError(
                "verdict must be one of 'TRUE', 'FALSE', 'UNVERIFIABLE' (uppercase)."
            )
        return self


#: Alias clarifying that this is the backend-facing verification contract,
#: distinct from the internal ``verification.models.VerificationEvent``.
ContractVerificationEvent = VerificationEvent


class ErrorEvent(EventModel):
    """Structured error surfaced to the frontend and to upstream callers.

    Example::

        {
            "type": "error",
            "sessionId": "session_001",
            "code": "VERIFICATION_FAILED",
            "message": "Unable to verify the claim.",
            "recoverable": true
        }
    """

    type: str = Field(default="error")
    eventId: str = Field(default_factory=_generate_event_id)
    sessionId: Optional[str] = None
    code: ErrorCode = Field(default=ErrorCode.INTERNAL_ERROR)
    message: str = Field(..., min_length=1)
    recoverable: bool = Field(default=True)
    claimId: Optional[str] = None
    detail: Optional[str] = Field(default=None)

    @field_validator("type")
    @classmethod
    def _type_must_be_error(cls, value: str) -> str:
        if value != "error":
            raise ValueError("type must be 'error'.")
        return value

    @field_validator("message")
    @classmethod
    def _message_non_blank(cls, value: str) -> str:
        return _require_non_blank(value, "message")


class SessionEvent(EventModel):
    """Session lifecycle notification broadcast to the frontend.

    Example::

        {"type": "session", "sessionId": "session_001", "status": "connected"}
    """

    type: str = Field(default="session")
    eventId: str = Field(default_factory=_generate_event_id)
    sessionId: str = Field(..., min_length=1)
    status: SessionEventStatus = Field(...)
    detail: Optional[str] = Field(default=None)

    @field_validator("type")
    @classmethod
    def _type_must_be_session(cls, value: str) -> str:
        if value != "session":
            raise ValueError("type must be 'session'.")
        return value

    @field_validator("sessionId")
    @classmethod
    def _session_non_blank(cls, value: str) -> str:
        return _require_non_blank(value, "sessionId")


#: Any event that the backend can emit on the WebSocket.
AnyEvent = Union[
    TranscriptEvent,
    ClaimEvent,
    VerificationEvent,
    ErrorEvent,
    SessionEvent,
]


# ---------------------------------------------------------------------------
# Request / response models for the HTTP API
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    """Optional body for ``POST /session/start``.

    An empty body is valid: the backend owns and generates ``sessionId``.
    """

    model_config = ConfigDict(extra="ignore")

    startMockPipeline: bool = Field(
        default=False,
        description=(
            "Run the deterministic mock transcript -> claim -> verification flow "
            "immediately after the session starts. Requires no API keys."
        ),
    )


class SessionStateResponse(BaseModel):
    """Snapshot of a session returned by the session routes."""

    model_config = ConfigDict(extra="ignore")

    sessionId: str
    status: SessionStatus
    createdAt: str
    updatedAt: str
    connectedClients: int = 0
    transcriptCount: int = 0
    claimCount: int = 0
    verificationCount: int = 0
    errorCount: int = 0
    wsUrl: Optional[str] = None


class StartSessionResponse(SessionStateResponse):
    """Response for ``POST /session/start``."""

    type: str = "session"


class PipelineCounts(BaseModel):
    """Event counts produced while handling one inbound event."""

    model_config = ConfigDict(extra="ignore")

    claims: int = 0
    verifications: int = 0
    errors: int = 0


class TranscriptAcceptedResponse(BaseModel):
    """Result of ``POST /events/transcript``."""

    model_config = ConfigDict(extra="ignore")

    accepted: bool = True
    sessionId: str
    transcript: TranscriptEvent
    counts: PipelineCounts
    claims: List[ClaimEvent] = Field(default_factory=list)
    verifications: List[VerificationEvent] = Field(default_factory=list)
    idempotent: bool = Field(
        default=False,
        description=(
            "True when at least one extracted claimId had already been verified "
            "in this session, so it was not verified again."
        ),
    )


class ClaimAcceptedResponse(BaseModel):
    """Result of ``POST /events/claim``."""

    model_config = ConfigDict(extra="ignore")

    accepted: bool = True
    sessionId: str
    claim: ClaimEvent
    counts: PipelineCounts
    verifications: List[VerificationEvent] = Field(default_factory=list)
    idempotent: bool = Field(
        default=False,
        description=(
            "True when this claimId was already processed in this session; "
            "`verifications` then carries the result produced the first time."
        ),
    )


class VerificationAcceptedResponse(BaseModel):
    """Result of ``POST /events/verification``."""

    model_config = ConfigDict(extra="ignore")

    accepted: bool = True
    sessionId: str
    verification: VerificationEvent
    broadcastTo: int = 0
    idempotent: bool = Field(
        default=False,
        description=(
            "True when this claimId already had a verification in this session, "
            "so the result was kept and `broadcastTo` is 0."
        ),
    )


class HealthResponse(BaseModel):
    """Result of ``GET /health``."""

    model_config = ConfigDict(extra="ignore")

    status: str = "ok"
    service: str
    version: str
    environment: str
    sessions: int = 0
    websocketClients: int = 0
    engines: Dict[str, str] = Field(default_factory=dict)
    credentialsConfigured: Dict[str, bool] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def unknown_fields(payload: Dict[str, Any], model: type[BaseModel]) -> List[str]:
    """Return payload keys that are not part of ``model``'s contract.

    Unknown fields are ignored by the models (so a teammate adding a field
    cannot break the live demo), but the backend logs them so contract drift
    stays visible.
    """
    known = set(model.model_fields.keys())
    return sorted(key for key in payload.keys() if key not in known)
