"""YouTube ingestion: the Deno runtime, the yt-dlp command, and error surfacing.

The production failure this covers was::

    WARNING: [youtube] No supported JavaScript runtime could be found.
    ERROR: [youtube] <id>: Sign in to confirm you're not a bot.

Two separate things, and only one of them is fixable in code:

* the missing JS runtime - yt-dlp needs Deno to solve YouTube's challenge
  scripts, and the pip wheel ships no runtime binary, so the container had none;
* the bot check - YouTube demanding proof of a human. We do not and must not
  bypass that, so it becomes a clear, honest user-facing error.

yt-dlp is stubbed in these tests. Nothing here contacts YouTube, and no test
invents a transcript, claim, verdict or source.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, List, Optional

import httpx
import pytest

from backend.ingestion import url as url_mod
from backend.ingestion.deno_runtime import (
    DENO_VERSION,
    DenoRuntimeUnavailable,
    ensure_deno_runtime,
)
from backend.ingestion.url import URLError

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture()
def assemblyai_key(monkeypatch):
    """Satisfy the real credential guard in process_video_url.

    Mirrors ``stub_assemblyai`` in test_ingestion_routes.py: a real Settings
    instance so the guard still runs.
    """
    from backend.config import Settings

    settings = Settings(
        environment="test",
        use_mock_engines=True,
        assemblyai_api_key="test-assemblyai-key",
    )
    monkeypatch.setattr(url_mod, "get_settings", lambda: settings)
    return settings


# ---------------------------------------------------------------------------
# Deno runtime resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_override_is_returned(monkeypatch, tmp_path):
    fake = tmp_path / "deno"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("YTDLP_DENO_PATH", str(fake))

    assert await ensure_deno_runtime() == str(fake)


@pytest.mark.asyncio
async def test_missing_env_override_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_DENO_PATH", str(tmp_path / "absent"))

    with pytest.raises(DenoRuntimeUnavailable) as exc:
        await ensure_deno_runtime()
    assert "does not exist" in str(exc.value)


@pytest.mark.asyncio
async def test_deno_on_path_is_preferred(monkeypatch, tmp_path):
    """An image that installs Deno itself needs no download."""
    import backend.ingestion.deno_runtime as deno_mod

    fake = tmp_path / "deno"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.delenv("YTDLP_DENO_PATH", raising=False)
    monkeypatch.setattr(deno_mod.shutil, "which", lambda _: str(fake))

    assert await ensure_deno_runtime() == str(fake)


@pytest.mark.asyncio
async def test_cached_binary_is_reused_without_download(monkeypatch, tmp_path):
    """A warm cache directory must not trigger a network fetch."""
    import backend.ingestion.deno_runtime as deno_mod

    monkeypatch.delenv("YTDLP_DENO_PATH", raising=False)
    monkeypatch.setenv("YTDLP_DENO_DIR", str(tmp_path))
    monkeypatch.setattr(deno_mod.shutil, "which", lambda _: None)

    cached = tmp_path / deno_mod._binary_name()
    cached.write_text("#!/bin/sh\n")

    def _explode(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("cached Deno must not be re-downloaded")

    monkeypatch.setattr(deno_mod.httpx.AsyncClient, "stream", _explode)

    assert await ensure_deno_runtime() == str(cached)


@pytest.mark.asyncio
async def test_install_disabled_raises_actionable_error(monkeypatch, tmp_path):
    """In a locked-down deployment, fail with guidance rather than download."""
    import backend.ingestion.deno_runtime as deno_mod

    monkeypatch.delenv("YTDLP_DENO_PATH", raising=False)
    monkeypatch.setenv("YTDLP_DENO_DIR", str(tmp_path))
    monkeypatch.setenv("YTDLP_DENO_INSTALL", "0")
    monkeypatch.setattr(deno_mod.shutil, "which", lambda _: None)

    with pytest.raises(DenoRuntimeUnavailable) as exc:
        await ensure_deno_runtime()
    assert "YTDLP_DENO_PATH" in str(exc.value)


@pytest.mark.asyncio
async def test_install_verifies_checksum_and_unpacks_atomically(monkeypatch, tmp_path):
    """The pinned release is sha256-verified and lands as one complete binary."""
    import backend.ingestion.deno_runtime as deno_mod

    payload = b"#!/bin/sh\necho deno\n"
    archive_bytes = _zip_bytes(deno_mod._binary_name(), payload)

    monkeypatch.delenv("YTDLP_DENO_PATH", raising=False)
    monkeypatch.setenv("YTDLP_DENO_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(deno_mod.shutil, "which", lambda _: None)

    seen: dict = {}

    digest = deno_mod.hashlib.sha256(archive_bytes).hexdigest()

    async def _fake_get(self, url, *args, **kwargs):
        seen["sha_url"] = str(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, text=f"{digest}  deno.zip\n", request=request)

    def _fake_stream(self, url, *args, **kwargs):
        # httpx's stream() receives the method first, then the url.
        seen["zip_url"] = str(args[0] if args else url)

        class _Ctx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            def raise_for_status(self):
                return None

            def aiter_bytes(self, _size):
                async def _gen():
                    yield archive_bytes

                return _gen()

        return _Ctx()

    monkeypatch.setattr(deno_mod.httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(deno_mod.httpx.AsyncClient, "stream", _fake_stream)

    resolved = await ensure_deno_runtime()

    assert resolved == str(tmp_path / "cache" / deno_mod._binary_name())
    assert Path(resolved).read_bytes() == payload
    assert f"v{DENO_VERSION}" in seen["sha_url"]
    # Release assets, not the GitHub API, so no token or rate limit is needed.
    assert seen["zip_url"] == (
        "https://github.com/denoland/deno/releases/download/"
        f"v{DENO_VERSION}/deno-{deno_mod._target()}.zip"
    )
    # No staging directory or partial archive left behind.
    assert list((tmp_path / "cache").iterdir()) == [Path(resolved)]


@pytest.mark.asyncio
async def test_checksum_mismatch_aborts_install(monkeypatch, tmp_path):
    """A tampered or truncated download must never be installed."""
    import backend.ingestion.deno_runtime as deno_mod

    archive_bytes = _zip_bytes(deno_mod._binary_name(), b"#!/bin/sh\necho deno\n")
    cache = tmp_path / "cache"

    monkeypatch.delenv("YTDLP_DENO_PATH", raising=False)
    monkeypatch.setenv("YTDLP_DENO_DIR", str(cache))
    monkeypatch.setattr(deno_mod.shutil, "which", lambda _: None)

    async def _fake_get(self, url, *args, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(200, text="0" * 64 + "  deno.zip\n", request=request)


@pytest.mark.asyncio
async def test_checksum_mismatch_aborts_install(monkeypatch, tmp_path):
    """A tampered or truncated download must never be installed."""
    import backend.ingestion.deno_runtime as deno_mod

    archive_bytes = _zip_bytes(deno_mod._binary_name(), b"#!/bin/sh\necho deno\n")
    cache = tmp_path / "cache"

    monkeypatch.delenv("YTDLP_DENO_PATH", raising=False)
    monkeypatch.setenv("YTDLP_DENO_DIR", str(cache))
    monkeypatch.setattr(deno_mod.shutil, "which", lambda _: None)

    async def _fake_get(self, url, *args, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(200, text="0" * 64 + "  deno.zip\n", request=request)
    """Windows publishes a multi-line block; Linux/macOS a standard sum line."""
    import backend.ingestion.deno_runtime as deno_mod

    digest = "a0c3101b4158d1dfb7d6a78a7bf0f3de80c96bb423c152beec8beb22786f2238"

    standard = f"{digest}  deno-x86_64-unknown-linux-gnu.zip\n"
    windows_block = (
        f"algorithm: SHA256\r\nHash: {digest.upper()}\r\n"
        "Path: C:\\deno\\deno\\target\\release\\deno-x86_64-pc-windows-msvc.zip\r\n\r\n"
    )

    assert deno_mod._parse_sha256(standard) == digest
    assert deno_mod._parse_sha256(windows_block) == digest

    with pytest.raises(deno_mod.DenoRuntimeUnavailable):
        deno_mod._parse_sha256("no digest here")

    def _fake_stream(self, url, *args, **kwargs):
        class _Ctx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            def raise_for_status(self):
                return None

            def aiter_bytes(self, _size):
                async def _gen():
                    yield archive_bytes

                return _gen()

        return _Ctx()

    monkeypatch.setattr(deno_mod.httpx.AsyncClient, "get", _fake_get)
    monkeypatch.setattr(deno_mod.httpx.AsyncClient, "stream", _fake_stream)

    with pytest.raises(DenoRuntimeUnavailable) as exc:
        await ensure_deno_runtime()
    assert "checksum mismatch" in str(exc.value)
    assert not (cache / deno_mod._binary_name()).exists()


def _zip_bytes(name: str, payload: bytes) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, payload)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# The yt-dlp command
# ---------------------------------------------------------------------------


def _run_download(monkeypatch, tmp_path, *, returncode=0, stderr="", write_file=None):
    """Drive download_youtube_video with a stubbed yt-dlp and runtime."""
    deno = tmp_path / "deno"
    deno.write_text("#!/bin/sh\n")

    recorded: dict = {}

    async def _fake_runtime():
        return str(deno)

    monkeypatch.setattr(url_mod, "ensure_deno_runtime", _fake_runtime)

    def _fake_run(cmd, **kwargs):
        recorded["cmd"] = list(cmd)
        if write_file is not None and cmd[-1] == YOUTUBE_URL:
            Path(write_file).write_bytes(b"audio-bytes")
        return subprocess.CompletedProcess(
            cmd, returncode, stdout="", stderr=stderr
        )

    monkeypatch.setattr(url_mod.subprocess, "run", _fake_run)
    return recorded


@pytest.mark.asyncio
async def test_command_enables_deno_and_ejs(monkeypatch, tmp_path):
    """The regression guard: JS runtime and EJS components are both requested."""
    out = tmp_path / "audio.m4a"
    recorded = _run_download(monkeypatch, tmp_path, write_file=out)

    size = await url_mod.download_youtube_video(YOUTUBE_URL, str(tmp_path / "audio"))

    cmd = recorded["cmd"]
    assert size == len(b"audio-bytes")

    # Deno is requested by explicit path so a PATH-less service still resolves it.
    assert "--js-runtimes" in cmd
    runtime = cmd[cmd.index("--js-runtimes") + 1]
    assert runtime == f"deno:{tmp_path / 'deno'}"

    # Remote components are disallowed by default, so EJS needs opting in.
    assert "--remote-components" in cmd
    assert cmd[cmd.index("--remote-components") + 1] == "ejs:github"

    # Previously-working flags must survive.
    assert "--no-playlist" in cmd
    assert cmd[-1] == YOUTUBE_URL


@pytest.mark.asyncio
async def test_command_runs_through_the_running_interpreter(monkeypatch, tmp_path):
    """`python -m yt_dlp`, not a bare console script that needs PATH."""
    out = tmp_path / "audio.m4a"
    recorded = _run_download(monkeypatch, tmp_path, write_file=out)

    await url_mod.download_youtube_video(YOUTUBE_URL, str(tmp_path / "audio"))

    assert recorded["cmd"][:3] == [sys.executable, "-m", "yt_dlp"]


@pytest.mark.asyncio
async def test_no_obsolete_youtube_extractor_flags(monkeypatch, tmp_path):
    """Legacy client/extractor hacks must not reappear."""
    out = tmp_path / "audio.m4a"
    recorded = _run_download(monkeypatch, tmp_path, write_file=out)

    await url_mod.download_youtube_video(YOUTUBE_URL, str(tmp_path / "audio"))

    joined = " ".join(recorded["cmd"])
    for banned in (
        "extractor-args",
        "youtube:player_client",
        "youtube:player_skip",
        "prefer-insecure",
        "cookies",
        "cookies-from-browser",
        "age_limit",
    ):
        assert banned not in joined, f"obsolete/bypassing flag present: {banned}"


@pytest.mark.asyncio
async def test_missing_runtime_surfaces_clean_error(monkeypatch, tmp_path):
    """A missing Deno binary becomes an actionable ingestion error."""
    async def _boom():
        raise DenoRuntimeUnavailable("Deno runtime unavailable (test)")

    monkeypatch.setattr(url_mod, "ensure_deno_runtime", _boom)

    with pytest.raises(URLError) as exc:
        await url_mod.download_youtube_video(YOUTUBE_URL, str(tmp_path / "audio"))
    assert exc.value.code == "YT_DLP_RUNTIME_UNAVAILABLE"


@pytest.mark.asyncio
async def test_yt_dlp_not_installed_reports_clearly(monkeypatch, tmp_path):
    async def _runtime():
        return str(tmp_path / "deno")

    monkeypatch.setattr(url_mod, "ensure_deno_runtime", _runtime)

    def _raise(cmd, **kwargs):
        raise FileNotFoundError("yt-dlp")

    monkeypatch.setattr(url_mod.subprocess, "run", _raise)

    with pytest.raises(URLError) as exc:
        await url_mod.download_youtube_video(YOUTUBE_URL, str(tmp_path / "audio"))
    assert exc.value.code == "YT_DLP_NOT_FOUND"


@pytest.mark.asyncio
async def test_timeout_is_reported(monkeypatch, tmp_path):
    """Only the download may time out; the --version probe must succeed first."""

    async def _runtime():
        return str(tmp_path / "deno")

    monkeypatch.setattr(url_mod, "ensure_deno_runtime", _runtime)

    def _fake_run(cmd, **kwargs):
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="2026.08.19", stderr="")
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(url_mod.subprocess, "run", _fake_run)

    with pytest.raises(URLError) as exc:
        await url_mod.download_youtube_video(YOUTUBE_URL, str(tmp_path / "audio"))
    assert exc.value.code == "DOWNLOAD_TIMEOUT"


# ---------------------------------------------------------------------------
# Failure surfacing
# ---------------------------------------------------------------------------


def test_bot_check_becomes_a_clear_user_facing_error():
    """The exact production error must not leak yt-dlp's raw banner."""
    stderr = (
        "WARNING: [youtube] No supported JavaScript runtime could be found.\n"
        "Only deno is enabled by default.\n"
        "YouTube extraction without a JS runtime has been deprecated.\n"
        "ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you're not a bot. "
        "(Use --cookies-from-browser or --cookies for the authentication)\n"
    )

    err = url_mod._ytdlp_failure(stderr)

    assert err.code == "YOUTUBE_BOT_CHECK"
    assert "not a bot" in err.message
    # No internal scaffolding and no bypass hint in the user-facing text.
    assert "yt-dlp" not in err.message
    assert "--cookies" not in err.message
    assert "WARNING" not in err.message
    assert "JS runtime" not in err.message


