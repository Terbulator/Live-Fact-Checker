"""Video URL ingestion adapter.

Supports:
- Direct video file URLs (MP4, WebM, etc.)
- YouTube URLs (via yt-dlp if available)

Note: Only processes publicly accessible URLs. Does not bypass authentication,
paywalls, or platform protections.
"""

import os
import sys
import tempfile
import asyncio
import subprocess
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import httpx

from backend.ingestion.models import InputSource, InputType, ProcessingStatus, IngestionError
from backend.ingestion.audio import transcribe_audio_file
from backend.ingestion.video import extract_audio_from_video, get_media_duration
from backend.ingestion.deno_runtime import DenoRuntimeUnavailable, ensure_deno_runtime
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


def _ytdlp_cmd() -> List[str]:
    """Invoke yt-dlp through this interpreter.

    The bare ``yt-dlp`` console script only resolves if its install directory is
    on PATH, which is true for a shell-activated venv but not guaranteed for a
    service manager. ``python -m yt_dlp`` always uses the yt-dlp that was
    installed alongside the running interpreter.
    """
    return [sys.executable, "-m", "yt_dlp"]


async def download_youtube_video(url: str, output_path: str) -> int:
    """Download YouTube audio using yt-dlp.

    yt-dlp needs a JavaScript runtime to solve YouTube's challenge scripts, and
    EJS components are disallowed by default, so both are enabled explicitly.
    The runtime path is resolved by ``ensure_deno_runtime`` (preinstalled binary
    if the image provides one, otherwise the pinned official release).

    Args:
        url: YouTube URL
        output_path: Path to save downloaded file (without extension)

    Returns:
        File size in bytes

    Raises:
        URLError: if yt-dlp is missing, the runtime is unavailable, or YouTube
            refuses to serve the video.
    """
    try:
        deno_path = await ensure_deno_runtime()
    except DenoRuntimeUnavailable as exc:
        raise URLError(str(exc), "YT_DLP_RUNTIME_UNAVAILABLE")

    ytdlp = _ytdlp_cmd()
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ytdlp + ["--version"], capture_output=True, check=True, text=True
            ),
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise URLError(
            "yt-dlp not installed. Install with: pip install yt-dlp",
            "YT_DLP_NOT_FOUND",
        )

    cmd = ytdlp + [
        # yt-dlp 2026.08.x: Deno is the highest-priority runtime, and remote
        # components are disallowed unless named, so EJS solving is opt-in.
        "--js-runtimes", f"deno:{deno_path}",
        "--remote-components", "ejs:github",
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
        raise _ytdlp_failure(proc.stderr)

    downloaded = _find_downloaded_file(output_path)
    if downloaded is None:
        raise URLError("Downloaded file not found", "DOWNLOAD_FAILED")
    return os.path.getsize(downloaded)


def _find_downloaded_file(output_path: str) -> Optional[str]:
    """Locate the file yt-dlp wrote for ``output_path``.

    Prefers the audio formats we can hand straight to AssemblyAI, then falls
    back to whatever single file yt-dlp left in the directory, so a format
    change upstream cannot turn a successful download into a 400.
    """
    for ext in (".m4a", ".webm", ".mp4", ".opus"):
        candidate = output_path + ext
        if os.path.exists(candidate):
            return candidate

    parent = os.path.dirname(output_path) or "."
    try:
        leftovers = [p for p in Path(parent).iterdir() if p.is_file()]
    except OSError:
        return None
    return str(leftovers[0]) if len(leftovers) == 1 else None


# Each entry is (substring, code, user message).
#
# Order matters. "Sign in to confirm your age" and "Join this channel to get
# access" are more specific than the bot check, and the age message literally
# contains "sign in to confirm", so the generic entry has to come last.
_YTDLP_FAILURES = (
    (
        "confirm your age",
        "YOUTUBE_AGE_RESTRICTED",
        "This YouTube video is age-restricted and cannot be fetched without "
        "signing in, which we do not do. Try a different video.",
    ),
    (
        "members-only",
        "YOUTUBE_MEMBERS_ONLY",
        "This YouTube video is members-only, so it cannot be fetched. Try a "
        "different video.",
    ),
    (
        "join this channel",
        "YOUTUBE_MEMBERS_ONLY",
        "This YouTube video is members-only, so it cannot be fetched. Try a "
        "different video.",
    ),
    (
        "private video",
        "YOUTUBE_PRIVATE",
        "This YouTube video is private, so it cannot be fetched. Ask the "
        "uploader to make it public.",
    ),
    (
        "video unavailable",
        "YOUTUBE_UNAVAILABLE",
        "This YouTube video is unavailable. It may have been removed or is "
        "blocked in this region.",
    ),
    (
        "is not a valid url",
        "YOUTUBE_BAD_URL",
        "That does not look like a valid YouTube URL.",
    ),
    (
        "sign in to confirm",
        "YOUTUBE_BOT_CHECK",
        "YouTube would not serve this video to our server because it wants to "
        "verify we are not a bot. This is a YouTube access restriction, not a "
        "problem with the video, and we cannot sign in or bypass it. Try a "
        "different video, or upload the audio/video file directly.",
    ),
    (
        "confirm you are not a bot",
        "YOUTUBE_BOT_CHECK",
        "YouTube would not serve this video because it wants to verify we are "
        "not a bot. We cannot sign in or bypass that check. Try a different "
        "video, or upload the audio/video file directly.",
    ),
)


def _ytdlp_failure(stderr: Optional[str]) -> URLError:
    """Turn yt-dlp's raw stderr into a short, user-facing ingestion error.

    yt-dlp's stderr carries multi-line banners (deprecation warnings, JS runtime
    notices) that mean nothing to a user, so only the trailing ``ERROR:`` line
    is surfaced.
    """
    text = (stderr or "").strip()
    lowered = text.lower()

    for marker, code, message in _YTDLP_FAILURES:
        if marker in lowered:
            return URLError(message, code)

    detail = ""
    for line in reversed(text.splitlines()):
        if line.strip().lower().startswith("error"):
            detail = line.strip()
            break
    if not detail:
        detail = text.splitlines()[-1].strip() if text else "no output"

    return URLError(
        f"YouTube download failed: {detail[:300]}",
        "YOUTUBE_DOWNLOAD_FAILED",
    )



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

            # download_youtube_video already resolved the file, but locate it
            # again for the transcode step.
            downloaded_file = _find_downloaded_file(audio_path)
            if not downloaded_file:
                raise URLError("YouTube download produced no file", "DOWNLOAD_FAILED")

            # Convert to WAV for AssemblyAI, whether the download arrived as
            # audio or as a video container.
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