"""Claim verification logic.

Compares an extracted claim against retrieved evidence items to determine:
- True
- False
- Unverifiable

Synthesizes a concise rationale and points to the primary authoritative source.
Adheres strictly to the principle: if evidence is missing, weak, or conflicting,
the verdict must be Unverifiable.
"""

from typing import List, Tuple
import re

from verification.models import EvidenceItem, VerdictType

# Keywords in evidence indicating refutation or contradiction
REFUTATION_SIGNALS = [
    r"\bnot\b",
    r"\bincorrect\b",
    r"\bfalse\b",
    r"\bdebunked\b",
    r"\bdenied\b",
    r"\buntrue\b",
    r"\bmisleading\b",
    r"\bcontrary\b",
    r"\bdifferent\b",
]

# Keywords indicating conflicting or disputing reports
CONFLICT_SIGNALS = [
    r"\bconflicting\b",
    r"\bdisputed\b",
    r"\bunclear\b",
    r"\bunsettled\b",
    r"\bcontradictory\b",
    r"\bmixed reports\b",
]


NUM_WORD_MAP = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "twelve": "12", "fifteen": "15", "twenty": "20",
    "hundred": "100", "thousand": "1000", "million": "1000000", "billion": "1000000000",
}


def extract_numerical_tokens(text: str) -> set:
    """Extracts numeric values and quantity terms from text."""
    tokens = set()
    for word in re.findall(r"\b\w+(?:\.\w+)?%?\b", text.lower()):
        if word in NUM_WORD_MAP:
            tokens.add(NUM_WORD_MAP[word])
        elif re.match(r"^\d+(?:\.\d+)?%?$", word):
            tokens.add(word)
    return tokens


class VerificationChecker:
    """Evaluates claims against retrieved evidence snippets."""

    def __init__(self, min_confidence_threshold: float = 0.60):
        self.min_confidence_threshold = min_confidence_threshold

    def verify(self, claim_text: str, evidence: List[EvidenceItem]) -> Tuple[VerdictType, str, str]:
        """Evaluates a claim against a list of retrieved evidence snippets.

        Returns:
            A tuple of (VerdictType, reason_string, primary_source_url)
        """
        # 1. No evidence found -> Unverifiable
        if not evidence:
            return (
                VerdictType.UNVERIFIABLE,
                "No verifiable evidence found from trusted sources to evaluate this claim.",
                "No source available",
            )

        # Filter out empty snippets or extremely low-confidence noise
        usable_evidence = [
            e for e in evidence
            if e.confidence >= self.min_confidence_threshold and e.snippet and e.snippet.strip()
        ]
        if not usable_evidence:
            return (
                VerdictType.UNVERIFIABLE,
                "Retrieved sources do not have sufficient confidence or relevance to corroborate this claim.",
                evidence[0].source_url if evidence else "No source available",
            )

        # 2. Check for conflicting evidence
        has_conflict_stance = any(e.stance == "conflicting" for e in usable_evidence)
        stances = {e.stance for e in usable_evidence if e.stance in ("supports", "refutes")}
        has_opposing_stances = ("supports" in stances and "refutes" in stances)

        text_has_conflict = any(
            any(re.search(pat, e.snippet, re.IGNORECASE) for pat in CONFLICT_SIGNALS)
            for e in usable_evidence
        )

        if has_conflict_stance or has_opposing_stances or text_has_conflict:
            return (
                VerdictType.UNVERIFIABLE,
                "Available sources provide conflicting or inconclusive information regarding this claim.",
                usable_evidence[0].source_url,
            )

        # 3. Check for refutation / contradiction
        primary_evidence = usable_evidence[0]

        # Explicit refutes stance
        if primary_evidence.stance == "refutes":
            reason = self._generate_refutation_reason(claim_text, primary_evidence)
            return (VerdictType.FALSE, reason, primary_evidence.source_url)

        # Explicit supports stance
        if primary_evidence.stance == "supports":
            reason = self._generate_support_reason(claim_text, primary_evidence)
            return (VerdictType.TRUE, reason, primary_evidence.source_url)

        # 4. Text-based heuristic analysis if stance is neutral or unannotated
        return self._heuristic_analysis(claim_text, usable_evidence)

    def _generate_refutation_reason(self, claim: str, evidence: EvidenceItem) -> str:
        """Constructs a concise reason explaining why a claim is false."""
        snippet_lower = evidence.snippet.lower()

        # Check for numerical / figure discrepancy
        has_figures = any(
            re.search(pat, claim.lower())
            for pat in [r"\b\d+\b", r"\bmillion\b", r"\bbillion\b", r"\bpercent\b", r"%"]
        )
        if has_figures and ("not" in snippet_lower or "different" in snippet_lower or "reports" in snippet_lower or "confirm" in snippet_lower):
            return "The available source reports a different figure or contradictory data."

        return f"Authoritative sources contradict this statement: {evidence.snippet.strip()}"

    def _generate_support_reason(self, claim: str, evidence: EvidenceItem) -> str:
        """Constructs a concise reason explaining why a claim is true."""
        return "Authoritative sources confirm the accuracy of this statement."

    def _heuristic_analysis(
        self, claim: str, evidence: List[EvidenceItem]
    ) -> Tuple[VerdictType, str, str]:
        """Fallback heuristic evaluation based on lexical overlap, numerical data, and contradiction markers."""
        primary = evidence[0]
        snippet_lower = primary.snippet.lower()
        claim_lower = claim.lower()

        # Check for refutation markers in snippet
        is_refuted = any(re.search(pat, snippet_lower, re.IGNORECASE) for pat in REFUTATION_SIGNALS)

        claim_words = set(re.findall(r"\w+", claim_lower)) - {"the", "a", "an", "is", "was", "are", "were", "in", "on", "at", "to", "for"}
        evidence_words = set(re.findall(r"\w+", snippet_lower))
        overlap = len(claim_words.intersection(evidence_words))

        # Numerical comparison check
        claim_nums = extract_numerical_tokens(claim)
        evidence_nums = extract_numerical_tokens(primary.snippet)

        if claim_nums and evidence_nums and overlap >= 2:
            # If the numbers conflict on the same topic -> FALSE
            if not claim_nums.intersection(evidence_nums):
                return (
                    VerdictType.FALSE,
                    "The available source reports a different figure or contradictory data.",
                    primary.source_url,
                )

        if is_refuted and overlap >= 2:
            return (
                VerdictType.FALSE,
                "The available source contradicts or refutes this claim.",
                primary.source_url,
            )

        if overlap >= max(2, len(claim_words) // 2):
            # If the claim made a specific numerical assertion that wasn't corroborated by numbers
            if claim_nums and not evidence_nums:
                return (
                    VerdictType.UNVERIFIABLE,
                    "Available evidence does not corroborate the specific figures in this claim.",
                    primary.source_url,
                )
            return (
                VerdictType.TRUE,
                "Authoritative sources corroborate the key facts of this statement.",
                primary.source_url,
            )

        return (
            VerdictType.UNVERIFIABLE,
            "Available evidence is insufficient to verify or falsify this claim conclusively.",
            primary.source_url,
        )


def verify_claim_against_evidence(
    claim_text: str, evidence: List[EvidenceItem]
) -> Tuple[VerdictType, str, str]:
    """Functional convenience wrapper for claim verification."""
    checker = VerificationChecker()
    return checker.verify(claim_text, evidence)