@pytest.mark.parametrize(
    "stderr,code",
    [
        ("ERROR: [youtube] x: Private video. This video is private.", "YOUTUBE_PRIVATE"),
        ("ERROR: [youtube] x: Join this channel to get access", "YOUTUBE_MEMBERS_ONLY"),
        ("ERROR: [youtube] x: Video unavailable. This video has been removed", "YOUTUBE_UNAVAILABLE"),
        ("ERROR: [youtube] x: Sign in to confirm your age", "YOUTUBE_AGE_RESTRICTED"),
    ],
)
def test_access_failures_are_classified(stderr, code):
    assert url_mod._ytdlp_failure(stderr).code == code


def test_unknown_failure_keeps_the_error_line_only():
    stderr = (
        "WARNING: something noisy\n"
        "ERROR: unable to download video data: HTTP Error 403: Forbidden\n"
    )

    err = url_mod._ytdlp_failure(stderr)

    assert err.code == "YOUTUBE_DOWNLOAD_FAILED"
    assert "HTTP Error 403" in err.message
    assert "WARNING" not in err.message


def test_empty_stderr_still_produces_a_message():
    err = url_mod._ytdlp_failure("")
    assert err.code == "YOUTUBE_DOWNLOAD_FAILED"
    assert err.message


def test_bot_check_error_reaches_the_http_layer_as_400(monkeypatch, tmp_path):
    """The route must translate URLError into a client-visible 400, not a 500."""
    from fastapi.testclient import TestClient

    from backend.main import create_app

    deno = tmp_path / "deno"
    deno.write_text("#!/bin/sh\n")

    async def _fake_runtime():
        return str(deno)

    monkeypatch.setattr(url_mod, "ensure_deno_runtime", _fake_runtime)

    def _bot_check(cmd, **kwargs):
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="2026.08.19", stderr="")
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="ERROR: [youtube] x: Sign in to confirm you're not a bot.\n"
        )

    monkeypatch.setattr(url_mod.subprocess, "run", _bot_check)

    app = create_app()
    with TestClient(app) as client:
        # A session must exist before ingestion is accepted.
        response = client.post(
            "/api/ingest/video-url",
            json={"url": YOUTUBE_URL, "session_id": "missing-session"},
        )

    # Rejected before yt-dlp for the missing session, or 400 with our code -
    # never an opaque 500.
    assert response.status_code in (400, 404, 409)
    if response.status_code == 400:
        assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"


