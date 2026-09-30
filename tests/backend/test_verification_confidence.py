"""Regression tests for the ``VerificationEvent.confidence`` crash.

Production failure
------------------
``AttributeError: 'VerificationEvent' object has no attribute 'confidence'``.

Commit ``6595eb1`` added ``sources`` to
:class:`backend.schemas.VerificationEvent` and, in the same hunk, deleted the
``confidence`` and ``fromCache`` fields that the persistence layer had been
added with. Two consumers still read them:

* :meth:`backend.adapters.verification.CachedVerificationEngine.verify`, which
  writes the verdict to ``verification_cache`` -- this runs inside the router's
  ``try`` around ``verify()``, so the AttributeError was converted into a
  ``VERIFICATION_FAILED`` error event and surfaced on the dashboard for every
  single claim;
* :meth:`backend.persistence.store.SupabaseStore.record_verification`, which
  writes the ``session_verifications`` history row.

Ownership of the value
----------------------
Confidence in this system is **evidence**, not verdict. The retrieval provider
scores each source, the ``verification`` package carries that score on
:class:`verification.models.EvidenceItem`, and the checker produces no
confidence of its own. So the honest mapping is: the provider's score travels
with its citation, and the event-level ``confidence`` is the score of the lead
ranked source. It is ``None`` -- never a default, a guess or an average -- when
the provider supplied no score or nothing was citable.

These tests pin all of that, and pin that the pipeline no longer raises.
"""

from typing import Any, Dict, List, Optional

import pytest
from pydantic import ValidationError

from backend.adapters.verification import (
    CachedVerificationEngine,
    VerificationServiceEngine,
    to_wire_sources,
    verdict_confidence,
)
from backend.persistence.store import CachedVerification, SupabaseStore
from backend.schemas import ClaimEvent, ContractVerificationEvent, Verdict
from verification.models import EvidenceItem, VerdictType
from verification.service import VerificationService


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


def _claim(claim_text: str = "India won the 2011 Cricket World Cup.") -> ClaimEvent:
    return ClaimEvent(
        type="claim",
        claimId="c1",
        sessionId="s1",
        speaker="Speaker 1",
        claim=claim_text,
        timestamp=1.0,
    )


class _Retriever:
    """Returns a fixed evidence list, standing in for the Tavily retriever."""

    def __init__(self, evidence: List[EvidenceItem]) -> None:
        self._evidence = evidence
        self.queries: List[str] = []

    def retrieve(self, query, max_results=3):
        self.queries.append(query)
        return list(self._evidence)


class _RecordingStore:
    """Minimal in-memory PersistenceStore double."""

    def __init__(self, cached: Optional[CachedVerification] = None) -> None:
        self._cached = cached
        self.writes: List[Dict[str, Any]] = []
        self.gets: List[str] = []

    async def get_cached_verification(self, claim_key: str):
        self.gets.append(claim_key)
        return self._cached

    async def put_cached_verification(self, **kwargs: Any) -> None:
        self.writes.append(kwargs)


def _evidence(url: str, snippet: str, **kwargs) -> EvidenceItem:
    return EvidenceItem(snippet=snippet, source_url=url, **kwargs)


class _StubPool:
    """Minimal ``asyncpg`` pool double that records the SQL it is handed.

    Stands in for both the pool and the connection, which is all
    ``SupabaseStore`` ever asks of them.
    """

    def __init__(self) -> None:
        self.executed: List[tuple] = []

    def acquire(self) -> "_StubAcquire":
        return _StubAcquire(self)

    async def execute(self, query, *args) -> None:
        self.executed.append((query, args))


class _StubAcquire:
    def __init__(self, conn: _StubPool) -> None:
        self._conn = conn

    async def __aenter__(self) -> _StubPool:
        return self._conn

    async def __aexit__(self, *exc_info) -> bool:
        return False


# ---------------------------------------------------------------------------
# 1. The exact production failure
# ---------------------------------------------------------------------------


async def test_cached_engine_passes_a_verification_event_without_confidence() -> None:
    """The crashing call, verbatim: cache write must not raise.

    Before the fix this raised
    ``AttributeError: 'VerificationEvent' object has no attribute 'confidence'``
    for every claim, which the router reported as ``VERIFICATION_FAILED``.
    """
    store = _RecordingStore()
    inner = VerificationServiceEngine(
        service=VerificationService(
            retriever=_Retriever(
                [
                    _evidence(
                        "https://espncricinfo.com/final",
                        "India won the 2011 ICC Cricket World Cup, defeating Sri Lanka.",
                        title="2011 Final",
                        stance="supports",
                        confidence=0.97,
                    )
                ]
            )
        )
    )

    event = await CachedVerificationEngine(inner, store).verify(_claim())

    assert event.verdict is Verdict.TRUE
    assert event.source == "https://espncricinfo.com/final"
    assert len(store.writes) == 1
    assert store.writes[0]["verdict"] is Verdict.TRUE
    assert store.writes[0]["reason"] == event.reason
    assert store.writes[0]["source"] == event.source


async def test_cached_engine_writes_the_providers_own_score() -> None:
    """The stored confidence is the lead source's real provider score."""
    store = _RecordingStore()
    inner = VerificationServiceEngine(
        service=VerificationService(
            retriever=_Retriever(
                [
                    _evidence(
                        "https://icc-cricket.com/archive",
                        "India defeated Sri Lanka to win the 2011 World Cup.",
                        stance="supports",
                        confidence=0.81,
                    )
                ]
            )
        )
    )

    event = await CachedVerificationEngine(inner, store).verify(_claim())

    assert event.confidence == pytest.approx(0.81)
    assert store.writes[0]["confidence"] == pytest.approx(0.81)


async def test_supabase_history_write_accepts_the_event() -> None:
    """``record_verification`` must not raise on a pipeline event either.

    Driven through a stub pool so the real SQL is executed against a recorder,
    which is the only way to prove the ``confidence`` column is populated
    rather than silently skipped.
    """
    pool = _StubPool()
    store = SupabaseStore("postgresql://unused")
    store._pool = pool

    event = await VerificationServiceEngine(
        service=VerificationService(
            retriever=_Retriever(
                [
                    _evidence(
                        "https://reuters.com/world/2011-final",
                        "India beat Sri Lanka by 89 runs in the 2011 final.",
                        stance="supports",
                        confidence=0.88,
                    )
                ]
            )
        )
    ).verify(_claim())

    await store.record_verification(event, from_cache=event.fromCache)

    assert len(pool.executed) == 1
    query, args = pool.executed[0]
    assert "confidence" in query
    # args: claimId, sessionId, verdict, reason, source, confidence, from_cache
    assert args[5] == pytest.approx(0.88)
    assert args[6] is False


# ---------------------------------------------------------------------------
# 2. Confidence belongs to the evidence
# ---------------------------------------------------------------------------


async def test_confidence_is_the_lead_ranked_source_score() -> None:
    """The event score matches the source published as ``source``."""
    inner = VerificationServiceEngine(
        service=VerificationService(
            retriever=_Retriever(
                [
                    # Lower score first, so the lead source is the second entry.
                    _evidence(
                        "https://weak.example.com/a", "Weak.", confidence=0.40
                    ),
                    _evidence(
                        "https://strong.example.com/b", "Strong.", confidence=0.93
                    ),
                ]
            )
        )
    )

    event = await inner.verify(_claim())

    assert event.source == "https://strong.example.com/b"
    assert event.sources[0]["url"] == event.source
    assert event.sources[0]["confidence"] == pytest.approx(0.93)
    assert event.confidence == pytest.approx(0.93)


