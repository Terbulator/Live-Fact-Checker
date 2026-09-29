"""Backend-integrated microphone test.

This test requires a running FastAPI backend at http://127.0.0.1:8000.

Run with a fresh backend-owned session:
    python -m voice.test_microphone_integrated

Or join the session the browser dashboard is already showing, so live speech
appears in the UI (this is the demo path):
    python -m voice.test_microphone_integrated --session-id session_002
    BACKEND_SESSION_ID=session_002 python -m voice.test_microphone_integrated

The test will:
1. Connect to AssemblyAI Realtime STT
2. Join (or create) a backend session
3. Stream microphone audio to AssemblyAI
4. Send transcript events to POST /events/transcript for that session

The AssemblyAI key is read from the environment and is never printed or sent to
the browser.
"""

import argparse
import os

from dotenv import load_dotenv

from voice.assemblyai_client import AssemblyAIClient
from voice.backend_client import BackendSessionNotFound

load_dotenv()


def on_transcript(event):
    print(f"\n=== TRANSCRIPT EVENT ===")
    print(f"  SessionId: {event['sessionId']}")
    print(f"  Speaker: {event['speaker']}")
    print(f"  Text: {event['text']}")
    print(f"  Timestamp: {event['timestamp']}s")
    print(f"  isFinal: {event['isFinal']}")
    print(f"  Type: {event['type']}")
    print(f"========================\n")


def resolve_session_id() -> str | None:
    """Session id from --session-id, else BACKEND_SESSION_ID, else None."""
    parser = argparse.ArgumentParser(
        description="Stream microphone audio into the Live Fact-Checker backend."
    )
    parser.add_argument(
        "--session-id",
        default=os.getenv("BACKEND_SESSION_ID"),
        help="Join this existing backend session instead of creating a new one.",
    )
    args = parser.parse_args()
    return args.session_id or None


def main():
    session_id = resolve_session_id()

    # Use default backend URL (http://127.0.0.1:8000) with use_backend=True
    client = AssemblyAIClient(
        on_transcript=on_transcript, use_backend=True, session_id=session_id
    )

    try:
        client.connect()
    except BackendSessionNotFound as exc:
        print(f"\nCannot start: {exc}")
        return

    try:
        print("\n=== BACKEND-INTEGRATED MICROPHONE TEST STARTED ===")
        print("Backend: http://127.0.0.1:8000")
        if session_id is not None:
            print(f"Joined session: {client.session_id} (created by the browser)")
            print("Live speech will appear in the dashboard.")
        else:
            print(f"Created a new session: {client.session_id}")
            print("Tip: start a session in the browser and pass --session-id to share it.")
        print("Speak into your microphone.")
        print("Press Ctrl+C to stop.\n")

        import pyaudio

        audio = pyaudio.PyAudio()

        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=1024,
        )

        while True:
            audio_chunk = stream.read(
                1024,
                exception_on_overflow=False,
            )

            client.stream_audio(audio_chunk)

    except KeyboardInterrupt:
        print("\nStopping...")

    finally:
        try:
            stream.stop_stream()
            stream.close()
            audio.terminate()
        except Exception:
            pass

        client.disconnect()
        print("AssemblyAI disconnected.")


if __name__ == "__main__":
    main()