"""Mock pipeline and identity-preservation tests (required checks 12, 13, 14).

These tests also cover the adapter boundary, including the explicit verdict
translation between the backend wire format (``TRUE``) and the existing
``verification`` module format (``True``).
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
import backend.mocks.mock_stream as mock_stream
from backend.adapters.claim_engine import StaticClaimEngine
from backend.adapters.verification import (
    VERDICT_TO_WIRE,
    VerificationServiceEngine,
    to_internal_claim_payload,
    to_internal_verdict,
    to_wire_verdict,
)
from backend.config import Settings
from backend.main import create_app
from backend.mocks.mock_stream import (
    NO_RULE_REASON,
    NO_RULE_SOURCE,
    REFERENCE_CLAIM_TEXT,
    REFERENCE_SPEAKER,
    REFERENCE_TIMESTAMP,
    MockClaimEngine,
    MockVerificationEngine,
    build_mock_transcript,
)
from backend.schemas import ClaimEvent, Verdict
from tests.backend.conftest import claim_payload, transcript_payload

REFERENCE_SOURCE = "https://example.com/source"
REFERENCE_REASON = "India defeated Sri Lanka in the 2011 final."


def _reference_claim(session_id: str, claim_id: str = "claim_001") -> ClaimEvent:
    return ClaimEvent(
        claimId=claim_id,
        sessionId=session_id,
        speaker=REFERENCE_SPEAKER,
        timestamp=REFERENCE_TIMESTAMP,
        claim=REFERENCE_CLAIM_TEXT,
        claimType="historical_fact",
    )


class _ExplodingVerificationService:
    """Stands in for a verification service whose dependency is unavailable."""

    def verify_claim(self, claim_input):
        raise ConnectionError("evidence provider unreachable")


def _drain_until(websocket, expected_type: str, limit: int = 16) -> dict:
    for _ in range(limit):
        message = websocket.receive_json()
        if message.get("type") == expected_type:
            return message
    raise AssertionError(f"No {expected_type} event received within {limit} messages.")


# ---------------------------------------------------------------------------
# 12. Mock transcript -> claim -> verification pipeline
# ---------------------------------------------------------------------------

def test_mock_pipeline_produces_expected_claim_and_verification(
    client: TestClient, session_id: str
) -> None:
    response = client.post("/events/transcript", json=transcript_payload(session_id))
    assert response.status_code == 202

    body = response.json()
    assert len(body["claims"]) == 1
    assert len(body["verifications"]) == 1

    claim = body["claims"][0]
    assert claim["type"] == "claim"
    assert claim["eventId"]
    assert claim["claimId"] == "claim_001"
    assert claim["sessionId"] == session_id
    assert claim["speaker"] == REFERENCE_SPEAKER
    assert claim["timestamp"] == REFERENCE_TIMESTAMP
    assert claim["claim"] == REFERENCE_CLAIM_TEXT
    assert claim["claimType"] == "historical_fact"

    verification = body["verifications"][0]
    assert verification["type"] == "verification"
    assert verification["eventId"]
    assert verification["claimId"] == "claim_001"
    assert verification["sessionId"] == session_id
    assert verification["speaker"] == REFERENCE_SPEAKER
    assert verification["timestamp"] == REFERENCE_TIMESTAMP
    assert verification["verdict"] == "TRUE"
    assert verification["reason"] == REFERENCE_REASON
    assert verification["source"] == REFERENCE_SOURCE


def test_mock_pipeline_runs_without_any_api_key(
    client: TestClient, session_id: str
) -> None:
    """No AssemblyAI, LLM or search credential is present in the test env."""
    health = client.get("/health").json()
    assert health["credentialsConfigured"] == {
        "assemblyai": False,
        "llmGateway": False,
        "search": False,
    }
    assert client.post(
        "/events/transcript", json=transcript_payload(session_id)
    ).status_code == 202


def test_mock_pipeline_ignores_non_claimable_transcript(
    client: TestClient, session_id: str
) -> None:
    response = client.post(
        "/events/transcript",
        json=transcript_payload(
            session_id, text="Good evening, and welcome to the show.", timestamp=1.2
        ),
    )
    body = response.json()
    assert body["claims"] == []
    assert body["verifications"] == []
    assert body["counts"] == {"claims": 0, "verifications": 0, "errors": 0}


def test_start_session_with_mock_pipeline_option(client: TestClient) -> None:
    """`startMockPipeline` replays the scripted demo into a live session."""
    response = client.post("/session/start", json={"startMockPipeline": True})
    assert response.status_code == 201
    new_session = response.json()["sessionId"]

    # The scripted stream runs in the background; wait for all three segments.
    deadline = time.time() + 10.0
    state: dict = {}
    while time.time() < deadline:
        state = client.get(f"/session/{new_session}").json()
        if state["transcriptCount"] >= len(mock_stream.MOCK_TRANSCRIPT_SCRIPT):
            break
        time.sleep(0.1)

    assert state["transcriptCount"] == 3
    # Segment 1 is a greeting (no claim), segments 2 and 3 each yield a claim.
    assert state["claimCount"] == 2
    assert state["verificationCount"] == 2
    assert state["errorCount"] == 0


def test_mock_scripted_stream_broadcasts_reference_claim(client: TestClient) -> None:
    """Drive the scripted stream directly and assert the reference result."""
    session_id = client.post("/session/start", json={}).json()["sessionId"]

    with client.websocket_connect(f"/ws/session/{session_id}") as websocket:
        _drain_until(websocket, "session")
        asyncio.run(
            mock_stream.stream_mock_transcripts(
                client.app.state.router,
                client.app.state.session_manager,
                session_id,
                delay=0,
            )
        )

        verification = _drain_until(websocket, "verification")
        assert verification["claimId"] == "claim_001"
        assert verification["sessionId"] == session_id
        assert verification["verdict"] == "TRUE"
        assert verification["reason"] == REFERENCE_REASON


# ---------------------------------------------------------------------------
# 13. claimId preservation
# ---------------------------------------------------------------------------

def test_claim_id_is_preserved_through_verification(
    client: TestClient, session_id: str
) -> None:
    claim_id = "claim_speaker_2_xyz"
    response = client.post(
        "/events/claim", json=claim_payload(session_id, claimId=claim_id)
    )
    body = response.json()
    assert body["verifications"][0]["claimId"] == claim_id
    assert body["claim"]["claimId"] == claim_id


def test_claim_id_is_preserved_over_the_websocket(
    client: TestClient, session_id: str
) -> None:
    claim_id = "claim_ws_roundtrip"
    with client.websocket_connect(f"/ws/session/{session_id}") as websocket:
        _drain_until(websocket, "session")
        client.post("/events/claim", json=claim_payload(session_id, claimId=claim_id))

        claim = _drain_until(websocket, "claim")
        verification = _drain_until(websocket, "verification")
        assert claim["claimId"] == verification["claimId"] == claim_id


def test_distinct_claims_get_distinct_ids(client: TestClient, session_id: str) -> None:
    first = client.post("/events/transcript", json=transcript_payload(session_id)).json()
    second = client.post(
        "/events/transcript",
        json=transcript_payload(
            session_id,
            text="Mount Everest is the highest mountain peak in Africa.",
            timestamp=31.8,
        ),
    ).json()

    ids = [first["claims"][0]["claimId"], second["claims"][0]["claimId"]]
    assert ids == ["claim_001", "claim_002"]
    assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# 14. sessionId preservation
# ---------------------------------------------------------------------------

def test_session_id_is_preserved_across_the_pipeline(
    client: TestClient, session_id: str
) -> None:
    body = client.post("/events/transcript", json=transcript_payload(session_id)).json()
    for event in (body["transcript"], body["claims"][0], body["verifications"][0]):
        assert event["sessionId"] == session_id


def test_backend_reassigns_session_id_on_transcript_events(
    client: TestClient, session_id: str
) -> None:
    """A claim carrying a stale sessionId is corrected by the backend."""
    stale_session = "session_999"
    client.post("/session/start", json={})  # creates session_002

    body = client.post(
        "/events/claim", json=claim_payload(session_id, claimId="claim_stale_01")
    ).json()

    assert body["verifications"][0]["sessionId"] == session_id
    assert body["verifications"][0]["claimId"] == "claim_stale_01"


def test_session_id_is_preserved_on_inbound_verification(
    client: TestClient, session_id: str
) -> None:
    response = client.post(
        "/events/verification",
        json={
            "type": "verification",
            "claimId": "claim_ext_01",
            "sessionId": session_id,
            "speaker": "Speaker 2",
            "timestamp": 7.5,
            "verdict": "UNVERIFIABLE",
            "reason": "No authoritative source was found in time.",
            "source": "https://example.com/source",
        },
    )
    assert response.status_code == 202
    assert response.json()["verification"]["sessionId"] == session_id
    assert response.json()["verification"]["claimId"] == "claim_ext_01"


# ---------------------------------------------------------------------------
# Adapter boundary: verdict translation
# ---------------------------------------------------------------------------

def test_verdict_translation_maps_internal_to_wire() -> None:
    assert to_wire_verdict("True") is Verdict.TRUE
    assert to_wire_verdict("False") is Verdict.FALSE
    assert to_wire_verdict("Unverifiable") is Verdict.UNVERIFIABLE
    assert VERDICT_TO_WIRE["True"] is Verdict.TRUE


def test_verdict_translation_maps_wire_to_internal() -> None:
    assert to_internal_verdict("TRUE") == "True"
    assert to_internal_verdict(Verdict.FALSE) == "False"
    assert to_internal_verdict(Verdict.UNVERIFIABLE) == "Unverifiable"


def test_verdict_translation_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        to_wire_verdict("Maybe")
    with pytest.raises(ValueError):
        to_internal_verdict("MAYBE")


def test_internal_claim_payload_drops_backend_only_fields() -> None:
    """sessionId and claimType are not sent to the internal model."""
    claim = ClaimEvent(
        claimId="claim_001",
        sessionId="session_001",
        speaker="Speaker 1",
        timestamp=12.4,
        claim=REFERENCE_CLAIM_TEXT,
        claimType="historical_fact",
    )
    payload = to_internal_claim_payload(claim)
    assert set(payload) == {"type", "claimId", "speaker", "claim", "timestamp"}
    assert "sessionId" not in payload
    assert "claimType" not in payload


@pytest.mark.asyncio
async def test_bridge_to_existing_verification_module() -> None:
    """The real `verification` package is reachable through the adapter."""
    engine = VerificationServiceEngine()
    claim = ClaimEvent(
        claimId="claim_bridge_01",
        sessionId="session_001",
        speaker="Speaker 1",
        timestamp=12.4,
        claim=REFERENCE_CLAIM_TEXT,
        claimType="historical_fact",
    )
    result = await engine.verify(claim)

    assert result.claimId == "claim_bridge_01"
    assert result.sessionId == "session_001"
    assert result.verdict in set(Verdict)
    assert result.reason


@pytest.mark.asyncio
async def test_bridge_preserves_session_id_for_unverifiable_claims() -> None:
    engine = VerificationServiceEngine()
    claim = ClaimEvent(
        claimId="claim_bridge_02",
        sessionId="session_042",
        speaker="Speaker 3",
        timestamp=99.9,
        claim="The CEO privately considers strawberry ice cream his favorite dessert.",
        claimType="other",
    )
    result = await engine.verify(claim)
    assert result.sessionId == "session_042"
    assert result.verdict is Verdict.UNVERIFIABLE


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------

def test_unavailable_engines_emit_error_events_instead_of_crashing(
    claim_engine, verification_engine
) -> None:
    settings = Settings(environment="test", use_mock_engines=False, log_level="WARNING")
    app = create_app(
        settings=settings,
        claim_engine=claim_engine,
        verification_engine=verification_engine,
    )
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"


# ---------------------------------------------------------------------------
# FIX 1: the real verification engine is reachable from the running app
# ---------------------------------------------------------------------------

REAL_SETTINGS = Settings(environment="test", use_mock_engines=False, log_level="WARNING")


def test_mock_mode_still_selects_the_mock_engines() -> None:
    """Regression guard: the offline demo path is untouched."""
    settings = Settings(environment="test", use_mock_engines=True, log_level="WARNING")
    app = create_app(settings=settings)
    with TestClient(app) as client:
        engines = client.get("/health").json()["engines"]
    assert engines["claimEngine"] == "mock-claim-engine"
    assert engines["verificationEngine"] == "mock-verification-engine"


def test_real_verification_engine_is_wired_without_code_changes() -> None:
    """`use_mock_engines=false` reaches the existing verification package."""
    app = create_app(settings=REAL_SETTINGS)
    assert app.state.verification_engine.name == "verification-service"
    # Atif's claim module is not integrated yet, so claims stay unavailable.
    assert app.state.claim_engine.name == "unavailable-claim-engine"

    with TestClient(app) as client:
        assert client.get("/health").json()["engines"]["verificationEngine"] == (
            "verification-service"
        )


def test_real_engine_verifies_claims_through_the_running_pipeline(
    claim_engine: MockClaimEngine,
) -> None:
    """A mock-extracted claim is verified by the real verification module.

    No API key is present in the test environment: the service runs on its
    default offline retriever.
    """
    app = create_app(settings=REAL_SETTINGS, claim_engine=claim_engine)
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        response = client.post(
            "/events/transcript", json=transcript_payload(session)
        )

    assert response.status_code == 202
    body = response.json()
    assert body["counts"]["errors"] == 0
    assert len(body["verifications"]) == 1
    verification = body["verifications"][0]
    assert verification["verdict"] in {"TRUE", "FALSE", "UNVERIFIABLE"}
    assert verification["reason"]
    assert verification["source"]
    # sessionId stays backend-owned across the real-engine boundary.
    assert verification["sessionId"] == session
    assert verification["claimId"] == body["claims"][0]["claimId"]


def test_missing_verification_package_degrades_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unimportable verification package must not stop the service starting."""
    def explode(*args, **kwargs):
        raise ImportError("No module named 'verification'")

    monkeypatch.setattr(backend_main, "VerificationServiceEngine", explode)

    app = create_app(settings=REAL_SETTINGS)
    assert app.state.verification_engine.name == "unavailable-verification-engine"

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"