async def test_confidence_is_none_rather_than_invented() -> None:
    """No evidence, no confidence. The checker never invents one."""
    inner = VerificationServiceEngine(
        service=VerificationService(retriever=_Retriever([]))
    )

    event = await inner.verify(_claim())

    assert event.verdict is Verdict.UNVERIFIABLE
    assert event.sources == []
    assert event.confidence is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "0.9",
        True,
        float("nan"),
        float("inf"),
        1.4,
        -0.2,
    ],
)
def test_unusable_scores_are_reported_as_absent(raw) -> None:
    """A score the provider did not really supply is dropped, not coerced."""
    wire = to_wire_sources([{"url": "https://a.example.com/1", "confidence": raw}])
    assert wire[0]["confidence"] is None
    assert verdict_confidence(wire) is None


def test_verdict_confidence_of_no_sources_is_none() -> None:
    assert verdict_confidence([]) is None
    assert verdict_confidence(to_wire_sources(None)) is None


async def test_source_scores_survive_the_wire_unchanged() -> None:
    """Per-source confidence is evidence metadata and is carried through."""
    wire = to_wire_sources(
        [
            {"url": "https://a.example.com/1", "title": "A", "confidence": 0.9},
            {"url": "https://a.example.com/1", "title": "dupe", "confidence": 0.1},
            {"url": "https://b.example.com/2", "confidence": 0.4},
        ]
    )
    assert [entry["url"] for entry in wire] == [
        "https://a.example.com/1",
        "https://b.example.com/2",
    ]
    assert [entry["confidence"] for entry in wire] == [0.9, 0.4]


# ---------------------------------------------------------------------------
# 3. Cache replay
# ---------------------------------------------------------------------------


async def test_cache_replay_returns_stored_score_and_marks_provenance() -> None:
    """A hit replays the stored verdict verbatim and flags ``fromCache``."""
    store = _RecordingStore(
        cached=CachedVerification(
            claim_key="india won the 2011 cricket world cup",
            verdict=Verdict.FALSE,
            reason="The available source reports a different figure.",
            source="https://cached.example.com/source",
            confidence=0.74,
            provider="tavily",
        )
    )

    class _NeverUsed:
        name = "must-not-run"

        async def verify(self, claim):  # pragma: no cover - must not be reached
            raise AssertionError("cache hit must not re-run retrieval")

    event = await CachedVerificationEngine(_NeverUsed(), store).verify(_claim())

    assert event.verdict is Verdict.FALSE
    assert event.reason == "The available source reports a different figure."
    assert event.source == "https://cached.example.com/source"
    assert event.confidence == pytest.approx(0.74)
    assert event.fromCache is True
    assert store.writes == []


async def test_cache_replay_of_a_null_confidence_stays_null() -> None:
    """A verdict stored without a score is replayed without one."""
    store = _RecordingStore(
        cached=CachedVerification(
            claim_key="k",
            verdict=Verdict.UNVERIFIABLE,
            reason="No evidence.",
            source="No source available",
            confidence=None,
            provider="tavily",
        )
    )

    class _NeverUsed:
        name = "must-not-run"

        async def verify(self, claim):  # pragma: no cover - must not be reached
            raise AssertionError("cache hit must not re-run retrieval")

    event = await CachedVerificationEngine(_NeverUsed(), store).verify(_claim())

    assert event.confidence is None
    assert event.fromCache is True


# ---------------------------------------------------------------------------
# 4. Verdict set is preserved
# ---------------------------------------------------------------------------


def test_every_backend_verdict_is_accepted_on_the_wire() -> None:
    """``AMBIGUOUS`` must reach the frontend, not fail the whole verification.

    The allowed set is derived from :class:`backend.schemas.Verdict`, so it
    cannot drift from the enum again.
    """
    for verdict in Verdict:
        built = ContractVerificationEvent(
            type="verification",
            claimId="c1",
            sessionId="s1",
            timestamp=1.0,
            verdict=verdict,
            reason="Because.",
            source="https://example.com/source",
        )
        assert built.verdict is verdict


