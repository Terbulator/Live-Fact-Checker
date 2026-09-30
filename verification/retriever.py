"""Evidence retriever module.

Defines the abstract EvidenceRetriever interface and provides a zero-dependency
MockRetriever for local development and testing, along with an extensible stub for
connecting real web search engines (Tavily, Serper, Bing, etc.) in the future.
"""

import os
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional
import re

from verification.models import EvidenceItem


class RetrieverError(Exception):
    """Base exception for retrieval errors."""
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

    Uses keyword/token overlap against an internal knowledge base to simulate
    retrieval from authoritative publications without external network or API calls.
    """

    def __init__(self, custom_records: Optional[Dict[str, List[EvidenceItem]]] = None):
        """Initializes mock retriever with default knowledge base and optional custom records."""
        self._records: List[dict] = []
        self._seed_default_knowledge_base()

        if custom_records:
            for keyword, items in custom_records.items():
                self.register_evidence(keywords=[keyword], items=items)

    def _seed_default_knowledge_base(self) -> None:
        """Seeds standard test knowledge items covering true, false, conflicting, and statistical claims."""
        # 1. Company units sold (Numerical mismatch -> False)
        self.register_evidence(
            keywords=["company", "sold", "two million", "units", "million units"],
            items=[
                EvidenceItem(
                    snippet="Official regulatory filings confirm the company sold 1.2 million units in fiscal year 2023.",
                    source_url="https://sec.gov/edgar/filings/company-annual-2023.pdf",
                    title="SEC Annual Disclosure Report 2023",
                    stance="refutes",
                    confidence=0.98,
                )
            ],
        )

        # 2. Apollo 11 Moon landing (Clearly True)
        self.register_evidence(
            keywords=["apollo", "moon", "1969", "neil armstrong", "astronauts"],
            items=[
                EvidenceItem(
                    snippet="NASA's Apollo 11 successfully landed humans on the Moon on July 20, 1969.",
                    source_url="https://www.nasa.gov/mission_pages/apollo/apollo-11.html",
                    title="NASA Apollo 11 Mission Overview",
                    stance="supports",
                    confidence=0.99,
                )
            ],
        )

        # 3. Mount Everest location (Clearly False)
        self.register_evidence(
            keywords=["mount everest", "everest", "africa", "highest peak", "peak in africa"],
            items=[
                EvidenceItem(
                    snippet="Mount Everest is located in the Himalayas on the border of Nepal and China in Asia. Mount Kilimanjaro is the highest peak in Africa.",
                    source_url="https://britannica.com/place/Mount-Everest",
                    title="Encyclopaedia Britannica - Mount Everest",
                    stance="refutes",
                    confidence=0.99,
                )
            ],
        )

        # 4. Product release date (Conflicting evidence -> Unverifiable)
        self.register_evidence(
            keywords=["product release", "november 15", "release date", "launch date"],
            items=[
                EvidenceItem(
                    snippet="Tech Insider reports internal memos scheduling the product release for November 15.",
                    source_url="https://techinsider.example.com/exclusive-launch-dates",
                    title="Tech Insider Report",
                    stance="conflicting",
                    confidence=0.70,
                ),
                EvidenceItem(
                    snippet="Supply chain analysts state production bottlenecks delayed the product launch to Q1 next year.",
                    source_url="https://supplychaindaily.example.com/delays-confirmed",
                    title="Supply Chain Daily",
                    stance="conflicting",
                    confidence=0.72,
                ),
            ],
        )

        # 5. Inflation rate claim (Numerical exaggeration -> False)
        self.register_evidence(
            keywords=["inflation", "dropped", "15%", "15 percent", "rate dropped"],
            items=[
                EvidenceItem(
                    snippet="The Bureau of Labor Statistics reported consumer inflation slowed by 0.5% year-over-year, not 15%.",
                    source_url="https://bls.gov/cpi/latest-numbers.htm",
                    title="Bureau of Labor Statistics Consumer Price Index",
                    stance="refutes",
                    confidence=0.95,
                )
            ],
        )

        # 6. Earth orbits the Sun (Clearly True)
        self.register_evidence(
            keywords=["earth", "orbits", "sun", "solar system"],
            items=[
                EvidenceItem(
                    snippet="Earth completes one revolution around the Sun approximately every 365.25 days.",
                    source_url="https://solarsystem.nasa.gov/planets/earth/in-depth/",
                    title="NASA Solar System Exploration - Earth",
                    stance="supports",
                    confidence=1.0,
                )
            ],
        )

        # 7. 2011 Cricket World Cup (Clearly True - matches Atif's demo claim)
        self.register_evidence(
            keywords=["cricket", "world cup", "2011", "india won", "india"],
            items=[
                EvidenceItem(
                    snippet="India won the 2011 ICC Cricket World Cup, defeating Sri Lanka in the final at Wankhede Stadium in Mumbai.",
                    source_url="https://www.espncricinfo.com/series/icc-cricket-world-cup-2010-11-381449/india-vs-sri-lanka-final-433606/match-report",
                    title="2011 ICC Cricket World Cup Final",
                    stance="supports",
                    confidence=0.99,
                )
            ],
        )

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
    """Provider-independent web search retriever.

    Supports plugging in any external web search provider (e.g., Tavily, Serper,
    Google Custom Search, Bing) by providing an API key or custom search handler.
    If no search handler is provided and no SEARCH_API_KEY is found, raises
    RetrieverConfigurationError.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "generic",
        search_handler: Optional[Callable[[str, int], List[EvidenceItem]]] = None,
    ):
        """Initializes the web search retriever.

        Args:
            api_key: Optional API key. If omitted, falls back to SEARCH_API_KEY env var.
            provider: Informative name of the provider (e.g. 'tavily', 'serper', 'google').
            search_handler: Optional callable executing the search and returning EvidenceItem list.
        """
        self.api_key = api_key or os.getenv("SEARCH_API_KEY")
        self.provider = provider
        self.search_handler = search_handler

    @property
    def is_configured(self) -> bool:
        """Returns True if an API key or custom search handler is configured."""
        return bool(self.search_handler or (self.api_key and self.api_key.strip()))

    @classmethod
    def parse_search_results(cls, raw_results: List[dict]) -> List[EvidenceItem]:
        """Convenience utility to convert generic search API JSON items into EvidenceItem models.

        Accepts items with standard keys like:
        {'title': ..., 'snippet' / 'content' / 'body': ..., 'url' / 'link': ..., 'confidence' / 'score': ...}
        """
        parsed_items: List[EvidenceItem] = []
        for item in raw_results:
            snippet = item.get("snippet") or item.get("content") or item.get("body") or ""
            source_url = item.get("url") or item.get("link") or item.get("source") or "https://example.com"
            title = item.get("title")
            raw_conf = item.get("confidence") or item.get("score") or 1.0
            try:
                confidence = float(raw_conf)
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 1.0

            if snippet.strip():
                parsed_items.append(
                    EvidenceItem(
                        snippet=snippet.strip(),
                        source_url=str(source_url).strip(),
                        title=title.strip() if title else None,
                        confidence=confidence,
                    )
                )
        return parsed_items

    def retrieve(self, query: str, max_results: int = 3) -> List[EvidenceItem]:
        """Retrieves evidence snippets for the query.

        If a custom search_handler was provided, delegates to it.
        Otherwise, if no API key is configured, raises RetrieverConfigurationError.
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

        # Provider stub: When an external provider client is wired in, this delegates to it.
        # Until then, returns empty evidence without inventing fake external data.
        return []


def create_default_retriever(
    use_mock: Optional[bool] = None,
    api_key: Optional[str] = None,
) -> EvidenceRetriever:
    """Factory creating the appropriate retriever based on configuration.

    Args:
        use_mock: If True, explicitly returns MockRetriever. If False, returns WebSearchRetriever.
                  If None, auto-selects WebSearchRetriever if SEARCH_API_KEY is present,
                  otherwise defaults safely to MockRetriever.
        api_key: Optional API key override for WebSearchRetriever.
    """
    if use_mock is True:
        return MockRetriever()

    resolved_key = api_key or os.getenv("SEARCH_API_KEY")
    if use_mock is False:
        return WebSearchRetriever(api_key=resolved_key)

    if resolved_key and resolved_key.strip():
        return WebSearchRetriever(api_key=resolved_key.strip())

    return MockRetriever()
