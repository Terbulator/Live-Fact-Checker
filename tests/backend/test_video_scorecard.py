"""Tests for the video scorecard and the evidence trail behind a cached verdict.

Two things are pinned here, both about the same underlying rule: **a number must
mean something that was actually measured.**

The scorecard
-------------
A video run reports how it went. The failure mode this guards against is a
scorecard that looks authoritative while reporting a finding nobody made. The
specific ways that happens are each tested below:

* a retrieval failure being counted as an ``UNVERIFIABLE`` verdict, which turns a
  broken search integration into a statistic about the video's truthfulness;
* an empty denominator being reported as ``0%``, which asserts that nothing in a
  video was true when in fact nothing about it could be checked;
* repeated claims being counted more than once, which over-weights whatever the
  speaker restated most.

The cache audit trail
---------------------
A verdict replayed from the persistent cache must arrive with the same evidence a
live retrieval would have produced. Before migration 002 only the verdict, reason,
source and confidence were stored, so a cached answer showed no supporting
statement and no citations -- the same claim then looked better evidenced the
first time it was asked than the second, which reads as a change in the facts.
"""

from typing import Any, Dict, List, Optional

import pytest

from backend.adapters.verification import CachedVerificationEngine, VerificationEngine
from backend.persistence.store import (
    CachedVerification,
    SupabaseStore,
    decode_sources,
    encode_sources,
)
from backend.schemas import ClaimEvent, VerificationEvent, Verdict
from backend.scorecard import (
    ClaimCheckStatus,
    VideoClaimResult,
    build_claim_result,
    build_scorecard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _claim(claim_id: str = "c1", text: str = "A claim.", ts: float = 1.0) -> ClaimEvent:
    return ClaimEvent(
        type="claim",
        claimId=claim_id,
        sessionId="s1",
        speaker="Speaker 1",
        claim=text,
        timestamp=ts,
    )


def _verification(
    claim_id: str = "c1",
    verdict: Verdict = Verdict.TRUE,
    ts: float = 1.0,
    **overrides: Any,
) -> VerificationEvent:
    payload: Dict[str, Any] = {
        "type": "verification",
        "claimId": claim_id,
        "sessionId": "s1",
        "speaker": "Speaker 1",
        "timestamp": ts,
        "verdict": verdict,
        "reason": "Because.",
        "source": "https://example.com/a",
    }
    payload.update(overrides)
    return VerificationEvent(**payload)


def _verified(verdict: Verdict, claim_id: str = "c1") -> VideoClaimResult:
    return build_claim_result(_claim(claim_id), _verification(claim_id, verdict))


def _failed(claim_id: str = "c1") -> VideoClaimResult:
    return build_claim_result(_claim(claim_id), None)


# ---------------------------------------------------------------------------
# Scorecard: counts and determinism
# ---------------------------------------------------------------------------


def test_scorecard_counts_each_verdict_exactly_once() -> None:
    results = [
        _verified(Verdict.TRUE, "c1"),
        _verified(Verdict.FALSE, "c2"),
        _verified(Verdict.FALSE, "c3"),
        _verified(Verdict.UNVERIFIABLE, "c4"),
        _verified(Verdict.AMBIGUOUS, "c5"),
    ]

    scorecard = build_scorecard(results)

    assert scorecard.total_claims == 5
    assert scorecard.checked_claims == 5
    assert scorecard.failed_claims == 0
    assert scorecard.true_claims == 1
    assert scorecard.false_claims == 2
    assert scorecard.unverifiable_claims == 1
    assert scorecard.ambiguous_claims == 1


def test_scorecard_is_deterministic_for_the_same_results() -> None:
    """Same input, same output, every time.

    Determinism matters because the scorecard is what a reviewer reads as the
    result. A distribution that shifted between two renders of the same run would
    make the number untrustworthy in a way nobody could diagnose.
    """
    results = [
        _verified(Verdict.TRUE, "c1"),
        _verified(Verdict.FALSE, "c2"),
        _failed("c3"),
    ]

    first = build_scorecard(results).model_dump(mode="json")
    second = build_scorecard(results).model_dump(mode="json")

    assert first == second


def test_scorecard_ratios_are_exact_divisions_of_the_counts() -> None:
    results = [
        _verified(Verdict.TRUE, "c1"),
        _verified(Verdict.TRUE, "c2"),
        _verified(Verdict.FALSE, "c3"),
        _verified(Verdict.UNVERIFIABLE, "c4"),
    ]

    scorecard = build_scorecard(results)

    assert scorecard.true_ratio == pytest.approx(2 / 4)
    assert scorecard.false_ratio == pytest.approx(1 / 4)
    assert scorecard.unverifiable_ratio == pytest.approx(1 / 4)
    assert scorecard.ambiguous_ratio == pytest.approx(0 / 4)


# ---------------------------------------------------------------------------
# Scorecard: a failed check is not a verdict
# ---------------------------------------------------------------------------


def test_failed_claim_is_excluded_from_every_verdict_ratio() -> None:
    """The core separation.

    A retrieval failure means no verdict exists. Folding it into the distribution
    would quietly convert a broken integration into a measurement of the video's
    truthfulness, so it is counted on its own and shares no ratio.
    """
    results = [
        _verified(Verdict.TRUE, "c1"),
        _verified(Verdict.FALSE, "c2"),
        _failed("c3"),
        _failed("c4"),
    ]

    scorecard = build_scorecard(results)

    assert scorecard.total_claims == 4
    assert scorecard.checked_claims == 2
    assert scorecard.failed_claims == 2

    # Ratios describe the two claims that actually got a verdict...
    assert scorecard.true_ratio == pytest.approx(0.5)
    assert scorecard.false_ratio == pytest.approx(0.5)

    # ...and the failures appear in none of them.
    assert sum(
        ratio
        for ratio in (
            scorecard.true_ratio,
            scorecard.false_ratio,
            scorecard.ambiguous_ratio,
            scorecard.unverifiable_ratio,
        )
        if ratio is not None
    ) == pytest.approx(1.0)

    # They are visible through coverage instead.
    assert scorecard.coverage_ratio == pytest.approx(0.5)


def test_retrieval_failure_is_not_recorded_as_an_unverifiable_verdict() -> None:
    """A failed check carries no verdict at all.

    Presenting it as ``UNVERIFIABLE`` would be a specific false claim: that the
    system searched, found nothing and concluded the claim could not be settled.
    Nothing of the sort happened, so the verdict field stays empty.
    """
    result = _failed("c1")

    assert result.status is ClaimCheckStatus.FAILED
    assert result.verdict is None
    assert result.reason is None
    assert result.source is None
    assert result.supporting_statement is None
    assert result.confidence is None
    assert result.sources == []


def test_failed_claim_explains_itself() -> None:
    """A reader must be able to tell a failure from an empty result."""
    result = _failed("c1")

    assert result.error is not None
    assert result.error.strip() != ""


def test_failed_claim_keeps_the_speaker_and_timestamp() -> None:
    """A claim that could not be checked is still a claim that was made.

    The moment and the speaker are known regardless of the verdict, so a
    failure stays locatable in the video rather than becoming a gap.
    """
    claim = ClaimEvent(
        type="claim",
        claimId="c1",
        sessionId="s1",
        speaker="Moderator",
        claim="Something specific.",
        timestamp=91.5,
    )

    result = build_claim_result(claim, None)

    assert result.speaker == "Moderator"
    assert result.timestamp == pytest.approx(91.5)


def test_verified_and_failed_counts_stay_consistent() -> None:
    """Internal consistency, so the scorecard cannot contradict itself."""
    results = [
        _verified(Verdict.TRUE, "c1"),
        _verified(Verdict.FALSE, "c2"),
        _verified(Verdict.AMBIGUOUS, "c3"),
        _verified(Verdict.UNVERIFIABLE, "c4"),
        _failed("c5"),
    ]

    scorecard = build_scorecard(results)

    assert (
        scorecard.true_claims
        + scorecard.false_claims
        + scorecard.ambiguous_claims
        + scorecard.unverifiable_claims
        == scorecard.checked_claims
    )
    assert scorecard.checked_claims + scorecard.failed_claims == scorecard.total_claims


def test_result_marked_verified_without_a_verdict_counts_as_failed() -> None:
    """Inconsistent input must not enter a measured ratio.

    A result claiming to be verified while carrying no verdict is untrustworthy
    input. Counting it as checked would put an unmeasured claim into the
    distribution, so it is counted as a failure instead.
    """
    inconsistent = VideoClaimResult(
        claim_id="c1",
        claim="A claim.",
        status=ClaimCheckStatus.VERIFIED,
        verdict=None,
    )

    scorecard = build_scorecard([inconsistent])

    assert scorecard.checked_claims == 0
    assert scorecard.failed_claims == 1
    assert scorecard.true_ratio is None


# ---------------------------------------------------------------------------
# Scorecard: an empty denominator has no percentage
# ---------------------------------------------------------------------------


def test_no_claims_yields_no_ratios() -> None:
    scorecard = build_scorecard([])

    assert scorecard.total_claims == 0
    assert scorecard.checked_claims == 0
    assert scorecard.coverage_ratio is None
    assert scorecard.true_ratio is None
    assert scorecard.false_ratio is None


def test_nothing_verified_yields_no_verdict_percentages() -> None:
    """The most important negative case.

    Every check failing must not report an accuracy. There is no distribution to
    describe, so every ratio is ``None`` -- not ``0.0``, which would state that
    nothing in the video was true.
    """
    results = [_failed("c1"), _failed("c2"), _failed("c3")]

    scorecard = build_scorecard(results)

    assert scorecard.checked_claims == 0
    assert scorecard.failed_claims == 3

    assert scorecard.true_ratio is None
    assert scorecard.false_ratio is None
    assert scorecard.ambiguous_ratio is None
    assert scorecard.unverifiable_ratio is None

    # Coverage is still exact: it is a real measurement of what happened.
    assert scorecard.coverage_ratio == pytest.approx(0.0)


def test_a_verdict_count_of_zero_still_reports_a_real_zero_share() -> None:
    """Once something *was* checked, a genuine zero is a real measurement.

    This is the counterpart to the rule above: with a non-zero denominator, zero
    is a fact about the run and must be reported as ``0.0``, not suppressed.
    """
    results = [_verified(Verdict.FALSE, "c1"), _verified(Verdict.FALSE, "c2")]

    scorecard = build_scorecard(results)

    assert scorecard.true_claims == 0
    assert scorecard.true_ratio == pytest.approx(0.0)
    assert scorecard.false_ratio == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Per-claim result: evidence is carried through unchanged
# ---------------------------------------------------------------------------


def test_result_carries_the_full_evidence_trail() -> None:
    verification = _verification(
        "c1",
        Verdict.FALSE,
        supportingStatement="example.com states: “The figure was 3, not 5.”",
        sources=[
            {
                "url": "https://example.com/a",
                "title": "A",
                "snippet": "The figure was 3, not 5.",
                "confidence": 0.8,
            }
        ],
        confidence=0.8,
        fromCache=True,
    )

    result = build_claim_result(_claim("c1"), verification)

    assert result.status is ClaimCheckStatus.VERIFIED
    assert result.verdict is Verdict.FALSE
    assert result.supporting_statement == verification.supportingStatement
    assert result.sources == verification.sources
    assert result.confidence == pytest.approx(0.8)
    assert result.from_cache is True


def test_result_copies_sources_rather_than_sharing_the_event_list() -> None:
    """A caller mutating a result must not reach back into the event.

    The same ``VerificationEvent`` is also broadcast over the WebSocket. Sharing
    the list would let one consumer's edit leak into every other reader.
    """
    verification = _verification("c1", Verdict.TRUE, sources=[{"url": "https://a.test"}])

    result = build_claim_result(_claim("c1"), verification)
    result.sources[0]["url"] = "https://tampered.test"

    assert verification.sources[0]["url"] == "https://a.test"


def test_result_reports_no_supporting_statement_when_evidence_was_absent() -> None:
    """Absence stays absence.

    ``UNVERIFIABLE`` with no citable evidence has nothing to explain, and
    inventing a sentence to fill the field would fabricate the finding.
    """
    verification = _verification("c1", Verdict.UNVERIFIABLE, supportingStatement=None)

    result = build_claim_result(_claim("c1"), verification)

    assert result.verdict is Verdict.UNVERIFIABLE
    assert result.supporting_statement is None


def test_result_reports_no_confidence_when_the_provider_gave_none() -> None:
    """No provider score means no confidence, never a default."""
    result = build_claim_result(_claim("c1"), _verification("c1", Verdict.TRUE, confidence=None))

    assert result.confidence is None


# ---------------------------------------------------------------------------
# Cache: the evidence trail survives a replay
# ---------------------------------------------------------------------------


class _InnerEngine(VerificationEngine):
    """A real engine, so the cache is exercised around something genuine."""

    name = "inner"

    def __init__(self, verification: VerificationEvent) -> None:
        self.verification = verification
        self.calls = 0

    async def verify(self, claim: ClaimEvent) -> VerificationEvent:
        self.calls += 1
        return self.verification.model_copy(update={"claimId": claim.claimId})


class _MemoryStore:
    """A store that records what it was given, standing in for Supabase."""

    enabled = True

    def __init__(self) -> None:
        self.row: Optional[CachedVerification] = None

    async def get_cached_verification(self, claim_key: str) -> Optional[CachedVerification]:
        return self.row

    async def put_cached_verification(self, **kwargs: Any) -> None:
        self.row = CachedVerification(
            claim_key=kwargs["claim_key"],
            verdict=kwargs["verdict"],
            reason=kwargs["reason"],
            source=kwargs["source"],
            confidence=kwargs["confidence"],
            provider=kwargs["provider"],
            supporting_statement=kwargs.get("supporting_statement"),
            sources=list(kwargs.get("sources") or []),
        )


@pytest.mark.asyncio
async def test_cache_stores_the_supporting_statement_and_sources() -> None:
    """The write path must persist the whole evidence trail.

    Without these the replay below would have nothing to return, which is the
    defect migration 002 exists to fix.
    """
    store = _MemoryStore()
    sources = [
        {"url": "https://example.com/a", "title": "A", "snippet": "s", "confidence": 0.9}
    ]
    inner = _InnerEngine(
        _verification(
            "c1",
            Verdict.TRUE,
            supportingStatement="example.com states: “Confirmed.”",
            sources=sources,
            confidence=0.9,
        )
    )
    engine = CachedVerificationEngine(inner, store)

    await engine.verify(_claim("c1"))

    assert store.row is not None
    assert store.row.supporting_statement == "example.com states: “Confirmed.”"
    assert store.row.sources == sources


@pytest.mark.asyncio
async def test_cache_replay_preserves_the_supporting_statement_and_sources() -> None:
    """A cached verdict must be as auditable as a live one.

    This is the regression: replaying used to return the verdict alone, so the
    same claim showed its evidence on first retrieval and hid it on every
    subsequent one. That reads as a change in the underlying facts when it is
    only a change in caching.
    """
    sources = [
        {"url": "https://example.com/a", "title": "A", "snippet": "s", "confidence": 0.9}
    ]
    store = _MemoryStore()
    inner = _InnerEngine(_verification("c1", Verdict.TRUE))
    engine = CachedVerificationEngine(inner, store)

    live = await engine.verify(_claim("c1"))
    replay = await engine.verify(_claim("c1"))

    # The inner engine ran exactly once; the second call was served from cache.
    assert inner.calls == 1
    assert replay.fromCache is True
    assert replay.verdict == live.verdict
    assert replay.reason == live.reason
    assert replay.source == live.source
    assert replay.confidence == live.confidence
    assert replay.supportingStatement == live.supportingStatement
    assert replay.sources == live.sources


@pytest.mark.asyncio
async def test_cache_replay_does_not_invent_evidence_absent_at_write_time() -> None:
    """A row with no statement must replay with no statement.

    The tempting shortcut is to synthesise one from ``reason`` on the way out. That
    would make every cached claim look evidenced, including the ones that never
    were.
    """
    store = _MemoryStore()
    inner = _InnerEngine(
        _verification("c1", Verdict.UNVERIFIABLE, supportingStatement=None, sources=[])
    )
    engine = CachedVerificationEngine(inner, store)

    await engine.verify(_claim("c1"))
    replay = await engine.verify(_claim("c1"))

    assert replay.supportingStatement is None
    assert replay.sources == []


@pytest.mark.asyncio
async def test_cache_replay_binds_identity_from_the_incoming_claim() -> None:
    """A cached verdict must not leak another session's ids."""
    store = _MemoryStore()
    inner = _InnerEngine(_verification("other", Verdict.TRUE))
    engine = CachedVerificationEngine(inner, store)

    await engine.verify(_claim("c1"))

    other_session_claim = ClaimEvent(
        type="claim",
        claimId="c1",
        sessionId="s2",
        speaker="Speaker 2",
        claim="A claim.",
        timestamp=5.0,
    )
    replay = await engine.verify(other_session_claim)

    assert replay.claimId == "c1"
    assert replay.sessionId == "s2"
    assert replay.timestamp == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# JSON codec for the sources column
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored",
    [
        "[]",
        '[{"url": "https://a.test"}]',
        [{"url": "https://a.test"}],
        None,
        "",
        "not json",
        "[1, 2, 3]",
        '{"url": "https://a.test"}',
    ],
)
def test_decode_sources_tolerates_whatever_the_column_holds(stored: Any) -> None:
    """A row the codec cannot read is a cache miss, never a failure.

    These are all shapes a ``jsonb`` column, a hand-edited row or a pre-migration
    database could present. None may raise, because a cache read sits inside the
    verification path.
    """
    decoded = decode_sources(stored)

    assert isinstance(decoded, list)
    assert all(isinstance(entry, dict) for entry in decoded)