def test_failing_verification_dependency_produces_a_structured_error() -> None:
    """A real engine whose dependency blows up becomes an error event, not a 500."""
    app = create_app(
        settings=REAL_SETTINGS,
        claim_engine=StaticClaimEngine([_reference_claim("session_001")]),
        verification_engine=VerificationServiceEngine(
            service=_ExplodingVerificationService()
        ),
    )
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        body = client.post(
            "/events/transcript", json=transcript_payload(session)
        ).json()

    assert body["counts"] == {"claims": 1, "verifications": 0, "errors": 1}
    assert body["verifications"] == []


# ---------------------------------------------------------------------------
# FIX 4: an unknown claim is UNVERIFIABLE, not an engine failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_verifier_returns_unverifiable_for_an_unknown_claim() -> None:
    engine = MockVerificationEngine()
    result = await engine.verify(
        ClaimEvent(
            claimId="claim_unknown_99",
            sessionId="session_007",
            speaker="Speaker 2",
            timestamp=3.5,
            claim="A statement the offline mock has never been taught.",
            claimType="statistic",
        )
    )
    assert result.verdict is Verdict.UNVERIFIABLE
    assert result.reason == NO_RULE_REASON
    assert result.source == NO_RULE_SOURCE
    assert result.claimId == "claim_unknown_99"
    assert result.sessionId == "session_007"


@pytest.mark.asyncio
async def test_mock_verifier_still_answers_known_claims() -> None:
    engine = MockVerificationEngine()
    result = await engine.verify(_reference_claim("session_001"))
    assert result.verdict is Verdict.TRUE
    assert result.reason == REFERENCE_REASON
    assert result.source == REFERENCE_SOURCE


def test_mock_transcript_builder_is_deterministic(session_id: str) -> None:
    event = build_mock_transcript(session_id, index=2)
    assert event.text == REFERENCE_CLAIM_TEXT
    assert event.timestamp == REFERENCE_TIMESTAMP
    assert event.speaker == REFERENCE_SPEAKER
    assert event.sessionId == session_id
