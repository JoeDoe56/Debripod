from __future__ import annotations

import os
import secrets
import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any

from .secrets import get_secret, saved_status, set_secret
from .storage import settings as settings_repository
from .storage.legacy_import import read_json as read_legacy_json, retire as retire_legacy

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PACKAGE_ROOT / "data" / "settings.json"

STARTUP_CONFIG_KEYS = {"PORT", "USERS", "ENABLE_MCP", "MCP_TOKEN", "SETUP_COMPLETE"}
REMOTE_TORRENT_SOURCE_IDS = ("knaben", "bitsearch", "magnetz", "torlock", "bt4g", "torrentclaw", "torapi")

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    "visualizer": True, "visualizerMaxBrightnessPct": 60, "visualizerFpsLock": 30,
    "visualizerFrequencyResponse": {"brightness": 1.0, "opacity": 0.0, "saturation": 0.15, "contrast": 0.10},
    "visualizerEnergyResponse": {"brightness": 0.12, "opacity": 0.0, "saturation": 0.05, "contrast": 0.05},
    "visualizerBeatResponse": {"brightness": 0.10, "opacity": 0.0, "saturation": 0.0, "contrast": 0.05},
    "videoAmbient": {"enabled": True, "sampleFps": 8, "brightness": 1.0, "saturation": 1.0, "audioEnergyBrightness": 0.12, "smoothing": 0.82},
    "textModes": {"wheelLabels": "transparent", "pathPill": "transparent", "infoPill": "transparent", "rows": "transparent", "rowPills": "transparent", "selectedRow": "contrast", "selectedRowPills": "contrast"},
    "textTransparency": 0.68,
    "animationFps": {"selectedRow": 60, "wheelTilt": 60, "libraryList": 60, "infoPill": 60, "albumArtTransition": 60, "pathPill": 60, "rowInsertion": 60},
    "performanceOverlayButton": True, "performanceOverlayText": False,
    "liquidGlassElements": {
        "libraryList": {"material": -0.20},
        "wheel": {"material": -0.20},
        "pathPill": {"material": -0.20},
        "infoPill": {"material": -0.20},
        "listPills": {"material": 0.0},
        "selectedRow": {"material": -0.50},
    },
    "glassRenderScale": 1.0, "glassFrostSamples": 8, "glassIdleFps": 30, "glassInteractionFps": 60,
    "centerBounceAmount": 0.075, "centerBounceDuration": 240.0, "centerBounceOvershoot": 0.9,
    "wheelClickTiltAmount": 0.5, "wheelTiltRampDuration": 90.0, "wheelTiltReleaseDuration": 360.0,
    "infoPillDarkMultiplier": 1.0, "infoPillLightMultiplier": 1.0,
}

