"""Tests for multi-source evidence ranking and exposure.

Covers the P1 multi-source evidence feature:

* deterministic ranking of retrieved evidence into citable sources
* URL-less evidence discarded, duplicates collapsed
* the backward-compatible ``source`` field agreeing with the ranked list
* the backend wire shape and its normalisation at the adapter boundary
* TRUE / FALSE / UNVERIFIABLE semantics and conflict handling preserved
"""

import pytest

from backend.adapters.verification import (
    VerificationServiceEngine,
    to_wire_sources,
)
from backend.schemas import ClaimEvent, VerificationEvent, Verdict
from verification.models import EvidenceItem, VerdictType
from verification.service import VerificationService
from verification.sources import (
    MAX_SNIPPET_CHARS,
    dedupe_key,
    primary_source,
    rank_sources,
)


def _evidence(url: str, snippet: str, **kwargs) -> EvidenceItem:
    return EvidenceItem(snippet=snippet, source_url=url, **kwargs)


def _claim(claim_text: str = "India won the 2011 Cricket World Cup.") -> ClaimEvent:
    return ClaimEvent(
        type="claim",
        claimId="c1",
        sessionId="s1",
        speaker="Speaker 1",
        claim=claim_text,
        timestamp=1.0,
    )


# ---------------------------------------------------------------------------
# 1. Basic ranking
# ---------------------------------------------------------------------------


def test_single_source_is_returned() -> None:
    """One citable item yields exactly one source."""
    sources = rank_sources(
        [
            _evidence(
                "https://nasa.gov/apollo",
                "Apollo 11 landed on the Moon in 1969.",
                title="Apollo 11",
                confidence=0.99,
            )
        ]
    )
    assert len(sources) == 1
    assert sources[0]["url"] == "https://nasa.gov/apollo"
    assert sources[0]["title"] == "Apollo 11"


def test_multiple_sources_are_all_returned() -> None:
    """Several citable items yield several sources, best first."""
    sources = rank_sources(
        [
            _evidence("https://low.example.com/a", "Low scored source.", confidence=0.30),
            _evidence("https://high.example.com/b", "High scored source.", confidence=0.95),
            _evidence("https://mid.example.com/c", "Mid scored source.", confidence=0.70),
        ]
    )
    assert [s["url"] for s in sources] == [
        "https://high.example.com/b",
        "https://mid.example.com/c",
        "https://low.example.com/a",
    ]


def test_sources_carry_title_and_snippet() -> None:
    """Each source exposes title, url and a short snippet."""
    sources = rank_sources(
        [
            _evidence(
                "https://nasa.gov/apollo",
                "Apollo 11 landed on the Moon in 1969.",
                title="Apollo 11 Mission",
                confidence=0.99,
            )
        ]
    )
    assert sources[0]["title"] == "Apollo 11 Mission"
    assert "Apollo 11 landed" in sources[0]["snippet"]
    assert sources[0]["url"] == "https://nasa.gov/apollo"


# ---------------------------------------------------------------------------
# 2. Filtering
# ---------------------------------------------------------------------------


def test_url_less_evidence_is_discarded() -> None:
    """Evidence with no URL is dropped, never replaced by a placeholder."""
    sources = rank_sources(
        [
            _evidence("", "A source with no URL at all.", confidence=0.99),
            _evidence("   ", "Whitespace-only URL.", confidence=0.99),
            _evidence("https://real.example.com/x", "A real citable source.", confidence=0.80),
        ]
    )
    assert [s["url"] for s in sources] == ["https://real.example.com/x"]


def test_snippet_less_evidence_is_discarded() -> None:
    """A URL with nothing to compare carries no evidence and is dropped."""
    sources = rank_sources(
        [
            EvidenceItem(snippet="", source_url="https://empty.example.com/"),
            _evidence("https://real.example.com/x", "A real citable source."),
        ]
    )
    assert [s["url"] for s in sources] == ["https://real.example.com/x"]


def test_duplicate_sources_are_collapsed() -> None:
    """The same page from two records is listed once."""
    sources = rank_sources(
        [
            _evidence("https://nasa.gov/apollo", "First record.", confidence=0.90),
            _evidence("https://www.nasa.gov/apollo/", "Second record.", confidence=0.95),
        ]
    )
    assert len(sources) == 1


def test_dedupe_keeps_the_higher_scoring_duplicate() -> None:
    """When a page appears twice, the better-attested record wins."""
    sources = rank_sources(
        [
            _evidence("https://nasa.gov/apollo", "Weak record.", confidence=0.65),
            _evidence("https://nasa.gov/apollo", "Strong record.", confidence=0.99),
        ]
    )
    assert len(sources) == 1
    assert sources[0]["snippet"] == "Strong record."


def test_dedupe_key_normalises_host_and_trailing_slash() -> None:
    assert dedupe_key("https://www.Example.com/Path/") == dedupe_key(
        "https://example.com/Path"
    )


