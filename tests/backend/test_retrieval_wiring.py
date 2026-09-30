"""Tests for backend wiring of the real evidence retriever.

Mock mode must keep the fully offline pipeline. Real mode must reach a live
search provider and must never silently fall back to the offline
``MockRetriever``, whose hardcoded records would otherwise produce confident
verdicts with no search provider involved.
"""

from typing import Any, Dict, List

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.adapters.verification import VerificationServiceEngine
from backend.config import Settings
from backend.main import _default_verification_engine, create_app
from backend.mocks.mock_stream import MockClaimEngine
from backend.schemas import ClaimEvent
from verification.retriever import MockRetriever, WebSearchRetriever
from verification.search_providers import SearchRateLimitError
from tests.backend.conftest import transcript_payload

API_KEY = "tvly-test-key"

REAL_SETTINGS = Settings(environment="test", use_mock_engines=False, log_level="WARNING")
MOCK_SETTINGS = Settings(environment="test", use_mock_engines=True, log_level="WARNING")


class _StubSearchProvider:
    name = "stub"

    def __init__(self, records: List[Dict[str, Any]] = None) -> None:
        self.records = records if records is not None else [
            {
                "title": "NASA Apollo 11",
                "url": "https://www.nasa.gov/apollo-11",
                "content": "Apollo 11 landed humans on the Moon on July 20, 1969.",
                "score": 0.95,
            }
        ]
        self.calls: List[str] = []

    def search(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        self.calls.append(query)
        return list(self.records)[:max_results]


def _engine_with(provider: _StubSearchProvider) -> VerificationServiceEngine:
    retriever = WebSearchRetriever(
        api_key=API_KEY, provider="stub", provider_client=provider
    )
    return VerificationServiceEngine(retriever=retriever)


def _drain_until(websocket, expected_type: str, limit: int = 12) -> dict:
    for _ in range(limit):
        message = websocket.receive_json()
        if message.get("type") == expected_type:
            return message
    raise AssertionError(f"No {expected_type} event received within {limit} messages.")


# ---------------------------------------------------------------------------
# engine / retriever selection
# ---------------------------------------------------------------------------


def test_mock_mode_selects_the_mock_verification_engine() -> None:
    engine = _default_verification_engine(MOCK_SETTINGS)
    assert engine.name == "mock-verification-engine"


def test_real_mode_selects_the_verification_service_engine() -> None:
    engine = _default_verification_engine(REAL_SETTINGS)
    assert engine.name == "verification-service"


def test_real_mode_uses_the_web_retriever_never_the_mock_one() -> None:
    """The regression guard: real mode must not inherit mock evidence."""
    engine = _default_verification_engine(REAL_SETTINGS)
    retriever = engine._service.retriever
    assert isinstance(retriever, WebSearchRetriever)
    assert not isinstance(retriever, MockRetriever)


def test_real_mode_ignores_a_stray_key_present_in_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEARCH_API_KEY", "leftover-key")
    engine = _default_verification_engine(REAL_SETTINGS)
    assert isinstance(engine._service.retriever, WebSearchRetriever)


def test_real_mode_passes_the_configured_provider_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="test",
        use_mock_engines=False,
        log_level="WARNING",
        search_api_key=API_KEY,
        search_provider="tavily",
    )
    engine = _default_verification_engine(settings)
    assert engine._service.retriever.provider == "tavily"
    assert engine._service.retriever.api_key == API_KEY


