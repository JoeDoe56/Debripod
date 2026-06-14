from __future__ import annotations

import json
import os
import secrets
import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PACKAGE_ROOT / "data" / "settings.json"

STARTUP_CONFIG_KEYS = {"PORT", "USERS", "APP_SECRET_KEY", "ENABLE_MCP", "MCP_TOKEN", "SETUP_COMPLETE"}

DEFAULT_APP_SETTINGS: dict[str, Any] = {
    "APP_NAME": "DebriPod",
    "WHEEL_ROTATION_MAX_DEGREES": 10,
    "PLAYBACK_STREAMING_MODE": "http",
    "RESULTS_PER_PAGE": 50,
    "MAX_FILES_PER_TORRENT": 50,
    "MAX_TORRENT_WAIT_SECONDS": 1800,
    "POLL_INTERVAL_SECONDS": 4,
    "REQUEST_TIMEOUT_SECONDS": 25,
    "STREAM_PROXY_ALLOWED_HOST_SUFFIXES": [
        "real-debrid.com",
        "download.real-debrid.com",
        "youtube.com",
        "googlevideo.com",
        "ytimg.com",
    ],
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
    "LIBRARY_FOLDERS": [],
}

APP_SETTING_KEYS = set(DEFAULT_APP_SETTINGS)
SECRET_SETTING_KEYS = {
    "KNABEN_API_KEY",
    "REAL_DEBRID_API_KEY",
    "SOULSEEK_USERNAME",
    "SOULSEEK_PASSWORD",
    "LASTFM_API_KEY",
    "LASTFM_API_SECRET",
    "LASTFM_SESSION_KEY",
}

LEGACY_DEFAULT_LIBRARY_FOLDERS = [
    {"path": "./data/debrid", "mode": "list"},
    {"path": "./data/soulseek", "mode": "meta"},
    {"path": "./data/music", "mode": "meta"},
]


def _user_settings_path(username: str) -> Path:
    raw = str(username or "").strip().lower()
    digest = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    return PACKAGE_ROOT / "data" / "users" / digest / "settings.json"


def _user_data_dir(username: str) -> Path:
    return _user_settings_path(username).parent


def default_app_settings(username: str | None = None) -> dict[str, Any]:
    out = dict(DEFAULT_APP_SETTINGS)
    if str(username or "").strip():
        base = _user_data_dir(str(username))
        out["DOWNLOAD_DIR"] = str(base / "debrid")
        out["SOULSEEK_DOWNLOAD_DIR"] = str(base / "soulseek")
        out["YOUTUBE_DOWNLOAD_DIR"] = str(base / "youtube")
        out["LIBRARY_FOLDERS"] = []
    return out


def _settings_path(username: str | None = None) -> Path:
    username = str(username or "").strip()
    if username:
        return _user_settings_path(username)
    return SETTINGS_PATH


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    tmp.replace(path)


def _coerce_setting(key: str, value: Any) -> Any:
    default = DEFAULT_APP_SETTINGS.get(key)
    if key in {"SOULSEEK_LISTENING_PORT", "SOULSEEK_OBFUSCATED_PORT"}:
        try:
            return max(0, min(65535, int(value)))
        except Exception:
            return int(default or 0)
    if key in {"SOULSEEK_SEARCH_TIMEOUT_SEC", "SOULSEEK_SEARCH_HARD_MAX_SEC"}:
        try:
            return max(1, int(float(value)))
        except Exception:
            return int(default or 1)
    if key == "SOULSEEK_SEARCH_MAX_RESULTS":
        try:
            return max(1, int(value))
        except Exception:
            return int(default or 1)
    if key == "SOULSEEK_SEARCH_IDLE_STOP_SEC":
        try:
            return max(0.1, float(value))
        except Exception:
            return float(default or 0.1)
    if key == "LIBRARY_FOLDERS":
        out = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    path = str(item.get("path") or "").strip()
                    mode = str(item.get("mode") or "list").strip().lower()
                    mode = "meta" if mode in {"meta", "metadata"} else "list"
                    if path:
                        out.append({"path": path, "mode": mode})
                elif isinstance(item, str):
                    path, mode = item, "list"
                    if ":" in item:
                        p, suffix = item.rsplit(":", 1)
                        if suffix.strip().lower() in {"meta", "metadata", "m", "list", "folders", "folder", "l"}:
                            path = p
                            mode = "meta" if suffix.strip().lower() in {"meta", "metadata", "m"} else "list"
                    path = str(path or "").strip()
                    if path:
                        out.append({"path": path, "mode": mode})
        return out
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except Exception:
            return default
    if isinstance(default, float):
        try:
            return float(value)
        except Exception:
            return default
    if isinstance(default, dict):
        return value if isinstance(value, dict) else dict(default)
    if isinstance(default, list):
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            return [x.strip() for x in value.split(",") if x.strip()]
        return list(default)
    return "" if value is None else str(value)


