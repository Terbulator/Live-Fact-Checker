"""Tests for the LLM Gateway rate-limit fix.

Covers the three mechanisms that stop HTTP 429s:

1. a per-session single-slot gate, so only one gateway request per session is
   ever in flight while separate sessions stay independent
2. transcript deduplication *before* the billable request, with the original
   post-response claim deduplication kept as a second layer
3. bounded 429 retries that honour ``Retry-After``, fall back to exponential
   backoff, never retry other 4xx, and surface ``LLM_RATE_LIMITED`` when spent

No test sleeps for real: ``asyncio.sleep`` is replaced by a recorder that yields
without waiting, so the backoff schedule is asserted rather than endured.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Union

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.claim_engine import (
    GATEWAY_MAX_RETRIES,
    GATEWAY_RETRY_BASE_SECONDS,
    GATEWAY_RETRY_MAX_SECONDS,
    ClaimEngineError,
    LLMClaimEngine,
    LLMRateLimitError,
    normalize_transcript,
)
from backend.config import Settings
from backend.main import create_app
from backend.router import EventRouter
from backend.schemas import ErrorCode, TranscriptEvent
from backend.session_manager import SessionManager
from backend.websocket_manager import WebSocketManager
from tests.backend.conftest import transcript_payload

GATEWAY_KEY = "test-llm-gateway-key"
GATEWAY_BASE_URL = "https://llm-gateway.assemblyai.com/v1"

REAL_SETTINGS_NO_KEY = Settings(
    environment="test", use_mock_engines=False, log_level="WARNING"
)


def _settings(**overrides: Any) -> Settings:
    return Settings(
        environment="test", use_mock_engines=False, log_level="WARNING", **overrides
    )


def _transcript(
    session_id: str, text: str = "Some spoken words.", ts: float = 1.0
) -> TranscriptEvent:
    return TranscriptEvent(
        type="transcript",
        sessionId=session_id,
        speaker="Speaker 1",
        text=text,
        timestamp=ts,
        isFinal=True,
    )


def _claims_json(*pairs: Any) -> str:
    return json.dumps(
        {
            "claims": [
                {"claim": claim, "claimType": claim_type} for claim, claim_type in pairs
            ]
        }
    )


# ---------------------------------------------------------------------------
# gateway stubs
# ---------------------------------------------------------------------------


class _StubResponse:
    """Minimal stand-in for ``httpx.Response`` covering what the engine uses."""

    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"gateway returned {self.status_code}",
                request=httpx.Request("POST", f"{GATEWAY_BASE_URL}/chat/completions"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return self._payload


def _ok(content: str) -> _StubResponse:
    return _StubResponse({"choices": [{"message": {"content": content}}]})


def _rate_limited(retry_after: Optional[str] = None) -> _StubResponse:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return _StubResponse({"error": "rate limited"}, 429, headers)


def _scripted_gateway(
    monkeypatch: pytest.MonkeyPatch, script: Union[List[Any], Any]
) -> Dict[str, Any]:
    """Return ``script`` one entry per call; the last entry repeats.

    Each entry is either a ``_StubResponse`` or an exception instance to raise.
    Records every call in ``state["calls"]`` so retry counts are assertable.
    """
    state: Dict[str, Any] = {"calls": 0, "slept": []}
    replies = script if isinstance(script, list) else None

    async def fake_post(self, url, **kwargs):
        index = state["calls"]
        state["calls"] += 1
        reply = replies[min(index, len(replies) - 1)] if replies else script
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    _patch_sleep(monkeypatch, state["slept"])
    return state


def _tracking_gateway(
    monkeypatch: pytest.MonkeyPatch, content: str, hold: float = 0.02
) -> Dict[str, Any]:
    """A gateway that records how many requests overlap in time.

    ``hold`` is a real but tiny sleep standing in for gateway latency, so a
    missing lock genuinely shows up as overlap instead of passing by luck.
    """
    state: Dict[str, Any] = {"calls": 0, "in_flight": 0, "max_in_flight": 0}

    async def fake_post(self, url, **kwargs):
        state["calls"] += 1
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            await asyncio.sleep(hold)
            return _ok(content)
        finally:
            state["in_flight"] -= 1

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return state


def _switchable_gateway(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """429 while ``state["fail"]`` is set, otherwise one successful claim.

    Keyed off a flag rather than a call count so the test does not depend on
    how many retries the engine spends.
    """
    state: Dict[str, Any] = {"calls": 0, "slept": [], "fail": True}

    async def fake_post(self, url, **kwargs):
        state["calls"] += 1
        if state["fail"]:
            return _rate_limited()
        return _ok(_claims_json(("Late claim.", "date")))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    _patch_sleep(monkeypatch, state["slept"])
    return state


def _rate_limit_for_marker(
    monkeypatch: pytest.MonkeyPatch, marker: str, ok_content: str
) -> Dict[str, Any]:
    """429 for any transcript containing ``marker``, success for anything else.

    Lets a test drive one rate-limited segment and one healthy segment without
    depending on the retry budget.
    """
    state: Dict[str, Any] = {"calls": 0, "slept": []}

    async def fake_post(self, url, **kwargs):
        state["calls"] += 1
        prompt = kwargs["json"]["messages"][0]["content"]
        if marker in prompt:
            return _rate_limited()
        return _ok(ok_content)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    _patch_sleep(monkeypatch, state["slept"])
    return state


def _patch_sleep(
    monkeypatch: pytest.MonkeyPatch, recorded: List[float]
) -> None:
    """Replace ``asyncio.sleep`` with a recorder that only yields the loop."""
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        recorded.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    recorded: List[float] = []
    _patch_sleep(monkeypatch, recorded)
    return recorded


# ---------------------------------------------------------------------------
# transcript normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "left,right",
    [
        ("India won the 2011 Cricket World Cup.", "india won the 2011 cricket world cup"),
        ("Hello, world!", "hello world"),
        ("Wait... what?", "wait what"),
        ("  spaced   out   text ", "spaced out text"),
        ("dr. smith said: \"no\"", "dr smith said no"),
    ],
)
def test_normalization_folds_punctuation_and_case(left: str, right: str) -> None:
    assert normalize_transcript(left) == normalize_transcript(right)


@pytest.mark.parametrize(
    "left,right",
    [
        ("India won the 2011 Cricket World Cup.", "India won the 2011 Cricket World Cup final"),
        ("Two million units", "Two million"),
        ("Water boils at 100 degrees", "Water freezes at 100 degrees"),
        ("2011", "2012"),
    ],
)
def test_normalization_keeps_substantive_differences_distinct(
    left: str, right: str
) -> None:
    assert normalize_transcript(left) != normalize_transcript(right)


def test_punctuation_only_transcripts_do_not_all_collide() -> None:
    assert normalize_transcript("...") != normalize_transcript("!!!")


# ---------------------------------------------------------------------------
# 1. duplicate transcript is skipped BEFORE the gateway call
# ---------------------------------------------------------------------------


async def test_duplicate_transcript_is_skipped_before_the_gateway_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _scripted_gateway(monkeypatch, _ok(_claims_json(("A checkable claim.", "date"))))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    first = await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))
    second = await engine.extract_claims(_transcript("s1", "india won the 2011 cup!"))

    assert len(first) == 1
    assert second == []
    # The whole point: the duplicate never reached the gateway.
    assert state["calls"] == 1


async def test_distinct_transcripts_are_both_sent_to_the_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _scripted_gateway(
        monkeypatch,
        [
            _ok(_claims_json(("First claim.", "date"))),
            _ok(_claims_json(("Second claim.", "date"))),
        ],
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    await engine.extract_claims(_transcript("s1", "Alpha sentence."))
    await engine.extract_claims(_transcript("s1", "Beta sentence."))

    assert state["calls"] == 2


async def test_duplicate_detection_is_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _scripted_gateway(monkeypatch, _ok(_claims_json(("A checkable claim.", "date"))))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    a = await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))
    b = await engine.extract_claims(_transcript("s2", "India won the 2011 Cup."))

    assert len(a) == 1 and len(b) == 1
    assert [c.claimId for c in a] == ["s1_claim_001"]
    assert [c.claimId for c in b] == ["s2_claim_001"]
    assert state["calls"] == 2


async def test_failed_transcript_is_not_remembered_as_processed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rate-limited segment must stay retryable rather than be lost forever."""
    state = _switchable_gateway(monkeypatch)
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY), strict=True)

    with pytest.raises(LLMRateLimitError):
        await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))

    spent = state["calls"]
    state["fail"] = False

    # The reservation was released, so the identical segment is attempted again.
    claims = await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))
    assert [c.claim for c in claims] == ["Late claim."]
    assert state["calls"] == spent + 1


