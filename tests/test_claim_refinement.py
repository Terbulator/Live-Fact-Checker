"""Tests for the additive claim-intelligence layer and its wiring.

Covers :mod:`backend.adapters.claim_refinement` plus the composition of the
three pre-verification P1 features:

* compound claims reach the existing pipeline as independent claims
* only ``FACTUAL_CLAIM`` text is fact-checked
* an identical claim is checked once per session
* a factual claim is passed through byte for byte
* the wrapped engine reports the inner engine's name and strictness
* the layer is opt-in and defaults to leaving an engine untouched when disabled
"""

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claim_engine import ClaimEngine, ClaimEngineError
from backend.adapters.claim_refinement import (
    RefinedClaimEngine,
    apply_claim_refinement,
)
from backend.config import Settings
from backend.main import create_app
from backend.schemas import ClaimEvent, TranscriptEvent


def _transcript(text: str, session_id: str = "session_001") -> TranscriptEvent:
    return TranscriptEvent(
        type="transcript",
        sessionId=session_id,
        speaker="Speaker 1",
        text=text,
        timestamp=1.0,
        isFinal=True,
    )


class _FixedClaimEngine(ClaimEngine):
    """Returns a fixed set of claims, as a real engine would after extraction.

    ``claim_texts`` may be a single list, or a list of lists to return a
    different batch on each successive call.
    """

    name = "fixed-claim-engine"

    def __init__(self, claim_texts, strict: bool = False) -> None:
        batches = claim_texts if claim_texts and isinstance(claim_texts[0], list) else [claim_texts]
        self._batches = [list(batch) for batch in batches]
        self.strict = strict
        self.calls = 0

    async def extract_claims(self, transcript: TranscriptEvent):
        batch = self._batches[min(self.calls, len(self._batches) - 1)]
        self.calls += 1
        return [
            ClaimEvent(
                type="claim",
                claimId=f"{transcript.sessionId}_claim_{index:03d}",
                sessionId=transcript.sessionId,
                speaker=transcript.speaker,
                timestamp=transcript.timestamp,
                claim=text,
            )
            for index, text in enumerate(batch, start=1)
        ]


class _ExplodingClaimEngine(ClaimEngine):
    name = "exploding-claim-engine"

    async def extract_claims(self, transcript: TranscriptEvent):
        raise ClaimEngineError("The gateway is unreachable.")


# ---------------------------------------------------------------------------
# 1. A factual claim is passed through untouched
# ---------------------------------------------------------------------------


async def test_an_ordinary_claim_reaches_the_pipeline_unchanged() -> None:
    """The regression guard that matters most: the existing path is intact."""
    inner = _FixedClaimEngine(["India won the 2011 Cricket World Cup."])
    refined = RefinedClaimEngine(inner)

    claims = await refined.extract_claims(_transcript("India won the 2011 World Cup."))

    assert len(claims) == 1
    assert claims[0].claim == "India won the 2011 Cricket World Cup."
    assert claims[0].claimId == "session_001_claim_001"
    assert claims[0].speaker == "Speaker 1"
    assert claims[0].timestamp == 1.0
    assert claims[0].sessionId == "session_001"


# ---------------------------------------------------------------------------
# 2. Compound claims
# ---------------------------------------------------------------------------


async def test_a_compound_claim_becomes_independent_claims() -> None:
    inner = _FixedClaimEngine(
        ["India won the 2011 World Cup and Sachin Tendulkar scored 482 runs."]
    )
    refined = RefinedClaimEngine(inner)

    claims = await refined.extract_claims(_transcript("Something was said."))

    assert [claim.claim for claim in claims] == [
        "India won the 2011 World Cup.",
        "Sachin Tendulkar scored 482 runs.",
    ]


async def test_split_claims_get_distinct_ids_and_keep_their_context() -> None:
    """Two claims must never collide, or one would suppress the other."""
    inner = _FixedClaimEngine(
        ["India won the 2011 World Cup and Tendulkar scored 482 runs."]
    )
    refined = RefinedClaimEngine(inner)

    claims = await refined.extract_claims(_transcript("Something was said."))

    assert len({claim.claimId for claim in claims}) == 2
    for claim in claims:
        assert claim.speaker == "Speaker 1"
        assert claim.timestamp == 1.0
        assert claim.sessionId == "session_001"


async def test_split_ids_are_deterministic() -> None:
    """The same sentence always produces the same ids."""
    text = "India won the 2011 World Cup and Tendulkar scored 482 runs."
    first = await RefinedClaimEngine(_FixedClaimEngine([text])).extract_claims(
        _transcript("Said.")
    )
    second = await RefinedClaimEngine(_FixedClaimEngine([text])).extract_claims(
        _transcript("Said.")
    )
    assert [c.claimId for c in first] == [c.claimId for c in second]


# ---------------------------------------------------------------------------
# 3. Classification gating
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Who won the 2011 Cricket World Cup?",
        "I think India is the best cricket team.",
        "Please open the presentation.",
        "Hello there, good morning!",
    ],
)
async def test_non_factual_text_is_not_fact_checked(text: str) -> None:
    refined = RefinedClaimEngine(_FixedClaimEngine([text]))
    assert await refined.extract_claims(_transcript(text)) == []


