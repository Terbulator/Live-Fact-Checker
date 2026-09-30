"""Tests for the P1 compound-claim splitter.

Covers :mod:`verification.compound`:

* a sentence asserting several things is split into independent claims
* an ordinary single claim comes back byte-identical
* proper nouns, idioms and compound predicates are *not* split
* each part is a self-contained sentence
"""

import pytest

from verification.compound import (
    CompoundClaimSplitter,
    is_compound_claim,
    split_compound_claim,
)


@pytest.fixture(scope="module")
def splitter() -> CompoundClaimSplitter:
    return CompoundClaimSplitter()


# ---------------------------------------------------------------------------
# 1. The headline case
# ---------------------------------------------------------------------------


def test_two_assertions_joined_by_and_are_split(splitter) -> None:
    result = splitter.split(
        "India won the 2011 World Cup and Sachin Tendulkar scored 482 runs."
    )
    assert result == [
        "India won the 2011 World Cup.",
        "Sachin Tendulkar scored 482 runs.",
    ]


def test_both_halves_are_independently_checkable(splitter) -> None:
    """Each part keeps the subject and the figure that has to be verified."""
    parts = splitter.split(
        "Einstein was born in 1879 and he won the Nobel Prize in 1921."
    )
    assert parts == ["Einstein was born in 1879.", "He won the Nobel Prize in 1921."]


def test_three_assertions_are_all_recovered(splitter) -> None:
    parts = splitter.split(
        "The company was founded in 1998 and it listed in 2010 and it employs 400 people."
    )
    assert len(parts) == 3
    assert parts[0] == "The company was founded in 1998."
    assert parts[1] == "It listed in 2010."
    assert parts[2] == "It employs 400 people."


# ---------------------------------------------------------------------------
# 2. Single claims are untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "India won the 2011 Cricket World Cup.",
        "The company sold two million units.",
        "Mount Everest is the highest mountain peak in Africa.",
        "Apollo 11 landed on the Moon in 1969.",
        "Einstein was born in 1879.",
    ],
)
def test_ordinary_single_claims_are_returned_unchanged(splitter, text: str) -> None:
    """The existing behaviour for an ordinary claim is preserved exactly."""
    assert splitter.split(text) == [text]


# ---------------------------------------------------------------------------
# 3. Things that must NOT be split
# ---------------------------------------------------------------------------


def test_and_inside_a_proper_noun_is_not_a_split(splitter) -> None:
    text = "Research and Development is funded by the state."
    assert splitter.split(text) == [text]


def test_and_between_two_noun_phrases_is_not_a_split(splitter) -> None:
    text = "India and Pakistan played cricket."
    assert splitter.split(text) == [text]


def test_a_compound_predicate_stays_one_claim(splitter) -> None:
    """"reported a profit and missed forecasts" is one claim, not two."""
    text = "The company reported a profit and missed analyst forecasts."
    assert splitter.split(text) == [text]


def test_a_negated_continuation_stays_one_claim(splitter) -> None:
    text = "The launch happened in November and not in December."
    assert splitter.split(text) == [text]


def test_an_initialism_period_is_not_a_sentence_boundary(splitter) -> None:
    text = "The U.S. won the match."
    assert splitter.split(text) == [text]


def test_two_sentences_are_separated(splitter) -> None:
    parts = splitter.split("India won the 2011 World Cup. Mumbai hosted the final.")
    assert parts == ["India won the 2011 World Cup.", "Mumbai hosted the final."]


# ---------------------------------------------------------------------------
# 4. Shape of the output
# ---------------------------------------------------------------------------


def test_every_part_ends_as_a_sentence(splitter) -> None:
    parts = splitter.split("Apollo 11 landed in 1969 and Armstrong walked in 1969.")
    assert all(part.endswith(".") for part in parts)


def test_dangling_punctuation_is_not_carried_into_a_part(splitter) -> None:
    parts = splitter.split("The U.S. team won, and the coach was fired.")
    assert parts == ["The U.S. team won.", "The coach was fired."]


def test_empty_and_non_string_input_yield_nothing(splitter) -> None:
    assert splitter.split("") == []
    assert splitter.split("   ") == []
    assert splitter.split(None) == []


def test_a_very_long_list_of_clauses_is_left_alone(splitter) -> None:
    """Past the cap, the sentence is returned whole rather than shredded."""
    text = (
        "A happened and B happened and C happened and D happened and "
        "E happened and F happened"
    )
    assert splitter.split(text) == [text]


# ---------------------------------------------------------------------------
# 5. Helpers
# ---------------------------------------------------------------------------


def test_is_compound_claim_agrees_with_split(splitter) -> None:
    assert is_compound_claim("India won the 2011 World Cup and Tendulkar scored 482 runs.")
    assert not is_compound_claim("India won the 2011 Cricket World Cup.")


def test_split_many_preserves_order_and_flattens(splitter) -> None:
    result = splitter.split_many(
        [
            "India won the 2011 Cricket World Cup.",
            "Einstein was born in 1879 and he won the Nobel Prize in 1921.",
        ]
    )
    assert result == [
        "India won the 2011 Cricket World Cup.",
        "Einstein was born in 1879.",
        "He won the Nobel Prize in 1921.",
    ]


def test_splitting_is_deterministic(splitter) -> None:
    text = "India won the 2011 World Cup and Sachin Tendulkar scored 482 runs."
    assert splitter.split(text) == splitter.split(text)
    assert split_compound_claim(text) == split_compound_claim(text)


def test_splitting_never_loses_a_word(splitter) -> None:
    """The split re-punctuates; it never rewrites.

    Only the coordinating connector that made the split disappears; every
    other word must survive into one of the parts.
    """
    text = "Einstein was born in 1879 and he won the Nobel Prize in 1921."
    parts = splitter.split(text)
    joined = " ".join(parts).lower()
    for word in (w.strip(".,").lower() for w in text.split()):
        if word == "and":
            continue
        assert word in joined, f"{word!r} was lost in the split"
