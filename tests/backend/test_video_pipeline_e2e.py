"""End-to-end video-pipeline scenario.

Traces the full production path for an ingested transcript:

    transcript -> LLM claim extraction -> Tavily evidence -> verification
               -> verdict + supporting statement -> scorecard

Everything here is the real production wiring: the real
:class:`LLMClaimEngine`, the real :class:`WebSearchRetriever` with the real
``TavilyProvider``, the real :class:`VerificationService`, the real checker and
the real router. Only the two external network calls are stubbed -- the LLM
Gateway HTTP POST and the Tavily transport -- so the confidence parsing,
ranking, supporting-statement assembly and verdict logic all execute for real.

The assertions encode what the supplied evidence genuinely establishes. Nothing
here asserts a verdict the evidence does not support.
"""

import json
from typing import Any, Dict, List

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.claim_engine import LLMClaimEngine
from backend.adapters.verification import VerificationServiceEngine
from backend.config import Settings
from backend.main import create_app
from verification.retriever import WebSearchRetriever
from verification.search_providers import SearchResponse, TavilyProvider

# ---------------------------------------------------------------------------
# The transcript, and the evidence that decides each of its two claims.
# ---------------------------------------------------------------------------

TRANSCRIPT = "India won the 2011 Cricket World Cup. The final was played in Mumbai."

CLAIM_WINNER = "India won the 2011 Cricket World Cup."
CLAIM_VENUE = "The final was played in Mumbai."

# Supports the first claim: corroborating words plus the same year, so the
# checker's numerical branch finds no discrepancy.
EVIDENCE_WINNER = (
    "India beat Sri Lanka in the 2011 ICC Cricket World Cup final held at the "
    "Wankhede Stadium."
)
# Supports the second claim: names the venue the claim asserts.
EVIDENCE_VENUE = (
    "The 2011 ICC Cricket World Cup final was played at the Wankhede Stadium "
    "in Mumbai, India."
)

SOURCE_WINNER = "https://www.espncricinfo.com/series/icc-world-cup-2011-118026"
SOURCE_VENUE = "https://www.icc-cricket.com/tournaments/cricketworldcup/news/final"


def _gateway_response() -> Dict[str, Any]:
    """The LLM extracting the two independent assertions in the transcript."""
    content = json.dumps(
        {
            "claims": [
                {"claim": CLAIM_WINNER, "claimType": "sports"},
                {"claim": CLAIM_VENUE, "claimType": "location"},
            ]
        }
    )
    return {"model": "qwen3.5-4b-32k-fast", "choices": [{"message": {"content": content}}]}


def _tavily_payload(query: str) -> Dict[str, Any]:
    """Return evidence appropriate to the question that was asked.

    Keyed on the query so each claim is answered by the snippet that actually
    addresses it, exactly as a real search would.
    """
    if "mumbai" in query.lower():
        return {
            "results": [
                {
                    "title": "ICC World Cup 2011 final venue",
                    "url": SOURCE_VENUE,
                    "content": EVIDENCE_VENUE,
                    "score": 0.91,
                }
            ]
        }
    return {
        "results": [
            {
                "title": "ICC Cricket World Cup 2011",
                "url": SOURCE_WINNER,
                "content": EVIDENCE_WINNER,
                "score": 0.88,
            }
        ]
    }


class _StubTransport:
    """Stands in for the Tavily HTTP call; the provider adapter still runs."""

    def __init__(self) -> None:
        self.queries: List[str] = []

    def __call__(self, url, headers, payload, timeout_seconds) -> SearchResponse:
        query = str(payload.get("query", ""))
        self.queries.append(query)
        assert headers.get("Authorization", "").startswith("Bearer "), (
            "the provider must authenticate with a bearer token"
        )
        return SearchResponse(status_code=200, headers={}, payload=_tavily_payload(query))


@pytest.fixture()
def providers(monkeypatch):
    """Stub only the two external providers; leave all our own code real."""
    gateway = {"calls": 0, "bodies": []}

    class _StubResponse:
        def __init__(self, payload: Dict[str, Any]) -> None:
            self._payload = payload
            self.status_code = 200
            self.headers: Dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> Dict[str, Any]:
            return self._payload

    async def fake_post(self, url, **kwargs):
        gateway["calls"] += 1
        gateway["bodies"].append(kwargs.get("json"))
        return _StubResponse(_gateway_response())

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    gateway["tavily"] = _StubTransport()
    return gateway


@pytest.fixture()
def app(providers):
    """The real production stack, with only the providers replaced."""
    settings = Settings(
        environment="test",
        use_mock_engines=False,
        log_level="WARNING",
        llm_gateway_api_key="test-llm-key",
        search_api_key="test-search-key",
    )
    retriever = WebSearchRetriever(
        api_key="test-search-key",
        provider="tavily",
        provider_client=TavilyProvider("test-search-key", transport=providers["tavily"]),
    )
    return create_app(
        settings=settings,
        claim_engine=LLMClaimEngine(settings, strict=True),
        verification_engine=VerificationServiceEngine(retriever=retriever),
    )


def _tally(verifications: List[dict]) -> Dict[str, int]:
    """Mirror the frontend's tally so the invariant is checked on real data."""
    counts = {"TRUE": 0, "FALSE": 0, "UNVERIFIABLE": 0, "AMBIGUOUS": 0}
    for event in verifications:
        counts[event["verdict"]] += 1
    return counts