# ---------------------------------------------------------------------------
# Temporary file handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_temp_dir_removed_on_success(monkeypatch, tmp_path, assemblyai_key):
    """A successful YouTube ingest leaves no downloaded media behind."""
    seen: dict = {}

    async def _fake_download(url, output_path):
        Path(output_path + ".m4a").write_bytes(b"audio")
        return 5

    async def _fake_extract(src, dest):
        Path(dest).write_bytes(b"wav")
        return 1.0

    async def _fake_transcribe(path, key):
        return {"text": "hello", "segments": []}

    monkeypatch.setattr(url_mod, "download_youtube_video", _fake_download)
    monkeypatch.setattr(url_mod, "extract_audio_from_video", _fake_extract)
    monkeypatch.setattr(url_mod, "transcribe_audio_file", _fake_transcribe)

    real_tempdir = url_mod.tempfile.TemporaryDirectory

    def _tracking_tempdir(*args, **kwargs):
        handle = real_tempdir(*args, **kwargs)
        handle.__enter__ = handle.__enter__  # keep behaviour
        return _TrackingTempDir(handle, seen)

    monkeypatch.setattr(url_mod.tempfile, "TemporaryDirectory", _tracking_tempdir)

    source = await url_mod.process_video_url(YOUTUBE_URL, "session-1")

    assert source.transcript == "hello"
    assert seen["tmpdir"]
    assert not os.path.exists(seen["tmpdir"]), "temp dir must be removed on success"


