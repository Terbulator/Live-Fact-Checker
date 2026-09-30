"""Tests for AssemblyAI LLM Gateway fallback models and fragment suppression.

The Gateway can reroute a rate-limited primary to another provider inside a
single HTTP request via its native ``fallbacks`` field. These tests pin the
request shape, prove the existing bounded client-side retry still behaves, and
prove nothing credential-shaped reaches the logs.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List

import httpx
import pytest

from backend.adapters.claim_engine import (
    GATEWAY_MAX_RETRIES,
    MAX_TRACKED_SEGMENTS,
    LLMClaimEngine,
    LLMRateLimitError,
)
from backend.config import Settings
from backend.schemas import TranscriptEvent

API_KEY = "tvly-llm-secret-value-should-never-be-logged"
BASE_URL = "https://llm-gateway.assemblyai.com/v1"
PRIMARY = "qwen3.5-4b-32k-fast"
FALLBACK_1 = "gemini-2.5-flash-lite"
FALLBACK_2 = "gpt-5-nano"


def _settings(**overrides: Any) -> Settings:
    return Settings(
        environment="test", use_mock_engines=False, log_level="WARNING", **overrides
    )


def _engine(strict: bool = False, **overrides: Any) -> LLMClaimEngine:
    """Build an engine. ``strict`` goes to the engine, everything else to Settings."""
    return LLMClaimEngine(_settings(llm_gateway_api_key=API_KEY, **overrides), strict=strict)


def _transcript(session_id: str, text: str, ts: float = 1.0) -> TranscriptEvent:
    return TranscriptEvent(
        type="transcript",
        sessionId=session_id,
        speaker="Speaker 1",
        text=text,
        timestamp=ts,
        isFinal=True,
    )


def _claims(*texts: str) -> str:
    return json.dumps(
        {"claims": [{"claim": t, "claimType": "location"} for t in texts]}
    )


class _StubResponse:
    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        headers: Dict[str, str] = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"gateway returned {self.status_code}",
                request=httpx.Request("POST", f"{BASE_URL}/chat/completions"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return self._payload


def _stub(monkeypatch, responses: Any = None, error: Exception = None) -> Dict[str, Any]:
    """Patch the transport.

    ``responses`` may be omitted (a canned successful reply), a single
    ``_StubResponse`` repeated for every call, or a list consumed one entry per
    call so a retry sequence can be driven.
    """
    state: Dict[str, Any] = {"calls": 0, "bodies": [], "slept": []}
    script = responses if isinstance(responses, list) else None

    async def fake_post(self, url, **kwargs):
        state["calls"] += 1
        state["bodies"].append(kwargs.get("json"))
        if error is not None:
            raise error
        if responses is None:
            return _StubResponse({"choices": [{"message": {"content": _claims("A claim.")}}]})
        reply = (
            script[min(state["calls"] - 1, len(script) - 1)]
            if script is not None
            else responses
        )
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *a, **kw):
        state["slept"].append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return state


# ---------------------------------------------------------------------------
# fallback request fields
# ---------------------------------------------------------------------------


def test_request_includes_the_gateway_fallback_field() -> None:
    body = _engine()._build_payload("Eiffel Tower in India.")

    assert "fallbacks" in body
    assert body["fallbacks"] == [
        {"model": FALLBACK_1},
        {"model": FALLBACK_2},
    ]


def test_request_includes_fallback_depth_of_two() -> None:
    body = _engine()._build_payload("Eiffel Tower in India.")
    assert body["fallback_config"] == {"depth": 2}


def test_primary_model_is_unchanged_and_first() -> None:
    body = _engine()._build_payload("Eiffel Tower in India.")
    assert body["model"] == PRIMARY
    assert body["fallbacks"][0]["model"] != PRIMARY


def test_existing_request_fields_are_preserved_verbatim() -> None:
    body = _engine()._build_payload("Eiffel Tower in India.")
    assert body["max_tokens"] == 500
    assert body["temperature"] == 0.0
    assert body["messages"][0]["role"] == "user"
    assert "Eiffel Tower in India." in body["messages"][0]["content"]
    # The prompt itself is untouched by the fallback change.
    assert '"claims"' in body["messages"][0]["content"]
    assert "claimType" in body["messages"][0]["content"]


async def test_fallbacks_are_sent_on_the_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _stub(monkeypatch)

    await _engine().extract_claims(_transcript("s1", "Eiffel Tower in India."))

    assert state["calls"] == 1
    body = state["bodies"][0]
    assert body["model"] == PRIMARY
    assert body["fallbacks"] == [{"model": FALLBACK_1}, {"model": FALLBACK_2}]
    assert body["fallback_config"] == {"depth": 2}


def test_depth_limits_how_many_fallbacks_are_offered() -> None:
    engine = _engine(llm_gateway_fallback_depth=1)
    body = engine._build_payload("Anything.")
    assert body["fallbacks"] == [{"model": FALLBACK_1}]
    assert body["fallback_config"] == {"depth": 1}


def test_more_than_depth_fallbacks_are_truncated() -> None:
    engine = _engine(llm_gateway_fallback_models=[FALLBACK_1, FALLBACK_2, "extra-model"])
    body = engine._build_payload("Anything.")
    assert [f["model"] for f in body["fallbacks"]] == [FALLBACK_1, FALLBACK_2]


def test_empty_fallback_list_disables_the_field() -> None:
    engine = _engine(llm_gateway_fallback_models=[])
    body = engine._build_payload("Anything.")
    assert "fallbacks" not in body
    assert "fallback_config" not in body


def test_fallbacks_can_be_configured_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_GATEWAY_FALLBACK_MODELS", "gemini-2.5-flash, qwen3.5-4b-32k-fast"
    )
    settings = Settings(use_mock_engines=False)
    assert settings.llm_gateway_fallback_models == [
        "gemini-2.5-flash",
        "qwen3.5-4b-32k-fast",
    ]

    monkeypatch.setenv("LLM_GATEWAY_FALLBACK_MODELS", "")
    assert Settings(use_mock_engines=False).llm_gateway_fallback_models == []


# ---------------------------------------------------------------------------
# selected model logging is safe
# ---------------------------------------------------------------------------


def test_selected_model_is_logged_at_debug(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    served_by_fallback = _StubResponse(
        {"model": FALLBACK_1, "choices": [{"message": {"content": _claims("A claim.")}}]}
    )
    _stub(monkeypatch, served_by_fallback)
    engine = _engine()

    with caplog.at_level(logging.DEBUG, logger="backend.adapters.claim_engine"):
        engine._parse_gateway_response(served_by_fallback)

    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(FALLBACK_1 in line for line in debug_lines)
    assert any("fallback model" in line for line in debug_lines)


def test_primary_model_is_logged_at_debug(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    response = _StubResponse(
        {"model": PRIMARY, "choices": [{"message": {"content": _claims("A claim.")}}]}
    )
    _stub(monkeypatch, response)

    with caplog.at_level(logging.DEBUG, logger="backend.adapters.claim_engine"):
        _engine()._parse_gateway_response(response)

    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("primary model" in line and PRIMARY in line for line in debug_lines)


@pytest.mark.parametrize(
    "hostile",
    [
        "sk-live-ABCDEFGHIJKLMNOP123456",
        "Bearer eyJhbGciOiJIUzI1NiJ9.secret",
        "model\nFAKE LOG LINE injected",
        "x" * 500,
        "",
        "   ",
        None,
        12345,
        {"nested": "object"},
    ],
)
def test_hostile_model_values_never_break_or_inject(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, hostile: Any
) -> None:
    """An untrusted response field must not become a log-injection vector."""
    response = _StubResponse(
        {"model": hostile, "choices": [{"message": {"content": _claims("A claim.")}}]}
    )
    _stub(monkeypatch, response)

    with caplog.at_level(logging.DEBUG, logger="backend.adapters.claim_engine"):
        items = _engine()._parse_gateway_response(response)

    assert len(items) == 1
    for record in caplog.records:
        assert "\n" not in record.getMessage()
    for line in (r.getMessage() for r in caplog.records):
        assert "FAKE LOG LINE" not in line


async def test_no_secret_is_ever_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """End-to-end: the API key must not appear in any log record."""
    response = _StubResponse(
        {"model": FALLBACK_1, "choices": [{"message": {"content": _claims("A claim.")}}]}
    )
    state = _stub(monkeypatch, response)

    with caplog.at_level(logging.DEBUG):
        await _engine().extract_claims(_transcript("s1", "Eiffel Tower in India."))

    assert state["calls"] == 1
    rendered = "\n".join(
        f"{r.name} {r.levelname} {r.getMessage()}" for r in caplog.records
    )
    assert API_KEY not in rendered
    assert "Bearer" not in rendered


# ---------------------------------------------------------------------------
# existing 429 behaviour is preserved
# ---------------------------------------------------------------------------


async def test_429_still_retries_then_raises_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _stub(monkeypatch, _StubResponse({"error": "slow"}, 429))
    engine = _engine(strict=True)

    with pytest.raises(LLMRateLimitError):
        await engine.extract_claims(_transcript("s1", "Eiffel Tower in India."))

    assert state["calls"] == GATEWAY_MAX_RETRIES + 1
    assert len(state["slept"]) == GATEWAY_MAX_RETRIES
    # Every attempt carried the fallbacks, so the Gateway could reroute each try.
    assert all(body.get("fallbacks") for body in state["bodies"])


async def test_429_recovers_on_a_later_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _stub(
        monkeypatch,
        [
            _StubResponse({"error": "slow"}, 429),
            _StubResponse(
                {"model": FALLBACK_2, "choices": [{"message": {"content": _claims("Recovered.")}}]}
            ),
        ],
    )
    engine = _engine(strict=True)

    claims = await engine.extract_claims(_transcript("s1", "Eiffel Tower in India."))

    assert [c.claim for c in claims] == ["Recovered."]
    assert state["calls"] == 2


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_non_429_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    state = _stub(monkeypatch, _StubResponse({"error": "no"}, status))
    engine = _engine(strict=True)

    with pytest.raises(Exception):
        await engine.extract_claims(_transcript("s1", "Anything."))

    assert state["calls"] == 1
    assert state["slept"] == []


# ---------------------------------------------------------------------------
# duplicate / near-duplicate fragment suppression
# ---------------------------------------------------------------------------


async def test_exact_duplicate_segment_makes_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _stub(monkeypatch)
    engine = _engine()

    first = await engine.extract_claims(_transcript("s1", "India won the 2011 Cup.", 1.0))
    second = await engine.extract_claims(_transcript("s1", "india won the 2011 cup!", 2.0))

    assert len(first) == 1
    assert second == []
    assert state["calls"] == 1


async def test_a_longer_follow_up_segment_is_not_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Containment must be one-directional or the claim would be lost.

    AssemblyAI endpointing can emit "In India." and then "Eiffel Tower in India."
    The second carries the subject the first lacked; suppressing it as a
    substring duplicate would throw away the only checkable statement.
    """
    state = _stub(monkeypatch)
    engine = _engine()

    await engine.extract_claims(_transcript("s1", "In India.", 1.0))
    await engine.extract_claims(_transcript("s1", "Eiffel Tower in India.", 2.0))

    assert state["calls"] == 2


