"""Tests for real evidence retrieval via the search provider adapter.

Covers the Tavily provider, the ``WebSearchRetriever`` -> ``EvidenceItem``
conversion, and the two anti-fabrication rules:

* a result with no URL is dropped, never given a placeholder citation
* a result with no score is treated as minimally acceptable, not maximally trusted

Every provider call goes through an injected transport, so no test performs a
network request.
"""

from typing import Any, Dict, List

import pytest

from verification.checker import VerificationChecker
from verification.models import EvidenceItem, VerdictType
from verification.retriever import (
    MockRetriever,
    RetrieverConfigurationError,
    RetrieverError,
    RetrieverRateLimitError,
    WebSearchRetriever,
    create_default_retriever,
)
from verification.search_providers import (
    PROVIDERS,
    SEARCH_MAX_RETRIES,
    SEARCH_RETRY_BASE_SECONDS,
    SEARCH_RETRY_MAX_SECONDS,
    SearchConfigurationError,
    SearchProviderError,
    SearchRateLimitError,
    SearchResponse,
    TavilyProvider,
    build_search_provider,
    parse_retry_after,
)
from verification.service import VerificationService

API_KEY = "tvly-test-key"


class _Recorder:
    """Injected transport returning canned responses and recording each call.

    ``script`` is either one :class:`SearchResponse` repeated, or a list consumed
    one entry per call so a retry sequence can be driven.
    """

    def __init__(
        self,
        payload: Any = None,
        error: Exception = None,
        status_code: int = 200,
        headers: Dict[str, str] = None,
        script: List[Any] = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.status_code = status_code
        self.headers = headers or {}
        self.script = script
        self.calls: List[Dict[str, Any]] = []
        self.slept: List[float] = []

    def __call__(self, url, headers, payload, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        if self.script is not None:
            index = min(len(self.calls) - 1, len(self.script) - 1)
            return self.script[index]
        return SearchResponse(
            status_code=self.status_code, headers=dict(self.headers), payload=self.payload
        )

    @property
    def call(self) -> Dict[str, Any]:
        assert len(self.calls) == 1, f"expected exactly one call, got {len(self.calls)}"
        return self.calls[0]


class _FakeClock:
    """Stands in for the ``time`` module inside the provider namespace.

    Recording instead of sleeping keeps the retry budget asserted rather than
    endured, and monkeypatch restores the real module afterwards.
    """

    def __init__(self) -> None:
        self.waits: List[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)


def _fake_clock(monkeypatch) -> _FakeClock:
    import verification.search_providers as providers

    clock = _FakeClock()
    monkeypatch.setattr(providers, "time", clock)
    return clock


def _tavily_result(**overrides: Any) -> Dict[str, Any]:
    """One Tavily-shaped search result."""
    record = {
        "title": "NASA Apollo 11 Mission Overview",
        "url": "https://www.nasa.gov/mission_pages/apollo/apollo-11.html",
        "content": "Apollo 11 landed humans on the Moon on July 20, 1969.",
        "score": 0.94,
    }
    record.update(overrides)
    return record


def _provider(transport: _Recorder) -> TavilyProvider:
    return TavilyProvider(API_KEY, transport=transport)


def _retriever(transport: _Recorder) -> WebSearchRetriever:
    return WebSearchRetriever(
        api_key=API_KEY, provider="tavily", provider_client=_provider(transport)
    )


# ---------------------------------------------------------------------------
# provider wiring
# ---------------------------------------------------------------------------


def test_tavily_request_shape_and_endpoint() -> None:
    transport = _Recorder({"results": [_tavily_result()]})
    provider = _provider(transport)

    results = provider.search("apollo 11 moon landing", max_results=3)

    assert results == [_tavily_result()]
    call = transport.call
    assert call["url"] == "https://api.tavily.com/search"
    assert call["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["payload"]["query"] == "apollo 11 moon landing"
    assert call["payload"]["max_results"] == 3


def test_tavily_is_the_registered_default_provider() -> None:
    assert "tavily" in PROVIDERS
    assert TavilyProvider.name == "tavily"
    assert WebSearchRetriever.DEFAULT_PROVIDER == "tavily"
    assert build_search_provider("tavily", API_KEY, transport=_Recorder({})).name == "tavily"


def test_provider_name_is_case_insensitive() -> None:
    provider = build_search_provider(" Tavily ", API_KEY, transport=_Recorder({}))
    assert isinstance(provider, TavilyProvider)


def test_unknown_provider_is_rejected_by_name() -> None:
    with pytest.raises(SearchProviderError) as excinfo:
        build_search_provider("bing", API_KEY)
    message = str(excinfo.value)
    assert "SEARCH_PROVIDER" in message
    assert "tavily" in message


def test_provider_requires_an_api_key() -> None:
    with pytest.raises(SearchProviderError) as excinfo:
        TavilyProvider("")
    assert "SEARCH_API_KEY" in str(excinfo.value)


def test_empty_results_are_returned_as_an_empty_list() -> None:
    """No results is a valid, non-error answer from the provider."""
    transport = _Recorder({"results": [], "response_time": 0.4})
    assert _provider(transport).search("anything") == []


def test_provider_error_is_wrapped_and_names_the_cause() -> None:
    transport = _Recorder(error=RuntimeError("connection reset"))
    with pytest.raises(SearchProviderError) as excinfo:
        _provider(transport).search("anything")
    assert "connection reset" in str(excinfo.value)


def test_malformed_payload_is_a_provider_error_not_empty_evidence() -> None:
    for payload in ({}, {"results": "not-a-list"}, {"results": {"a": 1}}, ["nope"]):
        transport = _Recorder(payload)
        with pytest.raises(SearchProviderError):
            _provider(transport).search("anything")


def test_non_dict_entries_are_dropped() -> None:
    transport = _Recorder({"results": [_tavily_result(), "junk", None]})
    assert _provider(transport).search("anything") == [_tavily_result()]


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_non_transient_http_errors_raise_immediately(monkeypatch, status: int) -> None:
    """A bad key or path will not fix itself, so it is never retried."""
    clock = _fake_clock(monkeypatch)
    transport = _Recorder(payload={"error": "nope"}, status_code=status)

    with pytest.raises(SearchProviderError) as excinfo:
        _provider(transport).search("anything")

    assert str(status) in str(excinfo.value)
    assert len(transport.calls) == 1
    assert clock.waits == []


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_not_retried_either(monkeypatch, status: int) -> None:
    clock = _fake_clock(monkeypatch)
    transport = _Recorder(payload={"error": "boom"}, status_code=status)

    with pytest.raises(SearchProviderError) as excinfo:
        _provider(transport).search("anything")

    assert str(status) in str(excinfo.value)
    assert len(transport.calls) == 1
    assert clock.waits == []


def test_non_json_error_body_does_not_crash_the_transport() -> None:
    """A 500 with an HTML body still reports a clean HTTP error."""
    class _HtmlTransport:
        def __call__(self, url, headers, payload, timeout_seconds):
            return SearchResponse(status_code=500, headers={}, payload=None)

    with pytest.raises(SearchProviderError) as excinfo:
        TavilyProvider(API_KEY, transport=_HtmlTransport()).search("anything")
    assert "500" in str(excinfo.value)


def test_transport_returning_the_wrong_type_is_rejected() -> None:
    class _BadTransport:
        def __call__(self, url, headers, payload, timeout_seconds):
            return {"results": []}

    with pytest.raises(SearchProviderError) as excinfo:
        TavilyProvider(API_KEY, transport=_BadTransport()).search("anything")
    assert "SearchResponse" in str(excinfo.value)


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------


def _throttled(retry_after: str = None) -> SearchResponse:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return SearchResponse(status_code=429, headers=headers, payload={"detail": "slow down"})


def test_429_then_success_is_retried_and_honours_retry_after(monkeypatch) -> None:
    clock = _fake_clock(monkeypatch)
    transport = _Recorder(
        script=[_throttled("2"), SearchResponse(200, {}, {"results": [_tavily_result()]})]
    )

    results = _provider(transport).search("anything")

    assert results == [_tavily_result()]
    assert len(transport.calls) == 2
    assert clock.waits == [2.0]


def test_429_without_retry_after_uses_bounded_exponential_backoff(monkeypatch) -> None:
    clock = _fake_clock(monkeypatch)
    transport = _Recorder(
        script=[_throttled(), SearchResponse(200, {}, {"results": [_tavily_result()]})]
    )

    _provider(transport).search("anything")

    assert clock.waits == [SEARCH_RETRY_BASE_SECONDS]


def test_absurd_retry_after_is_clamped(monkeypatch) -> None:
    """A provider asking for an hour must not park a live verification."""
    clock = _fake_clock(monkeypatch)
    transport = _Recorder(
        script=[_throttled("3600"), SearchResponse(200, {}, {"results": []})]
    )

    _provider(transport).search("anything")

    assert clock.waits == [SEARCH_RETRY_MAX_SECONDS]


def test_retries_stop_after_the_maximum_attempts(monkeypatch) -> None:
    clock = _fake_clock(monkeypatch)
    transport = _Recorder(status_code=429, payload={"detail": "slow down"})

    with pytest.raises(SearchRateLimitError) as excinfo:
        _provider(transport).search("anything")

    # Literals, not the constant: the bound must not drift silently.
    assert len(transport.calls) == 3
    assert len(clock.waits) == 2
    assert excinfo.value.attempts == 3
    assert excinfo.value.status_code == 429
    assert "rate limited" in str(excinfo.value).lower()


def test_the_retry_budget_is_exactly_two() -> None:
    assert SEARCH_MAX_RETRIES == 2
    assert SEARCH_RETRY_BASE_SECONDS > 0
    assert SEARCH_RETRY_BASE_SECONDS * 2 ** (SEARCH_MAX_RETRIES - 1) <= (
        SEARCH_RETRY_MAX_SECONDS
    )


def test_rate_limit_error_carries_no_credential(monkeypatch) -> None:
    _fake_clock(monkeypatch)
    transport = _Recorder(status_code=429, payload={"detail": "slow down"})

    with pytest.raises(SearchRateLimitError) as excinfo:
        _provider(transport).search("anything")

    assert API_KEY not in str(excinfo.value)


def test_rate_limit_error_is_a_provider_error_and_a_configuration_error_too() -> None:
    """Existing `except SearchProviderError` handling keeps working."""
    assert issubclass(SearchRateLimitError, SearchProviderError)
    assert issubclass(SearchConfigurationError, SearchProviderError)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("5", 5.0),
        ("0", 0.0),
        ("", None),
        ("soon", None),
        ("-3", None),
        (None, None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),
    ],
)
def test_parse_retry_after(value, expected) -> None:
    assert parse_retry_after(value) == expected


def test_retriever_maps_rate_limiting_to_a_retriever_rate_limit_error(monkeypatch) -> None:
    """Distinct at the retriever boundary too, and still a RetrieverError."""
    _fake_clock(monkeypatch)
    transport = _Recorder(status_code=429, payload={"detail": "slow down"})
    retriever = WebSearchRetriever(
        api_key=API_KEY, provider="tavily", provider_client=_provider(transport)
    )

    with pytest.raises(RetrieverRateLimitError) as excinfo:
        retriever.retrieve("anything")

    assert isinstance(excinfo.value, RetrieverError)
    assert excinfo.value.attempts == 3
    assert "rate limited" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# search result -> EvidenceItem conversion
# ---------------------------------------------------------------------------


def test_single_search_result_converts_to_an_evidence_item() -> None:
    transport = _Recorder({"results": [_tavily_result()]})

    items = _retriever(transport).retrieve("apollo 11 moon landing")

    assert len(items) == 1
    item = items[0]
    assert isinstance(item, EvidenceItem)
    assert item.snippet == "Apollo 11 landed humans on the Moon on July 20, 1969."
    assert item.source_url == "https://www.nasa.gov/mission_pages/apollo/apollo-11.html"
    assert item.title == "NASA Apollo 11 Mission Overview"
    assert item.confidence == pytest.approx(0.94)


def test_multiple_search_results_all_convert() -> None:
    transport = _Recorder(
        {
            "results": [
                _tavily_result(url="https://a.example.com", score=0.9),
                _tavily_result(url="https://b.example.com", score=0.8),
                _tavily_result(url="https://c.example.com", score=0.7),
            ]
        }
    )

    items = _retriever(transport).retrieve("apollo 11", max_results=3)

    assert [i.source_url for i in items] == [
        "https://a.example.com",
        "https://b.example.com",
        "https://c.example.com",
    ]
    assert [round(i.confidence, 2) for i in items] == [0.9, 0.8, 0.7]


def test_max_results_caps_the_evidence_returned() -> None:
    transport = _Recorder(
        {"results": [_tavily_result(url=f"https://{n}.example.com") for n in range(5)]}
    )
    assert len(_retriever(transport).retrieve("apollo 11", max_results=2)) == 2


def test_alternative_provider_key_spellings_are_accepted() -> None:
    """Serper-style `link`/`snippet` and Google-style `body` still convert."""
    transport = _Recorder(
        {
            "results": [
                {"title": "Serper style", "link": "https://s.example.com", "snippet": "A snippet."},
                {"title": "Google style", "url": "https://g.example.com", "body": "A body."},
            ]
        }
    )
    items = _retriever(transport).retrieve("anything")
    assert [i.source_url for i in items] == ["https://s.example.com", "https://g.example.com"]
    assert [i.snippet for i in items] == ["A snippet.", "A body."]


# ---------------------------------------------------------------------------
# fabrication guards
# ---------------------------------------------------------------------------


def test_missing_snippet_is_dropped() -> None:
    transport = _Recorder(
        {
            "results": [
                _tavily_result(content="", url="https://empty.example.com"),
                _tavily_result(content="   ", url="https://blank.example.com"),
                _tavily_result(content=None, url="https://none.example.com"),
                _tavily_result(url="https://kept.example.com"),
            ]
        }
    )
    items = _retriever(transport).retrieve("anything")
    assert [i.source_url for i in items] == ["https://kept.example.com"]


def test_missing_url_is_dropped_rather_than_invented() -> None:
    """A placeholder citation would read as a real source. Nothing is invented."""
    transport = _Recorder(
        {
            "results": [
                _tavily_result(url="", content="An unattributed claim."),
                _tavily_result(url=None, content="Also unattributed."),
                _tavily_result(url="https://real.example.com"),
            ]
        }
    )
    items = _retriever(transport).retrieve("anything")

    assert len(items) == 1
    assert items[0].source_url == "https://real.example.com"
    assert all("example.com/placeholder" not in i.source_url for i in items)
    assert all(i.source_url for i in items)


def test_unscored_result_is_not_treated_as_maximally_confident() -> None:
    transport = _Recorder(
        {"results": [_tavily_result(score=None), _tavily_result(score="not-a-number")]}
    )
    items = _retriever(transport).retrieve("anything")

    assert items
    for item in items:
        assert item.confidence == WebSearchRetriever.DEFAULT_UNSCORED_CONFIDENCE
        assert item.confidence < 1.0


def test_zero_score_is_preserved_not_treated_as_missing() -> None:
    """`score: 0.0` is a real value; a truthiness check would have discarded it."""
    transport = _Recorder({"results": [_tavily_result(score=0.0)]})
    assert _retriever(transport).retrieve("anything")[0].confidence == 0.0


def test_confidence_is_clamped_into_range() -> None:
    transport = _Recorder(
        {"results": [_tavily_result(score=5.0), _tavily_result(score=-2.0)]}
    )
    assert [i.confidence for i in _retriever(transport).retrieve("anything")] == [1.0, 0.0]


def test_parse_search_results_accepts_a_titled_or_untitled_record() -> None:
    with_title = WebSearchRetriever.parse_search_results(
        [{"title": "T", "snippet": "s", "url": "https://a.example.com"}]
    )
    without_title = WebSearchRetriever.parse_search_results(
        [{"snippet": "s", "url": "https://b.example.com"}]
    )
    assert with_title[0].title == "T"
    assert without_title[0].title is None


def test_parse_search_results_ignores_non_dict_entries() -> None:
    assert WebSearchRetriever.parse_search_results(["junk", None, 7]) == []


# ---------------------------------------------------------------------------
# retriever behaviour
# ---------------------------------------------------------------------------


def test_blank_query_returns_empty_without_calling_the_provider() -> None:
    transport = _Recorder({"results": [_tavily_result()]})
    assert _retriever(transport).retrieve("   ") == []
    assert transport.calls == []


def test_missing_api_key_raises_a_configuration_error() -> None:
    retriever = WebSearchRetriever(api_key="", provider="tavily")
    assert retriever.is_configured is False
    with pytest.raises(RetrieverConfigurationError) as excinfo:
        retriever.retrieve("anything")
    assert "SEARCH_API_KEY" in str(excinfo.value)


def test_unknown_provider_raises_a_configuration_error_per_request() -> None:
    """Deferred so a misconfigured deployment still starts and reports per claim."""
    retriever = WebSearchRetriever(api_key=API_KEY, provider="bing")
    with pytest.raises(RetrieverConfigurationError) as excinfo:
        retriever.retrieve("anything")
    assert "SEARCH_PROVIDER" in str(excinfo.value)


def test_provider_failure_surfaces_as_a_retriever_error() -> None:
    """A broken integration must not be mistaken for an absence of evidence."""
    transport = _Recorder(error=RuntimeError("gateway down"))
    with pytest.raises(RetrieverError) as excinfo:
        _retriever(transport).retrieve("anything")
    assert "gateway down" in str(excinfo.value)


def test_empty_provider_results_reach_the_checker_as_unverifiable() -> None:
    transport = _Recorder({"results": []})
    service = VerificationService(retriever=_retriever(transport))

    result = service.verify_claim(
        {
            "type": "claim",
            "claimId": "claim_empty",
            "speaker": "Speaker 1",
            "claim": "A claim with no indexed evidence.",
            "timestamp": 1.0,
        }
    )

    assert result.verdict == VerdictType.UNVERIFIABLE
    assert result.source == "No source available"
    assert "No verifiable evidence" in result.reason


def test_custom_search_handler_still_short_circuits_the_provider() -> None:
    def handler(query, max_results):
        return [
            EvidenceItem(
                snippet="Custom handler confirmed the facts.",
                source_url="https://custom.example.com",
                stance="supports",
                confidence=0.95,
            )
        ]

    retriever = WebSearchRetriever(api_key="", provider="tavily", search_handler=handler)
    assert retriever.retrieve("anything")[0].source_url == "https://custom.example.com"


def test_api_key_is_never_exposed_on_a_retrieved_item() -> None:
    transport = _Recorder({"results": [_tavily_result()]})
    for item in _retriever(transport).retrieve("anything"):
        assert API_KEY not in item.snippet
        assert API_KEY not in item.source_url
        assert API_KEY not in (item.title or "")


# ---------------------------------------------------------------------------
# retriever selection
# ---------------------------------------------------------------------------


def test_real_mode_selects_the_web_retriever_even_without_a_key(monkeypatch) -> None:
    """Real mode must never silently inherit mock evidence."""
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    retriever = create_default_retriever(use_mock=False)
    assert isinstance(retriever, WebSearchRetriever)
    assert not isinstance(retriever, MockRetriever)


def test_real_mode_honours_an_explicit_provider(monkeypatch) -> None:
    retriever = create_default_retriever(use_mock=False, api_key=API_KEY, provider="tavily")
    assert isinstance(retriever, WebSearchRetriever)
    assert retriever.provider == "tavily"
    assert retriever.api_key == API_KEY


def test_mock_mode_selects_the_mock_retriever(monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_API_KEY", API_KEY)
    assert isinstance(create_default_retriever(use_mock=True), MockRetriever)
    assert isinstance(create_default_retriever(use_mock=True, api_key=API_KEY), MockRetriever)


def test_auto_selection_keeps_its_original_behaviour(monkeypatch) -> None:
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    assert isinstance(create_default_retriever(), MockRetriever)

    monkeypatch.setenv("SEARCH_API_KEY", API_KEY)
    assert isinstance(create_default_retriever(), WebSearchRetriever)


def test_search_provider_env_var_selects_the_provider(monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    retriever = create_default_retriever(use_mock=False, api_key=API_KEY)
    assert retriever.provider == "tavily"


# ---------------------------------------------------------------------------
# checker verdicts still hold with real-shaped evidence
# ---------------------------------------------------------------------------


def test_checker_true_case_with_real_evidence() -> None:
    transport = _Recorder(
        {
            "results": [
                _tavily_result(
                    content="NASA's Apollo 11 landed humans on the Moon on July 20, 1969.",
                    score=0.97,
                )
            ]
        }
    )
    result = VerificationService(retriever=_retriever(transport)).verify_claim(
        {
            "type": "claim",
            "claimId": "claim_true",
            "speaker": "Speaker 1",
            "claim": "Apollo 11 landed humans on the Moon in 1969.",
            "timestamp": 3.0,
        }
    )
    assert result.verdict == VerdictType.TRUE
    assert result.source == "https://www.nasa.gov/mission_pages/apollo/apollo-11.html"
    assert result.reason


def test_checker_false_case_with_real_evidence() -> None:
    transport = _Recorder(
        {
            "results": [
                _tavily_result(
                    content="The Bureau of Labor Statistics reported inflation slowed by 0.5%, not 15%.",
                    url="https://bls.gov/cpi/latest-numbers.htm",
                    score=0.95,
                )
            ]
        }
    )
    result = VerificationService(retriever=_retriever(transport)).verify_claim(
        {
            "type": "claim",
            "claimId": "claim_false",
            "speaker": "Speaker 1",
            "claim": "Inflation dropped by 15 percent last year.",
            "timestamp": 4.0,
        }
    )
    assert result.verdict == VerdictType.FALSE
    assert result.source == "https://bls.gov/cpi/latest-numbers.htm"


def test_checker_unverifiable_case_when_everything_is_filtered() -> None:
    """Unattributable results leave the checker with nothing to work from."""
    transport = _Recorder({"results": [_tavily_result(url="")]})
    result = VerificationService(retriever=_retriever(transport)).verify_claim(
        {
            "type": "claim",
            "claimId": "claim_unverifiable",
            "speaker": "Speaker 1",
            "claim": "An entirely unsupported statement.",
            "timestamp": 5.0,
        }
    )
    assert result.verdict == VerdictType.UNVERIFIABLE
    assert result.source == "No source available"


def test_checker_itself_is_unchanged_for_stanced_evidence() -> None:
    """Direct checker contract, independent of any provider."""
    checker = VerificationChecker()
    supports = EvidenceItem(
        snippet="Official filings confirm the figure.",
        source_url="https://sec.example.com/filing",
        stance="supports",
        confidence=0.9,
    )
    refutes = EvidenceItem(
        snippet="Official filings report a different figure.",
        source_url="https://sec.example.com/filing",
        stance="refutes",
        confidence=0.9,
    )
    claim = "The company sold two million units."

    assert checker.verify(claim, [supports])[0] == VerdictType.TRUE
    assert checker.verify(claim, [refutes])[0] == VerdictType.FALSE
    assert checker.verify(claim, [])[0] == VerdictType.UNVERIFIABLE
    # Conflicting stances must stay Unverifiable.
    assert checker.verify(claim, [supports, refutes])[0] == VerdictType.UNVERIFIABLE


def test_claim_id_is_preserved_across_real_retrieval() -> None:
    transport = _Recorder({"results": [_tavily_result()]})
    result = VerificationService(retriever=_retriever(transport)).verify_claim(
        {
            "type": "claim",
            "claimId": "session_abc_claim_004",
            "speaker": "Speaker 1",
            "claim": "Apollo 11 landed on the Moon.",
            "timestamp": 6.0,
        }
    )
    assert result.claimId == "session_abc_claim_004"
