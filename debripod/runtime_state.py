
import os
import time
import uuid
import json
import threading
import hashlib
import base64
import math
import mimetypes
import subprocess
import queue
import asyncio
import concurrent.futures
import shutil
import logging
from typing import Dict, Optional, List, Tuple, Any
from urllib.parse import quote, unquote, urlparse

import requests
from flask import Flask, request, redirect, url_for, render_template, abort, Response, jsonify

from .Library.search_cache import (
    _SEARCH_DISK_LOCK,
    _disk_cache_get,
    _disk_cache_set,
    _load_search_history,
    _make_search_cache_key,
    clear_search_history_and_cache,
    configure_search_cache,
    record_search_history,
)
from .Library.playlists import (
    add_tracks_to_playlist,
    configure_playlists,
    create_root_playlist,
    create_root_smart_playlist,
    delete_root_playlist,
    is_smart_playlist_rel,
    load_smart_playlist_rules,
    playlist_tracks_for_root,
    remove_tracks_from_playlist,
    rename_root_playlist,
    save_smart_playlist_rules,
    scan_root_playlists,
    smart_playlist_tracks_for_root,
)
from .Library.metadata import (
    art_cache_path,
    art_for_media_path,
    configure_metadata,
    extract_art,
    file_meta_cached,
    pick_folder_art,
)
from .Library.index import (
    build_index_for_root,
    clear_index_cache,
    configure_library_index,
    ensure_index_async,
    enrichment_status,
    get_index,
    index_building_status,
    library_manifest,
    library_metadata_facets,
    library_root_version,
    library_root_versions,
    library_watch_root,
    queue_video_analysis_warm,
    pause_enrichment_writes,
    set_index_cache,
    track_sort_key,
)
from .Library.roots import LIBRARY_ALL_ROOT_ID, configure_library_roots, root_by_id, root_objects, roots, safe_path_join
from .media_types import (
    AUDIO_EXTS,
    VIDEO_EXTS,
)
from .paths import art_cache_dir, cache_dir, configure_paths, transcode_cache_dir
from .Routes import icons as icons_module
from .Routes.icons import register_icon_routes
from .Routes.lastfm import register_lastfm_routes
from .Routes.shell import register_shell_routes
from .Routes.tasks import register_task_routes
from .version import app_version, app_version_info
from .Services.knaben import configure_knaben, knaben_search, make_magnet
from .Services.lastfm import (
    configure_lastfm,
    initialize_lastfm_cache,
    lastfm_auth_finish,
    lastfm_auth_start,
    lastfm_enabled,
    lastfm_is_loved,
    lastfm_love_track,
    lastfm_loved_updated,
    lastfm_remote_is_loved,
    lastfm_scrobble,
    lastfm_session_key,
    lastfm_set_loved_local,
    lastfm_sync_loved_from_remote,
    lastfm_unlove_track,
    lastfm_update_now_playing,
    lastfm_username,
    _lastfm_async,
)
from .Services.soulseek import (
    SoulseekService,
    _slsk_annotate_file_with_download_state,
    _slsk_expected_incoming_path,
    _slsk_group_items_to_dirs,
    _slsk_group_snapshot_to_users,
    _slsk_guess_kind_ext_attrs,
    _slsk_norm_remote_path,
    _slsk_relative_under_directory,
    _slsk_session_create,
    _slsk_session_mark_done,
    _slsk_session_snapshot,
    _slsk_session_touch,
    _slsk_task_download_dir,
    configure_aioslsk_logging,
    configure_soulseek_module,
    soulseek_incoming_dir,
)
from .Services.youtube import (
    _prepare_youtube_stream_file,
    _search_youtube_cached,
    _standardize_youtube_results,
    _yt_dlp_base_args,
    _yt_selected_output_ext,
    _yt_stream_format_selector,
    _youtube_download_root,
    configure_youtube,
    youtube_channel_browse,
    youtube_load_result_files,
    ytdlp_list_formats,
)
from .Tasks.manager import (
    TASKS,
    TASKS_LOCK,
    Task,
    _get_file_control,
    _set_file_control,
    _update_task_file_entry,
    cancel_task,
    clear_all_tasks,
    clear_task,
    configure_task_manager,
    get_task,
    list_tasks,
    pause_task,
    resume_task,
    set_task,
    task_file_action,
    task_public_dict,
)
from .utils import (
    human_bytes,
    human_rate,
    is_audio,
    is_playlist_file,
    is_video,
    sanitize_filename,
    sanitize_folder_name,
    sha1_text,
)
from .playback.streaming import pick_mime, range_response
from .playback.state import (
    PLAYBACK_STATE,
    PLAYBACK_STATE_LOCK,
    configure_playback_state,
    load_playback_state,
    playback_snapshot_public,
    playback_update_from_client,
    media_progress_for,
    save_playback_state_best_effort,
)
from .playback.transcoding import (
    _browser_compatible_for_target,
    _build_smart_transcode_args,
    _build_transcode_args,
    _build_transmux_args,
    _primary_stream_info,
    configure_transcoding,
    last_ffmpeg_error,
    lock_for_key,
    transcode_if_needed,
)
from .playback.probe import configure_probe, ffprobe_json, run_cmd
from .storage.library import finish_full_reindex
from .storage.legacy_import import migrate_runtime_json, run_startup_import_once

