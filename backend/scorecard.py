"""Per-claim results and the deterministic video scorecard.

A video ingestion runs the ordinary ``transcript -> claim -> verification``
pipeline over every transcript segment, so the claims and verdicts already exist.
What was missing was the two things a person actually wants out of a video run:

* the **evidence behind each verdict** -- the supporting statement, the ranked
  citations, the speaker and the timestamp the claim was made at, so a viewer can
  jump to the moment and check it; and
* an **overall picture** -- how the video scored, in one place.

Both are derived here, from results that already exist. Nothing is estimated.

Why the scorecard cannot lie
----------------------------
The single most important property of this module is that it never produces a
number the system did not actually measure. Two specific hazards, both handled:

**A retrieval failure is not a verdict.** When evidence retrieval raises -- a
provider timeout, a missing credential, a rate limit -- the pipeline reports *no
verdict at all* for that claim. That is a different fact from a claim the system
tried to check and could not settle. Conflating them would quietly convert a
broken integration into a statistic about the video's truthfulness, which is
exactly the fabricated finding this project must not produce. So a claim with no
verdict is counted as :attr:`ClaimCheckStatus.FAILED` and kept out of every
verdict ratio, rather than being folded into ``UNVERIFIABLE``.

**An empty denominator has no percentage.** With no verified claim there is no
basis for a distribution, so every ratio is ``None``. It is never ``0.0``,
``0%`` or ``100%``: each of those is a claim about the video's accuracy that
nobody measured. The UI renders ``None`` as "not available" for the same reason
it renders an absent confidence as ``N/A``.

Percentages are computed over *verified* claims, not over all claims. A video
where every check failed would otherwise report a flawless accuracy of 0
failures out of 0 checked, which reads as a result and is not one. Coverage is
reported separately and explicitly, so the difference between "nothing was true"
and "nothing could be checked" is always visible.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas import ClaimEvent, VerificationEvent, Verdict

__all__ = [
    "ClaimCheckStatus",
    "VideoClaimResult",
    "VideoScorecard",
    "build_claim_result",
    "build_scorecard",
]


class ClaimCheckStatus(str, Enum):
    """What became of one claim's check.

    Deliberately not a verdict. ``VERIFIED`` means a verdict was reached (and
    ``UNVERIFIABLE`` is one of them); ``FAILED`` means the check itself did not
    complete, so there is no verdict to report and nothing to count it as.
    """

    VERIFIED = "verified"
    FAILED = "failed"


class VideoClaimResult(BaseModel):
    """One claim from the video, with its verdict and the evidence behind it.

    Every evidence field is optional and defaults to absent. A claim whose
    retrieval failed carries a ``FAILED`` status and no verdict, reason, source
    or confidence, which is the honest representation: there was no evidence, so
    there is nothing to display and nothing to guess at.
    """

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    claim: str
    speaker: Optional[str] = None
    #: Offset into the source video, in seconds, preserved from the transcript
    #: segment so the moment can be located.
    timestamp: float = 0.0

    status: ClaimCheckStatus = ClaimCheckStatus.FAILED
    verdict: Optional[Verdict] = None
    reason: Optional[str] = None
    #: Evidence-grounded explanation. None when retrieval produced nothing
    #: citable; never synthesised to fill the field.
    supporting_statement: Optional[str] = None
    source: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    #: The lead source's provider relevance score, exactly as returned. None when
    #: the provider reported none; never defaulted.
    confidence: Optional[float] = None
    #: True when this verdict was replayed from the persistent cache.
    from_cache: bool = False
    #: Populated only when ``status`` is FAILED, describing why no verdict exists.
    error: Optional[str] = None


class VideoScorecard(BaseModel):
    """The deterministic summary of one video's fact-checking run.

    The counts are exact. The ratios are exact divisions of those counts, and
    are ``None`` whenever their denominator is zero.
    """

    model_config = ConfigDict(extra="ignore")

    #: Claims extracted from the video. Includes claims whose check failed.
    total_claims: int = 0
    #: Claims that produced a verdict. The denominator for every verdict ratio.
    checked_claims: int = 0
    #: Claims whose check did not complete. Reported separately, never as a verdict.
    failed_claims: int = 0

    true_claims: int = 0
    false_claims: int = 0
    ambiguous_claims: int = 0
    unverifiable_claims: int = 0

    #: Share of *checked* claims per verdict, 0.0..1.0. None when nothing was
    #: checked, because there is then no distribution to report.
    true_ratio: Optional[float] = None
    false_ratio: Optional[float] = None
    ambiguous_ratio: Optional[float] = None
    unverifiable_ratio: Optional[float] = None
    #: Share of all claims that produced a verdict, 0.0..1.0. None when no claim
    #: was extracted.
    coverage_ratio: Optional[float] = None


def build_claim_result(
    claim: ClaimEvent,
    verification: Optional[VerificationEvent],
    *,
    error: Optional[str] = None,
) -> VideoClaimResult:
    """Pair one extracted claim with its verification, if one was produced.

    Args:
        claim: The claim the pipeline extracted, carrying its speaker and
            timestamp from the transcript segment.
        verification: The verdict for that claim, or ``None`` when the check did
            not complete.
        error: Why the check failed, when it did. Ignored for a verified claim,
            which has its own evidence to show instead.

    A ``None`` verification produces a ``FAILED`` result with every evidence
    field left empty. That is the whole point: the absence is recorded, and no
    placeholder verdict, source or confidence is manufactured to fill the gap.
    """
    if verification is None:
        return VideoClaimResult(
            claim_id=claim.claimId,
            claim=claim.claim,
            speaker=claim.speaker,
            timestamp=claim.timestamp,
            status=ClaimCheckStatus.FAILED,
            error=error
            or "Verification did not complete; no verdict was reached for this claim.",
        )

    return VideoClaimResult(
        claim_id=verification.claimId or claim.claimId,
        claim=claim.claim,
        speaker=verification.speaker or claim.speaker,
        timestamp=verification.timestamp if verification.timestamp else claim.timestamp,
        status=ClaimCheckStatus.VERIFIED,
        verdict=verification.verdict,
        reason=verification.reason,
        supporting_statement=verification.supportingStatement,
        source=verification.source,
        # Copied rather than shared: the caller owns the event's list, and a
        # caller mutating a result must not be able to reach back into it.
        sources=[dict(entry) for entry in (verification.sources or [])],
        confidence=verification.confidence,
        from_cache=bool(verification.fromCache),
    )


def _ratio(count: int, denominator: int) -> Optional[float]:
    """Return ``count / denominator``, or ``None`` when there is no denominator.

    The ``None`` is the point. A zero denominator means nothing was measured, and
    reporting ``0.0`` for it would state that nothing was true, which is a claim
    about the video this system cannot support.
    """
    if denominator <= 0:
        return None
    return count / denominator


def build_scorecard(results: Sequence[VideoClaimResult]) -> VideoScorecard:
    """Build the scorecard for one video's results.

    Deterministic by construction: it counts what is in ``results`` and divides.
    The same results always produce the same scorecard, and no verdict,
    percentage or evidence is introduced that is not already in the input.
    """
    true_claims = 0
    false_claims = 0
    ambiguous_claims = 0
    unverifiable_claims = 0
    failed_claims = 0

    for result in results:
        if result.status is ClaimCheckStatus.FAILED:
            failed_claims += 1
            continue

        verdict = result.verdict
        if verdict is Verdict.TRUE:
            true_claims += 1
        elif verdict is Verdict.FALSE:
            false_claims += 1
        elif verdict is Verdict.AMBIGUOUS:
            ambiguous_claims += 1
        elif verdict is Verdict.UNVERIFIABLE:
            unverifiable_claims += 1
        else:
            # A result marked verified but carrying no verdict is inconsistent
            # input. Counting it as checked would put an unmeasured claim into a
            # measured ratio, so it is treated as a failure instead.
            failed_claims += 1

    total_claims = len(results)
    checked_claims = true_claims + false_claims + ambiguous_claims + unverifiable_claims

    return VideoScorecard(
        total_claims=total_claims,
        checked_claims=checked_claims,
        failed_claims=failed_claims,
        true_claims=true_claims,
        false_claims=false_claims,
        ambiguous_claims=ambiguous_claims,
        unverifiable_claims=unverifiable_claims,
        true_ratio=_ratio(true_claims, checked_claims),
        false_ratio=_ratio(false_claims, checked_claims),
        ambiguous_ratio=_ratio(ambiguous_claims, checked_claims),
        unverifiable_ratio=_ratio(unverifiable_claims, checked_claims),
        coverage_ratio=_ratio(checked_claims, total_claims),
    )
