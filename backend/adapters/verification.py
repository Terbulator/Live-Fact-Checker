"""Verification adapter boundary.

The backend never performs evidence retrieval or reasoning. It defines the
interface Nayanika's verification engine must satisfy, and ships an explicit
bridge to the existing ``verification`` package so the pipeline already works
today without a search provider.

Verdict translation
-------------------
The backend wire format is uppercase ``TRUE`` / ``FALSE`` / ``UNVERIFIABLE``.
The existing ``verification.models.VerdictType`` is ``True`` / ``False`` /
``Unverifiable``. :data:`VERDICT_TO_WIRE` and :data:`WIRE_TO_VERDICT` are the
only place that conversion happens, so ``verification/models.py`` is never
edited.

``sessionId``
-------------
The internal ``verification`` models do not know about ``sessionId``, and
``extra="forbid"`` would reject it. The bridge therefore sends **only** the
fields the internal model accepts and re-attaches ``sessionId`` (plus
``speaker``, ``timestamp``) to the outgoing backend event. The backend keeps
ownership of ``sessionId`` in both directions.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import asyncio

from backend.schemas import ClaimEvent, VerificationEvent, Verdict

#: Internal ``verification`` verdict -> external wire verdict.
VERDICT_TO_WIRE: Dict[str, Verdict] = {
    "True": Verdict.TRUE,
    "False": Verdict.FALSE,
    "Unverifiable": Verdict.UNVERIFIABLE,
}

#: External wire verdict -> internal ``verification`` verdict.
WIRE_TO_VERDICT: Dict[str, str] = {
    Verdict.TRUE.value: "True",
    Verdict.FALSE.value: "False",
    Verdict.UNVERIFIABLE.value: "Unverifiable",
}


class VerificationEngineError(RuntimeError):
    """Raised when verification fails."""

    def __init__(self, message: str, claimId: Optional[str] = None) -> None:
        super().__init__(message)
        self.claimId = claimId


def to_wire_verdict(internal_verdict: object) -> Verdict:
    """Translate an internal ``verification`` verdict into the wire verdict.

    Raises:
        ValueError: if the internal verdict is not one of the three allowed
            values. The backend never guesses a verdict.
    """
    value = getattr(internal_verdict, "value", internal_verdict)
    try:
        return VERDICT_TO_WIRE[str(value)]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unsupported internal verdict: {value!r}") from exc


def to_internal_verdict(wire_verdict: object) -> str:
    """Translate a wire verdict into the internal ``verification`` value."""
    value = getattr(wire_verdict, "value", wire_verdict)
    try:
        return WIRE_TO_VERDICT[str(value)]
    except KeyError as exc:
        raise ValueError(f"Unsupported wire verdict: {value!r}") from exc


def to_internal_claim_payload(claim: ClaimEvent) -> Dict:
    """Reduce a backend claim event to the internal model's accepted fields.

    ``sessionId`` and ``claimType`` are dropped here on purpose: the internal
    model sets ``extra="forbid"`` and does not declare them.
    """
    return {
        "type": "claim",
        "claimId": claim.claimId,
        "speaker": claim.speaker or "Speaker 1",
        "claim": claim.claim,
        "timestamp": claim.timestamp,
    }


class VerificationEngine(ABC):
    """Interface between the backend and the verification module."""

    name: str = "verification-engine"

    @abstractmethod
    async def verify(self, claim: ClaimEvent) -> VerificationEvent:
        """Return the verdict, one-sentence reason and source for one claim.

        Args:
            claim: A validated backend claim event.

        Returns:
            A backend verification event carrying the **same** ``claimId`` and
            ``sessionId`` as the input claim.
        """
        raise NotImplementedError


class VerificationServiceEngine(VerificationEngine):
    """Bridge to the existing ``verification.VerificationService``.

    Runs the real, tested verification pipeline. The retriever is injected
    explicitly: real mode must reach a live search provider, never the offline
    ``MockRetriever``, so :func:`_default_verification_engine` builds it with
    ``use_mock=False``.

    Threading
    ---------
    ``verification`` is synchronous, and real retrieval performs blocking HTTP.
    Calling it directly from this coroutine would stall the event loop for the
    duration of the search, freezing WebSocket broadcasts for every session, so
    the call is dispatched to a worker thread. The contract is unchanged: the
    same verdict, reason, source and ordering.
    """

    name = "verification-service"

    def __init__(self, service: Optional[object] = None, retriever: Optional[object] = None) -> None:
        if service is None:
            from verification.service import VerificationService

            service = VerificationService(retriever=retriever)
        self._service = service

    async def verify(self, claim: ClaimEvent) -> VerificationEvent:
        """Run the internal pipeline and re-attach the backend-owned fields."""
        payload = to_internal_claim_payload(claim)
        try:
            internal = await asyncio.to_thread(self._service.verify_claim, payload)
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured error
            raise VerificationEngineError(
                f"Verification failed for claim {claim.claimId}: {exc}",
                claimId=claim.claimId,
            ) from exc

        return VerificationEvent(
            type="verification",
            claimId=claim.claimId,
            sessionId=claim.sessionId,
            speaker=claim.speaker,
            timestamp=claim.timestamp,
            verdict=to_wire_verdict(internal.verdict),
            reason=internal.reason,
            source=internal.source,
        )


class UnavailableVerificationEngine(VerificationEngine):
    """Placeholder used when no verification engine is wired in yet.

    Every call fails cleanly, so the backend emits a structured
    ``VERIFICATION_FAILED`` error event. Selected when ``USE_MOCK_ENGINES`` is
    false and Nayanika's engine has not been integrated; the existing
    ``verification`` package can be used instead by injecting
    :class:`VerificationServiceEngine`.
    """

    name = "unavailable-verification-engine"

    async def verify(self, claim: ClaimEvent) -> VerificationEvent:
        raise VerificationEngineError(
            "No verification engine is configured. Set USE_MOCK_ENGINES=true for "
            "the mock pipeline, or inject VerificationServiceEngine.",
            claimId=claim.claimId,
        )