DEFAULT_UI_APP_SETTINGS: dict[str, Any] = {
    "UI_VISUALIZER": True, "UI_VISUALIZER_MAX_BRIGHTNESS_PCT": 60, "UI_VISUALIZER_FPS_LOCK": 30,
    "UI_VISUALIZER_FREQUENCY_RESPONSE": DEFAULT_UI_SETTINGS["visualizerFrequencyResponse"], "UI_VISUALIZER_ENERGY_RESPONSE": DEFAULT_UI_SETTINGS["visualizerEnergyResponse"], "UI_VISUALIZER_BEAT_RESPONSE": DEFAULT_UI_SETTINGS["visualizerBeatResponse"], "UI_VIDEO_AMBIENT": DEFAULT_UI_SETTINGS["videoAmbient"],
    "UI_TEXT_WHEEL_LABELS": "transparent", "UI_TEXT_PATH_PILL": "transparent", "UI_TEXT_INFO_PILL": "transparent", "UI_TEXT_ROWS": "transparent", "UI_TEXT_ROW_PILLS": "transparent", "UI_TEXT_SELECTED_ROW": "contrast", "UI_TEXT_SELECTED_ROW_PILLS": "contrast", "UI_TEXT_TRANSPARENCY": 0.68,
    "UI_ANIMATION_SELECTED_ROW_FPS": 60, "UI_ANIMATION_WHEEL_TILT_FPS": 60, "UI_ANIMATION_LIBRARY_LIST_FPS": 60, "UI_ANIMATION_INFO_PILL_FPS": 60, "UI_ANIMATION_ALBUM_ART_TRANSITION_FPS": 60, "UI_ANIMATION_PATH_PILL_FPS": 60, "UI_ANIMATION_ROW_INSERTION_FPS": 60,
    "UI_PERFORMANCE_OVERLAY_BUTTON": True, "UI_PERFORMANCE_OVERLAY_TEXT": False,
    "UI_GLASS_LIBRARY_LIST": DEFAULT_UI_SETTINGS["liquidGlassElements"]["libraryList"], "UI_GLASS_WHEEL": DEFAULT_UI_SETTINGS["liquidGlassElements"]["wheel"], "UI_GLASS_PATH_PILL": DEFAULT_UI_SETTINGS["liquidGlassElements"]["pathPill"], "UI_GLASS_INFO_PILL": DEFAULT_UI_SETTINGS["liquidGlassElements"]["infoPill"], "UI_GLASS_LIST_PILLS": DEFAULT_UI_SETTINGS["liquidGlassElements"]["listPills"], "UI_GLASS_SELECTED_ROW": DEFAULT_UI_SETTINGS["liquidGlassElements"]["selectedRow"],
    "UI_GLASS_RENDER_SCALE": 1.0, "UI_GLASS_FROST_SAMPLES": 8, "UI_GLASS_IDLE_FPS": 30, "UI_GLASS_INTERACTION_FPS": 60,
    "UI_CENTER_BOUNCE_AMOUNT": 0.075, "UI_CENTER_BOUNCE_DURATION": 240.0, "UI_CENTER_BOUNCE_OVERSHOOT": 0.9, "UI_WHEEL_CLICK_TILT_AMOUNT": 0.5, "UI_WHEEL_TILT_RAMP_DURATION": 90.0, "UI_WHEEL_TILT_RELEASE_DURATION": 360.0, "UI_INFO_PILL_DARK_MULTIPLIER": 1.0, "UI_INFO_PILL_LIGHT_MULTIPLIER": 1.0,
}

