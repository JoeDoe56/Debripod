from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, MutableMapping

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATHS = [
    PACKAGE_ROOT / "config" / "debripod.local.json",
    PACKAGE_ROOT / "config" / "debripod.json",
    Path.home() / ".config" / "debripod" / "config.json",
]

CONFIG_KEYS = {
    "HOST", "PORT", "APP_NAME", "RESULTS_PER_PAGE", "MAX_FILES_PER_TORRENT",
    "MAX_TORRENT_WAIT_SECONDS", "POLL_INTERVAL_SECONDS", "REQUEST_TIMEOUT_SECONDS",
    "TASKS_POLL_MS", "LIQUID_GL_PRESET", "MCP_PROTOCOL_VERSION", "MCP_SEARCH_RESULT_LIMIT",
    "KNABEN_API_KEY", "KNABEN_MIN_SECONDS_BETWEEN_REQUESTS", "KNABEN_CACHE_TTL_SECONDS",
    "KNABEN_MAX_RETRIES", "KNABEN_API_BASE", "KNABEN_WEB_BASE",
    "YTDLP_CMD", "YOUTUBE_DOWNLOAD_DIR", "YOUTUBE_STREAM_CACHE_SUBDIR",
    "YOUTUBE_WEB_BASE", "YOUTUBE_SEARCH_LIMIT", "YOUTUBE_CHANNEL_BROWSE_LIMIT",
    "FFMPEG_PATH", "FFPROBE_PATH", "AUDIO_TRANSCODE",
    "AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY", "REPLACE_ORIGINAL",
    "PRELOAD_NEXT_FOR_GAPLESS", "PRELOAD_NEXT_CHUNK_BYTES", "CACHE_DIR_NAME",
    "REAL_DEBRID_API_KEY", "RD_BASE", "DOWNLOAD_DIR",
    "SOULSEEK_USERNAME", "SOULSEEK_PASSWORD", "SOULSEEK_DOWNLOAD_DIR",
    "SOULSEEK_LISTENING_PORT", "SOULSEEK_OBFUSCATED_PORT", "SOULSEEK_SEARCH_TIMEOUT_SEC",
    "SOULSEEK_SEARCH_MAX_RESULTS", "SOULSEEK_SEARCH_IDLE_STOP_SEC", "SOULSEEK_SEARCH_HARD_MAX_SEC",
    "LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY", "LASTFM_CALLBACK_URL",
    "LIBRARY_FOLDERS",
}

SECRET_KEYS = {
    "KNABEN_API_KEY", "REAL_DEBRID_API_KEY", "SOULSEEK_USERNAME", "SOULSEEK_PASSWORD",
    "LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY",
}


def _coerce_path(value: str) -> str:
    value = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(value)
    if not path.is_absolute() and value not in {"ffmpeg", "ffprobe", "yt-dlp"}:
        path = PACKAGE_ROOT / path
    return str(path)


def _coerce_library_folders(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("LIBRARY_FOLDERS must be a list")
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(_coerce_path(item))
            continue
        if isinstance(item, dict):
            path = _coerce_path(str(item.get("path", "")))
            mode = str(item.get("mode", "list")).strip().lower() or "list"
            if path:
                out.append(f"{path}:{mode}")
    return out


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    env_path = os.environ.get("DEBRIPOD_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(DEFAULT_CONFIG_PATHS)

    for candidate in candidates:
        candidate = Path(os.path.expandvars(os.path.expanduser(str(candidate))))
        if candidate.is_file():
            with candidate.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise TypeError(f"Config file must contain a JSON object: {candidate}")
            return data
    return {}


def apply_config_to_module(module_globals: MutableMapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    config = load_config(path)
    applied: dict[str, Any] = {}

    for key, value in config.items():
        key_upper = str(key).upper()
        if key_upper not in CONFIG_KEYS:
            continue
        if key_upper == "LIBRARY_FOLDERS":
            value = _coerce_library_folders(value)
        elif key_upper.endswith("_DIR") or key_upper.endswith("_PATH") or key_upper in {"DOWNLOAD_DIR", "CACHE_DIR_NAME"}:
            value = _coerce_path(str(value))
        module_globals[key_upper] = value
        applied[key_upper] = value

    return applied


def redacted(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    for key in SECRET_KEYS:
        if out.get(key):
            out[key] = "***"
    return out
