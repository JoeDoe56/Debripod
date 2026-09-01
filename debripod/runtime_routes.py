from __future__ import annotations

import json
import re
import base64
import zlib
import secrets
import time
import asyncio
import concurrent.futures
import contextlib
import logging
import math
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

from aiohttp import web

from . import runtime_downloads as downloads_module
from . import runtime_route_state as route_state_module
from . import runtime_state as state_module
from .Services import lastfm as lastfm_module
from .Services import soulseek as soulseek_module
from .Services import youtube as youtube_module
from .Services.youtube import ytdlp_comments, ytdlp_inspect
from .Services.ytdlp_runner import run_flat_entries_async
from .Services.ytdlp_search import YtdlpSearchProvider
from .Services.library_search import LibrarySearchProvider
from .Services.local_index_search import LocalIndexSearchProvider
from .Services.local_torrent_index import LocalIndexUpdater, LocalTorrentIndex
from .Services.soulseek_search import SoulseekSearchProvider
from .Services.torrent_search import TorrentSearchProvider
from .Services.torrent_sources import TorrentHit
from .Services.http import HttpClient, create_client_session
from .Services.search.pipeline import SearchPipeline
from .Services.search.providers import SearchContext
from .Services.search.runtime import build_search_runtime
from .Services.link_intake import classify_link_input
from .Services.safe_outbound import UnsafeOutboundUrl, request_public_url, validate_public_http_url, validate_ytdlp_target
from .Library import tvmaze as tvmaze_module
from .Library.tvmaze import normalized_episode_information
from .factory import AppServices, SERVICES_KEY, json_response, session_for, session_middleware
from .auth import _csrf_token, auth_middleware, current_user, is_owner, register_auth_routes
from .Routes.notifications import register_notification_routes
from .config import _coerce_config_value, ensure_startup_security_config, load_default_app_config_overrides, save_config, save_default_app_config_overrides
from .Library.library_db import clear_search_history, load_folder_entries, load_palette, load_palette_for_media, load_search_history, load_visualizer_analysis_for_media, record_search_history_row, save_folder_entries, save_palette
from .Library.index import build_index_for_root, set_index_cache
from .Library.metadata import file_meta_cached
from .Library.video_parse import duration_text, normalize_show_key, show_keys_close
from .Library.library_db import load_show_aliases, save_show_aliases
from .Library.search_ranker import infer_query_intent, normalize_search_text, rank_combined_results, source_priority_for_intent
from .Library.search_cache import SEARCH_CACHE_SCHEMA
from .Library.roots import sync_user_roots
from .Library.index import stop_index_watcher
from .storage.tasks import save_task_metadata
from .storage.palettes import load_video_timeline
from .storage.backups import list_backups
from .storage.database import create_database_backup, restore_database_backup
from .storage.media_likes import get_media_like, list_media_likes, set_media_like
from .Services.debrid import DebridAuthError, DebridProviderError, get_active_provider, get_provider, provider_specs, provider_status as debrid_provider_status
from .Services.debrid.identifiers import normalize_identifier
from .Tasks.manager import task_belongs_to_user
from .user_runtime import USER_RUNTIME_KEY, UserRuntime, UserRuntimeRegistry, user_runtime_for
from .runtime_state import *
from .runtime_downloads import *
from .settings import APP_SETTING_KEYS, DEFAULT_APP_SETTINGS, DEFAULT_UI_SETTINGS, DEVICE_SETTING_KEYS, SECRET_SETTING_KEYS, SERVER_SETTING_KEYS, SETTING_DESCRIPTORS, default_app_settings, executable_status, ensure_app_settings, masked_settings, migrate_owner_server_settings, migrate_user_secrets, pick_system_path, save_app_settings, save_server_settings, settings_fingerprint
from .playback.state import load_playback_runtime

# =========================
# aiohttp runtime state
# =========================
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
_HLS_ACCESS_LOCK = threading.RLock()
_HLS_ACCESS: dict[str, tuple[str, str, str, float]] = {}
_HLS_ACCESS_TTL_SECONDS = 15 * 60
routes = web.RouteTableDef()
_OWNER_ONLY_SETTING_KEYS = SERVER_SETTING_KEYS


from .runtime_route_state import *
from .MCP import routes as mcp_routes


def _default_app_overrides() -> dict[str, Any]:
    return load_default_app_config_overrides()


def _runtime_settings(request: web.Request) -> dict[str, Any]:
    return dict(user_runtime_for(request).settings)


async def _validated_ytdlp_url(request: web.Request, raw_url: str) -> str:
    services = request.app[SERVICES_KEY]
    http = getattr(services, "http", None)
    session = getattr(http, "session", None)
    if session is None:
        raise UnsafeOutboundUrl("Outbound URL validation is unavailable.")
    return await validate_ytdlp_target(
        session, raw_url, timeout=float(_runtime_settings(request).get("REQUEST_TIMEOUT_SECONDS") or 25)
    )


def _settings_scope(request: web.Request) -> str:
    """The immutable user ID used for all request-owned settings."""
    return user_runtime_for(request).settings_scope


def _current_user_id(request: web.Request) -> str:
    return user_runtime_for(request).user_id


def _request_roots(request: web.Request) -> list[tuple[str, str, str, str]]:
    return roots(_current_user_id(request))


def _request_root_by_id(request: web.Request, root_id: str):
    return root_by_id(root_id, _current_user_id(request))


def _sync_user_library_roots(user_id: str, settings: dict[str, Any]) -> None:
    for root_id in sync_user_roots(user_id, settings):
        stop_index_watcher(root_id)


def _user_library_versions(user_id: str) -> dict[str, int]:
    """Expose only physical roots explicitly associated with this user."""
    available = library_root_versions()
    return {
        root_id: int(available.get(root_id) or 0)
        for root_id, _name, _path, _mode in roots(user_id)
    }


def _request_library_versions(request: web.Request) -> dict[str, int]:
    return _user_library_versions(_current_user_id(request))


def _user_index_status(user_id: str) -> tuple[bool, dict[str, bool]]:
    _any_building, all_roots = index_building_status()
    allowed = {root_id for root_id, _name, _path, _mode in roots(user_id)}
    visible = {root_id: bool(value) for root_id, value in all_roots.items() if root_id in allowed}
    return any(visible.values()), visible


def _new_hls_access_token(user_id: str, root_id: str, key: str) -> str:
    """Bind cache-segment access to the authenticated manifest recipient."""
    token = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _HLS_ACCESS_LOCK:
        expired = [candidate for candidate, (_owner, _root, _key, deadline) in _HLS_ACCESS.items() if deadline <= now]
        for candidate in expired:
            _HLS_ACCESS.pop(candidate, None)
        _HLS_ACCESS[token] = (str(user_id), str(root_id), str(key), now + _HLS_ACCESS_TTL_SECONDS)
    return token


def _hls_access_allowed(token: str, user_id: str, key: str) -> bool:
    with _HLS_ACCESS_LOCK:
        entry = _HLS_ACCESS.get(str(token or ""))
        if not entry:
            return False
        owner, root_id, expected_key, deadline = entry
        if deadline <= time.monotonic():
            _HLS_ACCESS.pop(str(token or ""), None)
            return False
    if not secrets.compare_digest(owner, str(user_id or "")) or not secrets.compare_digest(expected_key, str(key or "")):
        return False
    return root_id == SEARCH_STREAM_ROOT_ID or root_by_id(root_id, str(user_id or "")) is not None


def _record_user_search_history(runtime: UserRuntime, query: str, source: str, cache_key: str) -> None:
    item = {"q": str(query or ""), "source": str(source or ""), "cache_key": str(cache_key or ""), "ts": time.time()}
    if not item["q"]:
        return
    history = [row for row in runtime.search_history if str(row.get("q") or "") != item["q"]]
    history.insert(0, item)
    try:
        limit = max(1, int(runtime.settings.get("SEARCH_HISTORY_MAX_ITEMS") or 100))
    except Exception:
        limit = 100
    runtime.search_history[:] = history[:limit]
    record_search_history_row(item["q"], item["source"], item["cache_key"], max_items=limit, user_id=runtime.user_id)


async def _create_soulseek_service(user_id: str, settings: dict[str, Any]) -> Any:
    username = str(settings.get("SOULSEEK_USERNAME") or "").strip()
    password = str(settings.get("SOULSEEK_PASSWORD") or "").strip()
    if not username or not password:
        return None
    try:
        service = SoulseekService(
            user_id=user_id,
            username=username,
            password=password,
            download_dir=str(settings.get("SOULSEEK_DOWNLOAD_DIR") or ""),
            listening_port=int(settings.get("SOULSEEK_LISTENING_PORT") or 0),
            obfuscated_port=int(settings.get("SOULSEEK_OBFUSCATED_PORT") or 0),
            search_timeout_sec=int(settings.get("SOULSEEK_SEARCH_TIMEOUT_SEC") or 30),
            search_max_results=int(settings.get("SOULSEEK_SEARCH_MAX_RESULTS") or 500),
            search_idle_stop_sec=float(settings.get("SOULSEEK_SEARCH_IDLE_STOP_SEC") or 2.5),
            search_hard_max_sec=float(settings.get("SOULSEEK_SEARCH_HARD_MAX_SEC") or 60),
        )
        await service.start()
        return service
    except Exception:
        return None


async def _create_user_runtime(services: AppServices, user: Any) -> UserRuntime:
    user_id = str(getattr(user, "user_id", "") or "").strip()
    username = str(getattr(user, "username", "") or "").strip()
    migrate_user_secrets(username, user_id)
    if str(getattr(user, "role", "") or "") == "owner":
        migrate_owner_server_settings(user_id, _default_app_overrides())
    settings = ensure_app_settings(
        user_id=user_id,
        legacy_username=username,
        defaults_overrides=_default_app_overrides(),
    )
    _sync_user_library_roots(user_id, settings)
    runtime = UserRuntime(
        user_id=user_id,
        username=username,
        role=str(getattr(user, "role", "user") or "user"),
        settings_scope=user_id,
        settings=dict(settings),
        settings_signature=settings_fingerprint(user_id),
        playback=load_playback_runtime(user_id),
        search_history=load_search_history(int(settings.get("SEARCH_HISTORY_MAX_ITEMS") or 100), user_id=user_id),
    )
    runtime.soulseek_service = await _create_soulseek_service(runtime.user_id, runtime.settings)
    runtime.lastfm = lastfm_module.LastfmClient(runtime.user_id, runtime.settings, services.http)
    runtime.search_runtime = _build_unified_search_runtime(
        runtime.settings,
        http_client=services.http,
        local_index=services.local_index,
        local_index_updater=services.local_index_updater,
        soulseek_service=runtime.soulseek_service,
        user_id=runtime.user_id,
    )
    runtime.playback.search_stream_get_or_restore = lambda rel: route_state_module._search_stream_get_or_restore(rel, runtime)
    return runtime


async def _reload_request_runtime(request: web.Request) -> UserRuntime:
    user = current_user(request)
    if user is None:
        raise web.HTTPUnauthorized()
    registry = request.app[SERVICES_KEY].user_runtimes
    if registry is None:
        raise RuntimeError("User runtime registry is unavailable")
    await registry.invalidate_user_runtime(user.user_id)
    runtime = await registry.get_user_runtime(user)
    request[USER_RUNTIME_KEY] = runtime
    return runtime


async def _invalidate_user_runtimes_for_server_settings(request: web.Request) -> None:
    """Force each per-user client to pick up a changed machine setting."""
    services = request.app.get(SERVICES_KEY) if request.app is not None else None
    registry = getattr(services, "user_runtimes", None)
    if registry is not None:
        await registry.close_all()


class _UnifiedSearchDiskCache:
    def __init__(self, user_id: str):
        self.user_id = str(user_id or "")

    def set(self, cache_key: str, payload: dict[str, Any]) -> None:
        stored = {**payload, "schema_version": SEARCH_CACHE_SCHEMA}
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "combined", str(payload.get("query") or ""), {"schema": SEARCH_CACHE_SCHEMA}, stored)


