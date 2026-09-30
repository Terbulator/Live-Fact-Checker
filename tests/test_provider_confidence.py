"""Provider confidence is passed through, or it is absent. Never invented.

The rule this module enforces, end to end:

    provider gave 0.73  ->  0.73
    provider gave none   ->  null
    provider gave junk   ->  null

There is no fallback, no clamp, no default and no fitted constant anywhere on
the path, because a number this system cannot source is a number it invented.
Three separate places are covered, since each had its own version of the same
mistake:

* the Tavily search response (:mod:`verification.retriever`)
* the AssemblyAI transcript (:mod:`backend.ingestion.audio`)
* the value published on the wire (:mod:`backend.adapters.verification`)
"""

import math

import pytest

from backend.adapters.verification import (
    VerificationServiceEngine,
    to_wire_sources,
    verdict_confidence,
)
from backend.ingestion.audio import _provider_confidence, transcribe_audio_file
from backend.persistence.store import CachedVerification
from backend.schemas import ClaimEvent
from verification.models import EvidenceItem
from verification.retriever import (
    RetrieverConfigurationError,
    RetrieverError,
    WebSearchRetriever,
    create_default_retriever,
)
from verification.search_providers import SearchProviderError
from verification.service import VerificationService
from verification.sources import _score, rank_sources, to_source_dict

