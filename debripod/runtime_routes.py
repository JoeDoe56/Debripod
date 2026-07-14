from __future__ import annotations

import ipaddress
import json
import re
import base64
import zlib
import secrets
import socket
import time
import concurrent.futures
import threading
from pathlib import Path
from urllib.parse import unquote

from flask import g, session, stream_with_context

from . import runtime_downloads as downloads_module
from . import runtime_route_state as route_state_module
from . import runtime_state as state_module
from .Services import lastfm as lastfm_module
from .Services import soulseek as soulseek_module
from .factory import DeferredApp
from .auth import register_auth
from .config import _coerce_config_value, ensure_startup_security_config, load_default_app_config_overrides, save_config, save_default_app_config_overrides
from .Library.library_db import load_folder_entries, load_palette, load_palette_for_media, load_visualizer_analysis_for_media, save_folder_entries, save_palette
from .Library.index import build_index_for_root, set_index_cache
from .Library.metadata import file_meta_cached
from .Library.video_parse import duration_text, normalize_show_key, show_keys_close
from .Library.library_db import load_show_aliases, save_show_aliases
from .Library.search_ranker import infer_query_intent, normalize_search_text, rank_combined_results, source_priority_for_intent
from .storage.tasks import save_task_metadata
from .storage.palettes import load_video_timeline
from .Services.debrid import DebridAuthError, DebridProviderError, get_active_provider, get_provider, provider_specs, provider_status as debrid_provider_status
from .Tasks.manager import task_belongs_to_owner
from .runtime_state import *
from .runtime_downloads import *
from .settings import APP_SETTING_KEYS, DEFAULT_APP_SETTINGS, DEFAULT_UI_SETTINGS, SECRET_SETTING_KEYS, default_app_settings, executable_status, ensure_app_settings, masked_settings, pick_system_path, save_app_settings, settings_fingerprint

# =========================
# Flask app and templates
# =========================
app = DeferredApp()
_ACTIVE_SETTINGS_USERNAME = ""
_ACTIVE_SETTINGS_SIGNATURE: tuple[int, int] = (0, 0)
_ACTIVE_SETTINGS_DATA: dict[str, Any] = {}
_RECENT_API_TIMINGS: list[dict[str, Any]] = []
_FULL_REINDEX_LOCK = threading.Lock()
_FULL_REINDEX_STATUS: dict[str, Any] = {
    "running": False,
    "percent": 0,
    "phase": "idle",
    "root": "",
    "processed_roots": 0,
    "total_roots": 0,
    "started_at": 0.0,
    "finished_at": 0.0,
    "error": "",
}


from .runtime_route_state import *
from .MCP import routes as mcp_routes


app.config["SECRET_KEY"] = os.urandom(24)
register_icon_routes(app)
register_lastfm_routes(
    app,
    api_key_provider=lambda: LASTFM_API_KEY,
    api_secret_provider=lambda: LASTFM_API_SECRET,
)
register_task_routes(app)


def _current_settings_username() -> str:
    try:
        return str(session.get("username") or "").strip()
    except Exception:
        return ""


def _default_app_overrides() -> dict[str, Any]:
    return load_default_app_config_overrides()


def _shutdown_soulseek_service() -> None:
    service = getattr(state_module, "SOULSEEK_SERVICE", None)
    if service:
        try:
            service.shutdown()
        except Exception:
            pass
    state_module.SOULSEEK_SERVICE = None
    globals()["SOULSEEK_SERVICE"] = None
    for module in (downloads_module, route_state_module, mcp_routes):
        if hasattr(module, "SOULSEEK_SERVICE"):
            setattr(module, "SOULSEEK_SERVICE", None)


def _start_soulseek_service_for_active_settings() -> None:
    username = str(SOULSEEK_USERNAME or "").strip()
    password = str(SOULSEEK_PASSWORD or "").strip()
    if not username or not password:
        _shutdown_soulseek_service()
        return
    current = getattr(state_module, "SOULSEEK_SERVICE", None)
    if (
        current
        and getattr(current, "username", "") == username
        and getattr(current, "password", "") == password
        and getattr(current, "download_dir", "") == os.path.abspath(SOULSEEK_DOWNLOAD_DIR)
        and int(getattr(current, "listening_port", 0) or 0) == int(SOULSEEK_LISTENING_PORT or 0)
        and int(getattr(current, "obfuscated_port", 0) or 0) == int(SOULSEEK_OBFUSCATED_PORT or 0)
        and int(getattr(current, "search_timeout_sec", 0) or 0) == int(SOULSEEK_SEARCH_TIMEOUT_SEC or 0)
        and int(getattr(current, "search_max_results", 0) or 0) == int(SOULSEEK_SEARCH_MAX_RESULTS or 0)
    ):
        return
    _shutdown_soulseek_service()
    try:
        service = SoulseekService(
            username=username,
            password=password,
            download_dir=SOULSEEK_DOWNLOAD_DIR,
            listening_port=SOULSEEK_LISTENING_PORT,
            obfuscated_port=SOULSEEK_OBFUSCATED_PORT,
            search_timeout_sec=SOULSEEK_SEARCH_TIMEOUT_SEC,
            search_max_results=SOULSEEK_SEARCH_MAX_RESULTS,
        )
    except Exception:
        service = None
    state_module.SOULSEEK_SERVICE = service
    globals()["SOULSEEK_SERVICE"] = service
    for module in (downloads_module, route_state_module, mcp_routes):
        if hasattr(module, "SOULSEEK_SERVICE"):
            setattr(module, "SOULSEEK_SERVICE", service)


def _clear_active_user_runtime_settings() -> None:
    global _ACTIVE_SETTINGS_DATA, _ACTIVE_SETTINGS_SIGNATURE, _ACTIVE_SETTINGS_USERNAME
    if not _ACTIVE_SETTINGS_USERNAME:
        return
    settings = default_app_settings()
    modules = (state_module, downloads_module, route_state_module, mcp_routes)
    for key, raw_value in settings.items():
        key_upper = str(key).upper()
        if key_upper not in CONFIG_KEYS:
            continue
        value = _coerce_config_value(key_upper, raw_value)
        globals()[key_upper] = value
        for module in modules:
            if hasattr(module, key_upper):
                setattr(module, key_upper, value)
    _shutdown_soulseek_service()
    try:
        lastfm_module.reset_lastfm_runtime_state()
    except Exception:
        pass
    try:
        with route_state_module.SEARCH_STREAMS_LOCK:
            route_state_module.SEARCH_STREAMS.clear()
    except Exception:
        pass
    try:
        with soulseek_module._SLSK_SESS_LOCK:
            soulseek_module._SLSK_SESSIONS.clear()
    except Exception:
        pass
    _ACTIVE_SETTINGS_USERNAME = ""
    _ACTIVE_SETTINGS_SIGNATURE = (0, 0)
    _ACTIVE_SETTINGS_DATA = {}


def _apply_runtime_settings_for_user(username: str, force: bool = False) -> dict[str, Any]:
    global _ACTIVE_SETTINGS_DATA, _ACTIVE_SETTINGS_SIGNATURE, _ACTIVE_SETTINGS_USERNAME
    if not username:
        return {}
    signature = settings_fingerprint(username)
    if (
        not force
        and _ACTIVE_SETTINGS_USERNAME == username
        and _ACTIVE_SETTINGS_SIGNATURE == signature
        and _ACTIVE_SETTINGS_DATA
    ):
        return dict(_ACTIVE_SETTINGS_DATA)
    settings = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    signature = settings_fingerprint(username)
    modules = (state_module, downloads_module, route_state_module, mcp_routes)
    for key, raw_value in settings.items():
        key_upper = str(key).upper()
        if key_upper not in CONFIG_KEYS:
            continue
        value = _coerce_config_value(key_upper, raw_value)
        globals()[key_upper] = value
        for module in modules:
            if hasattr(module, key_upper):
                setattr(module, key_upper, value)
    try:
        state_module.ensure_dirs()
    except Exception:
        pass
    try:
        soulseek_module.configure_soulseek_module(
            download_dir=SOULSEEK_DOWNLOAD_DIR,
            search_idle_stop_sec=SOULSEEK_SEARCH_IDLE_STOP_SEC,
            search_hard_max_sec=SOULSEEK_SEARCH_HARD_MAX_SEC,
            tasks=TASKS,
            tasks_lock=TASKS_LOCK,
            get_task_func=get_task,
            set_task_func=set_task,
            set_file_control_func=_set_file_control,
            get_file_control_func=_get_file_control,
        )
    except Exception:
        pass
    _start_soulseek_service_for_active_settings()
    if _ACTIVE_SETTINGS_USERNAME != username:
        load_playback_state()
        try:
            with route_state_module.SEARCH_STREAMS_LOCK:
                route_state_module.SEARCH_STREAMS.clear()
        except Exception:
            pass
        try:
            with soulseek_module._SLSK_SESS_LOCK:
                soulseek_module._SLSK_SESSIONS.clear()
        except Exception:
            pass
        _ACTIVE_SETTINGS_USERNAME = username
    _ACTIVE_SETTINGS_SIGNATURE = signature
    _ACTIVE_SETTINGS_DATA = dict(settings)
    return settings


@app.before_request
def apply_user_settings_before_request():
    try:
        g.dp_request_started_at = time.perf_counter()
    except Exception:
        pass
    username = _current_settings_username()
    if username:
        _apply_runtime_settings_for_user(username)
    else:
        _clear_active_user_runtime_settings()


def add_request_timing_headers(resp):
    try:
        elapsed_ms = (time.perf_counter() - float(getattr(g, "dp_request_started_at", time.perf_counter()))) * 1000.0
        path = request.path or ""
        if path.startswith("/static/") and request.args.get("v"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        if path.startswith("/api/") or path.startswith("/hls/") or path.startswith("/stream/"):
            resp.headers["X-DebriPod-Request-Ms"] = f"{elapsed_ms:.1f}"
        if path.startswith("/api/"):
            _RECENT_API_TIMINGS.append({
                "method": request.method,
                "path": path,
                "status": int(getattr(resp, "status_code", 0) or 0),
                "ms": round(elapsed_ms, 1),
                "ts": time.time(),
            })
            del _RECENT_API_TIMINGS[:-60]
        if elapsed_ms >= 750 and path.startswith("/api/"):
            app.logger.info("slow endpoint %s %.1fms", path, elapsed_ms)
    except Exception:
        pass
    return resp


@app.context_processor
def inject_helpers():
    return {"human_bytes": human_bytes, "human_rate": human_rate}


def render_shell(autorefresh: int = 0, **ctx) -> str:
    try:
        hostport = request.host
    except Exception:
        hostport = f"localhost:{PORT}"
    version_info = dict(VERSION_INFO)
    version_info.update({"version": VERSION, "host": HOST, "port": PORT})
    info_json = json.dumps(version_info)
    return render_template(
        "shell.html",
        hostport=hostport,
        port=PORT,
        ddir=DOWNLOAD_DIR,
        autorefresh=autorefresh,
        tasks_poll_ms=TASKS_POLL_MS,
        icon_v=ICON_VERSION,
        asset_v=ASSET_VERSION,
        info_json=info_json,
        ui_defaults=DEFAULT_UI_SETTINGS,
        **ctx,
    )
register_shell_routes(app, render_shell)


def _pwa_shell_assets() -> list[str]:
    base = [
        "/",
        f"/site.webmanifest?v={ICON_VERSION}",
        f"/favicon.ico?v={ICON_VERSION}",
        f"/apple-touch-icon.png?v={ICON_VERSION}",
        f"/apple-touch-icon-precomposed.png?v={ICON_VERSION}",
        f"/static/debripod.css?v={ASSET_VERSION}",
        f"/static/debripod.js?v={ASSET_VERSION}",
        f"/static/liquidGL.js?v={ASSET_VERSION}",
        f"/static/vendor/hls-local.js?v={ASSET_VERSION}",
        f"/static/fonts/inter-4.1/InterVariable.woff2?v={ASSET_VERSION}",
        f"/static/fonts/inter-4.1/InterVariable-Italic.woff2?v={ASSET_VERSION}",
    ]
    js_dir = Path(__file__).resolve().parent / "static" / "js"
    try:
        for path in sorted(js_dir.glob("*.js")):
            base.append(f"/static/js/{path.name}?v={ASSET_VERSION}")
    except Exception:
        pass
    return base


@app.route("/debripod-sw.js", methods=["GET"])
def debripod_service_worker():
    path = Path(__file__).resolve().parent / "static" / "debripod-sw.js"
    text = path.read_text(encoding="utf-8")
    text = text.replace("__DEBRIPOD_ASSET_VERSION__", str(ASSET_VERSION))
    text = text.replace("__DEBRIPOD_ICON_VERSION__", str(ICON_VERSION))
    text = text.replace("__DEBRIPOD_SHELL_ASSETS__", json.dumps(_pwa_shell_assets(), ensure_ascii=False))
    resp = Response(text, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


def _search_knaben_cached(q: str, page: int = 1) -> Tuple[List[dict], str, str, str, str]:
    extra = {"page": int(page or 1)}
    cache_key = _make_search_cache_key("knaben", q, extra)
    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")
    if cached_payload is not None:
        results = cached_payload.get("results") or []
        err = cached_payload.get("error") or ""
        remaining = cached_payload.get("remaining") or ""
        reset = cached_payload.get("reset") or ""
    else:
        results, err, remaining, reset = knaben_search(q, int(page or 1))
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "knaben", q, extra, {"results": results, "error": err, "remaining": remaining, "reset": reset})
    return results, err, remaining, reset, cache_key


def _search_soulseek_cached(q: str) -> Tuple[List[Dict[str, Any]], int, int, str, str]:
    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key("soulseek", q, extra)
    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")
    slsk_users: List[Dict[str, Any]] = []
    slsk_total_results = 0
    dir_count = 0
    err = ""
    if cached_payload is not None:
        slsk_users = cached_payload.get("slsk_users") or []
        try:
            slsk_total_results = int(cached_payload.get("slsk_total_results") or 0)
        except Exception:
            slsk_total_results = sum(int(u.get("total_files") or 0) for u in (slsk_users or []))
        try:
            dir_count = int(cached_payload.get("dir_count") or 0)
        except Exception:
            dir_count = sum(len(u.get("dirs") or []) for u in (slsk_users or []))
    else:
        svc = SOULSEEK_SERVICE
        if not svc or not svc.is_ready():
            start_error = str(svc.start_error() or "") if svc else ""
            suffix = f": {start_error}" if start_error else ""
            return [], 0, 0, cache_key, "Soulseek service is not ready" + suffix
        try:
            items = svc.search(q)
        except Exception:
            return [], 0, 0, cache_key, "Soulseek search failed"
        users: Dict[str, Dict[str, Any]] = {}
        for it in items:
            user = (it.get("user") or "").strip()
            rp = str(it.get("remote_path") or "")
            size = int(it.get("size") or 0)
            speed = int(it.get("speed") or 0)
            if not user or not rp:
                continue
            rp_norm = _slsk_norm_remote_path(rp)
            parts = rp_norm.split("\\")
            fname = parts[-1] if parts else rp_norm
            directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
            kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)
            u = users.get(user)
            if not u:
                u = {"user": user, "speed": speed, "dirs": {}, "total_size": 0, "total_files": 0}
                users[user] = u
            u["speed"] = max(int(u.get("speed") or 0), speed)
            d2 = (u.get("dirs") or {}).get(directory)
            if not d2:
                d2 = {"directory": directory, "files": [], "total_size": 0, "total_files": 0}
                (u.get("dirs") or {})[directory] = d2
                u["dirs"] = u.get("dirs") or {}
                u["dirs"][directory] = d2
            file_obj = {
                "name": fname, "remote_path": rp_norm, "size": size, "kind": kind, "ext": ext,
                "bitrate": br, "bit_depth": bd, "sample_rate": sr, "duration": dur, "vbr": vbr, "codec": codec,
            }
            file_obj = _slsk_annotate_file_with_download_state(file_obj, user)
            d2["files"].append(file_obj)
            d2["total_size"] += size
            d2["total_files"] = int(d2.get("total_files") or 0) + 1
            u["total_size"] = int(u.get("total_size") or 0) + size
            u["total_files"] = int(u.get("total_files") or 0) + 1
        for u in users.values():
            dirs_list = list((u.get("dirs") or {}).values())
            dirs_list.sort(key=lambda d: (int(d.get("total_size") or 0), len(d.get("files") or [])), reverse=True)
            slsk_users.append({"user": u.get("user") or "", "speed": int(u.get("speed") or 0), "dirs": dirs_list, "total_size": int(u.get("total_size") or 0), "total_files": int(u.get("total_files") or 0)})
        slsk_users.sort(key=lambda u: (int(u.get("speed") or 0), int(u.get("total_size") or 0), str(u.get("user") or "").lower()), reverse=True)
        slsk_total_results = sum(int(u.get("total_files") or 0) for u in slsk_users)
        dir_count = sum(len(u.get("dirs") or []) for u in (slsk_users or []))
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "soulseek", q, extra, {"slsk_users": slsk_users, "slsk_total_results": slsk_total_results, "file_count": slsk_total_results, "dir_count": dir_count})
    return slsk_users, slsk_total_results, dir_count, cache_key, err


