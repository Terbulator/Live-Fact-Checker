import json
import pytest
from backend.adapters.claim_engine import LLMClaimEngine
from backend.schemas import TranscriptEvent
from tests.backend.test_llm_claim_engine import _stub_gateway, _claims_json, _settings, GATEWAY_KEY


@pytest.mark.asyncio
async def test_claim_extraction_valid_historical_fact(monkeypatch: pytest.MonkeyPatch):
    _stub_gateway(monkeypatch, _claims_json(("India won the 2011 Cricket World Cup.", "historical_fact")))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    transcript = TranscriptEvent(
        type="transcript",
        sessionId="session_001",
        speaker="Speaker 1",
        text="India won the 2011 Cricket World Cup.",
        timestamp=12.4,
        isFinal=True,
    )
    claims = await engine.extract_claims(transcript)
    assert len(claims) == 1
    c = claims[0]
    assert c.type == "claim"
    assert c.claimId == "session_001_claim_001"
    assert c.sessionId == "session_001"
    assert c.speaker == "Speaker 1"
    assert c.timestamp == 12.4
    assert c.claim == "India won the 2011 Cricket World Cup."
    assert c.claimType == "historical_fact"


@pytest.mark.asyncio
async def test_claim_extraction_opinion_filtering(monkeypatch: pytest.MonkeyPatch):
    # Opinion-like text should result in empty claims from the LLM
    _stub_gateway(monkeypatch, '{"claims": []}')
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    transcript = TranscriptEvent(
        type="transcript",
        sessionId="session_001",
        speaker="Speaker 1",
        text="I think India has the best cricket team and it was an amazing match.",
        timestamp=15.0,
        isFinal=True,
    )
    claims = await engine.extract_claims(transcript)
    assert len(claims) == 0


@pytest.mark.asyncio
async def test_duplicate_claim_prevention(monkeypatch: pytest.MonkeyPatch):
    _stub_gateway(
        monkeypatch,
        _claims_json(("The company sold two million units.", "statistic")),
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    transcript_1 = TranscriptEvent(
        type="transcript",
        sessionId="session_001",
        speaker="Speaker 1",
        text="The company sold two million units.",
        timestamp=10.0,
        isFinal=True,
    )
    transcript_2 = TranscriptEvent(
        type="transcript",
        sessionId="session_001",
        speaker="Speaker 1",
        text="The company sold two million units.",
        timestamp=12.0,
        isFinal=True,
    )
    claims_1 = await engine.extract_claims(transcript_1)
    claims_2 = await engine.extract_claims(transcript_2)

    assert len(claims_1) == 1
    assert len(claims_2) == 0
    assert claims_1[0].claimId == "session_001_claim_001"