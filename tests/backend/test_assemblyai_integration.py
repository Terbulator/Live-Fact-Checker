"""AssemblyAI realtime boundary tests.

Covers the contract Tushar's realtime STT code depends on when it posts to
``POST /events/transcript``: interim segments are forwarded for live rendering
but never claim-checked, and only a finalized line reaches claim extraction and
verification.
"""

from fastapi.testclient import TestClient

from backend.adapters.claim_engine import StaticClaimEngine
from backend.config import Settings
from backend.main import create_app
from backend.mocks.mock_stream import MockVerificationEngine
from backend.schemas import ClaimEvent, TranscriptEvent

from .conftest import transcript_payload

REFERENCE_CLAIM = "India won the 2011 Cricket World Cup."


class _RecordingClaimEngine(StaticClaimEngine):
    """A non-filtering claim engine that records every transcript it is given."""

    name = "recording-static-claim-engine"

    def __init__(self) -> None:
        super().__init__(
            [
                ClaimEvent(
                    type="claim",
                    claimId="claim_live_001",
                    sessionId="session_placeholder",
                    speaker="Speaker 1",
                    timestamp=0.0,
                    claim=REFERENCE_CLAIM,
                    claimType="historical_fact",
                )
            ]
        )
        self.calls: list[TranscriptEvent] = []

    async def extract_claims(self, transcript: TranscriptEvent):
        self.calls.append(transcript)
        return await super().extract_claims(transcript)


def _app_with_real_style_claim_engine() -> tuple[TestClient, _RecordingClaimEngine]:
    """An app whose claim engine extracts from *any* transcript.

    The engine ignores ``isFinal``, like a real Atif claim engine, so the gate
    on interim segments has to live in the router rather than in a test double.
    """
    engine = _RecordingClaimEngine()
    settings = Settings(
        environment="test",
        use_mock_engines=False,
        log_level="WARNING",
        log_json=False,
    )
    client = TestClient(
        create_app(
            settings=settings,
            claim_engine=engine,
            verification_engine=MockVerificationEngine(),
        )
    )
    return client, engine


def test_interim_transcript_is_forwarded_but_never_claim_checked() -> None:
    client, engine = _app_with_real_style_claim_engine()
    with client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]

        response = client.post(
            "/events/transcript",
            json=transcript_payload(session_id, text="India won the", isFinal=False),
        )

        assert response.status_code == 202
        body = response.json()
        assert body["transcript"]["isFinal"] is False
        # The engine must not even be asked about an interim segment.
        assert engine.calls == []
        assert body["claims"] == []
        assert body["verifications"] == []
        assert body["counts"] == {"claims": 0, "verifications": 0, "errors": 0}
        # The interim segment still counts as heard audio.
        assert client.get(f"/session/{session_id}").json()["transcriptCount"] == 1


def test_realtime_stream_verifies_only_the_final_segment() -> None:
    client, engine = _app_with_real_style_claim_engine()
    with client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]

        for partial in ("India", "India won the", "India won the 2011 Cricket World"):
            response = client.post(
                "/events/transcript",
                json=transcript_payload(session_id, text=partial, isFinal=False),
            )
            assert response.json()["verifications"] == []

        final = client.post(
            "/events/transcript",
            json=transcript_payload(session_id, isFinal=True),
        ).json()

        assert [claim["claimId"] for claim in final["claims"]] == ["claim_live_001"]
        assert [v["verdict"] for v in final["verifications"]] == ["TRUE"]
        assert final["counts"] == {"claims": 1, "verifications": 1, "errors": 0}
        # Exactly one of the four segments reached the claim engine.
        assert [call.isFinal for call in engine.calls] == [True]
        assert client.get(f"/session/{session_id}").json()["transcriptCount"] == 4


def test_interim_segments_still_reach_the_frontend_in_order() -> None:
    client, _engine = _app_with_real_style_claim_engine()
    with client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]

        with client.websocket_connect(f"/ws/session/{session_id}") as websocket:
            assert websocket.receive_json()["type"] == "session"

            client.post(
                "/events/transcript",
                json=transcript_payload(session_id, text="India won the", isFinal=False),
            )
            client.post("/events/transcript", json=transcript_payload(session_id))

            received = []
            for _ in range(3):
                message = websocket.receive_json()
                if message["type"] != "session":
                    received.append(message["type"])

            # Interim live text, then the finalized transcript, then its claim.
            assert received == ["transcript", "transcript", "claim"]


def test_stopped_session_rejects_further_stream_segments() -> None:
    client, _engine = _app_with_real_style_claim_engine()
    with client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]
        client.post("/session/stop", params={"sessionId": session_id})

        response = client.post("/events/transcript", json=transcript_payload(session_id))

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "SESSION_STOPPED"


def test_stream_segment_with_wrong_type_is_rejected() -> None:
    client, _engine = _app_with_real_style_claim_engine()
    with client:
        session_id = client.post("/session/start", json={}).json()["sessionId"]

        response = client.post(
            "/events/transcript", json=transcript_payload(session_id, type="claim")
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "UNSUPPORTED_EVENT_TYPE"


def test_unknown_session_segment_is_rejected() -> None:
    client, _engine = _app_with_real_style_claim_engine()
    with client:
        response = client.post(
            "/events/transcript", json=transcript_payload("session_missing")
        )

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"
