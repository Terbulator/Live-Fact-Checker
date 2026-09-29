import os
import asyncio
import threading
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor

from assemblyai.streaming.v3 import (
    StreamingClient,
    StreamingEvents,
    StreamingParameters,
    TurnEvent,
    RealTimeTranscriberOptions,
)

from voice.events import create_transcript_event, TranscriptEvent
from voice.backend_client import BackendClient


class _AsyncEventLoop:
    """Dedicated background thread with a persistent asyncio event loop.
    
    This solves the event-loop lifecycle issues when making async HTTP calls
    from synchronous AssemblyAI callbacks in a long-lived streaming session.
    """
    
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._stop_requested = False

    def start(self):
        """Start the background thread and event loop."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._started.wait(timeout=5.0)
        if self._loop is None:
            raise RuntimeError("Failed to start async event loop")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()
            self._loop = None

    def submit(self, coro):
        """Submit a coroutine to the background loop.
        
        Returns a concurrent.futures.Future that can be awaited or .result()'d
        from the calling thread.
        """
        if self._loop is None:
            raise RuntimeError("Event loop not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self, timeout: float = 5.0):
        """Stop the background event loop and thread."""
        if self._loop is None:
            return
        self._stop_requested = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
        self._loop = None


class AssemblyAIClient:
    def __init__(
        self,
        on_transcript: Optional[Callable[[TranscriptEvent], None]] = None,
        backend_base_url: Optional[str] = None,
        use_backend: bool = True,
    ):
        api_key = os.getenv("ASSEMBLYAI_API_KEY")

        if not api_key:
            raise ValueError("ASSEMBLYAI_API_KEY is not set")

        self.on_transcript = on_transcript
        self.use_backend = use_backend
        self.backend_client = BackendClient(backend_base_url) if use_backend else None
        self.session_id: Optional[str] = None
        
        # Speaker label mapping: AssemblyAI labels (A, B, C, etc.) -> Speaker 1, Speaker 2, etc.
        self._speaker_map: dict[str, str] = {}
        self._next_speaker_num = 1
        
        # Deduplication: track last final transcript per speaker to avoid duplicates
        self._last_final_transcript: dict[str, str] = {}
        
        # Persistent background event loop for async backend operations
        self._async_loop = _AsyncEventLoop() if use_backend else None

        self.client = StreamingClient(
            RealTimeTranscriberOptions(
                api_key=api_key,
                max_connection_retries=5,
                connection_retry_delay=1.0,
            )
        )

        self._register_handlers()

    def _register_handlers(self):
        self.client.on(
            StreamingEvents.Begin,
            self._on_begin,
        )

        self.client.on(
            StreamingEvents.Turn,
            self._on_turn,
        )

        self.client.on(
            StreamingEvents.Error,
            self._on_error,
        )

        self.client.on(
            StreamingEvents.Termination,
            self._on_termination,
        )

    def _on_begin(self, client, event):
        print(f"[AssemblyAI] Session started: {event}")

    def _on_turn(self, client, event: TurnEvent):
        if not event.transcript:
            return

        is_final = getattr(event, "turn_is_formatted", False) is True

        # Get AssemblyAI speaker label
        raw_speaker = getattr(event, "speaker_label", None)
        
        # Map AssemblyAI speaker labels to deterministic Speaker 1, Speaker 2, etc.
        if raw_speaker and raw_speaker != "PENDING":
            if raw_speaker not in self._speaker_map:
                self._speaker_map[raw_speaker] = f"Speaker {self._next_speaker_num}"
                self._next_speaker_num += 1
            speaker = self._speaker_map[raw_speaker]
        else:
            # Deterministic fallback instead of UNKNOWN
            speaker = "Speaker 1"

        # Extract timestamp from words (in milliseconds, convert to seconds)
        timestamp = 0.0
        words = getattr(event, "words", None)
        if words:
            # Use the end time of the last word as the turn timestamp
            last_word = words[-1]
            timestamp = getattr(last_word, "end", 0) / 1000.0
        elif hasattr(event, "end_time") and event.end_time is not None:
            timestamp = float(event.end_time)

        # For standalone mode, generate a local session_id if not using backend
        if self.session_id is None and not self.use_backend:
            self.session_id = "standalone"

        if self.session_id is None:
            return

        # Deduplication: skip duplicate final transcripts for the same speaker
        if is_final:
            last_text = self._last_final_transcript.get(speaker)
            if last_text is not None and last_text == event.transcript:
                # Skip duplicate final transcript
                return
            self._last_final_transcript[speaker] = event.transcript

        transcript_event = create_transcript_event(
            session_id=self.session_id,
            speaker=speaker,
            text=event.transcript,
            timestamp=timestamp,
            is_final=is_final,
        )

        print(f"[{speaker}] {'FINAL' if is_final else 'PARTIAL'} {event.transcript}")

        if self.on_transcript:
            self.on_transcript(transcript_event)

        # Post to backend asynchronously via persistent event loop
        if self.use_backend and self._async_loop is not None:
            self._async_loop.submit(self._post_to_backend(transcript_event))

    async def _post_to_backend(self, event: TranscriptEvent):
        if not self.use_backend:
            return
        try:
            await self.backend_client.post_transcript(self.session_id, event)
        except Exception as e:
            print(f"[Backend ERROR] Failed to post transcript: {e}")

    def _on_error(self, client, error):
        print(f"[AssemblyAI ERROR] {error}")

    def _on_termination(self, client, event):
        print(f"[AssemblyAI] Session terminated: {event}")

    def connect(self):
        # Start backend session first (only if using backend)
        if self.use_backend:
            self._async_loop.start()
            self.session_id = self._async_loop.submit(self.backend_client.start_session()).result(timeout=10.0)
            print(f"[Backend] Session started: {self.session_id}")
        else:
            # For standalone mode, generate a local session ID
            self.session_id = "standalone"

        self.client.connect(
            StreamingParameters(
                sample_rate=16000,
                speaker_labels=True,
            )
        )

    def stream_audio(self, audio_chunk: bytes):
        self.client.stream(audio_chunk)

    def disconnect(self):
        self.client.disconnect()
        if self.use_backend and self.session_id:
            try:
                self._async_loop.submit(self.backend_client.stop_session(self.session_id)).result(timeout=10.0)
                print(f"[Backend] Session stopped: {self.session_id}")
            except Exception as e:
                print(f"[Backend ERROR] Failed to stop session: {e}")
            finally:
                try:
                    self._async_loop.submit(self.backend_client.close()).result(timeout=5.0)
                except Exception as e:
                    print(f"[Backend ERROR] Failed to close client: {e}")
        # Stop the background event loop
        if self._async_loop is not None:
            self._async_loop.stop()