DEFAULT_APP_SETTINGS: dict[str, Any] = {'APP_NAME': 'DebriPod',
 'WHEEL_ROTATION_MAX_DEGREES': 15,
 'PLAYBACK_STREAMING_MODE': 'http',
 'RESULTS_PER_PAGE': 50,
 'MAX_FILES_PER_TORRENT': 50,
 'MAX_TORRENT_WAIT_SECONDS': 1800,
 'POLL_INTERVAL_SECONDS': 4,
 'REQUEST_TIMEOUT_SECONDS': 25,
 'STREAM_PROXY_ALLOWED_HOST_SUFFIXES': ['real-debrid.com',
                                        'download.real-debrid.com',
                                        'youtube.com',
                                        'googlevideo.com',
                                        'ytimg.com'],
 'SEARCH_STREAM_ROOT_ID': '__search_stream__',
 'SEARCH_STREAM_SESSION_TTL_SECONDS': 21600,
 'SEARCH_HISTORY_MAX_ITEMS': 50,
 'SEARCH_DISK_CACHE_TTL_SECONDS': 604800,
 'TASKS_POLL_MS': 1200,
 'MCP_PROTOCOL_VERSION': '2025-03-26',
 'MCP_SEARCH_RESULT_LIMIT': 20,
 'MCP_SSE_KEEPALIVE_SECONDS': 15,
 'MCP_SESSION_TTL_SECONDS': 43200,
 'LOCAL_INDEX_ENABLED': True,
 'LOCAL_INDEX_UPDATE_INTERVAL_SECONDS': 21600,
 'TORRENT_SEARCH_ENABLED_SOURCES': ['knaben',
                                    'bitsearch',
                                    'magnetz',
                                    'torlock',
                                    'bt4g',
                                    'torrentclaw',
                                    'torapi'],
 'TORRENT_SEARCH_MAX_CONCURRENT': 7,
 'TORRENT_SEARCH_REQUEST_TIMEOUT_SECONDS': 20,
 'YTDLP_SEARCH_MAX_CONCURRENT': 4,
 'YTDLP_CMD': 'yt-dlp',
 'YOUTUBE_DOWNLOAD_DIR': '',
 'YOUTUBE_STREAM_CACHE_SUBDIR': 'youtube_streams',
 'YOUTUBE_WEB_BASE': 'https://www.youtube.com',
 'YOUTUBE_SEARCH_LIMIT': 24,
 'YOUTUBE_CHANNEL_BROWSE_LIMIT': 0,
 'YOUTUBE_REQUEST_HEADERS': {'Accept-Language': 'en-US,en;q=0.9',
                             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like '
                                           'Gecko) Chrome/122.0 Safari/537.36'},
 'FFMPEG_PATH': 'ffmpeg',
 'FFPROBE_PATH': 'ffprobe',
 'AUDIO_TRANSCODE': '',
 'AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY': True,
 'REPLACE_ORIGINAL': True,
 'PRELOAD_NEXT_FOR_GAPLESS': True,
 'PRELOAD_NEXT_CHUNK_BYTES': 2097152,
 'VIDEO_BROWSER_TARGET_EXT': 'mp4',
 'REAL_DEBRID_API_KEY': '',
 'RD_BASE': 'https://api.real-debrid.com/rest/1.0',
 'DEBRID_PROVIDER': '',
 'ALLDEBRID_API_KEY': '',
 'ALLDEBRID_BASE': 'https://api.alldebrid.com',
 'PREMIUMIZE_API_KEY': '',
 'PREMIUMIZE_BASE': 'https://www.premiumize.me',
 'TORBOX_API_KEY': '',
 'TORBOX_BASE': 'https://api.torbox.app',
 'DOWNLOAD_DIR': '',
 'SOULSEEK_USERNAME': '',
 'SOULSEEK_PASSWORD': '',
 'SOULSEEK_DOWNLOAD_DIR': '',
 'SOULSEEK_LISTENING_PORT': 61000,
 'SOULSEEK_OBFUSCATED_PORT': 0,
 'SOULSEEK_SEARCH_TIMEOUT_SEC': 8,
 'SOULSEEK_SEARCH_MAX_RESULTS': 5000,
 'SOULSEEK_SEARCH_IDLE_STOP_SEC': 2.5,
 'SOULSEEK_SEARCH_HARD_MAX_SEC': 60,
 'AIOSLSK_LOGGING_ENABLED': False,
 'LASTFM_API_KEY': '',
 'LASTFM_API_SECRET': '',
 'LASTFM_SESSION_KEY': '',
 'LASTFM_USERNAME': '',
 'LASTFM_SESSION_UPDATED': 0,
 'LASTFM_CALLBACK_URL': '',
 'LASTFM_API_ROOT': 'https://ws.audioscrobbler.com/2.0/',
 'LASTFM_REQUEST_TIMEOUT_SECONDS': 12,
 'LIBRARY_FOLDERS': [],
 'SETUP_WIZARD_COMPLETE': False,
 'SETUP_SKIPPED_SERVICES': {}}

APP_SETTING_KEYS = set(DEFAULT_APP_SETTINGS)
NON_PERSISTED_APP_SETTING_KEYS: set[str] = set()
SECRET_SETTING_KEYS = {
    "REAL_DEBRID_API_KEY",
    "ALLDEBRID_API_KEY",
    "PREMIUMIZE_API_KEY",
    "TORBOX_API_KEY",
    "SOULSEEK_USERNAME",
    "SOULSEEK_PASSWORD",
    "LASTFM_API_KEY",
    "LASTFM_API_SECRET",
    "LASTFM_SESSION_KEY",
}

