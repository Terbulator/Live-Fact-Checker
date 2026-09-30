"""Detection of compound claims -- sentences carrying several assertions.

P1 feature. A single extracted claim can assert more than one thing::

    "India won the 2011 World Cup and Sachin Tendulkar scored 482 runs."

becomes

    * "India won the 2011 World Cup."
    * "Sachin Tendulkar scored 482 runs."

Each part then enters the **existing** verification pipeline independently, so a
claim that is half right and half wrong is no longer forced into a single
verdict.

Design constraints, all deliberate:

* **A splitter is a splitter, not a rewriter.** It never edits words, never
  corrects grammar, and never merges. It either returns the original text
  unchanged, or returns the pieces it cut from it. Single claims are the common
  case and must come out byte-identical.
* **Conservative by construction.** Every segment produced by a split has to
  look like an independent clause on its own. If *any* segment fails that test
  the whole sentence is left alone, because a wrong split loses a claim and a
 * missed split merely under-segments.
* **No dependency on a parser or a model.** Lightweight, deterministic rules,
  consistent with :mod:`verification.classification`.
"""

from typing import List, Optional, Sequence, Tuple
import re


#: Coordinating connectors that can join two independent clauses. Matched on
#: word boundaries, longest first so "as well as" wins over "as".
_CONNECTORS: Tuple[str, ...] = (
    "as well as",
    "along with",
    "together with",
    "in addition to",
    "and also",
    "however",
    "whereas",
    "although",
    "and",
    "but",
    "while",
    "plus",
)

#: Finite verb forms. Covers the copula, the auxiliaries, the modals and the
#: irregular past forms that no ``-ed`` rule can reach. This is a recognition
#: list, not a dictionary: an unknown verb simply makes a segment look less
#: clause-like, which biases towards not splitting.
_VERB_FORMS = frozenset(
    {
        # copula + auxiliaries
        "is", "are", "was", "were", "am", "be", "been", "being",
        "has", "have", "had", "does", "did", "done",
        # modals
        "will", "would", "can", "could", "shall", "should", "may", "might",
        "must",
        # irregular past / participle forms
        "won", "wrote", "written", "made", "made", "said", "took", "taken",
        "gave", "given", "found", "told", "became", "left", "felt", "brought",
        "began", "begun", "kept", "held", "met", "sent", "built", "ran",
        "run", "saw", "seen", "came", "come", "went", "gone", "knew",
        "known", "thought", "spoke", "spoken", "drove", "driven", "broke",
        "broken", "chose", "chosen", "ate", "eaten", "fell", "fallen",
        "grew", "grown", "sold", "launched", "founded", "released",
        "invented", "discovered", "developed", "published", "designed",
        "scored", "played", "won", "beat", "defeated", "won",
        "happened", "occurred", "began", "ended", "finished", "won",
        "set", "put", "cut", "read", "said", "told", "sold", "sent",
        "bought", "brought", "caught", "taught", "thought", "sought",
        "led", "fed", "spun", "won", "born", "drawn", "shown", "known",
        "written", "spoken", "broken", "chosen", "driven", "eaten",
        "fallen", "given", "taken", "seen", "gone", "grown", "hidden",
    }
)

#: Tokens that mark a negation or an elided verb, meaning the text after a
#: connector continues the *same* clause rather than starting a new one:
#: "the company reported a profit and missed forecasts" is one compound
#: predicate about one company, not two independent claims.
_NEGATION_OR_ELISION = frozenset(
    {"not", "never", "no", "nt", "cannot", "wont", "didnt", "doesnt",
     "isnt", "wasnt", "hasnt", "havent", "couldnt", "wouldnt", "shouldnt"}
)

_SUBJECT_PRONOUNS = frozenset(
    {"it", "he", "she", "they", "we", "i", "you", "this", "that", "there"}
)

#: Endings that mean an "-s" token is not a third-person verb.
_NOT_A_VERB_SUFFIX = ("ss", "us", "is", "as", "os")

