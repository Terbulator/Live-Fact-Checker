"""Tests for the P1 conflicting-evidence layer.

Covers :mod:`verification.conflict`:

* genuinely opposing credible evidence yields UNVERIFIABLE
* a conflict one side's credibility resolves leaves the verdict alone
* two snippets from one source are not a conflict
* normal TRUE / FALSE cases behave exactly as they already did
* a claim already found inconclusive is returned untouched
"""

import pytest

from backend.config import Settings
from backend.main import _default_verification_engine
from verification.checker import VerificationChecker
from verification.conflict import (
    ConflictAwareChecker,
    ConflictDetector,
    quantity_keys,
)
from verification.models import EvidenceItem, VerdictType
from verification.service import VerificationService


def _evidence(url: str, snippet: str, **kwargs) -> EvidenceItem:
    return EvidenceItem(snippet=snippet, source_url=url, **kwargs)


@pytest.fixture
def detector() -> ConflictDetector:
    return ConflictDetector()


@pytest.fixture
def checker() -> ConflictAwareChecker:
    return ConflictAwareChecker()


# ---------------------------------------------------------------------------
# 1. The headline case: credible evidence that disagrees
# ---------------------------------------------------------------------------


def test_two_sources_reporting_different_figures_conflict(checker) -> None:
    """The worked example: same subject, two incompatible numbers."""
    evidence = [
        _evidence(
            "https://sec.gov/annual-report",
            "The company sold two million units during the year.",
            title="Annual Report",
            confidence=0.92,
        ),
        _evidence(
            "https://reuters.com/market-report",
            "The company sold 1.4 million units during the year.",
            title="Market Report",
            confidence=0.89,
        ),
    ]
    verdict, reason, _ = checker.verify("The company sold two million units.", evidence)
    assert verdict is VerdictType.UNVERIFIABLE
    assert "disagree" in reason.lower()


def test_conflicting_sources_yield_unverifiable_through_the_service(checker) -> None:
    class _Retriever:
        def retrieve(self, query, max_results=3):
            return [
                _evidence(
                    "https://sec.gov/annual-report",
                    "The company sold two million units during the year.",
                    title="Annual Report",
                    confidence=0.95,
                ),
                _evidence(
                    "https://reuters.com/market-report",
                    "The company sold 1.4 million units during the year.",
                    title="Market Report",
                    confidence=0.92,
                ),
            ]

    result = VerificationService(
        retriever=_Retriever(), checker=checker
    ).verify_claim(
        {
            "type": "claim",
            "claimId": "c1",
            "speaker": "Speaker 1",
            "claim": "The company sold two million units.",
            "timestamp": 1.0,
        }
    )
    assert result.verdict is VerdictType.UNVERIFIABLE
    # The citations are still shown alongside the inconclusive verdict.
    assert len(result.sources) == 2
    assert result.source == result.sources[0]["url"]


def test_a_conflict_about_who_won_is_not_guessed_at(checker) -> None:
    """An honest limit, pinned so it cannot regress silently.

    Two sources can name different winners while agreeing on every figure the
    claim states. Distinguishing that needs to understand the sentence's
    structure, not its vocabulary, so this layer declines to guess -- and the
    claim keeps the verdict the existing checker already gave it. Adding
    semantic comparison is a future improvement, not something to fake here.
    """
    evidence = [
        _evidence(
            "https://espncricinfo.com/final",
            "India won the 2011 ICC Cricket World Cup, defeating Sri Lanka.",
            confidence=0.95,
        ),
        _evidence(
            "https://cricbuzz.com/archive",
            "Sri Lanka won the 2011 ICC Cricket World Cup final.",
            confidence=0.92,
        ),
    ]
    base = VerificationChecker().verify(
        "India won the 2011 ICC Cricket World Cup.", evidence
    )[0]
    verdict, _, _ = checker.verify(
        "India won the 2011 ICC Cricket World Cup.", evidence
    )
    assert verdict is base


def test_contradiction_wording_counts_as_a_refutation(detector) -> None:
    evidence = [
        _evidence(
            "https://a.example.com/one",
            "The Apollo 11 mission landed on the Moon in 1969.",
            confidence=0.90,
        ),
        _evidence(
            "https://b.example.com/two",
            "The Apollo 11 landing is a myth; it was never carried out.",
            confidence=0.88,
        ),
    ]
    report = detector.detect("Apollo 11 landed on the Moon in 1969.", evidence)
    assert report.has_conflict
    assert not report.resolved
    assert report.supporting_urls == ["https://a.example.com/one"]
    assert report.refuting_urls == ["https://b.example.com/two"]