def _build_unified_search_runtime(
    settings: dict[str, Any],
    *,
    http_client: HttpClient | None = None,
    local_index: LocalTorrentIndex | None = None,
    local_index_updater: LocalIndexUpdater | None = None,
    soulseek_service: Any = None,
    user_id: str = "",
):
    current = dict(settings)
    local_index = local_index or LocalTorrentIndex()
    local_index.initialize()
    local_index_provider = LocalIndexSearchProvider(local_index)
    local_index_updater = local_index_updater or (
        LocalIndexUpdater(local_index, http=http_client) if http_client is not None else None
    )
    enabled_sources = list(current.get("TORRENT_SEARCH_ENABLED_SOURCES") or [])
    torrent = (
        TorrentSearchProvider.from_http(
            http_client,
            enabled_sources=enabled_sources,
            max_concurrent=int(current.get("TORRENT_SEARCH_MAX_CONCURRENT") or 7),
        )
        if http_client is not None
        else TorrentSearchProvider(
            [],
            enabled_sources=enabled_sources,
            max_concurrent=int(current.get("TORRENT_SEARCH_MAX_CONCURRENT") or 7),
        )
    )
    library = LibrarySearchProvider(
        lambda: root_objects(user_id),
        get_index,
        lambda: {root_id: library_root_versions().get(root_id, 0) for root_id, _name, _path, _mode in roots(user_id)},
    )
    soulseek = SoulseekSearchProvider(lambda: soulseek_service)
    ytdlp = YtdlpSearchProvider(max_concurrent=int(current.get("YTDLP_SEARCH_MAX_CONCURRENT") or 4))
    providers = [library]
    if current.get("LOCAL_INDEX_ENABLED", True):
        providers.append(local_index_provider)
    providers.extend([soulseek, torrent, ytdlp])
    pipeline = SearchPipeline(providers, cache=_UnifiedSearchDiskCache(user_id))
    return build_search_runtime(
        pipeline=pipeline,
        library_provider=library,
        local_index_provider=local_index_provider,
        soulseek_provider=soulseek,
        torrent_provider=torrent,
        ytdlp_provider=ytdlp,
        local_index=local_index,
        local_index_updater=local_index_updater,
        torrent_adapters={str(adapter.source_id): adapter for adapter in torrent.adapters},
    )


def _active_search_runtime(request: web.Request | None = None):
    if request is None:
        raise RuntimeError("Search runtime requires an authenticated request")
    runtime = user_runtime_for(request).search_runtime
    if runtime is None:
        raise RuntimeError("User search runtime is unavailable")
    return runtime


@web.middleware
async def runtime_middleware(request: web.Request, handler):
    started_at = time.perf_counter()
    user = current_user(request)
    if user is not None:
        registry = request.app[SERVICES_KEY].user_runtimes
        if registry is None:
            raise RuntimeError("User runtime registry is unavailable")
        request[USER_RUNTIME_KEY] = await registry.get_user_runtime(user)
    try:
        response = await handler(request)
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        path = request.path or ""
        if path.startswith("/static/") and request.query.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        if path.startswith("/api/") or path.startswith("/hls/") or path.startswith("/stream/"):
            response.headers["X-DebriPod-Request-Ms"] = f"{elapsed_ms:.1f}"
        if path.startswith("/api/"):
            _RECENT_API_TIMINGS.append({
                "method": request.method,
                "path": path,
                "status": int(response.status),
                "ms": round(elapsed_ms, 1),
                "ts": time.time(),
            })
            del _RECENT_API_TIMINGS[:-60]
        if elapsed_ms >= 750 and path.startswith("/api/"):
            logging.info("slow endpoint %s %.1fms", path, elapsed_ms)
        return response
    except asyncio.CancelledError:
        raise