def test_lowercase_verdicts_are_still_rejected() -> None:
    with pytest.raises(ValidationError):
        ContractVerificationEvent(
            type="verification",
            claimId="c1",
            sessionId="s1",
            timestamp=1.0,
            verdict="true",  # type: ignore[arg-type]
            reason="Because.",
            source="https://example.com/source",
        )


async def test_ambiguous_verdict_survives_the_whole_pipeline() -> None:
    """An ambiguous claim is reported, not turned into a failed check."""

    class _Service:
        def verify_claim(self, payload):
            class _Result:
                verdict = VerdictType.AMBIGUOUS
                reason = "Sources indicate multiple valid interpretations."
                source = "https://ambiguous.example.com/a"

            return _Result()

    event = await VerificationServiceEngine(service=_Service()).verify(
        _claim("The company's growth depends on the market.")
    )

    assert event.verdict is Verdict.AMBIGUOUS
    assert event.to_wire()["verdict"] == "AMBIGUOUS"


# ---------------------------------------------------------------------------
# 5. Evidence is preserved
# ---------------------------------------------------------------------------


async def test_reason_and_all_sources_survive_the_pipeline() -> None:
    """The fix must not cost the multi-source evidence added alongside it."""
    inner = VerificationServiceEngine(
        service=VerificationService(
            retriever=_Retriever(
                [
                    _evidence(
                        "https://espncricinfo.com/final",
                        "India won the 2011 ICC Cricket World Cup.",
                        title="2011 Final",
                        stance="supports",
                        confidence=0.99,
                    ),
                    _evidence(
                        "https://icc-cricket.com/archive",
                        "India defeated Sri Lanka in the 2011 final.",
                        title="ICC Archive",
                        stance="supports",
                        confidence=0.95,
                    ),
                ]
            )
        )
    )

    event = await CachedVerificationEngine(inner, _RecordingStore()).verify(_claim())

    assert event.reason
    assert event.source == "https://espncricinfo.com/final"
    assert [entry["url"] for entry in event.sources] == [
        "https://espncricinfo.com/final",
        "https://icc-cricket.com/archive",
    ]
    assert event.to_wire()["confidence"] == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# 6. The production wiring, end to end
# ---------------------------------------------------------------------------


class _CapturingSockets:
    """Stands in for the WebSocketManager and records what a client would see."""

    def __init__(self) -> None:
        self.events: List[Any] = []

    async def send_to_session(self, session_id, event) -> int:
        self.events.append(event)
        return 1


class _StaticClaimEngine:
    """One claim, so the transcript path is exercised without an LLM."""

    uses_transcript_buffer = False

    async def extract_claims(self, transcript):
        return [
            ClaimEvent(
                type="claim",
                claimId="claim_001",
                sessionId=transcript.sessionId,
                speaker=transcript.speaker,
                timestamp=transcript.timestamp,
                claim="India won the 2011 Cricket World Cup.",
                claimType="historical_fact",
            )
        ]