_WHITESPACE = re.compile(r"\s+", re.UNICODE)
_TOKEN = re.compile(r"[\w']+", re.UNICODE)

#: Split points are sentence-final punctuation followed by a new capitalised
#: sentence. Used only when every resulting piece is independently clausal.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

#: A period preceded by a single capital letter, or by a known abbreviation, is
#: an initialism or a title, not a sentence end: "the U.S. won the match."
_ABBREVIATION_TAIL = re.compile(r"(?:\b[A-Z]|\b(?:Dr|Mr|Mrs|Ms|Prof|St|Jr|Sr|vs|etc|Inc|Ltd|Co|approx|No|Vol|Fig)\.)$")

#: Shortest piece worth treating as its own claim. Below this, a "clause" is a
#: fragment and splitting would be guessing.
_MIN_CLAUSE_TOKENS = 3

#: Never emit more than this many claims from one sentence. A sentence with
#: many clauses is a list, and splitting it further helps nobody.
_MAX_CLAIMS_PER_SENTENCE = 4


def _normalise_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _tokens(text: str) -> List[str]:
    return _TOKEN.findall(text.lower())


def _is_participle(token: str) -> bool:
    """True for a past participle, i.e. an elided verb after a connector."""
    if token in _NEGATION_OR_ELISION:
        return True
    if len(token) >= 5 and token.endswith("ed"):
        return True
    return token in {
        "won", "made", "said", "told", "taken", "given", "seen", "known",
        "written", "shown", "done", "gone", "held", "kept", "built",
        "sent", "brought", "bought", "caught", "taught", "found",
        "led", "fed", "run", "set", "put", "cut", "read", "born", "drawn",
    }


def _looks_like_clause(text: str, min_tokens: int = _MIN_CLAUSE_TOKENS) -> bool:
    """Return True when ``text`` can stand alone as a checkable assertion.

    The bar is deliberately mechanical: enough words, and at least one token
    that is recognisably a finite verb. Anything else is treated as a fragment
    of the surrounding sentence.
    """
    normalised = _normalise_whitespace(text)
    if not normalised:
        return False
    tokens = _tokens(normalised)
    if len(tokens) < min_tokens:
        return False
    for token in tokens:
        if token in _VERB_FORMS:
            return True
        if len(token) >= 5 and token.endswith("ed"):
            return True
    # Last resort: an explicit subject followed by a third-person verb
    # ("it employs 400 people"). Restricted to a known subject pronoun so a
    # plural noun is never mistaken for one.
    if tokens[0] in _SUBJECT_PRONOUNS and len(tokens) >= 4:
        for token in tokens[1:]:
            if (
                len(token) >= 4
                and token.endswith("s")
                and not token.endswith(_NOT_A_VERB_SUFFIX)
            ):
                return True
    return False


def _split_on_connectors(text: str) -> Optional[List[str]]:
    """Split on coordinating connectors, or return ``None`` if unsafe.

    ``None`` means "this sentence is not a compound claim on this connector",
    which is different from "this sentence has one clause".
    """
    lowered = text.lower()

    segments: List[str] = []
    cursor = 0
    for connector in _CONNECTORS:
        pattern = re.compile(r"\b" + re.escape(connector) + r"\b", re.UNICODE)
        search_from = cursor
        while True:
            match = pattern.search(lowered, search_from)
            if match is None:
                break
            before = text[cursor:match.start()].strip()
            after = text[match.end():].strip()
            # A connector with nothing usable on one side is not a join.
            if before and after and not _starts_with_participle(_tokens(after)):
                if not segments:
                    segments = [before, after]
                else:
                    # `before` closes the piece opened just before this match;
                    # the pieces already collected are untouched.
                    segments[-1] = before
                    segments.append(after)
                cursor = match.end()
                search_from = cursor
            else:
                search_from = match.end()
    return segments or None


def _starts_with_participle(tokens: Sequence[str]) -> bool:
    return bool(tokens) and _is_participle(tokens[0])