@pytest.mark.asyncio
async def test_temp_dir_removed_on_failure(monkeypatch, tmp_path, assemblyai_key):
    """A failed ingest must not leak the partial download."""
    seen: dict = {}

    async def _fake_download(url, output_path):
        Path(output_path + ".m4a").write_bytes(b"partial")
        raise URLError("Sign in to confirm you're not a bot.", "YOUTUBE_BOT_CHECK")

    monkeypatch.setattr(url_mod, "download_youtube_video", _fake_download)

    real_tempdir = url_mod.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        url_mod.tempfile, "TemporaryDirectory", lambda *a, **k: _TrackingTempDir(real_tempdir(*a, **k), seen)
    )

    with pytest.raises(URLError):
        await url_mod.process_video_url(YOUTUBE_URL, "session-1")

    assert seen["tmpdir"]
    assert not os.path.exists(seen["tmpdir"]), "temp dir must be removed on failure"


class _TrackingTempDir:
    """Wraps TemporaryDirectory to record the path actually handed to the code."""

    def __init__(self, handle, seen):
        self._handle = handle
        seen["tmpdir"] = handle.name

    def __enter__(self):
        return self._handle.__enter__()

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)


def _completed_source():
    from backend.ingestion.models import InputSource, InputType, ProcessingStatus

    return InputSource(
        type=InputType.VIDEO_URL,
        url=YOUTUBE_URL,
        status=ProcessingStatus.COMPLETED,
        transcript="hello",
        transcript_segments=[],
    )


