"""Integration tests for the Claim Extraction + Verification pipeline.

Verifies the end-to-end flow:
    TranscriptEvent -> ClaimEngine (LLM/fallback) -> ClaimEvent
    -> VerificationEngine (VerificationServiceEngine) -> VerificationEvent
"""

import json
import pytest
from backend.adapters.claim_engine import LLMClaimEngine
from backend.adapters.verification import VerificationServiceEngine
from backend.router import EventRouter
from backend.schemas import TranscriptEvent, Verdict
from backend.session_manager import SessionManager
from backend.websocket_manager import WebSocketManager
from verification.models import VerdictType, EvidenceItem
from verification.service import VerificationService
from verification.retriever import MockRetriever
from tests.backend.test_llm_claim_engine import _stub_gateway, _claims_json, _settings, GATEWAY_KEY


def _seeded_mock_retriever() -> MockRetriever:
    """Create a MockRetriever with the standard test knowledge base."""
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
    return retriever


@pytest.mark.asyncio
async def test_claim_to_verification_true_verdict(monkeypatch: pytest.MonkeyPatch):
    """Verify that a claim extracts and verifies as TRUE via dynamic search."""
    _stub_gateway(monkeypatch, _claims_json(("India won the 2011 Cricket World Cup.", "historical_fact")))
    claim_engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    transcript = TranscriptEvent(
        type="transcript",
        sessionId="sess_test_101",
        speaker="Speaker 1",
        text="India won the 2011 Cricket World Cup.",
        timestamp=12.4,
        isFinal=True,
    )

    claims = await claim_engine.extract_claims(transcript)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.claimId == "sess_test_101_claim_001"
    assert "India won the 2011 Cricket World Cup" in claim.claim

    verif_engine = VerificationServiceEngine(retriever=_seeded_mock_retriever())
    verification = await verif_engine.verify(claim)

    assert verification.type == "verification"
    assert verification.claimId == claim.claimId
    assert verification.sessionId == claim.sessionId
    assert verification.verdict == Verdict.TRUE
    assert verification.source != "No source available"
    assert len(verification.reason) > 0


@pytest.mark.asyncio
async def test_claim_to_verification_false_verdict(monkeypatch: pytest.MonkeyPatch):
    """Verify that a false claim extracts and verifies as FALSE via dynamic search."""
    _stub_gateway(monkeypatch, _claims_json(("The company sold two million units in the quarter.", "statistic")))
    claim_engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    transcript = TranscriptEvent(
        type="transcript",
        sessionId="sess_test_102",
        speaker="Speaker 1",
        text="The company sold two million units in the quarter.",
        timestamp=8.0,
        isFinal=True,
    )

    claims = await claim_engine.extract_claims(transcript)
    assert len(claims) == 1
    claim = claims[0]

    verif_engine = VerificationServiceEngine(retriever=_seeded_mock_retriever())
    verification = await verif_engine.verify(claim)

    assert verification.type == "verification"
    assert verification.claimId == claim.claimId
    assert verification.verdict == Verdict.FALSE
    assert "sec.gov" in verification.source


def test_direct_verification_service_interface():
    """Verify that verification.VerificationService accepts ClaimEvent and returns VerdictType."""
    svc = VerificationService(retriever=_seeded_mock_retriever())
    result = svc.verify_claim({
        "type": "claim",
        "claimId": "claim_999",
        "speaker": "Speaker 2",
        "claim": "India won the 2011 Cricket World Cup.",
        "timestamp": 4.0,
        "sessionId": "sess_test_103",
        "claimType": "historical_fact",
    })

    assert result.claimId == "claim_999"
    assert result.verdict == VerdictType.TRUE


@pytest.mark.asyncio
async def test_event_router_end_to_end(monkeypatch: pytest.MonkeyPatch):
    """Verify EventRouter handles a transcript end-to-end with real claim and verification engines."""
    _stub_gateway(monkeypatch, _claims_json(("India won the 2011 Cricket World Cup.", "historical_fact")))
    sessions = SessionManager()
    websockets = WebSocketManager()
    claim_engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    verification_engine = VerificationServiceEngine(retriever=_seeded_mock_retriever())

    router = EventRouter(
        session_manager=sessions,
        websocket_manager=websockets,
        claim_engine=claim_engine,
        verification_engine=verification_engine,
    )

    session = await sessions.create()
    transcript = TranscriptEvent(
        type="transcript",
        sessionId=session.sessionId,
        speaker="Speaker 1",
        text="India won the 2011 Cricket World Cup.",
        timestamp=10.0,
        isFinal=True,
    )

    counts, claims, verifications = await router.handle_transcript(transcript)

    assert counts.claims == 1
    assert counts.verifications == 1
    assert counts.errors == 0
    assert len(claims) == 1
    assert len(verifications) == 1
    assert verifications[0].verdict == Verdict.TRUE
    assert verifications[0].claimId == claims[0].claimId


@pytest.mark.asyncio
async def test_claim_deduplication_session_isolation(monkeypatch: pytest.MonkeyPatch):
    """Same claim in different sessions must both be processed; duplicate in same session filtered."""
    _stub_gateway(monkeypatch, _claims_json(("India won the 2011 Cricket World Cup.", "historical_fact")))
    claim_engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    # Session A: first occurrence
    transcript_a = TranscriptEvent(
        type="transcript",
        sessionId="session_A",
        speaker="Speaker 1",
        text="India won the 2011 Cricket World Cup.",
        timestamp=10.0,
        isFinal=True,
    )
    claims_a = await claim_engine.extract_claims(transcript_a)
    assert len(claims_a) == 1
    assert claims_a[0].claimId == "session_A_claim_001"

    # Session B: same claim text, different session -> should NOT be filtered
    transcript_b = TranscriptEvent(
        type="transcript",
        sessionId="session_B",
        speaker="Speaker 1",
        text="India won the 2011 Cricket World Cup.",
        timestamp=10.0,
        isFinal=True,
    )
    claims_b = await claim_engine.extract_claims(transcript_b)
    assert len(claims_b) == 1
    assert claims_b[0].claimId == "session_B_claim_001"

    # Session A again: duplicate -> should be filtered
    claims_a_dup = await claim_engine.extract_claims(transcript_a)
    assert len(claims_a_dup) == 0

    # Session B again: duplicate -> should be filtered
    claims_b_dup = await claim_engine.extract_claims(transcript_b)
    assert len(claims_b_dup) == 0


@pytest.mark.asyncio
async def test_claim_id_unique_across_sessions(monkeypatch: pytest.MonkeyPatch):
    """Claim IDs must include session prefix to prevent collisions."""
    _stub_gateway(monkeypatch, _claims_json(("India won the 2011 Cricket World Cup.", "historical_fact")))
    claim_engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    transcript_a = TranscriptEvent(
        type="transcript",
        sessionId="session_A",
        speaker="Speaker 1",
        text="India won the 2011 Cricket World Cup.",
        timestamp=10.0,
        isFinal=True,
    )
    transcript_b = TranscriptEvent(
        type="transcript",
        sessionId="session_B",
        speaker="Speaker 1",
        text="India won the 2011 Cricket World Cup.",
        timestamp=10.0,
        isFinal=True,
    )

    claims_a = await claim_engine.extract_claims(transcript_a)
    claims_b = await claim_engine.extract_claims(transcript_b)

    assert claims_a[0].claimId != claims_b[0].claimId
    assert claims_a[0].claimId.startswith("session_A_claim_")
    assert claims_b[0].claimId.startswith("session_B_claim_")
