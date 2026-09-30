"""Video ingestion adapter with audio extraction using ffmpeg.

Supports MP4, MOV, WebM and other ffmpeg-supported video formats.
Extracts audio and delegates to audio transcription.
"""

import os
import tempfile
import asyncio
import subprocess
from typing import Optional, List, Dict, Any
from pathlib import Path

from backend.ingestion.models import InputSource, InputType, ProcessingStatus, IngestionError
from backend.ingestion.audio import transcribe_audio_file
from backend.config import get_settings


# Supported video MIME types and extensions
SUPPORTED_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    "video/x-webm",
}

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500MB


class VideoIngestionError(IngestionError):
    """Raised when video ingestion fails."""

    def __init__(self, message: str, code: str = "VIDEO_INGESTION_FAILED"):
        super().__init__(message, code)


async def validate_video_file(filename: str, content_type: str, file_size: int) -> None:
    """Validate uploaded video file.

    Args:
        filename: Original filename
        content_type: MIME type from upload
        file_size: File size in bytes

    Raises:
        VideoIngestionError: If validation fails
    """
    if file_size > MAX_FILE_SIZE_BYTES:
        raise VideoIngestionError(
            f"File size {file_size} bytes exceeds maximum of {MAX_FILE_SIZE_BYTES} bytes (500MB)",
            "FILE_TOO_LARGE",
        )

    if file_size == 0:
        raise VideoIngestionError("File is empty", "EMPTY_FILE")

    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_VIDEO_EXTENSIONS:
        raise VideoIngestionError(
            f"Unsupported video format: {ext}. Supported: {', '.join(SUPPORTED_VIDEO_EXTENSIONS)}",
            "UNSUPPORTED_FORMAT",
        )

    if content_type and content_type not in SUPPORTED_VIDEO_MIME_TYPES:
        if ext not in SUPPORTED_VIDEO_EXTENSIONS:
            raise VideoIngestionError(
                f"Unsupported MIME type: {content_type}",
                "UNSUPPORTED_MIME_TYPE",
            )


async def extract_audio_from_video(video_path: str, output_path: str) -> float:
    """Extract audio from video file using ffmpeg.

    Args:
        video_path: Path to input video file
        output_path: Path for output audio file (WAV format)

    Returns:
        Duration of extracted audio in seconds
    """
    # Use ffmpeg to extract audio as WAV (16kHz, mono for AssemblyAI compatibility)
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", video_path,
        "-vn",  # No video
        "-acodec", "pcm_s16le",  # PCM 16-bit little-endian
        "-ar", "16000",  # 16kHz sample rate
        "-ac", "1",  # Mono
        output_path,
    ]

    loop = asyncio.get_event_loop()
    try:
        proc = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        )
    except subprocess.TimeoutExpired:
        raise VideoIngestionError("Audio extraction timed out (5 min)", "EXTRACTION_TIMEOUT")
    except FileNotFoundError:
        raise VideoIngestionError(
            "ffmpeg not found. Please install ffmpeg to process video files.",
            "FFMPEG_NOT_FOUND",
        )

    if proc.returncode != 0:
        raise VideoIngestionError(
            f"ffmpeg failed: {proc.stderr}",
            "EXTRACTION_FAILED",
        )

    # Get duration using ffprobe
    duration = await get_media_duration(output_path)
    return duration


async def get_media_duration(file_path: str) -> float:
    """Get media duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]

    loop = asyncio.get_event_loop()
    try:
        proc = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        )
    except FileNotFoundError:
        return 0.0

    if proc.returncode == 0 and proc.stdout.strip():
        try:
            return float(proc.stdout.strip())
        except ValueError:
            pass
    return 0.0


async def process_video_upload(
    file_content: bytes,
    filename: str,
    content_type: str,
    session_id: str,
) -> InputSource:
    """Process an uploaded video file: extract audio, transcribe, return InputSource.

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
    await validate_video_file(filename, content_type, file_size)

    # Get settings and API key
    settings = get_settings()
    api_key = settings.assemblyai_api_key
    if not api_key or not api_key.get_secret_value():
        raise VideoIngestionError(
            "AssemblyAI API key not configured on backend",
            "ASSEMBLYAI_NOT_CONFIGURED",
        )

    # Create InputSource for tracking
    source = InputSource(
        type=InputType.VIDEO_UPLOAD,
        filename=filename,
        media_type=content_type,
        status=ProcessingStatus.EXTRACTING_AUDIO,
    )

    # Write video to temp file
    video_suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=video_suffix, delete=False) as tmp:
        tmp.write(file_content)
        video_path = tmp.name

    # Extract audio to temp WAV file
    audio_path = video_path + ".wav"

    try:
        # Extract audio
        duration = await extract_audio_from_video(video_path, audio_path)
        source.duration_seconds = duration
        source.status = ProcessingStatus.TRANSCRIBING

        # Transcribe extracted audio
        result = await transcribe_audio_file(audio_path, api_key.get_secret_value())

        # Update source with results
        source.transcript = result["text"]
        source.transcript_segments = result["segments"]
        source.status = ProcessingStatus.COMPLETED

        return source

    except VideoIngestionError:
        source.status = ProcessingStatus.FAILED
        raise
    except Exception as e:
        source.status = ProcessingStatus.FAILED
        source.error = str(e)
        raise VideoIngestionError(f"Video processing failed: {e}", "PROCESSING_ERROR")
    finally:
        # Cleanup temp files
        for path in [video_path, audio_path]:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass