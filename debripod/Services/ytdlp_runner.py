from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable

from ..playback.probe import run_cmd


_ytdlp_cmd_provider: Callable[[], str] = lambda: "yt-dlp"
_ffmpeg_path_provider: Callable[[], str] = lambda: ""


class YtdlpError(RuntimeError):
    def __init__(self, message: str, category: str = "unavailable"):
        super().__init__(message)
        self.category = category


def configure_ytdlp_runner(*, ytdlp_cmd_provider: Callable[[], str], ffmpeg_path_provider: Callable[[], str] | None = None) -> None:
    global _ytdlp_cmd_provider, _ffmpeg_path_provider
    _ytdlp_cmd_provider = ytdlp_cmd_provider
    _ffmpeg_path_provider = ffmpeg_path_provider or (lambda: "")


def plugin_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def _ffmpeg_location() -> str:
    raw = str(_ffmpeg_path_provider() or "").strip()
    if not raw:
        return ""
    return raw if os.path.isdir(raw) else (os.path.dirname(raw) or raw)


def base_args(*, include_ffmpeg: bool = True) -> list[str]:
    args = ["--no-warnings", "--ignore-config", "--plugin-dirs", plugin_root()]
    location = _ffmpeg_location() if include_ffmpeg else ""
    if location:
        args.extend(["--ffmpeg-location", location])
    return args


def classify_error(message: str, code: int = 1) -> str:
    value = str(message or "").casefold()
    if code == 124 or "timed out" in value or "timeout" in value:
        return "timeout"
    if "drm" in value:
        return "drm"
    if "subscription" in value or "members-only" in value or "premium account" in value:
        return "subscription_required"
    if "geo" in value or "not available in your country" in value:
        return "geo_restricted"
    if "private" in value or "deleted" in value or "removed" in value:
        return "private_or_deleted"
    return "unavailable"


def run_json(url_or_prefix: str, flat: bool = True, timeout: int | None = None) -> dict[str, Any]:
    args = base_args()
    if flat:
        args.append("--flat-playlist")
    args.extend(["--dump-single-json", "--skip-download", str(url_or_prefix)])
    code, stdout, stderr = run_cmd([str(_ytdlp_cmd_provider() or "yt-dlp")] + args, timeout=timeout or 120)
    if code != 0:
        message = (stderr or stdout or "yt-dlp failed").strip()
        raise YtdlpError(message, classify_error(message, code))
    try:
        value = json.loads(stdout or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise YtdlpError(f"yt-dlp returned malformed JSON: {exc}", "malformed_json") from exc
    if not isinstance(value, dict):
        raise YtdlpError("yt-dlp returned malformed JSON: expected an object", "malformed_json")
    return value


def run_flat_entries(url_or_prefix: str, timeout: int | None = None) -> list[dict[str, Any]]:
    payload = run_json(url_or_prefix, flat=True, timeout=timeout)
    entries = payload.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return [payload] if payload.get("id") else []


async def run_json_async(url_or_prefix: str, flat: bool = True, timeout: int | None = None) -> dict[str, Any]:
    args = base_args()
    if flat:
        args.append("--flat-playlist")
    args.extend(["--dump-single-json", "--skip-download", str(url_or_prefix)])
    process = await asyncio.create_subprocess_exec(
        str(_ytdlp_cmd_provider() or "yt-dlp"),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout or 120)
    except asyncio.CancelledError:
        process.kill()
        await process.communicate()
        raise
    except asyncio.TimeoutError as exc:
        process.kill()
        stdout, stderr = await process.communicate()
        message = (stderr or stdout or b"yt-dlp timed out").decode("utf-8", "replace").strip()
        raise YtdlpError(message, "timeout") from exc
    if process.returncode != 0:
        message = (stderr or stdout or b"yt-dlp failed").decode("utf-8", "replace").strip()
        raise YtdlpError(message, classify_error(message, int(process.returncode or 1)))
    try:
        value = json.loads(stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as exc:
        raise YtdlpError(f"yt-dlp returned malformed JSON: {exc}", "malformed_json") from exc
    if not isinstance(value, dict):
        raise YtdlpError("yt-dlp returned malformed JSON: expected an object", "malformed_json")
    return value


async def run_flat_entries_async(url_or_prefix: str, timeout: int | None = None) -> list[dict[str, Any]]:
    payload = await run_json_async(url_or_prefix, flat=True, timeout=timeout)
    entries = payload.get("entries")
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    return [payload] if payload.get("id") else []
