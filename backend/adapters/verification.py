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
from typing import Any, Dict, List, Optional

import asyncio

from backend.logging_config import get_logger
from backend.schemas import ClaimEvent, VerificationEvent, Verdict

logger = get_logger("verification")

#: Internal ``verification`` verdict -> external wire verdict.
VERDICT_TO_WIRE: Dict[str, Verdict] = {
    "True": Verdict.TRUE,
    "False": Verdict.FALSE,
    "Unverifiable": Verdict.UNVERIFIABLE,
    "Ambiguous": Verdict.AMBIGUOUS,
}

#: External wire verdict -> internal ``verification`` verdict.
WIRE_TO_VERDICT: Dict[str, str] = {
    Verdict.TRUE.value: "True",
    Verdict.FALSE.value: "False",
    Verdict.UNVERIFIABLE.value: "Unverifiable",
    Verdict.AMBIGUOUS.value: "Ambiguous",
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


def to_wire_sources(sources: Any) -> List[Dict[str, Any]]:
    """Normalise the internal ``sources`` list onto the backend wire shape.

    The bridge is the only place that knows the two representations differ, so
    an engine that does not produce the field at all, or produces it as
    ``None``, still yields ``[]`` rather than failing the whole verification.
    Only entries carrying a non-empty string ``url`` survive: a source that
    cannot be linked is not something to put in front of a user.
    """
    if not sources or not isinstance(sources, (list, tuple)):
        return []

    wire_sources: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in sources:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        normalised = url.strip()
        if normalised in seen:
            continue
        seen.add(normalised)

        title = entry.get("title")
        snippet = entry.get("snippet")
        wire_sources.append(
            {
                "url": normalised,
                "title": title.strip() if isinstance(title, str) and title.strip() else None,
                "snippet": snippet.strip()
                if isinstance(snippet, str) and snippet.strip()
                else None,
            }
        )
    return wire_sources


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
            # `source` is still authoritative for existing consumers; `sources`
            # is the additive, backward-compatible extension.
            source=internal.source,
            sources=to_wire_sources(getattr(internal, "sources", None)),
        )


class CachedVerificationEngine(VerificationEngine):
    """Read-through cache in front of a real verification engine.

    A claim already verified recently is answered from the persistent store
    instead of re-running the search provider, which is both cheaper and one
    less source of rate limiting. Identity fields are always rebound from the
    incoming claim, so a cached verdict never leaks another session's
    ``claimId`` or ``sessionId``.

    Correctness guards
    ------------------
    * The cache is only ever constructed around a **strict** engine. That is the
      single configuration in which the rule-based fallback extractor cannot
      run, so a hardcoded fact cannot enter the store.
    * On any store failure the lookup returns ``None`` and retrieval proceeds,
      so a database outage degrades to live verification instead of failing.
    * The verdict, reason, source and confidence are replayed verbatim. Nothing
      is synthesised: a miss simply performs the real retrieval.
    """

    name = "cached-verification-engine"

    def __init__(
        self,
        inner: VerificationEngine,
        store: Any,
        *,
        provider_name: str = "tavily",
    ) -> None:
        self._inner = inner
        self._store = store
        self._provider_name = provider_name

    @property
    def inner_name(self) -> str:
        return self._inner.name

    async def verify(self, claim: ClaimEvent) -> VerificationEvent:
        from backend.persistence.store import normalize_claim_key

        claim_key = normalize_claim_key(claim.claim)

        cached = await self._store.get_cached_verification(claim_key)
        if cached is not None:
            logger.debug(
                "Serving claim %s from the persistent cache (provider %s).",
                claim.claimId,
                cached.provider or "unknown",
            )
            return VerificationEvent(
                type="verification",
                claimId=claim.claimId,
                sessionId=claim.sessionId,
                speaker=claim.speaker,
                timestamp=claim.timestamp,
                verdict=cached.verdict,
                reason=cached.reason,
                source=cached.source,
                confidence=cached.confidence,
                fromCache=True,
            )

        verification = await self._inner.verify(claim)

        await self._store.put_cached_verification(
            claim_key=claim_key,
            verdict=verification.verdict,
            reason=verification.reason,
            source=verification.source,
            confidence=verification.confidence,
            provider=self._provider_name,
            session_id=claim.sessionId,
        )
        return verification


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
