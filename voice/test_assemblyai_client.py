import unittest
from unittest.mock import MagicMock, patch, PropertyMock, AsyncMock
from typing import Optional
from voice.events import create_transcript_event, TranscriptEvent
from concurrent.futures import Future


class MockAsyncLoop:
    """Mock for _AsyncEventLoop in tests."""
    def __init__(self):
        self._loop_started = True
    
    def submit(self, coro):
        # In tests, we need to actually await the coroutine if it's an AsyncMock
        # to get the proper result
        future = Future()
        try:
            import asyncio
            
            # Check if it's a coroutine object
            if asyncio.iscoroutine(coro):
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(coro)
                    future.set_result(result)
                finally:
                    loop.close()
            # Check if it's an AsyncMock (has _mock_call attribute)
            elif hasattr(coro, '_mock_call'):
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(coro)
                    future.set_result(result)
                finally:
                    loop.close()
            else:
                future.set_result(None)
        except Exception as e:
            future.set_exception(e)
        return future
    
    def start(self):
        pass
    
    def stop(self):
        pass


class MockWord:
    def __init__(self, start: int, end: int, text: str, confidence: float = 1.0, word_is_final: bool = True):
        self.start = start
        self.end = end
        self.confidence = confidence
        self.text = text
        self.word_is_final = word_is_final


class TestCreateTranscriptEvent(unittest.TestCase):
    def test_create_transcript_event_basic(self):
        event = create_transcript_event("session_001", "Speaker A", "Hello world", 12.4, True)
        self.assertEqual(event["type"], "transcript")
        self.assertEqual(event["sessionId"], "session_001")
        self.assertEqual(event["speaker"], "Speaker A")
        self.assertEqual(event["text"], "Hello world")
        self.assertEqual(event["timestamp"], 12.4)
        self.assertEqual(event["isFinal"], True)

    def test_create_transcript_event_strips_whitespace(self):
        event = create_transcript_event("session_001", "Speaker A", "  Hello world  ", 12.4, True)
        self.assertEqual(event["text"], "Hello world")

    def test_create_transcript_event_timestamp_float(self):
        event = create_transcript_event("session_001", "Speaker A", "Hello", 12, False)
        self.assertIsInstance(event["timestamp"], float)
        self.assertEqual(event["timestamp"], 12.0)
        self.assertEqual(event["isFinal"], False)


