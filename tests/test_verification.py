"""Unit and integration tests for the Verification module.

Validates:
- Valid ClaimEvent inputs
- Strict claimId preservation
- All three verdict types (True, False, Unverifiable)
- Malformed inputs and schema validation
- No evidence scenarios
- Conflicting evidence scenarios
- Empty, whitespace, and numerical claim handling
- Batch processing and mock dataset integrity
"""

import pytest
from pydantic import ValidationError

from verification.checker import VerificationChecker, verify_claim_against_evidence
from verification.models import ClaimEvent, EvidenceItem, VerdictType, VerificationEvent
from verification.query_generator import clean_conversational_text, generate_search_query
from verification.retriever import MockRetriever
from verification.service import VerificationService, verify_claim_event
from tests.fixtures.mock_claims import MOCK_CLAIMS


def _seeded_verification_service() -> VerificationService:
    """Create a VerificationService with the standard test knowledge base."""
    retriever = MockRetriever()
    # Cricket World Cup 2011
    retriever.register_evidence(
        keywords=["cricket", "world cup", "2011", "india won", "india"],
        items=[
            EvidenceItem(
                snippet="India won the 2011 ICC Cricket World Cup, defeating Sri Lanka in the final at Wankhede Stadium in Mumbai.",
                source_url="https://www.espncricinfo.com/series/icc-cricket-world-cup-2010-11-381449/india-vs-sri-lanka-final-433606/match-report",
                title="2011 ICC Cricket World Cup Final",
                stance="supports",
                confidence=0.99,
            )
        ],
    )
    # Apollo 11 Moon landing
    retriever.register_evidence(
        keywords=["apollo", "moon", "1969", "neil armstrong", "astronauts", "nasa"],
        items=[
            EvidenceItem(
                snippet="NASA's Apollo 11 successfully landed humans on the Moon on July 20, 1969.",
                source_url="https://www.nasa.gov/mission_pages/apollo/apollo-11.html",
                title="NASA Apollo 11 Mission Overview",
                stance="supports",
                confidence=0.99,
            )
        ],
    )
    # Company units sold
    retriever.register_evidence(
        keywords=["company", "sold", "two million", "units", "million units"],
        items=[
            EvidenceItem(
                snippet="Official regulatory filings confirm the company sold 1.2 million units in fiscal year 2023.",
                source_url="https://sec.gov/edgar/filings/company-annual-2023.pdf",
                title="SEC Annual Disclosure Report 2023",
                stance="refutes",
                confidence=0.98,
            )
        ],
    )
    # Mount Everest location
    retriever.register_evidence(
        keywords=["mount everest", "everest", "africa", "highest peak", "peak in africa"],
        items=[
            EvidenceItem(
                snippet="Mount Everest is located in the Himalayas on the border of Nepal and China in Asia. Mount Kilimanjaro is the highest peak in Africa.",
                source_url="https://britannica.com/place/Mount-Everest",
                title="Encyclopaedia Britannica - Mount Everest",
                stance="refutes",
                confidence=0.99,
            )
        ],
    )
    # Product release date (conflicting)
    retriever.register_evidence(
        keywords=["product release", "november 15", "release date", "launch date"],
        items=[
            EvidenceItem(
                snippet="Tech Insider reports internal memos scheduling the product release for November 15.",
                source_url="https://techinsider.example.com/exclusive-launch-dates",
                title="Tech Insider Report",
                stance="conflicting",
                confidence=0.70,
            ),
            EvidenceItem(
                snippet="Supply chain analysts state production bottlenecks delayed the product launch to Q1 next year.",
                source_url="https://supplychaindaily.example.com/delays-confirmed",
                title="Supply Chain Daily",
                stance="conflicting",
                confidence=0.72,
            ),
        ],
    )
    return VerificationService(retriever=retriever)


# ---------------------------------------------------------------------------
# 1. Model & Validation Tests
# ---------------------------------------------------------------------------

def test_claim_event_valid_input():
    """Ensures valid claim input dictionaries parse correctly into ClaimEvent."""
    payload = {
        "type": "claim",
        "claimId": "claim_001",
        "speaker": "Speaker 1",
        "claim": "The company sold two million units.",
        "timestamp": 12.4,
    }
    event = ClaimEvent(**payload)
    assert event.type == "claim"
    assert event.claimId == "claim_001"
    assert event.speaker == "Speaker 1"
    assert event.claim == "The company sold two million units."
    assert event.timestamp == 12.4