#: The invented values this project must never emit. Asserted against directly
#: so a reintroduced default fails here rather than in front of a judge.
FORBIDDEN_FALLBACKS = (0.6, 0.8, 0.9, 1.0)


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _Recorder:
    """A Tavily transport that returns a canned payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        if isinstance(self.payload, Exception):
            raise self.payload
        return _Response(self.payload)

class _Response:
    """A ``SearchResponse`` the injected transport hands back.

    Built as the real dataclass rather than a stand-in, because the provider
    checks the type before it will trust the payload.
    """

    def __new__(cls, payload, status_code=200, headers=None):
        from verification.search_providers import SearchResponse

        return SearchResponse(
            status_code=status_code, headers=dict(headers or {}), payload=payload
        )


def _retriever(payload) -> WebSearchRetriever:
    """A real ``WebSearchRetriever`` over a stubbed Tavily transport.

    The provider is genuinely constructed so the request/response conversion is
    exercised; only the HTTP call is replaced. ``payload`` is a Tavily response
    body, or an exception for the transport to raise.
    """
    from verification.search_providers import TavilyProvider

    transport = _Recorder(payload)
    return WebSearchRetriever(
        api_key="test-key",
        provider_client=TavilyProvider("test-key", transport=transport),
    )


def _tavily_result(score=0.73, url="https://reuters.com/world/report", content="A real snippet."):
    record = {"title": "T", "url": url, "content": content}
    if score is not ...:
        record["score"] = score
    return record


def _claim(text="India won the 2011 Cricket World Cup.") -> ClaimEvent:
    return ClaimEvent(
        type="claim",
        claimId="c1",
        sessionId="s1",
        speaker="Speaker 1",
        claim=text,
        timestamp=1.0,
    )


# ---------------------------------------------------------------------------
# G. A real provider score is preserved exactly
# ---------------------------------------------------------------------------


def test_tavily_score_reaches_the_evidence_item_unchanged() -> None:
    """0.73 in the response is 0.73 in the model, to the last digit."""
    item = WebSearchRetriever.parse_search_results([_tavily_result(score=0.73)])[0]

    assert item.confidence == 0.73
    assert item.confidence not in FORBIDDEN_FALLBACKS


@pytest.mark.parametrize("score", [0.73, 0.05, 0.0, 0.999, 1.0])
def test_real_scores_survive_a_full_retrieval(score) -> None:
    """The whole conversion path, for scores across the range."""
    retriever = _retriever({"results": [_tavily_result(score=score)]})

    items = retriever.retrieve("india 2011 world cup")

    assert len(items) == 1
    assert items[0].confidence == pytest.approx(score)


def test_both_provider_spellings_are_read() -> None:
    """Tavily sends ``score``; some providers send ``confidence``."""
    with_score = WebSearchRetriever.parse_search_results(
        [{"snippet": "s", "url": "https://a.example.com", "score": 0.42}]
    )[0]
    with_confidence = WebSearchRetriever.parse_search_results(
        [{"snippet": "s", "url": "https://a.example.com", "confidence": 0.42}]
    )[0]

    assert with_score.confidence == 0.42
    assert with_confidence.confidence == 0.42


# ---------------------------------------------------------------------------
# G. A missing or unusable score is null, never defaulted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score", [None, ..., "0.73", "high", True, False, [], {}, [0.7], math.nan, math.inf, -math.inf, 1.4, -0.2]
)
def test_missing_or_unusable_scores_become_none(score) -> None:
    """Nothing is coerced into a number and nothing is filled in."""
    record = {"title": "T", "url": "https://a.example.com", "content": "s"}
    if score is not ...:
        record["score"] = score

    item = WebSearchRetriever.parse_search_results([record])[0]

    assert item.confidence is None
    assert item.confidence not in FORBIDDEN_FALLBACKS


def test_the_evidence_item_itself_defaults_to_none() -> None:
    """A hand-built item with no score states so, rather than claiming 1.0."""
    item = EvidenceItem(snippet="A real snippet.", source_url="https://a.example.com")

    assert item.confidence is None


def test_the_retriever_exposes_no_fallback_constant() -> None:
    """A removed constant must not be reintroduced under any name."""
    offenders = [
        name
        for name in dir(WebSearchRetriever)
        if "DEFAULT" in name and "CONFIDENCE" in name
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# The wire value
# ---------------------------------------------------------------------------


def test_wire_confidence_is_the_lead_source_score() -> None:
    """Top-level confidence means the lead ranked source's actual score.

    ``to_wire_sources`` preserves the order it is given, and in production that
    order is the ranked one, so the lead is the first entry.
    """
    wire = to_wire_sources(
        [
            {"url": "https://a.example.com/1", "confidence": 0.88},
            {"url": "https://b.example.com/2", "confidence": 0.41},
        ]
    )

    assert verdict_confidence(wire) == 0.88


@pytest.mark.parametrize(
    "raw", [None, "0.8", True, math.nan, math.inf, 2.0, -1.0, [0.5]]
)
def test_wire_confidence_drops_unusable_values(raw) -> None:
    """The adapter rejects rather than repairs: no clamping, no defaulting."""
    wire = to_wire_sources([{"url": "https://a.example.com/1", "confidence": raw}])

    assert wire[0]["confidence"] is None
    assert verdict_confidence(wire) is None


def test_wire_confidence_is_none_without_sources() -> None:
    assert verdict_confidence([]) is None


def test_ranking_score_is_never_published_as_confidence() -> None:
    """The internal ranking key is a made-up number and must stay private.

    ``_score`` deliberately blends provider relevance with stance and
    record-quality bonuses. It orders the source list; it is not a measurement,
    so no field on the wire may ever carry it.
    """
    item = _wire_item(confidence=0.9, stance="supports", title="A", snippet="s")
    ranking_key = _score(item)
    entry = to_source_dict(item)

    assert ranking_key != item.confidence
    assert entry["confidence"] == item.confidence
    assert entry["confidence"] != ranking_key


def _wire_item(confidence, url="https://a.example.com/1", stance=None, title=None, snippet="s"):
    return EvidenceItem(
        snippet=snippet,
        source_url=url,
        title=title,
        stance=stance,
        confidence=confidence,
    )


def test_unscored_sources_still_rank_and_still_cite() -> None:
    """A missing score must not remove the source or invent one to rank it."""
    items = [
        _wire_item(
            url="https://a.example.com/1",
            confidence=None,
            stance="supports",
            title="Real source",
        ),
        _wire_item(url="https://b.example.com/2", confidence=None),
    ]

    ranked = rank_sources(items)

    assert len(ranked) == 2
    assert all(entry["confidence"] is None for entry in ranked)
    # The supporting, titled source still leads purely on real signals.
    assert ranked[0]["url"] == items[0].source_url


# ---------------------------------------------------------------------------
# I. Cache replay
# ---------------------------------------------------------------------------


async def test_confidence_survives_a_cache_write_and_replay() -> None:
    """0.73 goes into the store and 0.73 comes back out."""
    from backend.adapters.verification import CachedVerificationEngine

    captured = {}

    class _Store:
        async def get_cached_verification(self, claim_key):
            return None

        async def put_cached_verification(self, **kwargs):
            captured.update(kwargs)

    inner = VerificationServiceEngine(
        service=VerificationService(
            retriever=type(
                "_R",
                (),
                {
                    "retrieve": lambda self, q, max_results=3: [
                        _wire_item(confidence=0.73, stance="supports", snippet="Evidence text.")
                    ]
                },
            )()
        )
    )

    event = await CachedVerificationEngine(inner, _Store()).verify(_claim())

    assert captured["confidence"] == 0.73

    class _ReplayingStore:
        async def get_cached_verification(self, claim_key):
            return CachedVerification(
                claim_key=claim_key,
                verdict=event.verdict,
                reason=event.reason,
                source=event.source,
                confidence=captured["confidence"],
                provider="tavily",
            )

    replayed = await CachedVerificationEngine(_NeverRun(), _ReplayingStore()).verify(_claim())

    assert replayed.confidence == 0.73
    assert replayed.fromCache is True


async def test_a_null_confidence_replays_as_null_not_as_one() -> None:
    """The cache must not upgrade "unmeasured" into "certain" on the way out."""
    from backend.adapters.verification import CachedVerificationEngine

    class _Store:
        async def get_cached_verification(self, claim_key):
            return CachedVerification(
                claim_key=claim_key,
                verdict=cached_verdict(),
                reason="No evidence.",
                source="No source available",
                confidence=None,
                provider="tavily",
            )

    event = await CachedVerificationEngine(_NeverRun(), _Store()).verify(_claim())

    assert event.confidence is None
    assert event.confidence not in FORBIDDEN_FALLBACKS


def cached_verdict():
    from backend.schemas import Verdict

    return Verdict.UNVERIFIABLE


class _NeverRun:
    """An engine that must not be reached on a cache hit."""

    name = "must-not-run"

    async def verify(self, claim):  # pragma: no cover - a hit must not call this
        raise AssertionError("a cache hit must not re-run retrieval")


# ---------------------------------------------------------------------------
# H. AssemblyAI transcript confidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        (0.94, 0.94),
        (0.0, 0.0),
        (1.0, 1.0),
        (None, None),
        (0, 0.0),
        (False, None),
        (True, None),
        ("0.94", None),
        (1.5, None),
        (-0.1, None),
        (math.nan, None),
        (math.inf, None),
    ],
)
def test_assemblyai_confidence_is_preserved_or_null(raw, expected) -> None:
    """The 1.0 fallback is gone: absent stays absent."""
    assert _provider_confidence(raw) == expected


async def test_transcript_segments_carry_the_provider_confidence(monkeypatch) -> None:
    """Segment-level scores come from AssemblyAI, with no substitution."""
    import backend.ingestion.audio as audio_module

    class _Utterance:
        speaker = "A"
        text = "India won the 2011 World Cup."
        start = 1000
        end = 4000
        confidence = 0.91

    class _Transcript:
        status = "ok"
        error = None
        text = "India won the 2011 World Cup."
        confidence = 0.88
        utterances = [_Utterance()]

    monkeypatch.setattr(audio_module.aai, "Transcriber", lambda config=None: _FakeTranscriber(_Transcript()))
    monkeypatch.setattr(audio_module.aai, "TranscriptStatus", _FakeStatus)

    result = await transcribe_audio_file("ignored.wav", "key")

    assert result["segments"][0]["confidence"] == 0.91


async def test_transcript_without_utterances_reports_null_not_one(monkeypatch) -> None:
    """The exact line that used to answer ``1.0`` for a missing score."""
    import backend.ingestion.audio as audio_module

    class _Transcript:
        status = "ok"
        error = None
        text = "Spoken words."
        confidence = None
        utterances = None

    monkeypatch.setattr(audio_module.aai, "Transcriber", lambda config=None: _FakeTranscriber(_Transcript()))
    monkeypatch.setattr(audio_module.aai, "TranscriptStatus", _FakeStatus)

    result = await transcribe_audio_file("ignored.wav", "key")

    assert result["segments"][0]["confidence"] is None
    assert result["segments"][0]["confidence"] != 1.0
    # The text itself is still the provider's, untouched.
    assert result["segments"][0]["text"] == "Spoken words."


class _FakeTranscriber:
    def __init__(self, transcript):
        self._transcript = transcript

    def transcribe(self, path):
        return self._transcript


class _FakeStatus:
    error = "error"


# ---------------------------------------------------------------------------
# F. A provider failure never becomes evidence
# ---------------------------------------------------------------------------


def test_a_provider_fault_raises_instead_of_returning_results() -> None:
    """A broken integration is not an absence of evidence, and never evidence."""
    retriever = _retriever(
        SearchProviderError("tavily search failed with HTTP 401.")
    )

    with pytest.raises(RetrieverError) as excinfo:
        retriever.retrieve("india 2011")

    assert "401" in str(excinfo.value)


def test_a_missing_credential_raises_rather_than_serving_mock_evidence() -> None:
    """Real mode must never quietly fall back to fabricated results."""
    retriever = WebSearchRetriever(api_key=None)
    retriever.api_key = None

    with pytest.raises(RetrieverConfigurationError):
        retriever.retrieve("india 2011")


def test_an_empty_provider_result_yields_no_evidence_and_no_confidence() -> None:
    """Nothing returned means nothing to cite and nothing to be confident about."""
    retriever = _retriever({"results": []})

    assert retriever.retrieve("india 2011") == []
    assert verdict_confidence([]) is None


def test_a_provider_result_with_no_url_is_dropped_not_backfilled() -> None:
    """No URL means nothing to cite; a placeholder would be a fake citation."""
    items = WebSearchRetriever.parse_search_results(
        [{"title": "T", "content": "A real snippet.", "score": 0.9}]
    )

    assert items == []


def test_real_mode_never_selects_the_mock_retriever() -> None:
    assert not isinstance(
        create_default_retriever(use_mock=False, api_key="k"), type(None)
    )
    assert type(create_default_retriever(use_mock=False, api_key="k")).__name__ == (
        "WebSearchRetriever"
    )
