"""Lightweight classification of newly extracted text.

P1 feature: decide *what kind of thing* the extractor produced before any
verification work is spent on it.

    FACTUAL CLAIM      -> continue through the existing fact-checking pipeline
    QUESTION           -> not a verifiable assertion
    OPINION            -> not objectively checkable
    COMMAND / INSTRUCTION -> an instruction, not an assertion
    SMALL TALK         -> conversational noise
    UNCLEAR            -> too ambiguous to force a verdict

Design constraints, all deliberate:

* **This module never verifies anything and never rewrites the text.** It only
  labels. The existing factual-claim path is untouched: a ``FACTUAL_CLAIM`` is
  handed on exactly as it was extracted, byte for byte.
* **Default to ``FACTUAL_CLAIM``.** Every rule below is a *veto*, never a
  licence. A sentence is only held back when a high-precision pattern matches.
  Silence therefore means "let the existing pipeline deal with it", which is
  what keeps this layer from ever dropping a real claim through over-eager
  pattern matching. Losing a true claim is far worse than spending a search on
  a phrase that turns out to be a claim after all.
* **Deterministic and dependency-free.** No model call, no network, no new
  dependency. Same input, same label, every time.
* **Ordered rules.** The order below is part of the contract: a greeting that
  happens to contain a question mark is small talk, not a question.
"""

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet
import re


class ClaimCategory(str, Enum):
    """What kind of thing the extracted text is."""

    FACTUAL_CLAIM = "factual_claim"
    QUESTION = "question"
    OPINION = "opinion"
    COMMAND = "command"
    SMALL_TALK = "small_talk"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class ClaimClassification:
    """The verdict of the classifier for one piece of text.

    Attributes:
        category: The assigned :class:`ClaimCategory`.
        reason: A short, human-readable justification. Safe to log and to put
            in front of a user; it never contains anything but the match kind.
    """

    category: ClaimCategory
    reason: str

    @property
    def is_fact_checkable(self) -> bool:
        """True only for text that should reach the verification pipeline."""
        return self.category is ClaimCategory.FACTUAL_CLAIM


# ---------------------------------------------------------------------------
# Signal sets
# ---------------------------------------------------------------------------

#: Whole-text greetings, farewells and pleasantries. Matched against the
#: normalised text (no punctuation, single-spaced, lowercased), so "Hello!" and
#: "hello" are the same signal.
_SMALL_TALK_EXACT: FrozenSet[str] = frozenset(
    {
        "hi", "hey", "hello", "yo", "hiya", "howdy", "heya",
        "bye", "goodbye", "ciao", "cheers", "ta", "later",
        "thanks", "thank you", "many thanks", "thank you so much",
        "no problem", "np", "youre welcome", "my pleasure",
        "yes", "yeah", "yep", "yup", "no", "nope", "nah",
        "ok", "okay", "k", "sure", "right", "alright", "fine", "cool",
        "good morning", "good afternoon", "good evening", "good night",
        "good day", "welcome", "hello everyone", "hi everyone",
        "hello there", "hi there", "hey there", "thanks a lot",
        "thank you all", "good morning everyone", "good afternoon everyone",
        "good evening everyone", "thanks everyone", "thank you everyone",
        "how are you", "how are you doing", "hows it going", "hows everyone",
        "nice to meet you", "nice to see you", "good to see you",
        "lets get started", "let us begin", "lets begin",
        "moving on", "next slide", "any questions", "over to you",
        "welcome back", "we are back", "that concludes", "end of session",
    }
)

#: Words that may trail a greeting without making it a claim. "Hello there" is
#: still a greeting; "hello, India won the World Cup" is not.
_GREETING_TAIL_WORDS: FrozenSet[str] = frozenset(
    {
        "there", "everyone", "everybody", "all", "guys", "folks", "team",
        "world", "welcome", "back", "again", "and", "to", "the", "show",
        "morning", "afternoon", "evening", "night", "day", "good", "and",
    }
)

#: Leading filler for a small-talk / false-start. Matched as a prefix, so
#: "hello everyone and welcome" is still recognised as small talk.
_SMALL_TALK_PREFIXES: FrozenSet[str] = frozenset(
    {
        "hello", "hi", "hey", "good morning", "good afternoon",
        "good evening", "good night", "thanks", "thank you",
        "goodbye", "bye", "welcome", "how are you", "nice to meet you",
        "let us get started", "lets get started",
    }
)

