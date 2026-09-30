"""Tests for the evidence-grounded ``supportingStatement``.

Three things are kept deliberately apart, and this module exists to prove it:

1. **verdict** -- what the system concluded
2. **supporting statement** -- why, in prose traceable to retrieved evidence
3. **confidence** -- the search provider's own relevance score, or ``None``

The statement is assembled from the evidence the retriever returned and from
nothing else. There is no second model call, so the tests below can assert the
strongest possible property: every fact in the sentence came out of a snippet
that really came back from the provider.
"""

import re
from urllib.parse import urlsplit

import pytest

from backend.adapters.verification import VerificationServiceEngine
from backend.schemas import ClaimEvent, Verdict
from verification.models import EvidenceItem, VerdictType
from verification.service import (
    VerificationService,
    build_supporting_statement,
)
from verification.sources import rank_sources

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _Retriever:
    """Stands in for the search retriever with a fixed evidence list."""

    def __init__(self, evidence):
        self._evidence = list(evidence)

    def retrieve(self, query, max_results=3):
        return list(self._evidence)


def _evidence(url, snippet, **kwargs) -> EvidenceItem:
    return EvidenceItem(snippet=snippet, source_url=url, **kwargs)


def _claim(text="India won the 2011 Cricket World Cup.") -> ClaimEvent:
    return ClaimEvent(
        type="claim",
        claimId="c1",
        sessionId="s1",
        speaker="Speaker 1",
        claim=text,
        timestamp=1.0,
    )


def _statements_in(text: str):
    """Every ``“...”`` excerpt quoted in a statement."""
    return re.findall(r"“([^”]*)”", text or "")


# ---------------------------------------------------------------------------
# B. The statement is based on the supplied evidence
# ---------------------------------------------------------------------------


def test_statement_quotes_the_retrieved_snippet_and_names_its_source() -> None:
    """The sentence is traceable: it quotes a real snippet and names its host."""
    evidence = [
        _evidence(
            "https://www.espncricinfo.com/series/icc-world-cup-2011-final",
            "India beat Sri Lanka by 89 runs in the 2011 World Cup final.",
            confidence=0.98,
        )
    ]

    statement = build_supporting_statement(VerdictType.TRUE, evidence)

    assert statement is not None
    assert "India beat Sri Lanka by 89 runs" in statement
    assert "espncricinfo.com" in statement


async def test_engine_carries_the_statement_onto_the_wire() -> None:
    """The full pipeline publishes it, so a client can render it."""
    inner = VerificationServiceEngine(
        service=VerificationService(
            retriever=_Retriever(
                [
                    _evidence(
                        "https://britannica.com/place/Mount-Everest",
                        "Mount Everest is in Asia; Kilimanjaro is Africa's highest peak.",
                        stance="refutes",
                        confidence=0.99,
                    )
                ]
            )
        )
    )

    event = await inner.verify(_claim("Mount Everest is the highest mountain in Africa."))

    assert event.verdict is Verdict.FALSE
    assert event.supportingStatement is not None
    assert "Kilimanjaro" in event.supportingStatement
    assert event.to_wire()["supportingStatement"] == event.supportingStatement


# ---------------------------------------------------------------------------
# C. The statement invents no numbers or facts
# ---------------------------------------------------------------------------


def test_statement_contains_no_figure_the_evidence_did_not_state() -> None:
    """Every number in the sentence must appear in a retrieved snippet.

    The claim is checked because its numbers are the most tempting thing to
    invent: a statement that quietly repeated the claim's own figures would
    look like corroboration while being a copy of the assertion.
    """
    claim = "The company sold 4.7 million units in 2019."
    evidence = [
        _evidence(
            "https://sec.gov/edgar/company-annual-2019",
            "The company reported revenue of 1.2 million units for fiscal 2019.",
            stance="refutes",
            confidence=0.97,
        )
    ]

    statement = build_supporting_statement(VerdictType.FALSE, evidence)

    assert statement is not None
    numbers = set(re.findall(r"\d+(?:\.\d+)?", statement))
    evidence_numbers = set(re.findall(r"\d+(?:\.\d+)?", evidence[0].snippet))
    assert numbers, "the quoted evidence should still carry its own figures"
    assert numbers <= evidence_numbers, "the statement introduced a figure of its own"
    # The claim's own figure must not leak in as if it were sourced.
    assert "4.7" not in statement