@pytest.mark.parametrize(
    "malformed_payload",
    [
        # Missing claim
        {"type": "claim", "claimId": "claim_001", "speaker": "Speaker 1", "timestamp": 12.4},
        # Missing claimId
        {"type": "claim", "speaker": "Speaker 1", "claim": "Valid claim", "timestamp": 12.4},
        # Empty claim
        {"type": "claim", "claimId": "c1", "speaker": "S1", "claim": "", "timestamp": 12.4},
        # Whitespace-only claim
        {"type": "claim", "claimId": "c1", "speaker": "S1", "claim": "   ", "timestamp": 12.4},
        # Wrong type
        {"type": "wrong_type", "claimId": "c1", "speaker": "S1", "claim": "Valid", "timestamp": 12.4},
        # Negative timestamp
        {"type": "claim", "claimId": "c1", "speaker": "S1", "claim": "Valid", "timestamp": -5.0},
        # Extra unexpected fields (forbidden by strict model config)
        {"type": "claim", "claimId": "c1", "speaker": "S1", "claim": "Valid", "timestamp": 1.0, "extra": "field"},
    ],
)
def test_claim_event_malformed_inputs(malformed_payload):
    """Ensures malformed or invalid payloads are rejected with ValidationError."""
    with pytest.raises(ValidationError):
        ClaimEvent(**malformed_payload)


def test_verification_event_valid():
    """Ensures VerificationEvent matches agreed output contract."""
    event = VerificationEvent(
        type="verification",
        claimId="claim_001",
        verdict=VerdictType.FALSE,
        reason="The available source reports a different figure.",
        source="https://example.com",
    )
    dumped = event.model_dump()
    assert dumped["type"] == "verification"
    assert dumped["claimId"] == "claim_001"
    assert dumped["verdict"] == "False"
    assert dumped["reason"] == "The available source reports a different figure."
    assert dumped["source"] == "https://example.com"


def test_verification_event_rejects_invalid_verdict():
    """Ensures verdict accepts only True, False, or Unverifiable."""
    with pytest.raises(ValidationError):
        VerificationEvent(
            type="verification",
            claimId="claim_001",
            verdict="Maybe",  # Invalid
            reason="Uncertain statement",
            source="https://example.com",
        )


# ---------------------------------------------------------------------------
# 2. Query Generation Tests
# ---------------------------------------------------------------------------

def test_query_generator_cleans_speech_artifacts():
    """Ensures conversational prefixes and discourse markers are stripped."""
    raw = "Speaker 1 said that in my opinion the company sold two million units."
    query = generate_search_query(raw)
    assert "Speaker 1 said that" not in query
    assert "in my opinion" not in query
    assert "company sold two million units" in query


def test_query_generator_handles_empty_string():
    """Ensures empty or whitespace strings return empty queries without error."""
    assert generate_search_query("") == ""
    assert generate_search_query("   ") == ""


# ---------------------------------------------------------------------------
# 3. Pipeline & Claim ID Preservation Tests
# ---------------------------------------------------------------------------

def test_claim_id_preservation():
    """Ensures the original claimId is strictly preserved across the pipeline."""
    service = _seeded_verification_service()
    test_id = "unique_claim_id_9999"
    claim = {
        "type": "claim",
        "claimId": test_id,
        "speaker": "Speaker 1",
        "claim": "NASA's Apollo 11 landed humans on the Moon in July 1969.",
        "timestamp": 10.0,
    }
    result = service.verify_claim(claim)
    assert result.claimId == test_id


# ---------------------------------------------------------------------------
# 4. Verdict Types Tests (True / False / Unverifiable)
# ---------------------------------------------------------------------------

def _service_with_evidence(claim_text: str, evidence: list) -> VerificationService:
    """Helper to create a service with specific evidence for a claim."""
    from verification.retriever import MockRetriever
    retriever = MockRetriever()
    retriever.register_evidence(keywords=[claim_text], items=evidence)
    return VerificationService(retriever=retriever)


def test_verdict_true():
    """Tests a clearly true factual claim."""
    evidence = [
        EvidenceItem(
            snippet="NASA's Apollo 11 successfully landed humans on the Moon on July 20, 1969.",
            source_url="https://www.nasa.gov/mission_pages/apollo/apollo-11.html",
            title="NASA Apollo 11 Mission Overview",
            stance="supports",
            confidence=0.99,
        )
    ]
    service = _service_with_evidence(
        "NASA's Apollo 11 landed humans on the Moon in July 1969.", evidence
    )
    claim = {
        "type": "claim",
        "claimId": "claim_true_01",
        "speaker": "Speaker 2",
        "claim": "NASA's Apollo 11 landed humans on the Moon in July 1969.",
        "timestamp": 20.0,
    }
    result = service.verify_claim(claim)
    assert result.verdict == VerdictType.TRUE
    assert "nasa.gov" in result.source
    assert result.reason != ""


