"""Ingestion route tests: the existing audio / video / URL paths still work.

These routes were added alongside the live-microphone work and then left with no
coverage at all, which is how a missing ``python-multipart`` dependency could
stop the entire application from importing without a single test failing.

The AssemblyAI call is the only thing replaced. Validation, routing, session
guards, transcript conversion and the hand-off into the real claim/verification
pipeline all run for real, with the mock engines that ``tests/conftest.py``
selects.
"""

import io
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.mocks.mock_stream import MockClaimEngine, MockVerificationEngine
from backend.schemas import TranscriptEvent


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _Segment:
    """An AssemblyAI utterance."""

    def __init__(self, speaker, text, start, end, confidence):
        self.speaker = speaker
        self.text = text
        self.start = start
        self.end = end
        self.confidence = confidence


class _Transcript:
    def __init__(self, text, confidence, utterances):
        self.status = "ok"
        self.error = None
        self.text = text
        self.confidence = confidence
        self.utterances = utterances


@pytest.fixture()
def stub_assemblyai(monkeypatch):
    """Replace the AssemblyAI call and record what the adapter was given.

    Returns a dict the test can read ``.calls`` off. The AssemblyAI credential
    check is satisfied with a real ``Settings`` instance so the guard itself is
    still exercised.
    """
    import backend.ingestion.audio as audio_module
    import backend.ingestion.url as url_module
    import backend.ingestion.video as video_module

    settings = Settings(
        environment="test",
        use_mock_engines=True,
        assemblyai_api_key="test-assemblyai-key",
    )

    class _FakeTranscriber:
        def __init__(self, config=None):
            self.config = config

        def transcribe(self, path):
            stub_assemblyai.calls.append({"path": path})
            return stub_assemblyai.transcript

    stub_assemblyai.calls = []
    stub_assemblyai.transcript = _Transcript("Real words.", None, None)
    stub_assemblyai.paths = audio_module.Path

    monkeypatch.setattr(audio_module, "get_settings", lambda: settings)
    monkeypatch.setattr(url_module, "get_settings", lambda: settings)
    monkeypatch.setattr(video_module, "get_settings", lambda: settings)
    monkeypatch.setattr(audio_module.aai, "Transcriber", _FakeTranscriber)
    return stub_assemblyai


@pytest.fixture()
def app_with_sockets(monkeypatch):
    """An app whose broadcast path records what a WebSocket client would see.

    ``create_app`` does not take a socket manager, so the recording happens one
    layer earlier, on the router's own outbound path.
    """
    created: Dict[str, Any] = {"events": []}

    async def _record(self, session_id, event) -> None:
        created["events"].append(event)

    monkeypatch.setattr("backend.router.EventRouter.broadcast", _record, raising=True)

    created["app"] = create_app(
        settings=Settings(environment="test", use_mock_engines=True),
        claim_engine=MockClaimEngine(),
        verification_engine=MockVerificationEngine(),
    )
    return created


@pytest.fixture()
def client(app_with_sockets):
    with TestClient(app_with_sockets["app"]) as test_client:
        yield test_client


@pytest.fixture()
def session_id(client) -> str:
    response = client.post("/session/start", json={})
    assert response.status_code == 201, response.text
    return response.json()["sessionId"]


def _upload(client, path, session, filename, content_type, payload=b"binary-bytes"):
    return client.post(
        path,
        data={"session_id": session},
        files={"file": (filename, io.BytesIO(payload), content_type)},
    )


def _transcript_events(app_with_sockets) -> List[TranscriptEvent]:
    return [
        event
        for event in app_with_sockets.get("events", [])
        if isinstance(event, TranscriptEvent)
    ]


# ---------------------------------------------------------------------------
# K. The endpoints are registered and reachable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/ingestion/audio", "/ingestion/video", "/ingestion/video-url"]
)
def test_ingestion_routes_are_registered(client, path) -> None:
    """The ingestion router must be mounted, or the UI's buttons do nothing."""
    paths = client.get("/openapi.json").json()["paths"]
    assert path in paths


