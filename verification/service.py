"""Main verification service orchestrating the verification pipeline.

Pipeline stages:
    ClaimEvent
    → query generation
    → evidence retrieval
    → verification
    → VerificationEvent (with original claimId strictly preserved)

The supporting statement
------------------------
``reason`` and ``supportingStatement`` answer two different questions and are
both kept. ``reason`` is the checker's one-line rationale, which is what existing
clients already render. ``supportingStatement`` is the part that can be traced
back to the retrieved material: it names the source and quotes the actual
snippet the verdict rests on.

It is assembled from the evidence the retriever returned, in the same ranked
order the UI renders beside it, and nothing else. There is no lookup table, no
template of canned explanations, no second model call and no outside
knowledge, so every sentence it produces is a restatement of a snippet that
really came back from the search provider. With no citable evidence it is
``None`` rather than an apology: there is nothing to ground a sentence in.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

# Ensure project root is in sys.path when executed directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from verification.checker import VerificationChecker
from verification.models import ClaimEvent, EvidenceItem, VerdictType, VerificationEvent
from verification.query_generator import generate_search_query
from verification.retriever import EvidenceRetriever, MockRetriever, create_default_retriever
from verification.sources import primary_source, rank_sources, source_host

#: How the lead citation is introduced, by verdict. These are the only fixed
#: words in a supporting statement: they describe what the verdict concluded,
#: and every fact, figure and quotation in the sentence after them comes from a
#: retrieved snippet.
_LEAD_IN = {
    VerdictType.TRUE: "The retrieved evidence supports this claim.",
    VerdictType.FALSE: "The retrieved evidence contradicts this claim.",
    VerdictType.UNVERIFIABLE: "The retrieved evidence does not establish this claim.",
    VerdictType.AMBIGUOUS: "The retrieved evidence supports more than one reading of this claim.",
}

#: The stance an annotated source must carry to be quoted as the lead citation
#: for a verdict. Unannotated evidence has no stance and never matches, which is
#: what leaves those claims to quote the top-ranked source instead.
_STANCE_FOR_VERDICT = {
    VerdictType.TRUE: "supports",
    VerdictType.FALSE: "refutes",
}


def _host_label(url: str) -> str:
    """Render a citation's origin for a reader, without inventing a name."""
    host = source_host(url)
    return host if host else "the retrieved source"


def _lead_entry(
    ranked: Sequence[Dict[str, Any]],
    stance_by_url: Dict[str, str],
    verdict: VerdictType,
) -> Dict[str, Any]:
    """Choose which ranked citation the statement leads with.

    When the retriever or a caller annotated the evidence with a stance, the
    citation matching the verdict is the one the verdict actually rests on, so
    it is quoted. Otherwise the top-ranked source is quoted, which is the same
    item the UI shows as the primary citation.
    """
    wanted = _STANCE_FOR_VERDICT.get(verdict)
    if wanted is not None:
        for entry in ranked:
            if stance_by_url.get(str(entry.get("url", ""))) == wanted:
                return entry
    return ranked[0]


def build_supporting_statement(
    verdict: VerdictType,
    evidence: Optional[Sequence[EvidenceItem]],
) -> Optional[str]:
    """Return an explanation grounded only in the retrieved evidence.

    Args:
        verdict: The verdict the checker reached.
        evidence: Everything the retriever returned for this claim.

    Returns:
        A sentence naming the source it quotes, or ``None`` when no citable
        evidence came back -- in which case there is nothing to ground an
        explanation in and inventing one is the only way to produce text.

    The statements are assembled, not written: the verdict decides the framing
    word, the retrieved snippet supplies every fact in the sentence, and the
    URL's host attributes it. Nothing is looked up, inferred or recalled.
    """
    ranked = rank_sources(evidence)
    if not ranked:
        return None

    stance_by_url = {
        item.source_url: item.stance
        for item in (evidence or [])
        if isinstance(item, EvidenceItem) and item.stance
    }

    lead = _lead_entry(ranked, stance_by_url, verdict)
    quote = str(lead.get("snippet") or "").strip()
    if not quote:
        return None

    lead_in = _LEAD_IN.get(verdict, _LEAD_IN[VerdictType.UNVERIFIABLE])
    citation = f"{_host_label(str(lead.get('url', '')))} states: “{quote}”"

    if verdict is VerdictType.AMBIGUOUS:
        # Reflect the disagreement rather than summarising one side. Only a
        # source on a different domain counts, because one page quoted twice is
        # not a second opinion.
        lead_host = source_host(str(lead.get("url", "")))
        other = next(
            (
                entry
                for entry in ranked[1:]
                if source_host(str(entry.get("url", ""))) != lead_host
            ),
            None,
        )
        if other is not None:
            second = str(other.get("snippet") or "").strip()
            if second:
                return (
                    f"{lead_in} {_host_label(str(lead.get('url', '')))} states: "
                    f"“{quote}” Meanwhile {_host_label(str(other.get('url', '')))} "
                    f"states: “{second}”"
                )

    return f"{lead_in} {citation}"