def test_statement_does_not_quote_a_source_that_was_not_retrieved() -> None:
    """No citation may appear that the retriever did not return."""
    evidence = [
        _evidence("https://reuters.com/world/report", "Reported figures differ.", confidence=0.8)
    ]

    statement = build_supporting_statement(VerdictType.TRUE, evidence)

    assert statement is not None
    hosts = [urlsplit(str(e.source_url)).netloc for e in evidence]
    for forbidden in ("bbc.co.uk", "wikipedia.org", "example.com"):
        assert forbidden not in statement
    assert any(host in statement for host in hosts)


def test_statement_is_absent_when_there_is_nothing_to_ground_it_in() -> None:
    """With no evidence the only honest answer is to say nothing."""
    assert build_supporting_statement(VerdictType.UNVERIFIABLE, []) is None
    assert build_supporting_statement(VerdictType.UNVERIFIABLE, None) is None
    assert build_supporting_statement(VerdictType.TRUE, []) is None


# ---------------------------------------------------------------------------
# D. Conflicting evidence -> AMBIGUOUS, with the conflict reflected
# ---------------------------------------------------------------------------


def test_ambiguous_statement_shows_both_sides_rather_than_a_consensus() -> None:
    """Two sources, two readings: the statement must present the disagreement."""
    evidence = [
        _evidence(
            "https://analyst.example.com/forecast",
            "Growth may depend on several factors, and may refer to a regional split.",
            confidence=0.9,
        ),
        _evidence(
            "https://press.example.com/announcement",
            "The multiple regions each reported different outcomes for the quarter.",
            confidence=0.8,
        ),
    ]

    statement = build_supporting_statement(VerdictType.AMBIGUOUS, evidence)

    assert statement is not None
    assert "more than one reading" in statement
    quotes = _statements_in(statement)
    assert len(quotes) == 2, "an ambiguous statement must present both sides"
    assert "may depend on" in quotes[0]
    assert "multiple regions" in quotes[1]


def test_ambiguous_statement_still_quotes_when_only_one_source_exists() -> None:
    """One source is not a conflict, but the statement still explains the claim."""
    evidence = [
        _evidence(
            "https://analyst.example.com/forecast",
            "Growth may depend on several factors.",
            confidence=0.9,
        )
    ]

    statement = build_supporting_statement(VerdictType.AMBIGUOUS, evidence)

    assert statement is not None
    assert "more than one reading" in statement
    assert "may depend on several factors" in statement


def test_unverifiable_statement_says_the_evidence_is_insufficient() -> None:
    """Weak evidence must be reported as insufficient, never as support."""
    evidence = [
        _evidence(
            "https://blog.example.com/opinion",
            "Some people think this might be true, though it is hard to say.",
            confidence=0.62,
        )
    ]

    statement = build_supporting_statement(VerdictType.UNVERIFIABLE, evidence)

    assert statement is not None
    assert "does not establish this claim" in statement
    assert "supports this claim" not in statement
    assert "contradicts this claim" not in statement


# ---------------------------------------------------------------------------
# Verdict-specific framing
# ---------------------------------------------------------------------------


def test_each_verdict_frames_the_same_evidence_differently() -> None:
    """The verdict decides the framing word; the evidence supplies the facts."""
    evidence = [
        _evidence("https://source.example.com/a", "The recorded figure was 12 units.", confidence=0.9)
    ]

    assert "supports this claim" in build_supporting_statement(VerdictType.TRUE, evidence)
    assert "contradicts this claim" in build_supporting_statement(VerdictType.FALSE, evidence)
    assert "does not establish this claim" in build_supporting_statement(
        VerdictType.UNVERIFIABLE, evidence
    )
    assert "more than one reading" in build_supporting_statement(VerdictType.AMBIGUOUS, evidence)