class TestAssemblyAIClient(unittest.TestCase):
    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_init_requires_api_key(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = None
        from voice.assemblyai_client import AssemblyAIClient
        with self.assertRaises(ValueError) as ctx:
            AssemblyAIClient()
        self.assertIn("ASSEMBLYAI_API_KEY", str(ctx.exception))

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_init_with_api_key(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient()
        self.assertIsNotNone(client.client)

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_connect_calls_client_connect(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient()
        # Patch the async loop with a mock
        client._async_loop = MockAsyncLoop()
        client.connect()

        mock_client_instance.connect.assert_called_once()
        mock_backend_instance.start_session.assert_called_once()

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_stream_audio_calls_client_stream(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient()
        client._async_loop = MockAsyncLoop()
        client.connect()
        client.stream_audio(b"audio_data")
        mock_client_instance.stream.assert_called_once_with(b"audio_data")

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_disconnect_calls_client_disconnect(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")
        mock_backend_instance.stop_session = AsyncMock()
        mock_backend_instance.close = AsyncMock()

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient()
        client._async_loop = MockAsyncLoop()
        client.connect()
        client.disconnect()

        mock_client_instance.disconnect.assert_called_once()
        mock_backend_instance.stop_session.assert_called_once_with("session_001")
        mock_backend_instance.close.assert_called_once()

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_on_turn_emits_final_transcript_event(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")
        mock_backend_instance.post_transcript = AsyncMock()

        captured_events = []

        def capture_callback(event):
            captured_events.append(event)

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient(on_transcript=capture_callback)
        client.session_id = "session_001"
        client._async_loop = MockAsyncLoop()

        mock_turn_event = MagicMock()
        mock_turn_event.transcript = "Hello world"
        type(mock_turn_event).turn_is_formatted = PropertyMock(return_value=True)
        type(mock_turn_event).speaker_label = PropertyMock(return_value="Speaker A")
        type(mock_turn_event).end_time = PropertyMock(return_value=12.4)
        mock_turn_event.words = [
            MockWord(start=12000, end=12500, text="Hello"),
            MockWord(start=12500, end=13400, text="world"),
        ]

        client._on_turn(None, mock_turn_event)

        self.assertEqual(len(captured_events), 1)
        event = captured_events[0]
        self.assertEqual(event["type"], "transcript")
        self.assertEqual(event["sessionId"], "session_001")
        # AssemblyAI "Speaker A" maps to "Speaker 1"
        self.assertEqual(event["speaker"], "Speaker 1")
        self.assertEqual(event["text"], "Hello world")
        self.assertEqual(event["timestamp"], 13.4)
        self.assertEqual(event["isFinal"], True)

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_on_turn_ignores_partial_transcript(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")
        mock_backend_instance.post_transcript = AsyncMock()

        captured_events = []

        def capture_callback(event):
            captured_events.append(event)

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient(on_transcript=capture_callback)
        client.session_id = "session_001"
        client._async_loop = MockAsyncLoop()

        mock_turn_event = MagicMock()
        mock_turn_event.transcript = "Hello"
        type(mock_turn_event).turn_is_formatted = PropertyMock(return_value=False)

        client._on_turn(None, mock_turn_event)

        self.assertEqual(len(captured_events), 1)
        self.assertEqual(captured_events[0]["isFinal"], False)

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_on_turn_handles_pending_speaker_label(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")
        mock_backend_instance.post_transcript = AsyncMock()

        captured_events = []

        def capture_callback(event):
            captured_events.append(event)

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient(on_transcript=capture_callback)
        client.session_id = "session_001"
        client._async_loop = MockAsyncLoop()

        mock_turn_event = MagicMock()
        mock_turn_event.transcript = "Hello"
        type(mock_turn_event).turn_is_formatted = PropertyMock(return_value=True)
        type(mock_turn_event).speaker_label = PropertyMock(return_value="PENDING")
        type(mock_turn_event).end_time = PropertyMock(return_value=5.0)
        mock_turn_event.words = [MockWord(start=1000, end=2000, text="Hello")]

        client._on_turn(None, mock_turn_event)

        self.assertEqual(len(captured_events), 1)
        # PENDING speaker falls back to "Speaker 1"
        self.assertEqual(captured_events[0]["speaker"], "Speaker 1")
        self.assertEqual(captured_events[0]["isFinal"], True)

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_on_turn_handles_none_speaker_label(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")
        mock_backend_instance.post_transcript = AsyncMock()

        captured_events = []

        def capture_callback(event):
            captured_events.append(event)

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient(on_transcript=capture_callback)
        client.session_id = "session_001"
        client._async_loop = MockAsyncLoop()

        mock_turn_event = MagicMock()
        mock_turn_event.transcript = "Hello"
        type(mock_turn_event).turn_is_formatted = PropertyMock(return_value=True)
        type(mock_turn_event).speaker_label = PropertyMock(return_value=None)
        type(mock_turn_event).end_time = PropertyMock(return_value=5.0)
        mock_turn_event.words = [MockWord(start=1000, end=2000, text="Hello")]

        client._on_turn(None, mock_turn_event)

        self.assertEqual(len(captured_events), 1)
        # None speaker falls back to "Speaker 1"
        self.assertEqual(captured_events[0]["speaker"], "Speaker 1")
        self.assertEqual(captured_events[0]["isFinal"], True)

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_on_turn_handles_missing_timestamp(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")
        mock_backend_instance.post_transcript = AsyncMock()

        captured_events = []

        def capture_callback(event):
            captured_events.append(event)

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient(on_transcript=capture_callback)
        client.session_id = "session_001"
        client._async_loop = MockAsyncLoop()

        mock_turn_event = MagicMock()
        mock_turn_event.transcript = "Hello"
        type(mock_turn_event).turn_is_formatted = PropertyMock(return_value=True)
        type(mock_turn_event).speaker_label = PropertyMock(return_value="Speaker A")
        type(mock_turn_event).end_time = PropertyMock(return_value=None)
        mock_turn_event.words = []

        client._on_turn(None, mock_turn_event)

        self.assertEqual(len(captured_events), 1)
        self.assertEqual(captured_events[0]["timestamp"], 0.0)
        self.assertEqual(captured_events[0]["isFinal"], True)

    @patch("voice.assemblyai_client.os.getenv")
    @patch("voice.assemblyai_client.StreamingClient")
    @patch("voice.assemblyai_client.BackendClient")
    def test_on_turn_ignores_empty_transcript(self, mock_backend_client, mock_streaming_client, mock_getenv):
        mock_getenv.return_value = "test-key"
        mock_client_instance = MagicMock()
        mock_streaming_client.return_value = mock_client_instance

        mock_backend_instance = AsyncMock()
        mock_backend_client.return_value = mock_backend_instance
        mock_backend_instance.start_session = AsyncMock(return_value="session_001")
        mock_backend_instance.post_transcript = AsyncMock()

        captured_events = []

        def capture_callback(event):
            captured_events.append(event)

        from voice.assemblyai_client import AssemblyAIClient
        client = AssemblyAIClient(on_transcript=capture_callback)
        client.session_id = "session_001"
        client._async_loop = MockAsyncLoop()

        mock_turn_event = MagicMock()
        mock_turn_event.transcript = ""
        type(mock_turn_event).turn_is_formatted = PropertyMock(return_value=True)

        client._on_turn(None, mock_turn_event)

        self.assertEqual(len(captured_events), 0)


if __name__ == "__main__":
    unittest.main()