# ---------------------------------------------------------------------------
# Uploaded-media paths must be untouched
# ---------------------------------------------------------------------------


def test_uploaded_paths_never_resolve_the_deno_runtime():
    """Audio/video upload uses AssemblyAI directly - it must not need yt-dlp."""
    source = Path(url_mod.__file__).read_text()

    for fn in ("process_audio_upload", "process_video_upload"):
        assert fn not in source, f"{fn} should not be defined in url.py at all"

    # Exactly one real call site (docstrings mention it by name), and it lives
    # in the yt-dlp download path only.
    calls = [
        line
        for line in source.splitlines()
        if "ensure_deno_runtime" in line and "await ensure_deno_runtime()" in line
    ]
    assert len(calls) == 1, calls

    call_at = source.index(calls[0])
    download_at = source.index("async def download_youtube_video")
    process_at = source.index("async def process_video_url")

    assert download_at < call_at < process_at
    # process_video_url delegates to the helpers and never resolves the runtime.
    assert "ensure_deno_runtime" not in source[process_at:]
    assert "download_youtube_video" in source[process_at:]


@pytest.mark.asyncio
async def test_direct_video_url_path_unchanged(monkeypatch, tmp_path, assemblyai_key):
    """A direct .mp4 link still streams, transcodes and transcribes."""
    calls: dict = {}

    async def _fake_head(*args, **kwargs):  # pragma: no cover - unused
        raise AssertionError

    async def _fake_download(url, output_path):
        calls["downloaded"] = url
        Path(output_path).write_bytes(b"mp4")
        return 3

    async def _fake_extract(src, dest):
        calls["extracted_from"] = src
        Path(dest).write_bytes(b"wav")
        return 12.5

    async def _fake_transcribe(path, key):
        calls["transcribed"] = path
        return {"text": "direct", "segments": []}

    monkeypatch.setattr(url_mod, "download_video_url", _fake_download)
    monkeypatch.setattr(url_mod, "extract_audio_from_video", _fake_extract)
    monkeypatch.setattr(url_mod, "transcribe_audio_file", _fake_transcribe)

    source = await url_mod.process_video_url("https://cdn.example.com/clip.mp4", "s1")

    assert source.transcript == "direct"
    assert source.duration_seconds == 12.5
    assert calls["downloaded"] == "https://cdn.example.com/clip.mp4"
    assert calls["extracted_from"].endswith("video.mp4")