def test_decode_sources_returns_the_stored_citations() -> None:
    stored = '[{"url": "https://a.test", "title": "A", "snippet": "s", "confidence": 0.5}]'

    assert decode_sources(stored) == [
        {"url": "https://a.test", "title": "A", "snippet": "s", "confidence": 0.5}
    ]


@pytest.mark.parametrize("sources", [None, [], "not a list"])
def test_encode_sources_always_yields_valid_json(sources: Any) -> None:
    encoded = encode_sources(sources)

    assert encoded == "[]"
    decode_sources(encoded)  # round-trips


def test_encode_sources_round_trips_citations() -> None:
    sources: List[Dict[str, Any]] = [
        {"url": "https://a.test", "title": "A", "snippet": "s", "confidence": 0.5}
    ]

    assert decode_sources(encode_sources(sources)) == sources


def test_store_without_a_pool_is_a_no_op_and_never_raises() -> None:
    """Persistence stays an optimisation: with no pool, nothing happens."""

    async def _noop() -> None:
        store = SupabaseStore("postgresql://unused")
        assert await store.get_cached_verification("k") is None
        await store.put_cached_verification(
            claim_key="k",
            verdict=Verdict.TRUE,
            reason="r",
            source="s",
            confidence=None,
            provider="tavily",
            session_id="s1",
        )

    import asyncio

    asyncio.run(_noop())
