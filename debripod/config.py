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

DEFAULT_CONFIG: dict[str, Any] = {
    "HOST": "127.0.0.1",
    "PORT": 8083,
    "APP_NAME": "Debripod",
    "WHEEL_ROTATION_MAX_DEGREES": 0.95,
    "PLAYBACK_STREAMING_MODE": "http",
    "RESULTS_PER_PAGE": 50,
    "MAX_FILES_PER_TORRENT": 50,
    "MAX_TORRENT_WAIT_SECONDS": 1800,
    "POLL_INTERVAL_SECONDS": 4,
    "REQUEST_TIMEOUT_SECONDS": 25,
    "SEARCH_STREAM_ROOT_ID": "__search_stream__",
    "SEARCH_STREAM_SESSION_TTL_SECONDS": 21600,
    "SEARCH_HISTORY_MAX_ITEMS": 50,
    "SEARCH_DISK_CACHE_TTL_SECONDS": 604800,
    "TASKS_POLL_MS": 1200,
    "MCP_PROTOCOL_VERSION": "2025-03-26",
    "MCP_SEARCH_RESULT_LIMIT": 20,
    "MCP_SSE_KEEPALIVE_SECONDS": 15,
    "MCP_SESSION_TTL_SECONDS": 43200,
    "KNABEN_API_KEY": "",
    "KNABEN_MIN_SECONDS_BETWEEN_REQUESTS": 0.6,
    "KNABEN_CACHE_TTL_SECONDS": 120.0,
    "KNABEN_MAX_RETRIES": 5,
    "KNABEN_API_BASE": "https://api.knaben.org/v1",
    "KNABEN_WEB_BASE": "https://knaben.org",
    "YTDLP_CMD": "yt-dlp",
    "YOUTUBE_DOWNLOAD_DIR": "./data/youtube",
    "YOUTUBE_STREAM_CACHE_SUBDIR": "youtube_streams",
    "YOUTUBE_WEB_BASE": "https://www.youtube.com",
    "YOUTUBE_SEARCH_LIMIT": 24,
    "YOUTUBE_CHANNEL_BROWSE_LIMIT": 0,
    "YOUTUBE_REQUEST_HEADERS": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    },
    "FFMPEG_PATH": "ffmpeg",
    "FFPROBE_PATH": "ffprobe",
    "AUDIO_TRANSCODE": "",
    "AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY": True,
    "REPLACE_ORIGINAL": True,
    "PRELOAD_NEXT_FOR_GAPLESS": True,
    "PRELOAD_NEXT_CHUNK_BYTES": 2097152,
    "CACHE_DIR_NAME": "_debripod_cache",
    "VIDEO_BROWSER_TARGET_EXT": "mp4",
    "REAL_DEBRID_API_KEY": "",
    "RD_BASE": "https://api.real-debrid.com/rest/1.0",
    "DOWNLOAD_DIR": "./data/debrid",
    "SOULSEEK_USERNAME": "",
    "SOULSEEK_PASSWORD": "",
    "SOULSEEK_DOWNLOAD_DIR": "./data/soulseek",
    "SOULSEEK_LISTENING_PORT": 61000,
    "SOULSEEK_OBFUSCATED_PORT": 0,
    "SOULSEEK_SEARCH_TIMEOUT_SEC": 8,
    "SOULSEEK_SEARCH_MAX_RESULTS": 5000,
    "SOULSEEK_SEARCH_IDLE_STOP_SEC": 2.5,
    "SOULSEEK_SEARCH_HARD_MAX_SEC": 60,
    "LASTFM_API_KEY": "",
    "LASTFM_API_SECRET": "",
    "LASTFM_SESSION_KEY": "",
    "LASTFM_CALLBACK_URL": "",
    "LASTFM_API_ROOT": "https://ws.audioscrobbler.com/2.0/",
    "LASTFM_REQUEST_TIMEOUT_SECONDS": 12,
    "LIBRARY_FOLDERS": [
        {"path": "./data/debrid", "mode": "list"},
        {"path": "./data/soulseek", "mode": "meta"},
        {"path": "./data/music", "mode": "meta"},
    ],
}

CONFIG_KEYS = {
    "HOST", "PORT", "APP_NAME", "RESULTS_PER_PAGE", "MAX_FILES_PER_TORRENT",
    "MAX_TORRENT_WAIT_SECONDS", "POLL_INTERVAL_SECONDS", "REQUEST_TIMEOUT_SECONDS",
    "TASKS_POLL_MS", "WHEEL_ROTATION_MAX_DEGREES", "PLAYBACK_STREAMING_MODE",
    "SEARCH_STREAM_ROOT_ID", "SEARCH_STREAM_SESSION_TTL_SECONDS",
    "SEARCH_HISTORY_MAX_ITEMS", "SEARCH_DISK_CACHE_TTL_SECONDS",
    "MCP_PROTOCOL_VERSION", "MCP_SEARCH_RESULT_LIMIT", "MCP_SSE_KEEPALIVE_SECONDS", "MCP_SESSION_TTL_SECONDS",
    "KNABEN_API_KEY", "KNABEN_MIN_SECONDS_BETWEEN_REQUESTS", "KNABEN_CACHE_TTL_SECONDS",
    "KNABEN_MAX_RETRIES", "KNABEN_API_BASE", "KNABEN_WEB_BASE",
    "YTDLP_CMD", "YOUTUBE_DOWNLOAD_DIR", "YOUTUBE_STREAM_CACHE_SUBDIR",
    "YOUTUBE_WEB_BASE", "YOUTUBE_SEARCH_LIMIT", "YOUTUBE_CHANNEL_BROWSE_LIMIT", "YOUTUBE_REQUEST_HEADERS",
    "FFMPEG_PATH", "FFPROBE_PATH", "AUDIO_TRANSCODE",
    "AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY", "REPLACE_ORIGINAL",
    "PRELOAD_NEXT_FOR_GAPLESS", "PRELOAD_NEXT_CHUNK_BYTES", "CACHE_DIR_NAME", "VIDEO_BROWSER_TARGET_EXT",
    "REAL_DEBRID_API_KEY", "RD_BASE", "DOWNLOAD_DIR",
    "SOULSEEK_USERNAME", "SOULSEEK_PASSWORD", "SOULSEEK_DOWNLOAD_DIR",
    "SOULSEEK_LISTENING_PORT", "SOULSEEK_OBFUSCATED_PORT", "SOULSEEK_SEARCH_TIMEOUT_SEC",
    "SOULSEEK_SEARCH_MAX_RESULTS", "SOULSEEK_SEARCH_IDLE_STOP_SEC", "SOULSEEK_SEARCH_HARD_MAX_SEC",
    "LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY", "LASTFM_CALLBACK_URL",
    "LASTFM_API_ROOT", "LASTFM_REQUEST_TIMEOUT_SECONDS",
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


def _coerce_config_value(key_upper: str, value: Any) -> Any:
    if key_upper == "LIBRARY_FOLDERS":
        return _coerce_library_folders(value)
    if key_upper.endswith("_DIR") or key_upper.endswith("_PATH") or key_upper == "DOWNLOAD_DIR":
        return _coerce_path(str(value))
    return value


def apply_config_to_module(module_globals: MutableMapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config.update(load_config(path))
    applied: dict[str, Any] = {}

    for key, value in config.items():
        key_upper = str(key).upper()
        if key_upper not in CONFIG_KEYS:
            continue
        value = _coerce_config_value(key_upper, value)
        module_globals[key_upper] = value
        applied[key_upper] = value

    return applied


def redacted(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    for key in SECRET_KEYS:
        if out.get(key):
            out[key] = "***"
    return out