def test_an_explicitly_disputed_source_is_a_conflict(detector) -> None:
    evidence = [
        _evidence(
            "https://a.example.com/report",
            "Internal memos schedule the product release for November 15.",
            stance="conflicting",
            confidence=0.80,
        ),
        _evidence(
            "https://b.example.com/analysis",
            "Analysts state the launch slipped to next year.",
            stance="conflicting",
            confidence=0.78,
        ),
    ]
    report = detector.detect("The product release date is November 15.", evidence)
    assert report.has_conflict


def test_the_conflict_reason_names_both_sides(checker) -> None:
    evidence = [
        _evidence(
            "https://a.example.com/one",
            "The company sold two million units during the year.",
            confidence=0.90,
        ),
        _evidence(
            "https://b.example.com/two",
            "The company sold 1.4 million units during the year.",
            confidence=0.88,
        ),
    ]
    _, reason, _ = checker.verify("The company sold two million units.", evidence)
    assert "two million units" in reason
    assert "1.4 million units" in reason


# ---------------------------------------------------------------------------
# 2. Resolution: a conflict that can be settled is not a conflict
# ---------------------------------------------------------------------------


def test_a_conflict_resolved_by_credibility_keeps_the_verdict(checker) -> None:
    """One dissenting low-quality snippet does not overturn strong evidence."""
    evidence = [
        _evidence(
            "https://sec.gov/annual-report",
            "The company sold two million units during the year.",
            title="Annual Report",
            confidence=0.99,
        ),
        _evidence(
            "https://randomblog.example.net/post",
            "I think the company sold some other amount, honestly not sure.",
            confidence=0.61,
        ),
    ]
    verdict, _, _ = checker.verify("The company sold two million units.", evidence)
    assert verdict is VerdictType.TRUE


def test_the_detector_reports_a_resolved_conflict_as_resolved(detector) -> None:
    evidence = [
        _evidence(
            "https://sec.gov/annual-report",
            "The company sold two million units during the year.",
            confidence=0.99,
        ),
        _evidence(
            "https://randomblog.example.net/post",
            "The company sold 1.4 million units during the year.",
            confidence=0.62,
        ),
    ]
    report = detector.detect("The company sold two million units.", evidence)
    assert not report.has_conflict
    assert report.resolved


# ---------------------------------------------------------------------------
# 3. Independence
# ---------------------------------------------------------------------------


def test_one_source_quoted_twice_is_not_a_conflict(detector) -> None:
    """Corroboration and contradiction must come from different sources."""
    evidence = [
        _evidence(
            "https://reuters.com/report",
            "The company sold two million units during the year.",
            confidence=0.90,
        ),
        _evidence(
            "https://www.reuters.com/report",
            "The company sold 1.4 million units during the year.",
            confidence=0.90,
        ),
    ]
    report = detector.detect("The company sold two million units.", evidence)
    assert not report.has_conflict


def test_evidence_that_is_merely_adjacent_does_not_conflict(detector) -> None:
    """A snippet about something else cannot contradict the claim."""
    evidence = [
        _evidence(
            "https://a.example.com/one",
            "The company sold two million units during the year.",
            confidence=0.90,
        ),
        _evidence(
            "https://b.example.com/two",
            "Unrelated commentary about the weather in Oslo.",
            confidence=0.90,
        ),
    ]
    report = detector.detect("The company sold two million units.", evidence)
    assert not report.has_conflict


def test_low_confidence_evidence_cannot_create_a_conflict(detector) -> None:
    evidence = [
        _evidence(
            "https://a.example.com/one",
            "The company sold two million units during the year.",
            confidence=0.90,
        ),
        _evidence(
            "https://b.example.com/two",
            "The company sold 1.4 million units during the year.",
            confidence=0.10,
        ),
    ]
    report = detector.detect("The company sold two million units.", evidence)
    assert not report.has_conflict


def test_a_single_source_cannot_conflict_with_itself(detector) -> None:
    evidence = [
        _evidence(
            "https://a.example.com/one",
            "The company sold two million units during the year.",
            confidence=0.90,
        )
    ]
    report = detector.detect("The company sold two million units.", evidence)
    assert not report.has_conflict


