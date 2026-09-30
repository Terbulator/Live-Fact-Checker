"""Search-provider adapters backing real evidence retrieval.

The retriever (:mod:`verification.retriever`) owns evidence conversion and
provider selection; this module owns the wire format of one concrete search API.

Adding another provider means implementing :class:`SearchProvider` and
registering it in :data:`PROVIDERS`. Nothing in :mod:`verification.checker` or
:mod:`verification.models` changes, and no result is ever synthesised here: a
provider either returns real records or this raises.

Transport is an injected callable rather than a hard-wired client so the test
suite can exercise every path without a network call.

Rate limiting
-------------
HTTP 429 is transient, so it is retried within a hard budget that honours
``Retry-After``. Every other failure -- a bad key, a wrong path, a server fault
-- raises immediately, because retrying it only deepens the problem. This mirrors
the policy the LLM Gateway client uses, so both external dependencies behave the
same way.

The module is deliberately synchronous: the synchronous ``verification``
package is only ever driven from a worker thread by the backend adapter, so a
blocking :func:`time.sleep` cannot stall the event loop.
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Type

import httpx

#: How many times a 429 is retried after the initial attempt. Bounded on
#: purpose: a live demo must fail visibly rather than stall on a wedged provider.
SEARCH_MAX_RETRIES = 2

#: First backoff step when the provider sends no usable ``Retry-After``.
#: Doubles per attempt: 0.5s then 1.0s for SEARCH_MAX_RETRIES = 2.
SEARCH_RETRY_BASE_SECONDS = 0.5

#: Ceiling for any single wait, including a ``Retry-After`` the provider asks
#: for. Without this a header like ``Retry-After: 3600`` would park a live
#: verification for an hour.
SEARCH_RETRY_MAX_SECONDS = 8.0


class SearchResponse(NamedTuple):
    """What a transport returns: the status, the headers, and the decoded body."""

    status_code: int
    headers: Dict[str, str]
    payload: Any


#: ``(url, headers, payload, timeout_seconds) -> SearchResponse``.
Transport = Callable[[str, Dict[str, str], Dict[str, Any], float], SearchResponse]


class SearchProviderError(Exception):
    """Raised when a provider call fails or returns an unusable payload."""


class SearchConfigurationError(SearchProviderError):
    """Raised for an unknown provider name or a missing API key.

    A deployment mistake rather than a runtime fault, so callers can tell it
    apart from a provider that was reachable and then failed.
    """


class SearchRateLimitError(SearchProviderError):
    """The provider answered 429 and the bounded retry budget ran out.

    Carries no credential: only the attempt count and the wait the provider
    asked for, both safe to place in a log line or a structured error detail.
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        status_code: int = 429,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.status_code = status_code
        self.retry_after = retry_after