def test_verdict_false_geographical():
    """Tests a clearly false claim."""
    evidence = [
        EvidenceItem(
            snippet="Mount Everest is located in the Himalayas on the border of Nepal and China in Asia. Mount Kilimanjaro is the highest peak in Africa.",
            source_url="https://britannica.com/place/Mount-Everest",
            title="Encyclopaedia Britannica - Mount Everest",
            stance="refutes",
            confidence=0.99,
        )
    ]
    service = _service_with_evidence(
        "Mount Everest is the highest mountain peak in Africa.", evidence
    )
    claim = {
        "type": "claim",
        "claimId": "claim_false_01",
        "speaker": "Speaker 1",
        "claim": "Mount Everest is the highest mountain peak in Africa.",
        "timestamp": 35.0,
    }
    result = service.verify_claim(claim)
    assert result.verdict == VerdictType.FALSE
    assert "britannica.com" in result.source
    assert "contradict" in result.reason.lower() or "source" in result.reason.lower()


def test_verdict_false_numerical_contract_example():
    """Tests the exact sample claim from project specification."""
    evidence = [
        EvidenceItem(
            snippet="Official regulatory filings confirm the company sold 1.2 million units in fiscal year 2023.",
            source_url="https://sec.gov/edgar/filings/company-annual-2023.pdf",
            title="SEC Annual Disclosure Report 2023",
            stance="refutes",
            confidence=0.98,
        )
    ]
    service = _service_with_evidence(
        "The company sold two million units.", evidence
    )
    claim = {
        "type": "claim",
        "claimId": "claim_001",
        "speaker": "Speaker 1",
        "claim": "The company sold two million units.",
        "timestamp": 12.4,
    }
    result = service.verify_claim(claim)
    assert result.claimId == "claim_001"
    assert result.verdict == VerdictType.FALSE
    assert "different figure" in result.reason.lower() or "contradictory" in result.reason.lower()
    assert "sec.gov" in result.source


def test_verdict_unverifiable_no_evidence():
    """Tests an unverifiable claim with no matching evidence found."""
    service = VerificationService()
    claim = {
        "type": "claim",
        "claimId": "claim_unverifiable_01",
        "speaker": "Speaker 3",
        "claim": "The CEO privately considers strawberry ice cream his favorite dessert.",
        "timestamp": 50.0,
    }
    result = service.verify_claim(claim)
    assert result.verdict == VerdictType.UNVERIFIABLE
    assert "No verifiable evidence found" in result.reason


def test_verdict_unverifiable_conflicting_evidence():
    """Tests conflicting evidence reports leading to Unverifiable verdict."""
    evidence = [
        EvidenceItem(
            snippet="Tech Insider reports internal memos scheduling the product release for November 15.",
            source_url="https://techinsider.example.com/exclusive-launch-dates",
            title="Tech Insider Report",
            stance="conflicting",
            confidence=0.70,
        ),
        EvidenceItem(
            snippet="Supply chain analysts state production bottlenecks delayed the product launch to Q1 next year.",
            source_url="https://supplychaindaily.example.com/delays-confirmed",
            title="Supply Chain Daily",
            stance="conflicting",
            confidence=0.72,
        ),
    ]
    service = _service_with_evidence(
        "The new product release will occur exactly on November 15.", evidence
    )
    claim = {
        "type": "claim",
        "claimId": "claim_conflict_01",
        "speaker": "Speaker 2",
        "claim": "The new product release will occur exactly on November 15.",
        "timestamp": 60.0,
    }
    result = service.verify_claim(claim)
    assert result.verdict == VerdictType.UNVERIFIABLE
    assert "conflicting" in result.reason.lower() or "inconclusive" in result.reason.lower()


# ---------------------------------------------------------------------------
# 5. Checker Edge Cases (Direct Checker Tests)
# ---------------------------------------------------------------------------