# ---------------------------------------------------------------------------
# 3. Ranking signals
# ---------------------------------------------------------------------------


def test_higher_confidence_outranks_provider_order() -> None:
    """The first search result is not automatically authoritative."""
    sources = rank_sources(
        [
            _evidence("https://first.example.com/a", "Returned first.", confidence=0.61),
            _evidence("https://second.example.com/b", "Returned second.", confidence=0.99),
        ]
    )
    assert sources[0]["url"] == "https://second.example.com/b"


def test_ties_keep_provider_order_deterministically() -> None:
    """Equal scores preserve the order the retriever returned."""
    evidence = [
        _evidence("https://a.example.com/1", "First.", confidence=0.80),
        _evidence("https://b.example.com/2", "Second.", confidence=0.80),
        _evidence("https://c.example.com/3", "Third.", confidence=0.80),
    ]
    first = [s["url"] for s in rank_sources(evidence)]
    second = [s["url"] for s in rank_sources(list(evidence))]
    assert first == ["https://a.example.com/1", "https://b.example.com/2", "https://c.example.com/3"]
    assert first == second


def test_stance_outranks_an_equal_confidence_neutral_source() -> None:
    """Evidence that bears on the claim leads evidence that is adjacent to it."""
    sources = rank_sources(
        [
            _evidence("https://neutral.example.com/a", "Merely adjacent.", stance="neutral"),
            _evidence("https://supports.example.com/b", "Directly supports.", stance="supports"),
        ]
    )
    assert sources[0]["url"] == "https://supports.example.com/b"


def test_a_title_and_snippet_make_a_record_more_citable() -> None:
    """A record a reader can actually use outranks a bare stub."""
    sources = rank_sources(
        [
            _evidence("https://bare.example.com/a", "A snippet."),
            _evidence("https://rich.example.com/b", "A snippet.", title="A Useful Headline"),
        ]
    )
    assert sources[0]["url"] == "https://rich.example.com/b"


def test_ranking_caps_the_number_of_sources() -> None:
    """The card shows corroboration, not a search-results page."""
    evidence = [
        _evidence(f"https://example.com/{index}", f"Snippet {index}.", confidence=0.9)
        for index in range(12)
    ]
    assert len(rank_sources(evidence)) == 5


def test_empty_and_none_evidence_rank_to_nothing() -> None:
    assert rank_sources([]) == []
    assert rank_sources(None) == []


def test_snippet_is_truncated_for_the_wire() -> None:
    """Long retrieval snippets do not become long wire payloads."""
    long_snippet = "word " * 400
    sources = rank_sources([_evidence("https://nasa.gov/x", long_snippet)])
    assert len(sources[0]["snippet"]) <= MAX_SNIPPET_CHARS + 1
    assert sources[0]["snippet"].endswith("…")


# ---------------------------------------------------------------------------
# 4. Primary source selection
# ---------------------------------------------------------------------------


def test_primary_source_is_the_top_ranked_url() -> None:
    sources = rank_sources(
        [
            _evidence("https://weak.example.com/a", "Weak.", confidence=0.62),
            _evidence("https://strong.example.com/b", "Strong.", confidence=0.98),
        ]
    )
    assert primary_source(sources, "fallback") == "https://strong.example.com/b"


def test_primary_source_falls_back_when_nothing_is_citable() -> None:
    assert primary_source([], "No source available") == "No source available"


# ---------------------------------------------------------------------------
# 5. Verdicts and conflicts are unchanged
# ---------------------------------------------------------------------------


def test_true_with_supporting_evidence_keeps_true_and_lists_sources() -> None:
    class _Retriever:
        def retrieve(self, query, max_results=3):
            return [
                _evidence(
                    "https://espncricinfo.com/final",
                    "India won the 2011 ICC Cricket World Cup, defeating Sri Lanka.",
                    title="2011 Final",
                    stance="supports",
                    confidence=0.99,
                ),
                _evidence(
                    "https://icc-cricket.com/archive",
                    "India defeated Sri Lanka to win the 2011 World Cup.",
                    title="ICC Archive",
                    stance="supports",
                    confidence=0.95,
                ),
            ]

    result = VerificationService(retriever=_Retriever()).verify_claim(_claim())

    assert result.verdict == VerdictType.TRUE
    assert result.source == "https://espncricinfo.com/final"
    assert [s["url"] for s in result.sources] == [
        "https://espncricinfo.com/final",
        "https://icc-cricket.com/archive",
    ]