def _quality_text_from_attrs(bit_depth: Any, sample_rate: Any, bitrate: Any) -> str:
    parts: List[str] = []
    try:
        bd = int(bit_depth or 0)
    except Exception:
        bd = 0
    try:
        sr = int(sample_rate or 0)
    except Exception:
        sr = 0
    br = bitrate
    if bd > 0:
        parts.append(f"{bd} bit")
    if sr > 0:
        parts.append(f"{round(sr / 1000.0, 1):g} kHz")
    if br:
        try:
            parts.append(f"{int(br)} kbps")
        except Exception:
            parts.append(str(br))
    return " ".join(parts)


def _standardize_knaben_results(raw_results: List[dict]) -> List[dict]:
    out: List[dict] = []
    for r in raw_results or []:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        size = r.get("size")
        try:
            size = int(size) if size is not None else 0
        except Exception:
            size = 0
        seeders = r.get("seeders")
        leechers = r.get("leechers")
        out.append({
            "result_id": "knaben:" + str(r.get("id") or r.get("infohash") or sha1_text(title)),
            "source": "knaben",
            "source_label": "Knaben",
            "user": "",
            "title": title,
            "directory": "",
            "directory_title": title,
            "file_count": 0,
            "size": size,
            "speed": 0,
            "seeders": int(seeders) if isinstance(seeders, int) else 0,
            "leechers": int(leechers) if isinstance(leechers, int) else 0,
            "browse_available": False,
            "stream_available": True,
            "download_available": True,
            "files_loaded": False,
            "files": [],
            "magnet": str(r.get("magnet") or ""),
            "infohash": str(r.get("infohash") or ""),
            "category": str(r.get("category") or ""),
            "verified": bool(r.get("verified")),
            "href": str(r.get("href") or ""),
        })
    return out


def _standardize_soulseek_results(slsk_users: List[Dict[str, Any]]) -> List[dict]:
    out: List[dict] = []
    for u in slsk_users or []:
        user = str(u.get("user") or "").strip()
        speed = int(u.get("speed") or 0)
        for d in (u.get("dirs") or []):
            directory = str(d.get("directory") or "").strip()
            files_std: List[dict] = []
            for f in (d.get("files") or []):
                if not isinstance(f, dict):
                    continue
                files_std.append({
                    "name": str(f.get("name") or ""),
                    "title": str(f.get("name") or ""),
                    "ext": str(f.get("ext") or "").lower(),
                    "quality": _quality_text_from_attrs(f.get("bit_depth"), f.get("sample_rate"), f.get("bitrate")),
                    "bitrate": (str(int(f.get("bitrate"))) + " kbps") if f.get("bitrate") else "",
                    "size": int(f.get("size") or 0),
                    "remote_path": str(f.get("remote_path") or ""),
                    "bit_depth": int(f.get("bit_depth") or 0) if f.get("bit_depth") else 0,
                    "sample_rate": int(f.get("sample_rate") or 0) if f.get("sample_rate") else 0,
                    "download_state": str(f.get("download_state") or ""),
                    "codec": str(f.get("codec") or ""),
                    "source": "soulseek",
                })
            base = directory.split("\\")[-1] if directory else ""
            out.append({
                "result_id": "soulseek:" + sha1_text(user + "|" + directory),
                "source": "soulseek",
                "source_label": "Soulseek",
                "user": user,
                "title": base or directory or user or "Soulseek",
                "directory": directory,
                "directory_title": base or directory,
                "file_count": len(files_std),
                "size": int(d.get("total_size") or 0),
                "speed": speed,
                "seeders": 0,
                "leechers": 0,
                "browse_available": True,
                "stream_available": False,
                "download_available": True,
                "files_loaded": True,
                "files": files_std,
            })
    return out


COMBINED_SEARCH_SOURCES = ("library", "soulseek", "knaben", "youtube")


def _library_file_payload(record: dict, media: str) -> dict:
    rel = str(record.get("rel") or "")
    name = str(record.get("name") or os.path.basename(rel))
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    return {
        "name": name, "title": str(record.get("title") or name), "root_id": str(record.get("root_id") or ""),
        "rel": rel, "media": media, "source": "library", "ext": ext,
        "quality": str(record.get("quality") or _quality_text_from_attrs(record.get("bit_depth"), record.get("sample_rate"), record.get("bitrate"))),
        "codec": str(record.get("codec") or ""), "bit_depth": record.get("bit_depth") or 0,
        "sample_rate": record.get("sample_rate") or 0, "bitrate": record.get("bitrate") or 0,
        "size": int(record.get("size") or 0),
    }


def _standardize_library_record(record: dict, media: str) -> dict:
    file = _library_file_payload(record, media)
    title = str(record.get("title") or record.get("name") or "")
    artist = str(record.get("artist") or "") if media == "audio" else ""
    album = str(record.get("album") or "") if media == "audio" else ""
    rel, root_id = file["rel"], file["root_id"]
    progress = media_progress_for(root_id, rel) if media == "video" else {}
    return {
        "result_id": "library:" + root_id + ":" + sha1_text(rel), "source": "library", "source_label": "Library",
        "root_id": root_id, "rel": rel, "media": media, "title": title, "directory_title": title or file["name"],
        "directory": os.path.dirname(rel).replace("\\", "/"), "user": artist, "artist": artist, "album": album,
        "name": file["name"], "size": int(record.get("size") or 0), "speed": 0, "seeders": 0, "leechers": 0,
        "browse_available": False, "stream_available": True, "download_available": False, "files_loaded": True,
        "file_count": 1, "quality": file["quality"], "files": [file],
        "position": float(progress.get("position") or record.get("position") or 0), "duration": float(progress.get("duration") or record.get("duration") or 0),
        "completion": float(progress.get("completion_percent") or record.get("completion_percent") or 0), "browser_label": str(record.get("browser_label") or title),
    }


def _search_library_indexed(q: str) -> tuple[list[dict], str]:
    qnorm = normalize_search_text(q)
    tokens = set(qnorm.split())
    audio_candidates: list[dict] = []
    video_candidates: list[dict] = []
    albums: dict[tuple[str, str, str], list[dict]] = {}
    for root in root_objects():
        root_id, root_abs = str(root.get("id") or ""), str(root.get("path") or "")
        snapshot = get_index(root_id)
        if snapshot is None:
            ensure_index_async(root_id, root_abs, mode="metadata")
            continue
        for track in snapshot.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            item = dict(track); item["root_id"] = root_id
            title = normalize_search_text(item.get("title") or item.get("name") or "")
            artist = normalize_search_text(item.get("artist") or item.get("album_artist") or "")
            album = normalize_search_text(item.get("album") or "")
            artist_title = normalize_search_text(f"{artist} {title}")
            album_artist = normalize_search_text(f"{artist} {album}")
            artist_words = set(artist.split())
            artist_match = bool(qnorm and (qnorm == artist or (tokens and tokens.issubset(artist_words))))
            album_match = bool(qnorm and (qnorm in album_artist or (tokens and tokens.issubset(set(album_artist.split())))))
            # Artist/album searches should surface albums.  Individual tracks
            # are reserved for exact or near-exact song searches, avoiding a
            # wall of songs when the user asks for an artist.
            if artist_match or album_match:
                albums.setdefault((root_id, str(item.get("artist") or ""), str(item.get("album") or "")), []).append(item)
            song_close = bool(qnorm and (
                qnorm == title or qnorm == artist_title or
                (len(tokens) > 1 and (qnorm in title or qnorm in artist_title))
            ))
            if song_close:
                audio_candidates.append(item)
        all_videos: list[dict] = list(snapshot.get("videos") or []) + list(snapshot.get("movies") or [])
        for show in snapshot.get("shows") or []:
            if isinstance(show, dict):
                all_videos.extend(show.get("episodes") or [])
        for video in all_videos:
            if not isinstance(video, dict):
                continue
            item = dict(video); item["root_id"] = root_id
            parsed = item.get("parse") if isinstance(item.get("parse"), dict) else {}
            haystack = normalize_search_text(" ".join(str(value or "") for value in (item.get("title"), item.get("name"), item.get("rel"), parsed.get("show_title"), parsed.get("episode_title"), parsed.get("year"))))
            if qnorm in haystack or (tokens and tokens.intersection(haystack.split())):
                video_candidates.append(item)
    results: list[dict] = []
    for (root_id, artist, album), tracks in albums.items():
        if not album or qnorm not in normalize_search_text(f"{artist} {album}") or len(tracks) < 2:
            continue
        ordered = sorted(tracks, key=lambda item: track_sort_key(str(item.get("track") or "")) + (str(item.get("title") or ""),))
        files = [_library_file_payload(item, "audio") for item in ordered]
        results.append({
            "result_id": "library:" + root_id + ":album:" + sha1_text(artist + "|" + album), "source": "library",
            "source_label": "Library", "root_id": root_id, "rel": "", "media": "audio", "title": album,
            "directory_title": album, "directory": "", "user": artist, "artist": artist, "album": album, "name": album,
            "size": 0, "speed": 0, "seeders": 0, "leechers": 0, "browse_available": False,
            "stream_available": True, "download_available": False, "files_loaded": True, "file_count": len(files), "files": files,
        })
    results.extend(_standardize_library_record(item, "audio") for item in audio_candidates[:200])
    results.extend(_standardize_library_record(item, "video") for item in video_candidates[:200])
    return results, _make_search_cache_key("library", q, {"roots": library_root_versions()})


@app.route("/api/libsearch/combined", methods=["GET"])
def api_libsearch_combined():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Missing query", results=[], result_count=0, cache_key="")
    combined_cache_key = _make_search_cache_key("combined", q, {})
    debug = str(request.args.get("debug") or "").strip().lower() in {"1", "true", "yes"}
    with _SEARCH_DISK_LOCK:
        cached_entry = _disk_cache_get(combined_cache_key)
    cached_payload = dict((cached_entry or {}).get("payload") or {}) if cached_entry else {}
    if not (
        cached_payload.get("ok")
        and isinstance(cached_payload.get("results"), list)
        and isinstance(cached_payload.get("source_status"), list)
        and {str(item.get("source") or "") for item in cached_payload.get("source_status") if isinstance(item, dict)} == set(COMBINED_SEARCH_SOURCES)
    ):
        cached_payload = {}
    if cached_payload:
        cached_payload.pop("intent", None)
        cached_payload.pop("source_priority", None)
        cached_payload.update({"ok": True, "q": q, "cache_key": combined_cache_key, "cached": True})
        if debug:
            intent = infer_query_intent(q, library_hits=[item for item in cached_payload.get("results") or [] if item.get("source") == "library"])
            cached_payload["intent"] = intent
            cached_payload["source_priority"] = source_priority_for_intent(intent)
    if str(request.args.get("stream") or "").strip().lower() in {"1", "true", "yes"}:
        def gen():
            yield json.dumps({
                "event": "start", "ok": True, "q": q, "cache_key": combined_cache_key,
                "sources": list(COMBINED_SEARCH_SOURCES), "cached": bool(cached_payload),
            }, ensure_ascii=False) + "\n"
            if cached_payload:
                try:
                    record_search_history(q, "combined", combined_cache_key)
                except Exception:
                    pass
                yield json.dumps({"event": "cached", **cached_payload}, ensure_ascii=False) + "\n"
                yield json.dumps({"event": "done", **cached_payload}, ensure_ascii=False) + "\n"
                return
            payloads: dict[str, dict[str, Any]] = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="dp-search") as executor:
                future_map = {executor.submit(_libsearch_source_payload, source, q): source for source in COMBINED_SEARCH_SOURCES}
                for future in concurrent.futures.as_completed(future_map):
                    source = future_map[future]
                    try:
                        payload = future.result()
                    except Exception as exc:
                        payload = {"source": source, "source_label": source.title(), "results": [], "result_count": 0, "error": "Search failed", "duration_ms": 0}
                        try:
                            app.logger.info("libsearch source failed %s: %s", source, exc)
                        except Exception:
                            pass
                    payloads[source] = payload
                    yield json.dumps({"event": "source", **payload}, ensure_ascii=False) + "\n"
            final_payload = _combined_search_response_payload(q, combined_cache_key, payloads, debug=debug)
            cache_payload = dict(final_payload)
            cache_payload.pop("intent", None)
            cache_payload.pop("source_priority", None)
            with _SEARCH_DISK_LOCK:
                _disk_cache_set(combined_cache_key, "combined", q, {}, cache_payload)
            try:
                record_search_history(q, "combined", combined_cache_key)
            except Exception:
                pass
            yield json.dumps({"event": "done", **final_payload}, ensure_ascii=False) + "\n"
        return Response(stream_with_context(gen()), mimetype="application/x-ndjson")

    if cached_payload:
        try:
            record_search_history(q, "combined", combined_cache_key)
        except Exception:
            pass
        return jsonify(cached_payload)
    payloads = _run_combined_search_sources(q)
    response_payload = _combined_search_response_payload(q, combined_cache_key, payloads, debug=debug)
    cache_payload = dict(response_payload)
    cache_payload.pop("intent", None)
    cache_payload.pop("source_priority", None)
    with _SEARCH_DISK_LOCK:
        _disk_cache_set(combined_cache_key, "combined", q, {}, cache_payload)
    try:
        record_search_history(q, "combined", combined_cache_key)
    except Exception:
        pass
    return jsonify(response_payload)


