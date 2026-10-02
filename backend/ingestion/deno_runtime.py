"""Deno JavaScript runtime for yt-dlp YouTube extraction.

yt-dlp needs a JS runtime to run YouTube's challenge scripts, and warns that
extraction without one is deprecated. The pip wheel ships no runtime binary, so
a container built straight from ``requirements.txt`` has none either - which is
exactly the ``No supported JavaScript runtime could be found`` warning the
deployment was logging.

Resolution order:

1. ``YTDLP_DENO_PATH``  - explicit path to a preinstalled deno. Set this when
   the image installs Deno itself (Dockerfile / Render build command).
2. ``deno`` on ``PATH`` - an image that already provides it.
3. The pinned official release, downloaded once into a cache directory and
   verified against the published sha256.

``YTDLP_DENO_INSTALL=0`` disables step 3, which turns a missing runtime into a
clear error instead of a download. That is the switch to reach for in a network
-restricted deployment.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DENO_VERSION = "2.9.7"
_RELEASE_URL = "https://github.com/denoland/deno/releases/download/v{version}/{asset}"

# (os, normalised machine) -> release target triple.
_TARGETS = {
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("Windows", "arm64"): "aarch64-pc-windows-msvc",
}

_TIMEOUT = httpx.Timeout(60.0, read=300.0)
_CHUNK = 1024 * 64


class DenoRuntimeUnavailable(RuntimeError):
    """Raised when no usable Deno runtime could be located or installed."""


def _machine() -> str:
    raw = platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64"}.get(raw, raw)


def _target() -> str:
    key = (platform.system(), _machine())
    target = _TARGETS.get(key)
    if target is None:
        raise DenoRuntimeUnavailable(
            f"No official Deno build for {key[0]}/{key[1]}. "
            "Install Deno in the image and set YTDLP_DENO_PATH."
        )
    return target


def _install_enabled() -> bool:
    return os.environ.get("YTDLP_DENO_INSTALL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _cache_dir() -> Path:
    override = os.environ.get("YTDLP_DENO_DIR")
    if override:
        return Path(override)

    # XDG first, then the platform cache dir. Deliberately not /opt: Render runs
    # as an unprivileged user and would fail to write there.
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "lfc" / "deno"

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "lfc" / "deno"
    return Path.home() / ".cache" / "lfc" / "deno"


def _binary_name() -> str:
    return "deno.exe" if os.name == "nt" else "deno"


async def _download(expected_sha: str, dest: Path) -> None:
    asset = f"deno-{_target()}.zip"
    url = _RELEASE_URL.format(version=DENO_VERSION, asset=asset)

    digest = hashlib.sha256()
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                async for chunk in response.aiter_bytes(_CHUNK):
                    handle.write(chunk)
                    digest.update(chunk)

    actual = digest.hexdigest()
    if actual != expected_sha:
        raise DenoRuntimeUnavailable(
            f"Deno checksum mismatch for {asset}: expected {expected_sha}, got {actual}"
        )


async def _install() -> Path:
    """Download, verify and atomically install the pinned Deno release."""
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    final = cache / _binary_name()

    expected_sha = await _fetch_sha256()

    # Unpack into a private temp dir, then move into place atomically so a
    # crashed or concurrent install can never leave a half-written binary that a
    # later run would happily execute.
    # ponytail: two concurrent first-calls may both download. Harmless (the
    # loser just overwrites an identical binary); add a lock only if the
    # duplicate ~40MB pull ever matters.
    with tempfile.TemporaryDirectory(dir=str(cache)) as work:
        work_dir = Path(work)
        archive = work_dir / "deno.zip"
        await _download(expected_sha, archive)

        with zipfile.ZipFile(archive) as bundle:
            names = [n for n in bundle.namelist() if Path(n).name == _binary_name()]
            if not names:
                raise DenoRuntimeUnavailable(f"{_binary_name()} missing from Deno archive")
            with bundle.open(names[0]) as src, (work_dir / _binary_name()).open("wb") as dst:
                shutil.copyfileobj(src, dst)

        staged = work_dir / _binary_name()
        if os.name != "nt":
            staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        os.replace(staged, final)

    logger.info("Installed Deno %s at %s", DENO_VERSION, final)
    return final


def _parse_sha256(text: str) -> str:
    """Pull the digest out of a ``.sha256sum`` body.

    Deno's files are not one consistent format: the Linux and macOS assets use
    the standard ``<digest>  <name>`` line, while the Windows asset is a
    multi-line ``algorithm: SHA256 / Hash: <digest> / Path: ...`` block with an
    uppercase digest. Matching the digest itself handles both.
    """
    match = re.search(r"[0-9a-fA-F]{64}", text)
    if not match:
        raise DenoRuntimeUnavailable("Deno checksum file contained no sha256 digest")
    return match.group(0).lower()


async def _fetch_sha256() -> str:
    asset = f"deno-{_target()}.zip.sha256sum"
    url = _RELEASE_URL.format(version=DENO_VERSION, asset=asset)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    return _parse_sha256(response.text)


async def ensure_deno_runtime() -> str:
    """Return the path to a usable Deno binary, installing one if needed.

    Raises:
        DenoRuntimeUnavailable: if no runtime is present and one cannot be
            installed. Callers translate this into a user-facing error.
    """
    override = os.environ.get("YTDLP_DENO_PATH")
    if override:
        if Path(override).exists():
            return override
        raise DenoRuntimeUnavailable(
            f"YTDLP_DENO_PATH is set to {override!r}, which does not exist"
        )

    on_path = shutil.which("deno")
    if on_path:
        return on_path

    cached = _cache_dir() / _binary_name()
    if cached.exists():
        return str(cached)

    if not _install_enabled():
        raise DenoRuntimeUnavailable(
            "yt-dlp needs the Deno JavaScript runtime for YouTube extraction and it "
            "is not installed. Set YTDLP_DENO_PATH, or allow YTDLP_DENO_INSTALL=1."
        )

    try:
        return str(await _install())
    except httpx.HTTPError as exc:
        raise DenoRuntimeUnavailable(
            f"Could not download the Deno runtime required for YouTube extraction: {exc}"
        ) from exc