# ---------------------------------------------------------------------------
# 2. per-session concurrency limit
# ---------------------------------------------------------------------------


async def test_two_simultaneous_finals_for_one_session_never_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _tracking_gateway(monkeypatch, _claims_json(("A checkable claim.", "date")))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    await asyncio.gather(
        engine.extract_claims(_transcript("s1", "First utterance.", 1.0)),
        engine.extract_claims(_transcript("s1", "Second utterance.", 2.0)),
    )

    assert state["calls"] == 2
    # The regression guard: without the per-session gate this is 2.
    assert state["max_in_flight"] == 1


async def test_simultaneous_duplicate_finals_cost_one_gateway_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both pass dedup-safe because the gate serializes check and call."""
    state = _tracking_gateway(monkeypatch, _claims_json(("A checkable claim.", "date")))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    results = await asyncio.gather(
        engine.extract_claims(_transcript("s1", "India won the 2011 Cup.", 1.0)),
        engine.extract_claims(_transcript("s1", "india won the 2011 cup", 2.0)),
    )

    assert state["max_in_flight"] == 1
    assert state["calls"] == 1
    assert sum(len(r) for r in results) == 1


async def test_different_sessions_process_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate sessions hold separate gates, so their requests may overlap."""
    state = _tracking_gateway(monkeypatch, _claims_json(("A checkable claim.", "date")))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    await asyncio.gather(
        engine.extract_claims(_transcript("s1", "Utterance one.", 1.0)),
        engine.extract_claims(_transcript("s2", "Utterance two.", 2.0)),
    )

    assert state["calls"] == 2
    # Independence is the point: a global lock would force this to 1.
    assert state["max_in_flight"] == 2
    assert set(engine._session_gates) == {"s1", "s2"}