async def test_a_question_never_reaches_verification() -> None:
    refined = RefinedClaimEngine(_FixedClaimEngine(["Did India win the 2011 final?"]))
    assert await refined.extract_claims(_transcript("Did India win?")) == []


async def test_a_claim_greeted_with_small_talk_is_still_checked() -> None:
    """Greeting noise in front of a claim must not swallow the claim."""
    refined = RefinedClaimEngine(_FixedClaimEngine(["India won the 2011 World Cup."]))
    claims = await refined.extract_claims(
        _transcript("Hi everyone, India won the 2011 World Cup.")
    )
    assert [claim.claim for claim in claims] == ["India won the 2011 World Cup."]


# ---------------------------------------------------------------------------
# 4. Duplicate protection
# ---------------------------------------------------------------------------


async def test_the_same_claim_is_only_emitted_once_per_session() -> None:
    refined = RefinedClaimEngine(
        _FixedClaimEngine(["India won the 2011 Cricket World Cup."])
    )
    first = await refined.extract_claims(_transcript("India won it."))
    second = await refined.extract_claims(_transcript("India won it."))
    assert len(first) == 1
    assert second == []


async def test_an_extended_claim_is_still_emitted() -> None:
    """A restatement that adds detail is a different claim, not a repeat."""
    refined = RefinedClaimEngine(
        _FixedClaimEngine(
            [
                ["Ireland won the match."],
                ["Ireland won the match by 5 wickets."],
            ]
        )
    )
    await refined.extract_claims(_transcript("Ireland won."))
    again = await refined.extract_claims(_transcript("Ireland won by 5 wickets."))
    assert [claim.claim for claim in again] == ["Ireland won the match by 5 wickets."]


async def test_repeats_inside_one_response_are_collapsed() -> None:
    refined = RefinedClaimEngine(
        _FixedClaimEngine(
            [
                "India won the 2011 Cricket World Cup.",
                "India won the 2011 Cricket World Cup.",
            ]
        )
    )
    claims = await refined.extract_claims(_transcript("India won."))
    assert len(claims) == 1


async def test_two_sessions_do_not_suppress_each_other() -> None:
    refined = RefinedClaimEngine(
        _FixedClaimEngine(["India won the 2011 Cricket World Cup."])
    )
    first = await refined.extract_claims(_transcript("x", session_id="session_a"))
    second = await refined.extract_claims(_transcript("x", session_id="session_b"))
    assert len(first) == 1
    assert len(second) == 1


# ---------------------------------------------------------------------------
# 5. Pass-through and failure behaviour
# ---------------------------------------------------------------------------


async def test_an_empty_inner_result_stays_empty() -> None:
    refined = RefinedClaimEngine(_FixedClaimEngine([]))
    assert await refined.extract_claims(_transcript("Nothing checkable here.")) == []


async def test_the_inner_engine_is_always_delegated_to() -> None:
    inner = _FixedClaimEngine(["India won the 2011 Cricket World Cup."])
    await RefinedClaimEngine(inner).extract_claims(_transcript("x"))
    assert inner.calls == 1


async def test_an_inner_error_propagates_unchanged() -> None:
    refined = RefinedClaimEngine(_ExplodingClaimEngine())
    with pytest.raises(ClaimEngineError):
        await refined.extract_claims(_transcript("x"))


async def test_a_broken_stage_fails_open_rather_than_dropping_the_claim() -> None:
    """A bug in the new layers must never silently swallow a real claim."""

    class _BrokenSplitter:
        def split(self, text):
            raise RuntimeError("splitter exploded")

    class _BrokenClassifier:
        def classify(self, text):
            raise RuntimeError("classifier exploded")

    refined = RefinedClaimEngine(
        _FixedClaimEngine(["India won the 2011 Cricket World Cup."]),
        splitter=_BrokenSplitter(),
        classifier=_BrokenClassifier(),
    )
    claims = await refined.extract_claims(_transcript("x"))
    assert [claim.claim for claim in claims] == ["India won the 2011 Cricket World Cup."]


# ---------------------------------------------------------------------------
# 6. The wrapper is transparent
# ---------------------------------------------------------------------------


async def test_the_wrapped_engine_name_is_reported_unchanged() -> None:
    """Health output and the wiring tests read ``engine.name``."""
    refined = RefinedClaimEngine(_FixedClaimEngine([]))
    assert refined.name == "fixed-claim-engine"


async def test_strictness_is_mirrored() -> None:
    """Strictness is what makes the persistent cache safe to use."""
    assert RefinedClaimEngine(_FixedClaimEngine([], strict=True)).strict is True
    assert RefinedClaimEngine(_FixedClaimEngine([], strict=False)).strict is False


def test_the_inner_engine_remains_reachable() -> None:
    inner = _FixedClaimEngine([])
    assert RefinedClaimEngine(inner).inner is inner


