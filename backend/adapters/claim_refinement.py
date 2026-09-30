"""Additive claim-intelligence layer sitting in front of an existing engine.

P1 features 2, 3 and 4, composed as a single decorator so the router, the
schemas and the existing claim-extraction code are all left exactly as they
are. The pipeline simply gains a stage:

    LLMClaimEngine.extract_claims()          <- existing, untouched
        -> split_compound_claim()            <- new: one claim in, N claims out
        -> ClaimClassifier                   <- new: only FACTUAL_CLAIM survives
        -> ClaimDeduplicator                 <- new: never check the same claim twice
    -> router verifies each surviving claim <- existing, untouched

Design constraints, all deliberate:

* **The inner engine is the source of truth and is never modified.** This class
  only reads what the inner engine returned. If the inner engine raises, the
  exception propagates unchanged.
* **A ``FACTUAL_CLAIM`` is passed on byte for byte.** Classification gates; it
  never rewrites. The existing factual-claim path sees exactly the string the
  extractor produced.
* **Fails open, not closed.** Every stage is defensive. If a stage cannot make
  a decision it returns the input unchanged rather than dropping it, so a bug
  in the new layers can never silently swallow a real claim.
* **Identity is preserved.** Splitting mints deterministic sub-ids derived from
  the parent id, so no two claims can ever collide, and every claim keeps its
  original ``speaker``, ``timestamp``, ``sessionId`` and enrichment fields.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence

from backend.adapters.claim_engine import ClaimEngine
from backend.schemas import ClaimEvent, TranscriptEvent
from verification.claim_dedup import ClaimDeduplicator
from verification.classification import ClaimClassification, ClaimClassifier
from verification.compound import CompoundClaimSplitter

logger = logging.getLogger(__name__)


class RefinedClaimEngine(ClaimEngine):
    """Wraps a :class:`ClaimEngine` with compound splitting, classification
    and claim-level duplicate protection.

    Args:
        inner: The engine to delegate to. Its output is the only source of
            claims; this class never extracts one itself.
        classifier: Classifier for the gating step.
        splitter: Splitter for the compound-claim step.
        deduplicator: Per-session duplicate protection. One instance may be
            shared; its state is keyed by session.
    """

    def __init__(
        self,
        inner: ClaimEngine,
        classifier: Optional[ClaimClassifier] = None,
        splitter: Optional[CompoundClaimSplitter] = None,
        deduplicator: Optional[ClaimDeduplicator] = None,
    ) -> None:
        self._inner = inner
        self.classifier = classifier or ClaimClassifier()
        self.splitter = splitter or CompoundClaimSplitter()
        self.deduplicator = deduplicator or ClaimDeduplicator()

    @property
    def inner(self) -> ClaimEngine:
        """The wrapped engine."""
        return self._inner

    @property
    def name(self) -> str:
        """Report the wrapped engine's name.

        Health output and the wiring tests read ``engine.name``. Reporting the
        inner name keeps both exactly as they were before this layer existed.
        """
        return getattr(self._inner, "name", type(self._inner).__name__)

    @property
    def strict(self) -> bool:
        """Mirror the inner engine's strictness flag, when it has one."""
        return bool(getattr(self._inner, "strict", False))

    async def extract_claims(self, transcript: TranscriptEvent) -> List[ClaimEvent]:
        """Return the claims worth fact-checking from one transcript event.

        Delegates first, then refines. An empty inner result stays empty, and
        any error the inner engine raised propagates untouched.
        """
        claims = await self._inner.extract_claims(transcript)
        if not claims:
            return []

        return self.refine(transcript, claims)

    def refine(
        self, transcript: TranscriptEvent, claims: Sequence[ClaimEvent]
    ) -> List[ClaimEvent]:
        """Apply the three new stages to already-extracted claims.

        Exposed separately from :meth:`extract_claims` so the pipeline can be
        exercised without an async engine, and so the order of the stages is
        explicit at the one place it is defined.
        """
        if not claims:
            return []

        session_id = transcript.sessionId

        expanded: List[ClaimEvent] = []
        for claim in claims:
            expanded.extend(self._expand(claim))

        kept: List[ClaimEvent] = []
        for claim in expanded:
            classification = self._classify(claim.claim)
            if not classification.is_fact_checkable:
                logger.debug(
                    "Skipping claim %s: classified as %s (%s).",
                    claim.claimId,
                    classification.category.value,
                    classification.reason,
                )
                continue
            kept.append(claim)

        unique: List[ClaimEvent] = []
        for claim in kept:
            if self.deduplicator.accept(session_id, claim.claim):
                unique.append(claim)
            else:
                logger.debug(
                    "Skipping claim %s: an identical claim was already "
                    "processed in this session.",
                    claim.claimId,
                )

        return unique

    # -- stages -----------------------------------------------------------

    def _classify(self, text: str) -> ClaimClassification:
        """Classify one claim, failing open to FACTUAL_CLAIM."""
        try:
            return self.classifier.classify(text)
        except Exception as exc:  # noqa: BLE001 - never drop a claim on a bug
            logger.warning(
                "Claim classification failed (%s); treating the claim as factual.",
                type(exc).__name__,
            )
            from verification.classification import ClaimCategory

            return ClaimClassification(
                ClaimCategory.FACTUAL_CLAIM,
                "Classification unavailable; defaulting to the factual path.",
            )

    def _split(self, text: str) -> List[str]:
        """Split one claim, failing open to the original on error or on doubt."""
        try:
            pieces = self.splitter.split(text)
        except Exception as exc:  # noqa: BLE001 - never drop a claim on a bug
            logger.warning(
                "Compound claim splitting failed (%s); using the original claim.",
                type(exc).__name__,
            )
            return [text]
        return pieces or [text]

    def _expand(self, claim: ClaimEvent) -> List[ClaimEvent]:
        """Turn one extracted claim into the claims it actually asserts.

        A single assertion yields the original object, untouched. Several yield
        one :class:`ClaimEvent` per assertion, each keeping the parent's
        speaker, timestamp, session and enrichment, with a deterministic
        sub-id so no two claims can collide.
        """
        pieces = self._split(claim.claim)
        if len(pieces) <= 1:
            return [claim]

        expanded: List[ClaimEvent] = []
        for index, piece in enumerate(pieces, start=1):
            update: Dict[str, Any] = {"claim": piece, "claimId": self._sub_id(claim, index)}
            expanded.append(claim.model_copy(update=update))
        return expanded

    @staticmethod
    def _sub_id(claim: ClaimEvent, index: int) -> str:
        """Return a deterministic, collision-free id for a split-off claim.

        Derived from the parent id, so the same sentence always yields the same
        ids and no sub-claim can collide with another claim in the session.
        """
        return f"{claim.claimId}.{index}"


def apply_claim_refinement(
    engine: ClaimEngine,
    *,
    enabled: bool = True,
) -> ClaimEngine:
    """Return ``engine`` with the refinement layer applied, or unchanged.

    Two deliberate guards keep this from altering any existing behaviour:

    * ``enabled=False`` returns the engine untouched.
    * An engine that is already refined is not wrapped a second time, so this
      stays safe to call from more than one place.
    """
    if not enabled or isinstance(engine, RefinedClaimEngine):
        return engine
    return RefinedClaimEngine(engine)