def _libsearch_source_payload(source: str, q: str) -> dict[str, Any]:
    started = time.perf_counter()
    src = str(source or "").strip().lower()
    try:
        if src == "library":
            results, cache_key = _search_library_indexed(q)
            return {
                "ok": True, "source": "library", "source_label": "Library", "cache_key": cache_key,
                "results": results, "result_count": len(results), "error": "",
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
        if src == "youtube":
            raw_results, err, cache_key = _search_youtube_cached(q)
            results = _standardize_youtube_results(raw_results)
            return {
                "ok": True,
                "source": "youtube",
                "source_label": "YouTube",
                "cache_key": cache_key,
                "results": results,
                "youtube_results": raw_results,
                "result_count": len(results),
                "error": err,
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
        if src == "soulseek":
            slsk_users, slsk_total_results, dir_count, cache_key, err = _search_soulseek_cached(q)
            results = _standardize_soulseek_results(slsk_users)
            return {
                "ok": not bool(err),
                "source": "soulseek",
                "source_label": "Soulseek",
                "cache_key": cache_key,
                "results": results,
                "slsk_users": slsk_users,
                "result_count": len(results),
                "file_count": int(slsk_total_results or 0),
                "dir_count": int(dir_count or 0),
                "error": err,
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
        knaben_results, err, remaining, reset, cache_key = _search_knaben_cached(q, 1)
        results = _standardize_knaben_results(knaben_results)
        return {
            "ok": not bool(err),
            "source": "knaben",
            "source_label": "Knaben",
            "cache_key": cache_key,
            "results": results,
            "knaben_results": knaben_results,
            "result_count": len(results),
            "rate_remaining": remaining,
            "rate_reset": reset,
            "error": err,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }
    except Exception:
        return {
            "ok": False,
            "source": src or "unknown",
            "source_label": (src or "unknown").title(),
            "cache_key": "",
            "results": [],
            "result_count": 0,
            "error": "Search failed",
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }


def _run_combined_search_sources(q: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="dp-search") as executor:
        future_map = {executor.submit(_libsearch_source_payload, source, q): source for source in COMBINED_SEARCH_SOURCES}
        for future in concurrent.futures.as_completed(future_map):
            source = future_map[future]
            try:
                out[source] = future.result()
            except Exception:
                out[source] = {"ok": False, "source": source, "source_label": source.title(), "results": [], "result_count": 0, "error": "Search failed", "duration_ms": 0}
    return out


def _combined_search_response_payload(
    q: str,
    combined_cache_key: str,
    payloads: dict[str, dict[str, Any]],
    *,
    debug: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    errors: list[str] = []
    for source in COMBINED_SEARCH_SOURCES:
        payload = payloads.get(source) or {}
        results.extend([dict(x) for x in (payload.get("results") or []) if isinstance(x, dict)])
        err = str(payload.get("error") or "").strip()
        if err:
            errors.append(f"{payload.get('source_label') or source}: {err}")
        source_status.append({
            "source": source,
            "label": str(payload.get("source_label") or source.title()),
            "ok": bool(payload.get("ok", not bool(err))),
            "error": err,
            "result_count": int(payload.get("result_count") or len(payload.get("results") or []) or 0),
            "duration_ms": float(payload.get("duration_ms") or 0),
        })
    intent = infer_query_intent(q, library_hits=[item for item in results if item.get("source") == "library"])
    results = rank_combined_results(results, q, intent=intent)
    slsk_payload = payloads.get("soulseek") or {}
    response = {
        "ok": True,
        "q": q,
        "cache_key": combined_cache_key,
        "results": results,
        "result_count": len(results),
        "source_status": source_status,
        "knaben_results": (payloads.get("knaben") or {}).get("knaben_results") or [],
        "slsk_users": slsk_payload.get("slsk_users") or [],
        "youtube_results": (payloads.get("youtube") or {}).get("youtube_results") or [],
        "dir_count": int(slsk_payload.get("dir_count") or 0),
        "file_count": int(slsk_payload.get("file_count") or 0),
        "error": "; ".join(errors),
        "cached": False,
    }
    if debug:
        response["intent"] = intent
        response["source_priority"] = source_priority_for_intent(intent)
    return response


def api_libsearch_knaben():
    q = (request.args.get("q") or "").strip()
    try:
        page = int(request.args.get("page") or "1")
    except ValueError:
        page = 1
    page = max(1, page)
    if not q:
        return jsonify(ok=False, error="Missing query", results=[], page=page, result_count=0, cache_key="")

    extra = {"page": page}
    cache_key = _make_search_cache_key("knaben", q, extra)

    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")

    if cached_payload is not None:
        results = cached_payload.get("results") or []
        err = cached_payload.get("error") or ""
        remaining = cached_payload.get("remaining") or ""
        reset = cached_payload.get("reset") or ""
    else:
        results, err, remaining, reset = knaben_search(q, page)
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "knaben", q, extra, {"results": results, "error": err, "remaining": remaining, "reset": reset})

    if page == 1:
        try:
            record_search_history(q, "knaben", cache_key)
        except Exception:
            pass

    return jsonify(ok=True, q=q, page=page, cache_key=cache_key, results=results, error=err, rate_remaining=remaining, rate_reset=reset, result_count=len(results))



def api_libsearch_soulseek_start():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Missing query", sid="", done=True, slsk_users=[], file_count=0, dir_count=0, cache_key="")

    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key("soulseek", q, extra)

    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")

    if cached_payload is not None:
        slsk_users = cached_payload.get("slsk_users") or []
        try:
            file_count = int(cached_payload.get("file_count") or 0)
        except Exception:
            file_count = 0
        try:
            dir_count = int(cached_payload.get("dir_count") or 0)
        except Exception:
            dir_count = 0
        if not file_count:
            try:
                file_count = sum(int(u.get("total_files") or 0) for u in (slsk_users or []))
            except Exception:
                file_count = 0
        return jsonify(ok=True, q=q, cache_key=cache_key, sid="", rev=1, done=True, slsk_users=slsk_users, file_count=file_count, dir_count=dir_count, error="", changed=True)

    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return jsonify(ok=False, error="Soulseek service is not ready", sid="", done=True, slsk_users=[], file_count=0, dir_count=0, cache_key=cache_key)

    sid = _slsk_session_create(cache_key, q)

    try:
        record_search_history(q, "soulseek", cache_key)
    except Exception:
        pass

    try:
        svc.start_search_session(sid, q)
    except Exception:
        _slsk_session_mark_done(sid, error="Soulseek search failed")
        return jsonify(ok=False, error="Soulseek search failed", sid=sid, done=True, slsk_users=[], file_count=0, dir_count=0, cache_key=cache_key)

    return jsonify(ok=True, q=q, cache_key=cache_key, sid=sid, rev=0, done=False, slsk_users=[], file_count=0, dir_count=0, error="", changed=True)

def api_libsearch_soulseek_poll():
    sid = (request.args.get("sid") or "").strip()
    if not sid:
        return jsonify(ok=False, error="Missing sid", done=True)

    try:
        want_rev = int(request.args.get("rev") or 0)
    except Exception:
        want_rev = 0

    snap = _slsk_session_snapshot(sid)
    if not snap:
        return jsonify(ok=False, error="Unknown sid", done=True)

    _slsk_session_touch(sid)

    rev = int(snap.get("rev") or 0)
    done = bool(snap.get("done"))
    err = str(snap.get("error") or "")
    file_count = int(snap.get("file_count") or 0)
    dir_count = int(snap.get("dir_count") or 0)

    changed = (rev != want_rev) or done

    slsk_users = []
    if changed:
        slsk_users = _slsk_group_snapshot_to_users(snap)

    if done and not err:
        # Persist to disk cache for fast repeat loads
        cache_key = str(snap.get("cache_key") or "")
        q = str(snap.get("q") or "")
        extra: Dict[str, Any] = {}
        payload = {
            "slsk_users": slsk_users,
            "file_count": file_count,
            "dir_count": dir_count,
        }
        try:
            with _SEARCH_DISK_LOCK:
                _disk_cache_set(cache_key, "soulseek", q, extra, payload)
        except Exception:
            pass

    return jsonify(
        ok=True,
        sid=sid,
        cache_key=str(snap.get("cache_key") or ""),
        rev=rev,
        changed=changed,
        done=done,
        error=err,
        slsk_users=slsk_users,
        file_count=file_count,
        dir_count=dir_count,
    )

def api_libsearch_soulseek():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Missing query", slsk_users=[], result_count=0, cache_key="")

    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key("soulseek", q, extra)

    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")

    slsk_users: List[Dict[str, Any]] = []
    slsk_total_results = 0

    if cached_payload is not None:
        slsk_users = cached_payload.get("slsk_users") or []
        try:
            slsk_total_results = int(cached_payload.get("slsk_total_results") or 0)
        except Exception:
            slsk_total_results = sum(int(u.get("total_files") or 0) for u in (slsk_users or []))
    else:
        svc = SOULSEEK_SERVICE
        if not svc or not svc.is_ready():
            return jsonify(ok=False, error="Soulseek service is not ready", slsk_users=[], result_count=0, cache_key=cache_key)

        try:
            items = svc.search(q)
        except Exception:
            return jsonify(ok=False, error="Soulseek search failed", slsk_users=[], result_count=0, cache_key=cache_key)

        users: Dict[str, Dict[str, Any]] = {}
        for it in items:
            user = (it.get("user") or "").strip()
            rp = str(it.get("remote_path") or "")
            size = int(it.get("size") or 0)
            speed = int(it.get("speed") or 0)
            if not user or not rp:
                continue
            rp_norm = _slsk_norm_remote_path(rp)
            parts = rp_norm.split("\\")
            fname = parts[-1] if parts else rp_norm
            directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
            kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)

            u = users.get(user)
            if not u:
                u = {"user": user, "speed": speed, "dirs": {}, "total_size": 0, "total_files": 0}
                users[user] = u
            u["speed"] = max(int(u.get("speed") or 0), speed)

            d = (u.get("dirs") or {}).get(directory)
            if not d:
                d = {"directory": directory, "files": [], "total_size": 0, "total_files": 0}
                (u.get("dirs") or {})[directory] = d
                u["dirs"] = u.get("dirs") or {}
                u["dirs"][directory] = d

            d["files"].append({
                "name": fname,
                "remote_path": rp_norm,
                "size": size,
                "kind": kind,
                "ext": ext,
                "bitrate": br,
                "bit_depth": bd,
                "sample_rate": sr,
                "duration": dur,
                "vbr": vbr,
                "codec": codec,
            })
            d["total_size"] += size
            u["total_size"] = int(u.get("total_size") or 0) + size
            u["total_files"] = int(u.get("total_files") or 0) + 1

        for u in users.values():
            dirs_list = list((u.get("dirs") or {}).values())
            dirs_list.sort(key=lambda d: (int(d.get("total_size") or 0), len(d.get("files") or [])), reverse=True)
            u2 = {"user": u.get("user") or "", "speed": int(u.get("speed") or 0), "dirs": dirs_list, "total_size": int(u.get("total_size") or 0), "total_files": int(u.get("total_files") or 0)}
            slsk_users.append(u2)

        slsk_users.sort(key=lambda u: (int(u.get("speed") or 0), int(u.get("total_size") or 0), str(u.get("user") or "").lower()), reverse=True)
        slsk_total_results = sum(int(u.get("total_files") or 0) for u in slsk_users)

        dir_count = 0
        try:
            dir_count = sum(len(u.get("dirs") or []) for u in (slsk_users or []))
        except Exception:
            dir_count = 0

        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "soulseek", q, extra, {"slsk_users": slsk_users, "slsk_total_results": slsk_total_results, "file_count": slsk_total_results, "dir_count": dir_count})

    try:
        record_search_history(q, "soulseek", cache_key)
    except Exception:
        pass

    return jsonify(ok=True, q=q, cache_key=cache_key, slsk_users=slsk_users, result_count=slsk_total_results)

@app.route("/api/soulseek/browse_user", methods=["GET"])
def api_soulseek_browse_user():
    user = (request.args.get("user") or "").strip()
    selected_dir = _slsk_norm_remote_path(request.args.get("selected_dir") or "")
    if not user:
        return jsonify(ok=False, error="Missing user", user="", dirs=[], selected_dir=""), 400

    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return jsonify(ok=False, error="Soulseek service is not ready", user=user, dirs=[], selected_dir=selected_dir)

    try:
        items = svc.browse_user(user)
    except Exception:
        return jsonify(ok=False, error="Soulseek browse failed", user=user, dirs=[], selected_dir=selected_dir)

    dirs = _slsk_group_items_to_dirs(user, items)
    dir_paths = {str(d.get("directory") or "") for d in dirs}
    if selected_dir and selected_dir not in dir_paths:
        selected_dir = ""

    return jsonify(ok=True, user=user, dirs=dirs, selected_dir=selected_dir, file_count=sum(int(d.get("total_files") or 0) for d in dirs), dir_count=len(dirs))


@app.route("/api/libsearch/youtube", methods=["GET"])
def api_libsearch_youtube():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify(ok=False, error='Missing query', results=[], result_count=0, cache_key='')
    raw_results, err, cache_key = _search_youtube_cached(q)
    try:
        record_search_history(q, 'youtube', cache_key)
    except Exception:
        pass
    results = _standardize_youtube_results(raw_results)
    return jsonify(ok=True, q=q, cache_key=cache_key, results=results, result_count=len(results), error=err)


@app.route("/api/youtube/files", methods=["GET"])
def api_youtube_files():
    url = (request.args.get('url') or '').strip()
    if not url:
        return jsonify(ok=False, error='Missing URL', files=[], file_count=0, size=0), 400
    try:
        files = ytdlp_list_formats(url)
        total_size = sum(int(f.get('size') or 0) for f in files)
        return jsonify(ok=True, files=files, file_count=len(files), size=total_size)
    except Exception:
        return jsonify(ok=False, error="Failed to list formats", files=[], file_count=0, size=0), 500


@app.route("/api/youtube/channel", methods=["GET"])
def api_youtube_channel():
    channel_id = (request.args.get('channel_id') or '').strip()
    if not channel_id:
        return jsonify(ok=False, error='Missing channel id', results=[], result_count=0), 400
    try:
        results = youtube_channel_browse(channel_id)
        return jsonify(ok=True, results=results, result_count=len(results))
    except Exception:
        return jsonify(ok=False, error="Failed to browse channel", results=[], result_count=0), 500


@app.route("/api/youtube/enqueue", methods=["POST"])
def api_youtube_enqueue():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    title = str(data.get('title') or '').strip() or 'YouTube'
    url = str(data.get('url') or '').strip()
    selected = data.get('selected') or []
    if not url:
        return jsonify(ok=False, error='Missing URL'), 400
    if not str(YOUTUBE_DOWNLOAD_DIR or "").strip():
        return jsonify(ok=False, error='Pick the YouTube folder in Downloads settings before downloading.'), 400
    entries: List[Dict[str, Any]] = []
    for i, it in enumerate(selected):
        if not isinstance(it, dict):
            continue
        name = str(it.get('name') or it.get('title') or f'Format {i+1}')
        ext = str(it.get('ext') or 'mp4').lower()
        file_id = str(it.get('file_id') or it.get('itag') or sha1_text(name + '|' + ext)[:12])
        entries.append({
            'file_id': file_id,
            'itag': str(it.get('itag') or it.get('format_id') or it.get('file_id') or ''),
            'format_id': str(it.get('format_id') or it.get('itag') or it.get('file_id') or ''),
            'name': name,
            'title': name,
            'ext': ext,
            'media': str(it.get('media') or '').strip().lower(),
            'direct_url': str(it.get('direct_url') or '').strip(),
            'url': url,
            'total': int(it.get('size') or 0) if str(it.get('size') or '').strip() else 0,
            'done': 0,
            'speed': 0.0,
            'state': 'queued',
            'error': '',
            'paused': False,
            'canceled': False,
            'out_path': '',
        })
    if not entries:
        return jsonify(ok=False, error='No files selected'), 400
    task_id = uuid.uuid4().hex
    youtube_root = _youtube_download_root()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = sanitize_folder_name(title)
    folder = sanitize_folder_name(f"{stamp}_{base}_{task_id[:6]}")
    task_dir = os.path.join(youtube_root, folder)
    os.makedirs(task_dir, exist_ok=True)
    t = Task(id=task_id, title=title, magnet=url, task_dir=task_dir, owner=_current_settings_username(), source='youtube', state='queued', message='Queued', youtube_files=entries)
    with TASKS_LOCK:
        TASKS[task_id] = t
    save_task_metadata(t, original_result_title=title, remote_files=entries, selected_file_ids=[item.get('file_id') for item in entries], version=str(VERSION))
    th = threading.Thread(target=youtube_worker, args=(task_id,), daemon=True)
    th.start()
    return jsonify(ok=True, task_id=task_id)


@app.route("/api/search_history", methods=["GET"])
def api_search_history():
    try:
        with _SEARCH_DISK_LOCK:
            items = _load_search_history()
        return jsonify({"ok": True, "items": items})
    except Exception:
        return jsonify({"ok": False, "error": "Failed to browse channel", "items": []})


@app.route("/api/search_history/clear", methods=["POST"])
def api_search_history_clear():
    try:
        clear_search_history_and_cache()
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False, "error": "Failed to clear search history"})


@app.route("/api/libsearch/stream_selected", methods=["POST"])
def api_libsearch_stream_selected():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    try:
        out = _engine_prepare_stream_session(data)
        return jsonify({"ok": True, **out})
    except Exception:
        return jsonify({"ok": False, "error": "Failed to prepare stream"}), 400


@app.route("/api/debrid/providers", methods=["GET"])
def api_debrid_providers():
    settings = ensure_app_settings(username=_current_settings_username(), defaults_overrides=_default_app_overrides())
    return jsonify({"ok": True, **debrid_provider_status(settings)})