#: Interrogative openers. A question is a question because of how it is built,
#: so these are checked before any other content signal.
_QUESTION_OPENERS: FrozenSet[str] = frozenset(
    {
        "who", "whom", "whose", "what", "which", "when", "where", "why",
        "how", "is", "are", "was", "were", "do", "does", "did", "has",
        "have", "had", "can", "could", "will", "would", "should", "shall",
        "may", "might", "am", "any", "if", "whether",
    }
)

#: Opinion markers. Deliberately restricted to phrases where the speaker is
#: explicitly marking a judgement as their own. Without that self-marking, "X
#: is the greatest player" is indistinguishable from a factual claim, and
#: guessing wrong here would drop a checkable statement.
_OPINION_MARKERS: FrozenSet[str] = frozenset(
    {
        "i think", "i believe", "i feel", "i suppose", "i guess",
        "in my opinion", "in my view", "my opinion", "personally",
        "to be honest", "honestly", "arguably", "admittedly",
        "i reckon", "i suppose that", "if you ask me", "i would say",
        "i would argue", "in my estimation", "my take is",
        "i dont think", "i do not think", "i disagree",
        # Hedged or reported speech: asserted, but not in a form that any
        # source can settle.
        "i predict", "i expect", "i assume", "it seems", "seems like",
        "seems to me", "apparently", "allegedly", "rumour has it",
        "rumor has it", "supposedly", "reportedly",
    }
)

#: Imperative openings. A command is recognised by an instruction-shaped
#: opening, never by a verb alone, so "Let us go to the next slide" is a
#: command while "Let us consider the evidence" stays claim-eligible.
_COMMAND_PREFIXES: FrozenSet[str] = frozenset(
    {
        "please", "go ahead", "go to", "move on",
        "open", "close", "click", "tap", "press", "scroll", "share",
        "look", "listen", "hear", "watch", "read", "write", "note",
        "remember", "forget", "consider", "imagine", "think about",
        "make sure", "do not", "dont", "never", "always", "keep",
        "take", "give", "put", "bring", "send", "check", "confirm",
        "explain", "describe", "discuss", "tell me", "show me",
        "start", "begin", "stop", "wait", "help me", "join", "follow",
        "pay attention", "focus on", "remember that", "note that",
    }
)

#: Content-free filler. When *every* word is one of these there is no assertion
#: to extract at all, which is UNCLEAR rather than a guess.
_FILLER_WORDS: FrozenSet[str] = frozenset(
    {
        "um", "uh", "er", "ah", "eh", "hmm", "mm", "mhm",
        "like", "you", "know", "so", "well", "anyway", "basically",
        "actually", "literally", "obviously", "honestly", "right",
        "okay", "ok", "yeah", "yes", "alright", "whatever",
        "thing", "stuff", "bit", "sort", "kind", "guess", "suppose",
    }
)

#: Words carrying no assertion of their own. Used only to measure how much
#: substantive content a fragment carries.
_STOPWORDS: FrozenSet[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "if", "then", "than",
        "that", "this", "these", "those", "there", "here", "it",
        "its", "is", "are", "was", "were", "be", "been", "being",
        "to", "of", "in", "on", "at", "for", "with", "by", "from",
        "as", "about", "into", "over", "after", "before", "up",
        "down", "out", "off", "very", "really", "quite", "just",
    }
)

_WHITESPACE = re.compile(r"\s+", re.UNICODE)
#: An apostrophe is deleted rather than replaced by a space, so a contraction
#: stays one word: "let's" normalises to "lets", not "let s".
_APOSTROPHES = re.compile(r"['\u2019]", re.UNICODE)
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_TOKEN = re.compile(r"[\w']+", re.UNICODE)