async def test_router_reports_a_verdict_instead_of_a_verification_failure() -> None:
    """The dashboard path: transcript -> claim -> verification, with the cache.

    This is the composition that failed in production. The router caught the
    AttributeError and turned it into a ``VERIFICATION_FAILED`` error event, so
    the assertion that matters is that no such event is emitted and a real
    verdict reaches the socket.
    """
    from backend.router import EventRouter
    from backend.schemas import ErrorCode, TranscriptEvent
    from backend.session_manager import SessionManager

    sockets = _CapturingSockets()
    store = SupabaseStore("postgresql://unused")
    store._pool = _StubPool()

    router = EventRouter(
        session_manager=SessionManager(),
        websocket_manager=sockets,
        claim_engine=_StaticClaimEngine(),
        verification_engine=CachedVerificationEngine(
            VerificationServiceEngine(
                service=VerificationService(
                    retriever=_Retriever(
                        [
                            _evidence(
                                "https://espncricinfo.com/final",
                                "India won the 2011 ICC Cricket World Cup.",
                                title="2011 Final",
                                stance="supports",
                                confidence=0.96,
                            )
                        ]
                    )
                )
            ),
            store,
        ),
        store=store,
    )

    session = await router.sessions.create()
    counts, claims, verifications = await router.handle_transcript(
        TranscriptEvent(
            type="transcript",
            sessionId=session.sessionId,
            speaker="Speaker 1",
            text="India won the 2011 Cricket World Cup.",
            timestamp=10.0,
            isFinal=True,
        )
    )

    assert counts.errors == 0
    assert counts.verifications == 1
    assert claims[0].claimId == verifications[0].claimId
    assert verifications[0].verdict is Verdict.TRUE
    assert verifications[0].confidence == pytest.approx(0.96)

    errors = [
        event
        for event in sockets.events
        if getattr(event, "type", None) == "error"
    ]
    assert errors == []
    assert all(
        "confidence" not in str(getattr(event, "detail", "") or "")
        for event in errors
    ), "the AttributeError must not resurface as a VERIFICATION_FAILED detail"
    assert ErrorCode.VERIFICATION_FAILED.value not in {
        getattr(event, "code", None) for event in errors
    }

# ---------------------------------------------------------------------------
# 8. The provider's exact number, and no default in its absence
# ---------------------------------------------------------------------------


def test_evidence_item_does_not_default_confidence_to_one() -> None:
    """The internal model must not invent a confidence of 1.0.

    ``EvidenceItem.confidence`` used to be ``float = Field(default=1.0)``. That
    made every evidence item with no provider score indistinguishable from a
    maximally relevant one, and the fabricated 1.0 then flowed all the way to
    the dashboard as if Tavily had returned it. Absent must stay absent.
    """
    item = EvidenceItem(snippet="A retrieved sentence.", source_url="https://a.example.com/1")

    assert item.confidence is None
    assert "confidence" in EvidenceItem.model_fields
    assert EvidenceItem.model_fields["confidence"].default is None


@pytest.mark.parametrize("provider_score", [0.9137, 0.4219])
async def test_provider_score_survives_the_pipeline_bit_for_bit(provider_score: float) -> None:
    """Tavily's number arrives as the same number, never rounded or rescaled.

    Exact equality on purpose: ``pytest.approx`` would tolerate exactly the kind
    of drift this guards against. The score is checked at the provider
    boundary, on the wire, and at the event level.
    """
    from verification.retriever import WebSearchRetriever

    parsed = WebSearchRetriever.parse_provider_score(provider_score)
    assert parsed == provider_score

    evidence = WebSearchRetriever.parse_search_results(
        [
            {
                "url": "https://source.example.com/a",
                "title": "A retrieved page",
                "content": "A retrieved sentence that says something checkable.",
                "score": provider_score,
            }
        ]
    )
    assert evidence[0].confidence == provider_score

    inner = VerificationServiceEngine(
        service=VerificationService(retriever=_Retriever(evidence))
    )

    event = await inner.verify(_claim())

    assert event.confidence == provider_score
    assert event.sources[0]["confidence"] == provider_score
    assert event.to_wire()["confidence"] == provider_score


async def test_absent_provider_score_stays_absent_end_to_end() -> None:
    """A provider that sent no score yields ``None`` the whole way through.

    This is the Tavily-omits-``score`` case: the evidence is still real and
    still cited, it simply carries no confidence anywhere in the system.
    """
    from verification.retriever import WebSearchRetriever

    evidence = WebSearchRetriever.parse_search_results(
        [
            {
                "url": "https://source.example.com/a",
                "title": "A retrieved page",
                "content": "A retrieved sentence that says something checkable.",
            }
        ]
    )
    assert evidence[0].confidence is None

    inner = VerificationServiceEngine(
        service=VerificationService(retriever=_Retriever(evidence))
    )

    event = await inner.verify(_claim())

    assert event.confidence is None
    assert event.sources[0]["confidence"] is None
    assert event.to_wire()["confidence"] is None
