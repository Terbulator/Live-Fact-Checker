import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice.backend_client import BackendClient
from voice.events import TranscriptEvent


class TestBackendClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = BackendClient(base_url="http://test-backend:8000")

    async def asyncTearDown(self):
        await self.client.close()

    @patch("voice.backend_client.httpx.AsyncClient")
    async def test_start_session(self, mock_async_client):
        mock_client = AsyncMock()
        mock_async_client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"sessionId": "session_001", "status": "started"}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        session_id = await self.client.start_session()

        self.assertEqual(session_id, "session_001")
        mock_client.post.assert_called_once_with(
            "http://test-backend:8000/session/start",
            json={"startMockPipeline": False},
        )

    @patch("voice.backend_client.httpx.AsyncClient")
    async def test_stop_session(self, mock_async_client):
        mock_client = AsyncMock()
        mock_async_client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        await self.client.stop_session("session_001")

        mock_client.post.assert_called_once_with(
            "http://test-backend:8000/session/stop",
            params={"sessionId": "session_001"},
        )

    @patch("voice.backend_client.httpx.AsyncClient")
    async def test_post_transcript(self, mock_async_client):
        mock_client = AsyncMock()
        mock_async_client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        event: TranscriptEvent = {
            "type": "transcript",
            "sessionId": "session_001",
            "speaker": "Speaker 1",
            "text": "Hello world",
            "timestamp": 12.4,
            "isFinal": True,
        }

        result = await self.client.post_transcript("session_001", event)

        self.assertTrue(result)
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        self.assertEqual(call_args[0][0], "http://test-backend:8000/events/transcript")
        payload = call_args[1]["json"]
        self.assertEqual(payload["sessionId"], "session_001")
        self.assertEqual(payload["speaker"], "Speaker 1")
        self.assertEqual(payload["text"], "Hello world")
        self.assertEqual(payload["timestamp"], 12.4)
        self.assertEqual(payload["isFinal"], True)

    async def test_close(self):
        mock_client = AsyncMock()
        self.client._client = mock_client
        await self.client.close()
        mock_client.aclose.assert_called_once()
        self.assertIsNone(self.client._client)


if __name__ == "__main__":
    unittest.main()