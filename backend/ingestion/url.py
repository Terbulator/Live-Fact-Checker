"""Video URL ingestion adapter.

Supports:
- Direct video file URLs (MP4, WebM, etc.)
- YouTube URLs (via yt-dlp if available)

Note: Only processes publicly accessible URLs. Does not bypass authentication,
paywalls, or platform protections.
"""

import os
import tempfile
import asyncio
import subprocess
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import httpx

from backend.ingestion.models import InputSource, InputType, ProcessingStatus, IngestionError
from backend.ingestion.audio import transcribe_audio_file
from backend.ingestion.video import extract_audio_from_video, get_media_duration
from backend.config import get_settings


# Supported URL patterns
YOUTUBE_URL_PATTERNS = [
    r"^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+",
    r"^https?://youtu\.be/[\w-]+",
    r"^https?://(?:www\.)?youtube\.com/shorts/[\w-]+",
]

DIRECT_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}

MAX_DOWNLOAD_SIZE_BYTES = 500 * 1024 * 1024  # 500MB
DOWNLOAD_TIMEOUT_SECONDS = 300


class URLError(IngestionError):
    """Raised when URL ingestion fails."""

    def __init__(self, message: str, code: str = "URL_INGESTION_FAILED"):
        super().__init__(message, code)


def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube URL."""
    for pattern in YOUTUBE_URL_PATTERNS:
        if re.match(pattern, url):
            return True
    return False


def is_direct_video_url(url: str) -> bool:
    """Check if URL appears to be a direct video file link."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in DIRECT_VIDEO_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def is_supported_url(url: str) -> bool:
    """Check if URL is supported for ingestion."""
    return is_youtube_url(url) or is_direct_video_url(url)


async def validate_url(url: str) -> None:
    """Validate URL before processing.

    Args:
        url: URL to validate

    Raises:
        URLError: If URL is not supported or accessible
    """
    if not is_supported_url(url):
        raise URLError(
            "Unsupported URL. Supported: YouTube video URLs and direct video file links (.mp4, .webm, .mov, .mkv, .avi)",
            "UNSUPPORTED_URL",
        )

    # Quick HEAD request to check accessibility (for direct URLs)
    if is_direct_video_url(url):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.head(url)
                if resp.status_code >= 400:
                    raise URLError(
                        f"URL returned HTTP {resp.status_code}",
                        "URL_NOT_ACCESSIBLE",
                    )
                # Check content length
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > MAX_DOWNLOAD_SIZE_BYTES:
                    raise URLError(
                        f"Video file too large: {content_length} bytes (max {MAX_DOWNLOAD_SIZE_BYTES})",
                        "FILE_TOO_LARGE",
                    )
        except httpx.TimeoutException:
            raise URLError("URL request timed out", "URL_TIMEOUT")
        except URLError:
            raise
        except Exception as e:
            # Don't fail on HEAD errors - some servers don't support it
            pass


async def download_video_url(url: str, output_path: str) -> int:
    """Download video from URL to local file.

    Args:
        url: Video URL
        output_path: Path to save downloaded file

    Returns:
        File size in bytes
    """
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total = 0
            with open(output_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_SIZE_BYTES:
                        raise URLError(
                            f"Download exceeded max size {MAX_DOWNLOAD_SIZE_BYTES}",
                            "FILE_TOO_LARGE",
                        )
    return total


async def download_youtube_video(url: str, output_path: str) -> int:
    """Download YouTube video using yt-dlp.

    Args:
        url: YouTube URL
        output_path: Path to save downloaded file (without extension)

    Returns:
        File size in bytes
    """
    # Check if yt-dlp is available
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise URLError(
            "yt-dlp not installed. Install with: pip install yt-dlp",
            "YT_DLP_NOT_FOUND",
        )

    # Use yt-dlp to download best audio/video
    cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio/best",  # Prefer audio-only for transcription
        "-o", output_path + ".%(ext)s",
        "--no-playlist",
        "--max-filesize", str(MAX_DOWNLOAD_SIZE_BYTES),
        url,
    ]

    loop = asyncio.get_event_loop()
    try:
        proc = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        )
    except subprocess.TimeoutExpired:
        raise URLError("YouTube download timed out", "DOWNLOAD_TIMEOUT")

    if proc.returncode != 0:
        raise URLError(
            f"yt-dlp failed: {proc.stderr}",
            "DOWNLOAD_FAILED",
        )

    # Find the downloaded file
    for ext in [".m4a", ".webm", ".mp4", ".opus"]:
        test_path = output_path + ext
        if os.path.exists(test_path):
            return os.path.getsize(test_path)

    raise URLError("Downloaded file not found", "DOWNLOAD_FAILED")


async def process_video_url(
    url: str,
    session_id: str,
) -> InputSource:
    """Process a video URL: download, extract audio, transcribe.

    Args:
        url: Video URL
        session_id: Session ID for tracking

    Returns:
        InputSource with transcript populated
    """
    # Validate URL
    await validate_url(url)

    # Get settings and API key
    settings = get_settings()
    api_key = settings.assemblyai_api_key
    if not api_key or not api_key.get_secret_value():
        raise URLError(
            "AssemblyAI API key not configured on backend",
            "ASSEMBLYAI_NOT_CONFIGURED",
        )

    # Create InputSource for tracking
    source = InputSource(
        type=InputType.VIDEO_URL,
        url=url,
        status=ProcessingStatus.PENDING,
    )

    # Determine download method
    is_youtube = is_youtube_url(url)

    with tempfile.TemporaryDirectory() as tmpdir:
        if is_youtube:
            source.status = ProcessingStatus.EXTRACTING_AUDIO
            # yt-dlp can extract audio directly
            audio_path = os.path.join(tmpdir, "audio")
            file_size = await download_youtube_video(url, audio_path)

            # Find the actual downloaded file
            downloaded_file = None
            for ext in [".m4a", ".webm", ".mp4", ".opus"]:
                test_path = audio_path + ext
                if os.path.exists(test_path):
                    downloaded_file = test_path
                    break

            if not downloaded_file:
                raise URLError("YouTube download produced no file", "DOWNLOAD_FAILED")

            # If it's already audio, transcribe directly; else extract audio
            if downloaded_file.endswith((".m4a", ".opus")):
                # Convert to WAV for AssemblyAI
                wav_path = os.path.join(tmpdir, "audio.wav")
                await extract_audio_from_video(downloaded_file, wav_path)
                audio_to_transcribe = wav_path
            else:
                # Video file - extract audio
                wav_path = os.path.join(tmpdir, "audio.wav")
                await extract_audio_from_video(downloaded_file, wav_path)
                audio_to_transcribe = wav_path

        else:
            # Direct video URL
            source.status = ProcessingStatus.EXTRACTING_AUDIO
            video_path = os.path.join(tmpdir, "video.mp4")
            file_size = await download_video_url(url, video_path)

            # Extract audio
            wav_path = os.path.join(tmpdir, "audio.wav")
            duration = await extract_audio_from_video(video_path, wav_path)
            source.duration_seconds = duration
            audio_to_transcribe = wav_path

        # Transcribe
        source.status = ProcessingStatus.TRANSCRIBING
        result = await transcribe_audio_file(audio_to_transcribe, api_key.get_secret_value())

        # Update source with results
        source.transcript = result["text"]
        source.transcript_segments = result["segments"]
        source.status = ProcessingStatus.COMPLETED

        return source