async def render_shell(request: web.Request, autorefresh: int = 0, **ctx) -> web.Response:
    path = Path(__file__).resolve().parent / "static" / "shell.html"
    text = path.read_text(encoding="utf-8").replace("__DEBRIPOD_ASSET_VERSION__", str(ASSET_VERSION))
    response = web.Response(text=text, content_type="text/html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@routes.get("/api/bootstrap")
async def api_bootstrap(request: web.Request) -> web.Response:
    version_info = dict(VERSION_INFO)
    version_info.update({"version": VERSION, "host": HOST, "port": PORT})
    user = current_user(request)
    return json_response(
        ok=True,
        app_info=version_info,
        ui_defaults=DEFAULT_UI_SETTINGS,
        tasks_poll_ms=TASKS_POLL_MS,
        icon_version=ICON_VERSION,
        asset_version=ASSET_VERSION,
        csrf_token=_csrf_token(request),
        device_settings_user_id=str(getattr(user, "user_id", "") or ""),
    )


def _pwa_shell_assets() -> list[str]:
    base = [
        "/",
        f"/site.webmanifest?v={ICON_VERSION}",
        f"/favicon.ico?v={ICON_VERSION}",
        f"/apple-touch-icon.png?v={ICON_VERSION}",
        f"/icon-192.png?v={ICON_VERSION}",
        f"/icon-512.png?v={ICON_VERSION}",
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


@routes.get("/debripod-sw.js")
async def debripod_service_worker(request: web.Request):
    path = Path(__file__).resolve().parent / "static" / "debripod-sw.js"
    text = path.read_text(encoding="utf-8")
    text = text.replace("__DEBRIPOD_ASSET_VERSION__", str(ASSET_VERSION))
    text = text.replace("__DEBRIPOD_ICON_VERSION__", str(ICON_VERSION))
    text = text.replace("__DEBRIPOD_SHELL_ASSETS__", json.dumps(_pwa_shell_assets(), ensure_ascii=False))
    resp = web.Response(text=text, content_type="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp













@routes.get("/api/libsearch/combined")
async def api_libsearch_combined(request: web.Request):
    q = (request.query.get("q") or "").strip()
    if not q:
        return json_response(ok=False, error="Missing query", results=[], result_count=0, cache_key="", status=400)
    user_runtime = user_runtime_for(request)
    settings = dict(user_runtime.settings)
    runtime = _active_search_runtime(request)
    debug = str(request.query.get("debug") or "").strip().lower() in {"1", "true", "yes"}
    local_diagnostics = await asyncio.to_thread(runtime.local_index.diagnostics)
    local_meta = local_diagnostics.get("meta") if isinstance(local_diagnostics, dict) else {}
    cache_inputs = {
        "schema": SEARCH_CACHE_SCHEMA,
        "user_id": user_runtime.user_id,
        "roots": _request_library_versions(request),
        "local_index_enabled": bool(settings.get("LOCAL_INDEX_ENABLED", True)),
        "local_index_generation": str((local_meta or {}).get("local_index_generation") or "0"),
        "torrent_sources": sorted(str(value).strip().lower() for value in (settings.get("TORRENT_SEARCH_ENABLED_SOURCES") or []) if str(value).strip()),
        "soulseek_enabled": bool(settings.get("SOULSEEK_USERNAME") and settings.get("SOULSEEK_PASSWORD")),
        "soulseek_max_results": int(settings.get("SOULSEEK_SEARCH_MAX_RESULTS") or 0),
        "youtube_search_limit": int(settings.get("YOUTUBE_SEARCH_LIMIT") or 0),
    }
    combined_cache_key = _make_search_cache_key("combined", normalize_search_text(q), cache_inputs)
    cached_entry = None
    if not debug:
        with _SEARCH_DISK_LOCK:
            cached_entry = _disk_cache_get(combined_cache_key)
    cached_payload = dict((cached_entry or {}).get("payload") or {}) if cached_entry else {}
    if cached_payload.get("schema_version") != SEARCH_CACHE_SCHEMA or not isinstance(cached_payload.get("results"), list):
        cached_payload = {}
    intent = infer_query_intent(q)
    context = SearchContext(
        username=user_runtime.user_id,
        query=q,
        normalized_query=normalize_search_text(q),
        intent=intent,
        settings=settings,
        search_id=combined_cache_key,
        debug=debug,
    )
    if str(request.query.get("stream") or "").strip().lower() in {"1", "true", "yes"}:
        response = web.StreamResponse(
            status=200,
            headers={"Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-store"},
        )
        await response.prepare(request)
        try:
            if cached_payload:
                events = [
                    {"event": "start", "search_id": combined_cache_key, "query": q, "cached": True},
                    {"event": "done", "ok": True, "search_id": combined_cache_key, "cache_key": combined_cache_key, "query": q, "cached": True, "results": cached_payload.get("results", []), "result_count": len(cached_payload.get("results", [])), "provider_status": cached_payload.get("provider_status", [])},
                ]
                for event in events:
                    await response.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            else:
                async for event in runtime.pipeline.search_stream(q, context):
                    await response.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            _record_user_search_history(user_runtime, q, "combined", combined_cache_key)
            await response.write_eof()
        except ConnectionResetError:
            pass
        except asyncio.CancelledError:
            raise
        return response
    if cached_payload:
        _record_user_search_history(user_runtime, q, "combined", combined_cache_key)
        return json_response(ok=True, q=q, cache_key=combined_cache_key, cached=True, results=cached_payload.get("results", []), result_count=len(cached_payload.get("results", [])), provider_status=cached_payload.get("provider_status", []), schema_version=SEARCH_CACHE_SCHEMA)
    final = await runtime.pipeline.search_once(q, context)
    _record_user_search_history(user_runtime, q, "combined", combined_cache_key)
    return json_response(ok=True, q=q, cache_key=combined_cache_key, cached=False, results=final.get("results", []), result_count=len(final.get("results", [])), provider_status=final.get("provider_status", []), schema_version=SEARCH_CACHE_SCHEMA)











async def api_libsearch_soulseek_start(request: web.Request):
    q = (request.query.get("q") or "").strip()
    if not q:
        return json_response(ok=False, error="Missing query", sid="", done=True, slsk_users=[], file_count=0, dir_count=0, cache_key="")

    runtime = user_runtime_for(request)
    extra: Dict[str, Any] = {"user_id": runtime.user_id}
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
        return json_response(ok=True, q=q, cache_key=cache_key, sid="", rev=1, done=True, slsk_users=slsk_users, file_count=file_count, dir_count=dir_count, error="", changed=True)

    svc = user_runtime_for(request).soulseek_service
    if not svc or not svc.is_ready():
        return json_response(ok=False, error="Soulseek service is not ready", sid="", done=True, slsk_users=[], file_count=0, dir_count=0, cache_key=cache_key)

    sid = svc.create_search_session(cache_key, q)

    try:
        _record_user_search_history(runtime, q, "soulseek", cache_key)
    except Exception:
        pass

    try:
        svc.start_search_session(sid, q)
    except Exception:
        svc.mark_search_session_done(sid, error="Soulseek search failed")
        return json_response(ok=False, error="Soulseek search failed", sid=sid, done=True, slsk_users=[], file_count=0, dir_count=0, cache_key=cache_key)

    return json_response(ok=True, q=q, cache_key=cache_key, sid=sid, rev=0, done=False, slsk_users=[], file_count=0, dir_count=0, error="", changed=True)

async def api_libsearch_soulseek_poll(request: web.Request):
    sid = (request.query.get("sid") or "").strip()
    if not sid:
        return json_response(ok=False, error="Missing sid", done=True)

    try:
        want_rev = int(request.query.get("rev") or 0)
    except Exception:
        want_rev = 0

    svc = user_runtime_for(request).soulseek_service
    if not svc:
        return json_response(ok=False, error="Soulseek service is not ready", done=True)
    snap = svc.search_session_snapshot(sid)
    if not snap:
        return json_response(ok=False, error="Unknown sid", done=True)

    svc.touch_search_session(sid)

    rev = int(snap.get("rev") or 0)
    done = bool(snap.get("done"))
    err = str(snap.get("error") or "")
    file_count = int(snap.get("file_count") or 0)
    dir_count = int(snap.get("dir_count") or 0)

    changed = (rev != want_rev) or done

    slsk_users = []
    if changed:
        slsk_users = _slsk_group_snapshot_to_users(snap, user_runtime_for(request).user_id)

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

    return json_response(
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

async def api_libsearch_soulseek(request: web.Request):
    q = (request.query.get("q") or "").strip()
    if not q:
        return json_response(ok=False, error="Missing query", slsk_users=[], result_count=0, cache_key="")

    runtime = user_runtime_for(request)
    extra: Dict[str, Any] = {"user_id": runtime.user_id}
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
        svc = user_runtime_for(request).soulseek_service
        if not svc or not svc.is_ready():
            return json_response(ok=False, error="Soulseek service is not ready", slsk_users=[], result_count=0, cache_key=cache_key)

        try:
            items = await svc.search_async(q)
        except Exception:
            return json_response(ok=False, error="Soulseek search failed", slsk_users=[], result_count=0, cache_key=cache_key)

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
        _record_user_search_history(runtime, q, "soulseek", cache_key)
    except Exception:
        pass

    return json_response(ok=True, q=q, cache_key=cache_key, slsk_users=slsk_users, result_count=slsk_total_results)

@routes.get("/api/soulseek/browse_user")
async def api_soulseek_browse_user(request: web.Request):
    runtime = user_runtime_for(request)
    user = (request.query.get("user") or "").strip()
    selected_dir = _slsk_norm_remote_path(request.query.get("selected_dir") or "")
    if not user:
        return json_response(ok=False, error="Missing user", user="", dirs=[], selected_dir="", status=400)
    svc = runtime.soulseek_service
    if not svc or not svc.is_ready():
        return json_response(ok=False, error="Soulseek service is not ready", user=user, dirs=[], selected_dir=selected_dir)

    try:
        items = await svc.browse_user_async(user)
    except Exception:
        return json_response(ok=False, error="Soulseek browse failed", user=user, dirs=[], selected_dir=selected_dir)

    dirs = _slsk_group_items_to_dirs(user, items, runtime.user_id)
    dir_paths = {str(d.get("directory") or "") for d in dirs}
    if selected_dir and selected_dir not in dir_paths:
        selected_dir = ""

    return json_response(ok=True, user=user, dirs=dirs, selected_dir=selected_dir, file_count=sum(int(d.get("total_files") or 0) for d in dirs), dir_count=len(dirs))




@routes.get("/api/ytdlp/files")
@routes.get("/api/youtube/files")
async def api_ytdlp_files(request: web.Request):
    url = (request.query.get('url') or '').strip()
    if not url:
        return json_response(ok=False, error='Missing URL', files=[], file_count=0, size=0, status=400)
    try:
        safe_url = await _validated_ytdlp_url(request, url)
        files = await asyncio.to_thread(ytdlp_list_formats, safe_url)
        for file in files:
            if isinstance(file, dict):
                file["source_url"] = safe_url
        total_size = sum(int(f.get('size') or 0) for f in files)
        return json_response(ok=True, files=files, file_count=len(files), size=total_size)
    except UnsafeOutboundUrl as exc:
        return json_response(ok=False, error=str(exc), files=[], file_count=0, size=0, status=400)
    except Exception:
        return json_response(ok=False, error="Failed to list formats", files=[], file_count=0, size=0, status=500)
@routes.get("/api/ytdlp/directory")
async def api_ytdlp_directory(request: web.Request):
    url = (request.query.get("url") or "").strip()
    if not url:
        return json_response(ok=False, error="Missing URL", entries=[], result_count=0, status=400)
    try:
        entries = await run_flat_entries_async(await _validated_ytdlp_url(request, url))
        return json_response(ok=True, entries=entries, result_count=len(entries))
    except UnsafeOutboundUrl as exc:
        return json_response(ok=False, error=str(exc), entries=[], result_count=0, status=400)
    except Exception as exc:
        return json_response(ok=False, error=str(exc) or "Failed to load directory", entries=[], result_count=0, status=400)


@routes.get("/api/local-index/status")
async def api_local_index_status(request: web.Request):
    runtime = _active_search_runtime(request)
    diagnostics = await asyncio.to_thread(runtime.local_index.diagnostics)
    updater_state = dict(request.app[SERVICES_KEY].local_index_state or {})
    return json_response(ok=True, **diagnostics, updater=updater_state)


@routes.post("/api/torrent-search/resolve")
async def api_torrent_search_resolve(request: web.Request):
    data = await request.json()
    source_id = str(data.get("source_id") or "").strip().lower()
    runtime = _active_search_runtime(request)
    adapter = runtime.torrent_adapters.get(source_id)
    if adapter is None:
        return json_response(ok=False, error="Unknown torrent source", status=404)
    resolver = getattr(adapter, "resolve", None)
    if not callable(resolver):
        return json_response(ok=False, error="This source does not require detail resolution", status=400)
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    if source_id == "torapi" and str(extra.get("torapi_provider") or "").casefold() not in {"rutracker", "kinozal", "rutor", "nonameclub"}:
        return json_response(ok=False, error="Unknown TorAPI provider", status=400)
    hit = TorrentHit(
        source_id=source_id,
        source_label=str(getattr(adapter, "source_label", source_id)),
        title=str(data.get("title") or "Torrent"),
        infohash=str(data.get("infohash") or ""),
        magnet=str(data.get("magnet") or ""),
        torrent_url=str(data.get("torrent_url") or ""),
        source_record_id=str(data.get("source_record_id") or ""),
        extra=dict(extra),
    )
    try:
        resolved = await resolver(hit)
    except Exception as exc:
        return json_response(ok=False, error=str(exc) or "Failed to resolve torrent source", status=400)
    return json_response(
        ok=True,
        magnet=str(resolved.magnet or ""),
        infohash=str(resolved.infohash or ""),
        torrent_url=str(resolved.torrent_url or ""),
    )
@routes.post("/api/link/inspect")
async def api_link_inspect(request: web.Request):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    value = str(data.get("value") or "").strip()
    kind = classify_link_input(value)
    if kind == "query":
        return json_response(ok=False, error="Enter a valid magnet or HTTP(S) link.", status=400)
    try:
        if kind == "magnet":
            current = _runtime_settings(request)
            status = debrid_provider_status(current)
            if not status.get("configured"):
                return json_response(ok=False, error="No debrid provider is configured.", status=400)
            provider = get_active_provider(current, int(current.get("REQUEST_TIMEOUT_SECONDS") or 25), request.app[SERVICES_KEY].http)
            preview = await provider.preview_magnet(value)
            files = []
            for item in preview.files:
                name = str(item.path or "")
                files.append({
                    "name": name, "title": name, "path": name,
                    "id": item.file_id, "file_id": item.file_id,
                    "size": int(item.bytes or 0), "bytes": int(item.bytes or 0),
                    "source": "torrent", "selectable": True,
                })
            title = str(data.get("title") or "Magnet link")
            result = {
                "result_id": "torrent-url:" + sha1_text(value), "provider_group": "torrents",
                "source": "torrent", "source_label": "Torrent", "kind": "torrent", "kind_label": "Torrent",
                "title": title, "subtitle": "Magnet link", "artist": "", "album": "", "year": "", "duration": 0,
                "thumbnail": "", "canonical_url": value, "stable_source_id": "", "search_blob": title,
                "filter_values": {"sources": ["Torrent"], "types": ["Torrent"], "indexers": [], "media": []},
                "match_confidence": 1.0, "rank_score": 0.0, "browse_available": False, "stream_available": True,
                "download_available": True, "files_loaded": True, "files": files, "file_count": len(files),
                "size": sum(int(row.get("size") or 0) for row in files),
                "provider_data": {"infohash": "", "magnet": value, "indexer_ids": [], "indexer_labels": [], "source_urls": [], "seeders": 0, "leechers": 0, "verified": False, "category": "", "provider": provider.id, "debrid_task_id": preview.provider_task_id},
            }
            return json_response(ok=True, detail_kind="debrid_files", result=result)
        result = await asyncio.to_thread(ytdlp_inspect, await _validated_ytdlp_url(request, value))
        return json_response(ok=True, detail_kind="ytdlp_formats", result=result)
    except UnsafeOutboundUrl as exc:
        return json_response(ok=False, error=str(exc), status=400)
    except DebridProviderError as exc:
        return json_response(ok=False, error=str(exc) or "Failed to inspect link", status=400)
    except Exception as exc:
        app.logger.warning("Link inspection failed: %s", exc)
        return json_response(ok=False, error="This link could not be inspected by yt-dlp.", status=400)
@routes.get("/api/youtube/comments")
async def api_youtube_comments(request: web.Request):
    url = (request.query.get("url") or "").strip()
    if not url:
        return json_response(ok=False, error="Missing URL", comments=[], status=400)
    try:
        comments = await asyncio.to_thread(ytdlp_comments, await _validated_ytdlp_url(request, url), limit=100)
        return json_response(ok=True, comments=comments)
    except UnsafeOutboundUrl as exc:
        return json_response(ok=False, error=str(exc), comments=[], status=400)
    except Exception:
        return json_response(ok=False, error="Failed to load comments", comments=[], status=500)


def _ytdlp_enqueue_source_url(value: Any) -> str:
    """Pick the inspected page URL from either new or legacy UI payloads."""
    if not isinstance(value, dict):
        return ""
    for key in ("source_url", "original_url", "canonical_url", "youtube_url", "url"):
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


@routes.post("/api/youtube/enqueue")
async def api_youtube_enqueue(request: web.Request):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    source_label = str(data.get('source_label') or 'YouTube').strip() or 'YouTube'
    task_source = 'youtube'
    title = str(data.get('title') or '').strip() or source_label
    selected = data.get('selected') or []
    if not isinstance(selected, list):
        selected = []
    url = _ytdlp_enqueue_source_url(data)
    if not url:
        for item in selected:
            url = _ytdlp_enqueue_source_url(item)
            if url:
                break
    if not url:
        return json_response(ok=False, error='No URL found for the selected format', status=400)
    try:
        url = await _validated_ytdlp_url(request, url)
    except UnsafeOutboundUrl as exc:
        return json_response(ok=False, error=str(exc), status=400)
    youtube_root = str(_runtime_settings(request).get("YOUTUBE_DOWNLOAD_DIR") or "").strip()
    if not youtube_root:
        return json_response(ok=False, error='Pick the YouTube folder in Downloads settings before downloading.', status=400)
    entries: List[Dict[str, Any]] = []
    safe_source_urls = {url: url}
    for i, it in enumerate(selected):
        if not isinstance(it, dict):
            continue
        name = str(it.get('name') or it.get('title') or f'Format {i+1}')
        ext = str(it.get('ext') or 'mp4').lower()
        file_id = str(it.get('file_id') or it.get('itag') or sha1_text(name + '|' + ext)[:12])
        item_source_url = _ytdlp_enqueue_source_url(it) or url
        if item_source_url not in safe_source_urls:
            try:
                safe_source_urls[item_source_url] = await _validated_ytdlp_url(request, item_source_url)
            except UnsafeOutboundUrl as exc:
                return json_response(ok=False, error=str(exc), status=400)
        item_source_url = safe_source_urls[item_source_url]
        entries.append({
            'file_id': file_id,
            'itag': str(it.get('itag') or it.get('format_id') or it.get('file_id') or ''),
            'format_id': str(it.get('format_id') or it.get('itag') or it.get('file_id') or ''),
            'name': name,
            'title': name,
            'ext': ext,
            'media': str(it.get('media') or '').strip().lower(),
            'direct_url': str(it.get('direct_url') or '').strip(),
            'source_url': item_source_url,
            'url': item_source_url,
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
        return json_response(ok=False, error='No files selected', status=400)
    task_id = uuid.uuid4().hex
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = sanitize_folder_name(title)
    folder = sanitize_folder_name(f"{stamp}_{base}_{task_id[:6]}")
    task_dir = os.path.join(youtube_root, folder)
    os.makedirs(task_dir, exist_ok=True)
    t = Task(id=task_id, title=title, magnet=url, task_dir=task_dir, owner_user_id=_current_user_id(request), source=task_source, source_url=url, origin_client_id=str(request.headers.get("X-DebriPod-Client-Id") or ""), state='queued', message='Queued', youtube_files=entries)
    with TASKS_LOCK:
        TASKS[task_id] = t
    save_task_metadata(t, original_result_title=title, remote_files=entries, selected_file_ids=[item.get('file_id') for item in entries], version=str(VERSION))
    th = threading.Thread(target=youtube_worker, args=(task_id,), daemon=True)
    th.start()
    return json_response(ok=True, task_id=task_id)


@routes.get("/api/search_history")
async def api_search_history(request: web.Request):
    try:
        return json_response({"ok": True, "items": list(user_runtime_for(request).search_history)})
    except Exception:
        return json_response({"ok": False, "error": "Failed to browse channel", "items": []})


@routes.post("/api/search_history/clear")
async def api_search_history_clear(request: web.Request):
    try:
        runtime = user_runtime_for(request)
        runtime.search_history.clear()
        clear_search_history(user_id=runtime.user_id)
        return json_response({"ok": True})
    except Exception:
        return json_response({"ok": False, "error": "Failed to clear search history"})


@routes.post("/api/libsearch/stream_selected")
async def api_libsearch_stream_selected(request: web.Request):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    try:
        if str(data.get("source") or "").strip().lower() == "youtube":
            for candidate in [data, *[item for item in (data.get("selected") or []) if isinstance(item, dict)]]:
                raw_url = _ytdlp_enqueue_source_url(candidate)
                if not raw_url:
                    continue
                safe_url = await _validated_ytdlp_url(request, raw_url)
                for key in ("source_url", "original_url", "canonical_url", "youtube_url", "url"):
                    if candidate.get(key):
                        candidate[key] = safe_url
        out = await _engine_prepare_stream_session(data, request.app[SERVICES_KEY].http, user_runtime_for(request))
        return json_response({"ok": True, **out})
    except UnsafeOutboundUrl as exc:
        return json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception:
        return json_response({"ok": False, "error": "Failed to prepare stream"}, status=400)
@routes.get("/api/debrid/providers")
async def api_debrid_providers(request: web.Request):
    settings = _runtime_settings(request)
    return json_response({"ok": True, **debrid_provider_status(settings)})


@routes.post("/api/debrid/connect_token")
async def api_debrid_connect_token(request: web.Request):
    data = await request.json() or {}
    token = str(data.get("token") or "").strip()
    if not token:
        return json_response({"ok": False, "error": "Paste a debrid token first."}, status=400)
    settings = _runtime_settings(request)
    timeout_seconds = int(settings.get("REQUEST_TIMEOUT_SECONDS") or 25)
    matched_id = ""
    matched_label = ""
    failures: dict[str, str] = {}
    for provider_id, spec in provider_specs().items():
        candidate = dict(settings)
        candidate[spec.token_setting_key] = token
        try:
            await get_provider(provider_id, candidate, timeout_seconds, request.app[SERVICES_KEY].http).validate_token()
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
        return json_response({"ok": False, "error": "That token could not be verified with Real Debrid, AllDebrid, Premiumize, or TorBox." + suffix}, status=400)
    updates = {spec.token_setting_key: "" for spec in provider_specs().values()}
    updates[provider_specs()[matched_id].token_setting_key] = token
    updates["DEBRID_PROVIDER"] = matched_id
    saved = save_app_settings(updates, user_id=_settings_scope(request), defaults_overrides=_default_app_overrides())
    if _settings_scope(request):
        saved = (await _reload_request_runtime(request)).settings
    return json_response({"ok": True, "provider": matched_id, "label": matched_label, **debrid_provider_status(saved)})


@routes.post("/api/debrid/preview_files")
@routes.post("/api/debrid/load_files")
async def api_debrid_preview_files(request: web.Request):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    magnet = str(data.get("magnet") or "").strip()
    if not magnet.startswith("magnet:?"):
        return json_response({"ok": False, "error": "Invalid magnet"}, status=400)
    try:
        settings = _runtime_settings(request)
        status = debrid_provider_status(settings)
        if not status.get("configured"):
            return json_response({"ok": False, "error": "No debrid provider is configured."}, status=400)
        provider = get_active_provider(settings, int(settings.get("REQUEST_TIMEOUT_SECONDS") or 25), request.app[SERVICES_KEY].http)
        preview = await provider.preview_magnet(magnet)
        files = [{"id": item.file_id, "file_id": item.file_id, "path": item.path, "bytes": item.bytes} for item in preview.files]
        return json_response({
            "ok": True,
            "provider": provider.id,
            "provider_label": provider.label,
            "debrid_task_id": preview.provider_task_id,
            "files": files,
        })
    except DebridProviderError as exc:
        return json_response({"ok": False, "error": str(exc) or "Failed to preview files"}, status=400)
    except Exception:
        return json_response({"ok": False, "error": "Failed to preview files"}, status=500)
@routes.post("/api/debrid/enqueue_selected")
async def api_debrid_enqueue_selected(request: web.Request):
    try:
        data = await request.json() or {}
    except Exception:
        data = {}
    title = str(data.get("title") or "").strip() or "Torrent"
    magnet = str(data.get("magnet") or "").strip()
    provider_task_id = normalize_identifier(data.get("debrid_task_id")) or ""
    file_ids = data.get("file_ids") or []

    if not provider_task_id:
        return json_response({"ok": False, "error": "Missing debrid task id"}, status=400)
    download_root = str(_runtime_settings(request).get("DOWNLOAD_DIR") or "").strip()
    if not download_root:
        return json_response({"ok": False, "error": "Pick the Debrid folder in Downloads settings before downloading."}, status=400)
    clean_ids: List[str] = []
    if isinstance(file_ids, list):
        for x in file_ids:
            try:
                clean_ids.append(str(x))
            except Exception:
                continue

    if not clean_ids:
        return json_response({"ok": False, "error": "No files selected"}, status=400)
    settings = _runtime_settings(request)
    status = debrid_provider_status(settings)
    provider_id = str(status.get("active_provider") or "")
    if not provider_id:
        return json_response({"ok": False, "error": "No debrid provider is configured."}, status=400)
    requested_provider = str(data.get("provider") or "").strip().lower()
    if requested_provider and requested_provider != provider_id:
        return json_response({"ok": False, "error": "The preview provider is no longer active. Preview the result again."}, status=409)
    task_id = uuid.uuid4().hex
    task_dir = os.path.join(download_root, sanitize_folder_name(f"{task_id[:8]}_{title}"))
    os.makedirs(task_dir, exist_ok=True)

    t = Task(
        id=task_id,
        title=title,
        magnet=magnet,
        task_dir=task_dir,
        owner_user_id=_current_user_id(request),
        origin_client_id=str(request.headers.get("X-DebriPod-Client-Id") or ""),
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
    asyncio.create_task(worker(task_id), name=f"debrid-download:{task_id}")

    return json_response({"ok": True, "task_id": task_id})


@routes.post("/api/soulseek/enqueue")
async def api_soulseek_enqueue(request: web.Request):
    runtime = user_runtime_for(request)
    soulseek_download_dir = str(runtime.settings.get("SOULSEEK_DOWNLOAD_DIR") or "").strip()
    if not soulseek_download_dir:
        return json_response({"ok": False, "error": "Pick the Soulseek folder in Downloads settings before downloading."}, status=400)
    svc = runtime.soulseek_service
    if not svc or not svc.is_ready():
        return json_response({"ok": False, "error": "Soulseek is configured but not connected. Check username, password, and listening port in Services."}, status=400)
    try:
        data = await request.json() or {}
    except Exception:
        data = {}

    user = (data.get("user") or "").strip()
    directory = (data.get("directory") or "").strip()
    files_in = data.get("files") or []
    title = (data.get("title") or "").strip()

    task_download_dir = svc.task_download_dir(directory)
    try:
        os.makedirs(task_download_dir, exist_ok=True)
    except Exception:
        task_download_dir = soulseek_download_dir

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
        incoming_path = svc.expected_incoming_path(rp)
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
        return json_response({"ok": False, "error": "Missing user or selected files"}, status=400)
    if not title:
        base = directory.split("\\")[-1] if directory else ""
        title = f"Soulseek: {user} {base}".strip()

    task_id = uuid.uuid4().hex
    t = Task(
        id=task_id,
        title=title,
        magnet="",
        task_dir=task_download_dir,
        owner_user_id=_current_user_id(request),
        origin_client_id=str(request.headers.get("X-DebriPod-Client-Id") or ""),
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
        await svc.enqueue_downloads_async(task_id, user, remote_paths)
    except Exception:
        set_task(task_id, state="error", message="Failed to queue Soulseek download")
        return json_response({"ok": False, "error": "Failed to queue Soulseek download"}, status=500)
    return json_response({"ok": True, "task_id": task_id})




@routes.post("/cancel")
async def cancel(request: web.Request):
    form = await request.post()
    task_id = str(form.get("task_id") or "").strip()
    if not task_id:
        raise web.HTTPBadRequest()
    if not task_belongs_to_user(task_id, _current_user_id(request)):
        raise web.HTTPNotFound()
    cancel_task(task_id)
    raise web.HTTPSeeOther(location="/")




# =========================
# Library API
# =========================

@routes.get("/api/library/config")
async def api_library_config(request: web.Request):
    lastfm = user_runtime_for(request).lastfm
    rts = []
    versions = _request_library_versions(request)
    source_by_id = {str(item.get("id") or ""): str(item.get("source") or "library") for item in root_objects(_current_user_id(request))}
    for rid, name, ap, mode in _request_roots(request):
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
    return json_response(
        {
            "roots": rts,
            "aggregate_root": {"id": LIBRARY_ALL_ROOT_ID, "name": "Library", "mode": "metadata"},
            "preload_enabled": bool(PRELOAD_NEXT_FOR_GAPLESS),
            "preload_bytes": int(PRELOAD_NEXT_CHUNK_BYTES),
            "lastfm_enabled": bool(lastfm and lastfm.enabled()),
            "wheel_rotation_max_degrees": float(WHEEL_ROTATION_MAX_DEGREES),
            "playback_streaming_mode": str(PLAYBACK_STREAMING_MODE or "http").strip().lower() or "http",
            "library_versions": versions,
        }
    )


@routes.post("/api/library/reindex")
async def api_library_reindex(request: web.Request):
    def snapshot() -> dict[str, Any]:
        with _FULL_REINDEX_LOCK:
            return dict(_FULL_REINDEX_STATUS)

    with _FULL_REINDEX_LOCK:
        if _FULL_REINDEX_STATUS.get("running"):
            return json_response({"ok": True, "status": dict(_FULL_REINDEX_STATUS)})
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
            root_rows = [(rid, name, os.path.abspath(path), mode) for rid, name, path, mode in _request_roots(request)]
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
    return json_response({"ok": True, "status": snapshot()})


@routes.get("/api/library/reindex/status")
async def api_library_reindex_status(request: web.Request):
    with _FULL_REINDEX_LOCK:
        return json_response({"ok": True, "status": dict(_FULL_REINDEX_STATUS)})


@routes.get("/api/settings")
async def api_settings_get(request: web.Request):
    cfg = ensure_startup_security_config()
    runtime = user_runtime_for(request)
    server_controls_owner = is_owner(current_user(request))
    username = runtime.username
    settings = dict(runtime.settings)
    visible_settings = {
        key: value for key, value in settings.items()
        if server_controls_owner or key not in SERVER_SETTING_KEYS
    }
    soulseek_service = runtime.soulseek_service
    soulseek_status = soulseek_service.startup_status() if soulseek_service and hasattr(soulseek_service, "startup_status") else {}
    connections = {
        "current_user": username,
        "DEBRID": debrid_provider_status(settings),
        "DEBRID_PROVIDER": {"value": debrid_provider_status(settings)["active_provider"], "set": bool(debrid_provider_status(settings)["active_provider"])},
        "REAL_DEBRID_API_KEY": {"set": bool(str(settings.get("REAL_DEBRID_API_KEY") or "").strip())},
        "ALLDEBRID_API_KEY": {"set": bool(str(settings.get("ALLDEBRID_API_KEY") or "").strip())},
        "PREMIUMIZE_API_KEY": {"set": bool(str(settings.get("PREMIUMIZE_API_KEY") or "").strip())},
        "TORBOX_API_KEY": {"set": bool(str(settings.get("TORBOX_API_KEY") or "").strip())},
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
        "LASTFM_SESSION": {"set": bool(runtime.lastfm and runtime.lastfm.session_key), "username": str(getattr(runtime.lastfm, "session_username", "") or "")},
    }
    return json_response({
        "ok": True,
        "startup": {
            "PORT": int(PORT) if server_controls_owner else None,
            "ENABLE_MCP": bool(cfg.get("ENABLE_MCP")) if server_controls_owner else None,
            "MCP_TOKEN_SET": bool(str(cfg.get("MCP_TOKEN") or "").strip()) if server_controls_owner else None,
        },
        "server_controls_owner": server_controls_owner,
        "settings": masked_settings(visible_settings),
        "setting_scopes": SETTING_DESCRIPTORS,
        "device_settings_user_id": runtime.user_id,
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
            if k in {"library", "debrid", "soulseek", "lastfm", "youtube", "ffmpeg", "ffprobe", "ytdlp", "downloads"}:
                out[k] = "skipped" if str(value or "").strip().lower() == "skipped" else str(value or "").strip().lower()
    return out


def _kick_library_indexes_from_settings(user_id: str, settings: dict[str, Any]) -> None:
    _sync_user_library_roots(user_id, settings)
    for root in root_objects(user_id):
        try:
            path = str(root.get("path") or "").strip()
            mode = "metadata"
            if path and os.path.isabs(path):
                rid = str(root.get("id") or sha1_text(os.path.abspath(path)))
                ensure_index_async(rid, os.path.abspath(path), mode=mode)
                library_watch_root(rid, os.path.abspath(path), mode=mode)
        except Exception:
            pass


def _service_status_payload(settings: dict[str, Any], soulseek_service: Any = None, lastfm_client: Any = None) -> dict[str, Any]:
    tools = {
        "ffmpeg": executable_status(str(settings.get("FFMPEG_PATH") or "ffmpeg")),
        "ffprobe": executable_status(str(settings.get("FFPROBE_PATH") or "ffprobe")),
        "yt_dlp": executable_status(str(settings.get("YTDLP_CMD") or "yt-dlp")),
    }
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
            "session_user": str(getattr(lastfm_client, "session_username", settings.get("LASTFM_USERNAME") or "") or ""),
            "status": skipped.get("lastfm") or ("logged_in" if str(getattr(lastfm_client, "session_username", settings.get("LASTFM_USERNAME") or "") or "") else ("configured" if str(settings.get("LASTFM_API_KEY") or "").strip() and str(settings.get("LASTFM_API_SECRET") or "").strip() else "not_configured")),
        },
        "torrent_search": {
            "enabled_sources": list(settings.get("TORRENT_SEARCH_ENABLED_SOURCES") or []),
            "local_index_enabled": bool(settings.get("LOCAL_INDEX_ENABLED", True)),
            "status": "configured" if settings.get("TORRENT_SEARCH_ENABLED_SOURCES") or settings.get("LOCAL_INDEX_ENABLED", True) else "disabled",
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


def _setup_status_for_user(username: str, settings: dict[str, Any], lastfm_client: Any = None) -> dict[str, Any]:
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
    services = _service_status_payload(settings, lastfm_client=lastfm_client)
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
        "lastfm_session_configured": bool(getattr(lastfm_client, "session_key", settings.get("LASTFM_SESSION_KEY") or "")),
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


@routes.get("/api/setup/status")
async def api_setup_status(request: web.Request):
    runtime = user_runtime_for(request)
    username = runtime.username
    settings = dict(runtime.settings)
    return json_response(_setup_status_for_user(username, settings, runtime.lastfm))


@routes.post("/api/setup/skip")
async def api_setup_skip(request: web.Request):
    data = await request.json() or {}
    service = str(data.get("service") or "").strip().lower()
    allowed = {"library", "debrid", "soulseek", "lastfm", "youtube", "ffmpeg", "ffprobe", "ytdlp", "downloads"}
    if service not in allowed:
        return json_response({"ok": False, "error": "Unknown setup step"}, status=400)
    user_id = _settings_scope(request)
    settings = _runtime_settings(request)
    skipped = _setup_skipped_services(settings)
    skipped[service] = "skipped"
    saved = save_app_settings({"SETUP_SKIPPED_SERVICES": skipped}, user_id=user_id, defaults_overrides=_default_app_overrides())
    if user_id:
        saved = (await _reload_request_runtime(request)).settings
    runtime = user_runtime_for(request)
    return json_response(_setup_status_for_user(runtime.username, saved, runtime.lastfm))


@routes.post("/api/setup/finish")
async def api_setup_finish(request: web.Request):
    user_id = _settings_scope(request)
    settings = _runtime_settings(request)
    status = _setup_status_for_user(user_runtime_for(request).username, settings, user_runtime_for(request).lastfm)
    if not status.get("required_complete"):
        return json_response({"ok": False, "error": "Add a library folder before finishing setup."}, status=400)
    saved = save_app_settings({"SETUP_WIZARD_COMPLETE": True}, user_id=user_id, defaults_overrides=_default_app_overrides())
    if user_id:
        saved = (await _reload_request_runtime(request)).settings
    _kick_library_indexes_from_settings(user_id, saved)
    runtime = user_runtime_for(request)
    return json_response(_setup_status_for_user(runtime.username, saved, runtime.lastfm))


@routes.get("/api/services/status")
async def api_services_status(request: web.Request):
    runtime = user_runtime_for(request)
    return json_response({"ok": True, "services": _service_status_payload(runtime.settings, runtime.soulseek_service, runtime.lastfm)})


@routes.get("/api/settings/export")
async def api_settings_export(request: web.Request):
    runtime = user_runtime_for(request)
    settings = _runtime_settings(request)
    server_controls_owner = is_owner(current_user(request))
    payload = {}
    for key in sorted(APP_SETTING_KEYS):
        if key in {"SETUP_SKIPPED_SERVICES", "SETUP_WIZARD_COMPLETE"}:
            payload[key] = settings.get(key)
            continue
        if key in SECRET_SETTING_KEYS:
            continue
        if key in SERVER_SETTING_KEYS and not server_controls_owner:
            continue
        payload[key] = settings.get(key)
    return json_response({"ok": True, "version": 1, "username": runtime.username, "include_secrets": False, "settings": payload})


@routes.post("/api/settings/import")
async def api_settings_import(request: web.Request):
    data = await request.json() or {}
    raw_settings = data.get("settings")
    if not isinstance(raw_settings, dict):
        return json_response({"ok": False, "error": "Import file must contain a settings object."}, status=400)
    include_secrets = bool(data.get("include_secrets"))
    server_controls_owner = is_owner(current_user(request))
    clean = {}
    server_clean = {}
    for key, value in raw_settings.items():
        key_upper = str(key).upper()
        if key_upper in DEVICE_SETTING_KEYS:
            return json_response({"ok": False, "error": "Device settings stay in this browser and cannot be imported to the server."}, status=400)
        if key_upper not in APP_SETTING_KEYS:
            continue
        if key_upper in SECRET_SETTING_KEYS and not include_secrets:
            continue
        if key_upper in _OWNER_ONLY_SETTING_KEYS and not server_controls_owner:
            return json_response({"ok": False, "error": "Only the owner can import server endpoint settings."}, status=403)
        if key_upper in SERVER_SETTING_KEYS:
            server_clean[key_upper] = value
        else:
            clean[key_upper] = value
    user_id = _settings_scope(request)
    if server_clean:
        save_server_settings(server_clean, defaults_overrides=_default_app_overrides())
        await _invalidate_user_runtimes_for_server_settings(request)
    saved = save_app_settings(clean, user_id=user_id, defaults_overrides=_default_app_overrides())
    if user_id:
        await _reload_request_runtime(request)
    if "LIBRARY_FOLDERS" in clean:
        _kick_library_indexes_from_settings(user_id, saved)
    return json_response({"ok": True, "settings": masked_settings(saved), "imported_keys": sorted([*clean, *server_clean])})


@routes.post("/api/settings/save")
async def api_settings_save(request: web.Request):
    data = await request.json() or {}
    settings_updates = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    startup_updates = data.get("startup") if isinstance(data.get("startup"), dict) else {}
    server_controls_owner = is_owner(current_user(request))
    if startup_updates and not server_controls_owner:
        return json_response({"ok": False, "error": "Only the owner can change server settings."}, status=403)

    clean_settings = {}
    server_settings = {}
    for key, value in settings_updates.items():
        key_upper = str(key).upper()
        if value == "***":
            continue
        if key_upper in DEVICE_SETTING_KEYS:
            return json_response({"ok": False, "error": "Device settings stay in this browser and cannot be saved to the server."}, status=400)
        if key_upper in _OWNER_ONLY_SETTING_KEYS and not server_controls_owner:
            return json_response({"ok": False, "error": "Only the owner can change server endpoint settings."}, status=403)
        if key_upper not in APP_SETTING_KEYS:
            continue
        if key_upper in SERVER_SETTING_KEYS:
            server_settings[key_upper] = value
        else:
            clean_settings[key_upper] = value
    user_id = _settings_scope(request)
    if server_settings:
        save_server_settings(server_settings, defaults_overrides=_default_app_overrides())
        await _invalidate_user_runtimes_for_server_settings(request)
    saved = save_app_settings(clean_settings, user_id=user_id, defaults_overrides=_default_app_overrides())

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

    if user_id:
        saved = (await _reload_request_runtime(request)).settings
    library_setting_keys = {"LIBRARY_FOLDERS", "DOWNLOAD_DIR", "SOULSEEK_DOWNLOAD_DIR", "YOUTUBE_DOWNLOAD_DIR"}
    if library_setting_keys.intersection(clean_settings):
        _kick_library_indexes_from_settings(user_id, saved)
    restart_required = bool(set(startup_updates).intersection({"PORT", "ENABLE_MCP"}))
    return json_response({"ok": True, "settings": masked_settings(saved), "restart_required": restart_required, "library_versions": _user_library_versions(user_id)})


@routes.post("/api/settings/mcp_reset_token")
async def api_settings_mcp_reset_token(request: web.Request):
    if not is_owner(current_user(request)):
        return json_response({"ok": False, "error": "Only the owner can reset the MCP token."}, status=403)
    cfg = ensure_startup_security_config()
    cfg["MCP_TOKEN"] = secrets.token_urlsafe(48)
    cfg["ENABLE_MCP"] = True
    save_config(cfg)
    return json_response({"ok": True, "saved": True})


def _owner_backup_access(request: web.Request) -> None:
    if not is_owner(current_user(request)):
        raise web.HTTPForbidden(text="Owner access required")


@routes.get("/api/system/backups")
async def api_system_backups(request: web.Request):
    _owner_backup_access(request)
    return json_response({"ok": True, "backups": list_backups()})


@routes.post("/api/system/backups/create")
async def api_system_backup_create(request: web.Request):
    _owner_backup_access(request)
    result = await asyncio.to_thread(create_database_backup, reason="owner requested backup")
    return json_response({"ok": True, "backup": result})


@routes.post("/api/system/backups/restore")
async def api_system_backup_restore(request: web.Request):
    _owner_backup_access(request)
    data = await request.json() or {}
    requested = str(data.get("path") or "").strip()
    available = {str(item.get("path") or "") for item in list_backups()}
    if not requested or requested not in available:
        return json_response({"ok": False, "error": "Unknown backup"}, status=404)
    await asyncio.to_thread(restore_database_backup, requested)
    clear_all_tasks()
    restore_persisted_tasks()
    return json_response({"ok": True, "restart_required": True})


@routes.post("/api/settings/pick_path")
async def api_settings_pick_path(request: web.Request):
    data = await request.json() or {}
    kind = str(data.get("kind") or "directory")
    try:
        path = pick_system_path(kind)
    except Exception:
        return json_response({"ok": False, "error": "System picker is unavailable", "manual": True}, status=400)
    if not path:
        return json_response({"ok": False, "error": "No path selected", "canceled": True})
    return json_response({"ok": True, "path": path})


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
        try:
            material = float(item["material"])
            if not math.isfinite(material):
                raise ValueError("non-finite material")
        except (KeyError, TypeError, ValueError):
            try:
                tint = max(0.0, min(2.0, float(item.get("glassTint", 1.0))))
            except (TypeError, ValueError):
                tint = 1.0
            material = -(1.0 - tint) * 0.52 if tint < 1.0 else (tint - 1.0) * 0.52
            mode = str(item.get("mode") or "").strip().lower()
            if material == 0 and mode in {"dark", "light"}:
                material = -0.52 if mode == "dark" else 0.52
            try:
                transparency = max(0.0, min(1.0, float(item["transparency"])))
            except (KeyError, TypeError, ValueError):
                transparency = 0.0
            material *= 1.0 - transparency
        out[key] = {
            "label": labels[key],
            "material": round(max(-1.0, min(1.0, material)), 4),
        }
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
        text_modes[key] = "contrast" if value in {"black", "white", "engraved"} else (value if value in {"contrast", "transparent"} else fallback)

    fps_defaults = {
        "selectedRow": 60,
        "wheelTilt": 60,
        "libraryList": 60,
        "infoPill": 60,
        "albumArtTransition": 60,
        "pathPill": 60,
        "rowInsertion": 60,
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


@routes.get("/api/defaults/diff")
async def api_defaults_diff(request: web.Request):
    current = _runtime_settings(request)
    private = {"DOWNLOAD_DIR", "SOULSEEK_DOWNLOAD_DIR", "YOUTUBE_DOWNLOAD_DIR", "LIBRARY_FOLDERS", "FFMPEG_PATH", "FFPROBE_PATH"}
    changed = {}
    for key, source_value in DEFAULT_APP_SETTINGS.items():
        if key in SECRET_SETTING_KEYS or key in private:
            continue
        current_value = current.get(key)
        if current_value != source_value:
            changed[key] = {"source": source_value, "current": current_value}
    return json_response({"ok": True, "changes": changed, "excluded_private": sorted(private), "excluded_secrets": sorted(SECRET_SETTING_KEYS)})


@routes.get("/api/library/building")
async def api_library_building(request: web.Request):
    any_building, roots_status = _user_index_status(_current_user_id(request))
    return json_response({"ok": True, "any_building": any_building, "roots": roots_status, "versions": _request_library_versions(request)})


@routes.get("/api/client-state")
async def api_client_state(request: web.Request):
    for rid, _, root_abs, mode in _request_roots(request):
        try:
            ensure_index_async(rid, root_abs, mode=mode)
            library_watch_root(rid, root_abs, mode=mode)
        except Exception:
            pass
    any_building, roots_status = _user_index_status(_current_user_id(request))
    runtime = user_runtime_for(request)
    username = runtime.username
    settings = dict(runtime.settings)
    search_history_items = list(runtime.search_history)
    with runtime.playback.lock:
        playback_recent = runtime.playback.state.get("recent") or []
        playback_version = int(runtime.playback.state.get("version") or len(playback_recent) or 0)
    services = _service_status_payload(settings, runtime.soulseek_service, runtime.lastfm)
    return json_response({
        "ok": True,
        "user": username,
        "app_version": str(VERSION_INFO.get("display_version") or VERSION),
        "short_commit": str(VERSION_INFO.get("short_commit") or ""),
        "asset_version": str(ASSET_VERSION),
        "icon_version": str(ICON_VERSION),
        "settings_version": abs(hash(json.dumps(masked_settings(settings), sort_keys=True, default=str))) % 1000000007,
        "library_versions": _request_library_versions(request),
        "search_history_version": int(max([float(x.get("ts") or 0) for x in search_history_items] + [0])),
        "playback_version": playback_version,
        "service_status_version": abs(hash(json.dumps(services, sort_keys=True, default=str))) % 1000000007,
        "setup_complete": bool(settings.get("SETUP_WIZARD_COMPLETE")),
        "library_building": any_building,
        "library_building_roots": roots_status,
    })


@routes.get("/api/performance")
async def api_performance(request: web.Request):
    runtime = user_runtime_for(request)
    settings = dict(runtime.settings)
    any_building, roots_status = _user_index_status(_current_user_id(request))
    services = _service_status_payload(settings, runtime.soulseek_service, runtime.lastfm)
    service_summary = {}
    for key, value in services.items():
        if isinstance(value, dict):
            service_summary[key] = {
                "status": str(value.get("status") or ""),
                "configured": bool(value.get("configured") or value.get("api_configured") or value.get("set")),
                "connected": bool(value.get("connected")),
                "error": str(value.get("error") or value.get("warning") or ""),
            }
    return json_response({
        "ok": True,
        "library_versions": _request_library_versions(request),
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


@routes.get("/api/sync")
async def api_sync(request: web.Request):
    runtime = user_runtime_for(request)
    username = runtime.username
    settings = dict(runtime.settings)
    try:
        since = json.loads(request.query.get("since") or "{}")
    except Exception:
        since = {}
    if not isinstance(since, dict):
        since = {}
    since_roots = since.get("library_versions") if isinstance(since.get("library_versions"), dict) else {}
    versions = _request_library_versions(request)
    root_payload = [{"id": rid, "name": name, "mode": mode, "version": int(versions.get(rid) or 0)} for rid, name, _, mode in _request_roots(request)]
    library_changes = []
    deleted = []
    for rid, _, root_abs, mode in _request_roots(request):
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
    with runtime.playback.lock:
        now = runtime.playback.state.get("now")
        recent = runtime.playback.state.get("recent") or []
        version = int(runtime.playback.state.get("version") or len(recent) or 0)
        playback = {"now": dict(now) if isinstance(now, dict) else None, "recent": [dict(x) for x in recent if isinstance(x, dict)][:100], "session": dict(runtime.playback.state.get("playback_session") or {}), "version": version}
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
        "library_versions": versions,
        "library_changes": library_changes,
        "deleted": deleted,
        "settings": masked_settings(settings),
        "search_history": list(runtime.search_history),
        "playback": playback,
        "services": _service_status_payload(settings, runtime.soulseek_service, runtime.lastfm),
        "setup_complete": bool(settings.get("SETUP_WIZARD_COMPLETE")),
    }
    return json_response(state_payload)


@routes.get("/api/library/manifest")
async def api_library_manifest(request: web.Request):
    root_id = (request.query.get("root_id") or "").strip()
    try:
        since_version = int(request.query.get("since_version") or 0)
    except Exception:
        since_version = 0
    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, mode = r
    try:
        ensure_index_async(root_id, root_abs, mode=mode)
    except Exception:
        pass
    manifest = library_manifest(root_id, since_version=max(0, since_version))
    if manifest is None:
        return json_response({"ok": True, "root_id": root_id, "version": 0, "items": [], "building": True, "stale": True})
    return json_response({"ok": True, **manifest, "building": bool(index_building_status()[1].get(root_id)), "stale": False})


@routes.route("*", "/api/library/palette")
async def api_library_palette(request: web.Request):
    if request.method == "GET":
        cache_key = (request.query.get("key") or "").strip()
        if not cache_key:
            return json_response({"ok": False, "error": "Missing palette key"}, status=400)
        _require_palette_root_membership(request, cache_key)
        palette = load_palette(cache_key)
        if palette is None:
            palette = _palette_from_art_cache_key(cache_key, _current_user_id(request))
        return json_response({"ok": True, "palette": palette})

    data = await request.json() or {}
    cache_key = str(data.get("key") or "").strip()
    palette = data.get("palette")
    if not cache_key or not isinstance(palette, dict):
        return json_response({"ok": False, "error": "Missing palette key or palette"}, status=400)
    root_id = str(data.get("root_id") or "")
    if root_id and not _request_root_by_id(request, root_id):
        raise web.HTTPNotFound()
    save_palette(
        cache_key,
        palette,
        source_kind=str(data.get("source_kind") or ""),
        source_identity=str(data.get("source_identity") or ""),
        root_id=root_id,
        rel=str(data.get("rel") or ""),
    )
    return json_response({"ok": True})


def _palette_root_id_from_cache_key(cache_key: str) -> str:
    try:
        path_part = str(cache_key or "").split("|", 1)[0]
        marker = "/art/"
        if marker not in path_part:
            return ""
        suffix = path_part.split(marker, 1)[1].strip("/")
        if not suffix or "/" not in suffix:
            return ""
        root_id, rel_encoded = suffix.split("/", 1)
        root_id = unquote(root_id)
        return root_id if root_id and rel_encoded else ""
    except Exception:
        return ""


def _require_palette_root_membership(request: web.Request, cache_key: str) -> None:
    root_id = _palette_root_id_from_cache_key(cache_key)
    if root_id and not _request_root_by_id(request, root_id):
        raise web.HTTPNotFound()


def _palette_from_art_cache_key(cache_key: str, user_id: str) -> dict | None:
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
        if not root_id or not rel or not root_by_id(root_id, user_id):
            return None
        return load_palette_for_media(root_id, rel)
    except Exception:
        return None


@routes.get("/api/library/analysis")
async def api_library_analysis(request: web.Request):
    root_id = (request.query.get("root_id") or "").strip()
    rel = (request.query.get("rel") or "").strip()
    if not root_id or not rel:
        return json_response({"ok": False, "error": "Missing root_id or rel"}, status=400)
    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
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
            await asyncio.to_thread(start_video_analysis_warm)
    except Exception:
        pass
    if not analysis:
        warming = await asyncio.to_thread(start_video_analysis_warm)
        return json_response({"ok": True, "analysis": None, "stale": True, "warming": bool(warming)})
    blob = analysis.pop("feature_blob", b"")
    timeline = load_video_timeline(str(analysis.get("analysis_key") or ""))
    if timeline:
        analysis["video_palette_timeline"] = timeline
    analysis["feature_blob_b64"] = base64.b64encode(blob).decode("ascii")
    analysis["feature_blob_encoding"] = "base64-raw"
    return json_response({"ok": True, "analysis": analysis, "stale": False})





# =========================
# Playback state API (server-side)
# =========================
@routes.get("/api/playback/snapshot")
async def api_playback_snapshot(request: web.Request):
    return json_response(playback_snapshot_public(user_runtime_for(request).playback))

@routes.get("/api/playback/recent")
async def api_playback_recent(request: web.Request):
    runtime = user_runtime_for(request)
    with runtime.playback.lock:
        recent = runtime.playback.state.get("recent") or []
        out = []
        for it in recent:
            if not isinstance(it, dict):
                continue
            d = dict(it)
            d.pop("_key", None)
            d.pop("_sess", None)
            d.pop("_stream_item", None)
            out.append(d)
    return json_response({"recent": out})

@routes.post("/api/playback/update")
async def api_playback_update(request: web.Request):
    js = await request.json() or {}
    out = playback_update_from_client(js, user_runtime_for(request).playback)
    if not out.get("ok"):
        return json_response(out, status=400)
    return json_response(out)


@routes.get("/api/library/browse")
async def api_library_browse(request: web.Request):
    root_id = (request.query.get("root_id") or "").strip()
    rel = (request.query.get("rel") or "").strip()
    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, mode = r
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        raise web.HTTPBadRequest()
    if not os.path.isdir(abs_path):
        raise web.HTTPNotFound()

    try:
        ensure_index_async(root_id, root_abs, mode=mode)
    except Exception:
        pass

    cached = load_folder_entries(root_id, rel, abs_path)
    if cached is not None:
        return json_response(cached)

    entries = []
    try:
        names = os.listdir(abs_path)
    except OSError:
        names = []

    dirs = []
    files = []
    for n in names:
        if n.startswith(".") or n == "_debripod_cache":
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
    return json_response({"entries": entries, "version": version, "building": building, "stale": False})


@routes.get("/api/library/metadata")
async def api_library_metadata(request: web.Request):
    root_id = (request.query.get("root_id") or "").strip()
    level = (request.query.get("level") or "").strip().lower()
    value = (request.query.get("value") or "").strip()
    runtime = user_runtime_for(request)
    playback_runtime = runtime.playback
    lastfm = runtime.lastfm

    aggregate = root_id == LIBRARY_ALL_ROOT_ID
    r = None if aggregate else _request_root_by_id(request, root_id)
    if not aggregate and not r:
        raise web.HTTPNotFound()
    root_abs = "" if aggregate else r[2]
    mode = "metadata" if aggregate else r[3]

    if level == "playlists":
        items = []
        if aggregate:
            for root in root_objects(_current_user_id(request)):
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
        return json_response({"items": items, "version": (sum(_request_library_versions(request).values()) if aggregate else library_root_version(root_id)), "stale": False})

    if level == "playlist_tracks":
        playlist_root_id = root_id
        if aggregate:
            try:
                selector = json.loads(value) if value else {}
            except Exception:
                selector = {}
            playlist_root_id = str(selector.get("root_id") or request.query.get("item_root_id") or "")
            value = str(selector.get("rel") or selector.get("value") or value)
            selected_root = _request_root_by_id(request, playlist_root_id)
            if not selected_root:
                raise web.HTTPNotFound()
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
        return json_response({"items": items, "version": library_root_version(playlist_root_id), "stale": False})

    if aggregate:
        data = {"tracks": [], "videos": [], "movies": [], "shows": []}
        aggregate_shows: list[dict[str, Any]] = []
        building_map = index_building_status()[1]
        building = False
        for root in root_objects(_current_user_id(request)):
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
        aggregate_alias_root_id = f"{LIBRARY_ALL_ROOT_ID}:{_current_user_id(request)}"
        aliases = load_show_aliases(aggregate_alias_root_id)
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
        save_show_aliases(aggregate_alias_root_id, aliases)
        data["version"] = sum(int(version or 0) for version in _request_library_versions(request).values())
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
                {"key": "genres", "label": "Genres"},
                {"key": "playlists", "label": "Playlists"},
                {"key": "movies", "label": "Movies"},
                {"key": "shows", "label": "Shows"},
                {"key": "videos", "label": "Videos"},
                {"key": "folders", "label": "Folders"},
            ]
            return json_response({"categories": cats, "building": True, "version": 0, "stale": True})
        return json_response({"items": [{"kind": "info", "label": "Indexing media files..."}], "building": True, "version": 0, "stale": True})

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
        progress = media_progress_for(rid, rel, playback_runtime)
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
            "source_url": str(record.get("source_url") or (record.get("manifest") or {}).get("source_url") or ""),
            "season": parsed.get("season"),
            "episode": parsed.get("episode"),
            "episode_end": parsed.get("episode_end"),
            "show_title": str(parsed.get("show_title") or ""),
            "pills": pills,
            "forceTwoLine": True,
        }

    if level == "top":
        cats = [
            {"key": "artists", "label": "Artists"},
            {"key": "albums", "label": "Albums"},
            {"key": "songs", "label": "Songs"},
            {"key": "genres", "label": "Genres"},
            {"key": "playlists", "label": "Playlists"},
            {"key": "movies", "label": "Movies"},
            {"key": "shows", "label": "Shows"},
            {"key": "videos", "label": "Videos"},
            {"key": "folders", "label": "Folders"},
        ]
        return json_response({"categories": cats, **response_meta})

    if level == "artists":
        items = facet_items("artists", "No artist tags found")
        if items:
            return json_response({"items": items, **response_meta})
        s = sorted({(t.get("artist") or "").strip() for t in tracks if (t.get("artist") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "artist", "label": a, "value": a} for a in s] or [{"kind": "info", "label": "No artist tags found"}]
        return json_response({"items": items, **response_meta})

    if level == "albums":
        artist_filter = value
        if artist_filter and isinstance(facets.get("albums_by_artist"), dict):
            payload = facets.get("albums_by_artist", {}).get(artist_filter)
            if isinstance(payload, list):
                return json_response({"items": payload or [{"kind": "info", "label": "No albums found"}], **response_meta})
        if not artist_filter:
            payload = facet_items("albums", "No albums found")
            if payload:
                return json_response({"items": payload, **response_meta})
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
        return json_response({"items": albums, **response_meta})

    if level == "tracks":
        try:
            sel = json.loads(value) if value else {}
        except Exception:
            sel = {}
        artist = (sel.get("artist") or "").strip()
        album = (sel.get("album") or "").strip()
        genre = (sel.get("genre") or "").strip()
        liked_only = bool(sel.get("liked") or sel.get("loved") or sel.get("liked_only"))
        if liked_only and not (lastfm and lastfm.enabled()):
            return json_response({"items": [{"kind": "info", "label": "Last.fm is not configured. Add API credentials or skip Last.fm features."}], **response_meta})
        if not liked_only and isinstance(facets.get("tracks_by_key"), dict):
            payload = facets.get("tracks_by_key", {}).get(track_facet_key(artist=artist, album=album, genre=genre))
            if isinstance(payload, list):
                return json_response({"items": payload or [{"kind": "info", "label": "No tracks found"}], **response_meta})
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
                if not a or not tt or not lastfm or not lastfm.is_loved(a, tt, b):
                    continue
            label = t.get("title") or t.get("name") or "Track"
            tr.append({"kind": "track", "label": label, "rel": t.get("rel"), "root_id": t.get("root_id") or root_id, "root": {"id": t.get("root_id") or root_id}, "badge": (t.get("track") or "")})
        tr.sort(key=lambda x: track_sort_key(x.get("badge") or "") + (x.get("label") or "",))
        if not tr:
            tr = [{"kind": "info", "label": "No tracks found"}]
        return json_response({"items": tr, **response_meta})


    if level in {"liked_music", "liked_movies", "liked_episodes", "liked_videos"}:
        requested_types = {
            "liked_music": ("music",),
            "liked_movies": ("movie",),
            "liked_episodes": ("episode",),
            "liked_videos": ("video", "youtube"),
        }[level]
        liked_rows: list[dict[str, Any]] = []
        like_root_id = "" if aggregate else root_id
        for requested_type in requested_types:
            liked_rows.extend(list_media_likes(_current_user_id(request), media_type=requested_type, root_id=like_root_id))
        items = []
        for liked in sorted(liked_rows, key=lambda row: float(row.get("updated_at") or 0), reverse=True):
            media_type = str(liked.get("media_type") or "")
            metadata = liked.get("metadata") if isinstance(liked.get("metadata"), dict) else {}
            media = "audio" if media_type == "music" else "video"
            kind = {
                "music": "track",
                "movie": "movie",
                "episode": "show_episode",
            }.get(media_type, "file")
            row = {
                "kind": kind,
                "label": str(liked.get("title") or liked.get("rel") or "Liked media").split("/")[-1],
                "root_id": str(liked.get("root_id") or ""),
                "root": {"id": str(liked.get("root_id") or "")},
                "rel": str(liked.get("rel") or ""),
                "media": media,
                "source": str(liked.get("source") or "library"),
                "source_id": str(liked.get("source_id") or ""),
                "source_url": str(metadata.get("source_url") or ""),
                "title": str(liked.get("title") or ""),
                "artist": str(liked.get("artist") or ""),
                "album": str(liked.get("album") or ""),
                "year": metadata.get("year"),
                "show_key": str(metadata.get("show_key") or ""),
                "show_title": str(metadata.get("show_title") or ""),
                "season": metadata.get("season"),
                "episode": metadata.get("episode"),
                "art": str(metadata.get("art") or ""),
                "ext": str(metadata.get("ext") or ""),
                "quality": str(metadata.get("quality") or ""),
            }
            if row["rel"] or row["source_url"]:
                items.append(row)
        if not items:
            empty_label = {
                "liked_music": "No liked songs found",
                "liked_movies": "No liked movies found",
                "liked_episodes": "No liked episodes found",
                "liked_videos": "No liked videos found",
            }[level]
            items = [{"kind": "info", "label": empty_label}]
        return json_response({"items": items[:3000], **response_meta})

    if level == "songs":
        items = facet_items("songs", "No songs found")
        if items:
            return json_response({"items": items, **response_meta})
        s = sorted(tracks, key=lambda x: (x.get("title") or x.get("name") or "").lower())
        items = [{"kind": "track", "label": (t.get("title") or t.get("name") or "Track"), "rel": t.get("rel"), "root_id": t.get("root_id") or root_id, "root": {"id": t.get("root_id") or root_id}} for t in s[:3000]]
        if not items:
            items = [{"kind": "info", "label": "No songs found"}]
        return json_response({"items": items, **response_meta})

    if level == "genres":
        items = facet_items("genres", "No genre tags found")
        if items:
            return json_response({"items": items, **response_meta})
        s = sorted({(t.get("genre") or "").strip() for t in tracks if (t.get("genre") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "genre", "label": g, "value": g} for g in s] or [{"kind": "info", "label": "No genre tags found"}]

        return json_response({"items": items, **response_meta})

    if level == "genre_albums":
        genre = value
        if isinstance(facets.get("genre_albums"), dict):
            payload = facets.get("genre_albums", {}).get(genre)
            if isinstance(payload, list):
                return json_response({"items": payload or [{"kind": "info", "label": "No tracks found"}], **response_meta})
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
        return json_response({"items": albums, **response_meta})

    if level == "genre_tracks":
        genre = value
        if isinstance(facets.get("tracks_by_key"), dict):
            payload = facets.get("tracks_by_key", {}).get(track_facet_key(genre=genre))
            if isinstance(payload, list):
                return json_response({"items": payload or [{"kind": "info", "label": "No tracks found"}], **response_meta})
        items = []
        for t in tracks:
            if (t.get("genre") or "").strip() != genre:
                continue
            label = t.get("title") or t.get("name") or "Track"
            items.append({"kind": "track", "label": label, "rel": t.get("rel"), "root_id": t.get("root_id") or root_id, "root": {"id": t.get("root_id") or root_id}})
        items.sort(key=lambda x: (x.get("label") or "").lower())
        if not items:
            items = [{"kind": "info", "label": "No tracks found"}]
        return json_response({"items": items, **response_meta})

    if level == "movies":
        items = [playable_video_row(item, "movie") for item in (data.get("movies") or []) if isinstance(item, dict)]
        if not items:
            items = [{"kind": "info", "label": "No movies found"}]
        return json_response({"items": items[:3000], **response_meta})

    if level == "shows":
        items = []
        for show in data.get("shows") or []:
            if not isinstance(show, dict):
                continue
            episodes = [item for item in (show.get("episodes") or []) if isinstance(item, dict)]
            percentages = [int(media_progress_for(str(item.get("root_id") or root_id), str(item.get("rel") or ""), playback_runtime).get("completion_percent") or 0) for item in episodes]
            percent = math.floor(sum(percentages) / len(percentages)) if percentages else 0
            count = len(episodes)
            items.append({
                "kind": "show", "label": str(show.get("label") or "Show"), "show_key": str(show.get("show_key") or ""),
                "episode_count": count, "completion_percent": percent, "pills": [f"{count} episode" + ("" if count == 1 else "s"), f"{percent}%"],
            })
        if not items:
            items = [{"kind": "info", "label": "No shows found"}]
        return json_response({"items": items, **response_meta})

    if level == "show_seasons":
        show = next((item for item in (data.get("shows") or []) if isinstance(item, dict) and str(item.get("show_key") or "") == value), None)
        if not show:
            return json_response({"items": [{"kind": "info", "label": "Show not found"}], **response_meta})
        seasons: dict[int, list[dict]] = {}
        for episode in show.get("episodes") or []:
            if isinstance(episode, dict):
                seasons.setdefault(int((episode.get("parse") or {}).get("season") or 0), []).append(episode)
        items = []
        for season, episodes in sorted(seasons.items()):
            percentages = [int(media_progress_for(str(item.get("root_id") or root_id), str(item.get("rel") or ""), playback_runtime).get("completion_percent") or 0) for item in episodes]
            percent = math.floor(sum(percentages) / len(percentages)) if percentages else 0
            count = len(episodes)
            label = "Specials" if season == 0 else f"Season {season}"
            items.append({"kind": "show_season", "label": label, "show_key": value, "season": season, "episode_count": count, "completion_percent": percent, "pills": [f"{count} episode" + ("" if count == 1 else "s"), f"{percent}%"]})
        return json_response({"items": items or [{"kind": "info", "label": "No seasons found"}], **response_meta})

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
        return json_response({"items": items or [{"kind": "info", "label": "No episodes found"}], **response_meta})

    if level == "videos":
        items = [playable_video_row(item, "video") for item in sorted(vids, key=lambda x: (x.get("title") or x.get("name") or "").lower())[:3000] if isinstance(item, dict)]
        if not items:
            items = [{"kind": "info", "label": "No videos found"}]
        return json_response({"items": items, **response_meta})

    return json_response({"items": [{"kind": "info", "label": "Unsupported view"}], **response_meta})


@routes.post("/api/library/playlist_create")
async def api_library_playlist_create(request: web.Request):
    js = await request.json() or {}
    root_id = str(js.get("root_id") or "").strip()
    name = str(js.get("name") or "").strip()

    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r

    ok, err, info = create_root_playlist(root_abs, name)
    if not ok:
        return json_response({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return json_response({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@routes.post("/api/library/playlist_rename")
async def api_library_playlist_rename(request: web.Request):
    js = await request.json() or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    name = str(js.get("name") or "").strip()

    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r

    ok, err, info = rename_root_playlist(root_abs, playlist_rel, name)
    if not ok:
        return json_response({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return json_response({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@routes.post("/api/library/playlist_add")
async def api_library_playlist_add(request: web.Request):
    js = await request.json() or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    tracks = js.get("tracks") if isinstance(js.get("tracks"), list) else []
    clean_tracks = [str(x or "").strip() for x in tracks if str(x or "").strip()]

    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r

    ok, err, info = add_tracks_to_playlist(root_abs, playlist_rel, clean_tracks)
    if not ok:
        return json_response({"ok": False, "error": err, "added": int((info or {}).get("added") or 0)})
    return json_response({"ok": True, "added": int((info or {}).get("added") or 0)})


@routes.post("/api/library/playlist_remove")
async def api_library_playlist_remove(request: web.Request):
    js = await request.json() or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    tracks = js.get("tracks") if isinstance(js.get("tracks"), list) else []
    clean_tracks = [str(x or "").strip() for x in tracks if str(x or "").strip()]

    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r

    ok, err, info = remove_tracks_from_playlist(root_abs, playlist_rel, clean_tracks)
    if not ok:
        return json_response({"ok": False, "error": err, "removed": int((info or {}).get("removed") or 0)})
    return json_response({"ok": True, "removed": int((info or {}).get("removed") or 0)})




@routes.post("/api/library/playlist_delete")
async def api_library_playlist_delete(request: web.Request):
    js = await request.json() or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()

    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r

    ok, err, info = delete_root_playlist(root_abs, playlist_rel)
    if not ok:
        return json_response({"ok": False, "error": err}, status=400)
    return json_response({"ok": True, "smart": bool((info or {}).get("smart"))})


@routes.post("/api/library/smart_playlist_create")
async def api_library_smart_playlist_create(request: web.Request):
    js = await request.json() or {}
    root_id = str(js.get("root_id") or "").strip()
    name = str(js.get("name") or "").strip()

    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r

    ok, err, info = create_root_smart_playlist(root_abs, name)
    if not ok:
        return json_response({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return json_response({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@routes.route("*", "/api/library/smart_playlist_rules")
async def api_library_smart_playlist_rules(request: web.Request):
    if request.method == "GET":
        root_id = (request.query.get("root_id") or "").strip()
        playlist_rel = (request.query.get("rel") or "").strip()
        r = _request_root_by_id(request, root_id)
        if not r:
            raise web.HTTPNotFound()
        _, _, root_abs, _ = r
        ok, err, info = load_smart_playlist_rules(root_abs, playlist_rel)
        if not ok:
            return json_response({"ok": False, "error": err}, status=400)
        return json_response({"ok": True, "text": str((info or {}).get("text") or ""), "label": str((info or {}).get("label") or "")})

    js = await request.json() or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    text = str(js.get("text") or "")
    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r
    ok, err, info = save_smart_playlist_rules(root_abs, playlist_rel, text)
    if not ok:
        return json_response({"ok": False, "error": err}, status=400)
    return json_response({"ok": True, "label": str((info or {}).get("label") or "")})


@routes.get("/api/library/filemeta")
async def api_library_filemeta(request: web.Request):
    root_id = (request.query.get("root_id") or "").strip()
    rel = (request.query.get("rel") or "").strip()
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(rel, user_runtime_for(request))
        if not it:
            raise web.HTTPNotFound()
        return json_response({
            "title": str(it.get("title") or it.get("name") or ""),
            "artist": str(it.get("artist") or ""),
            "album": str(it.get("album") or ""),
            "genre": "",
            "duration": None,
            "tech": str(it.get("quality") or it.get("ext") or ""),
            "art": str(it.get("art") or ""),
        })
    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        raise web.HTTPBadRequest()
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        raise web.HTTPNotFound()

    meta = await asyncio.to_thread(file_meta_cached, abs_path)

    art = ""
    ver = ""
    try:
        ver = str(int(os.path.getmtime(os.path.dirname(abs_path))))
    except OSError:
        ver = ""
    ap = await asyncio.to_thread(art_for_media_path, abs_path) if is_audio(abs_path) else None
    if ap:
        art = "/art/" + quote(root_id, safe="") + "/" + quote(rel, safe="/")
        if ver:
            art = art + "?v=" + ver

    return json_response(
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


@routes.get("/api/library/media_information")
async def api_library_media_information(request: web.Request):
    show_title = (request.query.get("show_title") or "").strip()
    try:
        season = int(request.query.get("season") or 0)
        episode = int(request.query.get("episode") or 0)
    except (TypeError, ValueError):
        return json_response(ok=False, error="Invalid episode", information={}, status=400)
    if not show_title or season < 0 or episode <= 0:
        return json_response(ok=False, error="Missing episode", information={}, status=400)
    information = await normalized_episode_information(show_title, season, episode)
    return json_response(ok=True, information=information)


@routes.route("*", "/api/library/like")
async def api_library_like(request: web.Request):
    user_id = _current_user_id(request)
    lastfm = user_runtime_for(request).lastfm
    if request.method == "GET":
        media_key = (request.query.get("media_key") or "").strip()
        if not media_key:
            return json_response(ok=False, error="Missing media key", status=400)
        row = get_media_like(user_id, media_key)
        if row is None:
            artist = (request.query.get("artist") or "").strip()
            title = (request.query.get("title") or "").strip()
            album = (request.query.get("album") or "").strip()
            if artist and title and lastfm and lastfm.is_loved(artist, title, album):
                target = {
                    "media_type": "music", "source": "lastfm", "artist": artist,
                    "title": title, "album": album,
                }
                row = set_media_like(user_id, target, True)
        return json_response(ok=True, like=row)

    payload = await request.json() or {}
    if not isinstance(payload.get("liked"), bool):
        return json_response(ok=False, error="liked must be a boolean", status=400)
    try:
        row = set_media_like(user_id, payload, bool(payload["liked"]))
    except ValueError as exc:
        return json_response(ok=False, error=str(exc), status=400)
    warning = ""
    if row.get("media_type") == "music":
        artist = str(row.get("artist") or "")
        title = str(row.get("title") or "")
        album = str(row.get("album") or "")
        if artist and title:
            try:
                if lastfm:
                    lastfm.set_loved_local(artist, title, album, bool(row["liked"]))
                if lastfm and lastfm.enabled():
                    if row["liked"]:
                        await lastfm.love_track(artist, title)
                    else:
                        await lastfm.unlove_track(artist, title)
            except Exception:
                warning = "Local like saved; Last.fm sync failed"
    return json_response(ok=True, like=row, sync_warning=warning)


@routes.get("/api/library/liked")
async def api_library_liked(request: web.Request):
    media_type = (request.query.get("media_type") or "").strip().lower()
    root_id = (request.query.get("root_id") or "").strip()
    if media_type and media_type not in {"music", "movie", "episode", "video", "youtube"}:
        return json_response(ok=False, error="Unsupported media type", items=[], status=400)
    rows = list_media_likes(_current_user_id(request), media_type=media_type, root_id=root_id)
    return json_response(ok=True, items=rows)


@routes.get("/art/{root_id}/{relpath:.*}")
async def art(request: web.Request):
    root_id = request.match_info["root_id"]
    relpath = request.match_info["relpath"]
    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        raise web.HTTPBadRequest()
    ap = await asyncio.to_thread(art_for_media_path, abs_path)
    if not ap:
        raise web.HTTPNotFound()
    return await range_response(request, ap)




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
            raise web.HTTPNotFound()
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


def _resolve_stream_source_for_hls(root_id: str, relpath: str, runtime: UserRuntime) -> str:
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(unquote(relpath), runtime)
        if not it:
            raise web.HTTPNotFound()
        if str(it.get("source") or "").strip().lower() == 'youtube':
            try:
                return _prepare_youtube_stream_file(str(it.get('youtube_url') or it.get('url') or ''), it)
            except Exception:
                raise RuntimeError("Unable to fetch stream")
        raise web.HTTPBadRequest()
    r = root_by_id(root_id, runtime.user_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        raise web.HTTPBadRequest()
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        raise web.HTTPNotFound()
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


def _rewrite_hls_manifest_text(text: str, key: str, access_token: str) -> str:
    base = "/hls/file/" + quote(key, safe="") + "/"
    query = "?access_token=" + quote(access_token, safe="")
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out.append(raw)
            continue
        if line.startswith("#EXT-X-MAP:"):
            line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + base + quote(os.path.basename(m.group(1)), safe="/._-") + query + '"', line)
            out.append(line)
            continue
        if line.startswith("#"):
            out.append(raw)
            continue
        out.append(base + quote(line, safe="/._-") + query)
    return "\n".join(out) + "\n"


@routes.get("/hls/manifest")
async def hls_manifest(request: web.Request):
    root_id = str(request.query.get("root_id") or "")
    rel = str(request.query.get("rel") or "")
    if not root_id or not rel:
        raise web.HTTPBadRequest()
    try:
        playable = await asyncio.to_thread(_resolve_stream_source_for_hls, root_id, rel, user_runtime_for(request))
        key, manifest_path = await asyncio.to_thread(_hls_cache_entry_for_path, playable)
        raw = await asyncio.to_thread(Path(manifest_path).read_text, encoding="utf-8", errors="replace")
        access_token = _new_hls_access_token(_current_user_id(request), root_id, key)
        return web.Response(text=_rewrite_hls_manifest_text(raw, key, access_token), content_type="application/vnd.apple.mpegurl")
    except RuntimeError:
        return web.Response(text="Unable to prepare stream", status=500, content_type="text/plain")


@routes.get("/hls/file/{key}/{name:.*}")
async def hls_file(request: web.Request):
    key = request.match_info["key"]
    name = request.match_info["name"]
    key2 = re.sub(r"[^a-fA-F0-9]", "", str(key or ""))[:64]
    if not key2:
        raise web.HTTPNotFound()
    if not _hls_access_allowed(str(request.query.get("access_token") or ""), _current_user_id(request), key2):
        raise web.HTTPNotFound()
    base = os.path.join(hls_cache_dir(), key2)
    try:
        path = safe_path_join(base, unquote(name))
    except ValueError:
        raise web.HTTPBadRequest()
    if not os.path.exists(path) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    mime = pick_mime(path)
    if request.method.upper() == "HEAD":
        return web.Response(status=200, headers={"Content-Length": str(os.path.getsize(path))}, content_type=mime)
    return await range_response(request, path)


def _proxy_url_allowed(raw_url: str, *, trusted_provider_stream: bool = False) -> bool:
    try:
        validated = validate_public_http_url(raw_url)
        host = str(urlsplit(validated).hostname or "").lower()
    except UnsafeOutboundUrl:
        return False
    allowed_suffixes = []
    for raw_suffix in (STREAM_PROXY_ALLOWED_HOST_SUFFIXES or []):
        suffix = str(raw_suffix or "").strip().lower().lstrip(".")
        if suffix:
            allowed_suffixes.append(suffix)
    if not trusted_provider_stream and allowed_suffixes and not any(host == suffix or host.endswith("." + suffix) for suffix in allowed_suffixes):
        return False
    return True


def _safe_proxy_headers(upstream_headers: Any) -> List[Tuple[str, str]]:
    allowed = {"accept-ranges", "content-length", "content-range", "content-type", "etag", "last-modified"}
    out_headers: List[Tuple[str, str]] = []
    for k2, v2 in upstream_headers.items():
        if str(k2).lower() in allowed:
            out_headers.append((str(k2), str(v2)))
    return out_headers


@routes.get("/stream/{root_id}/{relpath:.*}")
async def stream(request: web.Request):
    root_id = request.match_info["root_id"]
    relpath = request.match_info["relpath"]
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(unquote(relpath), user_runtime_for(request))
        if not it:
            raise web.HTTPNotFound()
        if str(it.get("source") or "").strip().lower() == 'youtube':
            try:
                local_path = await asyncio.to_thread(_prepare_youtube_stream_file, str(it.get('youtube_url') or it.get('url') or ''), it)
            except Exception:
                return web.Response(text="Unable to fetch stream", status=502, content_type="text/plain")
            return await range_response(request, local_path)
        upstream_url = str(it.get("url") or "")
        trusted_provider_stream = bool(it.get("trusted_provider_stream"))
        if not _proxy_url_allowed(upstream_url, trusted_provider_stream=trusted_provider_stream):
            raise web.HTTPBadRequest()
        headers = {}
        rng = request.headers.get("Range")
        if rng:
            headers["Range"] = rng
        method = "HEAD" if request.method == "HEAD" else "GET"
        session = request.app[SERVICES_KEY].http.session
        try:
            upstream, _final_url = await request_public_url(
                session, method, upstream_url, headers=headers,
                timeout=float(REQUEST_TIMEOUT_SECONDS),
            )
        except web.HTTPException:
            raise
        except Exception:
            return web.Response(text="Unable to fetch stream", status=502, content_type="text/plain")
        out_headers = _safe_proxy_headers(upstream.headers)
        if request.method == "HEAD":
            status = upstream.status
            upstream.close()
            return web.Response(status=status, headers=out_headers)
        response = web.StreamResponse(status=upstream.status, headers=out_headers)
        await response.prepare(request)
        try:
            async for chunk in upstream.content.iter_chunked(64 * 1024):
                await response.write(chunk)
            await response.write_eof()
        finally:
            upstream.close()
        return response
    r = _request_root_by_id(request, root_id)
    if not r:
        raise web.HTTPNotFound()
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        raise web.HTTPBadRequest()

    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        raise web.HTTPNotFound()

    try:
        playable = await asyncio.to_thread(transcode_if_needed, abs_path)
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
        return web.Response(text="Unable to prepare stream", status=500, content_type="text/plain")

    return await range_response(request, playable)


async def _local_index_update_loop(services: AppServices) -> None:
    await asyncio.sleep(2.0)
    while True:
        updater = services.local_index_updater
        if updater is None:
            return
        services.local_index_state = {"building": True, **dict(getattr(updater, "state", {}) or {})}
        try:
            services.local_index_state = await updater.update()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            services.local_index_state = {"building": False, "error": str(exc)}
        interval = max(300, int(DEFAULT_APP_SETTINGS.get("LOCAL_INDEX_UPDATE_INTERVAL_SECONDS") or 21600))
        await asyncio.sleep(interval)


async def _library_reconciliation_loop() -> None:
    while True:
        for root_id, _name, root_abs, mode in state_module.roots():
            if not os.path.isdir(root_abs):
                continue
            state_module.ensure_index_async(root_id, root_abs, mode=mode, force=True)
            state_module.library_watch_root(root_id, root_abs, mode=mode)
        await asyncio.sleep(6 * 60 * 60)


async def _application_services(app: web.Application):
    services = app[SERVICES_KEY]
    restore_persisted_tasks()
    session = create_client_session(str(VERSION))
    services.http = HttpClient(session)
    lastfm_module.configure_lastfm_http(services.http)
    youtube_module.configure_youtube_http(services.http)
    tvmaze_module.configure_tvmaze_http(services.http)
    downloads_module.configure_debrid_downloads(services.http, asyncio.get_running_loop())
    services.local_index = LocalTorrentIndex()
    services.local_index.initialize()
    services.local_index_updater = LocalIndexUpdater(services.local_index, http=services.http)
    services.user_runtimes = UserRuntimeRegistry(lambda user: _create_user_runtime(services, user))
    configure_task_manager(
        soulseek_service_provider=lambda user_id: getattr(
            services.user_runtimes.snapshot().get(str(user_id or "")), "soulseek_service", None
        )
    )
    services.local_index_state = services.local_index.diagnostics()
    services.local_index_task = asyncio.create_task(_local_index_update_loop(services), name="local-index-updater")
    services.library_reconciliation_task = asyncio.create_task(
        _library_reconciliation_loop(), name="library-native-watcher-reconciliation"
    )
    try:
        yield
    finally:
        if services.local_index_task is not None:
            services.local_index_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await services.local_index_task
        if services.library_reconciliation_task is not None:
            services.library_reconciliation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await services.library_reconciliation_task
        if services.user_runtimes is not None:
            await services.user_runtimes.close_all()
        await asyncio.to_thread(state_module.library_stop_watchers)
        await session.close()


async def create_app() -> web.Application:
    ensure_startup_security_config()
    app = web.Application(middlewares=[session_middleware, auth_middleware, runtime_middleware])
    app[SERVICES_KEY] = AppServices()
    app.cleanup_ctx.append(_application_services)
    app.add_routes(routes)
    register_shell_routes(app, render_shell)
    register_icon_routes(app)
    register_lastfm_routes(app)
    register_task_routes(app)
    register_notification_routes(app)
    register_auth_routes(app)
    mcp_routes.register_mcp_routes(app)
    static_dir = Path(__file__).resolve().parent / "static"
    app.router.add_static("/static/", static_dir, name="static", follow_symlinks=False)
    return app
