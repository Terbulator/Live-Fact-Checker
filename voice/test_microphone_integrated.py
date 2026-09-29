"""Backend-integrated microphone test.

This test requires a running FastAPI backend at http://127.0.0.1:8000.

Run with:
    python -m voice.test_microphone_integrated

The test will:
1. Connect to AssemblyAI Realtime STT
2. Call POST /session/start on the backend
3. Stream microphone audio to AssemblyAI
4. Send transcript events to POST /events/transcript with backend sessionId
"""

import time

from dotenv import load_dotenv

from voice.assemblyai_client import AssemblyAIClient

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


def main():
    # Use default backend URL (http://127.0.0.1:8000) with use_backend=True
    client = AssemblyAIClient(on_transcript=on_transcript, use_backend=True)

    try:
        client.connect()

        print("\n=== BACKEND-INTEGRATED MICROPHONE TEST STARTED ===")
        print("Backend: http://127.0.0.1:8000")
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