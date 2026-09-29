"""Shared fixtures for the backend test suite.

Every fixture builds a fresh application with fresh in-memory state and
deterministic mock engines, so tests never share session ids or claim ids.
"""

import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.mocks.mock_stream import MockClaimEngine, MockVerificationEngine

# Keep the environment deterministic regardless of any developer .env file.
os.environ["ENVIRONMENT"] = "test"
os.environ["USE_MOCK_ENGINES"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"
# Explicitly unset credentials so tests are isolated from developer .env
os.environ["ASSEMBLYAI_API_KEY"] = ""
os.environ["LLM_GATEWAY_API_KEY"] = ""
os.environ["SEARCH_API_KEY"] = ""


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        environment="test",
        use_mock_engines=True,
        log_level="WARNING",
        log_json=False,
    )


@pytest.fixture()
def claim_engine() -> MockClaimEngine:
    return MockClaimEngine()


@pytest.fixture()
def verification_engine() -> MockVerificationEngine:
    return MockVerificationEngine()


@pytest.fixture()
def app(settings, claim_engine, verification_engine):
    return create_app(
        settings=settings,
        claim_engine=claim_engine,
        verification_engine=verification_engine,
    )


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def session_id(client: TestClient) -> str:
    """Create a session and return its id."""
    response = client.post("/session/start", json={})
    assert response.status_code == 201, response.text
    return response.json()["sessionId"]


def transcript_payload(session_id: str, **overrides) -> dict:
    """A valid transcript event body."""
    payload = {
        "type": "transcript",
        "sessionId": session_id,
        "speaker": "Speaker 1",
        "text": "India won the 2011 Cricket World Cup.",
        "timestamp": 12.4,
        "isFinal": True,
    }
    payload.update(overrides)
    return payload


def claim_payload(session_id: str, **overrides) -> dict:
    """A valid claim event body."""
    payload = {
        "type": "claim",
        "claimId": "claim_001",
        "sessionId": session_id,
        "speaker": "Speaker 1",
        "timestamp": 12.4,
        "claim": "India won the 2011 Cricket World Cup.",
        "claimType": "historical_fact",
    }
    payload.update(overrides)
    return payload


def verification_payload(session_id: str, **overrides) -> dict:
    """A valid verification event body."""
    payload = {
        "type": "verification",
        "claimId": "claim_001",
        "sessionId": session_id,
        "speaker": "Speaker 1",
        "timestamp": 12.4,
        "verdict": "TRUE",
        "reason": "India defeated Sri Lanka in the 2011 final.",
        "source": "https://example.com/source",
    }
    payload.update(overrides)
    return payload
