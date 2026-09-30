"""Deterministic ranking of retrieved evidence into a source list.

The retriever already returns several :class:`~verification.models.EvidenceItem`
objects per claim, but the pipeline only ever surfaced the first usable one. This
module turns that same evidence into an ordered, de-duplicated list of citable
sources so the UI can show more than a single citation.

Design constraints, all of which are deliberate:

* **Nothing is invented.** Only URLs the provider actually returned are used.
  An item with no URL is dropped, exactly as ``parse_search_results`` already
  drops one, because a placeholder would put a fabricated citation in front of
  a judge.
* **The first search result is not automatically authoritative.** Ranking is by
  the signals the retrieval abstraction already exposes -- provider confidence,
  stance, and whether the record carries a usable title and snippet.
* **No hardcoded allowlist of "trusted" domains.** Such a list rots the moment a
  credible outlet is added and silently downranks the one that matters. Domain
  shape and record quality are the only domain-level signal used.
* **Deterministic.** The same evidence always produces the same order, with ties
  broken by original provider order, so two clients never disagree.
"""

from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

from verification.models import EvidenceItem

#: Most sources shown on a card. Enough to show corroboration without turning a
#: claim card into a search-results page.
MAX_SOURCES = 5

#: Longest snippet carried on the wire. Retrieval returns paragraphs; a card
#: shows a sentence, and the full text stays one click away on the source page.
MAX_SNIPPET_CHARS = 280

#: Stance contributions. Evidence that actively bears on the claim outranks
#: evidence that is merely adjacent to it. ``conflicting`` is ranked below
#: ``neutral`` because the checker will still report UNVERIFIABLE on conflict --
#: the citation is still worth showing, just not as the lead one.
_STANCE_WEIGHT: Dict[str, float] = {
    "supports": 0.30,
    "refutes": 0.30,
    "neutral": 0.10,
    "conflicting": 0.05,
}

#: Confidence is already a 0..1 relevance signal, so it dominates the sum while
#: the per-source bonuses only reorder otherwise-similar results.
_CONFIDENCE_WEIGHT = 1.0

#: Small bonuses for a record that is actually citable and readable.
_TITLE_BONUS = 0.05
_SNIPPET_BONUS = 0.05


def _host_of(url: str) -> str:
    """Return the lowercased host of ``url``, or '' when it has none."""
    try:
        host = urlsplit(url).netloc
    except ValueError:
        return ""
    host = host.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def dedupe_key(url: str) -> str:
    """Return a stable identity for a citation.

    Two records pointing at the same page are the same source and must not be
    listed twice, however differently the provider formatted or scored them.
    """
    host = _host_of(url)
    path = urlsplit(url).path.rstrip("/") if host else url.strip().lower()
    return f"{host}{path}"


def _truncate(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    """Collapse whitespace and cut ``text`` to ``limit`` on a word boundary."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[:limit]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut + "…"


def _score(item: EvidenceItem) -> float:
    """Return this item's deterministic ranking score."""
    score = item.confidence * _CONFIDENCE_WEIGHT
    if item.stance is not None:
        score += _STANCE_WEIGHT.get(item.stance, 0.0)
    if item.title and item.title.strip():
        score += _TITLE_BONUS
    if item.snippet and item.snippet.strip():
        score += _SNIPPET_BONUS
    # A URL with no host cannot be verified by a reader, so it is weaker
    # evidence than a fully-qualified one even if the provider scored it high.
    if not _host_of(item.source_url):
        score -= 0.25
    return score


def to_source_dict(item: EvidenceItem) -> Dict[str, Any]:
    """Convert one :class:`EvidenceItem` into its wire shape."""
    return {
        "url": item.source_url,
        "title": item.title if item.title and item.title.strip() else None,
        "snippet": _truncate(item.snippet) if item.snippet else None,
    }


def rank_sources(
    evidence: Optional[Sequence[EvidenceItem]],
    limit: int = MAX_SOURCES,
) -> List[Dict[str, Any]]:
    """Return the citable sources for one claim, best first.

    Args:
        evidence: Items returned by the retriever, in provider order.
        limit: Maximum number of sources to return.

    Returns:
        A list of ``{"url", "title", "snippet"}`` dicts. Empty when nothing is
        citable, which the caller must treat as "no evidence", never as a
        verdict input.
    """
    if not evidence or limit <= 0:
        return []

    candidates: List[tuple] = []

    for position, item in enumerate(evidence):
        if not isinstance(item, EvidenceItem):
            continue
        url = (item.source_url or "").strip()
        snippet = (item.snippet or "").strip()
        # No URL means nothing to cite; no snippet means nothing to compare.
        if not url or not snippet:
            continue
        candidates.append((_score(item), position, item))

    # Sort by score, then by provider order. Python's sort is stable, so the
    # position tie-break makes the result total and reproducible.
    candidates.sort(key=lambda entry: (-entry[0], entry[1]))

    # De-duplicate *after* ranking, so when the same page is returned twice the
    # better-attested record is the one that survives rather than whichever the
    # provider happened to emit first.
    seen: set = set()
    sources: List[Dict[str, Any]] = []
    for _, _, item in candidates:
        key = dedupe_key(item.source_url)
        if key in seen:
            continue
        seen.add(key)
        sources.append(to_source_dict(item))
        if len(sources) >= limit:
            break
    return sources


def primary_source(
    sources: Sequence[Dict[str, Any]], fallback: str
) -> str:
    """Return the single citation for the existing ``source`` field.

    The contract still carries one primary URL, and it is now the top *ranked*
    source rather than whatever the provider happened to return first. The
    checker's own value is kept as a fallback so a claim with no citable
    evidence still reports exactly what it reported before.
    """
    for candidate in sources:
        url = candidate.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return fallback