def test_checker_weak_evidence():
    """Ensures evidence with confidence below threshold yields Unverifiable."""
    checker = VerificationChecker(min_confidence_threshold=0.8)
    weak_evidence = [
        EvidenceItem(
            snippet="Some unverified rumor on a blog.",
            source_url="https://unverifiedblog.example.com",
            stance="supports",
            confidence=0.3,
        )
    ]
    verdict, reason, source = checker.verify("Unverified assertion", weak_evidence)
    assert verdict == VerdictType.UNVERIFIABLE
    assert "sufficient confidence" in reason


def test_checker_opposing_stances():
    """Ensures mixed support and refutation stances yield Unverifiable."""
    checker = VerificationChecker()
    opposing_evidence = [
        EvidenceItem(
            snippet="Source A confirms the claim.",
            source_url="https://source-a.com",
            stance="supports",
            confidence=0.9,
        ),
        EvidenceItem(
            snippet="Source B refutes the claim.",
            source_url="https://source-b.com",
            stance="refutes",
            confidence=0.9,
        ),
    ]
    verdict, reason, source = checker.verify("Disputed assertion", opposing_evidence)
    assert verdict == VerdictType.UNVERIFIABLE
    assert "conflicting" in reason.lower()


# ---------------------------------------------------------------------------
# 6. Service Batch & Mock Dataset Tests
# ---------------------------------------------------------------------------

def _mock_retriever_with_all_claims() -> MockRetriever:
    """Build a MockRetriever with evidence for all MOCK_CLAIMS."""
    retriever = MockRetriever()
    
    # claim_001: The company sold two million units. -> FALSE
    retriever.register_evidence(
        keywords=["company sold two million units"],
        items=[EvidenceItem(
            snippet="Official regulatory filings confirm the company sold 1.2 million units in fiscal year 2023.",
            source_url="https://sec.gov/edgar/filings/company-annual-2023.pdf",
            title="SEC Annual Disclosure Report 2023",
            stance="refutes",
            confidence=0.98,
        )]
    )
    
    # claim_002: NASA's Apollo 11 landed humans on the Moon in July 1969. -> TRUE
    retriever.register_evidence(
        keywords=["NASA's Apollo 11 landed humans on the Moon in July 1969"],
        items=[EvidenceItem(
            snippet="NASA's Apollo 11 successfully landed humans on the Moon on July 20, 1969.",
            source_url="https://www.nasa.gov/mission_pages/apollo/apollo-11.html",
            title="NASA Apollo 11 Mission Overview",
            stance="supports",
            confidence=0.99,
        )]
    )
    
    # claim_003: Mount Everest is the highest mountain peak in Africa. -> FALSE
    retriever.register_evidence(
        keywords=["Mount Everest is the highest mountain peak in Africa"],
        items=[EvidenceItem(
            snippet="Mount Everest is located in the Himalayas on the border of Nepal and China in Asia. Mount Kilimanjaro is the highest peak in Africa.",
            source_url="https://britannica.com/place/Mount-Everest",
            title="Encyclopaedia Britannica - Mount Everest",
            stance="refutes",
            confidence=0.99,
        )]
    )
    
    # claim_004: CEO privately considers strawberry ice cream -> UNVERIFIABLE (no evidence)
    # claim_005: Product release Nov 15 -> UNVERIFIABLE (conflicting)
    retriever.register_evidence(
        keywords=["product release will occur exactly on November 15"],
        items=[
            EvidenceItem(
                snippet="Tech Insider reports internal memos scheduling the product release for November 15.",
                source_url="https://techinsider.example.com/exclusive-launch-dates",
                title="Tech Insider Report",
                stance="conflicting",
                confidence=0.70,
            ),
            EvidenceItem(
                snippet="Supply chain analysts state production bottlenecks delayed the product launch to Q1 next year.",
                source_url="https://supplychaindaily.example.com/delays-confirmed",
                title="Supply Chain Daily",
                stance="conflicting",
                confidence=0.72,
            ),
        ]
    )
    
    # claim_006: Inflation rate dropped 15% -> FALSE
    retriever.register_evidence(
        keywords=["national inflation rate dropped by 15%"],
        items=[EvidenceItem(
            snippet="The Bureau of Labor Statistics reported consumer inflation slowed by 0.5% year-over-year, not 15%.",
            source_url="https://bls.gov/cpi/latest-numbers.htm",
            title="Bureau of Labor Statistics Consumer Price Index",
            stance="refutes",
            confidence=0.95,
        )]
    )
    
    return retriever