async def test_a_shorter_repeat_after_a_longer_segment_is_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _stub(monkeypatch)
    engine = _engine()

    await engine.extract_claims(_transcript("s1", "Eiffel Tower in India.", 1.0))
    await engine.extract_claims(_transcript("s1", "Eiffel Tower in India", 2.0))

    assert state["calls"] == 1


async def test_many_repeated_finals_cost_a_single_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A burst of identical finals must not fan out into many LLM calls."""
    state = _stub(monkeypatch)
    engine = _engine()

    for i in range(12):
        await engine.extract_claims(
            _transcript("s1", "India won the 2011 Cricket World Cup.", float(i))
        )

    assert state["calls"] == 1


async def test_dedup_state_is_per_session(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _stub(monkeypatch)
    engine = _engine()

    a = await engine.extract_claims(_transcript("s1", "India won the 2011 Cup.", 1.0))
    b = await engine.extract_claims(_transcript("s2", "India won the 2011 Cup.", 1.0))

    assert len(a) == 1 and len(b) == 1
    assert state["calls"] == 2


def test_segment_history_is_bounded() -> None:
    engine = _engine()
    engine._record_segment("s1", "first")
    for i in range(MAX_TRACKED_SEGMENTS * 3):
        engine._record_segment("s1", f"segment {i}")

    assert len(engine._get_session_segments("s1")) == MAX_TRACKED_SEGMENTS
    # The oldest entries aged out.
    assert "first" not in engine._get_session_segments("s1")


async def test_a_failed_segment_stays_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rate limiting must not permanently poison a transcript segment."""
    failing = _stub(monkeypatch, _StubResponse({"error": "slow"}, 429))
    engine = _engine(strict=True)

    with pytest.raises(LLMRateLimitError):
        await engine.extract_claims(_transcript("s1", "Eiffel Tower in India."))

    assert failing["calls"] == GATEWAY_MAX_RETRIES + 1

    # Swap in a healthy gateway: the identical segment must be attempted again
    # rather than suppressed as already-processed.
    monkeypatch.undo()
    healthy = _stub(monkeypatch)

    claims = await engine.extract_claims(_transcript("s1", "Eiffel Tower in India."))

    assert len(claims) == 1
    assert healthy["calls"] == 1
