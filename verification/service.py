"""Main verification service orchestrating the verification pipeline.

Pipeline stages:
ClaimEvent
→ query generation
→ evidence retrieval
→ verification
→ VerificationEvent (with original claimId strictly preserved)
"""

import sys
from pathlib import Path
from typing import List, Optional, Union

# Ensure project root is in sys.path when executed directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from verification.checker import VerificationChecker
from verification.models import ClaimEvent, VerificationEvent
from verification.query_generator import generate_search_query
from verification.retriever import EvidenceRetriever, MockRetriever, create_default_retriever


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

        # 5. Output contract with strictly preserved claimId
        return VerificationEvent(
            type="verification",
            claimId=claim_event.claimId,
            verdict=verdict,
            reason=reason,
            source=source,
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