def test_batch_verification():
    """Tests batch verification processing multiple claims."""
    retriever = _mock_retriever_with_all_claims()
    service = VerificationService(retriever=retriever)
    results = service.verify_batch(MOCK_CLAIMS)
    assert len(results) == len(MOCK_CLAIMS)
    for original, verified in zip(MOCK_CLAIMS, results):
        assert verified.claimId == original["claimId"]
        assert verified.verdict in (VerdictType.TRUE, VerdictType.FALSE, VerdictType.UNVERIFIABLE)
        assert verified.reason != ""
        assert verified.source != ""


def test_all_verdict_types_represented_in_mock_claims():
    """Ensures mock dataset exercises all three required verdict types."""
    retriever = _mock_retriever_with_all_claims()
    service = VerificationService(retriever=retriever)
    results = service.verify_batch(MOCK_CLAIMS)
    verdicts = {r.verdict for r in results}
    assert VerdictType.TRUE in verdicts
    assert VerdictType.FALSE in verdicts
    assert VerdictType.UNVERIFIABLE in verdicts


# ---------------------------------------------------------------------------
# 7. Interoperability & Plug-and-Play Tests for Teammate Integration
# ---------------------------------------------------------------------------

def test_verification_event_to_dict():
    """Ensures to_dict returns a valid plain dictionary matching the contract."""
    event = VerificationEvent(
        type="verification",
        claimId="claim_001",
        verdict=VerdictType.FALSE,
        reason="The available source reports a different figure.",
        source="https://example.com",
    )
    d = event.to_dict()
    assert isinstance(d, dict)
    assert d["type"] == "verification"
    assert d["claimId"] == "claim_001"
    assert d["verdict"] == "False"
    assert d["source"] == "https://example.com"


def test_service_verify_claim_dict_interface():
    """Ensures verify_claim_dict accepts a dict and returns an agreed dict."""
    evidence = [
        EvidenceItem(
            snippet="Official regulatory filings confirm the company sold 1.2 million units in fiscal year 2023.",
            source_url="https://sec.gov/edgar/filings/company-annual-2023.pdf",
            title="SEC Annual Disclosure Report 2023",
            stance="refutes",
            confidence=0.98,
        )
    ]
    retriever = MockRetriever()
    retriever.register_evidence(keywords=["The company sold two million units"], items=evidence)
    service = VerificationService(retriever=retriever)
    
    claim_dict = {
        "type": "claim",
        "claimId": "claim_atif_01",
        "speaker": "Speaker 1",
        "claim": "The company sold two million units.",
        "timestamp": 12.4,
    }
    result_dict = service.verify_claim_dict(claim_dict)
    assert isinstance(result_dict, dict)
    assert result_dict["type"] == "verification"
    assert result_dict["claimId"] == "claim_atif_01"
    assert result_dict["verdict"] == "False"
    assert result_dict["reason"] != ""
    assert result_dict["source"] != ""


def test_service_handles_forwarded_extra_fields():
    """Ensures verify_claim gracefully filters extra pipeline metadata (e.g. sessionId)."""
    evidence = [
        EvidenceItem(
            snippet="Official regulatory filings confirm the company sold 1.2 million units in fiscal year 2023.",
            source_url="https://sec.gov/edgar/filings/company-annual-2023.pdf",
            title="SEC Annual Disclosure Report 2023",
            stance="refutes",
            confidence=0.98,
        )
    ]
    retriever = MockRetriever()
    retriever.register_evidence(keywords=["The company sold two million units"], items=evidence)
    service = VerificationService(retriever=retriever)
    
    forwarded = {
        "type": "claim",
        "claimId": "claim_forwarded_01",
        "speaker": "Speaker 1",
        "claim": "The company sold two million units.",
        "timestamp": 12.4,
        "sessionId": "sess_abc123",
        "claimType": "statistical",
    }
    result = service.verify_claim(forwarded)
    assert result.claimId == "claim_forwarded_01"
    assert result.verdict == VerdictType.FALSE


def test_service_accepts_model_dump_object():
    """Ensures objects from another module with a model_dump method are accepted."""
    evidence = [
        EvidenceItem(
            snippet="NASA's Apollo 11 successfully landed humans on the Moon on July 20, 1969.",
            source_url="https://www.nasa.gov/mission_pages/apollo/apollo-11.html",
            title="NASA Apollo 11 Mission Overview",
            stance="supports",
            confidence=0.99,
        )
    ]
    retriever = MockRetriever()
    retriever.register_evidence(keywords=["NASA's Apollo 11 landed humans on the Moon in July 1969"], items=evidence)
    service = VerificationService(retriever=retriever)
    
    class FakeExternalClaim:
        def model_dump(self):
            return {
                "type": "claim",
                "claimId": "claim_ext_01",
                "speaker": "Speaker 2",
                "claim": "NASA's Apollo 11 landed humans on the Moon in July 1969.",
                "timestamp": 10.0,
            }

    result = service.verify_claim(FakeExternalClaim())
    assert result.claimId == "claim_ext_01"
    assert result.verdict == VerdictType.TRUE


