"""Evidence retriever module.

Defines the abstract EvidenceRetriever interface and provides a zero-dependency
MockRetriever for local development and testing, plus WebSearchRetriever, which
delegates to a real search provider (see :mod:`verification.search_providers`)
and converts its records into EvidenceItem objects.

A retriever never invents evidence. A provider that returns nothing usable
yields ``[]``, and the checker turns that into an Unverifiable verdict; only a
genuine provider fault raises.
"""

import math
import os
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
import re

from verification.models import EvidenceItem
from verification.search_providers import (
    SearchProvider,
    SearchProviderError,
    SearchRateLimitError,
    build_search_provider,
)


class RetrieverError(Exception):
    """Base exception for retrieval errors."""


class RetrieverRateLimitError(RetrieverError):
    """The search provider rate limited us and the retry budget ran out.

    Distinct from a plain :class:`RetrieverError` so the caller can tell a
    transient throttle apart from a broken integration, without inventing a
    verdict from absent evidence. Subclasses the existing base so every current
    ``except RetrieverError`` keeps working.
    """

    def __init__(self, message: str, *, attempts: int = 0) -> None:
        super().__init__(message)
        self.attempts = attempts
    pass


class RetrieverConfigurationError(RetrieverError):
    """Raised when a retriever is misconfigured or lacks required credentials."""
    pass


class EvidenceRetriever(ABC):
    """Abstract interface for evidence retrieval components."""

    @abstractmethod
    def retrieve(self, query: str, max_results: int = 3) -> List[EvidenceItem]:
        """Retrieves relevant evidence snippets and sources for a given query.

        Args:
            query: The generated search query.
            max_results: Maximum number of evidence snippets to return.

        Returns:
            A list of EvidenceItem objects.
        """
        pass


class MockRetriever(EvidenceRetriever):
    """Local, deterministic evidence retriever for testing and offline development.

    Contains NO default knowledge base. Tests MUST inject evidence via
    ``register_evidence`` or the ``custom_records`` constructor argument.
    This ensures production code can never accidentally retrieve fabricated evidence.
    """

    def __init__(self, custom_records: Optional[Dict[str, List[EvidenceItem]]] = None):
        """Initializes mock retriever with an EMPTY knowledge base.

        Args:
            custom_records: Optional mapping of keyword -> EvidenceItem list for tests.
                           No default records are seeded.
        """
        self._records: List[dict] = []

        if custom_records:
            for keyword, items in custom_records.items():
                self.register_evidence(keywords=[keyword], items=items)

    def register_evidence(self, keywords: List[str], items: List[EvidenceItem]) -> None:
        """Dynamically registers evidence for matching queries during tests."""
        self._records.append({
            "keywords": [kw.lower() for kw in keywords],
            "items": items,
        })

    def retrieve(self, query: str, max_results: int = 3) -> List[EvidenceItem]:
        """Searches internal mock records for best token/keyword overlap."""
        if not query or not query.strip():
            return []

        normalized_query = query.lower()
        query_tokens = set(re.findall(r"\w+", normalized_query))

        best_matches: List[EvidenceItem] = []
        best_score = 0

        for record in self._records:
            match_score = 0
            for kw in record["keywords"]:
                # Check for exact substring match
                if kw in normalized_query:
                    match_score += 3
                else:
                    # Check token overlap
                    kw_tokens = set(re.findall(r"\w+", kw))
                    overlap = len(query_tokens.intersection(kw_tokens))
                    match_score += overlap

            if match_score > best_score and match_score >= 2:
                best_score = match_score
                best_matches = record["items"]

        return best_matches[:max_results]