async def test_repeated_calls_reuse_one_gate_per_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_gateway(monkeypatch, _ok(_claims_json(("A checkable claim.", "date"))))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    assert engine._get_session_gate("s1") is engine._get_session_gate("s1")
    assert engine._get_session_gate("s1") is not engine._get_session_gate("s2")


# ---------------------------------------------------------------------------
# 3. bounded 429 retry
# ---------------------------------------------------------------------------


async def test_429_with_retry_after_waits_the_requested_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _scripted_gateway(
        monkeypatch, [_rate_limited("2"), _rate_limited("4"), _ok(_claims_json(("Recovered.", "date")))]
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    claims = await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))

    assert [c.claim for c in claims] == ["Recovered."]
    assert state["calls"] == 3
    assert state["slept"] == [2.0, 4.0]


async def test_429_without_retry_after_uses_bounded_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _scripted_gateway(
        monkeypatch, [_rate_limited(), _rate_limited(), _ok(_claims_json(("Recovered.", "date")))]
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))

    assert state["slept"] == [
        GATEWAY_RETRY_BASE_SECONDS,
        GATEWAY_RETRY_BASE_SECONDS * 2,
    ]


async def test_absurd_retry_after_is_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gateway asking for an hour must not park a live transcript."""
    state = _scripted_gateway(
        monkeypatch, [_rate_limited("3600"), _ok(_claims_json(("Recovered.", "date")))]
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))

    assert state["slept"] == [GATEWAY_RETRY_MAX_SECONDS]


def test_unparsable_retry_after_falls_back_to_backoff() -> None:
    parse = LLMClaimEngine._parse_retry_after
    assert parse("soon-ish") is None
    assert parse("") is None
    assert parse(None) is None
    assert parse("-5") is None
    assert parse("3") == 3.0


def test_http_date_retry_after_is_understood() -> None:
    parse = LLMClaimEngine._parse_retry_after
    assert parse("Wed, 21 Oct 2015 07:28:00 GMT") is not None  # past -> 0.0
    assert parse("Wed, 21 Oct 2099 07:28:00 GMT") is not None


async def test_retries_stop_after_the_maximum_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _scripted_gateway(monkeypatch, _rate_limited())
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    with pytest.raises(LLMRateLimitError):
        await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))

    # Literals, not the constants: the bound must not be able to drift upward
    # without a test failing.
    assert state["calls"] == 3
    assert len(state["slept"]) == 2


def test_the_retry_budget_is_exactly_two() -> None:
    """A live demo must fail visibly rather than stall on a wedged gateway."""
    assert GATEWAY_MAX_RETRIES == 2
    assert GATEWAY_RETRY_BASE_SECONDS > 0
    assert GATEWAY_RETRY_BASE_SECONDS * 2 ** (GATEWAY_MAX_RETRIES - 1) <= (
        GATEWAY_RETRY_MAX_SECONDS
    )


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_auth_and_path_errors_are_never_retried(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    state = _scripted_gateway(monkeypatch, _StubResponse({"error": "no"}, status))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    with pytest.raises(httpx.HTTPStatusError):
        await engine._call_llm_gateway("Some spoken words.")

    assert state["calls"] == 1
    assert state["slept"] == []


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_server_errors_are_not_retried_either(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Only 429 is transient; a 5xx is not chased."""
    state = _scripted_gateway(monkeypatch, _StubResponse({"error": "boom"}, status))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    with pytest.raises(httpx.HTTPStatusError):
        await engine._call_llm_gateway("Some spoken words.")

    assert state["calls"] == 1
    assert state["slept"] == []