# ---------------------------------------------------------------------------
# 4. Existing TRUE / FALSE behaviour is unchanged
# ---------------------------------------------------------------------------


def test_agreeing_sources_still_produce_true(checker) -> None:
    evidence = [
        _evidence(
            "https://espncricinfo.com/final",
            "India won the 2011 ICC Cricket World Cup, defeating Sri Lanka.",
            stance="supports",
            confidence=0.99,
        ),
        _evidence(
            "https://icc-cricket.com/archive",
            "India defeated Sri Lanka to win the 2011 World Cup.",
            stance="supports",
            confidence=0.95,
        ),
    ]
    verdict, _, _ = checker.verify("India won the 2011 Cricket World Cup.", evidence)
    assert verdict is VerdictType.TRUE


def test_agreeing_sources_still_produce_false(checker) -> None:
    evidence = [
        _evidence(
            "https://sec.gov/annual",
            "Regulatory filings confirm the company sold 1.2 million units.",
            stance="refutes",
            confidence=0.98,
        ),
        _evidence(
            "https://reuters.com/report",
            "Reported sales were 1.2 million, not two million.",
            stance="refutes",
            confidence=0.90,
        ),
    ]
    verdict, _, _ = checker.verify("The company sold two million units.", evidence)
    assert verdict is VerdictType.FALSE


@pytest.mark.parametrize(
    "evidence",
    [
        [],
        [_evidence("https://a.example.com/x", "Some evidence about nothing in particular.")],
    ],
)
def test_sparse_evidence_matches_the_base_checker(checker, evidence) -> None:
    base = VerificationChecker().verify("India won the 2011 World Cup.", evidence)[0]
    assert checker.verify("India won the 2011 World Cup.", evidence)[0] is base


def test_an_already_unverifiable_claim_is_returned_untouched(checker) -> None:
    """The layer only ever downgrades; it never re-runs an inconclusive case."""
    evidence = [
        _evidence(
            "https://a.example.com/one",
            "Completely unrelated commentary.",
            confidence=0.90,
        )
    ]
    base_verdict, base_reason, base_source = VerificationChecker().verify(
        "India won the 2011 World Cup.", evidence
    )
    assert base_verdict is VerdictType.UNVERIFIABLE
    verdict, reason, source = checker.verify("India won the 2011 World Cup.", evidence)
    assert verdict is base_verdict
    assert reason == base_reason
    assert source == base_source


def test_the_conflict_checker_matches_the_base_checker_with_no_conflict(checker) -> None:
    """A broad equivalence check across varied evidence."""
    cases = [
        (
            "Apollo 11 landed on the Moon in 1969.",
            [
                _evidence(
                    "https://nasa.gov/apollo",
                    "Apollo 11 landed on the Moon in 1969.",
                    stance="supports",
                    confidence=0.99,
                ),
                _evidence(
                    "https://smithsonian.edu/apollo",
                    "The Apollo 11 mission touched down in July 1969.",
                    stance="supports",
                    confidence=0.94,
                ),
            ],
        ),
        (
            "The treaty was signed in 1815.",
            [
                _evidence(
                    "https://history.state.gov/treaty",
                    "The treaty was signed in 1815.",
                    stance="supports",
                    confidence=0.99,
                ),
                _evidence(
                    "https://britannica.com/congress",
                    "The treaty was signed in 1815 after lengthy negotiation.",
                    stance="supports",
                    confidence=0.90,
                ),
            ],
        ),
    ]
    for claim, evidence in cases:
        base = VerificationChecker().verify(claim, evidence)[0]
        assert checker.verify(claim, evidence)[0] is base, claim


# ---------------------------------------------------------------------------
# 5. Source preservation
# ---------------------------------------------------------------------------


def test_the_primary_source_survives_a_conflict(checker) -> None:
    """Downgrading a verdict must not strip the citation from the card."""
    evidence = [
        _evidence(
            "https://sec.gov/annual-report",
            "The company sold two million units during the year.",
            confidence=0.92,
        ),
        _evidence(
            "https://reuters.com/market-report",
            "The company sold 1.4 million units during the year.",
            confidence=0.89,
        ),
    ]
    _, _, source = checker.verify("The company sold two million units.", evidence)
    assert source in {item.source_url for item in evidence}


# ---------------------------------------------------------------------------
# 6. Quantity handling
# ---------------------------------------------------------------------------