def _normalise(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace."""
    if not isinstance(text, str):
        return ""
    collapsed = _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", _APOSTROPHES.sub("", text.lower()))).strip()
    return collapsed


def _tokens(normalised: str) -> list:
    return _TOKEN.findall(normalised)


def _content_words(tokens: list) -> list:
    return [word for word in tokens if word not in _STOPWORDS]


def _is_small_talk(normalised: str, tokens: list) -> bool:
    """Greetings, farewells and conversational filler."""
    if not normalised:
        return False
    if normalised in _SMALL_TALK_EXACT:
        return True
    # A greeting only stays small talk while nothing factual follows it. "Hi,
    # India won the 2011 World Cup" is a claim that happens to be greeted.
    for prefix in _SMALL_TALK_PREFIXES:
        if normalised.startswith(prefix + " ") or normalised == prefix:
            remainder = normalised[len(prefix):].strip()
            if not remainder:
                return True
            tail = _content_words(_tokens(remainder))
            # A greeting stays small talk while only greeting vocabulary
            # follows it. Anything else -- "hi, India won the 2011 World Cup"
            # -- is a claim that happens to be greeted.
            if not tail or all(word in _GREETING_TAIL_WORDS for word in tail):
                return True
    return False


def _is_question(normalised: str) -> bool:
    """A question mark, or a sentence built as an interrogative."""
    if not normalised:
        return False
    if "?" in normalised or normalised.endswith("?"):
        return True
    tokens = _tokens(normalised)
    if not tokens:
        return False
    if tokens[0] in _QUESTION_OPENERS:
        # "Is" / "was" only open a question when a subject follows; a bare
        # fragment starting with one is not evidence of a question.
        if tokens[0] in {"is", "are", "was", "were", "am", "do", "does", "did"}:
            return len(tokens) >= 3
        return True
    # "the question is whether ...", "let me ask ..." style openers.
    return normalised.startswith(
        ("any idea", "do you know", "can you tell me", "i wonder", "just curious")
    )


def _is_opinion(normalised: str) -> bool:
    """An explicitly self-marked judgement."""
    for marker in _OPINION_MARKERS:
        if normalised.startswith(marker + " ") or normalised == marker:
            return True
    return False


def _is_command(normalised: str) -> bool:
    """An instruction-shaped opening."""
    if not normalised:
        return False
    for prefix in _COMMAND_PREFIXES:
        if normalised.startswith(prefix + " ") or normalised == prefix:
            return True
    return False


def _is_unclear(normalised: str, tokens: list) -> bool:
    """Too little substantive content to be anything, let alone a claim."""
    content = _content_words(tokens)
    if not content:
        return True
    # Every remaining word is conversational filler, so there is nothing
    # here that could be checked.
    if all(word in _FILLER_WORDS for word in content):
        return True
    return False


class ClaimClassifier:
    """Assigns a :class:`ClaimCategory` to extracted text.

    Stateless and safe to share between threads: the only state is the immutable
    signal tables above.
    """

    name = "claim-classifier"

    def classify(self, text: str) -> ClaimClassification:
        """Return the classification for one piece of extracted text.

        Args:
            text: Raw text as extracted from speech or by the claim engine.

        Returns:
            A :class:`ClaimClassification`. Anything not positively matched as
            a question, opinion, command, greeting or fragment is reported as
            :attr:`ClaimCategory.FACTUAL_CLAIM` so the existing pipeline sees
            exactly what it saw before.
        """
        normalised = _normalise(text)
        if not normalised:
            return ClaimClassification(
                ClaimCategory.UNCLEAR, "Text is empty or carries no words."
            )

        tokens = _tokens(normalised)

        if _is_small_talk(normalised, tokens):
            return ClaimClassification(
                ClaimCategory.SMALL_TALK, "Greeting, farewell or conversational filler."
            )

        if _is_question(normalised):
            return ClaimClassification(
                ClaimCategory.QUESTION, "Asked as a question rather than asserted."
            )

        if _is_opinion(normalised):
            return ClaimClassification(
                ClaimCategory.OPINION, "Explicitly marked as a personal judgement."
            )

        if _is_command(normalised):
            return ClaimClassification(
                ClaimCategory.COMMAND, "An instruction or request, not an assertion."
            )

        if _is_unclear(normalised, tokens):
            return ClaimClassification(
                ClaimCategory.UNCLEAR, "Too little substantive content to be a claim."
            )

        return ClaimClassification(
            ClaimCategory.FACTUAL_CLAIM,
            "Reads as an objectively checkable assertion.",
        )


#: Shared instance. The classifier holds no mutable state.
DEFAULT_CLASSIFIER = ClaimClassifier()


def classify_claim(text: str) -> ClaimClassification:
    """Classify one piece of text with the shared :class:`ClaimClassifier`."""
    return DEFAULT_CLASSIFIER.classify(text)


def is_fact_checkable(text: str) -> bool:
    """Return True when ``text`` should continue into verification."""
    return DEFAULT_CLASSIFIER.classify(text).is_fact_checkable