# =========================
# Runtime config
# =========================
VERSION_INFO = app_version_info()
VERSION = app_version()


def _commit_cache_version() -> str:
    full = str(VERSION_INFO.get("full_commit") or "").strip()
    short = str(VERSION_INFO.get("short_commit") or "").strip()
    base = full or short or str(VERSION or "dev")
    # Development and migration updates must invalidate the PWA shell even before a commit exists.
    newest = 0.0
    package_dir = os.path.dirname(__file__)
    for rel in ("static", "templates"):
        root = os.path.join(package_dir, rel)
        for current, _dirs, files in os.walk(root):
            for name in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(current, name)))
                except OSError:
                    pass
    return f"{base}-{int(newest * 1000)}" if newest else base


ASSET_VERSION = _commit_cache_version()
ICON_VERSION = ASSET_VERSION
icons_module.configure_asset_versions(asset_version=ASSET_VERSION, icon_version=ICON_VERSION)
VERSION_INFO.update({"asset_version": ASSET_VERSION, "icon_version": ICON_VERSION})

HOST = "127.0.0.1"

# Defaults live in debripod.config and are overlaid by config JSON files.
try:
    from .config import CONFIG_KEYS, apply_config_to_module
    globals().update({key: None for key in CONFIG_KEYS})
    apply_config_to_module(globals())
except Exception as _config_error:
    print(f"DebriPod config warning: {_config_error}")
