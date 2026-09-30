"""Tests for the P1 claim-classification layer.

Covers :mod:`verification.classification`:

* each :class:`~verification.classification.ClaimCategory` is recognised
* greetings lose to claims, so "hi, India won" stays a claim
* the factual path is the default, so a real claim is never dropped
* only ``FACTUAL_CLAIM`` is fact-checkable
"""

import pytest

from verification.classification import (
    ClaimCategory,
    ClaimClassifier,
    classify_claim,
    is_fact_checkable,
)


@pytest.fixture(scope="module")
def classifier() -> ClaimClassifier:
    return ClaimClassifier()


# ---------------------------------------------------------------------------
# 1. FACTUAL CLAIM -- the existing path must keep working
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "India won the 2011 Cricket World Cup.",
        "The company sold two million units.",
        "Mount Everest is the highest mountain peak above sea level.",
        "Einstein was born in 1879.",
        "Apollo 11 landed on the Moon in 1969.",
        "The treaty was signed in 1815.",
        "Sachin Tendulkar scored 482 runs in the tournament.",
    ],
)
def test_ordinary_statements_are_factual_claims(classifier, text: str) -> None:
    """The path the existing pipeline already handles is reached unchanged."""
    result = classifier.classify(text)
    assert result.category is ClaimCategory.FACTUAL_CLAIM
    assert result.is_fact_checkable


# ---------------------------------------------------------------------------
# 2. QUESTION
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Who won the 2011 Cricket World Cup?",
        "Did India win the final?",
        "How many runs did Tendulkar score?",
        "Is the treaty still in force?",
        "What is the capital of France?",
    ],
)
def test_questions_are_not_fact_checkable(classifier, text: str) -> None:
    result = classifier.classify(text)
    assert result.category is ClaimCategory.QUESTION
    assert not result.is_fact_checkable


# ---------------------------------------------------------------------------
# 3. OPINION
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I think India is the best cricket team.",
        "I believe the policy was a mistake.",
        "In my opinion, the film was overrated.",
        "Honestly, the best team is India.",
        "Arguably it is the greatest album ever.",
    ],
)
def test_opinions_are_not_checked_as_objective_claims(
    classifier, text: str
) -> None:
    result = classifier.classify(text)
    assert result.category is ClaimCategory.OPINION
    assert not result.is_fact_checkable


def test_an_unmarked_superlative_stays_a_claim(classifier) -> None:
    """Precision beats recall: only self-marked judgements are opinions.

    "is the greatest player" is indistinguishable from a factual claim
    without a hedging marker, and guessing wrong here would drop a checkable
    statement.
    """
    result = classifier.classify("He is the greatest player of all time.")
    assert result.category is ClaimCategory.FACTUAL_CLAIM


# ---------------------------------------------------------------------------
# 4. COMMAND / INSTRUCTION
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Please open the file.",
        "Go to the next slide.",
        "Check the figures before you publish.",
        "Take notes during the briefing.",
        "Read the terms and conditions.",
    ],
)
def test_instructions_are_not_fact_checked(classifier, text: str) -> None:
    result = classifier.classify(text)
    assert result.category is ClaimCategory.COMMAND
    assert not result.is_fact_checkable


# ---------------------------------------------------------------------------
# 5. SMALL TALK
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Hello there!",
        "Good morning.",
        "Thanks a lot.",
        "Hi everyone",
        "How are you?",
        "Let's get started.",
    ],
)
def test_small_talk_is_ignored(classifier, text: str) -> None:
    result = classifier.classify(text)
    assert result.category is ClaimCategory.SMALL_TALK
    assert not result.is_fact_checkable


# ---------------------------------------------------------------------------
# 6. UNCLEAR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "Um.", "You know.", "Um, uh."])
def test_unmeaningful_text_is_unclear(classifier, text: str) -> None:
    result = classifier.classify(text)
    assert result.category is ClaimCategory.UNCLEAR
    assert not result.is_fact_checkable


# ---------------------------------------------------------------------------
# 7. Ordering and precedence
# ---------------------------------------------------------------------------


def test_a_greeting_wins_over_a_trailing_question(classifier) -> None:
    """Rules are ordered, so "How are you?" is small talk, not a question."""
    result = classifier.classify("How are you?")
    assert result.category is ClaimCategory.SMALL_TALK


def test_a_greeting_does_not_swallow_the_claim_after_it(classifier) -> None:
    """The important direction: a greeted claim is still a claim."""
    result = classifier.classify("Hi, India won the 2011 Cricket World Cup.")
    assert result.category is ClaimCategory.FACTUAL_CLAIM
    assert result.is_fact_checkable


def test_non_string_input_is_unclear_not_an_exception(classifier) -> None:
    assert classifier.classify(None).category is ClaimCategory.UNCLEAR
    assert classifier.classify(42).category is ClaimCategory.UNCLEAR


# ---------------------------------------------------------------------------
# 8. Determinism
# ---------------------------------------------------------------------------


def test_classification_is_stable_across_calls() -> None:
    """The same text must always classify the same way, in any order."""
    texts = [
        "India won the 2011 Cricket World Cup.",
        "Who won?",
        "Please close the door.",
        "I think it is wrong.",
    ]
    first = [classify_claim(text).category for text in texts]
    second = [classify_claim(text).category for text in reversed(texts)][::-1]
    assert first == second


def test_module_helpers_agree_with_the_classifier() -> None:
    assert is_fact_checkable("India won the 2011 Cricket World Cup.") is True
    assert is_fact_checkable("Who won the 2011 World Cup?") is False
    assert classify_claim("Please close the door.").category is ClaimCategory.COMMAND


def test_every_result_carries_a_reason() -> None:
    """A reason is always present, so a decision is always explainable."""
    for text in ["", "Hi.", "Who?", "I think so.", "Go away.", "India won."]:
        assert classify_claim(text).reason.strip()