def test_search_provider_env_var_selects_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEARCH_PROVIDER is the documented switch; Tavily is the default."""
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    assert Settings(use_mock_engines=False).search_provider == "tavily"

    monkeypatch.setenv("SEARCH_PROVIDER", "TAVILY")
    assert Settings(use_mock_engines=False).search_provider == "TAVILY"

    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    assert Settings(use_mock_engines=False).search_provider == "tavily"


def test_health_reports_the_search_credential_as_a_boolean_only() -> None:
    settings = Settings(
        environment="test", use_mock_engines=False, log_level="WARNING", search_api_key=API_KEY
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        health = client.get("/health").json()
    assert health["credentialsConfigured"]["search"] is True
    assert API_KEY not in str(health)
    assert health["engines"]["verificationEngine"] == "verification-service"


async def test_slow_retrieval_does_not_block_the_event_loop() -> None:
    """Real retrieval blocks on HTTP; it must not stall other sessions.

    Without the worker-thread dispatch the heartbeat would be starved for the
    whole search, freezing WebSocket broadcasts across every session.
    """

    class _SlowProvider:
        name = "slow"

        def search(self, query, max_results=3):
            time.sleep(0.25)
            return [
                {
                    "title": "Slow but authoritative",
                    "url": "https://slow.example.com/report",
                    "content": "The archived report confirms the figure.",
                    "score": 0.9,
                }
            ]

    engine = VerificationServiceEngine(
        retriever=WebSearchRetriever(
            api_key=API_KEY, provider="stub", provider_client=_SlowProvider()
        )
    )
    claim = ClaimEvent(
        claimId="session_1_claim_001",
        sessionId="session_1",
        speaker="Speaker 1",
        claim="A claim whose search is slow.",
        timestamp=1.0,
    )

    ticks: List[str] = []

    async def heartbeat() -> None:
        for _ in range(10):
            ticks.append("tick")
            await asyncio.sleep(0.01)
        ticks.append("heartbeat-done")

    async def search() -> Any:
        ticks.append("search-start")
        result = await engine.verify(claim)
        ticks.append("search-end")
        return result

    verification, _ = await asyncio.gather(search(), heartbeat())

    assert verification.source == "https://slow.example.com/report"
    # At least one heartbeat tick landed *during* the 0.25s search. Asserting
    # only the final tick count would pass even if the search blocked the loop,
    # because the heartbeat would still run to completion afterwards.
    assert ticks.index("search-end") > ticks.index("search-start") + 1


# ---------------------------------------------------------------------------
# missing credential in real mode: fail loudly
# ---------------------------------------------------------------------------


async def test_real_mode_without_a_search_key_fails_loudly() -> None:
    """No fabricated verdict: the failure is a structured error event."""
    engine = _default_verification_engine(REAL_SETTINGS)
    claim = ClaimEvent(
        claimId="session_1_claim_001",
        sessionId="session_1",
        speaker="Speaker 1",
        claim="India won the 2011 Cricket World Cup.",
        timestamp=1.0,
    )

    from backend.adapters.verification import VerificationEngineError

    with pytest.raises(VerificationEngineError) as excinfo:
        await engine.verify(claim)

    assert "SEARCH_API_KEY" in str(excinfo.value)
    # The error must not read as a successful verification.
    assert excinfo.value.claimId == "session_1_claim_001"


def test_missing_search_key_surfaces_as_a_structured_error_event() -> None:
    app = create_app(settings=REAL_SETTINGS, claim_engine=MockClaimEngine())

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            body = client.post(
                "/events/transcript", json=transcript_payload(session)
            ).json()
            error = _drain_until(websocket, "error")

    assert body["counts"] == {"claims": 1, "verifications": 0, "errors": 1}
    assert body["verifications"] == []
    assert error["code"] == "VERIFICATION_FAILED"
    assert "SEARCH_API_KEY" in error["detail"]


def test_unknown_provider_surfaces_as_a_structured_error_event() -> None:
    settings = Settings(
        environment="test",
        use_mock_engines=False,
        log_level="WARNING",
        search_api_key=API_KEY,
        search_provider="bing",
    )
    app = create_app(settings=settings, claim_engine=MockClaimEngine())

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            error = _drain_until(websocket, "error")

    assert error["code"] == "VERIFICATION_FAILED"
    assert "SEARCH_PROVIDER" in error["detail"]


def test_provider_rate_limiting_surfaces_as_a_structured_error_event() -> None:
    """A throttle must never be reported as a verdict or as absent evidence."""

    class _ThrottledProvider:
        name = "throttled"

        def __init__(self) -> None:
            self.calls = 0

        def search(self, query, max_results=3):
            self.calls += 1
            raise SearchRateLimitError(
                "tavily rate limited at https://api.tavily.com/search "
                "after 3 attempt(s) (HTTP 429). No evidence was retrieved.",
                attempts=3,
            )

    provider = _ThrottledProvider()
    app = create_app(
        settings=REAL_SETTINGS,
        claim_engine=MockClaimEngine(),
        verification_engine=VerificationServiceEngine(
            retriever=WebSearchRetriever(
                api_key=API_KEY, provider="stub", provider_client=provider
            )
        ),
    )

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            error = _drain_until(websocket, "error")

    assert error["code"] == "VERIFICATION_FAILED"
    assert "rate limited" in error["detail"].lower()
    assert "429" in error["detail"]
    assert API_KEY not in error["detail"]


def test_provider_failure_surfaces_as_a_structured_error_event() -> None:
    class _BrokenProvider:
        name = "broken"

        def search(self, query, max_results=3):
            raise RuntimeError("provider exploded")

    retriever = WebSearchRetriever(
        api_key=API_KEY, provider="stub", provider_client=_BrokenProvider()
    )
    app = create_app(
        settings=REAL_SETTINGS,
        claim_engine=MockClaimEngine(),
        verification_engine=VerificationServiceEngine(retriever=retriever),
    )

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            error = _drain_until(websocket, "error")

    assert error["code"] == "VERIFICATION_FAILED"
    assert "provider exploded" in error["detail"]


# ---------------------------------------------------------------------------
# real retrieval through the running pipeline
# ---------------------------------------------------------------------------


def test_real_retrieval_produces_a_verification_with_a_real_source() -> None:
    provider = _StubSearchProvider()
    app = create_app(
        settings=REAL_SETTINGS,
        claim_engine=MockClaimEngine(),
        verification_engine=_engine_with(provider),
    )

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            body = client.post(
                "/events/transcript", json=transcript_payload(session)
            ).json()
            verification = _drain_until(websocket, "verification")

    assert body["counts"]["verifications"] == 1
    assert body["counts"]["errors"] == 0
    assert verification["verdict"] in {"TRUE", "FALSE", "UNVERIFIABLE"}
    # A real provider URL, never a placeholder invented by the retriever.
    assert verification["source"] == "https://www.nasa.gov/apollo-11"
    # Identity is preserved across the boundary.
    assert verification["claimId"] == body["claims"][0]["claimId"]
    assert verification["sessionId"] == session
    # The provider was actually consulted with a generated query.
    assert len(provider.calls) == 1
    assert provider.calls[0].strip()


def test_empty_provider_results_yield_unverifiable_not_an_error() -> None:
    provider = _StubSearchProvider(records=[])
    app = create_app(
        settings=REAL_SETTINGS,
        claim_engine=MockClaimEngine(),
        verification_engine=_engine_with(provider),
    )

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            verification = _drain_until(websocket, "verification")

    assert verification["verdict"] == "UNVERIFIABLE"
    assert verification["source"] == "No source available"


def test_unattributable_results_yield_unverifiable() -> None:
    provider = _StubSearchProvider(records=[{"content": "Something unsourced.", "score": 0.9}])
    app = create_app(
        settings=REAL_SETTINGS,
        claim_engine=MockClaimEngine(),
        verification_engine=_engine_with(provider),
    )

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            verification = _drain_until(websocket, "verification")

    assert verification["verdict"] == "UNVERIFIABLE"
    assert verification["source"] == "No source available"


# ---------------------------------------------------------------------------
# mock mode untouched
# ---------------------------------------------------------------------------


def test_mock_mode_pipeline_is_unchanged() -> None:
    app = create_app(settings=MOCK_SETTINGS)
    with TestClient(app) as client:
        engines = client.get("/health").json()["engines"]
        assert engines["claimEngine"] == "mock-claim-engine"
        assert engines["verificationEngine"] == "mock-verification-engine"

        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            body = client.post(
                "/events/transcript", json=transcript_payload(session)
            ).json()
            claim = _drain_until(websocket, "claim")
            verification = _drain_until(websocket, "verification")

    assert body["counts"] == {"claims": 1, "verifications": 1, "errors": 0}
    assert claim["sessionId"] == session
    assert verification["claimId"] == claim["claimId"]


def test_mock_mode_makes_no_provider_calls() -> None:
    """Mock mode must not reach the network at all."""
    app = create_app(settings=MOCK_SETTINGS)
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            _drain_until(websocket, "verification")

    state = app.state.verification_engine
    assert state.name == "mock-verification-engine"
