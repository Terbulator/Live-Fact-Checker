"""Tests for Atif's ``LLMClaimEngine`` and its production wiring.

Covers the two integration defects fixed here:

1. ``seen_claims``/``claim_counter`` were typed ``set``/``int`` but indexed by
   session id, so every extraction raised ``TypeError``.
2. ``_default_claim_engine`` returned ``UnavailableClaimEngine`` in real mode,
   so ``LLMClaimEngine`` was never reachable from the running service.

The LLM Gateway is always stubbed: no test performs a real network call, and
no test can see a real credential (``tests/conftest.py`` empties them all).
"""

import json
from typing import Any, Dict, List, Optional, Union

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.claim_engine import (
    ClaimEngineError,
    LLMClaimEngine,
    UnavailableClaimEngine,
)
from backend.adapters.verification import VerificationServiceEngine
from backend.config import Settings
from backend.main import _default_claim_engine, create_app
from backend.mocks.mock_stream import MockClaimEngine
from backend.router import EventRouter
from backend.schemas import ClaimEvent, TranscriptEvent, Verdict
from backend.session_manager import SessionManager
from backend.websocket_manager import WebSocketManager
from tests.backend.conftest import transcript_payload

GATEWAY_KEY = "test-llm-gateway-key"
GATEWAY_BASE_URL = "https://api.assemblyai.com/llm/v1"
GATEWAY_MODEL = "qwen3.5-4b-32k-fast"

#: A real-mode deployment with no LLM credential in the environment.
REAL_SETTINGS_NO_KEY = Settings(
    environment="test", use_mock_engines=False, log_level="WARNING"
)


def _settings(**overrides: Any) -> Settings:
    return Settings(
        environment="test", use_mock_engines=False, log_level="WARNING", **overrides
    )


def _transcript(session_id: str, text: str = "Some spoken words.", ts: float = 1.0):
    return TranscriptEvent(
        type="transcript",
        sessionId=session_id,
        speaker="Speaker 1",
        text=text,
        timestamp=ts,
        isFinal=True,
    )


# ---------------------------------------------------------------------------
# LLM Gateway stub
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