class VerificationService:
    """Service handling the end-to-end fact verification workflow."""

    def __init__(
        self,
        retriever: Optional[EvidenceRetriever] = None,
        checker: Optional[VerificationChecker] = None,
    ):
        """Initializes the verification service with configurable retriever and checker.

        Args:
            retriever: EvidenceRetriever implementation (defaults to create_default_retriever()).
            checker: VerificationChecker implementation (defaults to standard checker).
        """
        self.retriever = retriever if retriever is not None else create_default_retriever()
        self.checker = checker if checker is not None else VerificationChecker()

    def verify_claim(self, claim_input: Union[ClaimEvent, dict, object]) -> VerificationEvent:
        """Runs a single ClaimEvent through the verification pipeline.

        Supports ClaimEvent instances, dictionaries adhering to the contract,
        or any object with a .model_dump() / .dict() method.

        Args:
            claim_input: Input claim data.

        Returns:
            A VerificationEvent with preserved claimId and determined verdict.
        """
        # 1. Parse & validate input contract
        if isinstance(claim_input, ClaimEvent):
            claim_event = claim_input
        elif isinstance(claim_input, dict):
            # Extract standard contract fields to allow friendly forwarding from other modules
            contract_keys = {"type", "claimId", "speaker", "claim", "timestamp"}
            filtered_payload = {k: v for k, v in claim_input.items() if k in contract_keys}
            claim_event = ClaimEvent(**filtered_payload)
        elif hasattr(claim_input, "model_dump"):
            dumped = claim_input.model_dump()
            contract_keys = {"type", "claimId", "speaker", "claim", "timestamp"}
            filtered_payload = {k: v for k, v in dumped.items() if k in contract_keys}
            claim_event = ClaimEvent(**filtered_payload)
        elif hasattr(claim_input, "dict"):
            dumped = claim_input.dict()
            contract_keys = {"type", "claimId", "speaker", "claim", "timestamp"}
            filtered_payload = {k: v for k, v in dumped.items() if k in contract_keys}
            claim_event = ClaimEvent(**filtered_payload)
        else:
            raise TypeError(f"Expected ClaimEvent, dict, or Pydantic model; received {type(claim_input)}")

        # 2. Query generation
        query = generate_search_query(claim_event.claim)

        # 3. Evidence retrieval
        evidence = self.retriever.retrieve(query)

        # 4. Comparison and verification
        verdict, reason, source = self.checker.verify(claim_event.claim, evidence)

        # 4b. Rank every citable item the retriever returned, not just the first.
        # `source` becomes the top-ranked citation so the primary link agrees
        # with the list the UI renders beside it.
        sources = rank_sources(evidence)

        # 4c. The evidence-grounded explanation, assembled from the same ranked
        # snippets. None when the retriever returned nothing citable.
        supporting_statement = build_supporting_statement(verdict, evidence)

        # 5. Output contract with strictly preserved claimId
        return VerificationEvent(
            type="verification",
            claimId=claim_event.claimId,
            verdict=verdict,
            reason=reason,
            source=primary_source(sources, source),
            sources=sources,
            supportingStatement=supporting_statement,
        )

    def verify_claim_dict(self, claim_input: Union[ClaimEvent, dict, object]) -> dict:
        """Convenience method returning a plain dictionary matching VerificationEvent contract."""
        return self.verify_claim(claim_input).model_dump()

    def verify_batch(self, claims: List[Union[ClaimEvent, dict, object]]) -> List[VerificationEvent]:
        """Runs a sequence of claims through the verification pipeline."""
        return [self.verify_claim(c) for c in claims]

    def verify_batch_dict(self, claims: List[Union[ClaimEvent, dict, object]]) -> List[dict]:
        """Runs a sequence of claims and returns plain dictionaries."""
        return [self.verify_claim_dict(c) for c in claims]


def verify_claim_event(
    claim_input: Union[ClaimEvent, dict, object],
    retriever: Optional[EvidenceRetriever] = None,
) -> VerificationEvent:
    """Convenience functional interface for verifying a single claim."""
    service = VerificationService(retriever=retriever)
    return service.verify_claim(claim_input)