# Settings are deliberately classified at the boundary.  Device values never
# enter SQLite; server values are shared machine configuration controlled by
# the owner; all other known application settings are per-user.
SERVER_SETTING_KEYS = frozenset({
    "RD_BASE", "ALLDEBRID_BASE", "PREMIUMIZE_BASE", "TORBOX_BASE",
    "YOUTUBE_WEB_BASE", "LASTFM_API_ROOT", "LASTFM_CALLBACK_URL",
    "FFMPEG_PATH", "FFPROBE_PATH", "YTDLP_CMD",
    "LOCAL_INDEX_ENABLED", "LOCAL_INDEX_UPDATE_INTERVAL_SECONDS",
})
DEVICE_SETTING_KEYS = frozenset(DEFAULT_UI_APP_SETTINGS)
USER_SETTING_KEYS = frozenset(APP_SETTING_KEYS.difference(SERVER_SETTING_KEYS))
SETTING_DESCRIPTORS: dict[str, dict[str, str]] = {
    **{key: {"scope": "server"} for key in SERVER_SETTING_KEYS},
    **{key: {"scope": "user"} for key in USER_SETTING_KEYS},
    **{key: {"scope": "device"} for key in DEVICE_SETTING_KEYS},
    "PORT": {"scope": "server"},
    "ENABLE_MCP": {"scope": "server"},
    "MCP_TOKEN": {"scope": "server"},
}


def setting_scope(key: str) -> str | None:
    """Return the explicit persistence scope for a known setting key."""
    descriptor = SETTING_DESCRIPTORS.get(str(key or "").upper())
    return str(descriptor.get("scope")) if descriptor else None

def _user_settings_path(username: str) -> Path:
    raw = str(username or "").strip().lower()
    digest = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    return PACKAGE_ROOT / "data" / "users" / digest / "settings.json"