# ---------------------------------------------------------------------------
# 8. WebSearchRetriever & Retriever Factory Tests
# ---------------------------------------------------------------------------

def test_retriever_factory_default(monkeypatch):
    """Ensures create_default_retriever defaults to MockRetriever unless key is set."""
    from verification.retriever import create_default_retriever, WebSearchRetriever

    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    retriever = create_default_retriever()
    assert isinstance(retriever, MockRetriever)

    monkeypatch.setenv("SEARCH_API_KEY", "test_key_123")
    retriever_with_key = create_default_retriever()
    assert isinstance(retriever_with_key, WebSearchRetriever)


def test_web_search_retriever_unconfigured_raises():
    """Ensures unconfigured WebSearchRetriever raises RetrieverConfigurationError."""
    from verification.retriever import RetrieverConfigurationError, WebSearchRetriever

    retriever = WebSearchRetriever(api_key=None)
    with pytest.raises(RetrieverConfigurationError) as exc_info:
        retriever.retrieve("test query")
    assert "SEARCH_API_KEY" in str(exc_info.value)


def test_web_search_retriever_with_custom_handler():
    """Ensures custom search_handler plug-in works seamlessly."""
    from verification.retriever import WebSearchRetriever

    def custom_search(query: str, max_results: int):
        return [
            EvidenceItem(
                snippet="Custom search confirmed the facts of this statement.",
                source_url="https://custom-search.example.com/result",
                stance="supports",
                confidence=0.95,
            )
        ]

    retriever = WebSearchRetriever(search_handler=custom_search)
    service = VerificationService(retriever=retriever)
    claim = {
        "type": "claim",
        "claimId": "claim_custom_search_01",
        "speaker": "Speaker 1",
        "claim": "A bespoke verifiable factual claim.",
        "timestamp": 5.0,
    }
    result = service.verify_claim(claim)
    assert result.verdict == VerdictType.TRUE
    assert result.source == "https://custom-search.example.com/result"


def test_web_search_retriever_parse_search_results():
    """Ensures parse_search_results normalizes third-party search results."""
    from verification.retriever import WebSearchRetriever

    raw_results = [
        {"title": "Doc 1", "snippet": "Official excerpt.", "url": "https://source1.com", "score": 0.9},
        {"title": "Doc 2", "body": "Alternative excerpt.", "link": "https://source2.com", "confidence": 0.85},
        {"title": "Doc 3", "snippet": "", "url": "https://empty.com"},
    ]
    items = WebSearchRetriever.parse_search_results(raw_results)
    assert len(items) == 2
    assert items[0].snippet == "Official excerpt."
    assert items[0].source_url == "https://source1.com"
    assert items[0].confidence == 0.9
    assert items[1].snippet == "Alternative excerpt."
    assert items[1].source_url == "https://source2.com"


# ---------------------------------------------------------------------------
# 9. Numerical & Empty Snippet Heuristics Tests
# ---------------------------------------------------------------------------

def test_heuristic_numerical_mismatch_unannotated():
    """Ensures unannotated snippet with numerical mismatch returns FALSE."""
    checker = VerificationChecker()
    evidence = [
        EvidenceItem(
            snippet="The organization disclosed it achieved five hundred users globally.",
            source_url="https://example.com/report",
            stance=None,
            confidence=0.9,
        )
    ]
    verdict, reason, source = checker.verify(
        "The organization achieved two million users globally.",
        evidence,
    )
    assert verdict == VerdictType.FALSE
    assert "different figure" in reason.lower()


def test_empty_evidence_snippet_filtered():
    """Ensures empty evidence snippets are filtered and result in Unverifiable."""
    checker = VerificationChecker()
    empty_evidence = [
        EvidenceItem(
            snippet="   ",
            source_url="https://example.com/empty",
            confidence=0.9,
        )
    ]
    verdict, reason, source = checker.verify("Some claim", empty_evidence)
    assert verdict == VerdictType.UNVERIFIABLE