# ---------------------------------------------------------------------------
# The scenario
# ---------------------------------------------------------------------------


def test_video_transcript_flows_to_a_consistent_scorecard(app, providers) -> None:
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        response = client.post(
            "/events/transcript",
            json={
                "type": "transcript",
                "sessionId": session,
                "speaker": "Speaker 1",
                "text": TRANSCRIPT,
                "timestamp": 0.0,
                "isFinal": True,
            },
        )

    assert response.status_code == 202
    body = response.json()
    claims = body["claims"]
    verifications = body["verifications"]

    # --- one extraction call produced both claims -------------------------
    assert providers["calls"] == 1, "the batch must cost a single gateway request"
    assert len(claims) == 2, "a compound sentence must split into two claims"
    assert [c["claim"] for c in claims] == [CLAIM_WINNER, CLAIM_VENUE]
    assert [c["claimId"] for c in claims] == [
        f"{session}_claim_001",
        f"{session}_claim_002",
    ]

    # --- each claim verified independently --------------------------------
    assert len(verifications) == 2, "each extracted claim gets its own verification"
    by_claim = {v["claimId"]: v for v in verifications}
    assert set(by_claim) == {c["claimId"] for c in claims}

    # The evidence supplied supports both assertions.
    winner = by_claim[f"{session}_claim_001"]
    venue = by_claim[f"{session}_claim_002"]
    assert winner["verdict"] == "TRUE"
    assert venue["verdict"] == "TRUE"

    # --- real sources, not placeholders -----------------------------------
    assert winner["source"] == SOURCE_WINNER
    assert venue["source"] == SOURCE_VENUE
    assert all(v["source"].startswith("https://") for v in verifications)
    assert all(not v["source"].endswith("example.com") for v in verifications)

    # --- provider-derived confidence, preserved ---------------------------
    assert winner["confidence"] == pytest.approx(0.88)
    assert venue["confidence"] == pytest.approx(0.91)
    # Per-source score rides along so the UI can show how well attested each is.
    assert winner["sources"][0]["confidence"] == pytest.approx(0.88)

    # --- supporting statements grounded in the retrieved snippets ---------
    for verification, expected_snippet, expected_host in (
        (winner, EVIDENCE_WINNER, "espncricinfo.com"),
        (venue, EVIDENCE_VENUE, "icc-cricket.com"),
    ):
        statement = verification["supportingStatement"]
        assert statement is not None, "citable evidence must produce a statement"
        # It quotes the evidence verbatim rather than paraphrasing from memory.
        assert expected_snippet[:40] in statement
        assert expected_host in statement

    # --- identity preserved across the boundary ---------------------------
    assert all(v["sessionId"] == session for v in verifications)


def test_scorecard_counts_sum_to_the_total_analysed(app) -> None:
    """The invariant a video scorecard must satisfy: no claim goes uncounted."""
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        body = client.post(
            "/events/transcript",
            json={
                "type": "transcript",
                "sessionId": session,
                "speaker": "Speaker 1",
                "text": TRANSCRIPT,
                "timestamp": 0.0,
                "isFinal": True,
            },
        ).json()

    verifications = body["verifications"]
    counts = _tally(verifications)

    assert body["counts"]["claims"] == 2
    assert body["counts"]["verifications"] == 2
    assert body["counts"]["errors"] == 0

    # 11 + 5 + 3 + 1 == 20, i.e. every analysed claim lands in exactly one bucket.
    assert sum(counts.values()) == len(verifications) == body["counts"]["claims"]
    assert counts == {"TRUE": 2, "FALSE": 0, "UNVERIFIABLE": 0, "AMBIGUOUS": 0}


def test_timestamps_and_speaker_survive_to_the_verification(app) -> None:
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        body = client.post(
            "/events/transcript",
            json={
                "type": "transcript",
                "sessionId": session,
                "speaker": "Moderator",
                "text": TRANSCRIPT,
                "timestamp": 42.5,
                "isFinal": True,
            },
        ).json()

    claim = body["claims"][0]
    verification = body["verifications"][0]
    # Preserved, not invented: these came in on the transcript event.
    assert claim["speaker"] == "Moderator"
    assert claim["timestamp"] == pytest.approx(42.5)
    assert verification["speaker"] == "Moderator"
    assert verification["timestamp"] == pytest.approx(42.5)


def test_no_fake_data_appears_anywhere_in_the_flow(app) -> None:
    """Nothing in the response is fabricated: no invented verdict or source."""
    with TestClient(app) as client:
        session = client.post("/session/start", json={}).json()["sessionId"]
        body = client.post(
            "/events/transcript",
            json={
                "type": "transcript",
                "sessionId": session,
                "speaker": "Speaker 1",
                "text": TRANSCRIPT,
                "timestamp": 0.0,
                "isFinal": True,
            },
        ).json()

    rendered = json.dumps(body)
    for forbidden in ("example.com", "example.org", "lorem ipsum", "TODO", "placeholder"):
        assert forbidden not in rendered, f"fabricated content present: {forbidden}"
    # Every verdict is one of the four the product defines.
    assert {v["verdict"] for v in body["verifications"]} <= {
        "TRUE",
        "FALSE",
        "UNVERIFIABLE",
        "AMBIGUOUS",
    }