# ---------------------------------------------------------------------------
# 4. structured rate-limit error
# ---------------------------------------------------------------------------


def test_rate_limit_error_is_a_claim_engine_error() -> None:
    """Existing generic handling must keep working."""
    assert issubclass(LLMRateLimitError, ClaimEngineError)


async def test_exhausted_429_raises_a_rate_limit_specific_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_gateway(monkeypatch, _rate_limited())
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY), strict=True)

    with pytest.raises(LLMRateLimitError) as excinfo:
        await engine.extract_claims(_transcript("s1", "India won the 2011 Cup."))

    assert excinfo.value.attempts == 3
    assert excinfo.value.status_code == 429
    assert "rate limited" in str(excinfo.value).lower()
    # No credential may appear in an operator-visible message.
    assert GATEWAY_KEY not in str(excinfo.value)


def test_router_emits_llm_rate_limited_not_claim_extraction_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rate_limit_for_marker(
        monkeypatch,
        "India won the 2011 Cricket World Cup.",
        _claims_json(("A checkable claim.", "date")),
    )
    app = create_app(settings=_settings(llm_gateway_api_key=GATEWAY_KEY))

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            error = _drain_until(websocket, "error")

    assert error["code"] == ErrorCode.LLM_RATE_LIMITED.value == "LLM_RATE_LIMITED"
    assert error["recoverable"] is True
    assert "rate limit" in error["message"].lower()
    assert GATEWAY_KEY not in json.dumps(error)


def test_missing_credentials_still_report_claim_extraction_failed() -> None:
    """The two codes stay distinguishable: bad config is not a rate limit."""
    app = create_app(settings=REAL_SETTINGS_NO_KEY)
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            client.post("/events/transcript", json=transcript_payload(session))
            error = _drain_until(websocket, "error")

    assert error["code"] == "CLAIM_EXTRACTION_FAILED"
    assert error["code"] != "LLM_RATE_LIMITED"


