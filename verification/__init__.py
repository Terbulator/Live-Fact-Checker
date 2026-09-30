"""Verification module for the Live Fact-Checker project.

Exports core models, query generation, retrieval interface, checker, and
orchestration service.
"""

from verification.checker import VerificationChecker, verify_claim_against_evidence
from verification.models import (
    ClaimEvent,
    EvidenceItem,
    VerdictType,
    VerificationEvent,
)
from verification.query_generator import clean_conversational_text, generate_search_query
from verification.retriever import (
    EvidenceRetriever,
    MockRetriever,
    RetrieverConfigurationError,
    RetrieverError,
    RetrieverRateLimitError,
    WebSearchRetriever,
    create_default_retriever,
)
from verification.search_providers import (
    SearchConfigurationError,
    SearchProvider,
    SearchProviderError,
    SearchRateLimitError,
    SearchResponse,
    TavilyProvider,
    build_search_provider,
)
from verification.service import VerificationService, verify_claim_event

__all__ = [
    "ClaimEvent",
    "VerificationEvent",
    "VerdictType",
    "EvidenceItem",
    "generate_search_query",
    "clean_conversational_text",
    "EvidenceRetriever",
    "MockRetriever",
    "WebSearchRetriever",
    "create_default_retriever",
    "RetrieverError",
    "RetrieverConfigurationError",
    "RetrieverRateLimitError",
    "SearchProvider",
    "SearchProviderError",
    "SearchConfigurationError",
    "SearchRateLimitError",
    "SearchResponse",
    "TavilyProvider",
    "build_search_provider",
    "VerificationChecker",
    "verify_claim_against_evidence",
    "VerificationService",
    "verify_claim_event",
]