def test_ingestion_router_actually_imports() -> None:
    """Regression guard for the missing ``python-multipart`` dependency.

    FastAPI raises at decoration time when the multipart parser is absent, so
    its absence stopped ``import backend.main`` -- and therefore the whole
    application -- rather than only the upload endpoints.
    """
    import backend.main  # noqa: F401
    from backend.routes import ingestion  # noqa: F401


# ---------------------------------------------------------------------------
# Audio upload
# ---------------------------------------------------------------------------


def test_audio_upload_transcribes_and_enters_the_pipeline(
    client, session_id, stub_assemblyai
) -> None:
    """A real upload is transcribed and its segments reach the router."""
    stub_assemblyai.transcript = _Transcript(
        "India won the 2011 Cricket World Cup.",
        0.93,
        [_Segment("A", "India won the 2011 Cricket World Cup.", 1200, 4800, 0.93)],
    )

    response = _upload(
        client, "/ingestion/audio", session_id, "speech.mp3", "audio/mpeg"
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["transcript"] == "India won the 2011 Cricket World Cup."
    assert body["transcript_segments"] == [
        {
            "speaker": "Speaker A",
            "text": "India won the 2011 Cricket World Cup.",
            "start": 1.2,
            "end": 4.8,
            "confidence": 0.93,
        }
    ]


def test_audio_upload_sends_transcript_events_to_the_session(
    client, session_id, stub_assemblyai, app_with_sockets
) -> None:
    """The transcript is fed into the existing pipeline, not just returned."""
    stub_assemblyai.transcript = _Transcript(
        "Mount Everest is the highest mountain in Africa.",
        0.9,
        [_Segment("A", "Mount Everest is the highest mountain in Africa.", 0, 2000, 0.9)],
    )

    _upload(client, "/ingestion/audio", session_id, "speech.wav", "audio/wav")

    broadcasts = _transcript_events(app_with_sockets)
    assert broadcasts, "the ingested transcript never reached the router"
    assert broadcasts[0].text == "Mount Everest is the highest mountain in Africa."
    assert broadcasts[0].sessionId == session_id


def test_audio_upload_preserves_the_provider_confidence(
    client, session_id, stub_assemblyai
) -> None:
    """AssemblyAI's score is stored as it arrived."""
    stub_assemblyai.transcript = _Transcript(
        "A claim.", 0.77, [_Segment("A", "A claim.", 0, 1000, 0.77)]
    )

    body = _upload(
        client, "/ingestion/audio", session_id, "speech.mp3", "audio/mpeg"
    ).json()

    assert body["transcript_segments"][0]["confidence"] == 0.77


def test_audio_upload_reports_null_when_the_provider_gave_no_confidence(
    client, session_id, stub_assemblyai
) -> None:
    """A missing score is null. It must never become 1.0."""
    stub_assemblyai.transcript = _Transcript(
        "A claim.", None, [_Segment("A", "A claim.", 0, 1000, None)]
    )

    body = _upload(
        client, "/ingestion/audio", session_id, "speech.mp3", "audio/mpeg"
    ).json()

    segment = body["transcript_segments"][0]
    assert segment["confidence"] is None
    assert segment["confidence"] != 1.0


def test_audio_upload_without_utterances_reports_null_not_one(
    client, session_id, stub_assemblyai
) -> None:
    """The single-segment fallback must not invent a confidence."""
    stub_assemblyai.transcript = _Transcript("Whole file text.", None, None)

    body = _upload(
        client, "/ingestion/audio", session_id, "speech.flac", "audio/flac"
    ).json()

    assert body["transcript_segments"] == [
        {
            "speaker": "Speaker 1",
            "text": "Whole file text.",
            "start": 0.0,
            "end": 0.0,
            "confidence": None,
        }
    ]


@pytest.mark.parametrize(
    "filename, content_type, code",
    [
        ("notes.txt", "text/plain", "UNSUPPORTED_FORMAT"),
        ("clip.mp3", "audio/mpeg", "EMPTY_FILE"),
    ],
)
def test_audio_upload_rejects_unusable_files(
    client, session_id, filename, content_type, code
) -> None:
    """Validation still guards the endpoint."""
    payload = b"" if code == "EMPTY_FILE" else b"not media"
    response = _upload(
        client, "/ingestion/audio", session_id, filename, content_type, payload
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == code


# ---------------------------------------------------------------------------
# Video upload
# ---------------------------------------------------------------------------


def test_video_upload_extracts_audio_then_transcribes(
    client, session_id, stub_assemblyai, monkeypatch
) -> None:
    """ffmpeg is stubbed; everything after it is the real code path."""
    import backend.ingestion.video as video_module

    extracted = {}

    async def _fake_extract(video_path, output_path) -> float:
        extracted["video"] = video_path
        extracted["audio"] = output_path
        return 12.5

    async def _fake_duration(path) -> float:
        return 12.5

    monkeypatch.setattr(video_module, "extract_audio_from_video", _fake_extract)
    monkeypatch.setattr(video_module, "get_media_duration", _fake_duration)

    stub_assemblyai.transcript = _Transcript(
        "Extracted words.", 0.85, [_Segment("A", "Extracted words.", 0, 3000, 0.85)]
    )

    response = _upload(
        client, "/ingestion/video", session_id, "clip.mp4", "video/mp4"
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["transcript"] == "Extracted words."
    assert extracted["audio"].endswith(".wav")


def test_video_upload_rejects_unsupported_format(client, session_id) -> None:
    response = _upload(
        client, "/ingestion/video", session_id, "clip.txt", "text/plain"
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


# ---------------------------------------------------------------------------
# Video URL
# ---------------------------------------------------------------------------


def test_video_url_ingestion_transcribes_the_download(
    client, session_id, stub_assemblyai, monkeypatch
) -> None:
    """A direct video URL is downloaded, de-voiced and transcribed."""
    import backend.ingestion.url as url_module

    async def _fake_download(url, output_path) -> int:
        return 2048

    async def _fake_extract(video_path, output_path) -> float:
        return 7.0

    async def _fake_duration(path) -> float:
        return 7.0

    async def _fake_validate(url) -> None:
        return None

    monkeypatch.setattr(url_module, "validate_url", _fake_validate)
    monkeypatch.setattr(url_module, "download_video_url", _fake_download)
    monkeypatch.setattr(url_module, "extract_audio_from_video", _fake_extract)
    monkeypatch.setattr(url_module, "get_media_duration", _fake_duration)

    stub_assemblyai.transcript = _Transcript(
        "Downloaded words.", None, [_Segment("A", "Downloaded words.", 0, 2000, None)]
    )

    response = client.post(
        "/ingestion/video-url",
        json={"session_id": session_id, "url": "https://cdn.example.com/talk.mp4"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["transcript"] == "Downloaded words."
    assert body["transcript_segments"][0]["confidence"] is None


def test_video_url_ingestion_rejects_an_unsupported_url(client, session_id) -> None:
    response = client.post(
        "/ingestion/video-url",
        json={"session_id": session_id, "url": "https://example.com/not-a-video"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNSUPPORTED_URL"


# ---------------------------------------------------------------------------
# Session guards
# ---------------------------------------------------------------------------


def test_audio_upload_requires_a_known_session(client) -> None:
    response = _upload(
        client, "/ingestion/audio", "no-such-session", "speech.mp3", "audio/mpeg"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_ingestion_is_refused_once_the_session_is_stopped(
    client, session_id, stub_assemblyai
) -> None:
    """A stopped session must not accept new media."""
    assert client.post(f"/session/stop?sessionId={session_id}").status_code == 200

    response = _upload(
        client, "/ingestion/audio", session_id, "speech.mp3", "audio/mpeg"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SESSION_STOPPED"
