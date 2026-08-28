from __future__ import annotations

import json
import os
import secrets
import warnings
from pathlib import Path
from typing import Any, MutableMapping

from .settings import APP_SETTING_KEYS, DEFAULT_APP_SETTINGS, SECRET_SETTING_KEYS, STARTUP_CONFIG_KEYS, ensure_app_settings
from .secrets import get_secret, set_secret
from .storage.database import database_path
from .storage import settings as settings_repository
from .storage.users import list_users, replace_users

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
    "REAL_DEBRID_API_KEY", "ALLDEBRID_API_KEY", "PREMIUMIZE_API_KEY", "TORBOX_API_KEY",
    "SOULSEEK_USERNAME", "SOULSEEK_PASSWORD",
    "LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY", "APP_SECRET_KEY", "MCP_TOKEN",
}


def load_default_app_config_overrides(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    candidate = Path(path) if path else DEFAULTS_CONFIG_PATH
    candidate = Path(os.path.expandvars(os.path.expanduser(str(candidate))))
    data = settings_repository.load("__defaults__")
    if not data and candidate.is_file():
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            settings_repository.save(data if isinstance(data, dict) else {}, "__defaults__")
            candidate.replace(candidate.with_name(candidate.name + ".migrated.local"))
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
    clean: dict[str, Any] = {}
    for key, value in (data or {}).items():
        key_upper = str(key).upper()
        if key_upper in APP_SETTING_KEYS and key_upper not in SECRET_SETTING_KEYS:
            clean[key_upper] = value
    settings_repository.save(clean, "__defaults__")
    return Path(database_path())


def _coerce_path(value: str) -> str:
    if not str(value or "").strip():
        return ""
    value = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(value)
    if not path.is_absolute() and value not in {"ffmpeg", "ffprobe", "yt-dlp"}:
        path = PACKAGE_ROOT / path
    return str(path)


def _coerce_library_folders(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("LIBRARY_FOLDERS must be a list")
    out: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            path = _coerce_path(str(item.get("path", "")))
            if path:
                out.append({"path": path, "mode": "meta"})
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
            data["_LEGACY_CONFIG_PATH"] = str(candidate)
            return data
    stored = settings_repository.load("")
    data = {key: stored[key] for key in STARTUP_CONFIG_KEYS if key in stored}
    users = list_users()
    data["USERS"] = [{"username": u["username"], "password_hash": u["password_hash"], "id": u["user_id"]} for u in users]
    data["SETUP_COMPLETE"] = bool(users)
    for key in ("APP_SECRET_KEY", "MCP_TOKEN"):
        data[key] = get_secret("global", key)
    return data


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
    current = settings_repository.load("")
    for key in ("ENABLE_MCP", "SETUP_COMPLETE"):
        if key in data:
            current[key] = data[key]
    settings_repository.save(current, "")
    replace_users(data.get("USERS") if isinstance(data.get("USERS"), list) else [])
    for key in ("APP_SECRET_KEY", "MCP_TOKEN"):
        if key in data:
            set_secret("global", key, str(data.get(key) or ""))
    legacy_path = str(data.get("_LEGACY_CONFIG_PATH") or "")
    if legacy_path:
        source = Path(legacy_path)
        try:
            source.replace(source.with_name(source.name + ".migrated.local"))
        except OSError:
            pass
    return Path(database_path())


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
    config["PORT"] = 8083
    port_env = os.environ.get("DEBRIPOD_PORT")
    if port_env:
        try:
            config["PORT"] = int(port_env)
        except ValueError as exc:
            raise ValueError("DEBRIPOD_PORT must be an integer") from exc
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
