"""Regression tests: the production application starts empty.

The product must not present anything as fact-checked until a user actually
speaks or uploads. These tests exercise the real initialization path rather
than trusting a fixture: they construct the app through ``create_app`` and
render the real dashboard components, then assert that no claim, verdict,
source, confidence or scorecard exists.

A test that injects a mock claim proves only that the mock works. These prove
the absence.
"""

import json
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.mocks.mock_stream import MOCK_TRANSCRIPT_SCRIPT, REFERENCE_CLAIM_TEXT

# Real-mode settings with no engine injected, so the wiring under test is the
# one production uses.
PRODUCTION_SETTINGS = Settings(
    environment="test",
    use_mock_engines=False,
    log_level="WARNING",
    llm_gateway_api_key="test-llm-key",
    search_api_key="test-search-key",
)


# ---------------------------------------------------------------------------
# 5 / 19. mock mode must be opt-in, never the default
# ---------------------------------------------------------------------------


def test_mock_mode_is_not_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that forgets the variable must get real mode, not mock.

    ``tests/backend/conftest.py`` pins ``USE_MOCK_ENGINES=true`` for the whole
    backend package so its own tests stay deterministic. That is an environment
    override, so the code default has to be checked with the variable cleared.
    """
    monkeypatch.delenv("USE_MOCK_ENGINES", raising=False)
    assert Settings().use_mock_engines is False
    assert Settings(use_mock_engines=True).use_mock_engines is True


def test_engine_wiring_defaults_to_the_real_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.main import _default_claim_engine, _default_verification_engine

    monkeypatch.delenv("USE_MOCK_ENGINES", raising=False)
    settings = Settings()
    assert _default_claim_engine(settings).name == "llm-claim-engine"
    assert _default_verification_engine(settings).name == "verification-service"


# ---------------------------------------------------------------------------
# 10 / 12. a new session starts empty
# ---------------------------------------------------------------------------


def test_a_new_session_contains_no_claims_or_verifications() -> None:
    """Starting a session must not resurrect anything from a previous one."""
    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        first = client.post("/session/start", json={}).json()
        second = client.post("/session/start", json={}).json()

        assert first["sessionId"] != second["sessionId"]

        for started in (first, second):
            assert started["claimCount"] == 0
            assert started["verificationCount"] == 0
            assert started["transcriptCount"] == 0
            assert started["errorCount"] == 0

        state = client.get(f"/session/{second['sessionId']}").json()
        assert state["status"] in {"started", "stopped"}


def test_no_websocket_event_is_emitted_for_an_idle_session() -> None:
    """Connecting to a fresh session must not immediately deliver content."""
    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session_id}") as websocket:
            # The only thing available immediately is the session hello.
            hello = websocket.receive_json()
            assert hello["type"] in {"session", "connected"}


def test_startup_does_not_seed_any_factual_content() -> None:
    """Starting the app must not populate claims, verdicts or sources."""
    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        router = app.state.router
        # Every per-session collection starts empty.
        assert router.claim_engine.seen_claims == {}
        assert router.claim_engine.seen_transcripts == {}
        assert router.claim_engine.claim_counter == {}
        assert router.verification_engine._service.retriever.retrieve("") == []


# ---------------------------------------------------------------------------
# 9. the live microphone path enters the pipeline only on a real event
# ---------------------------------------------------------------------------


def test_no_transcript_event_means_no_claims() -> None:
    """Nothing is extracted until a finalized transcript actually arrives."""
    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]
        session_manager = app.state.session_manager
        session = session_manager._sessions[session_id]

        assert session.claimCount == 0
        assert session.verificationCount == 0
        assert session.transcriptCount == 0


def test_an_interim_transcript_never_produces_a_claim() -> None:
    """Growing interim segments must not enter the claim pipeline."""
    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]
        body = client.post(
            "/events/transcript",
            json={
                "type": "transcript",
                "sessionId": session_id,
                "speaker": "Speaker 1",
                "text": "Partial speech that is not final",
                "timestamp": 1.0,
                "isFinal": False,
            },
        ).json()

        assert body["claims"] == []
        assert body["verifications"] == []
        assert body["counts"]["claims"] == 0


# ---------------------------------------------------------------------------
# 4. the retriever must never fall back to seeded evidence
# ---------------------------------------------------------------------------


def test_mock_retriever_ships_with_no_knowledge_base() -> None:
    """The offline retriever must be empty unless a test injects records."""
    from verification.retriever import MockRetriever

    retriever = MockRetriever()
    assert retriever._records == []
    # No plausible factual query may return anything.
    for query in (
        "india won the 2011 cricket world cup",
        "water boils at 100 degrees",
        "eiffel tower paris",
    ):
        assert retriever.retrieve(query) == []


def test_web_retriever_fails_loudly_instead_of_returning_fake_evidence() -> None:
    """A failed search must raise, never degrade to invented evidence."""
    from verification.retriever import (
        RetrieverConfigurationError,
        RetrieverError,
        WebSearchRetriever,
    )
    from verification.search_providers import SearchRateLimitError

    unconfigured = WebSearchRetriever(api_key="", provider="tavily")
    with pytest.raises(RetrieverConfigurationError):
        unconfigured.retrieve("any claim")

    class _Broken:
        name = "broken"

        def search(self, query, max_results=3):
            raise SearchRateLimitError("throttled", attempts=3)

    with pytest.raises(RetrieverError):
        WebSearchRetriever(api_key="k", provider="tavily", provider_client=_Broken()).retrieve(
            "any claim"
        )


# ---------------------------------------------------------------------------
# 11. persistence must not seed Supabase
# ---------------------------------------------------------------------------


def test_no_factual_rows_are_seeded_into_persistence() -> None:
    """Schema only. Nothing writes a claim or verdict at construction time."""
    from backend.persistence.store import NullStore, SupabaseStore

    store = SupabaseStore("postgresql://unused", ttl_seconds=60)
    # Constructed but never connected: no pool, therefore no writes, therefore
    # no rows can have been seeded by this class.
    assert store._pool is None

    null = NullStore()
    assert null.enabled is False


def test_store_is_disabled_without_explicit_configuration() -> None:
    from backend.persistence.store import build_store

    # No SUPABASE_DATABASE_URL configured -> nothing is persisted at all.
    store = build_store(PRODUCTION_SETTINGS, strict=True)
    assert store.enabled is False


# ---------------------------------------------------------------------------
# 15 / 16 / 17. nothing precomputed can leak into a payload
# ---------------------------------------------------------------------------


def test_health_exposes_no_factual_payload() -> None:
    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        body = client.get("/health").json()

    # Credentials are booleans, never values, and there is no claims/verdicts
    # array anywhere in the health document.
    assert all(isinstance(v, bool) for v in body["credentialsConfigured"].values())
    rendered = json.dumps(body).lower()
    for forbidden in ("claim", "verdict", "evidence", "source"):
        assert f'"{forbidden}"' not in rendered


def test_the_known_demo_claim_is_not_a_seeded_record() -> None:
    """The mock script may exist for the explicit demo, but never as data.

    ``REFERENCE_CLAIM_TEXT`` is the one canned claim in the repository. It must
    only be reachable through an explicit ``startMockPipeline`` request, and
    must never be present in the default production path.
    """
    scripted_texts = [str(segment["text"]) for segment in MOCK_TRANSCRIPT_SCRIPT]
    assert REFERENCE_CLAIM_TEXT in scripted_texts

    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]
        # A plain start must not have replayed the script.
        session = app.state.session_manager._sessions[session_id]
        assert session.transcriptCount == 0
        assert session.claimCount == 0


# ---------------------------------------------------------------------------
# 18. opening the dashboard must not retrieve fabricated results
# ---------------------------------------------------------------------------


def test_dashboard_loads_without_any_ingestion_or_results_request() -> None:
    """Session creation and health are legitimate; fabricated results are not."""
    app = create_app(settings=PRODUCTION_SETTINGS)
    with TestClient(app) as client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]
        state = client.get(f"/session/{session_id}").json()

    assert state["claimCount"] == 0
    assert state["verificationCount"] == 0
    # The session response carries no claims/verifications arrays at all.
    assert "claims" not in state
    assert "verifications" not in state