def default_app_settings(user_id: str | None = None, defaults_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(DEFAULT_APP_SETTINGS)
    for key, value in (defaults_overrides or {}).items():
        key_upper = str(key).upper()
        if key_upper in APP_SETTING_KEYS and key_upper not in SECRET_SETTING_KEYS:
            out[key_upper] = _coerce_setting(key_upper, value)
    if str(user_id or "").strip():
        out["LIBRARY_FOLDERS"] = []
    return out


def load_server_settings(defaults_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load machine-scoped settings without inheriting legacy user values."""
    out = {
        key: _coerce_setting(key, DEFAULT_APP_SETTINGS[key])
        for key in SERVER_SETTING_KEYS
    }
    for key, value in (defaults_overrides or {}).items():
        key_upper = str(key).upper()
        if key_upper in SERVER_SETTING_KEYS:
            out[key_upper] = _coerce_setting(key_upper, value)
    for key, value in settings_repository.load("").items():
        key_upper = str(key).upper()
        if key_upper in SERVER_SETTING_KEYS:
            out[key_upper] = _coerce_setting(key_upper, value)
    return out


def save_server_settings(
    updates: dict[str, Any],
    defaults_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist only the server-scoped subset in the shared SQLite row set."""
    raw = settings_repository.load("")
    for key, value in (updates or {}).items():
        key_upper = str(key).upper()
        if key_upper in SERVER_SETTING_KEYS:
            raw[key_upper] = _coerce_setting(key_upper, value)
    settings_repository.save(raw, "")
    return load_server_settings(defaults_overrides)


def migrate_owner_server_settings(
    user_id: str,
    defaults_overrides: dict[str, Any] | None = None,
) -> bool:
    """Move meaningful pre-scope owner settings into shared server storage.

    Earlier releases stored these machine-wide values with the owner account.
    Only non-default legacy values can win over an untouched shared default,
    which prevents a normal per-user default from replacing owner intent.
    """
    legacy = settings_repository.load(str(user_id or ""))
    shared_raw = settings_repository.load("")
    shared = load_server_settings(defaults_overrides)
    defaults = {
        key: _coerce_setting(key, (defaults_overrides or {}).get(key, DEFAULT_APP_SETTINGS[key]))
        for key in SERVER_SETTING_KEYS
    }
    changed = False
    for key in SERVER_SETTING_KEYS:
        if key not in legacy:
            continue
        candidate = _coerce_setting(key, legacy[key])
        if candidate != defaults[key] and shared.get(key) == defaults[key]:
            shared_raw[key] = candidate
            changed = True
    if changed:
        settings_repository.save(shared_raw, "")
    return changed


def ui_setting_updates(value: Any) -> dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    text = src.get("textModes") if isinstance(src.get("textModes"), dict) else {}
    animation = src.get("animationFps") if isinstance(src.get("animationFps"), dict) else {}
    glass = src.get("liquidGlassElements") if isinstance(src.get("liquidGlassElements"), dict) else {}
    out = {"UI_VISUALIZER": src.get("visualizer"), "UI_VISUALIZER_MAX_BRIGHTNESS_PCT": src.get("visualizerMaxBrightnessPct"), "UI_VISUALIZER_FPS_LOCK": src.get("visualizerFpsLock"), "UI_TEXT_TRANSPARENCY": src.get("textTransparency"), "UI_PERFORMANCE_OVERLAY_BUTTON": src.get("performanceOverlayButton"), "UI_PERFORMANCE_OVERLAY_TEXT": src.get("performanceOverlayText"), "UI_CENTER_BOUNCE_AMOUNT": src.get("centerBounceAmount"), "UI_CENTER_BOUNCE_DURATION": src.get("centerBounceDuration"), "UI_CENTER_BOUNCE_OVERSHOOT": src.get("centerBounceOvershoot"), "UI_WHEEL_CLICK_TILT_AMOUNT": src.get("wheelClickTiltAmount"), "UI_WHEEL_TILT_RAMP_DURATION": src.get("wheelTiltRampDuration"), "UI_WHEEL_TILT_RELEASE_DURATION": src.get("wheelTiltReleaseDuration"), "UI_INFO_PILL_DARK_MULTIPLIER": src.get("infoPillDarkMultiplier"), "UI_INFO_PILL_LIGHT_MULTIPLIER": src.get("infoPillLightMultiplier"), "UI_TEXT_WHEEL_LABELS": text.get("wheelLabels"), "UI_TEXT_PATH_PILL": text.get("pathPill"), "UI_TEXT_INFO_PILL": text.get("infoPill"), "UI_TEXT_ROWS": text.get("rows"), "UI_TEXT_ROW_PILLS": text.get("rowPills"), "UI_TEXT_SELECTED_ROW": text.get("selectedRow"), "UI_TEXT_SELECTED_ROW_PILLS": text.get("selectedRowPills"), "UI_ANIMATION_SELECTED_ROW_FPS": animation.get("selectedRow"), "UI_ANIMATION_WHEEL_TILT_FPS": animation.get("wheelTilt"), "UI_ANIMATION_LIBRARY_LIST_FPS": animation.get("libraryList"), "UI_ANIMATION_INFO_PILL_FPS": animation.get("infoPill"), "UI_ANIMATION_ALBUM_ART_TRANSITION_FPS": animation.get("albumArtTransition"), "UI_ANIMATION_PATH_PILL_FPS": animation.get("pathPill"), "UI_ANIMATION_ROW_INSERTION_FPS": animation.get("rowInsertion"), "UI_GLASS_LIBRARY_LIST": glass.get("libraryList"), "UI_GLASS_WHEEL": glass.get("wheel"), "UI_GLASS_PATH_PILL": glass.get("pathPill"), "UI_GLASS_INFO_PILL": glass.get("infoPill"), "UI_GLASS_LIST_PILLS": glass.get("listPills"), "UI_GLASS_SELECTED_ROW": glass.get("selectedRow")}
    return {key: item for key, item in out.items() if item is not None}


def _settings_path(user_id: str | None = None) -> Path:
    user_id = str(user_id or "").strip()
    if user_id:
        # This path is only retained to import pre-database JSON settings. New
        # user-owned settings live in SQLite under the immutable user ID.
        return _user_settings_path(user_id)
    return SETTINGS_PATH


def settings_fingerprint(user_id: str | None = None) -> tuple[int, int]:
    return settings_repository.fingerprint(str(user_id or ""))


def _coerce_setting(key: str, value: Any) -> Any:
    default = DEFAULT_APP_SETTINGS.get(key)
    if key.startswith("UI_TEXT_") and key != "UI_TEXT_TRANSPARENCY":
        clean = str(value or "").strip().lower()
        if clean in {"black", "white", "engraved"}:
            return "contrast"
        return clean if clean in {"contrast", "transparent"} else str(default or "transparent")
    if key == "DEBRID_PROVIDER":
        clean = str(value or "").strip().lower()
        return clean if clean in {"", "real_debrid", "alldebrid", "premiumize", "torbox"} else ""
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
                    if path:
                        out.append({"path": path, "mode": "meta"})
        return out
    if key == "TORRENT_SEARCH_ENABLED_SOURCES":
        values = value if isinstance(value, list) else (str(value or "").split(",") if isinstance(value, str) else [])
        normalized = (str(item).strip().casefold() for item in values)
        return list(dict.fromkeys(item for item in normalized if item in REMOTE_TORRENT_SOURCE_IDS))
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


def normalize_settings(data: dict[str, Any], user_id: str | None = None, defaults_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    out = default_app_settings(user_id, defaults_overrides=defaults_overrides)
    for key, value in (data or {}).items():
        key_upper = str(key).upper()
        if key_upper in APP_SETTING_KEYS:
            out[key_upper] = _coerce_setting(key_upper, value)
    return out


def _persistable_settings(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in data.items()
        if key in USER_SETTING_KEYS
        and key not in NON_PERSISTED_APP_SETTING_KEYS
        and key not in SECRET_SETTING_KEYS
    }


def _secret_service(key: str, values: dict[str, Any]) -> str:
    if key in {"REAL_DEBRID_API_KEY", "ALLDEBRID_API_KEY", "PREMIUMIZE_API_KEY", "TORBOX_API_KEY"}:
        provider = key.removesuffix("_API_KEY").lower()
        return f"DEBRID_TOKEN:{provider}"
    return key


def _load_saved_secrets(values: dict[str, Any], user_id: str | None) -> None:
    user_id = str(user_id or "global")
    status = saved_status(user_id)
    for key in SECRET_SETTING_KEYS:
        service = _secret_service(key, values)
        values[key] = get_secret(user_id, service) if bool((status.get(service) or {}).get("saved")) else ""


def _save_secret_updates(updates: dict[str, Any], current: dict[str, Any], user_id: str | None) -> None:
    user_id = str(user_id or "global")
    for key, value in updates.items():
        key_upper = str(key).upper()
        if key_upper not in SECRET_SETTING_KEYS or value == "***":
            continue
        clean = _coerce_setting(key_upper, value)
        set_secret(user_id, _secret_service(key_upper, current), str(clean), provider_identity=str(current.get("DEBRID_PROVIDER") or ""))
        current[key_upper] = clean


def migrate_user_secrets(legacy_username: str, user_id: str) -> None:
    """Copy legacy username-keyed secrets to a stable user ID once.

    Keyring contents cannot be migrated by an SQLite schema transaction, so
    this deliberately best-effort bridge runs when a user runtime is created.
    A failed or unavailable keyring never destroys the legacy secret.
    """
    old_scope = str(legacy_username or "").strip()
    new_scope = str(user_id or "").strip()
    if not old_scope or not new_scope or old_scope == new_scope:
        return
    services = {_secret_service(key, {}) for key in SECRET_SETTING_KEYS}
    try:
        services.update(saved_status(old_scope).keys())
    except Exception:
        pass
    for service in services:
        try:
            value = get_secret(old_scope, service)
            if value:
                set_secret(new_scope, service, value)
                set_secret(old_scope, service, "")
        except Exception:
            continue


def ensure_app_settings(
    startup_config: dict[str, Any] | None = None,
    user_id: str | None = None,
    defaults_overrides: dict[str, Any] | None = None,
    *,
    legacy_username: str | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    """Load settings for a stable user ID.

    ``username`` is an intentionally narrow compatibility input for callers
    upgrading from the old API. Runtime request paths pass only ``user_id``.
    ``legacy_username`` is used solely to import a retired JSON settings file.
    """
    if user_id is None and username is not None:
        user_id = username
    scope = str(user_id or "").strip()
    path = _settings_path(scope)
    legacy_path = path
    raw = settings_repository.load(scope)
    changed = not bool(raw)
    legacy_value = read_legacy_json(path)
    if not legacy_value and legacy_username:
        legacy_path = _user_settings_path(str(legacy_username))
        legacy_value = read_legacy_json(legacy_path)
    legacy = legacy_value if isinstance(legacy_value, dict) else {}
    if legacy and not raw:
        raw = dict(legacy)
        changed = True
    old_ui_defaults = raw.pop("ADVANCED_UI_SETTINGS_DEFAULTS", None)
    old_ui_settings = raw.pop("UI_SETTINGS", None)
    # UI visual and performance preferences are device-local now.  Retire
    # legacy server payloads rather than copying them into app_settings.
    if isinstance(old_ui_settings, dict) or isinstance(old_ui_defaults, dict):
        changed = True
    merged = dict(raw)
    if not scope:
        for key, value in (startup_config or {}).items():
            key_upper = str(key).upper()
            if key_upper in APP_SETTING_KEYS and key_upper not in merged:
                merged[key_upper] = value
                changed = True
    normalized = normalize_settings(merged, user_id=scope, defaults_overrides=defaults_overrides)
    legacy_secrets = {key: normalized.get(key) for key in SECRET_SETTING_KEYS if normalized.get(key)}
    if legacy_secrets:
        _save_secret_updates(legacy_secrets, normalized, scope)
    if not str(normalized.get("DEBRID_PROVIDER") or "").strip():
        if str(normalized.get("REAL_DEBRID_API_KEY") or "").strip():
            normalized["DEBRID_PROVIDER"] = "real_debrid"
            changed = True
    if scope:
        normalized.update(load_server_settings(defaults_overrides))
    persisted = _persistable_settings(normalized) if scope else {
        key: value for key, value in normalized.items()
        if key not in NON_PERSISTED_APP_SETTING_KEYS and key not in SECRET_SETTING_KEYS and key not in DEVICE_SETTING_KEYS
    }
    if changed or persisted != raw:
        settings_repository.save(persisted, scope)
    if legacy and legacy_path.is_file():
        try:
            retire_legacy(legacy_path)
        except OSError:
            pass
    _load_saved_secrets(normalized, scope)
    return normalized


def save_app_settings(
    updates: dict[str, Any],
    user_id: str | None = None,
    defaults_overrides: dict[str, Any] | None = None,
    *,
    username: str | None = None,
) -> dict[str, Any]:
    if user_id is None and username is not None:
        user_id = username
    scope = str(user_id or "").strip()
    current = ensure_app_settings(user_id=scope, defaults_overrides=defaults_overrides)
    _save_secret_updates(updates, current, scope)
    for key, value in (updates or {}).items():
        key_upper = str(key).upper()
        if key_upper in USER_SETTING_KEYS and key_upper not in NON_PERSISTED_APP_SETTING_KEYS and key_upper not in SECRET_SETTING_KEYS:
            current[key_upper] = _coerce_setting(key_upper, value)
    current = normalize_settings(current, user_id=scope, defaults_overrides=defaults_overrides)
    settings_repository.save(_persistable_settings(current), scope)
    _load_saved_secrets(current, scope)
    return current


def masked_settings(data: dict[str, Any]) -> dict[str, Any]:
    out = normalize_settings(data)
    for key in SECRET_SETTING_KEYS:
        if out.get(key):
            out[key] = ""
            out[f"{key}_SAVED"] = True
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
