from __future__ import annotations

import json
import os
import secrets
import warnings
from pathlib import Path
from typing import Any, MutableMapping

from .settings import APP_SETTING_KEYS, DEFAULT_APP_SETTINGS, SECRET_SETTING_KEYS, STARTUP_CONFIG_KEYS, ensure_app_settings

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_CONFIG_PATH = PACKAGE_ROOT / "config" / "debripod.defaults.json"
DEFAULT_CONFIG_PATHS = [
    PACKAGE_ROOT / "config" / "debripod.local.json",
    PACKAGE_ROOT / "config" / "debripod.json",
    Path.home() / ".config" / "debripod" / "config.json",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "PORT": 8083,
    "USERS": [],
    "APP_SECRET_KEY": "",
    "ENABLE_MCP": False,
    "MCP_TOKEN": "",
    "SETUP_COMPLETE": False,
    **DEFAULT_APP_SETTINGS,
}

CONFIG_KEYS = {
    "PORT", "USERS", "APP_SECRET_KEY", "ENABLE_MCP", "MCP_TOKEN", "SETUP_COMPLETE",
} | APP_SETTING_KEYS

SECRET_KEYS = {
    "KNABEN_API_KEY", "REAL_DEBRID_API_KEY", "SOULSEEK_USERNAME", "SOULSEEK_PASSWORD",
    "LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY", "APP_SECRET_KEY", "MCP_TOKEN",
}


def load_default_app_config_overrides(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    candidate = Path(path) if path else DEFAULTS_CONFIG_PATH
    candidate = Path(os.path.expandvars(os.path.expanduser(str(candidate))))
    if not candidate.is_file():
        return {}
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        warnings.warn(f"DebriPod defaults config is unreadable: {candidate}: {exc}", RuntimeWarning)
        return {}
    if not isinstance(data, dict):
        warnings.warn(f"DebriPod defaults config must contain a JSON object: {candidate}", RuntimeWarning)
        return {}
    out: dict[str, Any] = {}
    for key, value in data.items():
        key_upper = str(key).upper()
        if key_upper in APP_SETTING_KEYS and key_upper not in SECRET_SETTING_KEYS:
            out[key_upper] = value
    return out


def save_default_app_config_overrides(data: dict[str, Any], path: str | os.PathLike[str] | None = None) -> Path:
    target = Path(path) if path else DEFAULTS_CONFIG_PATH
    target = Path(os.path.expandvars(os.path.expanduser(str(target))))
    clean: dict[str, Any] = {}
    for key, value in (data or {}).items():
        key_upper = str(key).upper()
        if key_upper in APP_SETTING_KEYS and key_upper not in SECRET_SETTING_KEYS:
            clean[key_upper] = value
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(clean, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(target)
    return target


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


def _config_write_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(os.path.expandvars(os.path.expanduser(str(path))))
    env_path = os.environ.get("DEBRIPOD_CONFIG")
    if env_path:
        return Path(os.path.expandvars(os.path.expanduser(env_path)))
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.is_file():
            return candidate
    return DEFAULT_CONFIG_PATHS[0]


def save_config(data: dict[str, Any], path: str | os.PathLike[str] | None = None) -> Path:
    target = _config_write_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    tmp.replace(target)
    return target


def ensure_startup_security_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    data = load_config(path)
    ensure_app_settings(data, defaults_overrides=load_default_app_config_overrides())
    changed = False
    for key in list(data.keys()):
        key_upper = str(key).upper()
        if key_upper not in STARTUP_CONFIG_KEYS and not str(key).startswith("_"):
            data.pop(key, None)
            changed = True
    if not str(data.get("APP_SECRET_KEY") or "").strip():
        data["APP_SECRET_KEY"] = secrets.token_urlsafe(48)
        changed = True
    if "USERS" not in data or not isinstance(data.get("USERS"), list):
        data["USERS"] = []
        changed = True
    if "ENABLE_MCP" not in data:
        data["ENABLE_MCP"] = False
        changed = True
    if bool(data.get("ENABLE_MCP")) and not str(data.get("MCP_TOKEN") or "").strip():
        data["MCP_TOKEN"] = secrets.token_urlsafe(48)
        changed = True
    elif "MCP_TOKEN" not in data:
        data["MCP_TOKEN"] = ""
        changed = True
    setup_complete = bool(data.get("SETUP_COMPLETE")) and bool(data.get("USERS"))
    if data.get("SETUP_COMPLETE") != setup_complete:
        data["SETUP_COMPLETE"] = setup_complete
        changed = True
    if changed:
        save_config(data, path)
    return data


def _coerce_config_value(key_upper: str, value: Any) -> Any:
    if key_upper == "LIBRARY_FOLDERS":
        return _coerce_library_folders(value)
    if key_upper.endswith("_DIR") or key_upper.endswith("_PATH") or key_upper == "DOWNLOAD_DIR":
        return _coerce_path(str(value))
    return value


def apply_config_to_module(module_globals: MutableMapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    startup_config = load_config(path)
    default_overrides = load_default_app_config_overrides()
    app_settings = ensure_app_settings(startup_config, defaults_overrides=default_overrides)
    config = dict(DEFAULT_CONFIG)
    config.update(default_overrides)
    config.update(app_settings)
    for key in ("PORT", "USERS", "APP_SECRET_KEY", "ENABLE_MCP", "MCP_TOKEN", "SETUP_COMPLETE"):
        if key in startup_config:
            config[key] = startup_config[key]
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
