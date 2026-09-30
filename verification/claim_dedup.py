"""Claim-level duplicate protection.

P1 feature. The pipeline already deduplicates whole transcript segments and
whole ``claimId`` values. Neither covers the case this module handles: the
*same assertion arriving again under a fresh claim id*, which happens whenever
a speaker restates a point, when endpointing emits overlapping finals, and when
a session is resumed.

    "Ireland won the match."        -> processed
    "Ireland won the match."        -> skipped, the exact same claim
    "Ireland won the match by 5 wickets." -> processed, a different claim

Design constraints, all deliberate:

* **Exact-identity only.** Two claims are the same claim when their normalised
  text is identical -- case, punctuation and spacing aside. A claim that adds,
  drops or rewords anything is a *different* claim, because
  "won the match" and "won the match by 5 wickets" are not interchangeable and
  collapsing them would hide the difference from the fact-checker. There is
  deliberately no fuzzy, token-subset or near-duplicate matching: a similarity
  heuristic that is wrong here silently discards a real claim.
* **Additive only.** This complements the existing transcript and session
  deduplication; it never replaces or relaxes any of it.
* **Bounded and per-session.** State is keyed by session so two concurrent
  sessions never suppress each other's claims, and each session's set is capped
  so a long broadcast cannot grow it without limit.
"""

from typing import Dict, List, Optional, Set
import re


#: Punctuation and symbols are dropped when normalising. Letters and digits are
#: kept, so genuinely different wording never collapses onto one key.
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+", re.UNICODE)

#: How many distinct claim keys one session remembers. A speaker restating a
#: point does so within seconds, so only recent claims are ever needed to catch
#: a repeat; older ones cannot plausibly be re-sent. Bounded so an all-day
#: session cannot grow this without limit.
DEFAULT_MAX_TRACKED_CLAIMS = 200


def normalize_claim_text(text: str) -> str:
    """Return the comparison key for a claim.

    Case, punctuation and spacing are noise when deciding whether the same
    assertion has already been processed, so they are folded away. The words
    and the numbers are the identity and are preserved, so
    ``"Ireland won the match."`` and ``"Ireland won the match by 5 wickets."``
    produce two different keys.
    """
    if not isinstance(text, str):
        return ""
    stripped = text.strip()
    if not stripped:
        return ""
    key = _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", stripped.lower())).strip()
    # Punctuation-only text normalises to nothing. Falling back to the literal
    # keeps such claims from all colliding on a single empty key.
    return key or stripped


class ClaimDeduplicator:
    """Remembers which claims a session has already processed.

    Stateless across sessions and safe to share: every mutation is confined to
    the dictionary entry for the session it was called with.
    """

    name = "claim-deduplicator"

    def __init__(self, max_tracked_claims: int = DEFAULT_MAX_TRACKED_CLAIMS) -> None:
        self.max_tracked_claims = max_tracked_claims
        self._seen: Dict[str, Set[str]] = {}
        self._order: Dict[str, List[str]] = {}

    def seen_keys(self, session_id: str) -> Set[str]:
        """Return the claim keys already processed for ``session_id``."""
        return self._seen.setdefault(session_id, set())

    def is_duplicate(self, session_id: str, claim_text: str) -> bool:
        """Return True when this exact claim was already processed.

        This method does not record anything. Use :meth:`filter_duplicates`
        when the decision and the bookkeeping have to happen together, so a
        claim cannot slip through between a check and a record.
        """
        key = normalize_claim_text(claim_text)
        if not key:
            return False
        return key in self.seen_keys(session_id)

    def remember(self, session_id: str, claim_text: str) -> str:
        """Record ``claim_text`` for ``session_id`` and return its key."""
        key = normalize_claim_text(claim_text)
        if not key:
            return ""

        seen = self.seen_keys(session_id)
        if key not in seen:
            seen.add(key)
            order = self._order.setdefault(session_id, [])
            order.append(key)
            self._evict(session_id)
        return key

    def accept(self, session_id: str, claim_text: str) -> bool:
        """Return True when the claim is new, recording it either way.

        The check and the record happen together so two concurrent claims
        cannot both pass the check and both be processed.
        """
        key = normalize_claim_text(claim_text)
        if not key:
            # Nothing to compare, so nothing to suppress.
            return True
        seen = self.seen_keys(session_id)
        if key in seen:
            return False
        seen.add(key)
        order = self._order.setdefault(session_id, [])
        order.append(key)
        self._evict(session_id)
        return True

    def filter_duplicates(
        self, session_id: str, claim_texts: List[str]
    ) -> List[str]:
        """Return only the texts not already processed, preserving order.

        Repeats *within* the supplied batch are collapsed too, so one gateway
        response restating a claim twice yields it once.
        """
        kept: List[str] = []
        for text in claim_texts:
            if self.accept(session_id, text):
                kept.append(text)
        return kept

    def clear(self, session_id: Optional[str] = None) -> None:
        """Forget one session's claims, or every session's when omitted."""
        if session_id is None:
            self._seen.clear()
            self._order.clear()
        else:
            self._seen.pop(session_id, None)
            self._order.pop(session_id, None)

    def _evict(self, session_id: str) -> None:
        """Drop the oldest keys once a session exceeds its cap."""
        order = self._order.get(session_id)
        if not order:
            return
        seen = self._seen.get(session_id)
        overflow = len(order) - self.max_tracked_claims
        if overflow <= 0:
            return
        for key in order[:overflow]:
            if seen is not None:
                seen.discard(key)
        del order[:overflow]