@app.route("/api/debrid/connect_token", methods=["POST"])
def api_debrid_connect_token():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Paste a debrid token first."}), 400
    settings = ensure_app_settings(username=_current_settings_username(), defaults_overrides=_default_app_overrides())
    timeout_seconds = int(settings.get("REQUEST_TIMEOUT_SECONDS") or 25)
    matched_id = ""
    matched_label = ""
    failures: dict[str, str] = {}
    for provider_id, spec in provider_specs().items():
        candidate = dict(settings)
        candidate[spec.token_setting_key] = token
        try:
            get_provider(provider_id, candidate, timeout_seconds).validate_token()
            matched_id, matched_label = provider_id, spec.label
            break
        except (DebridAuthError, DebridProviderError) as exc:
            failures[provider_id] = str(exc)
            continue
        except Exception as exc:
            failures[provider_id] = str(exc)
            continue
    if not matched_id:
        details = [str(value).strip() for value in failures.values() if str(value).strip() and "rejected" not in str(value).lower()]
        suffix = (" " + details[-1]) if details else ""
        return jsonify({"ok": False, "error": "That token could not be verified with Real Debrid, AllDebrid, Premiumize, or TorBox." + suffix}), 400
    updates = {spec.token_setting_key: "" for spec in provider_specs().values()}
    updates[provider_specs()[matched_id].token_setting_key] = token
    updates["DEBRID_PROVIDER"] = matched_id
    saved = save_app_settings(updates, username=_current_settings_username(), defaults_overrides=_default_app_overrides())
    if _current_settings_username():
        saved = _apply_runtime_settings_for_user(_current_settings_username(), force=True)
    return jsonify({"ok": True, "provider": matched_id, "label": matched_label, **debrid_provider_status(saved)})


@app.route("/api/debrid/preview_files", methods=["POST"])
@app.route("/api/debrid/load_files", methods=["POST"])
def api_debrid_preview_files():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    magnet = str(data.get("magnet") or "").strip()
    if not magnet.startswith("magnet:?"):
        return jsonify({"ok": False, "error": "Invalid magnet"}), 400
    try:
        settings = ensure_app_settings(username=_current_settings_username(), defaults_overrides=_default_app_overrides())
        status = debrid_provider_status(settings)
        if not status.get("configured"):
            return jsonify({"ok": False, "error": "No debrid provider is configured."}), 400
        provider = get_active_provider(settings, int(settings.get("REQUEST_TIMEOUT_SECONDS") or 25))
        preview = provider.preview_magnet(magnet)
        files = [{"id": item.file_id, "file_id": item.file_id, "path": item.path, "bytes": item.bytes} for item in preview.files]
        return jsonify({
            "ok": True,
            "provider": provider.id,
            "provider_label": provider.label,
            "debrid_task_id": preview.provider_task_id,
            "files": files,
        })
    except DebridProviderError as exc:
        return jsonify({"ok": False, "error": str(exc) or "Failed to preview files"}), 400
    except Exception:
        return jsonify({"ok": False, "error": "Failed to preview files"}), 500


