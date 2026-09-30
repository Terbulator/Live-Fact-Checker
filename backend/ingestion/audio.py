"""Audio ingestion adapter using AssemblyAI for transcription.

Supports MP3, WAV, M4A, and other AssemblyAI-supported audio formats.
"""

import os
import tempfile
import asyncio
from typing import Optional, List, Dict, Any
from pathlib import Path

import assemblyai as aai

from backend.ingestion.models import InputSource, InputType, ProcessingStatus, IngestionError
from backend.config import get_settings


# Supported audio MIME types and extensions
SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/ogg",
    "audio/webm",
    "audio/flac",
}

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac"}

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB


class AudioIngestionError(IngestionError):
    """Raised when audio ingestion fails."""

    def __init__(self, message: str, code: str = "AUDIO_INGESTION_FAILED"):
        super().__init__(message, code)


async def validate_audio_file(filename: str, content_type: str, file_size: int) -> None:
    """Validate uploaded audio file.

    Args:
        filename: Original filename
        content_type: MIME type from upload
        file_size: File size in bytes

    Raises:
        AudioIngestionError: If validation fails
    """
    # Check file size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise AudioIngestionError(
            f"File size {file_size} bytes exceeds maximum of {MAX_FILE_SIZE_BYTES} bytes (100MB)",
            "FILE_TOO_LARGE",
        )

    if file_size == 0:
        raise AudioIngestionError("File is empty", "EMPTY_FILE")

    # Check extension
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise AudioIngestionError(
            f"Unsupported audio format: {ext}. Supported: {', '.join(SUPPORTED_AUDIO_EXTENSIONS)}",
            "UNSUPPORTED_FORMAT",
        )

    # Check MIME type (if provided)
    if content_type and content_type not in SUPPORTED_AUDIO_MIME_TYPES:
        # Allow if extension is valid but MIME is missing/unknown
        if ext not in SUPPORTED_AUDIO_EXTENSIONS:
            raise AudioIngestionError(
                f"Unsupported MIME type: {content_type}",
                "UNSUPPORTED_MIME_TYPE",
            )


async def transcribe_audio_file(file_path: str, api_key: str) -> Dict[str, Any]:
    """Transcribe audio file using AssemblyAI.

    Args:
        file_path: Path to audio file
        api_key: AssemblyAI API key

    Returns:
        Dict with transcript text and segments
    """
    aai.settings.api_key = api_key

    config = aai.TranscriptionConfig(
        speaker_labels=True,
        punctuate=True,
        format_text=True,
    )

    transcriber = aai.Transcriber(config=config)

    # Run transcription in thread pool since AssemblyAI SDK is synchronous
    loop = asyncio.get_event_loop()
    transcript = await loop.run_in_executor(None, transcriber.transcribe, file_path)

    if transcript.status == aai.TranscriptStatus.error:
        raise AudioIngestionError(
            f"Transcription failed: {transcript.error}",
            "TRANSCRIPTION_FAILED",
        )

    # Build segments with speaker info and timestamps
    segments = []
    if transcript.utterances:
        for utterance in transcript.utterances:
            segments.append({
                "speaker": f"Speaker {utterance.speaker}",
                "text": utterance.text,
                "start": utterance.start / 1000.0,  # Convert ms to seconds
                "end": utterance.end / 1000.0,
                "confidence": utterance.confidence,
            })
    else:
        # Fallback: single segment
        segments.append({
            "speaker": "Speaker 1",
            "text": transcript.text,
            "start": 0.0,
            "end": 0.0,
            "confidence": transcript.confidence if transcript.confidence else 1.0,
        })

    return {
        "text": transcript.text,
        "segments": segments,
    }


async def process_audio_upload(
    file_content: bytes,
    filename: str,
    content_type: str,
    session_id: str,
) -> InputSource:
    """Process an uploaded audio file through transcription and return InputSource.

    Args:
        file_content: Raw file bytes
        filename: Original filename
        content_type: MIME type
        session_id: Session ID for tracking

    Returns:
        InputSource with transcript populated
    """
    file_size = len(file_content)

    # Validate
    await validate_audio_file(filename, content_type, file_size)

    # Get settings and API key
    settings = get_settings()
    api_key = settings.assemblyai_api_key
    if not api_key or not api_key.get_secret_value():
        raise AudioIngestionError(
            "AssemblyAI API key not configured on backend",
            "ASSEMBLYAI_NOT_CONFIGURED",
        )

    # Create InputSource for tracking
    source = InputSource(
        type=InputType.AUDIO_UPLOAD,
        filename=filename,
        media_type=content_type,
        status=ProcessingStatus.TRANSCRIBING,
    )

    # Write to temp file for AssemblyAI
    with tempfile.NamedTemporaryFile(
        suffix=Path(filename).suffix, delete=False
    ) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # Transcribe
        result = await transcribe_audio_file(tmp_path, api_key.get_secret_value())

        # Update source with results
        source.transcript = result["text"]
        source.transcript_segments = result["segments"]
        source.status = ProcessingStatus.COMPLETED
        source.duration_seconds = max(
            (seg.get("end", 0) for seg in result["segments"]), default=0
        )

        return source

    except AudioIngestionError:
        source.status = ProcessingStatus.FAILED
        raise
    except Exception as e:
        source.status = ProcessingStatus.FAILED
        source.error = str(e)
        raise AudioIngestionError(f"Audio processing failed: {e}", "PROCESSING_ERROR")
    finally:
        # Cleanup temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass