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
    client = AssemblyAIClient(on_transcript=on_transcript, use_backend=False)

    try:
        client.connect()

        print("\n=== MICROPHONE TEST STARTED ===")
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