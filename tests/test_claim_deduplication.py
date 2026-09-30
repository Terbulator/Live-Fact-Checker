"""Tests for the P1 claim-level duplicate protection.

Covers :mod:`verification.claim_dedup`:

* the exact same claim is processed once
* a claim that adds, drops or rewords anything is a *different* claim
* state is per session, so concurrent sessions never suppress each other
* the remembered set is bounded
* existing transcript and session deduplication is untouched
"""

import pytest

from backend.adapters.claim_engine import normalize_transcript
from verification.claim_dedup import (
    ClaimDeduplicator,
    normalize_claim_text,
)


@pytest.fixture
def dedup() -> ClaimDeduplicator:
    return ClaimDeduplicator()


# ---------------------------------------------------------------------------
# 1. The exact same claim is processed once
# ---------------------------------------------------------------------------


def test_the_same_claim_is_only_processed_once(dedup) -> None:
    assert dedup.accept("session_1", "Ireland won the match.") is True
    assert dedup.accept("session_1", "Ireland won the match.") is False
    assert dedup.accept("session_1", "Ireland won the match.") is False


def test_case_and_punctuation_are_noise(dedup) -> None:
    """Only spelling noise is folded away, never the words themselves."""
    assert dedup.accept("session_1", "Ireland won the match.") is True
    assert dedup.accept("session_1", "ireland won the match.") is False
    assert dedup.accept("session_1", "  Ireland won the match!  ") is False
    assert dedup.accept("session_1", "Ireland  won   the match.") is False


def test_normalisation_folds_case_punctuation_and_spacing() -> None:
    assert normalize_claim_text("Ireland won the match!") == normalize_claim_text(
        "  ireland   won the match  "
    )


# ---------------------------------------------------------------------------
# 2. A different claim is a different claim
# ---------------------------------------------------------------------------


def test_an_extended_claim_is_not_a_duplicate(dedup) -> None:
    """The worked example from the specification."""
    assert dedup.accept("session_1", "Ireland won the match.") is True
    assert dedup.accept("session_1", "Ireland won the match by 5 wickets.") is True


@pytest.mark.parametrize(
    "second",
    [
        "Ireland lost the match.",
        "Ireland won the tournament.",
        "England won the match.",
        "Ireland won the match yesterday.",
    ],
)
def test_any_material_change_makes_a_new_claim(dedup, second: str) -> None:
    assert dedup.accept("session_1", "Ireland won the match.") is True
    assert dedup.accept("session_1", second) is True


def test_numbers_make_a_claim_distinct(dedup) -> None:
    assert dedup.accept("session_1", "He scored 482 runs.") is True
    assert dedup.accept("session_1", "He scored 500 runs.") is True


# ---------------------------------------------------------------------------
# 3. Per-session isolation
# ---------------------------------------------------------------------------


def test_two_sessions_do_not_suppress_each_other(dedup) -> None:
    """Two concurrent sessions may legitimately make the same claim."""
    assert dedup.accept("session_1", "Ireland won the match.") is True
    assert dedup.accept("session_2", "Ireland won the match.") is True


def test_clearing_one_session_leaves_the_other_alone(dedup) -> None:
    dedup.accept("session_1", "Ireland won the match.")
    dedup.accept("session_2", "Ireland won the match.")
    dedup.clear("session_1")
    assert dedup.accept("session_1", "Ireland won the match.") is True
    assert dedup.accept("session_2", "Ireland won the match.") is False


def test_clear_without_a_session_forgets_everything(dedup) -> None:
    dedup.accept("session_1", "Ireland won the match.")
    dedup.clear()
    assert dedup.accept("session_1", "Ireland won the match.") is True


# ---------------------------------------------------------------------------
# 4. Bounded state
# ---------------------------------------------------------------------------


def test_remembered_claims_are_bounded() -> None:
    """A long session cannot grow the dedup set without limit."""
    dedup = ClaimDeduplicator(max_tracked_claims=10)
    for index in range(50):
        dedup.accept("session_1", f"Claim number {index} was made.")
    assert len(dedup.seen_keys("session_1")) == 10


def test_the_most_recent_claims_are_the_ones_remembered() -> None:
    dedup = ClaimDeduplicator(max_tracked_claims=3)
    for text in ["first claim here", "second claim here", "third claim here"]:
        dedup.accept("session_1", text)
    dedup.accept("session_1", "fourth claim here")
    # The newest is still suppressed; the oldest has aged out.
    assert dedup.accept("session_1", "fourth claim here") is False
    assert dedup.accept("session_1", "first claim here") is True


# ---------------------------------------------------------------------------
# 5. Batch filtering
# ---------------------------------------------------------------------------


def test_filter_duplicates_collapses_repeats_within_one_batch(dedup) -> None:
    result = dedup.filter_duplicates(
        "session_1",
        [
            "India won the 2011 World Cup.",
            "India won the 2011 World Cup.",
            "Tendulkar scored 482 runs.",
        ],
    )
    assert result == [
        "India won the 2011 World Cup.",
        "Tendulkar scored 482 runs.",
    ]


def test_filter_duplicates_preserves_order(dedup) -> None:
    result = dedup.filter_duplicates(
        "session_1", ["Alpha happened here.", "Beta happened here."]
    )
    assert result == ["Alpha happened here.", "Beta happened here."]


# ---------------------------------------------------------------------------
# 6. Edge cases and the non-intrusiveness guarantee
# ---------------------------------------------------------------------------


def test_empty_text_is_never_treated_as_a_duplicate(dedup) -> None:
    """Collapsing every empty claim onto one key would drop real claims."""
    assert dedup.accept("session_1", "") is True
    assert dedup.accept("session_1", "") is True
    assert dedup.accept("session_1", "   ") is True
    assert dedup.is_duplicate("session_1", "") is False


def test_punctuation_only_text_does_not_collide(dedup) -> None:
    assert dedup.accept("session_1", "...") is True
    assert dedup.accept("session_1", "!!!") is True


def test_is_duplicate_does_not_record(dedup) -> None:
    """Checking and remembering are separate operations, by design."""
    assert dedup.is_duplicate("session_1", "Ireland won the match.") is False
    assert dedup.is_duplicate("session_1", "Ireland won the match.") is False
    assert dedup.accept("session_1", "Ireland won the match.") is True
    assert dedup.is_duplicate("session_1", "Ireland won the match.") is True


def test_the_existing_transcript_deduplication_is_untouched() -> None:
    """This layer complements the existing one; it does not replace it."""
    # `normalize_transcript` is the pre-existing, still-in-use helper.
    assert normalize_transcript("Ireland won the match.") == "ireland won the match"
    # And it still differs from a claim that changes meaning.
    assert normalize_transcript("Ireland won the match.") != normalize_transcript(
        "Ireland won the match by 5 wickets."
    )