def test_rate_limit_does_not_break_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 is recoverable: the next segment still reaches the gateway."""
    _rate_limit_for_marker(
        monkeypatch,
        "India won the 2011 Cricket World Cup.",
        _claims_json(("Recovered.", "date")),
    )
    app = create_app(settings=_settings(llm_gateway_api_key=GATEWAY_KEY))

    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        with client.websocket_connect(f"/ws/session/{session}") as websocket:
            websocket.receive_json()
            first_body = client.post(
                "/events/transcript", json=transcript_payload(session)
            ).json()
            first = _drain_until(websocket, "error")

            # A different segment, so pre-gateway dedup does not suppress it.
            second_body = client.post(
                "/events/transcript",
                json=transcript_payload(session, text="A different sentence entirely."),
            ).json()
            claim = _drain_until(websocket, "claim")

    assert first_body["counts"] == {"claims": 0, "verifications": 0, "errors": 1}
    assert first["code"] == "LLM_RATE_LIMITED"
    assert second_body["counts"]["claims"] == 1
    assert claim["claim"] == "Recovered."


# ---------------------------------------------------------------------------
# 5. existing behaviours still hold
# ---------------------------------------------------------------------------


async def test_post_response_claim_deduplication_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway restating a claim is still filtered, second layer intact."""
    state = _scripted_gateway(
        monkeypatch, _ok(_claims_json(("Water boils at 100 C.", "scientific_fact")))
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    first = await engine.extract_claims(_transcript("s1", "Utterance one.", 1.0))
    second = await engine.extract_claims(_transcript("s1", "Utterance two.", 2.0))

    # Distinct transcripts, so both are sent; the repeated claim is dropped.
    assert state["calls"] == 2
    assert [c.claimId for c in first] == ["s1_claim_001"]
    assert second == []


async def test_strict_mode_still_refuses_the_rule_based_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-429 failure must not fabricate a claim in production mode."""
    _scripted_gateway(monkeypatch, httpx.ConnectError("gateway unreachable"))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY), strict=True)

    with pytest.raises(ClaimEngineError) as excinfo:
        await engine.extract_claims(_transcript("s1", "India won the 2011 Cricket World Cup."))

    assert not isinstance(excinfo.value, LLMRateLimitError)
    assert "gateway unreachable" in str(excinfo.value)


async def test_non_strict_mode_still_falls_back_on_a_gateway_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_gateway(monkeypatch, httpx.ConnectError("gateway unreachable"))
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    claims = await engine.extract_claims(
        _transcript("s1", "India won the 2011 Cricket World Cup.")
    )

    assert [c.claim for c in claims] == ["India won the 2011 Cricket World Cup."]


async def test_strict_mode_missing_credentials_still_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    engine = LLMClaimEngine(REAL_SETTINGS_NO_KEY, strict=True)

    with pytest.raises(ClaimEngineError) as excinfo:
        await engine.extract_claims(_transcript("s1"))

    assert not isinstance(excinfo.value, LLMRateLimitError)
    assert "LLM_GATEWAY_API_KEY" in str(excinfo.value)


async def test_claim_ids_stay_session_scoped_under_the_new_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scripted_gateway(
        monkeypatch,
        _ok(
            _claims_json(
                ("Claim one.", "date"),
                ("Claim two.", "statistic"),
                ("Claim three.", "person"),
            )
        ),
    )
    engine = LLMClaimEngine(_settings(llm_gateway_api_key=GATEWAY_KEY))

    await asyncio.gather(
        *[
            engine.extract_claims(_transcript("s1", f"Utterance {i}.", float(i)))
            for i in range(3)
        ]
    )

    assert engine.claim_counter["s1"] == 4
    assert sorted(engine.seen_claims["s1"]) == [
        "claim one.",
        "claim three.",
        "claim two.",
    ]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _drain_until(websocket, expected_type: str, limit: int = 12) -> dict:
    for _ in range(limit):
        message = websocket.receive_json()
        if message.get("type") == expected_type:
            return message
    raise AssertionError(f"No {expected_type} event received within {limit} messages.")
