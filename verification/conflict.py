"""Detection of genuinely conflicting evidence.

P1 feature. The existing checker already refuses to pick a side when evidence
is explicitly tagged ``conflicting`` or when one snippet carries contradiction
wording. What it cannot do is notice a conflict in the far more common case:
several credible, *unannotated* search results that quietly disagree.

    "The company reported 2.1 million units."
      source A: "Revenue reached 2.1 million units for the year."   -> agrees
      source B: "Reported sales were 1.4 million units, not 2.1 million." -> disagrees

That is a real conflict, and answering TRUE or FALSE from it would be picking a
winner the evidence does not support. When the conflict cannot be resolved the
claim is reported ``UNVERIFIABLE``.

Resolution
----------
A conflict is only *unresolved* when neither side is clearly the better
evidence. If one side's best source is decisively more credible than the
other's, the conflict is resolved in favour of the credible side and the claim
keeps the verdict the base checker already gave it. That is what keeps this
layer from overriding a well-evidenced answer with one dissenting snippet.

What counts as a conflict
-------------------------
Three signals, and only three:

1. the retriever or a caller tagged the source ``conflicting``
2. the snippet explicitly contradicts the claim
3. the snippet states a different figure for the same subject

Known limit, stated rather than hidden: sources can name *different subjects*
for the same predicate while agreeing on every figure -- "India won the 2011
World Cup" against "Sri Lanka won the 2011 World Cup final". Telling those
apart needs to read the sentence's structure rather than its vocabulary, so
this layer deliberately declines to guess and leaves such a case to the
existing checker. Reporting UNVERIFIABLE for something the evidence does not
actually contradict would trade one unearned verdict for another.

Design constraints, all deliberate:

* **This never becomes the primary decision-maker.** :class:`ConflictDetector`
  is a pure function of ``(claim, evidence)``; it produces a report. Only
  :class:`ConflictAwareChecker` turns that report into a verdict, and only by
  *downgrading* a verdict to ``UNVERIFIABLE`` -- never by inventing one.
* **A conflict needs two genuinely independent sources.** Two snippets from
  the same site are one source repeating itself, not corroboration against
  contradiction. Independence is judged on domain, the one signal the retrieval
  abstraction already exposes.
* **Conservative by construction.** Every condition below is a requirement to
  *report* a conflict. Missing any one of them means no conflict, and the base
  checker's verdict stands.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlsplit
import re

from verification.checker import VerificationChecker
from verification.models import EvidenceItem, VerdictType


#: Wording that positively contradicts a claim. Deliberately narrower than the
#: checker's broad ``\bnot\b`` rule: a stray "not" in an unrelated clause must
#: never be enough to turn a corroborated claim into UNVERIFIABLE.
_REFUTATION_PATTERNS: Tuple[str, ...] = (
    r"\bis\s+not\b", r"\bwas\s+not\b", r"\bwere\s+not\b", r"\bare\s+not\b",
    r"\bwas\s+incorrect\b", r"\bis\s+incorrect\b", r"\bis\s+false\b",
    r"\bwas\s+false\b", r"\bnot\s+true\b", r"\buntrue\b", r"\bincorrect\b",
    r"\bdenied\b", r"\bdenies\b", r"\bdebunked\b", r"\bdisproved\b",
    r"\bmisleading\b", r"\binaccurate\b", r"\bwrong\b", r"\bmyth\b",
    r"\bnever\s+(?:happened|occurred|said|reported|announced|released|won)\b",
    r"\bcontrary\s+to\b", r"\bcontradicts?\b", r"\bno\s+evidence\s+that\b",
    r"\bregarding\s+reports\b", r"\bactually\s+(?:was|were|is|are)\b",
)

#: Function words carrying no evidential weight when comparing a snippet with
#: a claim.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "if", "then", "than", "that",
        "this", "these", "those", "there", "it", "its", "is", "are", "was",
        "were", "be", "been", "being", "to", "of", "in", "on", "at", "for",
        "with", "by", "from", "as", "about", "into", "over", "after",
        "before", "up", "down", "out", "off", "has", "have", "had", "will",
        "would", "can", "could", "should", "may", "might", "not", "no",
    }
)

_TOKEN = re.compile(r"\w+", re.UNICODE)

# ---------------------------------------------------------------------------
# Quantities
# ---------------------------------------------------------------------------
#
# Conflict detection is mostly a numbers problem: two sources rarely argue in
# words, they state different figures. These patterns turn "1.4 million units,
# not two million" and "1,400,000 units" into the same comparable key, so a
# genuine disagreement in scale is caught even when the units are written
# differently.

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

_MAGNITUDES = {
    "hundred": 100.0,
    "thousand": 1_000.0,
    "million": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "trillion": 1_000_000_000_000.0,
}

_BARE_NUMBER = r"\d+(?:[.,]\d+)*|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_MAGNITUDE_WORD = "|".join(sorted(_MAGNITUDES, key=len, reverse=True))

_QUANTITY = re.compile(
    rf"\b({_BARE_NUMBER})\s*({_MAGNITUDE_WORD})?\b", re.UNICODE
)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.UNICODE)


def _base_value(raw: str) -> Optional[float]:
    """Return the numeric value of a bare number token, digits or words."""
    cleaned = raw.replace(",", "").strip().lower()
    if cleaned in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[cleaned])
    try:
        return float(cleaned)
    except ValueError:
        return None


def quantity_keys(text: str) -> set:
    """Return the comparable quantity figures stated in ``text``.

    Magnitudes are folded into the number, so "2 million", "two million" and
    "2,000,000" all yield the same key while "1.4 million" yields a different
    one. Returns an empty set when the text states no figures at all, which the
    caller reads as "this text makes no numerical claim to contradict".
    """
    keys = set()
    for match in _QUANTITY.finditer(text or ""):
        base = _base_value(match.group(1))
        if base is None:
            continue
        magnitude = (match.group(2) or "").lower()
        if magnitude:
            base *= _MAGNITUDES[magnitude]
        keys.add(f"num:{base:g}")
    for match in _PERCENT.finditer(text or ""):
        try:
            keys.add(f"pct:{float(match.group(1)):g}")
        except ValueError:  # pragma: no cover - the pattern only matches digits
            continue
    return keys


@dataclass(frozen=True)
class EvidenceStance:
    """One piece of evidence, and what it says about the claim.

    Attributes:
        stance: ``"supports"``, ``"refutes"`` or ``"neutral"``. ``"neutral"``
            means this snippet neither confirms nor contradicts; it is still
            citable, it just does not vote.
        source_url: The item's URL, carried through for the report.
        confidence: The item's confidence, carried through for the report.
        snippet: A short excerpt used to explain the conflict to a reader.
        origin: ``"annotated"`` when the retriever supplied a stance,
            ``"derived"`` when it was inferred from the text, ``"manual"``
            when it was handed to the detector by a caller.
    """

    stance: str
    source_url: str
    confidence: float
    snippet: str
    origin: str = "derived"


@dataclass(frozen=True)
class ConflictReport:
    """The outcome of comparing every piece of evidence against the claim."""

    has_conflict: bool
    resolved: bool = False
    supporting: Tuple[EvidenceStance, ...] = ()
    refuting: Tuple[EvidenceStance, ...] = ()
    explanation: str = ""
    considered: int = 0
    neutral: Tuple[EvidenceStance, ...] = field(default_factory=tuple)

    @property
    def supporting_urls(self) -> List[str]:
        return [item.source_url for item in self.supporting]

    @property
    def refuting_urls(self) -> List[str]:
        return [item.source_url for item in self.refuting]


def _host_of(url: str) -> str:
    """Return the lowercased host of ``url``, or '' when it has none."""
    try:
        host = urlsplit(url or "").netloc
    except ValueError:
        return ""
    host = host.strip().lower()
    return host[4:] if host.startswith("www.") else host


def _identity_of(url: str) -> str:
    """Return the domain a source is judged independent by.

    Two URLs on the same host are the same voice. URLs with no host at all fall
    back to the full URL, so two distinct bare strings still count separately
    and two identical ones do not.
    """
    return _host_of(url) or (url or "").strip().lower()


def _content_words(text: str) -> set:
    return {word for word in _TOKEN.findall((text or "").lower()) if word not in _STOPWORDS}


def _excerpt(snippet: str, limit: int = 160) -> str:
    collapsed = " ".join((snippet or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rsplit(" ", 1)[0] + "…"


def _has_refutation_wording(snippet: str) -> bool:
    return any(
        re.search(pattern, snippet, re.IGNORECASE) for pattern in _REFUTATION_PATTERNS
    )


class ConflictDetector:
    """Decides whether retrieved evidence genuinely disagrees with itself.

    Stateless and safe to share between threads.
    """

    name = "conflict-detector"

    def __init__(
        self,
        min_confidence: float = 0.60,
        max_confidence_gap: float = 0.25,
        min_lexical_overlap: int = 2,
    ) -> None:
        #: Evidence below this relevance is not credible enough to create a
        #: conflict, mirroring the checker's own usability threshold.
        self.min_confidence = min_confidence
        #: How far apart the two sides may be in confidence before the conflict
        #: counts as resolved. Beyond this the better-evidenced side wins and
        #: the base verdict stands.
        self.max_confidence_gap = max_confidence_gap
        #: Minimum shared content words before a snippet is considered to be
        #: talking about the claim at all.
        self.min_lexical_overlap = min_lexical_overlap

    # -- stance inference -------------------------------------------------

    def stance_of(self, claim_text: str, item: EvidenceItem) -> EvidenceStance:
        """Return what one evidence item implies about ``claim_text``.

        An annotated stance is trusted. An unannotated one is inferred from the
        text, and anything that is neither clearly confirming nor clearly
        contradicting is reported ``neutral`` rather than guessed at.
        """
        annotated = EvidenceStance(
            stance=item.stance if item.stance in {"supports", "refutes"} else "neutral",
            source_url=item.source_url,
            confidence=item.confidence,
            snippet=_excerpt(item.snippet),
            origin="annotated",
        )
        if item.stance in {"supports", "refutes"}:
            return annotated
        if item.stance == "conflicting":
            return EvidenceStance(
                stance="conflicting",
                source_url=item.source_url,
                confidence=item.confidence,
                snippet=_excerpt(item.snippet),
                origin="annotated",
            )
        return self._derive_stance(claim_text, item)

    def _derive_stance(self, claim_text: str, item: EvidenceItem) -> EvidenceStance:
        """Infer a stance from the snippet text alone.

        Two independent routes to "refutes", checked in order because the
        numeric one is the more specific claim: explicit contradiction wording,
        then a figure that disagrees with the claim's. Everything else is
        supporting only when the snippet is clearly about the claim.
        """
        snippet = item.snippet or ""
        claim_words = _content_words(claim_text)
        snippet_words = _content_words(snippet)
        overlap = len(claim_words & snippet_words)

        # Too little shared vocabulary to say anything either way.
        if overlap < self.min_lexical_overlap:
            return self._neutral(item)

        if _has_refutation_wording(snippet):
            return self._refutes(item)

        claim_numbers = quantity_keys(claim_text)
        snippet_numbers = quantity_keys(snippet)
        if claim_numbers and snippet_numbers and not (claim_numbers & snippet_numbers):
            # Same subject, a different figure: a direct contradiction. A
            # single shared quantity means the two are discussing something
            # else, or agree on the figure that matters, so no contradiction
            # is claimed.
            return self._refutes(item)

        # The snippet talks about the claim and contradicts nothing in it.
        return self._supports(item)

    def _neutral(self, item: EvidenceItem) -> EvidenceStance:
        return EvidenceStance(
            stance="neutral",
            source_url=item.source_url,
            confidence=item.confidence,
            snippet=_excerpt(item.snippet),
        )

    def _supports(self, item: EvidenceItem) -> EvidenceStance:
        return EvidenceStance(
            stance="supports",
            source_url=item.source_url,
            confidence=item.confidence,
            snippet=_excerpt(item.snippet),
        )

    def _refutes(self, item: EvidenceItem) -> EvidenceStance:
        return EvidenceStance(
            stance="refutes",
            source_url=item.source_url,
            confidence=item.confidence,
            snippet=_excerpt(item.snippet),
        )

    # -- conflict decision ------------------------------------------------

    def usable(self, evidence: Optional[Sequence[EvidenceItem]]) -> List[EvidenceItem]:
        """Return the evidence credible enough to vote on a conflict."""
        if not evidence:
            return []
        return [
            item
            for item in evidence
            if isinstance(item, EvidenceItem)
            and item.confidence >= self.min_confidence
            and item.snippet
            and item.snippet.strip()
        ]

    def detect(
        self, claim_text: str, evidence: Optional[Sequence[EvidenceItem]]
    ) -> ConflictReport:
        """Return whether the evidence genuinely disagrees with itself.

        Args:
            claim_text: The claim under consideration.
            evidence: Everything the retriever returned for it.

        Returns:
            A :class:`ConflictReport`. ``has_conflict`` is True only when two
            sources on *different domains* disagree and neither is clearly the
            better evidence.
        """
        usable = self.usable(evidence)
        if len(usable) < 2:
            return ConflictReport(
                has_conflict=False,
                resolved=True,
                explanation="Not enough usable evidence to disagree with itself.",
                considered=len(usable),
            )

        stances = [self.stance_of(claim_text, item) for item in usable]

        # An explicit "conflicting" tag is itself a declared conflict, and it
        # needs no second opinion: the source is telling us it is disputed.
        declared = [s for s in stances if s.stance == "conflicting"]
        if declared:
            return ConflictReport(
                has_conflict=True,
                resolved=False,
                refuting=tuple(declared),
                explanation=(
                    "Sources explicitly report that this claim is disputed or "
                    "inconclusive, so it cannot be settled one way."
                ),
                considered=len(usable),
            )

        supporting = [s for s in stances if s.stance == "supports"]
        refuting = [s for s in stances if s.stance == "refutes"]
        neutral = [s for s in stances if s.stance == "neutral"]

        if not supporting or not refuting:
            return ConflictReport(
                has_conflict=False,
                resolved=True,
                explanation="No source contradicts another on this claim.",
                considered=len(usable),
                neutral=tuple(neutral),
            )

        # Both sides must come from genuinely different sources. One outlet
        # quoted twice is not corroboration against contradiction.
        if not self._independent(supporting, refuting):
            return ConflictReport(
                has_conflict=False,
                resolved=True,
                explanation=(
                    "The agreeing and disagreeing snippets come from the same "
                    "source, so they are not independent."
                ),
                considered=len(usable),
                supporting=tuple(supporting),
                refuting=tuple(refuting),
            )

        best_support = max(item.confidence for item in supporting)
        best_refute = max(item.confidence for item in refuting)
        gap = abs(best_support - best_refute)

        if gap > self.max_confidence_gap:
            # Resolved: one side is decisively better evidenced, so this is not
            # a standoff and the base checker's verdict stands.
            if best_support > best_refute:
                winner, loser = supporting, refuting
            else:
                winner, loser = refuting, supporting
            return ConflictReport(
                has_conflict=False,
                resolved=True,
                explanation=(
                    f"Disagreeing sources differ in credibility by {gap:.2f}, so "
                    "the better-evidenced account resolves the disagreement."
                ),
                considered=len(usable),
                supporting=tuple(winner),
                refuting=tuple(loser),
            )

        return ConflictReport(
            has_conflict=True,
            resolved=False,
            supporting=tuple(supporting),
            refuting=tuple(refuting),
            explanation=self._explanation(supporting, refuting),
            considered=len(usable),
            neutral=tuple(neutral),
        )

    @staticmethod
    def _independent(
        supporting: Sequence[EvidenceStance], refuting: Sequence[EvidenceStance]
    ) -> bool:
        """True when the two sides are not the same source."""
        return bool(
            {_identity_of(item.source_url) for item in supporting}
            - {_identity_of(item.source_url) for item in refuting}
        )

    @staticmethod
    def _explanation(
        supporting: Sequence[EvidenceStance], refuting: Sequence[EvidenceStance]
    ) -> str:
        """Build a reason a reader can act on, naming both sides."""
        support = max(supporting, key=lambda item: item.confidence)
        refute = max(refuting, key=lambda item: item.confidence)
        return (
            "Credible sources disagree on this claim and neither is clearly "
            f"better evidenced. One reports: “{support.snippet}” Another "
            f"reports: “{refute.snippet}” The claim is therefore reported as "
            "Unverifiable rather than decided by picking a side."
        )


class ConflictAwareChecker(VerificationChecker):
    """The existing checker, plus a guard against self-contradicting evidence.

    A strict superset of :class:`~verification.checker.VerificationChecker`:
    the base class is untouched and still decides every case it already
    decided. This subclass only ever *downgrades* a verdict that the base
    checker was confident about, and only when two independent credible
    sources disagree without one being clearly the better evidence.

    A claim the base checker already found unverifiable or ambiguous is
    returned untouched, so nothing about existing inconclusive behaviour
    changes.
    """

    def __init__(
        self,
        detector: Optional[ConflictDetector] = None,
        min_confidence_threshold: float = 0.60,
    ) -> None:
        super().__init__(min_confidence_threshold=min_confidence_threshold)
        self.detector = detector or ConflictDetector(
            min_confidence=min_confidence_threshold
        )

    def verify(
        self, claim_text: str, evidence: List[EvidenceItem]
    ) -> Tuple[VerdictType, str, str]:
        """Return the base verdict, downgraded when evidence conflicts."""
        verdict, reason, source = super().verify(claim_text, evidence)

        # Already inconclusive. Nothing to downgrade, and nothing to change.
        if verdict in (VerdictType.UNVERIFIABLE, VerdictType.AMBIGUOUS):
            return verdict, reason, source

        report = self.detector.detect(claim_text, evidence)
        if not report.has_conflict:
            return verdict, reason, source

        return VerdictType.UNVERIFIABLE, report.explanation, source
