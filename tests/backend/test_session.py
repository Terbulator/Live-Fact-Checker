"""Session lifecycle tests (required checks 3, 4 and 5).

The second half covers the mock pipeline's lifecycle: the session owns the
background task, and stopping the session cancels it.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.mocks.mock_stream import stream_mock_transcripts
from backend.session_manager import SessionManager


def test_session_creation_returns_backend_owned_id(client: TestClient) -> None:
    response = client.post("/session/start", json={})
    assert response.status_code == 201

    body = response.json()
    assert body["type"] == "session"
    assert isinstance(body["sessionId"], str) and len(body["sessionId"]) > 0
    assert body["status"] in {"started", "connected"}
    assert body["createdAt"]
    assert body["updatedAt"]
    assert body["wsUrl"].startswith("ws://")
    assert f"/ws/session/{body['sessionId']}" in body["wsUrl"]


def test_session_creation_accepts_empty_body(client: TestClient) -> None:
    response = client.post("/session/start")
    assert response.status_code == 201
    assert isinstance(response.json()["sessionId"], str) and len(response.json()["sessionId"]) > 0


def test_session_ids_are_unique(client: TestClient) -> None:
    ids = {client.post("/session/start", json={}).json()["sessionId"] for _ in range(5)}
    assert len(ids) == 5


def test_session_retrieval(client: TestClient, session_id: str) -> None:
    response = client.get(f"/session/{session_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["sessionId"] == session_id
    assert body["transcriptCount"] == 0
    assert body["claimCount"] == 0
    assert body["verificationCount"] == 0
    assert body["connectedClients"] == 0


def test_session_retrieval_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get("/session/session_does_not_exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_session_stop(client: TestClient, session_id: str) -> None:
    response = client.post("/session/stop", params={"sessionId": session_id})
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert client.get(f"/session/{session_id}").json()["status"] == "stopped"


def test_session_stop_is_idempotent(client: TestClient, session_id: str) -> None:
    first = client.post("/session/stop", params={"sessionId": session_id})
    second = client.post("/session/stop", params={"sessionId": session_id})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "stopped"


def test_session_stop_unknown_session_returns_404(client: TestClient) -> None:
    response = client.post("/session/stop", params={"sessionId": "session_999"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_stopped_session_rejects_new_events(client: TestClient, session_id: str) -> None:
    client.post("/session/stop", params={"sessionId": session_id})
    response = client.post(
        "/events/transcript",
        json={
            "type": "transcript",
            "sessionId": session_id,
            "speaker": "Speaker 1",
            "text": "India won the 2011 Cricket World Cup.",
            "timestamp": 12.4,
            "isFinal": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SESSION_STOPPED"


def test_session_counters_increase_with_events(client: TestClient, session_id: str) -> None:
    client.post(
        "/events/transcript",
        json={
            "type": "transcript",
            "sessionId": session_id,
            "speaker": "Speaker 1",
            "text": "India won the 2011 Cricket World Cup.",
            "timestamp": 12.4,
            "isFinal": True,
        },
    )
    body = client.get(f"/session/{session_id}").json()
    assert body["transcriptCount"] == 1
    assert body["claimCount"] == 1
    assert body["verificationCount"] == 1


# ---------------------------------------------------------------------------
# Mock pipeline lifecycle
# ---------------------------------------------------------------------------


def test_session_start_tracks_the_mock_pipeline_task(client: TestClient) -> None:
    """The started session is recorded, so stop/shutdown can find the task."""
    session = client.post(
        "/session/start", json={"startMockPipeline": True}
    ).json()["sessionId"]
    assert isinstance(session, str) and len(session) > 0


def test_session_stop_cancels_the_mock_pipeline_task() -> None:
    """A live task is cancelled and awaited when its session stops."""
    sessions = SessionManager()

    async def scenario() -> None:
        session = (await sessions.create()).sessionId
        task = asyncio.create_task(asyncio.sleep(30))
        sessions.track_background_task(session, task)
        assert await sessions.background_task(session) is task

        await sessions.stop(session)

        assert task.done()
        assert await sessions.background_task(session) is None

    asyncio.run(scenario())


def test_shutdown_cancels_every_tracked_task() -> None:
    """`cancel_all_background_tasks` drains all sessions' tasks."""
    sessions = SessionManager()

    async def scenario() -> None:
        first = (await sessions.create()).sessionId
        second = (await sessions.create()).sessionId
        tasks = [asyncio.create_task(asyncio.sleep(30)) for _ in range(2)]
        sessions.track_background_task(first, tasks[0])
        sessions.track_background_task(second, tasks[1])

        await sessions.cancel_all_background_tasks()

        assert all(task.done() for task in tasks)
        assert await sessions.background_task(first) is None
        assert await sessions.background_task(second) is None

    asyncio.run(scenario())


def test_no_events_are_produced_after_a_stop(client: TestClient) -> None:
    session = client.post(
        "/session/start", json={"startMockPipeline": True}
    ).json()["sessionId"]
    client.post("/session/stop", params={"sessionId": session})
    transcript_count = client.get(f"/session/{session}").json()["transcriptCount"]

    time.sleep(0.9)  # longer than the mock pipeline's per-segment delay

    assert client.get(f"/session/{session}").json()["transcriptCount"] == transcript_count


def test_app_shutdown_cancels_surviving_mock_pipelines() -> None:
    """Exiting the TestClient context must not leave a pending task behind."""
    from backend.config import Settings
    from backend.main import create_app

    app = create_app(
        settings=Settings(environment="test", use_mock_engines=True, log_level="WARNING")
    )
    with TestClient(app) as client:
        client.post("/session/start", json={"startMockPipeline": True})
        assert app.state.session_manager._background  # a task is tracked

    assert not app.state.session_manager._background  # and drained on shutdown


@pytest.mark.asyncio
async def test_mock_stream_stops_emitting_once_the_session_is_gone() -> None:
    """A cleared session ends the stream instead of pushing a 409 every segment."""
    sessions = SessionManager()

    class _RecordingRouter:
        def __init__(self) -> None:
            self.calls = 0

        async def handle_transcript(self, event) -> None:
            self.calls += 1

    await sessions.create()  # the stream must tolerate the session disappearing
    router = _RecordingRouter()
    stream = asyncio.create_task(
        stream_mock_transcripts(router, sessions, "session_001", delay=0.01)
    )
    await asyncio.sleep(0.05)
    await sessions.remove("session_001")
    await asyncio.wait_for(stream, timeout=1.0)

    after_clear = router.calls
    await asyncio.sleep(0.05)
    assert router.calls == after_clear