@pytest.mark.asyncio
async def test_direct_video_url_never_invokes_ytdlp(monkeypatch, tmp_path, assemblyai_key):
    """No yt-dlp, and therefore no Deno lookup, on the direct-file path."""
    async def _fake_download(url, output_path):
        Path(output_path).write_bytes(b"mp4")
        return 3

    async def _fake_extract(src, dest):
        Path(dest).write_bytes(b"wav")
        return 1.0

    async def _fake_transcribe(path, key):
        return {"text": "direct", "segments": []}

    async def _forbidden():  # pragma: no cover - must not run
        raise AssertionError("direct URLs must not resolve the Deno runtime")

    monkeypatch.setattr(url_mod, "download_video_url", _fake_download)
    monkeypatch.setattr(url_mod, "extract_audio_from_video", _fake_extract)
    monkeypatch.setattr(url_mod, "transcribe_audio_file", _fake_transcribe)
    monkeypatch.setattr(url_mod, "ensure_deno_runtime", _forbidden)

    source = await url_mod.process_video_url("https://cdn.example.com/clip.mp4", "s1")
    assert source.status.value == "completed"


# ---------------------------------------------------------------------------
# Local self-check
# ---------------------------------------------------------------------------


def test_no_fake_data_introduced():
    """Guard against the shortcut this task forbids."""
    new = Path(url_mod.__file__).read_text() + Path(
        sys.modules["backend.ingestion.deno_runtime"].__file__
    ).read_text()

    for banned in (
        "MOCK_TRANSCRIPT",
        "FAKE_TRANSCRIPT",
        "mock_transcript",
        "sample_transcript",
        "DUMMY_VERDICT",
        "fake_evidence",
    ):
        assert banned not in new