def test_false_with_refuting_evidence_keeps_false_and_lists_sources() -> None:
    class _Retriever:
        def retrieve(self, query, max_results=3):
            return [
                _evidence(
                    "https://sec.gov/annual",
                    "Regulatory filings confirm the company sold 1.2 million units.",
                    title="Annual Disclosure",
                    stance="refutes",
                    confidence=0.98,
                ),
                _evidence(
                    "https://reuters.com/report",
                    "Reported sales were 1.2 million, not two million.",
                    title="Sales Report",
                    stance="refutes",
                    confidence=0.90,
                ),
            ]

    result = VerificationService(retriever=_Retriever()).verify_claim(
        _claim("The company sold two million units.")
    )

    assert result.verdict == VerdictType.FALSE
    assert "sec.gov" in result.source
    assert len(result.sources) == 2


def test_conflicting_evidence_stays_unverifiable_and_still_lists_sources() -> None:
    """Conflicting evidence must not be forced to TRUE or FALSE."""

    class _Retriever:
        def retrieve(self, query, max_results=3):
            return [
                _evidence(
                    "https://a.example.com/report",
                    "Internal memos schedule the product release for November 15.",
                    stance="conflicting",
                    confidence=0.72,
                ),
                _evidence(
                    "https://b.example.com/analysis",
                    "Supply chain analysts state the launch slipped to next year.",
                    stance="conflicting",
                    confidence=0.70,
                ),
            ]

    result = VerificationService(retriever=_Retriever()).verify_claim(
        _claim("The product release date is November 15.")
    )

    assert result.verdict == VerdictType.UNVERIFIABLE
    # The citations are still worth showing alongside the inconclusive verdict.
    assert len(result.sources) == 2
    assert result.source == result.sources[0]["url"]


def test_no_evidence_is_unverifiable_with_no_sources() -> None:
    class _Retriever:
        def retrieve(self, query, max_results=3):
            return []

    result = VerificationService(retriever=_Retriever()).verify_claim(_claim())
    assert result.verdict == VerdictType.UNVERIFIABLE
    assert result.sources == []
    assert result.source == "No source available"


# ---------------------------------------------------------------------------
# 6. Wire shape and adapter boundary
# ---------------------------------------------------------------------------


def test_backend_verification_event_defaults_sources_to_empty() -> None:
    """An event built without `sources` stays valid: the field is additive."""
    event = VerificationEvent(
        type="verification",
        claimId="c1",
        sessionId="s1",
        speaker="Speaker 1",
        timestamp=1.0,
        verdict=Verdict.TRUE,
        reason="Corroborated.",
        source="https://nasa.gov/apollo",
    )
    assert event.sources == []
    assert "sources" in event.to_wire()


def test_to_wire_sources_drops_urlless_and_duplicate_entries() -> None:
    wire = to_wire_sources(
        [
            {"url": "https://a.example.com/1", "title": "A", "snippet": "  x  "},
            {"url": "", "title": "No URL", "snippet": "y"},
            {"url": "https://a.example.com/1", "title": "Duplicate", "snippet": "z"},
            {"url": "  https://b.example.com/2  ", "title": "  ", "snippet": None},
            "not a dict",
        ]
    )
    assert [entry["url"] for entry in wire] == [
        "https://a.example.com/1",
        "https://b.example.com/2",
    ]
    assert wire[0]["snippet"] == "x"
    assert wire[1]["title"] is None


@pytest.mark.parametrize("value", [None, [], {}, "nope", 0])
def test_to_wire_sources_tolerates_absent_or_odd_input(value) -> None:
    assert to_wire_sources(value) == []


async def test_engine_exposes_sources_on_the_backend_event() -> None:
    """The adapter carries the ranked sources onto the backend contract."""

    class _Retriever:
        def retrieve(self, query, max_results=3):
            return [
                _evidence(
                    "https://espncricinfo.com/final",
                    "India won the 2011 ICC Cricket World Cup, defeating Sri Lanka.",
                    title="2011 Final",
                    stance="supports",
                    confidence=0.99,
                ),
                _evidence(
                    "https://icc-cricket.com/archive",
                    "India defeated Sri Lanka to win the 2011 World Cup.",
                    title="ICC Archive",
                    stance="supports",
                    confidence=0.95,
                ),
            ]

    event = await VerificationServiceEngine(
        service=VerificationService(retriever=_Retriever())
    ).verify(_claim())

    assert event.verdict == Verdict.TRUE
    assert event.source == "https://espncricinfo.com/final"
    assert len(event.sources) == 2
    assert event.sources[0]["title"] == "2011 Final"


async def test_engine_without_sources_field_still_verifies() -> None:
    """An engine that predates multi-source keeps working unchanged."""

    class _Service:
        def verify_claim(self, payload):
            class _Result:
                verdict = VerdictType.TRUE
                reason = "Corroborated by the archive."
                source = "https://nasa.gov/apollo"

            return _Result()

    event = await VerificationServiceEngine(service=_Service()).verify(
        _claim("Apollo 11 landed on the Moon in 1969.")
    )
    assert event.sources == []
    assert event.source == "https://nasa.gov/apollo"