def test_quantities_in_different_notations_are_the_same_figure() -> None:
    """Without this, "1,400,000" and "1.4 million" would look like a conflict."""
    assert quantity_keys("1.4 million units") == quantity_keys("1,400,000 units")
    assert quantity_keys("two million") == quantity_keys("2 million")
    assert quantity_keys("2 million") != quantity_keys("1.4 million")
    assert quantity_keys("40%") == quantity_keys("40 percent")


def test_a_shared_figure_prevents_a_false_conflict(checker) -> None:
    """Sources that agree on the number that matters must not be split."""
    evidence = [
        _evidence(
            "https://a.example.com/one",
            "The Apollo 11 mission landed on the Moon in 1969.",
            confidence=0.90,
        ),
        _evidence(
            "https://b.example.com/two",
            "Apollo 11 was a NASA mission that landed in 1969.",
            confidence=0.90,
        ),
    ]
    verdict, _, _ = checker.verify("Apollo 11 landed on the Moon in 1969.", evidence)
    assert verdict is VerdictType.TRUE


# ---------------------------------------------------------------------------
# 7. The default pipeline is NOT changed
# ---------------------------------------------------------------------------


def test_conflict_detection_is_off_by_default() -> None:
    """The regression guard for the additive-only rule.

    A new quality feature must not be able to silently alter the verdicts of a
    system that was already working. It ships available, not switched on.
    """
    assert Settings().conflict_detection_enabled is False


def test_the_default_engine_uses_the_untouched_existing_checker() -> None:
    """Real mode defaults to the plain `VerificationChecker`, as it always was."""
    settings = Settings(environment="test", use_mock_engines=False, log_level="WARNING")
    engine = _default_verification_engine(settings)

    service = engine._service
    assert type(service.checker) is VerificationChecker
    assert not isinstance(service.checker, ConflictAwareChecker)


def test_opting_in_swaps_in_the_conflict_aware_checker() -> None:
    settings = Settings(
        environment="test",
        use_mock_engines=False,
        log_level="WARNING",
        conflict_detection_enabled=True,
    )
    engine = _default_verification_engine(settings)
    assert isinstance(engine._service.checker, ConflictAwareChecker)


def test_the_opt_in_checker_is_a_superset_of_the_existing_one() -> None:
    """The opt-in checker must decide every existing case the same way.

    The strongest guarantee the additive-only rule allows: the wrapper
    subclasses the existing checker and calls it first, so for any evidence it
    already resolves these results are identical objects in every field.
    """
    base = VerificationChecker()
    wrapped = ConflictAwareChecker()

    cases = [
        (
            "India won the 2011 Cricket World Cup.",
            [
                _evidence(
                    "https://espncricinfo.com/final",
                    "India won the 2011 ICC Cricket World Cup, defeating Sri Lanka.",
                    stance="supports",
                    confidence=0.99,
                ),
                _evidence(
                    "https://icc-cricket.com/archive",
                    "India defeated Sri Lanka to win the 2011 World Cup.",
                    stance="supports",
                    confidence=0.95,
                ),
            ],
        ),
        (
            "The company sold two million units.",
            [
                _evidence(
                    "https://sec.gov/annual",
                    "Regulatory filings confirm the company sold 1.2 million units.",
                    stance="refutes",
                    confidence=0.98,
                ),
                _evidence(
                    "https://reuters.com/report",
                    "Reported sales were 1.2 million, not two million.",
                    stance="refutes",
                    confidence=0.90,
                ),
            ],
        ),
        (
            "The product release date is November 15.",
            [
                _evidence(
                    "https://a.example.com/report",
                    "Internal memos schedule the product release for November 15.",
                    stance="conflicting",
                    confidence=0.72,
                ),
            ],
        ),
        (
            "Mount Everest is the highest mountain peak in Africa.",
            [_evidence("https://x.example.com/a", "Unrelated commentary.", confidence=0.9)],
        ),
        ("India won the 2011 Cricket World Cup.", []),
        (
            "Einstein was born in 1879.",
            [
                _evidence(
                    "https://a.example.com/one",
                    "Einstein was born in Ulm in 1879.",
                    confidence=0.92,
                ),
                _evidence(
                    "https://b.example.com/two",
                    "Albert Einstein, born 1879 in Ulm, Germany.",
                    confidence=0.90,
                ),
            ],
        ),
    ]

    for claim, evidence in cases:
        assert wrapped.verify(claim, evidence) == base.verify(claim, evidence), claim