@app.route("/api/debrid/enqueue_selected", methods=["POST"])
def api_debrid_enqueue_selected():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    title = str(data.get("title") or "").strip() or "Knaben item"
    magnet = str(data.get("magnet") or "").strip()
    provider_task_id = str(data.get("debrid_task_id") or "").strip()
    file_ids = data.get("file_ids") or []

    if not provider_task_id:
        return jsonify({"ok": False, "error": "Missing debrid task id"}), 400
    if not str(DOWNLOAD_DIR or "").strip():
        return jsonify({"ok": False, "error": "Pick the Debrid folder in Downloads settings before downloading."}), 400

    clean_ids: List[str] = []
    if isinstance(file_ids, list):
        for x in file_ids:
            try:
                clean_ids.append(str(x))
            except Exception:
                continue

    if not clean_ids:
        return jsonify({"ok": False, "error": "No files selected"}), 400

    settings = ensure_app_settings(username=_current_settings_username(), defaults_overrides=_default_app_overrides())
    status = debrid_provider_status(settings)
    provider_id = str(status.get("active_provider") or "")
    if not provider_id:
        return jsonify({"ok": False, "error": "No debrid provider is configured."}), 400
    requested_provider = str(data.get("provider") or "").strip().lower()
    if requested_provider and requested_provider != provider_id:
        return jsonify({"ok": False, "error": "The preview provider is no longer active. Preview the result again."}), 409

    task_id = uuid.uuid4().hex
    task_dir = build_task_dir(task_id, title)
    os.makedirs(task_dir, exist_ok=True)

    t = Task(
        id=task_id,
        title=title,
        magnet=magnet,
        task_dir=task_dir,
        owner=_current_settings_username(),
        source="debrid",
        state="queued",
        message="Queued",
        debrid_provider=provider_id,
        debrid_task_id=provider_task_id,
        debrid_selected_file_ids=clean_ids,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    save_task_metadata(t, original_result_title=title, selected_file_ids=clean_ids, version=str(VERSION))
    th = threading.Thread(target=worker, args=(task_id,), daemon=True)
    th.start()

    return jsonify({"ok": True, "task_id": task_id})


@app.route("/api/soulseek/enqueue", methods=["POST"])
def api_soulseek_enqueue():
    if not str(SOULSEEK_DOWNLOAD_DIR or "").strip():
        return jsonify({"ok": False, "error": "Pick the Soulseek folder in Downloads settings before downloading."}), 400
    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return jsonify({"ok": False, "error": "Soulseek is configured but not connected. Check username, password, and listening port in Services."}), 400

    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception:
        data = {}

    user = (data.get("user") or "").strip()
    directory = (data.get("directory") or "").strip()
    files_in = data.get("files") or []
    title = (data.get("title") or "").strip()

    task_download_dir = _slsk_task_download_dir(directory)
    try:
        os.makedirs(task_download_dir, exist_ok=True)
    except Exception:
        task_download_dir = SOULSEEK_DOWNLOAD_DIR

    files: List[Dict[str, Any]] = []
    remote_paths: List[str] = []
    for it in files_in:
        if isinstance(it, str):
            rp = it
            sz = 0
        else:
            rp = it.get("remote_path") if isinstance(it, dict) else ""
            sz = it.get("size") if isinstance(it, dict) else 0
        rp = _slsk_norm_remote_path(str(rp or "").strip())
        if not rp:
            continue
        try:
            sz = int(sz or 0)
        except Exception:
            sz = 0
        remote_paths.append(rp)
        rel = _slsk_relative_under_directory(directory, rp)
        rel_parts = [x for x in _slsk_norm_remote_path(rel).split("\\") if x]
        local_path = os.path.join(task_download_dir, *rel_parts) if rel_parts else task_download_dir
        incoming_path = _slsk_expected_incoming_path(rp)
        files.append(
            {
                "user": user,
                "directory": directory,
                "remote_path": rp,
                "file_id": hashlib.sha1((user + "|" + rp).encode("utf-8", "ignore")).hexdigest()[:16],
                "name": _slsk_norm_remote_path(rp).split("\\")[-1],
                "total": sz,
                "done": 0,
                "state": "queued",
                "state_raw": "queued",
                "error": "",
                "paused": False,
                "canceled": False,
                "local_path": local_path,
                "incoming_path": incoming_path,
                "speed": 0.0,
            }
        )

    if not user or not remote_paths:
        return jsonify({"ok": False, "error": "Missing user or selected files"}), 400

    if not title:
        base = directory.split("\\")[-1] if directory else ""
        title = f"Soulseek: {user} {base}".strip()

    task_id = uuid.uuid4().hex
    t = Task(
        id=task_id,
        title=title,
        magnet="",
        task_dir=task_download_dir,
        owner=_current_settings_username(),
        source="soulseek",
        state="queued",
        message="Queued",
        slsk_user=user,
        slsk_directory=directory,
        slsk_files=files,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    save_task_metadata(t, original_result_title=title, remote_files=files, selected_file_ids=[item.get("file_id") for item in files], version=str(VERSION))

    try:
        svc.enqueue_downloads(task_id, user, remote_paths)
    except Exception:
        set_task(task_id, state="error", message="Failed to queue Soulseek download")
        return jsonify({"ok": False, "error": "Failed to queue Soulseek download"}), 500

    return jsonify({"ok": True, "task_id": task_id})




@app.route("/cancel", methods=["POST"])
def cancel():
    task_id = (request.form.get("task_id") or "").strip()
    if not task_id:
        abort(400)
    if not task_belongs_to_owner(task_id, _current_settings_username()):
        abort(404)
    cancel_task(task_id)
    return redirect(url_for("tasks"))




# =========================
# Library API
# =========================

@app.route("/api/library/config", methods=["GET"])
def api_library_config():
    rts = []
    versions = library_root_versions()
    source_by_id = {str(item.get("id") or ""): str(item.get("source") or "library") for item in root_objects()}
    for rid, name, ap, mode in roots():
        if mode in {"meta", "metadata"}:
            try:
                ensure_index_async(rid, os.path.abspath(ap), mode=mode)
            except Exception:
                pass
        try:
            library_watch_root(rid, os.path.abspath(ap), mode=mode)
        except Exception:
            pass
        rts.append({"id": rid, "name": name, "mode": mode, "source": source_by_id.get(rid, "library"), "version": int(versions.get(rid) or 0)})
    return jsonify(
        {
            "roots": rts,
            "aggregate_root": {"id": LIBRARY_ALL_ROOT_ID, "name": "Library", "mode": "metadata"},
            "preload_enabled": bool(PRELOAD_NEXT_FOR_GAPLESS),
            "preload_bytes": int(PRELOAD_NEXT_CHUNK_BYTES),
            "lastfm_enabled": bool(lastfm_enabled()),
            "wheel_rotation_max_degrees": float(WHEEL_ROTATION_MAX_DEGREES),
            "playback_streaming_mode": str(PLAYBACK_STREAMING_MODE or "http").strip().lower() or "http",
            "library_versions": versions,
        }
    )


@app.route("/api/library/reindex", methods=["POST"])
def api_library_reindex():
    def snapshot() -> dict[str, Any]:
        with _FULL_REINDEX_LOCK:
            return dict(_FULL_REINDEX_STATUS)

    with _FULL_REINDEX_LOCK:
        if _FULL_REINDEX_STATUS.get("running"):
            return jsonify({"ok": True, "status": dict(_FULL_REINDEX_STATUS)})
        _FULL_REINDEX_STATUS.update(
            {
                "running": True,
                "percent": 0,
                "phase": "starting",
                "root": "",
                "processed_roots": 0,
                "total_roots": 0,
                "started_at": time.time(),
                "finished_at": 0.0,
                "error": "",
            }
        )

    def set_status(**updates: Any) -> None:
        with _FULL_REINDEX_LOCK:
            _FULL_REINDEX_STATUS.update(updates)

    def run_full_reindex() -> None:
        try:
            root_rows = [(rid, name, os.path.abspath(path), mode) for rid, name, path, mode in roots()]
            total_roots = max(1, len(root_rows))
            set_status(total_roots=len(root_rows), phase="clearing cache", percent=1)
            clear_index_cache()
            for idx, (rid, name, root_abs, mode) in enumerate(root_rows):
                base = (idx / total_roots) * 100.0
                span = 100.0 / total_roots
                set_status(processed_roots=idx, root=name or rid, phase="scan", percent=int(base))

                def progress(done: int, total: int, phase: str) -> None:
                    pct = base + span * 0.92 * (max(0, min(done, total)) / max(1, total))
                    set_status(root=name or rid, phase=phase, percent=int(max(0, min(99, pct))))

                data = build_index_for_root(root_abs, full_video_sync=True, progress=progress)
                set_status(root=name or rid, phase="saving index", percent=int(max(0, min(99, base + span * 0.96))))
                set_index_cache(rid, data)
                set_status(processed_roots=idx + 1, root=name or rid, phase="root complete", percent=int(max(0, min(99, base + span))))
            maintenance_result = None
            maintenance_error = ""
            set_status(phase="database maintenance", percent=99, root="")
            try:
                with pause_enrichment_writes():
                    maintenance_result = finish_full_reindex()
            except Exception as exc:
                maintenance_error = str(exc)
            set_status(running=False, phase="complete", percent=100, root="", processed_roots=len(root_rows),
                       maintenance=maintenance_result, maintenance_error=maintenance_error, finished_at=time.time())
        except Exception as exc:
            set_status(running=False, phase="error", error=str(exc), finished_at=time.time())

    threading.Thread(target=run_full_reindex, daemon=True).start()
    return jsonify({"ok": True, "status": snapshot()})


@app.route("/api/library/reindex/status", methods=["GET"])
def api_library_reindex_status():
    with _FULL_REINDEX_LOCK:
        return jsonify({"ok": True, "status": dict(_FULL_REINDEX_STATUS)})


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    cfg = ensure_startup_security_config()
    username = _current_settings_username()
    settings = _apply_runtime_settings_for_user(username) if username else ensure_app_settings(defaults_overrides=_default_app_overrides())
    soulseek_service = getattr(state_module, "SOULSEEK_SERVICE", None)
    soulseek_status = soulseek_service.startup_status() if soulseek_service and hasattr(soulseek_service, "startup_status") else {}
    connections = {
        "current_user": username,
        "DEBRID": debrid_provider_status(settings),
        "DEBRID_PROVIDER": {"value": debrid_provider_status(settings)["active_provider"], "set": bool(debrid_provider_status(settings)["active_provider"])},
        "REAL_DEBRID_API_KEY": {"set": bool(str(settings.get("REAL_DEBRID_API_KEY") or "").strip())},
        "ALLDEBRID_API_KEY": {"set": bool(str(settings.get("ALLDEBRID_API_KEY") or "").strip())},
        "PREMIUMIZE_API_KEY": {"set": bool(str(settings.get("PREMIUMIZE_API_KEY") or "").strip())},
        "TORBOX_API_KEY": {"set": bool(str(settings.get("TORBOX_API_KEY") or "").strip())},
        "KNABEN_API_KEY": {"set": bool(str(settings.get("KNABEN_API_KEY") or "").strip())},
        "SOULSEEK_USERNAME": {"set": bool(str(settings.get("SOULSEEK_USERNAME") or "").strip())},
        "SOULSEEK_PASSWORD": {"set": bool(str(settings.get("SOULSEEK_PASSWORD") or "").strip())},
        "SOULSEEK": {
            "set": bool(str(settings.get("SOULSEEK_USERNAME") or "").strip() and str(settings.get("SOULSEEK_PASSWORD") or "").strip()),
            "connected": bool(soulseek_service and soulseek_service.is_ready()),
            "error": str(soulseek_service.start_error() or "") if soulseek_service else "",
            "warning": str(soulseek_status.get("warning") or ""),
            "startup_status": soulseek_status,
        },
        "LASTFM_API_KEY": {"set": bool(str(settings.get("LASTFM_API_KEY") or "").strip())},
        "LASTFM_API_SECRET": {"set": bool(str(settings.get("LASTFM_API_SECRET") or "").strip())},
        "LASTFM_SESSION": {"set": bool(lastfm_session_key()), "username": lastfm_username()},
    }
    return jsonify({
        "ok": True,
        "startup": {
            "PORT": int(PORT),
            "ENABLE_MCP": bool(cfg.get("ENABLE_MCP")),
            "MCP_TOKEN_SET": bool(str(cfg.get("MCP_TOKEN") or "").strip()),
        },
        "settings": masked_settings(settings),
        "tools": {
            "ffmpeg": executable_status(str(settings.get("FFMPEG_PATH") or "ffmpeg")),
            "ffprobe": executable_status(str(settings.get("FFPROBE_PATH") or "ffprobe")),
        },
        "connections": connections,
        "picker_available": True,
    })


def _setup_skipped_services(settings: dict[str, Any]) -> dict[str, str]:
    raw = settings.get("SETUP_SKIPPED_SERVICES")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            k = str(key or "").strip().lower()
            if k in {"library", "debrid", "soulseek", "lastfm", "youtube", "ffmpeg", "ffprobe", "ytdlp", "downloads", "knaben"}:
                out[k] = "skipped" if str(value or "").strip().lower() == "skipped" else str(value or "").strip().lower()
    return out


def _kick_library_indexes_from_settings(settings: dict[str, Any]) -> None:
    for root in root_objects():
        try:
            path = str(root.get("path") or "").strip()
            mode = "metadata"
            if path and os.path.isabs(path):
                rid = str(root.get("id") or sha1_text(os.path.abspath(path)))
                ensure_index_async(rid, os.path.abspath(path), mode=mode)
                library_watch_root(rid, os.path.abspath(path), mode=mode)
        except Exception:
            pass


def _service_status_payload(settings: dict[str, Any]) -> dict[str, Any]:
    tools = {
        "ffmpeg": executable_status(str(settings.get("FFMPEG_PATH") or "ffmpeg")),
        "ffprobe": executable_status(str(settings.get("FFPROBE_PATH") or "ffprobe")),
        "yt_dlp": executable_status(str(settings.get("YTDLP_CMD") or "yt-dlp")),
    }
    soulseek_service = getattr(state_module, "SOULSEEK_SERVICE", None)
    soulseek_status = soulseek_service.startup_status() if soulseek_service and hasattr(soulseek_service, "startup_status") else {}
    skipped = _setup_skipped_services(settings)
    debrid_status = debrid_provider_status(settings)
    return {
        "skipped": skipped,
        "debrid": {
            "configured": bool(debrid_status["configured"]),
            "active_provider": debrid_status["active_provider"],
            "providers": debrid_status["providers"],
            "download_dir": str(settings.get("DOWNLOAD_DIR") or ""),
            "status": skipped.get("debrid") or ("configured" if debrid_status["configured"] else "not_configured"),
        },
        "soulseek": {
            "configured": bool(str(settings.get("SOULSEEK_USERNAME") or "").strip() and str(settings.get("SOULSEEK_PASSWORD") or "").strip()),
            "connected": bool(soulseek_service and soulseek_service.is_ready()),
            "listening_port": soulseek_status.get("listening_port"),
            "obfuscated_port": soulseek_status.get("obfuscated_port"),
            "warning": str(soulseek_status.get("warning") or ""),
            "error": str(soulseek_service.start_error() or "") if soulseek_service else "",
            "status": skipped.get("soulseek") or ("connected" if soulseek_service and soulseek_service.is_ready() else ("not_connected" if str(settings.get("SOULSEEK_USERNAME") or "").strip() and str(settings.get("SOULSEEK_PASSWORD") or "").strip() else "not_configured")),
        },
        "lastfm": {
            "api_configured": bool(str(settings.get("LASTFM_API_KEY") or "").strip() and str(settings.get("LASTFM_API_SECRET") or "").strip()),
            "session_user": lastfm_username(),
            "status": skipped.get("lastfm") or ("logged_in" if lastfm_username() else ("configured" if str(settings.get("LASTFM_API_KEY") or "").strip() and str(settings.get("LASTFM_API_SECRET") or "").strip() else "not_configured")),
        },
        "knaben": {
            "api_key_configured": bool(str(settings.get("KNABEN_API_KEY") or "").strip()),
            "status": skipped.get("knaben") or ("configured" if str(settings.get("KNABEN_API_KEY") or "").strip() else "optional"),
        },
        "youtube": {
            "tool": tools["yt_dlp"],
            "download_dir": str(settings.get("YOUTUBE_DOWNLOAD_DIR") or ""),
            "status": skipped.get("youtube") or ("tool_found" if tools["yt_dlp"].get("ok") else "tool_missing"),
        },
        "ffmpeg": tools["ffmpeg"],
        "ffprobe": tools["ffprobe"],
        "ytdlp": tools["yt_dlp"],
    }


def _setup_status_for_user(username: str, settings: dict[str, Any]) -> dict[str, Any]:
    folders = settings.get("LIBRARY_FOLDERS") if isinstance(settings.get("LIBRARY_FOLDERS"), list) else []
    skipped = _setup_skipped_services(settings)
    required_complete = bool(folders)
    has_optional_setup = any(
        str(settings.get(key) or "").strip()
        for key in (
            "REAL_DEBRID_API_KEY",
            "ALLDEBRID_API_KEY",
            "PREMIUMIZE_API_KEY",
            "TORBOX_API_KEY",
            "SOULSEEK_USERNAME",
            "SOULSEEK_PASSWORD",
            "LASTFM_API_KEY",
            "LASTFM_API_SECRET",
            "LASTFM_SESSION_KEY",
            "FFMPEG_PATH",
            "FFPROBE_PATH",
            "YTDLP_CMD",
            "DOWNLOAD_DIR",
            "SOULSEEK_DOWNLOAD_DIR",
            "YOUTUBE_DOWNLOAD_DIR",
        )
    )
    should_show = not bool(settings.get("SETUP_WIZARD_COMPLETE"))
    services = _service_status_payload(settings)
    tools = {
        "ffmpeg": services.get("ffmpeg") or executable_status(str(settings.get("FFMPEG_PATH") or "ffmpeg")),
        "ffprobe": services.get("ffprobe") or executable_status(str(settings.get("FFPROBE_PATH") or "ffprobe")),
        "ytdlp": services.get("ytdlp") or executable_status(str(settings.get("YTDLP_CMD") or "yt-dlp")),
    }
    setup = {
        "library_configured": bool(folders),
        "youtube_download_folder_configured": bool(str(settings.get("YOUTUBE_DOWNLOAD_DIR") or "").strip()),
        "soulseek_username_configured": bool(str(settings.get("SOULSEEK_USERNAME") or "").strip()),
        "soulseek_password_configured": bool(str(settings.get("SOULSEEK_PASSWORD") or "").strip()),
        "soulseek_download_folder_configured": bool(str(settings.get("SOULSEEK_DOWNLOAD_DIR") or "").strip()),
        "lastfm_api_key_configured": bool(str(settings.get("LASTFM_API_KEY") or "").strip()),
        "lastfm_secret_configured": bool(str(settings.get("LASTFM_API_SECRET") or "").strip()),
        "lastfm_session_configured": bool(lastfm_session_key()),
    }
    debrid_status = debrid_provider_status(settings)
    setup["debrid_provider"] = debrid_status["active_provider"]
    setup["debrid_provider_configured"] = bool(debrid_status["configured"])
    setup["debrid_download_folder_configured"] = bool(str(settings.get("DOWNLOAD_DIR") or "").strip())
    setup["debrid_complete"] = bool(setup["debrid_provider_configured"] and setup["debrid_download_folder_configured"])
    setup["tools_complete"] = bool(tools["ffmpeg"].get("ok") and tools["ffprobe"].get("ok") and tools["ytdlp"].get("ok") and setup["youtube_download_folder_configured"])
    setup["soulseek_lastfm_complete"] = bool(
        setup["soulseek_username_configured"]
        and setup["soulseek_password_configured"]
        and setup["soulseek_download_folder_configured"]
        and setup["lastfm_api_key_configured"]
        and setup["lastfm_secret_configured"]
        and setup["lastfm_session_configured"]
    )
    return {
        "ok": True,
        "username": username,
        "setup_complete": bool(settings.get("SETUP_WIZARD_COMPLETE")),
        "should_show": bool(should_show),
        "required_complete": bool(required_complete),
        "library_folder_count": len(folders),
        "library_folders": folders,
        "skipped": skipped,
        "tools": tools,
        "settings": {
            "YOUTUBE_DOWNLOAD_DIR": str(settings.get("YOUTUBE_DOWNLOAD_DIR") or ""),
            "SOULSEEK_DOWNLOAD_DIR": str(settings.get("SOULSEEK_DOWNLOAD_DIR") or ""),
            "DOWNLOAD_DIR": str(settings.get("DOWNLOAD_DIR") or ""),
        },
        "setup": setup,
        "services": services,
        "debrid": debrid_status,
    }


@app.route("/api/setup/status", methods=["GET"])
def api_setup_status():
    username = _current_settings_username()
    settings = _apply_runtime_settings_for_user(username) if username else ensure_app_settings(defaults_overrides=_default_app_overrides())
    return jsonify(_setup_status_for_user(username, settings))


@app.route("/api/setup/skip", methods=["POST"])
def api_setup_skip():
    data = request.get_json(silent=True) or {}
    service = str(data.get("service") or "").strip().lower()
    allowed = {"library", "debrid", "soulseek", "lastfm", "youtube", "ffmpeg", "ffprobe", "ytdlp", "downloads", "knaben"}
    if service not in allowed:
        return jsonify({"ok": False, "error": "Unknown setup step"}), 400
    username = _current_settings_username()
    settings = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    skipped = _setup_skipped_services(settings)
    skipped[service] = "skipped"
    saved = save_app_settings({"SETUP_SKIPPED_SERVICES": skipped}, username=username, defaults_overrides=_default_app_overrides())
    if username:
        saved = _apply_runtime_settings_for_user(username, force=True)
    return jsonify(_setup_status_for_user(username, saved))


@app.route("/api/setup/finish", methods=["POST"])
def api_setup_finish():
    username = _current_settings_username()
    settings = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    status = _setup_status_for_user(username, settings)
    if not status.get("required_complete"):
        return jsonify({"ok": False, "error": "Add a library folder before finishing setup."}), 400
    saved = save_app_settings({"SETUP_WIZARD_COMPLETE": True}, username=username, defaults_overrides=_default_app_overrides())
    if username:
        saved = _apply_runtime_settings_for_user(username, force=True)
    _kick_library_indexes_from_settings(saved)
    return jsonify(_setup_status_for_user(username, saved))


@app.route("/api/services/status", methods=["GET"])
def api_services_status():
    username = _current_settings_username()
    settings = _apply_runtime_settings_for_user(username) if username else ensure_app_settings(defaults_overrides=_default_app_overrides())
    return jsonify({"ok": True, "services": _service_status_payload(settings)})


@app.route("/api/settings/export", methods=["GET"])
def api_settings_export():
    username = _current_settings_username()
    settings = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    payload = {}
    for key in sorted(APP_SETTING_KEYS):
        if key in {"SETUP_SKIPPED_SERVICES", "SETUP_WIZARD_COMPLETE"}:
            payload[key] = settings.get(key)
            continue
        if key in SECRET_SETTING_KEYS:
            continue
        payload[key] = settings.get(key)
    return jsonify({"ok": True, "version": 1, "username": username, "include_secrets": False, "settings": payload})


@app.route("/api/settings/import", methods=["POST"])
def api_settings_import():
    data = request.get_json(silent=True) or {}
    raw_settings = data.get("settings")
    if not isinstance(raw_settings, dict):
        return jsonify({"ok": False, "error": "Import file must contain a settings object."}), 400
    include_secrets = bool(data.get("include_secrets"))
    clean = {}
    for key, value in raw_settings.items():
        key_upper = str(key).upper()
        if key_upper not in APP_SETTING_KEYS:
            continue
        if key_upper in SECRET_SETTING_KEYS and not include_secrets:
            continue
        clean[key_upper] = value
    username = _current_settings_username()
    saved = save_app_settings(clean, username=username, defaults_overrides=_default_app_overrides())
    if username:
        _apply_runtime_settings_for_user(username, force=True)
    if "LIBRARY_FOLDERS" in clean:
        _kick_library_indexes_from_settings(saved)
    return jsonify({"ok": True, "settings": masked_settings(saved), "imported_keys": sorted(clean.keys())})


@app.route("/api/settings/save", methods=["POST"])
def api_settings_save():
    data = request.get_json(silent=True) or {}
    settings_updates = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    startup_updates = data.get("startup") if isinstance(data.get("startup"), dict) else {}

    clean_settings = {}
    for key, value in settings_updates.items():
        key_upper = str(key).upper()
        if value == "***":
            continue
        clean_settings[key_upper] = value
    username = _current_settings_username()
    saved = save_app_settings(clean_settings, username=username, defaults_overrides=_default_app_overrides())

    cfg = ensure_startup_security_config()
    if "PORT" in startup_updates:
        try:
            cfg["PORT"] = max(1, min(65535, int(startup_updates.get("PORT"))))
        except Exception:
            pass
    if "ENABLE_MCP" in startup_updates:
        cfg["ENABLE_MCP"] = bool(startup_updates.get("ENABLE_MCP"))
        if cfg["ENABLE_MCP"] and not str(cfg.get("MCP_TOKEN") or "").strip():
            cfg["MCP_TOKEN"] = secrets.token_urlsafe(48)
    save_config(cfg)

    for key, value in saved.items():
        if key in CONFIG_KEYS:
            globals()[key] = _coerce_config_value(key, value)
    if username:
        saved = _apply_runtime_settings_for_user(username, force=True)
    library_setting_keys = {"LIBRARY_FOLDERS", "DOWNLOAD_DIR", "SOULSEEK_DOWNLOAD_DIR", "YOUTUBE_DOWNLOAD_DIR"}
    if library_setting_keys.intersection(clean_settings):
        clear_index_cache()
        _kick_library_indexes_from_settings(saved)
    restart_required = bool(set(startup_updates).intersection({"PORT", "ENABLE_MCP"}))
    return jsonify({"ok": True, "settings": masked_settings(saved), "restart_required": restart_required, "library_versions": library_root_versions()})


@app.route("/api/settings/mcp_reset_token", methods=["POST"])
def api_settings_mcp_reset_token():
    cfg = ensure_startup_security_config()
    cfg["MCP_TOKEN"] = secrets.token_urlsafe(48)
    cfg["ENABLE_MCP"] = True
    save_config(cfg)
    return jsonify({"ok": True, "saved": True})


@app.route("/api/settings/pick_path", methods=["POST"])
def api_settings_pick_path():
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind") or "directory")
    try:
        path = pick_system_path(kind)
    except Exception:
        return jsonify({"ok": False, "error": "System picker is unavailable", "manual": True}), 400
    if not path:
        return jsonify({"ok": False, "error": "No path selected", "canceled": True})
    return jsonify({"ok": True, "path": path})


def _coerce_glass_defaults(raw: Any) -> dict[str, Any]:
    keys = ["libraryList", "wheel", "pathPill", "infoPill", "listPills", "selectedRow"]
    labels = {
        "libraryList": "Library list",
        "wheel": "Wheel",
        "pathPill": "Path pill",
        "infoPill": "Info pill",
        "listPills": "List pills",
        "selectedRow": "Selected row",
    }
    numeric_limits = {
        "glassTint": (0.0, 2.0),
        "resolution": (0.25, 3.0),
        "refraction": (0.0, 0.25),
        "bevelDepth": (0.0, 0.35),
        "bevelWidth": (0.0, 0.5),
        "frost": (0.0, 5.0),
        "refractionFill": (0.0, 1.0),
        "magnify": (0.001, 3.0),
    }
    source = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    if "infoPill" not in source and isinstance(source.get("pathPill"), dict):
        source = dict(source)
        source["infoPill"] = source["pathPill"]
    elif "infoPill" not in source and isinstance(source.get("nowPlayingPill"), dict):
        source = dict(source)
        source["infoPill"] = source["nowPlayingPill"]
    for key in keys:
        item = source.get(key) if isinstance(source.get(key), dict) else {}
        mode = str(item.get("mode") or "clear").strip().lower()
        if mode not in {"clear", "light", "dark"}:
            mode = "clear"
        clean: dict[str, Any] = {"label": labels[key], "mode": mode}
        for field, (min_value, max_value) in numeric_limits.items():
            try:
                value = float(item.get(field, 1.0 if field in {"glassTint", "magnify"} else 0.0))
            except Exception:
                value = 1.0 if field in {"glassTint", "magnify"} else 0.0
            clean[field] = round(max(min_value, min(max_value, value)), 4)
        clean["specular"] = bool(item.get("specular"))
        clean["shadow"] = bool(item.get("shadow"))
        out[key] = clean
    return out


def _coerce_advanced_ui_defaults(raw: Any, glass: dict[str, Any]) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}

    def clamp_num(key: str, fallback: float, min_value: float, max_value: float) -> float:
        try:
            value = float(source.get(key, fallback))
        except Exception:
            value = fallback
        return round(max(min_value, min(max_value, value)), 4)

    text_defaults = {
        "wheelLabels": "transparent",
        "pathPill": "transparent",
        "infoPill": "transparent",
        "rows": "transparent",
        "rowPills": "transparent",
        "selectedRow": "contrast",
        "selectedRowPills": "contrast",
    }
    text_modes_raw = source.get("textModes") if isinstance(source.get("textModes"), dict) else {}
    text_modes = {}
    for key, fallback in text_defaults.items():
        inherited = text_modes_raw.get("pathPill") if key == "infoPill" and "infoPill" not in text_modes_raw else fallback
        value = str(text_modes_raw.get(key, inherited)).strip().lower()
        text_modes[key] = value if value in {"black", "white", "engraved", "contrast", "transparent"} else fallback

    fps_defaults = {
        "selectedRow": 60,
        "wheelTilt": 60,
        "libraryList": 60,
        "infoPill": 60,
        "albumArtTransition": 60,
        "pageTransition": 60,
        "pathPill": 60,
    }
    fps_raw = source.get("animationFps") if isinstance(source.get("animationFps"), dict) else {}
    animation_fps = {}
    for key, fallback in fps_defaults.items():
        try:
            inherited = fps_raw.get("pathPill") if key == "infoPill" and "infoPill" not in fps_raw else fallback
            value = int(fps_raw.get(key, inherited))
        except Exception:
            value = fallback
        animation_fps[key] = value if value in {30, 60, 120} else fallback

    preset = str(source.get("visualizerPreset") or "album").strip().lower()
    if preset not in {"album", "aurora", "ember", "prism", "sonar", "cascade", "nova", "lattice"}:
        preset = "album"
    legacy_strength = str(source.get("visualizerStrength") or "high").strip().lower()
    legacy_brightness = {"low": 35, "medium": 50, "high": 60}.get(legacy_strength, 60)
    try:
        brightness = int(source.get("visualizerMaxBrightnessPct", legacy_brightness))
    except Exception:
        brightness = legacy_brightness
    brightness = max(0, min(200, brightness))
    try:
        fps_lock = int(source.get("visualizerFpsLock", 60))
    except Exception:
        fps_lock = 60
    if fps_lock not in {30, 60, 120}:
        fps_lock = 60

    return {
        "visualizer": bool(source.get("visualizer", True)),
        "visualizerMaxBrightnessPct": brightness,
        "visualizerPreset": preset,
        "visualizerFpsLock": fps_lock,
        "textModes": text_modes,
        "textTransparency": clamp_num("textTransparency", 0.68, 0.0, 1.0),
        "animationFps": animation_fps,
        "performanceOverlayButton": bool(source.get("performanceOverlayButton", False)),
        "performanceOverlayText": bool(source.get("performanceOverlayText", False)),
        "liquidGlassElements": "__LIQUID_GLASS_DEFAULTS__",
        "centerBounceAmount": clamp_num("centerBounceAmount", 0.075, 0.0, 0.3),
        "centerBounceDuration": clamp_num("centerBounceDuration", 240.0, 0.0, 1000.0),
        "centerBounceOvershoot": clamp_num("centerBounceOvershoot", 0.9, 0.0, 1.4),
        "wheelClickTiltAmount": clamp_num("wheelClickTiltAmount", 0.5, 0.0, 1.0),
        "wheelTiltRampDuration": clamp_num("wheelTiltRampDuration", 90.0, 0.0, 1000.0),
        "wheelTiltReleaseDuration": clamp_num("wheelTiltReleaseDuration", 360.0, 0.0, 1200.0),
        "infoPillDarkMultiplier": clamp_num("infoPillDarkMultiplier", 1.0, 0.0, 4.0),
        "infoPillLightMultiplier": clamp_num("infoPillLightMultiplier", 1.0, 0.0, 4.0),
    }


def _coerce_app_default_overrides(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    skip = set(SECRET_SETTING_KEYS) | {
        "LIBRARY_FOLDERS",
        "SETUP_SKIPPED_SERVICES",
        "SETUP_WIZARD_COMPLETE",
    }
    path_like_suffixes = ("_DIR", "_PATH")
    out: dict[str, Any] = {}
    for key, value in source.items():
        key_upper = str(key).upper()
        if key_upper not in APP_SETTING_KEYS or key_upper in skip or key_upper.endswith(path_like_suffixes):
            continue
        if value == "***":
            continue
        try:
            out[key_upper] = _coerce_config_value(key_upper, value)
        except Exception:
            pass
    return out


@app.route("/api/defaults/diff", methods=["GET"])
def api_defaults_diff():
    username = _current_settings_username()
    current = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    private = {"DOWNLOAD_DIR", "SOULSEEK_DOWNLOAD_DIR", "YOUTUBE_DOWNLOAD_DIR", "LIBRARY_FOLDERS", "FFMPEG_PATH", "FFPROBE_PATH", "CACHE_DIR_NAME"}
    changed = {}
    for key, source_value in DEFAULT_APP_SETTINGS.items():
        if key in SECRET_SETTING_KEYS or key in private:
            continue
        current_value = current.get(key)
        if current_value != source_value:
            changed[key] = {"source": source_value, "current": current_value}
    return jsonify({"ok": True, "changes": changed, "excluded_private": sorted(private), "excluded_secrets": sorted(SECRET_SETTING_KEYS)})


@app.route("/api/library/building", methods=["GET"])
def api_library_building():
    any_building, roots_status = index_building_status()
    return jsonify({"ok": True, "any_building": any_building, "roots": roots_status, "versions": library_root_versions()})


@app.route("/api/client-state", methods=["GET"])
def api_client_state():
    for rid, _, root_abs, mode in roots():
        try:
            ensure_index_async(rid, root_abs, mode=mode)
            library_watch_root(rid, root_abs, mode=mode)
        except Exception:
            pass
    any_building, roots_status = index_building_status()
    username = _current_settings_username()
    settings = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    search_history_items = _load_search_history()
    with PLAYBACK_STATE_LOCK:
        playback_recent = PLAYBACK_STATE.get("recent") or []
        playback_version = int(PLAYBACK_STATE.get("version") or len(playback_recent) or 0)
    services = _service_status_payload(settings)
    return jsonify({
        "ok": True,
        "user": username,
        "app_version": str(VERSION_INFO.get("display_version") or VERSION),
        "short_commit": str(VERSION_INFO.get("short_commit") or ""),
        "asset_version": str(ASSET_VERSION),
        "icon_version": str(ICON_VERSION),
        "settings_version": abs(hash(json.dumps(masked_settings(settings), sort_keys=True, default=str))) % 1000000007,
        "library_versions": library_root_versions(),
        "search_history_version": int(max([float(x.get("ts") or 0) for x in search_history_items] + [0])),
        "playback_version": playback_version,
        "service_status_version": abs(hash(json.dumps(services, sort_keys=True, default=str))) % 1000000007,
        "setup_complete": bool(settings.get("SETUP_WIZARD_COMPLETE")),
        "library_building": any_building,
        "library_building_roots": roots_status,
    })


@app.route("/api/performance", methods=["GET"])
def api_performance():
    username = _current_settings_username()
    settings = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    any_building, roots_status = index_building_status()
    services = _service_status_payload(settings)
    service_summary = {}
    for key, value in services.items():
        if isinstance(value, dict):
            service_summary[key] = {
                "status": str(value.get("status") or ""),
                "configured": bool(value.get("configured") or value.get("api_configured") or value.get("set")),
                "connected": bool(value.get("connected")),
                "error": str(value.get("error") or value.get("warning") or ""),
            }
    return jsonify({
        "ok": True,
        "library_versions": library_root_versions(),
        "indexing": {"any_building": bool(any_building), "roots": roots_status, "enrichment": enrichment_status()},
        "services": service_summary,
        "api_timings": list(_RECENT_API_TIMINGS[-30:]),
        "version": {
            "display": str(VERSION_INFO.get("display_version") or VERSION),
            "source": str(VERSION_INFO.get("source") or ""),
            "short_commit": str(VERSION_INFO.get("short_commit") or ""),
            "dirty": bool(VERSION_INFO.get("dirty")),
            "asset_version": str(ASSET_VERSION),
            "icon_version": str(ICON_VERSION),
        },
        "server_time": time.time(),
    })


@app.route("/api/sync", methods=["GET"])
def api_sync():
    username = _current_settings_username()
    settings = ensure_app_settings(username=username, defaults_overrides=_default_app_overrides())
    try:
        since = json.loads(request.args.get("since") or "{}")
    except Exception:
        since = {}
    if not isinstance(since, dict):
        since = {}
    since_roots = since.get("library_versions") if isinstance(since.get("library_versions"), dict) else {}
    root_payload = [{"id": rid, "name": name, "mode": mode, "version": int(library_root_versions().get(rid) or 0)} for rid, name, _, mode in roots()]
    library_changes = []
    deleted = []
    for rid, _, root_abs, mode in roots():
        try:
            ensure_index_async(rid, root_abs, mode=mode)
        except Exception:
            pass
        old_v = int(since_roots.get(rid) or 0)
        manifest = library_manifest(rid, since_version=old_v)
        if manifest:
            items = manifest.get("items") or []
            library_changes.extend([dict(item, root_id=rid) for item in items if not item.get("deleted")])
            deleted.extend([dict(item, root_id=rid) for item in items if item.get("deleted")])
    with PLAYBACK_STATE_LOCK:
        now = PLAYBACK_STATE.get("now")
        recent = PLAYBACK_STATE.get("recent") or []
        version = int(PLAYBACK_STATE.get("version") or len(recent) or 0)
        playback = {"now": dict(now) if isinstance(now, dict) else None, "recent": [dict(x) for x in recent if isinstance(x, dict)][:100], "session": dict(PLAYBACK_STATE.get("playback_session") or {}), "version": version}
    for item in playback.get("recent") or []:
        for key in ["_key", "_sess", "_stream_item"]:
            item.pop(key, None)
    if isinstance(playback.get("now"), dict):
        for key in ["_key", "_sess", "_stream_item"]:
            playback["now"].pop(key, None)
    state_payload = {
        "ok": True,
        "server_version": int(time.time()),
        "user": username,
        "asset_version": str(ASSET_VERSION),
        "icon_version": str(ICON_VERSION),
        "roots": root_payload,
        "library_versions": library_root_versions(),
        "library_changes": library_changes,
        "deleted": deleted,
        "settings": masked_settings(settings),
        "search_history": _load_search_history(),
        "playback": playback,
        "services": _service_status_payload(settings),
        "setup_complete": bool(settings.get("SETUP_WIZARD_COMPLETE")),
    }
    return jsonify(state_payload)


@app.route("/api/library/manifest", methods=["GET"])
def api_library_manifest():
    root_id = (request.args.get("root_id") or "").strip()
    try:
        since_version = int(request.args.get("since_version") or 0)
    except Exception:
        since_version = 0
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, mode = r
    try:
        ensure_index_async(root_id, root_abs, mode=mode)
    except Exception:
        pass
    manifest = library_manifest(root_id, since_version=max(0, since_version))
    if manifest is None:
        return jsonify({"ok": True, "root_id": root_id, "version": 0, "items": [], "building": True, "stale": True})
    return jsonify({"ok": True, **manifest, "building": bool(index_building_status()[1].get(root_id)), "stale": False})


@app.route("/api/library/palette", methods=["GET", "POST"])
def api_library_palette():
    if request.method == "GET":
        cache_key = (request.args.get("key") or "").strip()
        if not cache_key:
            return jsonify({"ok": False, "error": "Missing palette key"}), 400
        palette = load_palette(cache_key)
        if palette is None:
            palette = _palette_from_art_cache_key(cache_key)
        return jsonify({"ok": True, "palette": palette})

    data = request.get_json(silent=True) or {}
    cache_key = str(data.get("key") or "").strip()
    palette = data.get("palette")
    if not cache_key or not isinstance(palette, dict):
        return jsonify({"ok": False, "error": "Missing palette key or palette"}), 400
    save_palette(
        cache_key,
        palette,
        source_kind=str(data.get("source_kind") or ""),
        source_identity=str(data.get("source_identity") or ""),
        root_id=str(data.get("root_id") or ""),
        rel=str(data.get("rel") or ""),
    )
    return jsonify({"ok": True})


def _palette_from_art_cache_key(cache_key: str) -> dict | None:
    try:
        path_part = str(cache_key or "").split("|", 1)[0]
        marker = "/art/"
        if marker not in path_part:
            return None
        suffix = path_part.split(marker, 1)[1].strip("/")
        if not suffix or "/" not in suffix:
            return None
        root_id, rel_encoded = suffix.split("/", 1)
        root_id = unquote(root_id)
        rel = unquote(rel_encoded)
        if not root_id or not rel:
            return None
        return load_palette_for_media(root_id, rel)
    except Exception:
        return None


@app.route("/api/library/analysis", methods=["GET"])
def api_library_analysis():
    root_id = (request.args.get("root_id") or "").strip()
    rel = (request.args.get("rel") or "").strip()
    if not root_id or not rel:
        return jsonify({"ok": False, "error": "Missing root_id or rel"}), 400
    r = root_by_id(root_id)
    if not r:
        abort(404)
    analysis = load_visualizer_analysis_for_media(root_id, rel)
    def start_video_analysis_warm() -> bool:
        try:
            _, _, root_abs, _mode = r
            abs_path = safe_path_join(root_abs, rel)
            if not os.path.isfile(abs_path) or not is_video(abs_path):
                return False
            meta = file_meta_cached(abs_path)
            return queue_video_analysis_warm(
                abs_path,
                root_id=root_id,
                rel=rel,
                media_id=f"{root_id}:{rel}",
                duration=meta.get("duration") if isinstance(meta, dict) else None,
            )
        except Exception:
            return False
    try:
        meta = analysis.get("metadata") if isinstance(analysis, dict) else {}
        if isinstance(meta, dict) and meta.get("video_palette_pending"):
            start_video_analysis_warm()
    except Exception:
        pass
    if not analysis:
        warming = start_video_analysis_warm()
        return jsonify({"ok": True, "analysis": None, "stale": True, "warming": bool(warming)})
    blob = analysis.pop("feature_blob", b"")
    timeline = load_video_timeline(str(analysis.get("analysis_key") or ""))
    if timeline:
        analysis["video_palette_timeline"] = timeline
    analysis["feature_blob_b64"] = base64.b64encode(blob).decode("ascii")
    analysis["feature_blob_encoding"] = "base64-raw"
    return jsonify({"ok": True, "analysis": analysis, "stale": False})





# =========================
# Playback state API (server-side)
# =========================
@app.route("/api/playback/snapshot", methods=["GET"])
def api_playback_snapshot():
    return jsonify(playback_snapshot_public())

@app.route("/api/playback/recent", methods=["GET"])
def api_playback_recent():
    with PLAYBACK_STATE_LOCK:
        recent = PLAYBACK_STATE.get("recent") or []
        out = []
        for it in recent:
            if not isinstance(it, dict):
                continue
            d = dict(it)
            d.pop("_key", None)
            d.pop("_sess", None)
            d.pop("_stream_item", None)
            out.append(d)
    return jsonify({"recent": out})

@app.route("/api/playback/update", methods=["POST"])
def api_playback_update():
    js = request.get_json(silent=True) or {}
    out = playback_update_from_client(js)
    if not out.get("ok"):
        return jsonify(out), 400
    return jsonify(out)


@app.route("/api/library/browse", methods=["GET"])
def api_library_browse():
    root_id = (request.args.get("root_id") or "").strip()
    rel = (request.args.get("rel") or "").strip()
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, mode = r
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    if not os.path.isdir(abs_path):
        abort(404)

    try:
        ensure_index_async(root_id, root_abs, mode=mode)
    except Exception:
        pass

    cached = load_folder_entries(root_id, rel, abs_path)
    if cached is not None:
        return jsonify(cached)

    entries = []
    try:
        names = os.listdir(abs_path)
    except OSError:
        names = []

    dirs = []
    files = []
    for n in names:
        if n.startswith(".") or n == CACHE_DIR_NAME:
            continue
        p = os.path.join(abs_path, n)
        if os.path.isdir(p):
            dirs.append(n)
        elif os.path.isfile(p):
            ext = os.path.splitext(n)[1].lower()
            if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
                files.append(n)

    dirs.sort(key=lambda x: x.lower())
    files.sort(key=lambda x: x.lower())

    rel_norm = rel.replace("\\", "/").strip("/")
    for d in dirs:
        relp = f"{rel_norm}/{d}" if rel_norm else d
        entries.append({"type": "dir", "name": d, "rel": relp})
    for f in files:
        relp = f"{rel_norm}/{f}" if rel_norm else f
        p = os.path.join(abs_path, f)
        media = "video" if is_video(p) else ("audio" if is_audio(p) else "")
        entries.append({"type": "file", "name": f, "rel": relp, "media": media})
    version = save_folder_entries(root_id, rel, abs_path, entries)
    building = bool(index_building_status()[1].get(root_id))
    return jsonify({"entries": entries, "version": version, "building": building, "stale": False})


@app.route("/api/library/metadata", methods=["GET"])
def api_library_metadata():
    root_id = (request.args.get("root_id") or "").strip()
    level = (request.args.get("level") or "").strip().lower()
    value = (request.args.get("value") or "").strip()

    aggregate = root_id == LIBRARY_ALL_ROOT_ID
    r = None if aggregate else root_by_id(root_id)
    if not aggregate and not r:
        abort(404)
    root_abs = "" if aggregate else r[2]
    mode = "metadata" if aggregate else r[3]

    if level == "playlists":
        items = []
        if aggregate:
            for root in root_objects():
                for item in scan_root_playlists(str(root.get("path") or "")):
                    if isinstance(item, dict):
                        row = dict(item)
                        row["root_id"] = str(root.get("id") or "")
                        row["sub_label"] = str(root.get("name") or "")
                        row["forceTwoLine"] = True
                        items.append(row)
        else:
            items = scan_root_playlists(root_abs)
        if not items:
            items = [{"kind": "info", "label": "No playlists found"}]
        return jsonify({"items": items, "version": (sum(library_root_versions().values()) if aggregate else library_root_version(root_id)), "stale": False})

    if level == "playlist_tracks":
        playlist_root_id = root_id
        if aggregate:
            try:
                selector = json.loads(value) if value else {}
            except Exception:
                selector = {}
            playlist_root_id = str(selector.get("root_id") or request.args.get("item_root_id") or "")
            value = str(selector.get("rel") or selector.get("value") or value)
            selected_root = root_by_id(playlist_root_id)
            if not selected_root:
                abort(404)
            root_abs = selected_root[2]
        if is_smart_playlist_rel(value):
            items = smart_playlist_tracks_for_root(root_abs, value, playlist_root_id)
        else:
            items = playlist_tracks_for_root(root_abs, value)
        for item in items:
            if isinstance(item, dict):
                item.setdefault("root_id", playlist_root_id)
        if not items:
            items = [{"kind": "info", "label": "No playable tracks found in playlist"}]
        return jsonify({"items": items, "version": library_root_version(playlist_root_id), "stale": False})

    if aggregate:
        data = {"tracks": [], "videos": [], "movies": [], "shows": []}
        aggregate_shows: list[dict[str, Any]] = []
        building_map = index_building_status()[1]
        building = False
        for root in root_objects():
            rid = str(root.get("id") or "")
            path = str(root.get("path") or "")
            ensure_index_async(rid, path, mode="metadata")
            snapshot = get_index(rid)
            building = building or bool(building_map.get(rid)) or snapshot is None
            if not snapshot:
                continue
            for key in ("tracks", "videos", "movies"):
                for raw in snapshot.get(key) or []:
                    if isinstance(raw, dict):
                        row = dict(raw)
                        row["root_id"] = rid
                        data[key].append(row)
            for raw_show in snapshot.get("shows") or []:
                if not isinstance(raw_show, dict):
                    continue
                show = dict(raw_show)
                episodes = []
                for raw_episode in show.get("episodes") or []:
                    if isinstance(raw_episode, dict):
                        episode = dict(raw_episode)
                        episode["root_id"] = rid
                        episodes.append(episode)
                show["episodes"] = episodes
                aggregate_shows.append(show)
        aliases = load_show_aliases(LIBRARY_ALL_ROOT_ID)
        show_buckets: dict[str, dict[str, Any]] = {}
        for show in aggregate_shows:
            label = str(show.get("label") or "Show")
            raw_key = normalize_show_key(label)
            show_key = str(aliases.get(raw_key) or raw_key)
            if show_key not in show_buckets:
                for candidate_key, candidate in show_buckets.items():
                    if show_keys_close(label, str(candidate.get("label") or "")):
                        show_key = candidate_key
                        aliases[raw_key] = candidate_key
                        break
            bucket = show_buckets.setdefault(show_key, {"show_key": show_key, "label": label, "episodes": []})
            bucket["episodes"].extend(show.get("episodes") or [])
        data["shows"] = sorted(show_buckets.values(), key=lambda item: str(item.get("label") or "").lower())
        for show in data["shows"]:
            show["episodes"].sort(key=lambda item: (
                int((item.get("parse") or {}).get("season") or 0),
                int((item.get("parse") or {}).get("episode") or 0),
                str(item.get("root_id") or ""),
                str(item.get("rel") or "").lower(),
            ))
        save_show_aliases(LIBRARY_ALL_ROOT_ID, aliases)
        data["version"] = sum(int(value or 0) for value in library_root_versions().values())
    else:
        ensure_index_async(root_id, root_abs, mode=mode)
        data = get_index(root_id)
        building = bool(index_building_status()[1].get(root_id))
    if data is None:
        if level == "top":
            cats = [
                {"key": "artists", "label": "Artists"},
                {"key": "albums", "label": "Albums"},
                {"key": "songs", "label": "Songs"},
                {"key": "liked_songs", "label": "Liked Songs"},
                {"key": "genres", "label": "Genres"},
                {"key": "playlists", "label": "Playlists"},
                {"key": "movies", "label": "Movies"},
                {"key": "shows", "label": "Shows"},
                {"key": "videos", "label": "Videos"},
                {"key": "folders", "label": "Folders"},
            ]
            return jsonify({"categories": cats, "building": True, "version": 0, "stale": True})
        return jsonify({"items": [{"kind": "info", "label": "Indexing media files..."}], "building": True, "version": 0, "stale": True})

    tracks = data.get("tracks") or []
    vids = data.get("videos") or []
    version_value = int(data.get("version") or library_root_version(root_id))
    facets = {} if aggregate else (library_metadata_facets(root_id) or {})
    response_meta = {"building": building, "version": version_value, "stale": building}

    def facet_items(name: str, empty_label: str) -> list[dict]:
        payload = facets.get(name)
        if isinstance(payload, list):
            return payload or [{"kind": "info", "label": empty_label}]
        return []

    def track_facet_key(*, artist: str = "", album: str = "", genre: str = "") -> str:
        return json.dumps({"artist": artist, "album": album, "genre": genre}, ensure_ascii=False, sort_keys=True)

    def playable_video_row(record: dict, kind: str) -> dict:
        parsed = record.get("parse") if isinstance(record.get("parse"), dict) else {}
        rid = str(record.get("root_id") or root_id)
        rel = str(record.get("rel") or "")
        progress = media_progress_for(rid, rel)
        percent = int(progress.get("completion_percent") or record.get("completion_percent") or 0)
        duration = record.get("duration")
        duration_label = duration_text(duration)
        quality = str(record.get("quality") or parsed.get("quality") or "")
        friendly = bool(record.get("browser_friendly") or parsed.get("browser_friendly"))
        year = parsed.get("year")
        pills = []
        if kind == "show_episode":
            season = int(parsed.get("season") or 0)
            episode = int(parsed.get("episode") or 0)
            episode_end = parsed.get("episode_end")
            number = f"S{season:02d}E{episode:02d}" if season else f"E{episode:02d}"
            if episode_end:
                number += f" to E{int(episode_end):02d}"
            pills.append(number)
        if parsed.get("airdate"):
            pills.append(str(parsed.get("airdate")))
        if year:
            pills.append(str(year))
        if duration_label:
            pills.append(duration_label)
        if quality:
            pills.append(quality)
        pills.extend(["\u2713" if friendly else "\u00d7", f"{percent}%"])
        if kind == "show_episode":
            title = str(parsed.get("episode_title") or parsed.get("title") or record.get("title") or record.get("name") or "Episode")
            label = title
        else:
            label = str(parsed.get("title") or record.get("title") or record.get("name") or ("Movie" if kind == "movie" else "Video"))
        return {
            "kind": kind if kind != "video" else "file",
            "label": label,
            "sub_label": rel,
            "root_id": rid,
            "root": {"id": rid},
            "rel": rel,
            "media": "video",
            "year": year,
            "duration": duration,
            "duration_text": duration_label,
            "quality": quality,
            "browser_friendly": friendly,
            "completion_percent": percent,
            "position": float(progress.get("position") or record.get("position") or 0),
            "source": str(record.get("source") or "library"),
            "season": parsed.get("season"),
            "episode": parsed.get("episode"),
            "episode_end": parsed.get("episode_end"),
            "pills": pills,
            "forceTwoLine": True,
        }

    if level == "top":
        cats = [
            {"key": "artists", "label": "Artists"},
            {"key": "albums", "label": "Albums"},
            {"key": "songs", "label": "Songs"},
            {"key": "liked_songs", "label": "Liked Songs"},
            {"key": "genres", "label": "Genres"},
            {"key": "playlists", "label": "Playlists"},
            {"key": "movies", "label": "Movies"},
            {"key": "shows", "label": "Shows"},
            {"key": "videos", "label": "Videos"},
            {"key": "folders", "label": "Folders"},
        ]
        return jsonify({"categories": cats, **response_meta})

    if level == "artists":
        items = facet_items("artists", "No artist tags found")
        if items:
            return jsonify({"items": items, **response_meta})
        s = sorted({(t.get("artist") or "").strip() for t in tracks if (t.get("artist") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "artist", "label": a, "value": a} for a in s] or [{"kind": "info", "label": "No artist tags found"}]
        return jsonify({"items": items, **response_meta})

    if level == "albums":
        artist_filter = value
        if artist_filter and isinstance(facets.get("albums_by_artist"), dict):
            payload = facets.get("albums_by_artist", {}).get(artist_filter)
            if isinstance(payload, list):
                return jsonify({"items": payload or [{"kind": "info", "label": "No albums found"}], **response_meta})
        if not artist_filter:
            payload = facet_items("albums", "No albums found")
            if payload:
                return jsonify({"items": payload, **response_meta})
        albums = []
        seen = set()
        for t in tracks:
            art = (t.get("artist") or "").strip()
            alb = (t.get("album") or "").strip()
            if not alb:
                continue
            if artist_filter and art != artist_filter:
                continue
            key = (art, alb) if not artist_filter else ("", alb)
            if key in seen:
                continue
            seen.add(key)
            label = alb if artist_filter else (alb + (f"   {art}" if art else ""))
            val = json.dumps({"artist": art, "album": alb})
            albums.append({"kind": "album", "label": label, "value": val})
        albums.sort(key=lambda x: x["label"].lower())
        if artist_filter:
            # Special entry to show every track for this artist (no album filter)
            albums.insert(0, {"kind": "album", "label": "All Songs", "value": json.dumps({"artist": artist_filter, "album": ""})})
            albums.insert(0, {"kind": "album", "label": "Liked Songs", "value": json.dumps({"artist": artist_filter, "album": "", "liked": True})})

        if not albums:
            albums = [{"kind": "info", "label": "No albums found"}]
        return jsonify({"items": albums, **response_meta})

    if level == "tracks":
        try:
            sel = json.loads(value) if value else {}
        except Exception:
            sel = {}
        artist = (sel.get("artist") or "").strip()
        album = (sel.get("album") or "").strip()
        genre = (sel.get("genre") or "").strip()
        liked_only = bool(sel.get("liked") or sel.get("loved") or sel.get("liked_only"))
        if liked_only and not lastfm_enabled():
            return jsonify({"items": [{"kind": "info", "label": "Last.fm is not configured. Add API credentials or skip Last.fm features."}], **response_meta})
        if not liked_only and isinstance(facets.get("tracks_by_key"), dict):
            payload = facets.get("tracks_by_key", {}).get(track_facet_key(artist=artist, album=album, genre=genre))
            if isinstance(payload, list):
                return jsonify({"items": payload or [{"kind": "info", "label": "No tracks found"}], **response_meta})
        tr = []
        for t in tracks:
            if artist and (t.get("artist") or "").strip() != artist:
                continue
            if album and (t.get("album") or "").strip() != album:
                continue
            if genre and (t.get("genre") or "").strip() != genre:
                continue
            if liked_only:
                a = (t.get("artist") or "").strip()
                tt = (t.get("title") or t.get("name") or "").strip()
                b = (t.get("album") or "").strip()
                if not a or not tt or (not lastfm_is_loved(a, tt, b)):
                    continue
            label = t.get("title") or t.get("name") or "Track"
            tr.append({"kind": "track", "label": label, "rel": t.get("rel"), "root_id": t.get("root_id") or root_id, "root": {"id": t.get("root_id") or root_id}, "badge": (t.get("track") or "")})
        tr.sort(key=lambda x: track_sort_key(x.get("badge") or "") + (x.get("label") or "",))
        if not tr:
            tr = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": tr, **response_meta})


    if level == "liked_songs":
        if not lastfm_enabled():
            return jsonify({"items": [{"kind": "info", "label": "Last.fm is not configured. Add API credentials or skip Last.fm features."}], **response_meta})
        items = []
        for t in tracks:
            a = (t.get("artist") or "").strip()
            tt = (t.get("title") or t.get("name") or "").strip()
            b = (t.get("album") or "").strip()
            if not a or not tt:
                continue
            if not lastfm_is_loved(a, tt, b):
                continue
            items.append({"kind": "track", "label": (t.get("title") or t.get("name") or "Track"), "rel": t.get("rel"), "root_id": t.get("root_id") or root_id, "root": {"id": t.get("root_id") or root_id}, "badge": (t.get("track") or "")})
        items.sort(key=lambda x: (x.get("label") or "").lower())
        if not items:
            items = [{"kind": "info", "label": "No liked songs found"}]
        return jsonify({"items": items[:3000], **response_meta})

    if level == "songs":
        items = facet_items("songs", "No songs found")
        if items:
            return jsonify({"items": items, **response_meta})
        s = sorted(tracks, key=lambda x: (x.get("title") or x.get("name") or "").lower())
        items = [{"kind": "track", "label": (t.get("title") or t.get("name") or "Track"), "rel": t.get("rel"), "root_id": t.get("root_id") or root_id, "root": {"id": t.get("root_id") or root_id}} for t in s[:3000]]
        if not items:
            items = [{"kind": "info", "label": "No songs found"}]
        return jsonify({"items": items, **response_meta})

    if level == "genres":
        items = facet_items("genres", "No genre tags found")
        if items:
            return jsonify({"items": items, **response_meta})
        s = sorted({(t.get("genre") or "").strip() for t in tracks if (t.get("genre") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "genre", "label": g, "value": g} for g in s] or [{"kind": "info", "label": "No genre tags found"}]

        return jsonify({"items": items, **response_meta})

    if level == "genre_albums":
        genre = value
        if isinstance(facets.get("genre_albums"), dict):
            payload = facets.get("genre_albums", {}).get(genre)
            if isinstance(payload, list):
                return jsonify({"items": payload or [{"kind": "info", "label": "No tracks found"}], **response_meta})
        albums = []
        seen = set()
        any_match = False

        for t in tracks:
            if (t.get("genre") or "").strip() != genre:
                continue
            any_match = True
            art = (t.get("artist") or "").strip()
            alb = (t.get("album") or "").strip()
            if not alb:
                continue
            key = (art, alb)
            if key in seen:
                continue
            seen.add(key)
            label = alb + (f"   {art}" if art else "")
            val = json.dumps({"genre": genre, "artist": art, "album": alb})
            albums.append({"kind": "album", "label": label, "value": val})

        albums.sort(key=lambda x: x["label"].lower())

        # Always offer a way to play all tracks for this genre, even if albums are missing tags.
        if genre and any_match:
            albums.insert(0, {"kind": "album", "label": "All Songs", "value": json.dumps({"genre": genre, "album": ""})})
            albums.insert(0, {"kind": "album", "label": "Liked Songs", "value": json.dumps({"genre": genre, "album": "", "liked": True})})

        if not albums:
            albums = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": albums, **response_meta})

    if level == "genre_tracks":
        genre = value
        if isinstance(facets.get("tracks_by_key"), dict):
            payload = facets.get("tracks_by_key", {}).get(track_facet_key(genre=genre))
            if isinstance(payload, list):
                return jsonify({"items": payload or [{"kind": "info", "label": "No tracks found"}], **response_meta})
        items = []
        for t in tracks:
            if (t.get("genre") or "").strip() != genre:
                continue
            label = t.get("title") or t.get("name") or "Track"
            items.append({"kind": "track", "label": label, "rel": t.get("rel"), "root_id": t.get("root_id") or root_id, "root": {"id": t.get("root_id") or root_id}})
        items.sort(key=lambda x: (x.get("label") or "").lower())
        if not items:
            items = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": items, **response_meta})

    if level == "movies":
        items = [playable_video_row(item, "movie") for item in (data.get("movies") or []) if isinstance(item, dict)]
        if not items:
            items = [{"kind": "info", "label": "No movies found"}]
        return jsonify({"items": items[:3000], **response_meta})

    if level == "shows":
        items = []
        for show in data.get("shows") or []:
            if not isinstance(show, dict):
                continue
            episodes = [item for item in (show.get("episodes") or []) if isinstance(item, dict)]
            percentages = [int(media_progress_for(str(item.get("root_id") or root_id), str(item.get("rel") or "")).get("completion_percent") or 0) for item in episodes]
            percent = math.floor(sum(percentages) / len(percentages)) if percentages else 0
            count = len(episodes)
            items.append({
                "kind": "show", "label": str(show.get("label") or "Show"), "show_key": str(show.get("show_key") or ""),
                "episode_count": count, "completion_percent": percent, "pills": [f"{count} episode" + ("" if count == 1 else "s"), f"{percent}%"],
            })
        if not items:
            items = [{"kind": "info", "label": "No shows found"}]
        return jsonify({"items": items, **response_meta})

    if level == "show_seasons":
        show = next((item for item in (data.get("shows") or []) if isinstance(item, dict) and str(item.get("show_key") or "") == value), None)
        if not show:
            return jsonify({"items": [{"kind": "info", "label": "Show not found"}], **response_meta})
        seasons: dict[int, list[dict]] = {}
        for episode in show.get("episodes") or []:
            if isinstance(episode, dict):
                seasons.setdefault(int((episode.get("parse") or {}).get("season") or 0), []).append(episode)
        items = []
        for season, episodes in sorted(seasons.items()):
            percentages = [int(media_progress_for(str(item.get("root_id") or root_id), str(item.get("rel") or "")).get("completion_percent") or 0) for item in episodes]
            percent = math.floor(sum(percentages) / len(percentages)) if percentages else 0
            count = len(episodes)
            label = "Specials" if season == 0 else f"Season {season}"
            items.append({"kind": "show_season", "label": label, "show_key": value, "season": season, "episode_count": count, "completion_percent": percent, "pills": [f"{count} episode" + ("" if count == 1 else "s"), f"{percent}%"]})
        return jsonify({"items": items or [{"kind": "info", "label": "No seasons found"}], **response_meta})

    if level == "show_episodes":
        try:
            selector = json.loads(value) if value else {}
        except Exception:
            selector = {}
        show_key = str(selector.get("show_key") or "")
        season = int(selector.get("season") or 0)
        show = next((item for item in (data.get("shows") or []) if isinstance(item, dict) and str(item.get("show_key") or "") == show_key), None)
        episodes = [item for item in ((show or {}).get("episodes") or []) if isinstance(item, dict) and int((item.get("parse") or {}).get("season") or 0) == season]
        items = []
        for episode in episodes:
            row = playable_video_row(episode, "show_episode")
            row["show_key"] = show_key
            items.append(row)
        return jsonify({"items": items or [{"kind": "info", "label": "No episodes found"}], **response_meta})

    if level == "videos":
        items = [playable_video_row(item, "video") for item in sorted(vids, key=lambda x: (x.get("title") or x.get("name") or "").lower())[:3000] if isinstance(item, dict)]
        if not items:
            items = [{"kind": "info", "label": "No videos found"}]
        return jsonify({"items": items, **response_meta})

    return jsonify({"items": [{"kind": "info", "label": "Unsupported view"}], **response_meta})


@app.route("/api/library/playlist_create", methods=["POST"])
def api_library_playlist_create():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    name = str(js.get("name") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = create_root_playlist(root_abs, name)
    if not ok:
        return jsonify({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return jsonify({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@app.route("/api/library/playlist_rename", methods=["POST"])
def api_library_playlist_rename():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    name = str(js.get("name") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = rename_root_playlist(root_abs, playlist_rel, name)
    if not ok:
        return jsonify({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return jsonify({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@app.route("/api/library/playlist_add", methods=["POST"])
def api_library_playlist_add():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    tracks = js.get("tracks") if isinstance(js.get("tracks"), list) else []
    clean_tracks = [str(x or "").strip() for x in tracks if str(x or "").strip()]

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = add_tracks_to_playlist(root_abs, playlist_rel, clean_tracks)
    if not ok:
        return jsonify({"ok": False, "error": err, "added": int((info or {}).get("added") or 0)})
    return jsonify({"ok": True, "added": int((info or {}).get("added") or 0)})


@app.route("/api/library/playlist_remove", methods=["POST"])
def api_library_playlist_remove():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    tracks = js.get("tracks") if isinstance(js.get("tracks"), list) else []
    clean_tracks = [str(x or "").strip() for x in tracks if str(x or "").strip()]

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = remove_tracks_from_playlist(root_abs, playlist_rel, clean_tracks)
    if not ok:
        return jsonify({"ok": False, "error": err, "removed": int((info or {}).get("removed") or 0)})
    return jsonify({"ok": True, "removed": int((info or {}).get("removed") or 0)})




@app.route("/api/library/playlist_delete", methods=["POST"])
def api_library_playlist_delete():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = delete_root_playlist(root_abs, playlist_rel)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "smart": bool((info or {}).get("smart"))})


@app.route("/api/library/smart_playlist_create", methods=["POST"])
def api_library_smart_playlist_create():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    name = str(js.get("name") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = create_root_smart_playlist(root_abs, name)
    if not ok:
        return jsonify({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return jsonify({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@app.route("/api/library/smart_playlist_rules", methods=["GET", "POST"])
def api_library_smart_playlist_rules():
    if request.method == "GET":
        root_id = (request.args.get("root_id") or "").strip()
        playlist_rel = (request.args.get("rel") or "").strip()
        r = root_by_id(root_id)
        if not r:
            abort(404)
        _, _, root_abs, _ = r
        ok, err, info = load_smart_playlist_rules(root_abs, playlist_rel)
        if not ok:
            return jsonify({"ok": False, "error": err}), 400
        return jsonify({"ok": True, "text": str((info or {}).get("text") or ""), "label": str((info or {}).get("label") or "")})

    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    text = str(js.get("text") or "")
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    ok, err, info = save_smart_playlist_rules(root_abs, playlist_rel, text)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "label": str((info or {}).get("label") or "")})


@app.route("/api/library/filemeta", methods=["GET"])
def api_library_filemeta():
    root_id = (request.args.get("root_id") or "").strip()
    rel = (request.args.get("rel") or "").strip()
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(rel)
        if not it:
            abort(404)
        return jsonify({
            "title": str(it.get("title") or it.get("name") or ""),
            "artist": str(it.get("artist") or ""),
            "album": str(it.get("album") or ""),
            "genre": "",
            "duration": None,
            "tech": str(it.get("quality") or it.get("ext") or ""),
            "art": str(it.get("art") or ""),
        })
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        abort(404)

    meta = file_meta_cached(abs_path)

    art = ""
    ver = ""
    try:
        ver = str(int(os.path.getmtime(os.path.dirname(abs_path))))
    except OSError:
        ver = ""
    ap = art_for_media_path(abs_path) if is_audio(abs_path) else None
    if ap:
        art = url_for("art", root_id=root_id, relpath=rel)
        if ver:
            art = art + "?v=" + ver

    return jsonify(
        {
            "title": meta.get("title") or os.path.splitext(os.path.basename(abs_path))[0],
            "artist": meta.get("artist") or "",
            "album": meta.get("album") or "",
            "genre": meta.get("genre") or "",
            "duration": meta.get("duration"),
            "tech": meta.get("tech") or "",
            "art": art,
        }
    )


@app.route("/art/<root_id>/<path:relpath>", methods=["GET", "HEAD"])
def art(root_id: str, relpath: str):
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    ap = art_for_media_path(abs_path)
    if not ap:
        abort(404)
    return range_response(ap)




def hls_cache_dir() -> str:
    p = os.path.join(cache_dir(), "hls")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def _hls_stream_key_for_path(src_path: str) -> str:
    ap = os.path.abspath(src_path)
    try:
        st = os.stat(ap)
        sig = f"{ap}|{int(st.st_mtime)}|{int(st.st_size)}"
    except OSError:
        sig = ap
    return sha1_text(sig)


def _hls_build_args(src_path: str, out_dir: str) -> List[str]:
    manifest_path = os.path.join(out_dir, "stream.m3u8")
    seg_pat = os.path.join(out_dir, "seg_%05d.m4s")
    init_path = os.path.join(out_dir, "init.mp4")
    return [
        FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
        "-i", src_path,
        "-map", "0:v:0?",
        "-map", "0:a:0?",
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "0",
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", init_path,
        "-hls_segment_filename", seg_pat,
        manifest_path,
    ]


def _hls_cache_entry_for_path(src_path: str) -> Tuple[str, str]:
    key = _hls_stream_key_for_path(src_path)
    out_dir = os.path.join(hls_cache_dir(), key)
    manifest_path = os.path.join(out_dir, "stream.m3u8")
    lock = lock_for_key("hls:" + key)
    with lock:
        try:
            src_m = os.path.getmtime(src_path)
        except OSError:
            abort(404)
        ok = False
        if os.path.exists(manifest_path):
            try:
                ok = os.path.getmtime(manifest_path) >= src_m and os.path.getsize(manifest_path) > 0
            except OSError:
                ok = False
        if not ok:
            if os.path.isdir(out_dir):
                try:
                    shutil.rmtree(out_dir)
                except Exception:
                    pass
            os.makedirs(out_dir, exist_ok=True)
            args = _hls_build_args(src_path, out_dir)
            code, out, err = run_cmd(args)
            if code != 0 or not os.path.exists(manifest_path):
                raise RuntimeError((err or out or "ffmpeg HLS packaging failed").strip())
    return key, manifest_path


def _resolve_stream_source_for_hls(root_id: str, relpath: str) -> str:
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(unquote(relpath))
        if not it:
            abort(404)
        if str(it.get("source") or "").strip().lower() == 'youtube':
            try:
                return _prepare_youtube_stream_file(str(it.get('youtube_url') or it.get('url') or ''), it)
            except Exception:
                raise RuntimeError("Unable to fetch stream")
        abort(400)
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        abort(404)
    try:
        return transcode_if_needed(abs_path)
    except Exception as e:
        info = last_ffmpeg_error()
        msg = str(e)
        try:
            if isinstance(info, dict) and info.get("src") == abs_path:
                msg = msg + "\n\nLast ffmpeg error:\n" + json.dumps(info, indent=2)
        except Exception:
            pass
        raise RuntimeError(msg)


def _rewrite_hls_manifest_text(text: str, key: str) -> str:
    base = "/hls/file/" + quote(key, safe="") + "/"
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out.append(raw)
            continue
        if line.startswith("#EXT-X-MAP:"):
            line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + base + quote(os.path.basename(m.group(1)), safe="/._-") + '"', line)
            out.append(line)
            continue
        if line.startswith("#"):
            out.append(raw)
            continue
        out.append(base + quote(line, safe="/._-"))
    return "\n".join(out) + "\n"


@app.route("/hls/manifest", methods=["GET"])
def hls_manifest():
    root_id = str(request.args.get("root_id") or "")
    rel = str(request.args.get("rel") or "")
    if not root_id or not rel:
        abort(400)
    try:
        playable = _resolve_stream_source_for_hls(root_id, rel)
        key, manifest_path = _hls_cache_entry_for_path(playable)
        with open(manifest_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        return Response(_rewrite_hls_manifest_text(raw, key), mimetype="application/vnd.apple.mpegurl")
    except RuntimeError:
        return Response("Unable to prepare stream", status=500, mimetype="text/plain")


@app.route("/hls/file/<key>/<path:name>", methods=["GET", "HEAD"])
def hls_file(key: str, name: str):
    key2 = re.sub(r"[^a-fA-F0-9]", "", str(key or ""))[:64]
    if not key2:
        abort(404)
    base = os.path.join(hls_cache_dir(), key2)
    try:
        path = safe_path_join(base, unquote(name))
    except ValueError:
        abort(400)
    if not os.path.exists(path) or not os.path.isfile(path):
        abort(404)
    mime = pick_mime(path)
    if request.method.upper() == "HEAD":
        return Response(status=200, headers={"Content-Length": str(os.path.getsize(path))}, mimetype=mime)
    return range_response(path)


def _proxy_url_allowed(raw_url: str, *, trusted_provider_stream: bool = False) -> bool:
    try:
        parsed = urlparse(str(raw_url or "").strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "local"} or host.endswith(".localhost") or host.endswith(".local"):
        return False
    allowed_suffixes = []
    for raw_suffix in (STREAM_PROXY_ALLOWED_HOST_SUFFIXES or []):
        suffix = str(raw_suffix or "").strip().lower().lstrip(".")
        if suffix:
            allowed_suffixes.append(suffix)
    if not trusted_provider_stream and allowed_suffixes and not any(host == suffix or host.endswith("." + suffix) for suffix in allowed_suffixes):
        return False
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
        except Exception:
            return False
    for addr in addresses:
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
            return False
    return True


def _safe_proxy_headers(upstream_headers: Any) -> List[Tuple[str, str]]:
    allowed = {"accept-ranges", "content-length", "content-range", "content-type", "etag", "last-modified"}
    out_headers: List[Tuple[str, str]] = []
    for k2, v2 in upstream_headers.items():
        if str(k2).lower() in allowed:
            out_headers.append((str(k2), str(v2)))
    return out_headers


@app.route("/stream/<root_id>/<path:relpath>", methods=["GET", "HEAD"])
def stream(root_id: str, relpath: str):
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(unquote(relpath))
        if not it:
            abort(404)
        if str(it.get("source") or "").strip().lower() == 'youtube':
            try:
                local_path = _prepare_youtube_stream_file(str(it.get('youtube_url') or it.get('url') or ''), it)
            except Exception:
                return Response("Unable to fetch stream", status=502, mimetype="text/plain")
            return range_response(local_path)
        upstream_url = str(it.get("url") or "")
        trusted_provider_stream = bool(it.get("trusted_provider_stream"))
        if not _proxy_url_allowed(upstream_url, trusted_provider_stream=trusted_provider_stream):
            abort(400)
        headers = {}
        rng = request.headers.get("Range")
        if rng:
            headers["Range"] = rng
        method = "HEAD" if request.method == "HEAD" else "GET"
        try:
            upstream = requests.request(method, upstream_url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
            if not _proxy_url_allowed(str(upstream.url or ""), trusted_provider_stream=trusted_provider_stream):
                upstream.close()
                abort(400)
        except Exception:
            return Response("Unable to fetch stream", status=502, mimetype="text/plain")
        out_headers = _safe_proxy_headers(upstream.headers)
        if request.method == "HEAD":
            return Response(status=upstream.status_code, headers=out_headers)
        def gen():
            try:
                for chunk in upstream.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        yield chunk
            finally:
                try:
                    upstream.close()
                except Exception:
                    pass
        return Response(gen(), status=upstream.status_code, headers=out_headers)
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)

    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        abort(404)

    try:
        playable = transcode_if_needed(abs_path)
    except Exception as e:
        info = last_ffmpeg_error()
        msg = str(e)
        try:
            if isinstance(info, dict) and info.get("src") == abs_path:
                msg = msg + "\n\nLast ffmpeg error:\n" + json.dumps(info, indent=2)
        except Exception:
            pass
        try:
            print("STREAM ERROR:", msg)
        except Exception:
            pass
        return Response("Unable to prepare stream", status=500, mimetype="text/plain")

    return range_response(playable)


configure_playback_state(
    search_stream_root_id_provider=lambda: SEARCH_STREAM_ROOT_ID,
    search_stream_get_or_restore_provider=lambda rel: _search_stream_get_or_restore(rel),
)


def create_app() -> Flask:
    real_app = Flask(__name__)
    mcp_routes.app.apply_to(real_app)
    app.apply_to(real_app)
    register_auth(real_app)
    real_app.after_request(add_request_timing_headers)
    return real_app
