"""Integration tests for the Claim Extraction + Verification pipeline.

Verifies the end-to-end flow:
    TranscriptEvent -> ClaimEngine (LLM/fallback) -> ClaimEvent
    -> VerificationEngine (VerificationServiceEngine) -> VerificationEvent
"""

import pytest
from backend.adapters.claim_engine import LLMClaimEngine
from backend.adapters.verification import VerificationServiceEngine
from backend.router import EventRouter
from backend.schemas import TranscriptEvent, Verdict
from backend.session_manager import SessionManager
from backend.websocket_manager import WebSocketManager
from verification.models import VerdictType
from verification.service import VerificationService


@pytest.mark.asyncio
async def test_claim_to_verification_true_verdict():
    """Verify that Atif's demo claim extracts and Nayanika's engine verifies it as TRUE."""
    claim_engine = LLMClaimEngine()
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
    assert claim.claimId == "claim_001"
    assert "India won the 2011 Cricket World Cup" in claim.claim

    verif_engine = VerificationServiceEngine()
    verification = await verif_engine.verify(claim)

    assert verification.type == "verification"
    assert verification.claimId == claim.claimId
    assert verification.sessionId == claim.sessionId
    assert verification.verdict == Verdict.TRUE
    assert verification.source != "No source available"
    assert len(verification.reason) > 0


@pytest.mark.asyncio
async def test_claim_to_verification_false_verdict():
    """Verify that numerical exaggeration extracts and verifies as FALSE."""
    claim_engine = LLMClaimEngine()
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

    verif_engine = VerificationServiceEngine()
    verification = await verif_engine.verify(claim)

    assert verification.type == "verification"
    assert verification.claimId == claim.claimId
    assert verification.verdict == Verdict.FALSE
    assert "sec.gov" in verification.source


def test_direct_verification_service_interface():
    """Verify that verification.VerificationService accepts ClaimEvent and returns VerdictType."""
    claim_engine = LLMClaimEngine()
    transcript = TranscriptEvent(
        type="transcript",
        sessionId="sess_test_103",
        speaker="Speaker 2",
        text="India won the 2011 Cricket World Cup.",
        timestamp=4.0,
        isFinal=True,
    )
    # Using fallback claims helper directly
    fallback = claim_engine._get_fallback_claims(transcript.text)
    assert len(fallback) == 1

    svc = VerificationService()
    result = svc.verify_claim({
        "type": "claim",
        "claimId": "claim_999",
        "speaker": "Speaker 2",
        "claim": fallback[0]["claim"],
        "timestamp": 4.0,
        "sessionId": "sess_test_103",
        "claimType": fallback[0]["claimType"],
    })

    assert result.claimId == "claim_999"
    assert result.verdict == VerdictType.TRUE


@pytest.mark.asyncio
async def test_event_router_end_to_end():
    """Verify EventRouter handles a transcript end-to-end with real claim and verification engines."""
    sessions = SessionManager()
    websockets = WebSocketManager()
    claim_engine = LLMClaimEngine()
    verification_engine = VerificationServiceEngine()

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