def test_statement_quotes_the_annotated_source_matching_the_verdict() -> None:
    """When the retriever tagged stances, the quoted source must match the verdict."""
    evidence = [
        # Ranked above the refuting source by its higher score, so the top-ranked
        # entry supports while the verdict is FALSE.
        _evidence(
            "https://supporting.example.com/a",
            "The launch date is confirmed as spring.",
            stance="supports",
            confidence=0.95,
        ),
        _evidence(
            "https://refuting.example.com/b",
            "The launch was delayed to autumn.",
            stance="refutes",
            confidence=0.90,
        ),
    ]

    statement = build_supporting_statement(VerdictType.FALSE, evidence)

    assert statement is not None
    assert "autumn" in statement
    assert "spring" not in statement


def test_unannotated_evidence_falls_back_to_the_top_ranked_source() -> None:
    """Without stances, the statement quotes what the UI shows as primary."""
    evidence = [
        _evidence("https://a.example.com/1", "Lower ranked snippet.", confidence=0.10),
        _evidence("https://b.example.com/2", "Top ranked snippet.", confidence=0.99),
    ]
    ranked = rank_sources(evidence)

    statement = build_supporting_statement(VerdictType.TRUE, evidence)

    assert statement is not None
    assert ranked[0]["url"] == "https://b.example.com/2"
    assert "Top ranked snippet" in statement


def test_unscored_evidence_still_produces_a_statement() -> None:
    """No provider score must not suppress the explanation.

    Confidence and the statement are separate concerns: dropping the text
    because the provider returned no number would conflate them, and the text
    is a real snippet either way.
    """
    evidence = [
        _evidence(
            "https://source.example.com/a",
            "The regulator published the figure last week.",
            confidence=None,
        )
    ]

    statement = build_supporting_statement(VerdictType.TRUE, evidence)

    assert statement is not None
    assert "regulator published" in statement


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


async def test_event_built_without_a_statement_is_still_valid() -> None:
    """The field is additive: an engine that predates it still verifies."""
    from backend.adapters.verification import _wire_supporting_statement

    class _Service:
        def verify_claim(self, payload):
            class _Result:
                verdict = VerdictType.TRUE
                reason = "Corroborated by the archive."
                source = "https://nasa.gov/apollo"

            return _Result()

    event = await VerificationServiceEngine(service=_Service()).verify(_claim())

    assert event.supportingStatement is None
    assert event.verdict is Verdict.TRUE
    assert _wire_supporting_statement(None) is None
    assert _wire_supporting_statement("   ") is None
    assert _wire_supporting_statement("Real text.") == "Real text."


@pytest.mark.parametrize("verdict", list(Verdict))
async def test_every_wire_verdict_reaches_the_api(verdict) -> None:
    """AMBIGUOUS included: the statement must not break the verdict mapping."""
    from backend.schemas import ContractVerificationEvent

    internal = {
        Verdict.TRUE: VerdictType.TRUE,
        Verdict.FALSE: VerdictType.FALSE,
        Verdict.UNVERIFIABLE: VerdictType.UNVERIFIABLE,
        Verdict.AMBIGUOUS: VerdictType.AMBIGUOUS,
    }[verdict]

    class _Service:
        def verify_claim(self, payload):
            class _Result:
                verdict = internal
                reason = "Because of the retrieved evidence."
                source = "https://source.example.com/a"

            return _Result()

    event = await VerificationServiceEngine(service=_Service()).verify(_claim())

    assert event.verdict is verdict
    assert event.to_wire()["verdict"] == verdict.value
    assert ContractVerificationEvent(
        type="verification",
        claimId="c1",
        sessionId="s1",
        timestamp=1.0,
        verdict=verdict,
        reason="Because.",
        source="https://a.example.com",
    ).verdict is verdict