def _sentence_segments(text: str) -> Optional[List[str]]:
    """Split on sentence boundaries, or return ``None`` if unsafe."""
    boundaries: List[int] = []
    for match in _SENTENCE_BOUNDARY.finditer(text):
        left = text[: match.start() + 1]
        # "U.S." and "Dr." end in a period that is not a sentence end.
        if _ABBREVIATION_TAIL.search(left):
            continue
        boundaries.append(match.end())
    if not boundaries:
        return None

    segments: List[str] = []
    cursor = 0
    for end in boundaries:
        segment = text[cursor:end].strip()
        if segment:
            segments.append(segment)
        cursor = end
    tail = text[cursor:].strip()
    if tail:
        segments.append(tail)
    return segments or None


_TRAILING_JUNK = re.compile(r"[\s,;:\-–—]+$", re.UNICODE)


def _restore_terminal_punctuation(text: str) -> str:
    """Turn a cut fragment into the standalone statement it now is.

    Only two things change: punctuation left dangling at the cut is dropped and
    replaced by a full stop, and the piece is capitalised so it reads as a
    sentence in its own right. No word is added, removed or reordered.
    """
    stripped = _TRAILING_JUNK.sub("", _normalise_whitespace(text))
    if not stripped:
        return stripped
    if not stripped[-1] in ".!?":
        stripped += "."
    # Capitalise the first letter. Done on the raw text so an initialism such
    # as "e.g." is untouched by the check that follows.
    for index, character in enumerate(stripped):
        if character.isalpha():
            if character.islower():
                stripped = stripped[:index] + character.upper() + stripped[index + 1:]
            break
    return stripped


class CompoundClaimSplitter:
    """Splits sentences that assert several independent things."""

    name = "compound-claim-splitter"

    def __init__(
        self,
        max_claims: int = _MAX_CLAIMS_PER_SENTENCE,
        min_clause_tokens: int = _MIN_CLAUSE_TOKENS,
    ) -> None:
        self.max_claims = max_claims
        self.min_clause_tokens = min_clause_tokens

    def split(self, text: str) -> List[str]:
        """Return the independent claims contained in ``text``.

        Args:
            text: One extracted claim.

        Returns:
            A list of claim strings. ``[text]`` -- the original, unmodified --
            whenever the sentence makes at most one assertion, which is the
            overwhelmingly common case.
        """
        if not isinstance(text, str):
            return []
        original = _normalise_whitespace(text)
        if not original:
            return []

        segments = self._candidate_segments(original)
        if not segments or len(segments) < 2:
            return [text]

        # Every piece must stand alone. One fragment means the split was wrong.
        if not all(self._is_clause(segment) for segment in segments):
            return [text]

        if len(segments) > self.max_claims:
            return [text]

        pieces = [_restore_terminal_punctuation(segment) for segment in segments]
        # A split that produced nothing new is not a split.
        if len(pieces) < 2 or any(not piece for piece in pieces):
            return [text]
        return pieces

    def split_many(self, texts: Sequence[str]) -> List[str]:
        """Split several claims, preserving order and flattening the result."""
        result: List[str] = []
        for text in texts:
            result.extend(self.split(text))
        return result

    def _candidate_segments(self, text: str) -> Optional[List[str]]:
        """Prefer a connector split; fall back to a sentence split."""
        by_connector = _split_on_connectors(text)
        if by_connector and len(by_connector) >= 2:
            return by_connector
        return _sentence_segments(text)

    def _is_clause(self, segment: str) -> bool:
        return _looks_like_clause(segment, self.min_clause_tokens)


#: Shared instance. The splitter holds no mutable state.
DEFAULT_SPLITTER = CompoundClaimSplitter()


def split_compound_claim(text: str) -> List[str]:
    """Split one claim with the shared :class:`CompoundClaimSplitter`."""
    return DEFAULT_SPLITTER.split(text)


def is_compound_claim(text: str) -> bool:
    """Return True when ``text`` asserts more than one thing."""
    return len(split_compound_claim(text)) > 1