def _matches_legacy_default_library_folders(value: Any) -> bool:
    return _coerce_setting("LIBRARY_FOLDERS", value) == LEGACY_DEFAULT_LIBRARY_FOLDERS


def normalize_settings(data: dict[str, Any], username: str | None = None) -> dict[str, Any]:
    out = default_app_settings(username)
    for key, value in (data or {}).items():
        key_upper = str(key).upper()
        if key_upper in APP_SETTING_KEYS:
            out[key_upper] = _coerce_setting(key_upper, value)
    return out


def ensure_app_settings(startup_config: dict[str, Any] | None = None, username: str | None = None) -> dict[str, Any]:
    path = _settings_path(username)
    raw = _read_json(path)
    changed = not path.is_file()
    merged = dict(raw)
    if not username:
        for key, value in (startup_config or {}).items():
            key_upper = str(key).upper()
            if key_upper in APP_SETTING_KEYS and key_upper not in merged:
                merged[key_upper] = value
                changed = True
    else:
        user_defaults = default_app_settings(username)
        if _matches_legacy_default_library_folders(merged.get("LIBRARY_FOLDERS")):
            merged["LIBRARY_FOLDERS"] = []
            changed = True
        for key in ("DOWNLOAD_DIR", "SOULSEEK_DOWNLOAD_DIR", "YOUTUBE_DOWNLOAD_DIR"):
            if str(merged.get(key) or "").strip() == str(DEFAULT_APP_SETTINGS.get(key) or "").strip():
                merged[key] = user_defaults[key]
                changed = True
    normalized = normalize_settings(merged, username=username)
    if changed or normalized != raw:
        _atomic_write_json(path, normalized)
    return normalized


def save_app_settings(updates: dict[str, Any], username: str | None = None) -> dict[str, Any]:
    current = ensure_app_settings(username=username)
    for key, value in (updates or {}).items():
        key_upper = str(key).upper()
        if key_upper in APP_SETTING_KEYS:
            current[key_upper] = _coerce_setting(key_upper, value)
    current = normalize_settings(current, username=username)
    _atomic_write_json(_settings_path(username), current)
    return current


def masked_settings(data: dict[str, Any]) -> dict[str, Any]:
    out = normalize_settings(data)
    for key in SECRET_SETTING_KEYS:
        if out.get(key):
            out[key] = "***"
    return out


def executable_status(name_or_path: str) -> dict[str, Any]:
    raw = str(name_or_path or "").strip()
    found = ""
    if raw:
        found = raw if os.path.isfile(raw) else (shutil.which(raw) or "")
    install_hint = ""
    if sys.platform == "darwin":
        install_hint = "Install with Homebrew or MacPorts, then keep this as a command on PATH."
    elif sys.platform.startswith("linux"):
        install_hint = "Install with your distro package manager, then keep this as a command on PATH."
    elif sys.platform.startswith("win"):
        install_hint = "Pick ffmpeg.exe/ffprobe.exe or keep a command name if it is on PATH."
    return {
        "configured": raw,
        "found": found,
        "ok": bool(found),
        "platform": sys.platform,
        "install_hint": install_hint,
    }


def reset_mcp_token(startup_config: dict[str, Any]) -> dict[str, Any]:
    startup_config["MCP_TOKEN"] = secrets.token_urlsafe(48)
    return startup_config


def pick_system_path(kind: str = "directory") -> str:
    kind = (kind or "directory").strip().lower()
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("System picker is not available because Tkinter is not installed.") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    try:
        if kind == "file":
            filetypes = []
            if sys.platform.startswith("win"):
                filetypes = [("Executable files", "*.exe"), ("All files", "*.*")]
            path = filedialog.askopenfilename(title="Choose path", filetypes=filetypes)
        else:
            path = filedialog.askdirectory(title="Choose folder", mustexist=True)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return os.path.abspath(path) if path else ""