configure_library_roots(
    lambda: LIBRARY_FOLDERS,
    lambda: {
        "debrid": DOWNLOAD_DIR,
        "soulseek": SOULSEEK_DOWNLOAD_DIR,
        "youtube": YOUTUBE_DOWNLOAD_DIR,
    },
)
configure_playlists(
    file_meta_provider=lambda abs_path: file_meta_cached(abs_path),
    track_sort_key_provider=lambda track: track_sort_key(track),
    is_loved_provider=lambda artist, title, album: lastfm_is_loved(artist, title, album),
    get_index_provider=lambda root_id: get_index(root_id),
    build_index_provider=lambda root_abs: build_index_for_root(root_abs),
    set_index_provider=lambda root_id, data: set_index_cache(root_id, data),
)
configure_knaben(
    api_key_provider=lambda: KNABEN_API_KEY,
    min_interval_provider=lambda: KNABEN_MIN_SECONDS_BETWEEN_REQUESTS,
    cache_ttl_provider=lambda: KNABEN_CACHE_TTL_SECONDS,
    max_retries_provider=lambda: KNABEN_MAX_RETRIES,
    api_base_provider=lambda: KNABEN_API_BASE,
    web_base_provider=lambda: KNABEN_WEB_BASE,
    timeout_provider=lambda: REQUEST_TIMEOUT_SECONDS,
    results_per_page_provider=lambda: RESULTS_PER_PAGE,
)
configure_youtube(
    ytdlp_cmd_provider=lambda: YTDLP_CMD,
    youtube_download_dir_provider=lambda: YOUTUBE_DOWNLOAD_DIR,
    download_dir_provider=lambda: DOWNLOAD_DIR,
    stream_cache_subdir_provider=lambda: YOUTUBE_STREAM_CACHE_SUBDIR,
    web_base_provider=lambda: YOUTUBE_WEB_BASE,
    search_limit_provider=lambda: YOUTUBE_SEARCH_LIMIT,
    channel_browse_limit_provider=lambda: YOUTUBE_CHANNEL_BROWSE_LIMIT,
    request_headers_provider=lambda: YOUTUBE_REQUEST_HEADERS,
    timeout_provider=lambda: REQUEST_TIMEOUT_SECONDS,
    ffmpeg_path_provider=lambda: FFMPEG_PATH,
)
configure_soulseek_module(
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
configure_metadata(ffmpeg_path_provider=lambda: FFMPEG_PATH)
configure_library_index(cache_dir_name_provider=lambda: CACHE_DIR_NAME, progress_provider=lambda root_id, rel: media_progress_for(root_id, rel))
configure_probe(ffprobe_path_provider=lambda: FFPROBE_PATH)
configure_paths(
    download_dir_provider=lambda: DOWNLOAD_DIR,
    cache_dir_name_provider=lambda: CACHE_DIR_NAME,
)
configure_transcoding(
    audio_transcode_provider=lambda: AUDIO_TRANSCODE,
    ffmpeg_path_provider=lambda: FFMPEG_PATH,
    video_browser_target_ext_provider=lambda: VIDEO_BROWSER_TARGET_EXT,
)
configure_lastfm(
    api_key=LASTFM_API_KEY,
    api_secret=LASTFM_API_SECRET,
    session_key=LASTFM_SESSION_KEY,
    callback_url=LASTFM_CALLBACK_URL,
    api_root=LASTFM_API_ROOT,
    request_timeout_seconds=LASTFM_REQUEST_TIMEOUT_SECONDS,
)

def ensure_dirs() -> None:
    if DOWNLOAD_DIR:
        if not os.path.isabs(DOWNLOAD_DIR):
            raise ValueError("DOWNLOAD_DIR must be an absolute path")
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    if SOULSEEK_DOWNLOAD_DIR:
        if not os.path.isabs(SOULSEEK_DOWNLOAD_DIR):
            raise ValueError("SOULSEEK_DOWNLOAD_DIR must be an absolute path")
        os.makedirs(SOULSEEK_DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(soulseek_incoming_dir(), exist_ok=True)
    os.makedirs(cache_dir(), exist_ok=True)
    os.makedirs(transcode_cache_dir(), exist_ok=True)
    os.makedirs(art_cache_dir(), exist_ok=True)

    run_startup_import_once()
    migrate_runtime_json(cache_dir())

    configure_lastfm(
        api_key=LASTFM_API_KEY,
        api_secret=LASTFM_API_SECRET,
        session_key=LASTFM_SESSION_KEY,
        callback_url=LASTFM_CALLBACK_URL,
        api_root=LASTFM_API_ROOT,
        request_timeout_seconds=LASTFM_REQUEST_TIMEOUT_SECONDS,
    )
    initialize_lastfm_cache()
    # Best-effort: refresh loved cache occasionally so the UI shows existing likes
    try:
        last_upd = int(lastfm_loved_updated() or 0)
        if lastfm_enabled() and (time.time() - float(last_upd or 0)) > 6 * 3600:
            _lastfm_async(lastfm_sync_loved_from_remote, lastfm_username())
    except Exception:
        pass


configure_search_cache(
    cache_dir,
    history_max_items_provider=lambda: SEARCH_HISTORY_MAX_ITEMS,
    disk_cache_ttl_seconds_provider=lambda: SEARCH_DISK_CACHE_TTL_SECONDS,
)


# =========================
# Download task tracking
# =========================
class Cancelled(Exception):
    pass


class CancelledFile(Exception):
    pass


def check_canceled(t: Task) -> None:
    if t.cancel_event.is_set():
        raise Cancelled("Canceled")



# =========================
# Soulseek (aioslsk) service
# =========================
SOULSEEK_SERVICE = None  # initialized in main()

# =========================
# Soulseek streaming search sessions
# =========================
_SLSK_SESS_LOCK = threading.Lock()
_SLSK_SESSIONS: Dict[str, Dict[str, Any]] = {}


__all__ = [name for name in globals() if not name.startswith("__")]