# ---------------------------------------------------------------------------
# 7. The layer is opt-in
# ---------------------------------------------------------------------------


def test_disabled_leaves_the_engine_untouched() -> None:
    inner = _FixedClaimEngine([])
    assert apply_claim_refinement(inner, enabled=False) is inner


def test_enabled_wraps_the_engine() -> None:
    inner = _FixedClaimEngine([])
    wrapped = apply_claim_refinement(inner, enabled=True)
    assert isinstance(wrapped, RefinedClaimEngine)
    assert wrapped.inner is inner


def test_wrapping_is_not_applied_twice() -> None:
    once = apply_claim_refinement(_FixedClaimEngine([]))
    assert apply_claim_refinement(once) is once


# ---------------------------------------------------------------------------
# 8. Application wiring
# ---------------------------------------------------------------------------


def test_health_still_reports_the_inner_engine_name() -> None:
    """The layer must be invisible in the existing health contract."""
    from backend.mocks.mock_stream import MockClaimEngine

    settings = Settings(environment="test", use_mock_engines=True, log_level="WARNING")
    app = create_app(settings=settings, claim_engine=MockClaimEngine())
    with TestClient(app) as client:
        engines = client.get("/health").json()["engines"]
    assert engines["claimEngine"] == "mock-claim-engine"


def test_disabling_the_layer_restores_the_pre_refinement_engine() -> None:
    from backend.mocks.mock_stream import MockClaimEngine

    settings = Settings(
        environment="test",
        use_mock_engines=True,
        log_level="WARNING",
        claim_refinement_enabled=False,
    )
    app = create_app(settings=settings, claim_engine=MockClaimEngine())
    assert isinstance(app.state.claim_engine, MockClaimEngine)


def test_claim_refinement_is_off_by_default() -> None:
    """The regression guard for the additive-only rule.

    Claim classification, compound splitting and duplicate suppression all
    *remove* claims from what the existing pipeline receives. That is the
    intended behaviour once the feature is adopted, but it must never happen
    by default to a system that is already working.
    """
    assert Settings().claim_refinement_enabled is False


def test_the_default_claim_engine_is_the_unwrapped_one() -> None:
    from backend.mocks.mock_stream import MockClaimEngine

    settings = Settings(environment="test", use_mock_engines=True, log_level="WARNING")
    app = create_app(settings=settings, claim_engine=MockClaimEngine())
    assert not isinstance(app.state.claim_engine, RefinedClaimEngine)
    assert isinstance(app.state.claim_engine, MockClaimEngine)


def test_opting_in_activates_the_layer() -> None:
    from backend.mocks.mock_stream import MockClaimEngine

    settings = Settings(
        environment="test",
        use_mock_engines=True,
        log_level="WARNING",
        claim_refinement_enabled=True,
    )
    app = create_app(settings=settings, claim_engine=MockClaimEngine())
    assert isinstance(app.state.claim_engine, RefinedClaimEngine)


async def test_the_opt_in_layer_still_passes_factual_claims_through_unchanged() -> None:
    """Opting in must not disturb the claims that were always checked."""
    from backend.mocks.mock_stream import MockClaimEngine

    settings = Settings(
        environment="test",
        use_mock_engines=True,
        log_level="WARNING",
        claim_refinement_enabled=True,
    )
    app = create_app(settings=settings, claim_engine=MockClaimEngine())
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        response = client.post(
            "/events/transcript",
            json={
                "type": "transcript",
                "sessionId": session,
                "speaker": "Speaker 1",
                "text": "India won the 2011 Cricket World Cup.",
                "timestamp": 12.4,
                "isFinal": True,
            },
        )
    payload = response.json()
    assert [claim["claim"] for claim in payload["claims"]] == [
        "India won the 2011 Cricket World Cup."
    ]
    assert payload["counts"]["verifications"] == 1


def test_persistence_still_sees_the_raw_strict_engine() -> None:
    """The store is built from the raw engine, before any wrapping.

    Strictness is the single property that makes caching safe, so if the
    wrapper were applied before `build_store`, persistence would silently
    switch off. The inner engine stays reachable and still reports strict.
    """
    from backend.adapters.claim_engine import LLMClaimEngine
    from backend.main import _is_strict_claim_engine
    from backend.mocks.mock_stream import MockClaimEngine

    settings = Settings(
        environment="test",
        use_mock_engines=True,
        log_level="WARNING",
        claim_refinement_enabled=True,
    )
    app = create_app(settings=settings, claim_engine=MockClaimEngine())

    # Wrapping happened, and the raw engine is what the store decision reads.
    assert isinstance(app.state.claim_engine, RefinedClaimEngine)
    assert _is_strict_claim_engine(app.state.claim_engine.inner) is False

    # An LLM engine stays strict through the wrapper, so the store's decision
    # is unaffected by the layer existing at all.
    wrapped = RefinedClaimEngine(LLMClaimEngine(settings, strict=True))
    assert wrapped.strict is True
    assert _is_strict_claim_engine(wrapped.inner) is True
