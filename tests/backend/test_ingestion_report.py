"""Tests for what a video ingestion reports back.

:func:`backend.routes.ingestion._run_pipeline_on_source` pushes every transcript
segment through the unchanged claim/verification pipeline and then collects what
came out, so the response can carry per-claim evidence and a scorecard.

These tests drive that function directly with a stand-in router. The point is the
aggregation itself, which is where a long video's results could quietly go wrong:
a restated claim counted twice, a failed check reported as a verdict, or the
whole run collapsing into a summary that no longer matches the claims beneath it.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend.ingestion.models import ProcessingStatus
from backend.routes.ingestion import _run_pipeline_on_source
from backend.schemas import ClaimEvent, PipelineCounts, TranscriptEvent, VerificationEvent, Verdict


# ---------------------------------------------------------------------------
# Stand-ins for the pipeline
# ---------------------------------------------------------------------------


class _FakeSessions:
    """Enough of SessionManager to answer 'was this claim id already verified?'."""

    def __init__(self, stored: Optional[Dict[str, VerificationEvent]] = None) -> None:
        self._stored: Dict[str, VerificationEvent] = dict(stored or {})

    async def get_verification(
        self, session_id: str, claim_id: str
    ) -> Optional[VerificationEvent]:
        return self._stored.get(claim_id)


class _FakeRouter:
    """Replays a scripted outcome per transcript segment.

    Each script entry is ``(claims, verifications)``. A claim with no matching
    verification models a check that did not complete, which is how a retrieval
    failure reaches this function.
    """

    def __init__(self, script: List[Tuple[List[ClaimEvent], List[VerificationEvent]]]) -> None:
        self._script = script
        self._calls = 0
        self.sessions = _FakeSessions()

    async def handle_transcript(
        self, transcript: TranscriptEvent
    ) -> Tuple[PipelineCounts, List[ClaimEvent], List[VerificationEvent]]:
        if not self._script:
            return PipelineCounts(), [], []
        claims, verifications = self._script[min(self._calls, len(self._script) - 1)]
        self._calls += 1
        return (
            PipelineCounts(claims=len(claims), verifications=len(verifications)),
            claims,
            verifications,
        )


class _FakeApp:
    def __init__(self, router: _FakeRouter) -> None:
        self.state = _FakeState(router)


class _FakeState:
    def __init__(self, router: _FakeRouter) -> None:
        self.router = router
        self.session_manager = None


class _FakeRequest:
    def __init__(self, router: _FakeRouter) -> None:
        self.app = _FakeApp(router)


class _FakeSource:
    def __init__(self, segments: List[Dict[str, Any]]) -> None:
        self.source_id = "src1"
        self.status = ProcessingStatus.COMPLETED
        self.transcript = " ".join(segment["text"] for segment in segments)
        self.transcript_segments = segments
        self.duration_seconds = 120.0


def _segment(text: str, start: float, speaker: str = "Speaker 1") -> Dict[str, Any]:
    return {"text": text, "start": start, "end": start + 2.0, "speaker": speaker}


def _claim(claim_id: str, text: str, ts: float) -> ClaimEvent:
    return ClaimEvent(
        type="claim",
        claimId=claim_id,
        sessionId="s1",
        speaker="Speaker 1",
        claim=text,
        timestamp=ts,
    )


def _verification(claim_id: str, verdict: Verdict, ts: float) -> VerificationEvent:
    return VerificationEvent(
        type="verification",
        claimId=claim_id,
        sessionId="s1",
        speaker="Speaker 1",
        timestamp=ts,
        verdict=verdict,
        reason="Because.",
        source="https://example.com/a",
    )


async def _run(
    script: List[Tuple[List[ClaimEvent], List[VerificationEvent]]],
    segments: List[Dict[str, Any]],
):
    return await _run_pipeline_on_source(_FakeRequest(_FakeRouter(script)), "s1", _FakeSource(segments))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_carries_each_claim_with_its_verdict() -> None:
    """The per-claim detail a scorecard alone cannot give: who said what, when."""
    script = [
        (
            [_claim("c1", "Water boils at 100C.", 4.0)],
            [_verification("c1", Verdict.TRUE, 4.0)],
        ),
        (
            [_claim("c2", "The moon is cheese.", 40.0)],
            [_verification("c2", Verdict.FALSE, 40.0)],
        ),
    ]

    response = await _run(script, [_segment("Water boils at 100C.", 4.0), _segment("The moon is cheese.", 40.0)])

    assert [result.claim_id for result in response.claims] == ["c1", "c2"]
    assert response.claims[0].verdict is Verdict.TRUE
    assert response.claims[1].verdict is Verdict.FALSE

    # Timestamps survive to the response, so the moment can be located.
    assert response.claims[1].timestamp == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_aggregate_counters_are_unchanged_by_the_new_fields() -> None:
    """The existing response fields keep their meaning.

    The new fields are purely additive, so a consumer reading only the original
    counters sees exactly what it saw before this feature.
    """
    script = [([_claim("c1", "A claim.", 1.0)], [_verification("c1", Verdict.TRUE, 1.0)])]

    response = await _run(script, [_segment("A claim.", 1.0)])

    assert response.claims_extracted == 1
    assert response.verifications_completed == 1
    assert response.source_id == "src1"
    assert response.status is ProcessingStatus.COMPLETED
    assert response.duration_seconds == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_a_failed_check_is_reported_as_failed_not_as_unverifiable() -> None:
    """A retrieval failure must not enter the scorecard as a verdict.

    The claim is extracted but produces no verification, which is exactly what a
    provider timeout or a missing credential looks like to this function.
    """
    script = [([_claim("c1", "A claim.", 1.0)], [])]

    response = await _run(script, [_segment("A claim.", 1.0)])

    assert len(response.claims) == 1
    assert response.claims[0].status.value == "failed"
    assert response.claims[0].verdict is None

    assert response.scorecard is not None
    assert response.scorecard.checked_claims == 0
    assert response.scorecard.failed_claims == 1
    assert response.scorecard.true_ratio is None


@pytest.mark.asyncio
async def test_a_repeated_claim_id_is_counted_once() -> None:
    """A restated claim must not be weighted twice.

    In a long video the same claim recurs, often verbatim. The pipeline skips
    re-verifying a claim id it has already seen, so without this guard the second
    sighting would land in the results with no verdict and be recorded as a
    failure -- inflating the video's failure count for a claim that was in fact
    checked.
    """
    first = _claim("c1", "Water freezes at 0C.", 10.0)
    verification = _verification("c1", Verdict.TRUE, 10.0)
    # The same claim id appears again later in the video, and the pipeline
    # correctly returns no new verification for it.
    repeat = _claim("c1", "Water freezes at 0C.", 90.0)
    script = [([first], [verification]), ([repeat], [])]

    response = await _run(
        script,
        [_segment("Water freezes at 0C.", 10.0), _segment("Water freezes at 0C.", 90.0)],
    )

    assert len(response.claims) == 1
    assert response.claims[0].verdict is Verdict.TRUE

    assert response.scorecard is not None
    assert response.scorecard.total_claims == 1
    assert response.scorecard.checked_claims == 1
    assert response.scorecard.failed_claims == 0


@pytest.mark.asyncio
async def test_a_restated_claim_is_reported_once_even_with_a_new_claim_id() -> None:
    """Deduplication must not depend on which claim engine is wired in.

    The strict engine collapses identical claim text during extraction, but the
    report is also reached with engines that do not. When the same sentence is
    extracted twice it still arrives as one claim here, so the scorecard cannot
    be inflated -- or tilted toward whatever a speaker restated most -- by an
    engine's extraction behaviour.
    """
    script = [
        (
            [_claim("c1", "Water freezes at 0C.", 10.0)],
            [_verification("c1", Verdict.TRUE, 10.0)],
        ),
        (
            [_claim("c2", "Water freezes at 0C.", 90.0)],
            [_verification("c2", Verdict.TRUE, 90.0)],
        ),
    ]

    response = await _run(
        script,
        [_segment("Water freezes at 0C.", 10.0), _segment("Water freezes at 0C.", 90.0)],
    )

    # The pipeline saw both; the report counts the assertion once.
    assert response.claims_extracted == 2
    assert len(response.claims) == 1

    assert response.scorecard is not None
    assert response.scorecard.total_claims == 1
    assert response.scorecard.true_claims == 1
    assert response.scorecard.true_ratio == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_deduplication_ignores_case_and_punctuation() -> None:
    """Restating a claim in different words is still the same assertion.

    Reuses the same normalisation the fact cache uses to decide two claims are
    the same, so the report and the cache agree on what "the same claim" means.
    """
    script = [
        ([_claim("c1", "Water freezes at 0C.", 10.0)], [_verification("c1", Verdict.TRUE, 10.0)]),
        ([_claim("c2", "water freezes at 0c!", 90.0)], [_verification("c2", Verdict.TRUE, 90.0)]),
    ]

    response = await _run(
        script,
        [_segment("Water freezes at 0C.", 10.0), _segment("Water freezes at 0C.", 90.0)],
    )

    assert len(response.claims) == 1


@pytest.mark.asyncio
async def test_distinct_claims_are_not_merged() -> None:
    """Deduplication must not swallow genuinely different assertions."""
    script = [
        ([_claim("c1", "Water freezes at 0C.", 10.0)], [_verification("c1", Verdict.TRUE, 10.0)]),
        ([_claim("c2", "Water boils at 100C.", 20.0)], [_verification("c2", Verdict.FALSE, 20.0)]),
    ]

    response = await _run(
        script, [_segment("Water freezes at 0C.", 10.0), _segment("Water boils at 100C.", 20.0)]
    )

    assert len(response.claims) == 2


@pytest.mark.asyncio
async def test_a_later_verified_duplicate_replaces_an_earlier_failure() -> None:
    """The same claim failing once and succeeding later was still checked.

    Keeping the first occurrence would report a failure the system itself later
    resolved, and would hide evidence that exists.
    """
    script = [
        ([_claim("c1", "Water freezes at 0C.", 10.0)], []),
        ([_claim("c2", "Water freezes at 0C.", 90.0)], [_verification("c2", Verdict.TRUE, 90.0)]),
    ]

    response = await _run(
        script,
        [_segment("Water freezes at 0C.", 10.0), _segment("Water freezes at 0C.", 90.0)],
    )

    assert len(response.claims) == 1
    assert response.claims[0].status.value == "verified"
    assert response.claims[0].verdict is Verdict.TRUE

    assert response.scorecard is not None
    assert response.scorecard.failed_claims == 0
    assert response.scorecard.checked_claims == 1


@pytest.mark.asyncio
async def test_a_later_failure_does_not_replace_an_earlier_verdict() -> None:
    """A verdict already reached is not downgraded by a later repeat."""
    script = [
        ([_claim("c1", "Water freezes at 0C.", 10.0)], [_verification("c1", Verdict.TRUE, 10.0)]),
        ([_claim("c2", "Water freezes at 0C.", 90.0)], []),
    ]

    response = await _run(
        script,
        [_segment("Water freezes at 0C.", 10.0), _segment("Water freezes at 0C.", 90.0)],
    )

    assert len(response.claims) == 1
    assert response.claims[0].verdict is Verdict.TRUE
    assert response.scorecard is not None
    assert response.scorecard.failed_claims == 0


@pytest.mark.asyncio
async def test_deduplication_keeps_the_first_occurrence_timestamp() -> None:
    """The moment reported is where the claim was first made."""
    script = [
        ([_claim("c1", "Water freezes at 0C.", 10.0)], [_verification("c1", Verdict.TRUE, 10.0)]),
        ([_claim("c2", "Water freezes at 0C.", 90.0)], [_verification("c2", Verdict.TRUE, 90.0)]),
    ]

    response = await _run(
        script,
        [_segment("Water freezes at 0C.", 10.0), _segment("Water freezes at 0C.", 90.0)],
    )

    assert response.claims[0].timestamp == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_scorecard_counts_match_the_returned_claims() -> None:
    """The summary must describe exactly the results shipped beside it.

    A scorecard that disagreed with its own claim list would be worse than no
    scorecard, because it would look authoritative.
    """
    script = [
        ([_claim("c1", "A.", 1.0)], [_verification("c1", Verdict.TRUE, 1.0)]),
        ([_claim("c2", "B.", 2.0)], [_verification("c2", Verdict.FALSE, 2.0)]),
        ([_claim("c3", "C.", 3.0)], []),
    ]

    response = await _run(
        script, [_segment("A.", 1.0), _segment("B.", 2.0), _segment("C.", 3.0)]
    )

    assert response.scorecard is not None
    assert response.scorecard.total_claims == len(response.claims)
    assert response.scorecard.checked_claims == sum(
        1 for result in response.claims if result.verdict is not None
    )
    assert response.scorecard.true_claims == 1
    assert response.scorecard.false_claims == 1
    assert response.scorecard.failed_claims == 1


@pytest.mark.asyncio
async def test_a_long_video_scales_without_losing_or_reordering_results() -> None:
    """A long video processes segment by segment, with no cap on how many.

    The concern with a very long recording is that something upstream silently
    truncates it. Every segment must reach the pipeline and every claim must come
    back, in the order it was spoken, or the scorecard describes a video nobody
    watched.
    """
    segment_count = 500
    segments = [_segment(f"Statement {index}.", float(index)) for index in range(segment_count)]
    script = [
        (
            [_claim(f"c{index}", f"Statement {index}.", float(index))],
            [_verification(f"c{index}", Verdict.TRUE, float(index))],
        )
        for index in range(segment_count)
    ]

    response = await _run(script, segments)

    assert len(response.claims) == segment_count
    assert response.claims_extracted == segment_count
    assert response.verifications_completed == segment_count

    # Order is preserved, so timestamps read as a walk through the video.
    assert [result.timestamp for result in response.claims] == [
        pytest.approx(float(index)) for index in range(segment_count)
    ]

    assert response.scorecard is not None
    assert response.scorecard.total_claims == segment_count
    assert response.scorecard.coverage_ratio == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_every_segment_timestamps_its_claims_from_the_transcript() -> None:
    """Claim timestamps come from the transcript segment, not the wall clock."""
    script = [([_claim("c1", "A.", 123.0)], [_verification("c1", Verdict.TRUE, 123.0)])]

    response = await _run(script, [_segment("A.", 123.0)])

    assert response.claims[0].timestamp == pytest.approx(123.0)


@pytest.mark.asyncio
async def test_no_claims_yields_a_scorecard_with_no_percentages() -> None:
    """A video with no checkable claims reports nothing, rather than a clean sheet.

    Zero claims and zero accuracy are very different facts, and only one of them
    is a finding about the video.
    """
    response = await _run([], [_segment("Just some chatter.", 1.0)])

    assert response.claims == []
    assert response.scorecard is not None
    assert response.scorecard.total_claims == 0
    assert response.scorecard.coverage_ratio is None
    assert response.scorecard.true_ratio is None