class SearchProvider(ABC):
    """A web-search API returning raw result dictionaries."""

    name: str = "search-provider"

    @abstractmethod
    def search(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """Return up to ``max_results`` raw result dictionaries.

        Raises:
            SearchRateLimitError: 429 that survived the retry budget.
            SearchProviderError: any other transport or payload failure.
        """
        raise NotImplementedError


def _httpx_transport(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_seconds: float,
) -> SearchResponse:
    """Default transport: one JSON POST over HTTPS.

    Never raises for an HTTP status. The status is returned so the caller can
    apply its own policy, and a non-JSON error body degrades to ``None`` rather
    than raising from inside the transport.
    """
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(url, headers=headers, json=payload)
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        return SearchResponse(
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            payload=body,
        )


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header into non-negative seconds.

    Accepts both RFC 9110 forms: delta-seconds and an HTTP-date. An unparsable
    or negative value yields ``None`` so the caller falls back to exponential
    backoff rather than trusting a malformed header.
    """
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None

    try:
        seconds = float(candidate)
    except (TypeError, ValueError):
        pass
    else:
        return seconds if seconds >= 0 else None

    try:
        when = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = (when - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delta)


def retry_delay(headers: Dict[str, str], attempt: int) -> float:
    """Seconds to wait before retrying, from ``Retry-After`` or backoff."""
    requested = parse_retry_after(headers.get("Retry-After"))
    if requested is not None:
        return min(requested, SEARCH_RETRY_MAX_SECONDS)
    return min(SEARCH_RETRY_BASE_SECONDS * (2**attempt), SEARCH_RETRY_MAX_SECONDS)


class TavilyProvider(SearchProvider):
    """Tavily Search API adapter.

    ``POST https://api.tavily.com/search`` with a bearer key returns
    ``results[]`` entries carrying ``title``, ``url``, ``content`` and a
    relevance ``score`` in ``0.0..1.0`` -- the four fields the retriever
    converts into an :class:`~verification.models.EvidenceItem`.

    Auth is ``Authorization: Bearer <key>``; the key is never logged and never
    placed in a returned payload or an error message.
    """

    name = "tavily"
    DEFAULT_BASE_URL = "https://api.tavily.com"
    DEFAULT_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        api_key: Optional[str],
        *,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        transport: Optional[Transport] = None,
    ) -> None:
        if not api_key or not str(api_key).strip():
            raise SearchConfigurationError(
                f"{self.name} requires an API key. Set the SEARCH_API_KEY "
                "environment variable."
            )
        self.api_key = str(api_key).strip()
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout_seconds = float(
            self.DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        )
        self._transport: Transport = transport or _httpx_transport

    # -- wire -------------------------------------------------------------

    def _request(self, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> SearchResponse:
        """Perform one request, normalising any transport fault."""
        try:
            response = self._transport(url, headers, payload, self.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - any transport fault is a provider fault
            raise SearchProviderError(
                f"{self.name} search failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(response, SearchResponse):
            raise SearchProviderError(
                f"{self.name} transport returned {type(response).__name__}, "
                "expected a SearchResponse."
            )
        return response

    def search(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        payload = {
            "query": query,
            "max_results": max(1, int(max_results)),
            "search_depth": "basic",
            # The checker does its own reasoning; an extra model-written answer
            # would be a second opinion smuggled in as evidence.
            "include_answer": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/search"
        attempts = SEARCH_MAX_RETRIES + 1

        for attempt in range(attempts):
            response = self._request(url, headers, payload)

            if response.status_code == 429:
                if attempt == attempts - 1:
                    raise SearchRateLimitError(
                        f"{self.name} rate limited at {url} after {attempts} "
                        "attempt(s) (HTTP 429). No evidence was retrieved.",
                        attempts=attempts,
                    )
                delay = retry_delay(response.headers, attempt)
                time.sleep(delay)
                continue

            if response.status_code >= 400:
                # 401/403/404 and 5xx are not transient; retrying cannot help.
                raise SearchProviderError(
                    f"{self.name} search failed with HTTP {response.status_code}."
                )

            return self._extract_results(response.payload)

        # Unreachable: the loop returns or raises on its final iteration.
        raise SearchRateLimitError(  # pragma: no cover - defensive
            f"{self.name} rate limiting did not resolve.",
            attempts=attempts,
        )

    def _extract_results(self, payload: Any) -> List[Dict[str, Any]]:
        """Pull the result records out of a 2xx body."""
        if not isinstance(payload, dict):
            raise SearchProviderError(
                f"{self.name} returned {type(payload).__name__}, expected a JSON object."
            )
        results = payload.get("results")
        if not isinstance(results, list):
            raise SearchProviderError(
                f"{self.name} response contained no 'results' list."
            )
        # Entries that are not objects carry nothing convertible, so they are
        # dropped here rather than failing the whole response.
        return [item for item in results if isinstance(item, dict)]


#: Registry consulted by :func:`build_search_provider`.
PROVIDERS: Dict[str, Type[SearchProvider]] = {
    TavilyProvider.name: TavilyProvider,
}


def build_search_provider(
    name: Optional[str], api_key: Optional[str], **kwargs: Any
) -> SearchProvider:
    """Instantiate the registered provider called ``name``.

    Raises:
        SearchConfigurationError: unknown provider name or missing API key.
    """
    key = (name or "").strip().lower()
    provider_cls = PROVIDERS.get(key)
    if provider_cls is None:
        supported = ", ".join(sorted(PROVIDERS)) or "none"
        raise SearchConfigurationError(
            f"Unknown SEARCH_PROVIDER {name!r}. Supported providers: {supported}."
        )
    return provider_cls(api_key, **kwargs)