def _stub_gateway(
    monkeypatch: pytest.MonkeyPatch,
    content: Union[str, List[str], None],
) -> Dict[str, Any]:
    """Replace ``httpx.AsyncClient.post`` and return a record of the request.

    ``content`` is the raw assistant message text. A list is consumed one entry
    per call, so a test can drive a multi-turn conversation. ``None`` produces
    a response with no ``content`` field at all.
    """
    recorded: Dict[str, Any] = {}
    replies = content if isinstance(content, list) else None
    calls = {"n": 0}

    async def fake_post(self, url, **kwargs):
        recorded["url"] = url
        recorded["headers"] = kwargs.get("headers", {})
        recorded["json"] = kwargs.get("json", {})
        calls["n"] += 1
        if replies is None:
            text = content
        else:
            text = replies[min(calls["n"] - 1, len(replies) - 1)]
        message = {} if text is None else {"content": text}
        return _StubResponse({"choices": [{"message": message}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return recorded


def _claims_json(*pairs: Any) -> str:
    """Build a gateway reply of the documented JSON shape."""
    return json.dumps(
        {
            "claims": [
                {"claim": claim, "claimType": claim_type} for claim, claim_type in pairs
            ]
        }
    )


# ---------------------------------------------------------------------------
# 1 / 2. Engine selection is driven by USE_MOCK_ENGINES
# ---------------------------------------------------------------------------


def test_use_mock_engines_true_selects_mock_claim_engine() -> None:
    settings = Settings(environment="test", use_mock_engines=True, log_level="WARNING")
    engine = _default_claim_engine(settings)
    assert isinstance(engine, MockClaimEngine)
    assert engine.name == "mock-claim-engine"


def test_use_mock_engines_false_selects_llm_claim_engine() -> None:
    engine = _default_claim_engine(REAL_SETTINGS_NO_KEY)
    assert isinstance(engine, LLMClaimEngine)
    assert engine.name == "llm-claim-engine"
    # Real mode must never silently degrade to the placeholder engine.
    assert not isinstance(engine, UnavailableClaimEngine)
    # Strict: a missing credential or dead gateway becomes a structured error
    # rather than a fabricated rule-based claim.
    assert engine.strict is True


def test_real_mode_app_health_reports_the_llm_engine() -> None:
    app = create_app(settings=REAL_SETTINGS_NO_KEY)
    with TestClient(app) as client:
        engines = client.get("/health").json()["engines"]
    assert engines["claimEngine"] == "llm-claim-engine"
    # The service still starts so health stays reachable for diagnosis.
    assert app.state.claim_engine.name == "llm-claim-engine"


# ---------------------------------------------------------------------------
# 3 / 4. Credentials
# ---------------------------------------------------------------------------


def test_llm_claim_engine_instantiates_with_a_configured_key() -> None:
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    assert engine.is_configured() is True
    assert engine.configuration_error() is None
    assert engine.base_url == GATEWAY_BASE_URL
    assert engine.model == GATEWAY_MODEL


def test_missing_llm_credentials_produce_a_clear_error() -> None:
    engine = LLMClaimEngine(REAL_SETTINGS_NO_KEY, strict=True)
    assert engine.is_configured() is False
    message = engine.configuration_error()
    assert message is not None
    assert "LLM_GATEWAY_API_KEY" in message
    # The message names the variable; it must never carry a credential value.
    assert GATEWAY_KEY not in message


async def test_missing_credentials_raise_claim_engine_error() -> None:
    engine = LLMClaimEngine(REAL_SETTINGS_NO_KEY, strict=True)
    with pytest.raises(ClaimEngineError) as excinfo:
        await engine.extract_claims(_transcript("s_missing_key"))
    assert "LLM_GATEWAY_API_KEY" in str(excinfo.value)


def test_missing_credentials_become_a_structured_error_event() -> None:
    """The router converts the engine failure into CLAIM_EXTRACTION_FAILED."""
    app = create_app(settings=REAL_SETTINGS_NO_KEY)
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()  # the `connected` session event
            body = client.post(
                "/events/transcript", json=transcript_payload(session)
            ).json()
            error = _drain_until(websocket, "error")

    assert body["claims"] == []
    assert body["verifications"] == []
    assert body["counts"] == {"claims": 0, "verifications": 0, "errors": 1}
    assert error["type"] == "error"
    assert error["code"] == "CLAIM_EXTRACTION_FAILED"
    assert error["sessionId"] == session
    assert "LLM_GATEWAY_API_KEY" in error["detail"]


def test_placeholder_api_key_is_treated_as_unconfigured() -> None:
    engine = LLMClaimEngine(_settings(llm_gateway_api_key="your_key_here"))
    assert engine.is_configured() is False
    assert engine.configuration_error() is not None


# ---------------------------------------------------------------------------
# 5. A mocked gateway response produces valid ClaimEvents
# ---------------------------------------------------------------------------


async def test_mocked_gateway_response_produces_valid_claim_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _stub_gateway(
        monkeypatch,
        _claims_json(
            ("The Apollo 11 mission landed in 1969.", "date"),
            ("Mount Everest is 8,848 metres above sea level.", "statistic"),
        ),
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    claims = await engine.extract_claims(_transcript("s_gateway"))

    assert [c.claimId for c in claims] == [
        "s_gateway_claim_001",
        "s_gateway_claim_002",
    ]
    for claim in claims:
        assert isinstance(claim, ClaimEvent)
        assert claim.type == "claim"
        assert claim.sessionId == "s_gateway"
        assert claim.speaker == "Speaker 1"
        assert claim.timestamp == 1.0
    assert claims[0].claim == "The Apollo 11 mission landed in 1969."
    assert claims[0].claimType == "date"
    assert claims[1].claimType == "statistic"

    # The request is OpenAI-compatible chat completions.
    assert recorded["url"] == f"{GATEWAY_BASE_URL}/chat/completions"
    assert recorded["headers"]["Authorization"] == f"Bearer {GATEWAY_KEY}"
    assert recorded["headers"]["Content-Type"] == "application/json"
    assert recorded["json"]["model"] == GATEWAY_MODEL
    assert recorded["json"]["messages"][0]["role"] == "user"
    # The prompt carries the transcript under test, not the gateway's answer.
    assert "Some spoken words." in recorded["json"]["messages"][0]["content"]


async def test_gateway_reply_inside_a_markdown_code_fence_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_gateway(
        monkeypatch,
        "```json\n" + _claims_json(("Water boils at 100 C.", "scientific_fact")) + "\n```",
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    claims = await engine.extract_claims(_transcript("s_fence"))
    assert [c.claim for c in claims] == ["Water boils at 100 C."]


# ---------------------------------------------------------------------------
# 6. Malformed LLM JSON is handled safely
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("{not json at all", id="unparsable"),
        pytest.param("", id="empty"),
        pytest.param("   \n  ", id="whitespace"),
        pytest.param('{"claims": "not a list"}', id="claims-not-a-list"),
        pytest.param("[1, 2, 3]", id="top-level-array"),
        pytest.param('{"results": []}', id="wrong-key"),
        pytest.param('{"claims": [{"claim": "", "claimType": "date"}]}', id="blank-claim"),
        pytest.param('{"claims": [{"claim": "no type"}]}', id="missing-claim-type"),
        pytest.param('{"claims": ["a bare string"]}', id="claim-not-an-object"),
    ],
)
async def test_malformed_llm_json_is_handled_safely(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """A hostile or broken reply yields no claims and never raises."""
    _stub_gateway(monkeypatch, content)
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    assert await engine.extract_claims(_transcript("s_malformed")) == []


async def test_gateway_reply_without_content_is_handled_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_gateway(monkeypatch, None)
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    assert await engine.extract_claims(_transcript("s_no_content")) == []


async def test_valid_claims_survive_alongside_malformed_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One bad entry in the list must not discard the good ones."""
    _stub_gateway(
        monkeypatch,
        json.dumps(
            {
                "claims": [
                    {"claim": "", "claimType": "date"},
                    {"claim": "A valid checkable claim.", "claimType": "statistic"},
                    "junk",
                ]
            }
        ),
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    claims = await engine.extract_claims(_transcript("s_partial"))
    assert [c.claim for c in claims] == ["A valid checkable claim."]


async def test_strict_mode_turns_a_gateway_failure_into_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real mode must not broadcast a fabricated claim when the gateway dies."""
    _stub_gateway(monkeypatch, _claims_json(("A valid claim.", "date")))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY), strict=True)

    async def exploding_post(self, url, **kwargs):
        raise httpx.ConnectError("gateway unreachable")

    monkeypatch.setattr(httpx.AsyncClient, "post", exploding_post)
    with pytest.raises(ClaimEngineError) as excinfo:
        await engine.extract_claims(_transcript("s_down"))
    assert "gateway unreachable" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 7. Deduplication is per session
# ---------------------------------------------------------------------------


async def test_duplicate_claims_are_removed_within_one_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_gateway(
        monkeypatch,
        _claims_json(("Water boils at 100 C at sea level.", "scientific_fact")),
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    first = await engine.extract_claims(_transcript("s_dup", "First utterance.", 1.0))
    second = await engine.extract_claims(_transcript("s_dup", "A later utterance.", 9.0))

    assert [c.claimId for c in first] == ["s_dup_claim_001"]
    assert second == []


async def test_deduplication_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_gateway(
        monkeypatch,
        [
            _claims_json(("Water boils at 100 C.", "scientific_fact")),
            _claims_json(("WATER BOILS AT 100 C.", "scientific_fact")),
        ],
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    first = await engine.extract_claims(_transcript("s_case", "one", 1.0))
    second = await engine.extract_claims(_transcript("s_case", "two", 2.0))
    assert len(first) == 1
    assert second == []


async def test_the_same_claim_in_two_sessions_is_kept_in_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sessions must not share deduplication state."""
    _stub_gateway(
        monkeypatch,
        _claims_json(("Water boils at 100 C.", "scientific_fact")),
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    a = await engine.extract_claims(_transcript("s_one", "one", 1.0))
    b = await engine.extract_claims(_transcript("s_two", "two", 2.0))

    assert [c.claimId for c in a] == ["s_one_claim_001"]
    assert [c.claimId for c in b] == ["s_two_claim_001"]


# ---------------------------------------------------------------------------
# 8. Claim counters are per session
# ---------------------------------------------------------------------------


def test_session_state_is_a_dictionary_not_a_set_or_an_int() -> None:
    """Regression guard for the original TypeError."""
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    assert engine.seen_claims == {}
    assert engine.claim_counter == {}
    # Both accessors previously raised TypeError on item assignment.
    assert engine._get_session_claims("s_a") == set()
    assert engine._get_session_counter("s_a") == 1
    assert engine.seen_claims == {"s_a": set()}
    assert engine.claim_counter == {"s_a": 1}


def test_generated_claim_ids_are_deterministic_and_session_scoped() -> None:
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    assert engine._generate_claim_id("s_a") == "s_a_claim_001"
    assert engine._generate_claim_id("s_a") == "s_a_claim_002"
    assert engine._generate_claim_id("s_a") == "s_a_claim_003"
    # A second session restarts at 001 rather than continuing the first one.
    assert engine._generate_claim_id("s_b") == "s_b_claim_001"
    assert engine._generate_claim_id("s_b") == "s_b_claim_002"


async def test_session_claim_counters_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_gateway(
        monkeypatch,
        _claims_json(
            ("The first checkable claim.", "date"),
            ("The second checkable claim.", "statistic"),
        ),
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    a = await engine.extract_claims(_transcript("s_a", "utterance a", 1.0))
    b = await engine.extract_claims(_transcript("s_b", "utterance b", 2.0))

    assert [c.claimId for c in a] == ["s_a_claim_001", "s_a_claim_002"]
    assert [c.claimId for c in b] == ["s_b_claim_001", "s_b_claim_002"]


async def test_multiple_transcript_events_number_sequentially_in_one_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three transcript events, one distinct claim each, in a single session."""
    _stub_gateway(
        monkeypatch,
        [
            _claims_json(("Claim one about a date.", "date")),
            _claims_json(("Claim two about a number.", "statistic")),
            _claims_json(("Claim three about a person.", "person")),
        ],
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    ids: List[str] = []
    for index in range(3):
        claims = await engine.extract_claims(
            _transcript("s_many", f"utterance {index}", float(index))
        )
        ids.extend(c.claimId for c in claims)

    assert ids == [
        "s_many_claim_001",
        "s_many_claim_002",
        "s_many_claim_003",
    ]


# ---------------------------------------------------------------------------
# 9. LLM claim -> real verification integration
# ---------------------------------------------------------------------------


async def test_llm_extracted_claim_flows_into_the_verification_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TranscriptEvent -> LLMClaimEngine -> ClaimEvent -> VerificationEvent."""
    _stub_gateway(
        monkeypatch,
        _claims_json(("India won the 2011 Cricket World Cup.", "historical_fact")),
    )
    claim_engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    router = EventRouter(
        session_manager=SessionManager(),
        websocket_manager=WebSocketManager(),
        claim_engine=claim_engine,
        verification_engine=VerificationServiceEngine(),
    )
    session = await SessionManager().create()

    counts, claims, verifications = await router.handle_transcript(
        _transcript(session.sessionId, "India won the 2011 Cricket World Cup.", 12.4)
    )

    assert counts.claims == 1
    assert counts.verifications == 1
    assert counts.errors == 0
    assert claims[0].claimId == f"{session.sessionId}_claim_001"
    assert verifications[0].claimId == claims[0].claimId
    assert verifications[0].sessionId == session.sessionId
    assert verifications[0].verdict == Verdict.TRUE


# ---------------------------------------------------------------------------
# 10. Mock mode and the WebSocket/session surface are unchanged
# ---------------------------------------------------------------------------


def test_mock_mode_pipeline_and_websocket_are_unchanged() -> None:
    """USE_MOCK_ENGINES=true still runs MockClaim -> MockVerification over WS."""
    settings = Settings(environment="test", use_mock_engines=True, log_level="WARNING")
    app = create_app(settings=settings)
    with TestClient(app) as client:
        engines = client.get("/health").json()["engines"]
        assert engines["claimEngine"] == "mock-claim-engine"
        assert engines["verificationEngine"] == "mock-verification-engine"

        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            assert websocket.receive_json()["status"] == "connected"
            body = client.post(
                "/events/transcript", json=transcript_payload(session)
            ).json()
            claim = _drain_until(websocket, "claim")
            verification = _drain_until(websocket, "verification")

        state = client.get(f"/session/{session}").json()

    assert body["counts"] == {"claims": 1, "verifications": 1, "errors": 0}
    assert claim["sessionId"] == session
    assert verification["claimId"] == claim["claimId"]
    assert verification["verdict"] == "TRUE"
    assert state["claimCount"] == 1
    assert state["verificationCount"] == 1


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _drain_until(websocket, expected_type: str, limit: int = 12) -> dict:
    for _ in range(limit):
        message = websocket.receive_json()
        if message.get("type") == expected_type:
            return message
    raise AssertionError(f"No {expected_type} event received within {limit} messages.")


def test_api_key_is_never_exposed_to_the_frontend() -> None:
    """The real engine's key must not appear in any HTTP response."""
    settings = _settings(llm_gateway_api_key=GATEWAY_KEY)
    app = create_app(settings=settings)
    with TestClient(app) as client:
        health = client.get("/health").json()
        session = client.post("/session/start", json={}).json()
    assert health["credentialsConfigured"]["llmGateway"] is True
    # Only a boolean is reported, and `SessionStateResponse` carries no secrets.
    assert GATEWAY_KEY not in json.dumps(health)
    assert GATEWAY_KEY not in json.dumps(session)


def test_engine_never_hard_codes_a_credential() -> None:
    """The key comes from settings only."""
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))
    assert engine.api_key == GATEWAY_KEY
    unconfigured = LLMClaimEngine(REAL_SETTINGS_NO_KEY)
    assert unconfigured.api_key in (None, "")