class WebSearchRetriever(EvidenceRetriever):
    """Web search retriever backed by a real search provider.

    The provider is chosen by ``SEARCH_PROVIDER`` (default ``tavily``) and
    reached over plain JSON/HTTPS, so no vendor SDK is required. An explicit
    ``provider_client`` wins over name resolution, which is how tests inject a
    stub and never touch the network.

    A custom ``search_handler`` still short-circuits everything, preserving the
    original extension point. If neither a handler nor a credential is
    configured, :class:`RetrieverConfigurationError` is raised rather than
    silently degrading to mock evidence.
    """

    DEFAULT_PROVIDER = "tavily"

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        search_handler: Optional[Callable[[str, int], List[EvidenceItem]]] = None,
        provider_client: Optional[SearchProvider] = None,
    ):
        """Initializes the web search retriever.

        Args:
            api_key: Optional API key. If omitted, falls back to SEARCH_API_KEY env var.
            provider: Provider name (e.g. 'tavily'). Defaults to SEARCH_PROVIDER
                env var, then to DEFAULT_PROVIDER.
            search_handler: Optional callable returning an EvidenceItem list;
                short-circuits provider resolution entirely.
            provider_client: Optional prebuilt SearchProvider, used ahead of name
                resolution. This is the seam the tests stub.
        """
        self.api_key = api_key or os.getenv("SEARCH_API_KEY")
        self.provider = provider or os.getenv("SEARCH_PROVIDER") or self.DEFAULT_PROVIDER
        self.search_handler = search_handler
        self.provider_client = provider_client

    @property
    def is_configured(self) -> bool:
        """Returns True if an API key or custom search handler is configured."""
        return bool(self.search_handler or (self.api_key and self.api_key.strip()))

    def _resolve_provider(self) -> SearchProvider:
        """Build the provider client on first use and cache it.

        Deferred so a misconfigured deployment still starts and reports the
        problem per request, instead of failing at import or app startup.
        """
        if self.provider_client is not None:
            return self.provider_client
        try:
            self.provider_client = build_search_provider(self.provider, self.api_key)
        except SearchProviderError as exc:
            raise RetrieverConfigurationError(str(exc)) from exc
        return self.provider_client

    @staticmethod
    def parse_provider_score(raw: Any) -> Optional[float]:
        """Return the provider's own score, or ``None`` when it gave none.

        This is the only place a search score enters the system, so it is the
        only place that decides what counts as usable. A score is accepted
        exactly as the provider sent it, and anything else becomes ``None``:

        * a missing key, ``None`` or a non-numeric value means no score
        * a bool is rejected even though ``bool`` subclasses ``int``
        * ``NaN`` and infinities are rejected
        * a value outside ``0.0..1.0`` is rejected rather than clamped, because
          clamping would report a number the provider never gave

        Rejecting means ``None``, never a constant. An earlier version assigned
        ``0.60`` to any unscored result, which published a fabricated relevance
        to users as if the provider had returned it.
        """
        if raw is None or isinstance(raw, bool):
            return None
        if not isinstance(raw, (int, float)):
            return None
        value = float(raw)
        if math.isnan(value) or math.isinf(value):
            return None
        if not 0.0 <= value <= 1.0:
            return None
        return value

    @classmethod
    def parse_search_results(cls, raw_results: List[dict]) -> List[EvidenceItem]:
        """Convert generic search API items into EvidenceItem models.

        Accepts items with standard keys like:
        {'title': ..., 'snippet' / 'content' / 'body': ..., 'url' / 'link' / 'source': ...,
         'confidence' / 'score': ...}

        Records that cannot be attributed are dropped, never backfilled: a
        result with no snippet has nothing to compare, and one with no URL
        cannot be cited, so substituting a placeholder would put a fabricated
        source in front of the user as if it were real. The relevance score
        follows the same rule -- see :meth:`parse_provider_score`.
        """
        parsed_items: List[EvidenceItem] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet") or item.get("content") or item.get("body") or ""
            source_url = item.get("url") or item.get("link") or item.get("source")
            snippet_text = snippet.strip() if isinstance(snippet, str) else ""
            url_text = str(source_url).strip() if source_url else ""
            if not snippet_text or not url_text:
                continue
            title = item.get("title")
            # Both spellings are provider scores. Checked with `is None` rather
            # than truthiness, so a legitimate 0.0 survives as a real (if
            # useless) value instead of being mistaken for a missing one.
            raw_conf = item.get("confidence")
            if raw_conf is None:
                raw_conf = item.get("score")

            parsed_items.append(
                EvidenceItem(
                    snippet=snippet_text,
                    source_url=url_text,
                    title=title.strip() if isinstance(title, str) and title.strip() else None,
                    confidence=cls.parse_provider_score(raw_conf),
                )
            )
        return parsed_items

    def retrieve(self, query: str, max_results: int = 3) -> List[EvidenceItem]:
        """Retrieves evidence snippets for the query from the search provider.

        Returns [] when the provider has nothing useful to offer, which the
        checker reports as Unverifiable. Raises :class:`RetrieverError` when the
        provider call itself fails and :class:`RetrieverRateLimitError` when it
        was throttled, so neither a broken integration nor a transient throttle
        is ever mistaken for an absence of evidence.
        """
        if not query or not query.strip():
            return []

        if self.search_handler is not None:
            return self.search_handler(query, max_results)

        if not self.is_configured:
            raise RetrieverConfigurationError(
                f"WebSearchRetriever ({self.provider}) requires a configured API key or search_handler. "
                "Set the SEARCH_API_KEY environment variable or use MockRetriever for offline testing."
            )

        provider = self._resolve_provider()
        try:
            raw_results = provider.search(query, max_results)
        except SearchRateLimitError as exc:
            raise RetrieverRateLimitError(
                str(exc), attempts=exc.attempts
            ) from exc
        except SearchProviderError as exc:
            raise RetrieverError(str(exc)) from exc
        return self.parse_search_results(raw_results)[:max_results]


def create_default_retriever(
    use_mock: Optional[bool] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
) -> EvidenceRetriever:
    """Factory creating the appropriate retriever based on configuration.

    Args:
        use_mock: If True, explicitly returns MockRetriever. If False, always
                  returns WebSearchRetriever -- real mode never falls back to
                  mock evidence. If None, auto-selects WebSearchRetriever when a
                  key is present, otherwise MockRetriever.
        api_key: Optional API key override for WebSearchRetriever.
        provider: Optional provider name override for WebSearchRetriever.
    """
    if use_mock is True:
        return MockRetriever()

    if provider is None:
        provider = os.getenv("SEARCH_PROVIDER") or WebSearchRetriever.DEFAULT_PROVIDER

    if use_mock is False:
        return WebSearchRetriever(api_key=api_key or os.getenv("SEARCH_API_KEY"), provider=provider)

    resolved_key = api_key or os.getenv("SEARCH_API_KEY")
    if resolved_key and resolved_key.strip():
        return WebSearchRetriever(api_key=resolved_key.strip(), provider=provider)

    return MockRetriever()
