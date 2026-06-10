
import os
import re
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
    _atomic_write_json,
    _disk_cache_get,
    _disk_cache_set,
    _load_search_history,
    _make_search_cache_key,
    _read_json_file,
    clear_search_history_and_cache,
    configure_search_cache,
    record_search_history,
)
from .Library.roots import configure_library_roots, root_by_id, roots, safe_path_join
from .media_types import (
    AUDIO_EXTS,
    PLAYLISTS_FOLDER_NAME,
    PLAYLIST_EXTS,
    SMART_PLAYLISTS_FOLDER_NAME,
    SMART_PLAYLIST_MEDIA_FILENAME,
    SMART_PLAYLIST_RULES_FILENAME,
    SMART_PLAYLIST_RULES_TEMPLATE,
    VIDEO_EXTS,
)
from .paths import art_cache_dir, cache_dir, configure_paths, transcode_cache_dir
from .Routes.icons import ICON_VERSION, register_icon_routes
from .Routes.lastfm import register_lastfm_routes
from .Routes.shell import register_shell_routes
from .Routes.tasks import register_task_routes
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
from .Services.real_debrid import configure_real_debrid, rd_headers, rd_request
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
from .playback.probe import configure_probe, ffprobe_json, run_cmd

# =========================
# User configurable settings
# =========================

# =========================
# Debripod settings (including ffmpeg and ffprobe paths)
# =========================
HOST = "127.0.0.1"          # localhost only
PORT = 8083                 # change the port here

APP_NAME = "Debripod"
# Auto infer version from filename like debripod112.py
_fn = os.path.basename(__file__)
_m = re.search(r"debripod(\d+)", _fn, re.IGNORECASE)
VERSION = _m.group(1) if _m else "dev"
del _fn, _m

RESULTS_PER_PAGE = 50
MAX_FILES_PER_TORRENT = 50
MAX_TORRENT_WAIT_SECONDS = 1800
POLL_INTERVAL_SECONDS = 4
REQUEST_TIMEOUT_SECONDS = 25

SEARCH_STREAM_ROOT_ID = "__search_stream__"
SEARCH_STREAM_SESSION_TTL_SECONDS = 6 * 60 * 60

# How often the browser polls for task status updates
TASKS_POLL_MS = 1200

# MCP server settings
MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_SEARCH_RESULT_LIMIT = 20

# =========================
# Knaben settings
# =========================

# Optional: Knaben API key. Leave empty for free tier.
KNABEN_API_KEY = ""

# Knaben API behavior controls
KNABEN_MIN_SECONDS_BETWEEN_REQUESTS = 0.6
KNABEN_CACHE_TTL_SECONDS = 120.0
KNABEN_MAX_RETRIES = 5

KNABEN_API_BASE = "https://api.knaben.org/v1"
KNABEN_WEB_BASE = "https://knaben.org"

# =========================
# YouTube and yt-dlp settings
# =========================

YTDLP_CMD = "yt-dlp"
YOUTUBE_DOWNLOAD_DIR = r"./data/youtube"
YOUTUBE_STREAM_CACHE_SUBDIR = "youtube_streams"
YOUTUBE_WEB_BASE = "https://www.youtube.com"
YOUTUBE_SEARCH_LIMIT = 24
YOUTUBE_CHANNEL_BROWSE_LIMIT = 0  # 0 means all channel videos
YOUTUBE_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


# ffmpeg and ffprobe paths (set absolute paths if not on PATH)
FFMPEG_PATH = "C:\\Users\\bugma\\ffmpeg\\bin\\ffmpeg.exe"
FFPROBE_PATH = "C:\\Users\\bugma\\ffmpeg\\bin\\ffprobe.exe"

# Audio transcode (play time): comma separated list like "flac:mp3,m4a:mp3"
# Only applied to audio playback. Leave empty to stream original audio.
AUDIO_TRANSCODE = ""

# Video auto transcode on download (browser compatibility)
# When enabled, downloaded video files are checked with ffprobe. If codecs are compatible with a browser container,
# Debripod will transmux into mp4 when possible, otherwise it will transcode to mp4.
AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY = True

# If enabled, Debripod deletes the original file after a successful browser compatible output is produced,
# and moves the output into the original folder (typically changing extension to .mp4).
REPLACE_ORIGINAL = True

# Preload next chunk of next file for smoother transitions (audio and video)
PRELOAD_NEXT_FOR_GAPLESS = True
PRELOAD_NEXT_CHUNK_BYTES = 2 * 1024 * 1024

# Where to store transcoded and artwork cache files, as well as logs
CACHE_DIR_NAME = r"_debripod_cache"

# =========================
# Real Debrid settings (including download dir)
# =========================

# Put your Real Debrid API token here (Authorization: Bearer <token>)
REAL_DEBRID_API_KEY = ""
RD_BASE = "https://api.real-debrid.com/rest/1.0"
DOWNLOAD_DIR = r"./data/debrid"  # absolute path on your PC (parent folder)

# =========================
# Soulseek settings
# =========================
# Leave username/password blank to disable Soulseek features.
SOULSEEK_USERNAME = ""
SOULSEEK_PASSWORD = ""
SOULSEEK_DOWNLOAD_DIR = r"./data/soulseek"
# These are local listening ports on your machine. Keep UPNP disabled.
SOULSEEK_LISTENING_PORT = 61000
SOULSEEK_OBFUSCATED_PORT = 0
# Search behavior
SOULSEEK_SEARCH_TIMEOUT_SEC = 8
SOULSEEK_SEARCH_MAX_RESULTS = 5000
SOULSEEK_SEARCH_IDLE_STOP_SEC = 2.5
SOULSEEK_SEARCH_HARD_MAX_SEC = 60

# =========================
# Lastfm settings
# =========================
# Last.fm scrobbling + likes (optional)
# Debripod uses the Last.fm Web Services API (Scrobbling 2.0).
# You need an API key + shared secret, and a user session key (sk).
# After you connect once, Debripod stores the session key in its cache so you do not have to paste it here.
LASTFM_API_KEY = ""
LASTFM_API_SECRET = ""
LASTFM_SESSION_KEY = ""   # optional override; normally loaded from cache after auth
LASTFM_CALLBACK_URL = ""  # optional; leave empty to use desktop flow (no redirect)

# =========================
# Library settings
# =========================
# Configure library roots as a list of "path:mode" strings.
# mode:
#   - "list"  -> browse directories and files (classic folder view)
#   - "meta"  -> browse artists/albums/genres/etc (metadata index view)
#
# If you omit ":mode", it defaults to "list".
LIBRARY_FOLDERS: List[str] = [
    r"./data/debrid:list",
    r"./data/soulseek:meta",
    r"./data/music:meta",
   
]

# =========================
# Runtime config overlay
# =========================
# Values above are safe defaults. User specific settings are loaded from
# config/debripod.json, ~/.config/debripod/config.json, or DEBRIPOD_CONFIG.
try:
    from .config import apply_config_to_module
    apply_config_to_module(globals())
except Exception as _config_error:
    print(f"Debripod config warning: {_config_error}")
configure_library_roots(lambda: LIBRARY_FOLDERS)
configure_real_debrid(
    api_key_provider=lambda: REAL_DEBRID_API_KEY,
    base_url_provider=lambda: RD_BASE,
    timeout_provider=lambda: REQUEST_TIMEOUT_SECONDS,
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
configure_probe(ffprobe_path_provider=lambda: FFPROBE_PATH)
configure_paths(
    download_dir_provider=lambda: DOWNLOAD_DIR,
    cache_dir_name_provider=lambda: CACHE_DIR_NAME,
)
configure_lastfm(
    api_key=LASTFM_API_KEY,
    api_secret=LASTFM_API_SECRET,
    session_key=LASTFM_SESSION_KEY,
    callback_url=LASTFM_CALLBACK_URL,
)

def ensure_dirs() -> None:
    if not os.path.isabs(DOWNLOAD_DIR):
        raise ValueError("DOWNLOAD_DIR must be an absolute path")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(SOULSEEK_DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(soulseek_incoming_dir(), exist_ok=True)
    os.makedirs(cache_dir(), exist_ok=True)
    os.makedirs(transcode_cache_dir(), exist_ok=True)
    os.makedirs(art_cache_dir(), exist_ok=True)

    configure_lastfm(
        api_key=LASTFM_API_KEY,
        api_secret=LASTFM_API_SECRET,
        session_key=LASTFM_SESSION_KEY,
        callback_url=LASTFM_CALLBACK_URL,
        session_cache_path=os.path.join(cache_dir(), "lastfm_session.json"),
        loved_db_path=os.path.join(cache_dir(), "lastfm_loved.json"),
    )
    initialize_lastfm_cache()
    # Best-effort: refresh loved cache occasionally so the UI shows existing likes
    try:
        last_upd = int(lastfm_loved_updated() or 0)
        if lastfm_enabled() and (time.time() - float(last_upd or 0)) > 6 * 3600:
            _lastfm_async(lastfm_sync_loved_from_remote, lastfm_username())
    except Exception:
        pass


configure_search_cache(cache_dir)


def _playlist_rel_from_abs(root_abs: str, abs_path: str) -> Optional[str]:
    try:
        ap = os.path.abspath(abs_path)
        root_abs = os.path.abspath(root_abs)
        common = os.path.commonpath([root_abs, ap])
        if common != root_abs:
            return None
        rel = os.path.relpath(ap, root_abs).replace('\\', '/')
        return '' if rel == '.' else rel
    except Exception:
        return None


def _playlist_resolve_entry(root_abs: str, playlist_abs: str, entry: str) -> Optional[str]:
    raw = str(entry or '').strip().strip('"').strip("'")
    if not raw:
        return None
    low = raw.lower()
    if low.startswith('http://') or low.startswith('https://') or low.startswith('file://'):
        return None

    candidates: List[str] = []
    if os.path.isabs(raw):
        candidates.append(raw)
    else:
        try:
            candidates.append(os.path.join(os.path.dirname(playlist_abs), raw))
        except Exception:
            pass
        try:
            candidates.append(os.path.join(root_abs, raw))
        except Exception:
            pass

    seen = set()
    for cand in candidates:
        try:
            cand_abs = os.path.abspath(cand)
        except Exception:
            continue
        if cand_abs in seen:
            continue
        seen.add(cand_abs)
        if not os.path.exists(cand_abs) or not os.path.isfile(cand_abs):
            continue
        if not is_audio(cand_abs):
            continue
        rel = _playlist_rel_from_abs(root_abs, cand_abs)
        if rel:
            return rel
    return None


def scan_root_playlists(root_abs: str) -> List[dict]:
    out: List[dict] = []
    seen = set()
    root_norm = os.path.abspath(root_abs)
    std_root = os.path.join(root_norm, PLAYLISTS_FOLDER_NAME)
    smart_root = os.path.join(root_norm, SMART_PLAYLISTS_FOLDER_NAME)

    if os.path.isdir(std_root):
        try:
            for dirpath, dirnames, filenames in os.walk(std_root):
                dirnames.sort(key=lambda x: x.lower())
                for fn in sorted(filenames, key=lambda x: x.lower()):
                    ap = os.path.join(dirpath, fn)
                    if not is_playlist_file(ap):
                        continue
                    rel = _playlist_rel_from_abs(root_abs, ap)
                    if not rel or rel in seen:
                        continue
                    seen.add(rel)
                    out.append(
                        {
                            'kind': 'playlist',
                            'label': os.path.splitext(fn)[0] or fn,
                            'rel': rel,
                            'badge': os.path.splitext(fn)[1].lower().lstrip('.'),
                            'smart': False,
                        }
                    )
        except Exception:
            pass

    if os.path.isdir(smart_root):
        try:
            for entry in sorted(os.listdir(smart_root), key=lambda x: x.lower()):
                subdir = os.path.join(smart_root, entry)
                if not os.path.isdir(subdir):
                    continue
                playlist_abs = os.path.join(subdir, SMART_PLAYLIST_MEDIA_FILENAME)
                rules_abs = os.path.join(subdir, SMART_PLAYLIST_RULES_FILENAME)
                if not os.path.isfile(playlist_abs):
                    continue
                rel = _playlist_rel_from_abs(root_abs, playlist_abs)
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                out.append(
                    {
                        'kind': 'playlist',
                        'label': entry,
                        'rel': rel,
                        'badge': 'Smart',
                        'smart': True,
                        'rules_rel': _playlist_rel_from_abs(root_abs, rules_abs) or '',
                    }
                )
        except Exception:
            pass

    out.sort(key=lambda x: (str(x.get('label') or '').lower(), str(x.get('rel') or '').lower()))
    return out


def playlist_tracks_for_root(root_abs: str, playlist_rel: str) -> List[dict]:
    if is_smart_playlist_rel(playlist_rel):
        try:
            root_id = sha1_text(os.path.abspath(root_abs))
        except Exception:
            root_id = ''
        return smart_playlist_tracks_for_root(root_abs, playlist_rel, root_id)
    try:
        playlist_abs = safe_path_join(root_abs, playlist_rel)
    except ValueError:
        return []
    if not os.path.exists(playlist_abs) or not os.path.isfile(playlist_abs) or not is_playlist_file(playlist_abs):
        return []

    ext = os.path.splitext(playlist_abs)[1].lower()
    raw_entries: List[str] = []
    try:
        with open(playlist_abs, 'r', encoding='utf-8-sig', errors='ignore') as f:
            lines = f.read().splitlines()
    except Exception:
        folder_abs, playlist_abs, _, _ = _resolve_smart_playlist_parts(root_abs, playlist_rel)
        if playlist_abs:
            try:
                _write_playlist_entries(playlist_abs, [], root_abs)
            except Exception:
                pass
        return []

    if ext in {'.m3u', '.m3u8'}:
        for line in lines:
            s = (line or '').strip()
            if not s or s.startswith('#'):
                continue
            raw_entries.append(s)
    elif ext == '.pls':
        for line in lines:
            s = (line or '').strip()
            if not s:
                continue
            m = re.match(r'(?i)file\d+\s*=\s*(.+)$', s)
            if m:
                raw_entries.append((m.group(1) or '').strip())

    items: List[dict] = []
    seen = set()
    num = 0
    for entry in raw_entries:
        rel = _playlist_resolve_entry(root_abs, playlist_abs, entry)
        if not rel or rel in seen:
            continue
        seen.add(rel)
        num += 1
        try:
            abs_track = safe_path_join(root_abs, rel)
        except ValueError:
            continue
        label = os.path.splitext(os.path.basename(abs_track))[0] or os.path.basename(abs_track) or 'Track'
        badge = str(num)
        try:
            meta = file_meta_cached(abs_track)
            if isinstance(meta, dict):
                label = (meta.get('title') or meta.get('name') or label)
                if meta.get('track'):
                    badge = str(meta.get('track'))
        except Exception:
            pass
        items.append({'kind': 'track', 'label': label, 'rel': rel, 'badge': badge})

    items.sort(key=lambda x: track_sort_key(x.get('badge') or '') + (x.get('label') or '',))
    return items


def _normalize_new_playlist_name(name: str) -> str:
    s = str(name or '').strip()
    if not s:
        return ''
    s = re.sub(r'[\\/:*?\"<>|\x00-\x1f]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip().rstrip('.')
    if not s:
        return ''
    base, _ = os.path.splitext(s)
    s = (base or s).strip().rstrip('.')
    if not s:
        return ''
    return s + '.m3u8'



def create_root_playlist(root_abs: str, name: str) -> Tuple[bool, str, Dict[str, Any]]:
    filename = _normalize_new_playlist_name(name)
    if not filename:
        return False, 'Enter a playlist name', {}

    folder_abs = os.path.join(root_abs, PLAYLISTS_FOLDER_NAME)
    try:
        os.makedirs(folder_abs, exist_ok=True)
    except Exception as e:
        return False, f'Failed to create playlist folder: {e}', {}

    playlist_abs = os.path.abspath(os.path.join(folder_abs, filename))
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), playlist_abs])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}

    if os.path.exists(playlist_abs):
        rel_existing = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
        label_existing = os.path.splitext(os.path.basename(playlist_abs))[0] or os.path.basename(playlist_abs) or 'Playlist'
        return False, 'Playlist already exists', {'rel': rel_existing, 'label': label_existing}

    body = '#EXTM3U\n'
    try:
        with open(playlist_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
    except Exception as e:
        return False, f'Failed to create playlist: {e}', {}

    rel = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
    label = os.path.splitext(os.path.basename(playlist_abs))[0] or os.path.basename(playlist_abs) or 'Playlist'
    return True, '', {'rel': rel, 'label': label, 'folder': PLAYLISTS_FOLDER_NAME}


def _normalize_playlist_stem(name: str) -> str:
    s = str(name or '').strip()
    if not s:
        return ''
    s = re.sub(r'[\/:*?"<>|\x00-\x1f]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip().rstrip('.')
    if not s:
        return ''
    base, _ = os.path.splitext(s)
    return (base or s).strip().rstrip('.')


def _resolve_playlist_abs(root_abs: str, playlist_rel: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        playlist_abs = safe_path_join(root_abs, playlist_rel)
    except Exception:
        return None, 'Invalid playlist path'
    if not os.path.exists(playlist_abs) or not os.path.isfile(playlist_abs) or not is_playlist_file(playlist_abs):
        return None, 'Playlist not found'
    return playlist_abs, None


def _playlist_rel_entries(root_abs: str, playlist_rel: str) -> List[str]:
    items = playlist_tracks_for_root(root_abs, playlist_rel)
    out: List[str] = []
    seen = set()
    for it in items:
        rel = str((it or {}).get('rel') or '').strip().replace('\\', '/')
        if not rel or rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return out


def _write_playlist_entries(playlist_abs: str, rels: List[str], root_abs: Optional[str] = None) -> None:
    ext = os.path.splitext(playlist_abs)[1].lower()
    clean: List[str] = []
    seen = set()
    playlist_dir = os.path.dirname(os.path.abspath(playlist_abs))
    root_abs_norm = os.path.abspath(root_abs) if root_abs else None
    for rel in rels:
        rp = str(rel or '').strip().replace('\\', '/')
        if not rp or rp in seen:
            continue
        seen.add(rp)
        out_rel = rp
        if root_abs_norm:
            try:
                abs_track = safe_path_join(root_abs_norm, rp)
                out_rel = os.path.relpath(abs_track, playlist_dir).replace('\\', '/')
            except Exception:
                out_rel = rp
        clean.append(out_rel)
    if ext == '.pls':
        lines = ['[playlist]']
        for idx, rel in enumerate(clean, 1):
            title = os.path.splitext(os.path.basename(rel))[0] or f'Track {idx}'
            lines.append(f'File{idx}={rel}')
            lines.append(f'Title{idx}={title}')
            lines.append(f'Length{idx}=-1')
        lines.append(f'NumberOfEntries={len(clean)}')
        lines.append('Version=2')
        body = '\n'.join(lines) + '\n'
    else:
        body = '\n'.join(['#EXTM3U'] + clean) + '\n'
    with open(playlist_abs, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)


def rename_root_playlist(root_abs: str, playlist_rel: str, name: str) -> Tuple[bool, str, Dict[str, Any]]:
    stem = _normalize_playlist_stem(name)
    if not stem:
        return False, 'Enter a playlist name', {}
    playlist_abs, err = _resolve_playlist_abs(root_abs, playlist_rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    ext = os.path.splitext(playlist_abs)[1] or '.m3u8'
    new_abs = os.path.abspath(os.path.join(os.path.dirname(playlist_abs), stem + ext))
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), new_abs])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}
    if os.path.normcase(new_abs) == os.path.normcase(playlist_abs):
        rel_same = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
        label_same = os.path.splitext(os.path.basename(playlist_abs))[0] or os.path.basename(playlist_abs) or 'Playlist'
        return True, '', {'rel': rel_same, 'label': label_same}
    if os.path.exists(new_abs):
        rel_existing = _playlist_rel_from_abs(root_abs, new_abs) or ''
        label_existing = os.path.splitext(os.path.basename(new_abs))[0] or os.path.basename(new_abs) or 'Playlist'
        return False, 'Playlist already exists', {'rel': rel_existing, 'label': label_existing}
    try:
        os.replace(playlist_abs, new_abs)
    except Exception as e:
        return False, f'Failed to rename playlist: {e}', {}
    rel_new = _playlist_rel_from_abs(root_abs, new_abs) or ''
    label_new = os.path.splitext(os.path.basename(new_abs))[0] or os.path.basename(new_abs) or 'Playlist'
    return True, '', {'rel': rel_new, 'label': label_new}


def add_tracks_to_playlist(root_abs: str, playlist_rel: str, rels: List[str]) -> Tuple[bool, str, Dict[str, Any]]:
    playlist_abs, err = _resolve_playlist_abs(root_abs, playlist_rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    existing = _playlist_rel_entries(root_abs, playlist_rel)
    added = 0
    for rel in rels or []:
        rp = str(rel or '').strip().replace('\\', '/')
        if not rp:
            continue
        try:
            abs_track = safe_path_join(root_abs, rp)
        except Exception:
            continue
        if not os.path.exists(abs_track) or not os.path.isfile(abs_track) or not is_audio(abs_track):
            continue
        if rp not in existing:
            existing.append(rp)
            added += 1
    if added <= 0:
        return False, 'No songs added', {'added': 0}
    try:
        _write_playlist_entries(playlist_abs, existing, root_abs)
    except Exception as e:
        return False, f'Failed to update playlist: {e}', {'added': 0}
    return True, '', {'added': added}


def remove_tracks_from_playlist(root_abs: str, playlist_rel: str, rels: List[str]) -> Tuple[bool, str, Dict[str, Any]]:
    playlist_abs, err = _resolve_playlist_abs(root_abs, playlist_rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    remove_set = {str(rel or '').strip().replace('\\', '/') for rel in (rels or []) if str(rel or '').strip()}
    existing = _playlist_rel_entries(root_abs, playlist_rel)
    kept = [rel for rel in existing if rel not in remove_set]
    removed = max(0, len(existing) - len(kept))
    if removed <= 0:
        return False, 'No songs removed', {'removed': 0}
    try:
        _write_playlist_entries(playlist_abs, kept, root_abs)
    except Exception as e:
        return False, f'Failed to update playlist: {e}', {'removed': 0}
    return True, '', {'removed': removed}




def delete_root_playlist(root_abs: str, playlist_rel: str) -> Tuple[bool, str, Dict[str, Any]]:
    rel = str(playlist_rel or '').strip().replace('\\', '/')
    if not rel:
        return False, 'Playlist not found', {}

    if is_smart_playlist_rel(rel):
        folder_abs, playlist_abs, rules_abs, _ = _resolve_smart_playlist_parts(root_abs, rel)
        if not folder_abs or not playlist_abs or not rules_abs:
            return False, 'Smart playlist not found', {}
        try:
            common = os.path.commonpath([os.path.abspath(root_abs), os.path.abspath(folder_abs)])
            if common != os.path.abspath(root_abs):
                return False, 'Invalid playlist path', {}
        except Exception:
            return False, 'Invalid playlist path', {}
        try:
            shutil.rmtree(folder_abs)
        except Exception as e:
            return False, f'Failed to delete playlist: {e}', {}
        return True, '', {'smart': True}

    playlist_abs, err = _resolve_playlist_abs(root_abs, rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), os.path.abspath(playlist_abs)])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}
    try:
        os.remove(playlist_abs)
    except Exception as e:
        return False, f'Failed to delete playlist: {e}', {}
    return True, '', {'smart': False}


def _smart_playlist_dir_from_name(root_abs: str, name: str) -> Tuple[Optional[str], str, str]:
    stem = _normalize_playlist_stem(name)
    if not stem:
        return None, '', 'Enter a playlist name'
    folder_abs = os.path.join(root_abs, SMART_PLAYLISTS_FOLDER_NAME, stem)
    return folder_abs, stem, ''


def _default_smart_playlist_rules(name: str) -> str:
    stem = _normalize_playlist_stem(name) or 'Playlist'
    body = SMART_PLAYLIST_RULES_TEMPLATE
    body = re.sub(r'^\[name\]\s*$', f'[{stem}]', body, count=1, flags=re.MULTILINE)
    return body


def is_smart_playlist_rel(playlist_rel: str) -> bool:
    rel = str(playlist_rel or '').replace('\\', '/').strip('/')
    low = rel.lower()
    pref = SMART_PLAYLISTS_FOLDER_NAME.lower() + '/'
    return bool(low == SMART_PLAYLISTS_FOLDER_NAME.lower() or low.startswith(pref))


def _resolve_smart_playlist_parts(root_abs: str, playlist_rel: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    try:
        playlist_abs = safe_path_join(root_abs, playlist_rel)
    except Exception:
        return None, None, None, None
    if not os.path.isfile(playlist_abs):
        return None, None, None, None
    folder_abs = os.path.dirname(playlist_abs)
    rules_abs = os.path.join(folder_abs, SMART_PLAYLIST_RULES_FILENAME)
    if not os.path.isfile(rules_abs):
        return None, None, None, None
    rel = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
    rules_rel = _playlist_rel_from_abs(root_abs, rules_abs) or ''
    return folder_abs, playlist_abs, rules_abs, rules_rel


def create_root_smart_playlist(root_abs: str, name: str) -> Tuple[bool, str, Dict[str, Any]]:
    folder_abs, stem, err = _smart_playlist_dir_from_name(root_abs, name)
    if not folder_abs:
        return False, err, {}
    playlist_abs = os.path.join(folder_abs, SMART_PLAYLIST_MEDIA_FILENAME)
    rules_abs = os.path.join(folder_abs, SMART_PLAYLIST_RULES_FILENAME)
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), os.path.abspath(folder_abs)])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}
    if os.path.exists(folder_abs):
        rel_existing = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
        return False, 'Playlist already exists', {'rel': rel_existing, 'label': stem, 'smart': True}
    try:
        os.makedirs(folder_abs, exist_ok=True)
        with open(rules_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write(_default_smart_playlist_rules(stem))
        with open(playlist_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write('#EXTM3U\n')
    except Exception as e:
        return False, f'Failed to create smart playlist: {e}', {}
    rel = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
    return True, '', {'rel': rel, 'label': stem, 'folder': SMART_PLAYLISTS_FOLDER_NAME, 'smart': True}


def load_smart_playlist_rules(root_abs: str, playlist_rel: str) -> Tuple[bool, str, Dict[str, Any]]:
    folder_abs, playlist_abs, rules_abs, rules_rel = _resolve_smart_playlist_parts(root_abs, playlist_rel)
    if not rules_abs:
        return False, 'Smart playlist not found', {}
    try:
        with open(rules_abs, 'r', encoding='utf-8-sig', errors='ignore') as f:
            body = f.read()
    except Exception as e:
        return False, f'Failed to read rules: {e}', {}
    label = os.path.basename(folder_abs) if folder_abs else 'Smart Playlist'
    return True, '', {'text': body, 'rel': _playlist_rel_from_abs(root_abs, playlist_abs) or playlist_rel, 'rules_rel': rules_rel or '', 'label': label}


def save_smart_playlist_rules(root_abs: str, playlist_rel: str, text: str) -> Tuple[bool, str, Dict[str, Any]]:
    folder_abs, playlist_abs, rules_abs, rules_rel = _resolve_smart_playlist_parts(root_abs, playlist_rel)
    if not rules_abs:
        return False, 'Smart playlist not found', {}
    body = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    if not body.endswith('\n'):
        body += '\n'
    try:
        with open(rules_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
    except Exception as e:
        return False, f'Failed to save rules: {e}', {}
    try:
        smart_playlist_tracks_for_root(root_abs, playlist_rel)
    except Exception:
        pass
    label = os.path.basename(folder_abs) if folder_abs else 'Smart Playlist'
    return True, '', {'rel': _playlist_rel_from_abs(root_abs, playlist_abs) or playlist_rel, 'rules_rel': rules_rel or '', 'label': label}


def _smart_rule_values(raw: str) -> List[str]:
    out: List[str] = []
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', raw or ''):
        try:
            out.append(bytes(m.group(1), 'utf-8').decode('unicode_escape'))
        except Exception:
            out.append(m.group(1))
    if out:
        return out
    inner = str(raw or '').strip()
    if inner.startswith('(') and inner.endswith(')'):
        inner = inner[1:-1]
    for part in inner.split(','):
        part = str(part or '').strip().strip('"').strip("'")
        if part:
            out.append(part)
    return out


def _parse_smart_rule_line(line: str) -> Optional[Dict[str, Any]]:
    s = str(line or '').strip()
    if not s:
        return None
    if s.startswith('#'):
        s = s[1:].strip()
        active = False
    else:
        active = True
    m = re.match(r'(?i)^([a-z_]+)(?:\((is|not)\))?\s*=\s*(\(.*\))\s*$', s)
    if not m:
        return None
    field = (m.group(1) or '').strip().lower()
    op = (m.group(2) or '').strip().lower()
    vals = _smart_rule_values(m.group(3) or '')
    if field == 'liked':
        vv = str(vals[0] if vals else '').strip().lower()
        if vv not in ('true', 'false', '1', '0', 'yes', 'no'):
            return None
        vals = ['true' if vv in ('true', '1', 'yes') else 'false']
    return {'type': 'rule', 'active': active, 'field': field, 'op': op or ('is' if field != 'liked' else ''), 'values': vals}


def _parse_smart_block(lines: List[str], idx: int) -> Tuple[Optional[Dict[str, Any]], int]:
    mode = 'any'
    while idx < len(lines):
        raw = lines[idx]
        s = str(raw or '').strip()
        if not s:
            idx += 1
            continue
        if s.startswith('#'):
            test = s[1:].strip()
        else:
            test = s
        m = re.match(r'^\[?(any|all)\]?\s*\{\s*$', test, re.I)
        if not m:
            return None, idx
        mode = (m.group(1) or 'any').lower()
        active = not s.startswith('#')
        idx += 1
        break
    node = {'type': 'group', 'mode': mode, 'active': active, 'items': []}
    while idx < len(lines):
        raw = lines[idx]
        s = str(raw or '').strip()
        if not s:
            idx += 1
            continue
        if s == '}':
            idx += 1
            return node, idx
        test = s[1:].strip() if s.startswith('#') else s
        if re.match(r'^\[?(any|all)\]?\s*\{\s*$', test, re.I):
            child, idx = _parse_smart_block(lines, idx)
            if child:
                node['items'].append(child)
            else:
                idx += 1
            continue
        rule = _parse_smart_rule_line(s)
        if rule:
            node['items'].append(rule)
        idx += 1
    return node, idx


def parse_smart_playlist_rules_text(text: str) -> Dict[str, Any]:
    lines = str(text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    idx = 0
    name = ''
    while idx < len(lines):
        s = str(lines[idx] or '').strip()
        if not s:
            idx += 1
            continue
        m = re.match(r'^\[(.*)\]\s*$', s)
        if m:
            name = (m.group(1) or '').strip()
            idx += 1
        break
    group, _ = _parse_smart_block(lines, idx)
    if not group:
        raise RuntimeError('Invalid smart playlist rules')
    return {'name': name, 'root': group}


def _smart_text_value(v: Any) -> str:
    return str(v or '').strip().lower()


def _smart_folder_match(track_rel: str, folder_rule: str) -> bool:
    rel = '/' + str(track_rel or '').replace('\\', '/').lstrip('/')
    folder = '/' + str(folder_rule or '').replace('\\', '/').strip()
    folder = '/' + folder.strip('/') if folder.strip('/') else '/'
    if folder == '/':
        return True
    base = folder.rstrip('/')
    return rel == base or rel.startswith(base + '/')


def _smart_rule_match(rule: Dict[str, Any], track: Dict[str, Any]) -> bool:
    field = str(rule.get('field') or '').lower()
    values = list(rule.get('values') or [])
    op = str(rule.get('op') or 'is').lower()
    if field == 'liked':
        want = str(values[0] if values else 'false').strip().lower() == 'true'
        got = False
        try:
            got = lastfm_is_loved(str(track.get('artist') or ''), str(track.get('title') or ''), str(track.get('album') or ''))
        except Exception:
            got = False
        return got == want
    if field == 'folder':
        got_rel = str(track.get('rel') or '')
        matched = any(_smart_folder_match(got_rel, v) for v in values) if values else False
        return (not matched) if op == 'not' else matched
    track_val = ''
    if field == 'artist':
        track_val = _smart_text_value(track.get('artist'))
    elif field == 'albumartist':
        track_val = _smart_text_value(track.get('album_artist') or track.get('artist'))
    elif field == 'album':
        track_val = _smart_text_value(track.get('album'))
    elif field == 'genre':
        track_val = _smart_text_value(track.get('genre'))
    else:
        return False
    vals = {_smart_text_value(v) for v in values if str(v or '').strip()}
    matched = track_val in vals if vals else False
    return (not matched) if op == 'not' else matched


def _smart_group_match(node: Dict[str, Any], track: Dict[str, Any]) -> bool:
    if not node:
        return False
    if not bool(node.get('active', True)):
        return False

    results: List[bool] = []
    for item in node.get('items') or []:
        if not bool(item.get('active', True)):
            continue
        if item.get('type') == 'group':
            results.append(_smart_group_match(item, track))
        elif item.get('type') == 'rule':
            results.append(_smart_rule_match(item, track))

    # If nothing is active in this group, it matches nothing.
    if not results:
        return False

    return any(results) if str(node.get('mode') or 'any').lower() == 'any' else all(results)


def smart_playlist_tracks_for_root(root_abs: str, playlist_rel: str, root_id: str = '') -> List[dict]:
    ok, err, info = load_smart_playlist_rules(root_abs, playlist_rel)
    if not ok:
        return []
    text = str((info or {}).get('text') or '')
    try:
        parsed = parse_smart_playlist_rules_text(text)
    except Exception:
        folder_abs, playlist_abs, _, _ = _resolve_smart_playlist_parts(root_abs, playlist_rel)
        if playlist_abs:
            try:
                _write_playlist_entries(playlist_abs, [], root_abs)
            except Exception:
                pass
        return []
    data = get_index(root_id) if root_id else None
    if data is None:
        data = build_index_for_root(root_abs)
        if root_id:
            with INDEX_LOCK:
                INDEX_CACHE[root_id] = (time.time(), data)
    tracks = list((data or {}).get('tracks') or [])
    matched = [t for t in tracks if _smart_group_match(parsed.get('root') or {}, t)]
    matched.sort(key=lambda x: track_sort_key(x.get('track') or '') + ((x.get('artist') or '').lower(), (x.get('album') or '').lower(), (x.get('title') or x.get('name') or '').lower()))
    items: List[dict] = []
    for idx, t in enumerate(matched, 1):
        rel = str(t.get('rel') or '').strip().replace('\\', '/')
        if not rel:
            continue
        label = str(t.get('title') or t.get('name') or os.path.splitext(os.path.basename(rel))[0] or 'Track')
        badge = str(t.get('track') or idx)
        items.append({'kind': 'track', 'label': label, 'rel': rel, 'badge': badge})
    folder_abs, playlist_abs, _, _ = _resolve_smart_playlist_parts(root_abs, playlist_rel)
    if playlist_abs:
        try:
            _write_playlist_entries(playlist_abs, [str(t.get('rel') or '') for t in matched], root_abs)
        except Exception:
            pass
    return items


def parse_audio_transcode_rules() -> List[Tuple[str, str]]:
    rules = []
    for part in (AUDIO_TRANSCODE or "").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        a, b = part.split(":", 1)
        a = a.strip().lower().lstrip(".")
        b = b.strip().lower().lstrip(".")
        if a and b:
            rules.append((a, b))
    return rules


AUDIO_TRANSCODE_RULES_PARSED = parse_audio_transcode_rules()
TRANSCODE_LOCKS: Dict[str, threading.Lock] = {}
TRANSCODE_LOCKS_GUARD = threading.Lock()


def lock_for_key(key: str) -> threading.Lock:
    with TRANSCODE_LOCKS_GUARD:
        lk = TRANSCODE_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            TRANSCODE_LOCKS[key] = lk
        return lk


FFMPEG_ENCODERS_CACHE: Optional[set] = None
FFMPEG_ENCODERS_CACHE_AT: float = 0.0
FFMPEG_ENCODERS_CACHE_TTL_SECONDS: float = 300.0


def _ffmpeg_encoders() -> set:
    """Return a set of encoder names supported by the configured ffmpeg."""
    global FFMPEG_ENCODERS_CACHE, FFMPEG_ENCODERS_CACHE_AT
    now = time.time()
    if FFMPEG_ENCODERS_CACHE is not None and (now - FFMPEG_ENCODERS_CACHE_AT) < FFMPEG_ENCODERS_CACHE_TTL_SECONDS:
        return FFMPEG_ENCODERS_CACHE

    code, out, err = run_cmd([FFMPEG_PATH, "-hide_banner", "-encoders"])
    enc: set = set()
    if code == 0 and out:
        for line in (out or "").splitlines():
            line = line.strip()
            if not line or line.startswith("--") or line.startswith("Encoders:"):
                continue
            # Typical line: " V..... h264_nvenc NVIDIA NVENC H.264 encoder"
            parts = line.split()
            if len(parts) >= 2 and re.match(r"^[A-Za-z0-9_]+$", parts[1]):
                enc.add(parts[1])
    else:
        # If this fails, keep cache empty and allow CPU fallback paths.
        enc = set()

    FFMPEG_ENCODERS_CACHE = enc
    FFMPEG_ENCODERS_CACHE_AT = now
    return enc


def _safe_remove(p: str) -> None:
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except OSError:
        pass


def ffmpeg_log_dir() -> str:
    p = os.path.join(cache_dir(), "ffmpeg_logs")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


_LAST_FFMPEG_LOCK = threading.Lock()
_LAST_FFMPEG_ERROR: Dict[str, str] = {}


def _cmdline_for_log(args: List[str]) -> str:
    try:
        return subprocess.list2cmdline(args)
    except Exception:
        return " ".join(args)


def _record_ffmpeg_failure(stage: str, args: List[str], code: int, out: str, err: str, src_path: str, tmp_path: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    key = sha1_text(f"{src_path}|{tmp_path}|{stage}|{ts}|{uuid.uuid4().hex}")
    log_path = os.path.join(ffmpeg_log_dir(), f"{ts}_{stage}_{key[:10]}.log")
    body = []
    body.append(f"timestamp: {ts}")
    body.append(f"stage: {stage}")
    body.append(f"src: {src_path}")
    body.append(f"tmp: {tmp_path}")
    body.append(f"exit_code: {code}")
    body.append("")
    body.append("command:")
    body.append(_cmdline_for_log(args))
    body.append("")
    if out:
        body.append("stdout:")
        body.append(out)
        body.append("")
    if err:
        body.append("stderr:")
        body.append(err)
        body.append("")
    try:
        with open(log_path, "w", encoding="utf-8", errors="ignore") as f:
            f.write("\n".join(body))
    except OSError:
        log_path = ""

    with _LAST_FFMPEG_LOCK:
        _LAST_FFMPEG_ERROR.clear()
        _LAST_FFMPEG_ERROR.update(
            {
                "timestamp": ts,
                "stage": stage,
                "src": src_path,
                "tmp": tmp_path,
                "exit_code": str(code),
                "command": _cmdline_for_log(args),
                "log_path": log_path,
                "stderr_tail": (err or "")[-2000:],
            }
        )

    return log_path


def last_ffmpeg_error() -> Dict[str, str]:
    with _LAST_FFMPEG_LOCK:
        return dict(_LAST_FFMPEG_ERROR)


def _run_ffmpeg_to_tmp(args: List[str], tmp_path: str, *, stage: str, src_path: str) -> Tuple[bool, str]:
    code, out, err = run_cmd(args)
    if code == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
        return True, ""
    _safe_remove(tmp_path)
    log_path = _record_ffmpeg_failure(stage, args, code, out, err, src_path, tmp_path)
    msg = (err or "").strip() or "ffmpeg failed"
    if log_path:
        msg = msg + f"\nLog saved to: {log_path}"
    msg = msg + f"\nCache dir: {transcode_cache_dir()}"
    return False, msg




def _is_audio_ext(ext_no_dot: str) -> bool:
    e = "." + (ext_no_dot or "").lower().lstrip(".")
    return e in AUDIO_EXTS and e not in VIDEO_EXTS


def _pick_video_encoder_for_target(target_ext_no_dot: str) -> Tuple[str, List[str]]:
    """Pick a video encoder for the requested container extension, preferring GPU if available."""
    target = (target_ext_no_dot or "").lower().lstrip(".")
    enc = _ffmpeg_encoders()

    # For webm, prefer AV1 hardware if available, otherwise VP9 CPU fallback.
    if target == "webm":
        for name in ["av1_nvenc", "av1_qsv", "av1_amf"]:
            if name in enc:
                return name, []
        return "libvpx-vp9", ["-b:v", "0", "-crf", "32"]

    # Default: H.264 for broad compatibility.
    for name in ["h264_nvenc", "h264_qsv", "h264_amf"]:
        if name in enc:
            return name, []
    return "libx264", ["-preset", "veryfast", "-crf", "23"]


def _pick_audio_encoder_for_target(target_ext_no_dot: str) -> Tuple[str, List[str]]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    if target == "mp3":
        return "libmp3lame", ["-b:a", "192k"]
    if target in ("m4a", "mp4", "m4v", "mov", "aac"):
        return "aac", ["-b:a", "192k"]
    if target == "opus":
        return "libopus", ["-b:a", "128k"]
    if target == "ogg":
        return "libvorbis", ["-q:a", "5"]
    if target == "flac":
        return "flac", []
    if target == "wav":
        return "pcm_s16le", []
    return "aac", ["-b:a", "192k"]


def _build_transmux_args(src_path: str, target_ext_no_dot: str, tmp_path: str, *, first_audio_only: bool = False) -> List[str]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    audio_only = _is_audio_ext(target)
    args = [FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error", "-i", src_path]

    if audio_only:
        # Keep only audio for audio targets.
        # (If the source audio codec is incompatible with the target container, this will fail and we will fall back.)
        args += ["-vn", "-sn", "-dn", "-c:a", "copy"]
        args += [tmp_path]
        return args

    # Video targets: be conservative about what we copy.
    # Mapping "0" would include subtitles, attachments, and data streams which commonly make mp4/mov remux fail.
    args += ["-map", "0:v:0"]
    if first_audio_only:
        args += ["-map", "0:a:0?"]
    else:
        args += ["-map", "0:a?"]
    args += ["-sn", "-dn", "-c", "copy"]

    if target in ("mp4", "m4v", "mov"):
        args += ["-movflags", "+faststart"]

    args += [tmp_path]
    return args


def _build_transcode_args(src_path: str, target_ext_no_dot: str, tmp_path: str) -> List[str]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    audio_only = _is_audio_ext(target)

    args = [FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error", "-i", src_path]

    if audio_only:
        aenc, aextra = _pick_audio_encoder_for_target(target)
        args += ["-vn", "-sn", "-dn", "-c:a", aenc] + aextra
        args += [tmp_path]
        return args

    venc, vextra = _pick_video_encoder_for_target(target)
    aenc, aextra = _pick_audio_encoder_for_target("opus" if target == "webm" else "aac")

    args += ["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn"]
    args += ["-c:v", venc]

    if venc == "h264_nvenc":
        args += ["-preset", "p5", "-rc", "vbr", "-cq", "23"]
    elif venc == "h264_qsv":
        args += ["-global_quality", "23"]
    elif venc == "h264_amf":
        args += ["-quality", "balanced", "-qp_i", "23", "-qp_p", "23"]
    elif venc == "libx264":
        args += vextra
    elif venc == "libvpx-vp9":
        args += vextra

    # Compatibility pixel format for most browsers/players.
    args += ["-pix_fmt", "yuv420p"]

    args += ["-c:a", aenc] + aextra

    if target in ("mp4", "m4v", "mov"):
        args += ["-movflags", "+faststart"]

    args += [tmp_path]
    return args



def _primary_stream_info(path: str) -> dict:
    """
    Return info about the first video stream and first audio stream (if present).
    Uses ffprobe for reliable codec detection.
    """
    info = {"v_codec": None, "v_pix_fmt": None, "a_codec": None}
    try:
        j = ffprobe_json(path)
    except Exception:
        return info

    streams = j.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if v:
        info["v_codec"] = (v.get("codec_name") or "").lower() or None
        info["v_pix_fmt"] = (v.get("pix_fmt") or "").lower() or None
    if a:
        info["a_codec"] = (a.get("codec_name") or "").lower() or None
    return info


def _browser_compatible_for_target(target_ext_no_dot: str, v_codec: Optional[str], v_pix_fmt: Optional[str], a_codec: Optional[str]) -> Tuple[bool, bool]:
    """
    Return (video_ok, audio_ok) for broad HTML5 playback in common desktop browsers.

    For MP4/MOV/M4V we assume:
      - Video should be H.264 (h264) with yuv420p for maximum compatibility (Firefox, Chromium, Safari).
      - Audio should be AAC (aac) (mp3-in-mp4 is inconsistent across stacks).
    For WEBM we assume:
      - Video vp8/vp9/av1
      - Audio opus/vorbis
    """
    target = (target_ext_no_dot or "").lower().lstrip(".")

    # Audio-only targets: caller will handle separately.
    if _is_audio_ext(target):
        return True, True

    if target in ("mp4", "m4v", "mov"):
        video_ok = (v_codec == "h264") and (v_pix_fmt in (None, "", "yuv420p"))
        audio_ok = (a_codec is None) or (a_codec == "aac")
        return video_ok, audio_ok

    if target == "webm":
        video_ok = (v_codec in (None, "", "vp8", "vp9", "av1"))
        audio_ok = (a_codec is None) or (a_codec in ("opus", "vorbis"))
        return video_ok, audio_ok

    # Unknown container: be conservative (force transcode).
    return False, False


def _build_smart_transcode_args(src_path: str, target_ext_no_dot: str, tmp_path: str, *, video_ok: bool, audio_ok: bool) -> List[str]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    audio_only = _is_audio_ext(target)

    args = [FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error", "-i", src_path]

    if audio_only:
        # For audio targets, if we got here we need an actual transcode (or a container-specific rewrap elsewhere).
        aenc, aextra = _pick_audio_encoder_for_target(target)
        args += ["-vn", "-sn", "-dn", "-c:a", aenc] + aextra
        args += [tmp_path]
        return args

    # Map first video and first audio for browser playback reliability.
    # (Most browsers won't let you choose tracks in a simple <video> element anyway.)
    args += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]

    if video_ok:
        args += ["-c:v", "copy"]
    else:
        venc, vextra = _pick_video_encoder_for_target(target)
        args += ["-c:v", venc]
        if venc == "h264_nvenc":
            args += ["-preset", "p5", "-rc", "vbr", "-cq", "23"]
        elif venc == "h264_qsv":
            args += ["-global_quality", "23"]
        elif venc == "h264_amf":
            args += ["-quality", "balanced", "-qp_i", "23", "-qp_p", "23"]
        else:
            args += vextra

        # Compatibility pixel format for browsers.
        args += ["-pix_fmt", "yuv420p"]

    if audio_ok:
        args += ["-c:a", "copy"]
    else:
        # For webm default to opus, else aac.
        a_target = "opus" if target == "webm" else "aac"
        aenc, aextra = _pick_audio_encoder_for_target(a_target)
        args += ["-c:a", aenc] + aextra

    if target in ("mp4", "m4v", "mov"):
        args += ["-movflags", "+faststart"]

    args += [tmp_path]
    return args



def audio_transcode_if_needed(src_path: str) -> str:
    """Apply AUDIO_TRANSCODE rules as a cacheable pipeline, triggered at play time.

    AUDIO_TRANSCODE is a comma separated list like "flac:mp3,alac:m4a".
    Transmux (stream copy) is attempted first, then a full audio transcode.
    """
    ext = os.path.splitext(src_path)[1].lower().lstrip(".")
    for a, b in AUDIO_TRANSCODE_RULES_PARSED:
        if ext != a:
            continue

        key = sha1_text(os.path.abspath(src_path) + "|" + a + "->" + b)
        out_path = os.path.join(transcode_cache_dir(), f"{key}.{b}")
        lk = lock_for_key(out_path)

        with lk:
            try:
                src_m = os.path.getmtime(src_path)
            except OSError:
                return src_path

            if os.path.exists(out_path):
                try:
                    out_m = os.path.getmtime(out_path)
                    if out_m >= src_m and os.path.getsize(out_path) > 0:
                        return out_path
                except OSError:
                    pass

            base_tmp, ext_tmp = os.path.splitext(out_path)
            tmp_path = base_tmp + ".tmp" + ext_tmp
            _safe_remove(tmp_path)

            # 1) Try transmux (copy audio) first.
            transmux_args = _build_transmux_args(src_path, b, tmp_path, first_audio_only=True)
            ok1, err1 = _run_ffmpeg_to_tmp(transmux_args, tmp_path, stage="audio_transmux", src_path=src_path)
            if ok1:
                os.replace(tmp_path, out_path)
                return out_path

            _safe_remove(tmp_path)

            # 2) Fall back to full transcode.
            trans_args = _build_transcode_args(src_path, b, tmp_path)
            ok2, err2 = _run_ffmpeg_to_tmp(trans_args, tmp_path, stage="audio_transcode", src_path=src_path)
            if ok2:
                os.replace(tmp_path, out_path)
                return out_path

            raise RuntimeError((err2 or err1 or "ffmpeg failed").strip())

    return src_path


def transcode_if_needed(src_path: str) -> str:
    """Backwards compatible entry point used by the existing streaming routes.

    Audio: uses AUDIO_TRANSCODE at play time.
    Video: never transcodes at play time; prefers an already created browser compatible sibling output.
    """
    if is_audio(src_path):
        return audio_transcode_if_needed(src_path)

    if is_video(src_path):
        base, _ = os.path.splitext(src_path)
        # Prefer the download time browser compatible output when present.
        cand = base + "." + VIDEO_BROWSER_TARGET_EXT
        if os.path.exists(cand) and os.path.isfile(cand):
            return cand
        cand2 = base + ".browser." + VIDEO_BROWSER_TARGET_EXT
        if os.path.exists(cand2) and os.path.isfile(cand2):
            return cand2
        return src_path

    return src_path
# =========================
# =========================
# YouTube search and yt-dlp integration
# =========================

import xml.etree.ElementTree as ET


def _youtube_watch_url(video_id: str) -> str:
    vid = str(video_id or "").strip()
    return f"{YOUTUBE_WEB_BASE}/watch?v={vid}" if vid else ""


def _youtube_channel_url(channel_id: str = "", handle: str = "", browse_url: str = "") -> str:
    if browse_url:
        if browse_url.startswith('http://') or browse_url.startswith('https://'):
            return browse_url
        return YOUTUBE_WEB_BASE + browse_url
    h = str(handle or '').strip()
    cid = str(channel_id or '').strip()
    if h:
        return YOUTUBE_WEB_BASE + ('/' + h.lstrip('@') if h.startswith('/') else ('/' + h if h.startswith('@') else '/@' + h))
    if cid:
        return f"{YOUTUBE_WEB_BASE}/channel/{cid}"
    return YOUTUBE_WEB_BASE


def _extract_json_object_from_html(html: str, anchor: str) -> Optional[dict]:
    idx = html.find(anchor)
    if idx < 0:
        return None
    start = html.find('{', idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i+1])
                except Exception:
                    return None
    return None


def _iter_nested_values(obj: Any, key: str):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _iter_nested_values(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_nested_values(v, key)


def _youtube_text_runs(node: Any) -> str:
    if isinstance(node, dict):
        if isinstance(node.get('simpleText'), str):
            return node.get('simpleText') or ''
        runs = node.get('runs')
        if isinstance(runs, list):
            return ''.join(str(r.get('text') or '') for r in runs if isinstance(r, dict))
    if isinstance(node, list):
        return ''.join(_youtube_text_runs(x) for x in node)
    return str(node or '')


def _youtube_parse_video_renderer(vr: dict) -> Optional[dict]:
    if not isinstance(vr, dict):
        return None
    video_id = str(vr.get('videoId') or '').strip()
    if not video_id:
        return None
    title = _youtube_text_runs(vr.get('title')) or 'YouTube video'
    owner = _youtube_text_runs(vr.get('ownerText') or vr.get('longBylineText') or vr.get('shortBylineText'))
    length = _youtube_text_runs(vr.get('lengthText'))
    published = _youtube_text_runs(vr.get('publishedTimeText'))
    view_count = _youtube_text_runs(vr.get('viewCountText'))
    owner_runs = None
    for k in ('ownerText', 'longBylineText', 'shortBylineText'):
        cur = vr.get(k)
        if isinstance(cur, dict) and isinstance(cur.get('runs'), list) and cur.get('runs'):
            owner_runs = cur.get('runs')
            break
    channel_id = ''
    browse_url = ''
    handle = ''
    if owner_runs:
        run0 = owner_runs[0] if isinstance(owner_runs[0], dict) else {}
        nav = run0.get('navigationEndpoint') or {}
        browse = nav.get('browseEndpoint') or {}
        channel_id = str(browse.get('browseId') or '').strip()
        browse_url = str((browse.get('canonicalBaseUrl') or '')).strip()
        if browse_url.startswith('/@'):
            handle = browse_url[2:]
    thumb = ''
    thumbs = (((vr.get('thumbnail') or {}).get('thumbnails')) or [])
    if isinstance(thumbs, list) and thumbs:
        thumb = str((thumbs[-1] or {}).get('url') or '')
    return {
        'video_id': video_id,
        'url': _youtube_watch_url(video_id),
        'title': title,
        'channel': owner,
        'channel_id': channel_id,
        'channel_url': _youtube_channel_url(channel_id, handle, browse_url),
        'browse_url': browse_url,
        'handle': handle,
        'length': length,
        'published': published,
        'view_count': view_count,
        'thumbnail': thumb,
    }


def youtube_search(query: str, limit: int = YOUTUBE_SEARCH_LIMIT) -> List[dict]:
    q = str(query or '').strip()
    if not q:
        return []
    url = YOUTUBE_WEB_BASE + '/results?search_query=' + quote(q)
    resp = requests.get(url, headers=YOUTUBE_REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = _extract_json_object_from_html(resp.text, 'var ytInitialData =') or _extract_json_object_from_html(resp.text, 'ytInitialData =')
    if not isinstance(data, dict):
        return []
    out: List[dict] = []
    seen = set()
    for vr in _iter_nested_values(data, 'videoRenderer'):
        item = _youtube_parse_video_renderer(vr)
        if not item:
            continue
        vid = item.get('video_id') or ''
        if vid in seen:
            continue
        seen.add(vid)
        out.append(item)
        if len(out) >= int(limit or YOUTUBE_SEARCH_LIMIT):
            break
    return out


def _youtube_channel_feed_url(channel_id: str) -> str:
    return f'{YOUTUBE_WEB_BASE}/feeds/videos.xml?channel_id={quote(str(channel_id or "").strip())}'


def _youtube_format_upload_date(raw: Any) -> str:
    s = str(raw or '').strip()
    if len(s) == 8 and s.isdigit():
        return f'{s[0:4]}-{s[4:6]}-{s[6:8]}'
    return s


def _youtube_channel_entries_from_ytdlp(channel_id: str, limit: int = YOUTUBE_CHANNEL_BROWSE_LIMIT) -> List[dict]:
    cid = str(channel_id or '').strip()
    if not cid:
        return []
    args = ['-J', '--flat-playlist', '--playlist-items', '1:2147483647', _youtube_channel_url(cid) + '/videos']
    code, out, err = _run_ytdlp(args)
    if code != 0:
        raise RuntimeError((err or out or 'yt-dlp channel browse failed').strip())
    try:
        data = json.loads(out or '{}')
    except Exception:
        raise RuntimeError('yt-dlp channel browse returned invalid json')
    entries = data.get('entries')
    if not isinstance(entries, list):
        return []
    channel_name = str(data.get('channel') or data.get('uploader') or data.get('title') or '').strip()
    channel_url = str(data.get('channel_url') or _youtube_channel_url(cid)).strip()
    out_items: List[dict] = []
    max_items = int(limit or 0)
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        vid = str(ent.get('id') or ent.get('video_id') or '').strip()
        if not vid:
            url = str(ent.get('url') or '').strip()
            if 'watch?v=' in url:
                vid = url.split('watch?v=', 1)[1].split('&', 1)[0].strip()
        if not vid:
            continue
        title = str(ent.get('title') or '').strip() or 'YouTube video'
        published = _youtube_format_upload_date(ent.get('upload_date') or ent.get('release_date') or ent.get('timestamp') or '')
        duration = ent.get('duration')
        length = ''
        try:
            if duration is not None:
                secs = int(float(duration))
                h = secs // 3600
                m = (secs % 3600) // 60
                s = secs % 60
                length = f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
        except Exception:
            length = str(ent.get('duration_string') or '').strip()
        if not length:
            length = str(ent.get('duration_string') or '').strip()
        view_count = ''
        try:
            vc = ent.get('view_count')
            if vc is not None and str(vc).strip() != '':
                view_count = f'{int(vc):,} views'
        except Exception:
            view_count = str(ent.get('view_count') or '').strip()
        thumb = ''
        thumbs = ent.get('thumbnails')
        if isinstance(thumbs, list) and thumbs:
            last = thumbs[-1] or {}
            if isinstance(last, dict):
                thumb = str(last.get('url') or '').strip()
        if not thumb:
            thumb = str(ent.get('thumbnail') or '').strip()
        chan = str(ent.get('channel') or ent.get('uploader') or channel_name).strip()
        chan_id = str(ent.get('channel_id') or cid).strip() or cid
        out_items.append({
            'video_id': vid,
            'url': _youtube_watch_url(vid),
            'title': title,
            'channel': chan,
            'channel_id': chan_id,
            'channel_url': str(ent.get('channel_url') or channel_url or _youtube_channel_url(chan_id)).strip(),
            'browse_url': '',
            'handle': '',
            'length': length,
            'published': published,
            'view_count': view_count,
            'thumbnail': thumb,
            'description': str(ent.get('description') or '').strip(),
        })
        if max_items > 0 and len(out_items) >= max_items:
            break
    return out_items


def _youtube_channel_entries_from_feed(channel_id: str, limit: int = YOUTUBE_CHANNEL_BROWSE_LIMIT) -> List[dict]:
    cid = str(channel_id or '').strip()
    if not cid:
        return []
    resp = requests.get(_youtube_channel_feed_url(cid), headers=YOUTUBE_REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'yt': 'http://www.youtube.com/xml/schemas/2015',
        'media': 'http://search.yahoo.com/mrss/',
    }
    out: List[dict] = []
    max_items = int(limit or 0)
    for entry in root.findall('atom:entry', ns):
        vid = (entry.findtext('yt:videoId', default='', namespaces=ns) or '').strip()
        title = (entry.findtext('atom:title', default='', namespaces=ns) or '').strip()
        author = (entry.findtext('atom:author/atom:name', default='', namespaces=ns) or '').strip()
        published = (entry.findtext('atom:published', default='', namespaces=ns) or '').strip()
        media_group = entry.find('media:group', ns)
        desc = ''
        thumb = ''
        if media_group is not None:
            desc = (media_group.findtext('media:description', default='', namespaces=ns) or '').strip()
            thumb_el = media_group.find('media:thumbnail', ns)
            if thumb_el is not None:
                thumb = str(thumb_el.attrib.get('url') or '').strip()
        if not vid:
            continue
        out.append({
            'video_id': vid,
            'url': _youtube_watch_url(vid),
            'title': title or 'YouTube video',
            'channel': author,
            'channel_id': cid,
            'channel_url': _youtube_channel_url(cid),
            'browse_url': '',
            'handle': '',
            'length': '',
            'published': published.replace('T', ' ').replace('Z', ' UTC'),
            'view_count': '',
            'thumbnail': thumb,
            'description': desc,
        })
        if max_items > 0 and len(out) >= max_items:
            break
    return out


def youtube_channel_videos(channel_id: str, limit: int = YOUTUBE_CHANNEL_BROWSE_LIMIT) -> List[dict]:
    try:
        items = _youtube_channel_entries_from_ytdlp(channel_id, limit)
        if items:
            return items
    except Exception:
        pass
    return _youtube_channel_entries_from_feed(channel_id, limit)


def _run_ytdlp(args: List[str]) -> Tuple[int, str, str]:
    return run_cmd([YTDLP_CMD] + list(args or []))


def _ytdlp_ffmpeg_location() -> str:
    raw = str(FFMPEG_PATH or '').strip()
    if not raw:
        return ''
    try:
        if os.path.isdir(raw):
            return raw
        parent = os.path.dirname(raw)
        return parent or raw
    except Exception:
        return raw


def _youtube_download_root() -> str:
    root = str(YOUTUBE_DOWNLOAD_DIR or '').strip()
    if root:
        return root
    return str(DOWNLOAD_DIR or '').strip()


def _youtube_stream_cache_dir() -> str:
    try:
        base = cache_dir()
    except Exception:
        base = _youtube_download_root()
    sub = str(YOUTUBE_STREAM_CACHE_SUBDIR or 'youtube_streams').strip() or 'youtube_streams'
    out = os.path.join(base, sub)
    os.makedirs(out, exist_ok=True)
    return out


def _yt_selected_output_ext(fmt: dict) -> str:
    media = str(fmt.get('media') or '').strip().lower()
    ext = str(fmt.get('ext') or '').strip().lower()
    if media == 'audio':
        if ext in ('m4a', 'mp3', 'aac', 'ogg', 'opus', 'wav', 'flac', 'webm'):
            return ext
        return 'm4a'
    if ext == 'webm':
        return 'webm'
    return 'mp4'


def _yt_stream_format_selector(fmt: dict) -> str:
    fid = str(fmt.get('format_id') or fmt.get('itag') or fmt.get('file_id') or '').strip()
    media = str(fmt.get('media') or '').strip().lower()
    if not fid:
        return 'best'
    if media == 'audio':
        return fid
    return f'{fid}+bestaudio/best'


_YOUTUBE_STREAM_BUILD_LOCKS: Dict[str, threading.Lock] = {}
_YOUTUBE_STREAM_BUILD_LOCKS_GUARD = threading.Lock()


def _youtube_stream_build_lock(key: str) -> threading.Lock:
    with _YOUTUBE_STREAM_BUILD_LOCKS_GUARD:
        lk = _YOUTUBE_STREAM_BUILD_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _YOUTUBE_STREAM_BUILD_LOCKS[key] = lk
        return lk


def _find_existing_output(base_no_ext: str) -> str:
    folder = os.path.dirname(base_no_ext) or '.'
    stem = os.path.basename(base_no_ext)
    try:
        for name in sorted(os.listdir(folder)):
            if name == stem or name.startswith(stem + '.'):
                cand = os.path.join(folder, name)
                if os.path.isfile(cand):
                    return cand
    except Exception:
        return ''
    return ''


def _prepare_youtube_stream_file(url: str, fmt: dict) -> str:
    src_url = str(url or '').strip()
    if not src_url:
        raise RuntimeError('Missing YouTube URL')
    fmt2 = dict(fmt or {})
    fmt_id = str(fmt2.get('format_id') or fmt2.get('itag') or fmt2.get('file_id') or '').strip()
    media = str(fmt2.get('media') or '').strip().lower()
    out_ext = _yt_selected_output_ext(fmt2)
    key = sha1_text(src_url + '|' + fmt_id + '|' + media + '|' + out_ext)
    folder = _youtube_stream_cache_dir()
    base_no_ext = os.path.join(folder, key)
    existing = _find_existing_output(base_no_ext)
    if existing:
        return existing
    lock = _youtube_stream_build_lock(key)
    with lock:
        existing = _find_existing_output(base_no_ext)
        if existing:
            return existing
        selector = _yt_stream_format_selector(fmt2)
        args = _yt_dlp_base_args() + ['--no-part', '--force-overwrites', '--newline', '-f', selector]
        if media != 'audio':
            args += ['--merge-output-format', out_ext]
        args += ['-o', base_no_ext + '.%(ext)s', src_url]
        code, out, err = _run_ytdlp(args)
        if code != 0:
            raise RuntimeError((err or out or 'yt-dlp failed').strip())
        built = _find_existing_output(base_no_ext)
        if not built:
            raise RuntimeError('yt-dlp did not produce a streamable file')
        return built


def _yt_dlp_base_args() -> List[str]:
    args = ['--no-playlist', '--no-warnings', '--ignore-config']
    ff_loc = _ytdlp_ffmpeg_location()
    if ff_loc:
        args += ['--ffmpeg-location', ff_loc]
    return args


def _yt_dlp_extract_info(url: str) -> dict:
    u = str(url or '').strip()
    if not u:
        return {}
    code, out, err = _run_ytdlp(_yt_dlp_base_args() + ['-J', '--skip-download', u])
    if code != 0:
        raise RuntimeError((err or out or 'yt-dlp failed').strip())
    try:
        data = json.loads(out or '{}')
    except Exception as e:
        raise RuntimeError(f'yt-dlp returned invalid json: {e}')
    if not isinstance(data, dict):
        raise RuntimeError('yt-dlp returned invalid info')
    return data


def _yt_guess_media(format_info: dict) -> str:
    vcodec = str(format_info.get('vcodec') or '').strip().lower()
    acodec = str(format_info.get('acodec') or '').strip().lower()
    if vcodec in ('none', '') and acodec not in ('', 'none'):
        return 'audio'
    return 'video'


def _yt_audio_bitrate_k(format_info: dict) -> str:
    abr = format_info.get('abr')
    try:
        if abr is not None and float(abr) > 0:
            return str(int(round(float(abr)))) + 'k'
    except Exception:
        pass
    tbr = format_info.get('tbr')
    try:
        if tbr is not None and float(tbr) > 0 and _yt_guess_media(format_info) == 'audio':
            return str(int(round(float(tbr)))) + 'k'
    except Exception:
        pass
    return ''


def _yt_quality_text(format_info: dict) -> str:
    q = str(format_info.get('format') or '').strip()
    if q:
        return q
    note = str(format_info.get('format_note') or '').strip()
    if note:
        ext = str(format_info.get('ext') or '').strip().lower()
        return (note + ((' ' + ext) if ext else '')).strip()
    height = format_info.get('height')
    width = format_info.get('width')
    try:
        if height:
            fps = format_info.get('fps')
            base = f'{int(height)}p'
            try:
                if fps and float(fps) >= 1:
                    base += str(int(round(float(fps))))
            except Exception:
                pass
            ext = str(format_info.get('ext') or '').strip().lower()
            return (base + ((' ' + ext) if ext else '')).strip()
    except Exception:
        pass
    abr = _yt_audio_bitrate_k(format_info)
    if abr:
        ext = str(format_info.get('ext') or '').strip().lower()
        return (abr + ((' ' + ext) if ext else '')).strip()
    if width:
        ext = str(format_info.get('ext') or '').strip().lower()
        return (str(width) + 'w' + ((' ' + ext) if ext else '')).strip()
    return str(format_info.get('format_id') or 'Format').strip()


def _yt_direct_url_for_format(url: str, format_id: str) -> str:
    info = _yt_dlp_extract_info(url)
    fid = str(format_id or '').strip()
    if not fid:
        return str(info.get('url') or '').strip()
    for fmt in list(info.get('formats') or []):
        if not isinstance(fmt, dict):
            continue
        if str(fmt.get('format_id') or '').strip() == fid:
            return str(fmt.get('url') or '').strip()
    return ''


def ytdlp_list_formats(url: str) -> List[dict]:
    info = _yt_dlp_extract_info(url)
    items: List[dict] = []
    seen = set()
    for fmt in list(info.get('formats') or []):
        if not isinstance(fmt, dict):
            continue
        fid = str(fmt.get('format_id') or '').strip()
        if not fid:
            continue
        ext = str(fmt.get('ext') or '').strip().lower()
        if ext in ('mhtml', 'jpg', 'jpeg', 'png', 'webp'):
            continue
        acodec = str(fmt.get('acodec') or '').strip().lower()
        vcodec = str(fmt.get('vcodec') or '').strip().lower()
        if acodec in ('', 'none') and vcodec in ('', 'none'):
            continue
        direct_url = str(fmt.get('url') or '').strip()
        quality = _yt_quality_text(fmt)
        name = quality or ('Format ' + fid)
        size = 0
        for key in ('filesize', 'filesize_approx'):
            try:
                val = fmt.get(key)
                if val is not None and int(val) > 0:
                    size = int(val)
                    break
            except Exception:
                pass
        media = _yt_guess_media(fmt)
        bitrate = _yt_audio_bitrate_k(fmt) if media == 'audio' else ''
        key = (fid, ext, quality, size)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            'file_id': fid,
            'itag': fid,
            'format_id': fid,
            'name': name,
            'title': name,
            'ext': ext,
            'quality': quality,
            'bitrate': bitrate,
            'size': size,
            'size_text': human_bytes(size) if size > 0 else '',
            'source': 'youtube',
            'selectable': True,
            'media': media,
            'direct_url': direct_url,
            'fps': int(fmt.get('fps') or 0) if str(fmt.get('fps') or '').strip() else 0,
            'height': int(fmt.get('height') or 0) if str(fmt.get('height') or '').strip() else 0,
            'width': int(fmt.get('width') or 0) if str(fmt.get('width') or '').strip() else 0,
            'acodec': acodec,
            'vcodec': vcodec,
            'protocol': str(fmt.get('protocol') or '').strip(),
        })
    def _sort_key(it: dict):
        media_rank = 0 if str(it.get('media') or '') == 'video' else 1
        try:
            h = int(it.get('height') or 0)
        except Exception:
            h = 0
        try:
            sz = int(it.get('size') or 0)
        except Exception:
            sz = 0
        return (media_rank, -h, -sz, str(it.get('name') or '').lower())
    items.sort(key=_sort_key)
    return items


def _search_youtube_cached(q: str) -> Tuple[List[dict], str, str]:
    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key('youtube', q, extra)
    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get('payload'), dict):
            cached_payload = d.get('payload')
    if cached_payload is not None:
        return list(cached_payload.get('results') or []), str(cached_payload.get('error') or ''), cache_key
    try:
        results = youtube_search(q)
        err = ''
    except Exception as e:
        results = []
        err = 'YouTube search failed: ' + str(e)
    with _SEARCH_DISK_LOCK:
        _disk_cache_set(cache_key, 'youtube', q, extra, {'results': results, 'error': err})
    return results, err, cache_key


def _standardize_youtube_results(raw_results: List[dict]) -> List[dict]:
    out: List[dict] = []
    for r in raw_results or []:
        if not isinstance(r, dict):
            continue
        video_id = str(r.get('video_id') or '').strip()
        title = str(r.get('title') or '').strip()
        if not video_id or not title:
            continue
        published = str(r.get('published') or '').strip()
        view_count = str(r.get('view_count') or '').strip()
        length = str(r.get('length') or '').strip()
        channel = str(r.get('channel') or '').strip()
        channel_id = str(r.get('channel_id') or '').strip()
        out.append({
            'result_id': 'youtube:' + video_id,
            'source': 'youtube',
            'source_label': 'YouTube',
            'user': channel,
            'title': title,
            'directory': str(r.get('url') or ''),
            'directory_title': published or length or view_count,
            'file_count': 0,
            'size': 0,
            'speed': 0,
            'seeders': 0,
            'leechers': 0,
            'browse_available': bool(channel_id),
            'stream_available': True,
            'files_loaded': False,
            'files': [],
            'video_id': video_id,
            'url': str(r.get('url') or _youtube_watch_url(video_id)),
            'channel': channel,
            'channel_id': channel_id,
            'channel_url': str(r.get('channel_url') or ''),
            'published': published,
            'view_count': view_count,
            'length': length,
            'thumbnail': str(r.get('thumbnail') or ''),
            'description': str(r.get('description') or ''),
            '_score': 1,
        })
    return out


def youtube_load_result_files(raw: dict) -> dict:
    out = dict(raw or {})
    files = ytdlp_list_formats(str(out.get('url') or ''))
    total_size = 0
    for f in files:
        try:
            total_size += int(f.get('size') or 0)
        except Exception:
            pass
    out['files'] = files
    out['file_count'] = len(files)
    out['size'] = total_size
    out['files_loaded'] = True
    return out


def youtube_channel_browse(channel_id: str) -> List[dict]:
    return _standardize_youtube_results(youtube_channel_videos(channel_id))


# =========================
# Real Debrid task tracking
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
configure_task_manager(
    soulseek_service_provider=lambda: SOULSEEK_SERVICE,
    retry_worker_provider=lambda source: youtube_download_remaining_worker if source == "youtube" else rd_download_remaining_worker,
)

# =========================
# Soulseek streaming search sessions
# =========================
_SLSK_SESS_LOCK = threading.Lock()
_SLSK_SESSIONS: Dict[str, Dict[str, Any]] = {}

def _slsk_gc_sessions(max_keep: int = 20) -> None:
    with _SLSK_SESS_LOCK:
        if len(_SLSK_SESSIONS) <= max_keep:
            return
        # Drop oldest done sessions first
        items = list(_SLSK_SESSIONS.items())
        items.sort(key=lambda kv: float(kv[1].get("created") or 0.0))
        for sid, sess in items:
            if len(_SLSK_SESSIONS) <= max_keep:
                break
            if sess.get("done"):
                _SLSK_SESSIONS.pop(sid, None)

def _slsk_session_create(cache_key: str, q: str) -> str:
    sid = uuid.uuid4().hex
    with _SLSK_SESS_LOCK:
        _slsk_gc_sessions()
        _SLSK_SESSIONS[sid] = {
            "id": sid,
            "cache_key": cache_key,
            "q": q,
            "created": time.time(),
            "rev": 0,
            "done": False,
            "error": "",
            "items": {},
            "user_speed": {},
            "file_count": 0,
            "dir_count": 0,
            "last_touch": time.time(),
        }
    return sid

def _slsk_session_touch(sid: str) -> None:
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(sid)
        if s:
            s["last_touch"] = time.time()

def _slsk_session_add_items(session_id: str, items: List[Dict[str, Any]]) -> None:
    if not items:
        return
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(session_id)
        if not s or s.get("done"):
            return
        store = s.get("items")
        if not isinstance(store, dict):
            store = {}
            s["items"] = store
        user_speed = s.get("user_speed")
        if not isinstance(user_speed, dict):
            user_speed = {}
            s["user_speed"] = user_speed

        new_any = False
        for it in items:
            user = (it.get("user") or "").strip()
            rp = str(it.get("remote_path") or "")
            if not user or not rp:
                continue
            rp_norm = _slsk_norm_remote_path(rp)
            parts = rp_norm.split("\\")
            fname = parts[-1] if parts else rp_norm
            directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
            key = user + "|" + rp_norm
            if key in store:
                continue
            kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)
            try:
                size = int(it.get("size") or 0)
            except Exception:
                size = 0
            try:
                speed = int(it.get("speed") or 0)
            except Exception:
                speed = 0

            store[key] = {
                "user": user,
                "directory": directory,
                "name": fname,
                "remote_path": rp_norm,
                "size": size,
                "ext": ext,
                "kind": kind,
                "bitrate": br,
                "bit_depth": bd,
                "sample_rate": sr,
                "duration": dur,
                "vbr": vbr,
                "codec": codec,
                "speed": speed,
            }
            if speed and (user_speed.get(user, 0) < speed):
                user_speed[user] = speed
            new_any = True

        if new_any:
            # Recompute counts
            file_count = len(store)
            dirs = set()
            for v in store.values():
                dirs.add((v.get("user") or "", v.get("directory") or ""))
            s["file_count"] = int(file_count)
            s["dir_count"] = int(len(dirs))
            s["rev"] = int(s.get("rev") or 0) + 1
            s["last_touch"] = time.time()

def _slsk_session_mark_done(session_id: str, error: str = "") -> None:
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(session_id)
        if not s:
            return
        if s.get("done"):
            return
        s["done"] = True
        s["error"] = str(error or "")
        s["rev"] = int(s.get("rev") or 0) + 1
        s["last_touch"] = time.time()

def _slsk_session_snapshot(session_id: str) -> Optional[Dict[str, Any]]:
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(session_id)
        if not s:
            return None
        # Lightweight copy
        return {
            "id": s.get("id") or "",
            "cache_key": s.get("cache_key") or "",
            "q": s.get("q") or "",
            "created": float(s.get("created") or 0.0),
            "rev": int(s.get("rev") or 0),
            "done": bool(s.get("done")),
            "error": s.get("error") or "",
            "file_count": int(s.get("file_count") or 0),
            "dir_count": int(s.get("dir_count") or 0),
            "items": dict(s.get("items") or {}),
            "user_speed": dict(s.get("user_speed") or {}),
        }

def _slsk_download_state_priority(state: str) -> int:
    s = _slsk_clean_state_token(state)
    if s == "complete":
        return 100
    if s in {"downloading", "uploading", "initializing", "queued", "paused"}:
        return 80
    if s in {"incomplete", "failed", "aborted"}:
        return 60
    return 0


def _slsk_lookup_download_state(user: str, remote_path: str) -> Dict[str, Any]:
    user_s = str(user or "").strip()
    rp_norm = _slsk_norm_remote_path(remote_path or "")
    if not user_s or not rp_norm:
        return {}

    best: Dict[str, Any] = {}
    best_rank = -1
    with TASKS_LOCK:
        tasks = sorted(TASKS.values(), key=lambda t: float(getattr(t, "created", 0.0) or 0.0), reverse=True)

    for t in tasks:
        if (getattr(t, "source", "") or "").lower() != "soulseek":
            continue
        for f in list(getattr(t, "slsk_files", []) or []):
            try:
                fu = str(f.get("user") or getattr(t, "slsk_user", "") or "").strip()
                frp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            except Exception:
                continue
            if fu != user_s or frp.lower() != rp_norm.lower():
                continue
            st = _slsk_normalize_state(
                str(f.get("state") or f.get("state_raw") or ""),
                bool(f.get("paused")),
                bool(f.get("canceled")),
                _slsk_int_from_any(f.get("done") or 0),
                _slsk_int_from_any(f.get("total") or f.get("size") or 0),
                bool(f.get("error")),
            )
            rank = _slsk_download_state_priority(st)
            if rank > best_rank:
                best_rank = rank
                best = {
                    "download_state": st,
                    "download_task_id": str(getattr(t, "id", "") or ""),
                    "download_error": str(f.get("error") or ""),
                }
                if rank >= 100:
                    return best
    return best


def _slsk_annotate_file_with_download_state(file_obj: Dict[str, Any], user: str) -> Dict[str, Any]:
    if not isinstance(file_obj, dict):
        return file_obj
    info = _slsk_lookup_download_state(user, str(file_obj.get("remote_path") or ""))
    if info:
        file_obj.update(info)
    return file_obj


def _slsk_group_snapshot_to_users(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    store = snap.get("items") or {}
    user_speed = snap.get("user_speed") or {}
    users: Dict[str, Dict[str, Any]] = {}
    for v in store.values():
        user = v.get("user") or ""
        directory = v.get("directory") or ""
        if not user:
            continue
        u = users.get(user)
        if u is None:
            u = {"user": user, "speed": int(user_speed.get(user) or 0), "dirs": [], "total_files": 0}
            users[user] = u
        # directory entry
        dir_map = u.setdefault("_dir_map", {})
        dd = dir_map.get(directory)
        if dd is None:
            dd = {"directory": directory, "files": [], "total_size": 0}
            dir_map[directory] = dd
            u["dirs"].append(dd)
        fobj = {
            "name": v.get("name") or "",
            "remote_path": v.get("remote_path") or "",
            "size": int(v.get("size") or 0),
            "ext": v.get("ext") or "",
            "kind": v.get("kind") or "file",
            "bitrate": v.get("bitrate"),
            "bit_depth": v.get("bit_depth"),
            "sample_rate": v.get("sample_rate"),
            "duration": v.get("duration"),
            "vbr": v.get("vbr"),
            "codec": v.get("codec") or "",
        }
        fobj = _slsk_annotate_file_with_download_state(fobj, user)
        dd["files"].append(fobj)
        dd["total_size"] = int(dd.get("total_size") or 0) + int(fobj.get("size") or 0)
        u["total_files"] = int(u.get("total_files") or 0) + 1

    # Clean internal maps and sort
    out: List[Dict[str, Any]] = []
    for u in users.values():
        try:
            u.pop("_dir_map", None)
        except Exception:
            pass
        # sort dirs by total_size desc
        try:
            u["dirs"].sort(key=lambda d: int(d.get("total_size") or 0), reverse=True)
        except Exception:
            pass
        out.append(u)

    # Sort users by speed desc
    out.sort(key=lambda x: int(x.get("speed") or 0), reverse=True)
    return out



def _slsk_norm_remote_path(p: str) -> str:
    s = (p or "").replace("/", "\\")
    s = s.lstrip("\\")
    return s


def _slsk_local_path(download_dir: str, remote_path: str) -> str:
    rp = _slsk_norm_remote_path(remote_path)
    parts = [x for x in rp.split("\\") if x]
    return os.path.join(download_dir, *parts) if parts else download_dir


def soulseek_log_file_path() -> str:
    # Keeps Soulseek (aioslsk) logs out of the terminal; written to a dedicated file.
    return os.path.join(cache_dir(), "soulseek_aioslsk.log")


def soulseek_incoming_dir() -> str:
    return os.path.join(SOULSEEK_DOWNLOAD_DIR, "_incoming")


def _slsk_sanitized_dir_name(remote_directory: str) -> str:
    d = _slsk_norm_remote_path(remote_directory or "")
    base = d.split("\\")[-1].strip() if d else ""
    base = sanitize_filename(base) if base else ""
    return base or "soulseek"


def _slsk_task_download_dir(remote_directory: str) -> str:
    return os.path.join(SOULSEEK_DOWNLOAD_DIR, _slsk_sanitized_dir_name(remote_directory))


def _slsk_relative_under_directory(remote_directory: str, remote_path: str) -> str:
    d = _slsk_norm_remote_path(remote_directory or "").rstrip("\\")
    p = _slsk_norm_remote_path(remote_path or "")
    if d and p.lower().startswith((d + "\\").lower()):
        rel = p[len(d) + 1 :]
    else:
        rel = p.split("\\")[-1]
    rel = rel.lstrip("\\")
    return rel or (p.split("\\")[-1] if p else "")




def _slsk_collect_browse_items(obj: Any, user: str = "", base_dir: str = "", _seen: Optional[set] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if _seen is None:
        _seen = set()
    try:
        oid = id(obj)
    except Exception:
        oid = None
    if oid is not None:
        if oid in _seen:
            return items
        _seen.add(oid)

    def _get(o: Any, key: str, default=None):
        if isinstance(o, dict):
            return o.get(key, default)
        return getattr(o, key, default)

    if obj is None:
        return items

    if isinstance(obj, (list, tuple, set)):
        for part in obj:
            items.extend(_slsk_collect_browse_items(part, user=user, base_dir=base_dir, _seen=_seen))
        return items

    rp = _get(obj, "remote_path", None)
    if rp is None:
        rp = _get(obj, "filename", None)
    if rp is None:
        rp = _get(obj, "path", None)
    rp_str = str(rp or "").strip()
    if rp_str:
        rp_norm = _slsk_norm_remote_path(rp_str)
        if "\\" not in rp_norm and base_dir:
            rp_norm = _slsk_norm_remote_path(base_dir.rstrip("\\") + "\\" + rp_norm)
        parts = rp_norm.split("\\")
        fname = parts[-1] if parts else rp_norm
        directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
        size = _get(obj, "size", None)
        if size is None:
            size = _get(obj, "filesize", 0)
        try:
            size = int(size or 0)
        except Exception:
            size = 0
        kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, obj)
        items.append({
            "user": str(user or _get(obj, "username", "") or _get(obj, "user", "") or ""),
            "directory": directory,
            "name": fname,
            "remote_path": rp_norm,
            "size": size,
            "ext": ext,
            "kind": kind,
            "bitrate": br,
            "bit_depth": bd,
            "sample_rate": sr,
            "duration": dur,
            "vbr": vbr,
            "codec": codec,
        })
        return items

    next_base = base_dir
    dir_name = _get(obj, "directory", None)
    if dir_name is None:
        dir_name = _get(obj, "name", None)
    if dir_name is None:
        dir_name = _get(obj, "path", None)
    dir_name_s = str(dir_name or "").strip()
    if dir_name_s and dir_name_s != base_dir:
        if "\\" in dir_name_s or "/" in dir_name_s:
            next_base = _slsk_norm_remote_path(dir_name_s)
        else:
            next_base = _slsk_norm_remote_path((base_dir.rstrip("\\") + "\\" + dir_name_s) if base_dir else dir_name_s)

    for key in ("files", "items", "shared_items", "children", "directories", "dirs", "subdirs", "subdirectories"):
        val = _get(obj, key, None)
        if val:
            items.extend(_slsk_collect_browse_items(val, user=user, base_dir=next_base, _seen=_seen))

    if not items and not isinstance(obj, dict):
        for key in dir(obj):
            if key.startswith("_"):
                continue
            if key in {"remote_path", "filename", "path", "size", "filesize", "name", "directory"}:
                continue
            try:
                val = getattr(obj, key)
            except Exception:
                continue
            if callable(val):
                continue
            if isinstance(val, (str, bytes, int, float, bool)):
                continue
            items.extend(_slsk_collect_browse_items(val, user=user, base_dir=next_base, _seen=_seen))
    return items


def _slsk_group_items_to_dirs(user: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    dirs: Dict[str, Dict[str, Any]] = {}
    seen: set = set()
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        rp = _slsk_norm_remote_path(str(it.get("remote_path") or ""))
        if not rp or rp in seen:
            continue
        seen.add(rp)
        directory = _slsk_norm_remote_path(str(it.get("directory") or ""))
        if not directory and "\\" in rp:
            directory = "\\".join(rp.split("\\")[:-1])
        name = str(it.get("name") or rp.split("\\")[-1] or "")
        dd = dirs.get(directory)
        if dd is None:
            dd = {"directory": directory, "files": [], "total_size": 0, "total_files": 0}
            dirs[directory] = dd
        fobj = {
            "name": name,
            "remote_path": rp,
            "size": int(it.get("size") or 0),
            "ext": it.get("ext") or "",
            "kind": it.get("kind") or "file",
            "bitrate": it.get("bitrate"),
            "bit_depth": it.get("bit_depth"),
            "sample_rate": it.get("sample_rate"),
            "duration": it.get("duration"),
            "vbr": it.get("vbr"),
            "codec": it.get("codec") or "",
        }
        fobj = _slsk_annotate_file_with_download_state(fobj, user)
        dd["files"].append(fobj)
        dd["total_size"] = int(dd.get("total_size") or 0) + int(fobj.get("size") or 0)
        dd["total_files"] = int(dd.get("total_files") or 0) + 1

    out = list(dirs.values())
    out.sort(key=lambda d: (int(d.get("total_size") or 0), int(d.get("total_files") or 0), str(d.get("directory") or "").lower()), reverse=True)
    return out


def _slsk_expected_incoming_path(remote_path: str) -> str:
    fn = _slsk_norm_remote_path(remote_path or "").split("\\")[-1]
    return os.path.join(soulseek_incoming_dir(), fn) if fn else soulseek_incoming_dir()


def _safe_move_file(src_path: str, dst_path: str) -> str:
    """Move a file to dst_path, with automatic renaming if needed. Returns the final destination path."""
    src_path = str(src_path or "")
    dst_path = str(dst_path or "")
    if not src_path or not dst_path:
        return dst_path
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    if not os.path.exists(src_path):
        return dst_path
    if not os.path.exists(dst_path):
        try:
            os.replace(src_path, dst_path)
            return dst_path
        except Exception:
            pass
    base, ext = os.path.splitext(dst_path)
    for i in range(1, 1000):
        cand = f"{base} ({i}){ext}"
        if not os.path.exists(cand):
            try:
                os.replace(src_path, cand)
                return cand
            except Exception:
                continue
    return dst_path


class _DropAioslskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return not (record and getattr(record, "name", "").startswith("aioslsk"))
        except Exception:
            return True


def configure_aioslsk_logging() -> str:
    """Route aioslsk logs to a dedicated file and prevent them from printing to the terminal."""
    log_file = soulseek_log_file_path()
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
    except Exception:
        pass

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)

    # Prevent any existing root handlers from printing aioslsk logs.
    drop = _DropAioslskFilter()
    root = logging.getLogger()
    for h in list(getattr(root, "handlers", []) or []):
        try:
            h.addFilter(drop)
        except Exception:
            pass

    # Attach our handler to aioslsk loggers and stop propagation.
    try:
        names = list(logging.root.manager.loggerDict.keys())
    except Exception:
        names = []
    if "aioslsk" not in names:
        names.append("aioslsk")
    for name in names:
        if name == "aioslsk" or str(name).startswith("aioslsk."):
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            try:
                lg.handlers.clear()
            except Exception:
                for old in list(getattr(lg, "handlers", []) or []):
                    try:
                        lg.removeHandler(old)
                    except Exception:
                        pass
            lg.addHandler(fh)
            lg.propagate = False

    return log_file


def _slsk_resolve_local_progress_path(final_path: str) -> str:
    """Return a path that is likely to exist while downloading (handles common temp extensions)."""
    p = str(final_path or "")
    if not p:
        return p
    try:
        if os.path.exists(p):
            return p
        exts = [".part", ".partial", ".incomplete", ".tmp", ".download", ".downloading"]
        for ext in exts:
            cand = p + ext
            if os.path.exists(cand):
                return cand
        d = os.path.dirname(p)
        bn = os.path.basename(p)
        if d and os.path.isdir(d) and bn:
            for fn in os.listdir(d):
                if fn != bn and fn.startswith(bn):
                    cand = os.path.join(d, fn)
                    if os.path.isfile(cand):
                        return cand
    except Exception:
        pass
    return p


def _slsk_int_from_any(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0



def _slsk_clean_state_token(v: Any) -> str:
    s = ""
    try:
        if v is None:
            return ""
        if hasattr(v, "name"):
            s = str(getattr(v, "name", "") or "")
        else:
            s = str(v or "")
    except Exception:
        s = ""
    s = s.strip()
    if not s:
        return ""
    # Common enum/string formats: "TransferState.DOWNLOADING", "DOWNLOAD))"
    if "." in s:
        s = s.split(".")[-1]
    s = s.lower()
    # Remove non-token characters
    try:
        s = re.sub(r"[^a-z_]+", "", s)
    except Exception:
        pass
    s = s.strip("_")
    return s


def _slsk_normalize_state(raw_state: str, paused: bool, canceled: bool, done: int, total: int, has_error: bool) -> str:
    s = _slsk_clean_state_token(raw_state)

    if canceled:
        return "aborted"
    if paused and s != "complete":
        return "paused"
    if total > 0 and done >= total and done > 0:
        return "complete"

    if s in {"done", "finished", "completed", "complete", "success", "succeeded"}:
        return "complete"
    if s in {"abort", "aborted", "aborting", "cancel", "canceled", "cancelled"}:
        return "aborted"
    if s in {"pause", "paused", "pausing"}:
        return "paused"
    if s in {"incomplete", "retry", "retrying", "willretry", "queued_retry", "queuedretry"}:
        return "incomplete"
    if s in {"fail", "failed", "failure", "error", "exception", "timeout", "timedout", "timed_out"}:
        return "failed"
    if s in {"queue", "queued", "enqueued", "waiting", "pending", "idle"}:
        return "queued"
    if s in {"initialize", "initializing", "init", "starting", "request", "requesting", "requested", "connect", "connecting", "handshake", "negotiating"}:
        return "initializing"
    if s in {"upload", "uploading", "sending"}:
        return "uploading"
    if s in {"download", "downloading", "transfer", "transferring", "receiving", "inprogress", "in_progress", "active"}:
        return "downloading"

    if has_error:
        if s in {"incomplete", "retry", "retrying", "willretry", "queued_retry", "queuedretry"}:
            return "incomplete"
        return "failed"

    if done > 0 and (total <= 0 or done < total):
        return "downloading"
    if total > 0 and done >= total and done > 0:
        return "complete"
    return "queued"



def _slsk_extract_transfer_progress(tr: Any) -> Tuple[int, int, float, str]:
    """Best-effort extraction of (done_bytes, total_bytes, speed_bps, state_str) from aioslsk transfer objects."""
    done = 0
    total = 0
    speed = 0.0
    state = ""
    if tr is None:
        return done, total, speed, state

    # state
    try:
        st = getattr(tr, "state", "")
        if hasattr(st, "name"):
            state = str(getattr(st, "name", "")).lower()
        else:
            s = str(st or "")
            if "." in s:
                s = s.split(".")[-1]
            state = s.lower()
    except Exception:
        state = ""

    state = _slsk_clean_state_token(state) if state else ""

    # total
    for attr in ("filesize", "file_size", "size", "total", "total_bytes", "bytes_total", "expected_size"):
        try:
            total = _slsk_int_from_any(getattr(tr, attr, 0))
        except Exception:
            total = 0
        if total > 0:
            break

    # done
    for attr in ("bytes_received", "received", "bytes_transferred", "transferred", "downloaded", "bytes_done", "position", "offset"):
        try:
            done = _slsk_int_from_any(getattr(tr, attr, 0))
        except Exception:
            done = 0
        if done > 0:
            break

    # Some aioslsk versions store progress in a nested object
    try:
        prog = getattr(tr, "progress", None)
    except Exception:
        prog = None
    if prog is not None:
        if total <= 0:
            for attr in ("total", "total_bytes", "bytes_total", "filesize", "file_size", "size", "expected_size"):
                try:
                    total = _slsk_int_from_any(getattr(prog, attr, 0))
                except Exception:
                    total = 0
                if total > 0:
                    break
        if done <= 0:
            for attr in ("done", "bytes_received", "received", "bytes_transferred", "transferred", "downloaded", "bytes_done", "position", "offset"):
                try:
                    done = _slsk_int_from_any(getattr(prog, attr, 0))
                except Exception:
                    done = 0
                if done > 0:
                    break

    # speed
    for attr in ("speed", "bps", "bytes_per_second", "download_speed", "upload_speed"):
        try:
            s = getattr(tr, attr, None)
            if s is None:
                continue
            speed = float(s)
        except Exception:
            speed = 0.0
        if speed > 0:
            break

    return done, total, speed, state


def _slsk_extract_transfer_error(tr: Any) -> str:
    if tr is None:
        return ""
    for attr in ("error", "exception", "reason", "failure_reason", "last_error", "message"):
        try:
            v = getattr(tr, attr, None)
            if v:
                return str(v)
        except Exception:
            continue
    # Some versions keep errors nested
    for parent in ("progress", "status"):
        try:
            obj = getattr(tr, parent, None)
        except Exception:
            obj = None
        if obj is None:
            continue
        for attr in ("error", "exception", "reason", "failure_reason", "last_error", "message"):
            try:
                v = getattr(obj, attr, None)
                if v:
                    return str(v)
            except Exception:
                continue
    return ""


def _slsk_transfer_is_paused(tr: Any) -> bool:
    if tr is None:
        return False
    for attr in ("paused", "is_paused"):
        try:
            v = getattr(tr, attr, None)
            if isinstance(v, bool):
                return v
        except Exception:
            continue
    # state string sometimes includes paused
    try:
        st = getattr(tr, "state", "")
        s = str(getattr(st, "name", st) or "").lower()
        if "pause" in s:
            return True
    except Exception:
        pass
    return False


def _slsk_as_mapping(x: Any) -> Optional[Dict[str, Any]]:
    if x is None:
        return None
    if isinstance(x, dict):
        return x
    if isinstance(x, (list, tuple)):
        try:
            if all(isinstance(i, (list, tuple)) and len(i) == 2 for i in x):
                return {str(k): v for k, v in x}  # type: ignore
        except Exception:
            return None
    return None


def _slsk_to_dict(x: Any) -> Optional[Dict[str, Any]]:
    if x is None:
        return None
    if isinstance(x, dict):
        return x
    for mname in ("to_dict", "dict", "as_dict"):
        try:
            if hasattr(x, mname):
                d = getattr(x, mname)()
                if isinstance(d, dict):
                    return d
        except Exception:
            continue
    return None


def _slsk_pick(obj: Any, *names: str) -> Any:
    for n in names:
        try:
            if hasattr(obj, n):
                v = getattr(obj, n)
                if v is not None and v != "":
                    return v
        except Exception:
            pass
        try:
            if isinstance(obj, dict) and n in obj:
                v = obj.get(n)
                if v is not None and v != "":
                    return v
        except Exception:
            pass

    for cname in ("attributes", "attrs", "meta", "metadata", "info", "audio", "details", "extra"):
        c = None
        try:
            c = getattr(obj, cname, None)
        except Exception:
            c = None
        if c is None and isinstance(obj, dict):
            try:
                c = obj.get(cname)
            except Exception:
                c = None

        cm = _slsk_as_mapping(c) or _slsk_to_dict(c)
        if cm is not None:
            for n in names:
                if n in cm:
                    v = cm.get(n)
                    if v is not None and v != "":
                        return v
        else:
            for n in names:
                try:
                    if c is not None and hasattr(c, n):
                        v = getattr(c, n)
                        if v is not None and v != "":
                            return v
                except Exception:
                    pass

    d0 = _slsk_to_dict(obj)
    if d0 is not None:
        for n in names:
            if n in d0:
                v = d0.get(n)
                if v is not None and v != "":
                    return v
        for _, vv in list(d0.items())[:50]:
            dv = _slsk_as_mapping(vv) or _slsk_to_dict(vv)
            if dv is None:
                continue
            for n in names:
                if n in dv:
                    v = dv.get(n)
                    if v is not None and v != "":
                        return v
    return None


def _slsk_pick_int(obj: Any, *names: str) -> Optional[int]:
    v = _slsk_pick(obj, *names)
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None


def _slsk_attr_code_map(obj: Any) -> Dict[int, int]:
    """Return Soulseek attribute code mapping for a shared file item.

    Soulseek search results include file attributes as numeric code/value pairs.
    Common codes used by popular clients:
      0: bitrate (kbps)
      1: duration (seconds)
      2: vbr flag (1)
      4: sample rate (Hz)
      5: bit depth (bits)
    """
    candidates = []
    for cname in ("attributes", "attrs", "attr", "file_attributes", "fileAttrs", "audio_attributes", "audioAttributes"):
        try:
            v = getattr(obj, cname, None)
        except Exception:
            v = None
        if v is None and isinstance(obj, dict):
            try:
                v = obj.get(cname)
            except Exception:
                v = None
        if v is not None:
            candidates.append(v)

    # Also inspect dict views when provided by library objects
    d0 = _slsk_to_dict(obj)
    if d0:
        for k in ("attributes", "attrs", "file_attributes", "fileAttributes"):
            if k in d0 and d0.get(k) is not None:
                candidates.append(d0.get(k))

    out: Dict[int, int] = {}

    def _key_to_code(k: Any) -> Optional[int]:
        """Best effort conversion of aioslsk attribute keys into Soulseek numeric codes."""
        if k is None:
            return None
        # enum like AttributeType
        try:
            kv = getattr(k, "value", None)
            if isinstance(kv, (int, float)):
                return int(kv)
        except Exception:
            pass
        try:
            kn = getattr(k, "name", None)
            if isinstance(kn, str) and kn:
                c2 = _key_to_code(kn)
                if c2 is not None:
                    return c2
        except Exception:
            pass
        if isinstance(k, (int, float)):
            return int(k)
        if isinstance(k, str):
            s = k.strip().lower()
            if not s:
                return None
            if s.isdigit():
                try:
                    return int(s)
                except Exception:
                    return None
            s2 = s.replace("_", " ").replace("-", " ").strip()
            alias = {
                "bitrate": 0,
                "br": 0,
                "kbps": 0,
                "duration": 1,
                "length": 1,
                "time": 1,
                "vbr": 2,
                "variable bitrate": 2,
                "variable_bitrate": 2,
                "samplerate": 4,
                "sample rate": 4,
                "sample_rate": 4,
                "frequency": 4,
                "hz": 4,
                "bitdepth": 5,
                "bit depth": 5,
                "bit_depth": 5,
                "depth": 5,
                "bits": 5,
                "encoder": 3,
            }
            if s2 in alias:
                return alias[s2]
            if s in alias:
                return alias[s]
        return None

    def _val_to_int(v: Any) -> Optional[int]:
        if v is None:
            return None
        try:
            vv = getattr(v, "value", None)
            if vv is not None:
                v = vv
        except Exception:
            pass
        try:
            return int(v)
        except Exception:
            try:
                return int(float(v))
            except Exception:
                return None
    for v in candidates:
        if v is None:
            continue
        if isinstance(v, dict):
            for kk, vv in v.items():
                try:
                    ik = _key_to_code(kk)
                    iv = _val_to_int(vv)
                    if ik is None or iv is None:
                        continue
                    out[int(ik)] = int(iv)
                except Exception:
                    continue
            if out:
                return out

        if isinstance(v, (list, tuple)):
            # list of pairs
            try:
                if all(isinstance(i, (list, tuple)) and len(i) == 2 for i in v):
                    for kk, vv in v:
                        ck = _key_to_code(kk)
                        cv = _val_to_int(vv)
                        if ck is None or cv is None:
                            continue
                        out[int(ck)] = int(cv)
                    if out:
                        return out
            except Exception:
                pass

            # list of objects: [{index/code, value}, ...] or FileAttribute objects
            try:
                for it in v:
                    if it is None:
                        continue
                    if isinstance(it, dict):
                        ck = it.get("index", None)
                        if ck is None:
                            ck = it.get("code", None)
                        if ck is None:
                            ck = it.get("id", None)
                        if ck is None:
                            ck = it.get("key", None)
                        if ck is None:
                            ck = it.get("type", None)
                        if ck is None:
                            ck = it.get("attribute", None)
                        if ck is None:
                            ck = it.get("attribute_type", None)
                        if ck is None:
                            ck = it.get("attr_type", None)

                        cv = it.get("value", None)
                        if cv is None:
                            cv = it.get("val", None)
                        if cv is None:
                            cv = it.get("v", None)
                        if ck is None or cv is None:
                            continue
                        ck2 = _key_to_code(ck)
                        cv2 = _val_to_int(cv)
                        if ck2 is None or cv2 is None:
                            continue
                        try:
                            out[int(ck2)] = int(cv2)
                        except Exception:
                            continue
                    else:
                        ck = None
                        for kn in ("index", "code", "id", "key", "type", "attribute", "attribute_type", "attr_type"):
                            try:
                                ck = getattr(it, kn, None)
                            except Exception:
                                ck = None
                            if ck is not None:
                                break
                        cv = None
                        for vn in ("value", "val", "v"):
                            try:
                                cv = getattr(it, vn, None)
                            except Exception:
                                cv = None
                            if cv is not None:
                                break
                        if ck is None or cv is None:
                            continue
                        ck2 = _key_to_code(ck)
                        cv2 = _val_to_int(cv)
                        if ck2 is None or cv2 is None:
                            continue
                        try:
                            out[int(ck2)] = int(cv2)
                        except Exception:
                            continue
                if out:
                    return out
            except Exception:
                pass

            # flat list [code, value, code, value, ...]
            try:
                if len(v) >= 2 and all(isinstance(i, (int, float, str)) for i in v):
                    if len(v) % 2 == 0:
                        for i in range(0, len(v), 2):
                            ck = _key_to_code(v[i])
                            cv = _val_to_int(v[i + 1])
                            if ck is None or cv is None:
                                continue
                            out[int(ck)] = int(cv)
                        if out:
                            return out
            except Exception:
                pass

        # object with to_dict etc already handled, but try mapping conversion
        m = _slsk_as_mapping(v) or _slsk_to_dict(v)
        if m:
            for kk, vv in m.items():
                try:
                    ck = _key_to_code(kk)
                    cv = _val_to_int(vv)
                    if ck is None or cv is None:
                        continue
                    out[int(ck)] = int(cv)
                except Exception:
                    continue
            if out:
                return out

    return out


def _slsk_guess_lossless_depth_and_rate_from_name(name: str) -> Tuple[Optional[int], Optional[int]]:
    """Best effort fallback when peers omit attributes.

    Returns (bit_depth, sample_rate_hz).
    """
    n = (name or "").lower()
    bit_depth = None
    sample_rate = None

    # bit depth patterns: 16bit, 24 bit, 32-bit
    m = re.search(r"\b(16|20|24|32)\s*[-_ ]?bit\b", n)
    if m:
        try:
            bit_depth = int(m.group(1))
        except Exception:
            bit_depth = None

    # sample rate patterns: 44.1k, 48khz, 96k, 192khz
    m = re.search(r"\b(\d{2,3}(?:\.\d)?)\s*[-_ ]?(?:khz|k)\b", n)
    if m:
        try:
            khz = float(m.group(1))
            sample_rate = int(round(khz * 1000.0))
        except Exception:
            sample_rate = None

    return bit_depth, sample_rate


def _slsk_extract_media_attrs(shared_item: Any, remote_path: str, size: int) -> Dict[str, Any]:
    amap = _slsk_attr_code_map(shared_item)
    bitrate = amap.get(0)
    duration = amap.get(1)
    vbr = amap.get(2)
    sample_rate = amap.get(4)
    bit_depth = amap.get(5)

    # Some library versions expose these directly instead of numeric code pairs.
    if bitrate is None:
        bitrate = _slsk_pick_int(shared_item, "bitrate", "bit_rate", "bitRate", "kbps", "bps")
    if duration is None:
        duration = _slsk_pick_int(shared_item, "duration", "length", "time", "seconds", "secs")
    if vbr is None:
        vbr = _slsk_pick_int(shared_item, "vbr", "is_vbr", "variable_bitrate", "variableBitrate")
    if sample_rate is None:
        sample_rate = _slsk_pick_int(shared_item, "sample_rate", "samplerate", "sampleRate", "rate", "frequency", "hz")
    if bit_depth is None:
        bit_depth = _slsk_pick_int(shared_item, "bit_depth", "bitdepth", "bitDepth", "depth", "bits")

    # Normalize and sanity check
    def sane_int(x, lo, hi):
        try:
            xi = int(x)
        except Exception:
            return None
        if xi < lo or xi > hi:
            return None
        return xi

    # bitrate is usually kbps, but some implementations may provide bps
    bitrate = sane_int(bitrate, 1, 20000000)
    if bitrate is not None and bitrate > 20000:
        try:
            bitrate = int(round(bitrate / 1000.0))
        except Exception:
            pass
    bitrate = sane_int(bitrate, 1, 20000)  # kbps

    duration = sane_int(duration, 0, 60 * 60 * 24 * 7)  # seconds

    # sample rate is typically Hz (44100), but occasionally kHz (44)
    sample_rate = sane_int(sample_rate, 1, 768000)
    if sample_rate is not None and sample_rate < 1000:
        if 8 <= sample_rate <= 768:
            sample_rate = sample_rate * 1000
    sample_rate = sane_int(sample_rate, 1000, 768000)  # Hz

    bit_depth = sane_int(bit_depth, 1, 128)
    vbr = sane_int(vbr, 0, 1)

    name_part = remote_path.replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(name_part)[1].lower().lstrip(".")
    ext = ext or ""

    kind = "file"
    try:
        if ("." + ext) in AUDIO_EXTS:
            kind = "audio"
        elif ("." + ext) in VIDEO_EXTS:
            kind = "video"
    except Exception:
        kind = "file"

    # Fallback: infer common lossless attributes from name when missing
    if kind == "audio" and (bit_depth is None or sample_rate is None):
        bd2, sr2 = _slsk_guess_lossless_depth_and_rate_from_name(name_part)
        if bit_depth is None:
            bit_depth = bd2
        if sample_rate is None:
            sample_rate = sr2

    # Codec is often just the extension for Soulseek shares
    codec = ext.upper() if ext else ""

    return {
        "ext": ext,
        "kind": kind,
        "bitrate": bitrate,
        "bit_depth": bit_depth,
        "sample_rate": sample_rate,
        "duration": duration,
        "vbr": vbr,
        "codec": codec,
    }


def _slsk_guess_kind_ext_attrs(name: str, shared_item: Any) -> Tuple[str, str, Optional[int], Optional[int], Optional[int], Optional[int], Optional[int], str]:
    """Return (kind, ext, bitrate_kbps, bit_depth, sample_rate_hz, duration_sec, vbr_flag, codec)."""
    rp = ""
    try:
        rp = str(_slsk_pick(shared_item, "remote_path", "path", "filename", "file", "name") or "")
    except Exception:
        rp = ""
    if not rp:
        rp = str(name or "")
    size = 0
    try:
        size = int(_slsk_pick(shared_item, "size", "filesize", "file_size", "bytes", "length") or 0)
    except Exception:
        size = 0

    try:
        m = _slsk_extract_media_attrs(shared_item, rp, size)
    except Exception:
        # Fallback: minimal inference from the filename only
        base = (name or "").replace("\\", "/").split("/")[-1]
        ext = os.path.splitext(base)[1].lower().lstrip(".")
        kind = "file"
        try:
            if ("." + ext) in AUDIO_EXTS:
                kind = "audio"
            elif ("." + ext) in VIDEO_EXTS:
                kind = "video"
        except Exception:
            kind = "file"
        codec = ext.upper() if ext else ""
        return kind, ext, None, None, None, None, None, codec

    kind = str(m.get("kind") or "file")
    ext = str(m.get("ext") or "")
    br = m.get("bitrate", None)
    bd = m.get("bit_depth", None)
    sr = m.get("sample_rate", None)
    dur = m.get("duration", None)
    vbr = m.get("vbr", None)
    codec = str(m.get("codec") or "")
    return kind, ext, br, bd, sr, dur, vbr, codec


class SoulseekService:
    def __init__(
        self,
        username: str,
        password: str,
        download_dir: str,
        listening_port: int,
        obfuscated_port: int,
        search_timeout_sec: int = 8,
        search_max_results: int = 60,
    ):
        self.username = (username or "").strip()
        self.password = (password or "").strip()
        self.download_dir = os.path.abspath(download_dir)
        self.listening_port = int(listening_port)
        self.obfuscated_port = int(obfuscated_port)
        self.search_timeout_sec = max(2, int(search_timeout_sec))
        self.search_max_results = max(10, int(search_max_results))

        self._thread = None
        self._loop = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._client = None
        self._start_error = None

        os.makedirs(self.download_dir, exist_ok=True)
        self.incoming_dir = os.path.join(self.download_dir, "_incoming")
        os.makedirs(self.incoming_dir, exist_ok=True)

        self._thread = threading.Thread(target=self._thread_main, name="SoulseekLoop", daemon=True)
        self._thread.start()

        # Wait briefly for startup to either succeed or fail
        self._ready.wait(timeout=15)

    def is_ready(self) -> bool:
        return bool(self._ready.is_set() and self._client is not None and self._start_error is None)

    def start_error(self) -> Optional[str]:
        return self._start_error

    def _thread_main(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.create_task(self._async_start())
            loop.run_forever()
        except Exception as e:
            self._start_error = str(e)
        finally:
            self._ready.set()

    async def _async_start(self):
        try:
            from aioslsk.client import SoulSeekClient
            from aioslsk.settings import Settings, CredentialsSettings

            settings = Settings(credentials=CredentialsSettings(username=self.username, password=self.password))
# Reliability relevant options
            try:
                settings.network.listening.port = int(self.listening_port)
            except Exception:
                pass
            try:
                settings.network.listening.obfuscated_port = int(self.obfuscated_port)
            except Exception:
                pass
            try:
                settings.network.upnp.enabled = False
            except Exception:
                pass
            try:
                settings.network.peer.obfuscate = False
            except Exception:
                pass
            try:
                settings.shares.download = self.incoming_dir
            except Exception:
                pass
            try:
                settings.server.reconnect.auto = True
            except Exception:
                pass

            client = SoulSeekClient(settings)
            self._client = client

            await client.start()
            await client.login()

            # Background poller to integrate transfer progress into Debripod tasks
            asyncio.create_task(self._poll_transfers_loop())

            self._ready.set()
        except Exception as e:
            self._start_error = str(e)
            self._ready.set()

    def submit(self, coro, timeout: int = 30):
        if not self._loop:
            raise RuntimeError("Soulseek loop not initialized")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def submit_nowait(self, coro):
        if not self._loop:
            raise RuntimeError("Soulseek loop not initialized")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)


    def start_search_session(self, session_id: str, query: str) -> None:
        q = (query or "").strip()
        if not q:
            _slsk_session_mark_done(session_id, error="Missing query")
            return
        try:
            self.submit_nowait(self._search_stream_coro(q, session_id))
        except Exception as e:
            _slsk_session_mark_done(session_id, error=str(e))

    def search(self, query: str) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        return self.submit(self._search_coro(q), timeout=self.search_timeout_sec + 10)

    async def _search_coro(self, query: str) -> List[Dict[str, Any]]:
        if not self._client:
            raise RuntimeError("Soulseek client not started")
        # aioslsk search results can arrive asynchronously; wait a short window
        searcher = None
        try:
            searches = getattr(self._client, "searches", None)
            if searches is not None and hasattr(searches, "search"):
                searcher = searches.search
        except Exception:
            searcher = None
        if searcher is None:
            try:
                sm = getattr(self._client, "search_manager", None)
                if sm is not None and hasattr(sm, "search"):
                    searcher = sm.search
            except Exception:
                searcher = None
        if searcher is None:
            raise RuntimeError("Soulseek client does not expose a search manager (expected client.searches.search)")
        req = await searcher(query)
        await asyncio.sleep(min(1.0, max(0.2, self.search_timeout_sec / 10)))
        # Wait up to timeout and keep the largest snapshot (Soulseek results can trickle in)
        end = time.time() + float(self.search_timeout_sec)
        best: List[Any] = []
        while time.time() < end:
            try:
                cur = list(getattr(req, "results", []) or [])
            except Exception:
                cur = []
            if len(cur) > len(best):
                best = cur
            await asyncio.sleep(0.25)
        results = best
# Flatten into {user, remote_path, size} items, grouped by directory later
        items: List[Dict[str, Any]] = []
        for r in results[: self.search_max_results]:
            user = getattr(r, "username", "") or getattr(r, "user", "")
            speed = _slsk_extract_result_speed(r)
            try:
                shared = list(getattr(r, "shared_items", []) or [])
            except Exception:
                shared = []
            for f in shared:
                rp = getattr(f, "filename", None)
                if rp is None:
                    rp = getattr(f, "remote_path", "")
                rp = str(rp or "")
                if not rp:
                    continue
                size = getattr(f, "filesize", None)
                if size is None:
                    size = getattr(f, "size", 0)
                try:
                    size = int(size or 0)
                except Exception:
                    size = 0
                meta = _slsk_extract_media_attrs(f, rp, size)

                ext = meta.get("ext") or ""

                kind = meta.get("kind") or "file"

                bitrate = meta.get("bitrate")

                bit_depth = meta.get("bit_depth")

                sample_rate = meta.get("sample_rate")

                duration = meta.get("duration")

                vbr = meta.get("vbr")

                codec = meta.get("codec") or ""

                items.append({
                    "user": str(user or ""),
                    "speed": int(speed) if speed else 0,
                    "remote_path": rp,
                    "size": size,
                    "ext": ext,
                    "kind": kind,
                    "bitrate": bitrate,
                    "bit_depth": bit_depth,
                    "sample_rate": sample_rate,
                    "duration": duration,
                    "vbr": vbr,
                    "codec": codec,
                })
        return items

    async def _search_stream_coro(self, query: str, session_id: str) -> None:
        if not self._client:
            _slsk_session_mark_done(session_id, error="Soulseek client not started")
            return

        searcher = None
        try:
            searches = getattr(self._client, "searches", None)
            if searches is not None and hasattr(searches, "search"):
                searcher = searches.search
        except Exception:
            searcher = None
        if searcher is None:
            try:
                sm = getattr(self._client, "search_manager", None)
                if sm is not None and hasattr(sm, "search"):
                    searcher = sm.search
            except Exception:
                searcher = None
        if searcher is None:
            _slsk_session_mark_done(session_id, error="Soulseek client does not expose a search manager")
            return

        try:
            req = await searcher(query)
        except Exception as e:
            _slsk_session_mark_done(session_id, error=str(e))
            return

        idle_stop = float(globals().get("SOULSEEK_SEARCH_IDLE_STOP_SEC", 2.5) or 2.5)
        hard_max = float(globals().get("SOULSEEK_SEARCH_HARD_MAX_SEC", 60) or 60)
        start_t = time.time()
        last_growth = start_t
        seen: set = set()

        # Small initial wait to let first packets arrive
        try:
            await asyncio.sleep(0.15)
        except Exception:
            pass

        while True:
            now = time.time()
            if (now - start_t) > hard_max:
                break

            new_items: List[Dict[str, Any]] = []

            try:
                cur = list(getattr(req, "results", []) or [])
            except Exception:
                cur = []

            for r in cur:
                user = getattr(r, "username", "") or getattr(r, "user", "")
                speed = _slsk_extract_result_speed(r)
                try:
                    shared = list(getattr(r, "shared_items", []) or [])
                except Exception:
                    shared = []
                if not user or not shared:
                    continue

                for f in shared:
                    rp = getattr(f, "filename", None)
                    if rp is None:
                        rp = getattr(f, "remote_path", "")
                    rp = str(rp or "")
                    if not rp:
                        continue
                    key = str(user) + "|" + rp
                    if key in seen:
                        continue
                    seen.add(key)

                    size = getattr(f, "filesize", None)
                    if size is None:
                        size = getattr(f, "size", 0)
                    try:
                        size = int(size or 0)
                    except Exception:
                        size = 0

                    meta = _slsk_extract_media_attrs(f, rp, size)
                    ext = meta.get("ext") or ""
                    kind = meta.get("kind") or "file"
                    bitrate = meta.get("bitrate")
                    bit_depth = meta.get("bit_depth")
                    sample_rate = meta.get("sample_rate")
                    duration = meta.get("duration")
                    vbr = meta.get("vbr")
                    codec = meta.get("codec") or ""

                    new_items.append(
                        {
                            "user": str(user or ""),
                            "speed": int(speed) if speed else 0,
                            "remote_path": rp,
                            "size": size,
                            "ext": ext,
                            "kind": kind,
                            "bitrate": bitrate,
                            "bit_depth": bit_depth,
                            "sample_rate": sample_rate,
                            "duration": duration,
                            "vbr": vbr,
                            "codec": codec,
                        }
                    )

                    if len(seen) >= int(self.search_max_results):
                        break
                if len(seen) >= int(self.search_max_results):
                    break

            if new_items:
                last_growth = time.time()
                _slsk_session_add_items(session_id, new_items)

            if len(seen) >= int(self.search_max_results):
                break

            if (time.time() - last_growth) >= idle_stop:
                break

            try:
                await asyncio.sleep(0.25)
            except Exception:
                break

        _slsk_session_mark_done(session_id, error="")


    def browse_user(self, username: str) -> List[Dict[str, Any]]:
        user = (username or "").strip()
        if not user:
            return []
        timeout = max(20, int(self.search_timeout_sec) + 20)
        return self.submit(self._browse_user_coro(user), timeout=timeout)

    async def _browse_user_coro(self, username: str) -> List[Dict[str, Any]]:
        if not self._client:
            raise RuntimeError("Soulseek client not started")

        response = None
        last_error = ""

        async def _try_await(fn, *args, **kwargs):
            val = fn(*args, **kwargs)
            if asyncio.iscoroutine(val):
                return await val
            return val

        async def _run_command(cmd_obj: Any):
            exec_methods = []
            for meth_name in ("execute",):
                meth = getattr(self._client, meth_name, None)
                if callable(meth):
                    exec_methods.append(meth)
            call_dunder = getattr(self._client, "__call__", None)
            if callable(call_dunder):
                exec_methods.append(call_dunder)
            for meth in exec_methods:
                try:
                    out = meth(cmd_obj, response=True)
                    if asyncio.iscoroutine(out):
                        out = await out
                    if out is not None:
                        return out
                except TypeError:
                    try:
                        out = meth(cmd_obj)
                        if asyncio.iscoroutine(out):
                            out = await out
                        if out is not None:
                            return out
                    except Exception as e:
                        nonlocal last_error
                        last_error = str(e)
                except Exception as e:
                    last_error = str(e)
            return None

        # First try command objects from aioslsk.commands. The exact command names
        # differ between releases, so discover them dynamically instead of assuming
        # a single BrowseUserCommand symbol exists.
        try:
            import aioslsk.commands as slsk_commands  # type: ignore
            command_names = []
            for name in dir(slsk_commands):
                lname = str(name).lower()
                if "command" not in lname:
                    continue
                if ("share" in lname) or ("browse" in lname) or ("directory" in lname and "peer" in lname):
                    command_names.append(name)
            preferred = []
            deferred = []
            for name in command_names:
                lname = str(name).lower()
                if ("share" in lname or "browse" in lname) and "directory" not in lname:
                    preferred.append(name)
                else:
                    deferred.append(name)
            for name in preferred + deferred:
                cls = getattr(slsk_commands, name, None)
                if not callable(cls):
                    continue
                variants = [
                    ((username,), {}),
                    ((), {"username": username}),
                    ((username, None), {}),
                    ((username, ""), {}),
                    ((), {"user": username}),
                ]
                for args, kwargs in variants:
                    try:
                        cmd_obj = cls(*args, **kwargs)
                    except TypeError:
                        continue
                    except Exception as e:
                        last_error = str(e)
                        continue
                    try:
                        response = await _run_command(cmd_obj)
                        if response is not None:
                            break
                    except Exception as e:
                        last_error = str(e)
                if response is not None:
                    break
        except Exception:
            pass

        if response is None:
            candidates = []
            for owner_name in dir(self._client):
                if owner_name.startswith("_"):
                    continue
                owner = getattr(self._client, owner_name, None)
                if owner is None:
                    continue
                for meth_name in dir(owner):
                    if meth_name.startswith("_"):
                        continue
                    lname = str(meth_name).lower()
                    if not ("browse" in lname or "share" in lname or ("directory" in lname and "get" in lname)):
                        continue
                    meth = getattr(owner, meth_name, None)
                    if callable(meth):
                        candidates.append(meth)
            for meth in candidates:
                try:
                    response = await _try_await(meth, username)
                    if response is not None:
                        break
                except TypeError:
                    try:
                        response = await _try_await(meth, username=username)
                        if response is not None:
                            break
                    except TypeError:
                        try:
                            response = await _try_await(meth, user=username)
                            if response is not None:
                                break
                        except Exception as e:
                            last_error = str(e)
                    except Exception as e:
                        last_error = str(e)
                except Exception as e:
                    last_error = str(e)

        if response is None:
            raise RuntimeError(last_error or "Could not browse user shares with current aioslsk API")

        try:
            await asyncio.sleep(1.0)
        except Exception:
            pass

        items = _slsk_collect_browse_items(response, user=username)
        if not items:
            for attr_name in ("results", "items", "shared_items", "directories", "files", "value", "payload"):
                try:
                    extra = getattr(response, attr_name, None)
                except Exception:
                    extra = None
                if extra:
                    items = _slsk_collect_browse_items(extra, user=username)
                    if items:
                        break
                if isinstance(response, dict):
                    extra = response.get(attr_name)
                    if extra:
                        items = _slsk_collect_browse_items(extra, user=username)
                        if items:
                            break

        if not items:
            raise RuntimeError("Browse returned no readable shared files")

        dedup: Dict[str, Dict[str, Any]] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            rp = _slsk_norm_remote_path(str(it.get("remote_path") or ""))
            if not rp:
                continue
            it["user"] = username
            it["remote_path"] = rp
            it["directory"] = _slsk_norm_remote_path(str(it.get("directory") or ""))
            dedup[rp] = it
        out = list(dedup.values())
        out.sort(key=lambda x: str(x.get("remote_path") or "").lower())
        return out

    def enqueue_downloads(self, task_id: str, username: str, remote_paths: List[str]) -> None:
        self.submit(self._enqueue_coro(task_id, username, remote_paths), timeout=30)

    async def _enqueue_coro(self, task_id: str, username: str, remote_paths: List[str]) -> None:
        if not self._client:
            raise RuntimeError("Soulseek client not started")
        from aioslsk.transfer.model import TransferDirection

        user = (username or "").strip()
        paths = [p for p in (remote_paths or []) if (p or "").strip()]
        if not user or not paths:
            return

        # Create transfers (idempotent: aioslsk returns existing transfer if already present)
        for rp in paths:
            if get_task(task_id) and get_task(task_id).cancel_event.is_set():
                break
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "download"):
                await tm.download(user, rp)
            else:
                tm_old = getattr(self._client, "transfer_manager", None)
                if tm_old is None or not hasattr(tm_old, "download"):
                    raise RuntimeError("Soulseek client does not expose transfers manager")
                await tm_old.download(user, rp, paused=False)

        set_task(task_id, state="downloading", message="Soulseek downloads queued")

    def abort_task(self, task_id: str) -> None:
        try:
            self.submit(self._abort_task_coro(task_id), timeout=20)
        except Exception:
            pass

    async def _abort_task_coro(self, task_id: str) -> None:
        if not self._client:
            return
        from aioslsk.transfer.model import TransferDirection
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        try:
            files = list(t.slsk_files or [])
        except Exception:
            files = []
        for f in files:
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = f.get("remote_path") or ""
            rp = str(rp)
            if not user or not rp:
                continue
            tr = None
            try:
                tm = getattr(self._client, "transfers", None)
                if tm is not None and hasattr(tm, "transfers"):
                    for _tr in list(getattr(tm, "transfers", []) or []):
                        try:
                            tr_rp = getattr(_tr, "filename", "") or getattr(_tr, "remote_path", "") or getattr(_tr, "path", "")
                            if getattr(_tr, "username", "") == user and _slsk_norm_remote_path(str(tr_rp)).lower() == _slsk_norm_remote_path(rp).lower():
                                d = getattr(_tr, "direction", None)
                                if d is None or getattr(d, "name", str(d)).upper() == "DOWNLOAD":
                                    tr = _tr
                                    break
                        except Exception:
                            continue
                if tr is None:
                    tm_old = getattr(self._client, "transfer_manager", None)
                    if tm_old is not None and hasattr(tm_old, "find_transfer"):
                        tr = tm_old.find_transfer(user, rp, TransferDirection.DOWNLOAD)
            except Exception:
                tr = None
            if tr is not None:
                try:
                    tm = getattr(self._client, "transfers", None)
                    if tm is not None and hasattr(tm, "abort"):
                        await tm.abort(tr)
                    else:
                        tm_old = getattr(self._client, "transfer_manager", None)
                        if tm_old is not None and hasattr(tm_old, "abort"):
                            await tm_old.abort(tr)
                except Exception:
                    pass


    def pause_task(self, task_id: str) -> None:
        try:
            self.submit(self._pause_task_coro(task_id), timeout=20)
        except Exception:
            pass

    def resume_task(self, task_id: str) -> None:
        try:
            self.submit(self._resume_task_coro(task_id), timeout=20)
        except Exception:
            pass

    def pause_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._pause_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    def resume_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._resume_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    def cancel_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._cancel_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    def retry_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._retry_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    async def _find_transfer(self, user: str, rp_norm: str):
        if not self._client:
            return None
        try:
            from aioslsk.transfer.model import TransferDirection
        except Exception:
            TransferDirection = None  # type: ignore

        tr = None
        try:
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "transfers"):
                for _tr in list(getattr(tm, "transfers", []) or []):
                    try:
                        if getattr(_tr, "username", "") != user:
                            continue
                        tr_rp = getattr(_tr, "filename", "") or getattr(_tr, "remote_path", "") or getattr(_tr, "path", "")
                        if _slsk_norm_remote_path(str(tr_rp)).lower() != _slsk_norm_remote_path(str(rp_norm)).lower():
                            continue
                        d = getattr(_tr, "direction", None)
                        if d is not None and getattr(d, "name", str(d)).upper() != "DOWNLOAD":
                            continue
                        tr = _tr
                        break
                    except Exception:
                        continue
            if tr is None:
                tm_old = getattr(self._client, "transfer_manager", None)
                if tm_old is not None and hasattr(tm_old, "find_transfer") and TransferDirection is not None:
                    tr = tm_old.find_transfer(user, rp_norm, TransferDirection.DOWNLOAD)
        except Exception:
            tr = None
        return tr

    async def _pause_transfer(self, tr) -> bool:
        if not self._client or tr is None:
            return False
        try:
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "pause"):
                res = tm.pause(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            tm_old = getattr(self._client, "transfer_manager", None)
            if tm_old is not None and hasattr(tm_old, "pause"):
                res = tm_old.pause(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            if hasattr(tr, "paused"):
                setattr(tr, "paused", True)
                return True
        except Exception:
            pass
        return False

    async def _resume_transfer(self, tr) -> bool:
        if not self._client or tr is None:
            return False
        try:
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "resume"):
                res = tm.resume(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            tm_old = getattr(self._client, "transfer_manager", None)
            if tm_old is not None and hasattr(tm_old, "resume"):
                res = tm_old.resume(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            if hasattr(tr, "paused"):
                setattr(tr, "paused", False)
                return True
        except Exception:
            pass
        return False

    async def _pause_task_coro(self, task_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        files = list(t.slsk_files or [])
        for f in files:
            try:
                fid = str(f.get("file_id") or "")
                if fid:
                    _set_file_control(task_id, fid, paused=True)
            except Exception:
                pass
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                continue
            tr = await self._find_transfer(user, rp)
            await self._pause_transfer(tr)

    async def _resume_task_coro(self, task_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        files = list(t.slsk_files or [])
        for f in files:
            try:
                fid = str(f.get("file_id") or "")
                if fid:
                    _set_file_control(task_id, fid, paused=False)
            except Exception:
                pass
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                continue
            tr = await self._find_transfer(user, rp)
            await self._resume_transfer(tr)

    async def _pause_file_coro(self, task_id: str, file_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, paused=True)
            tr = await self._find_transfer(user, rp)
            await self._pause_transfer(tr)
            return

    async def _resume_file_coro(self, task_id: str, file_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, paused=False)
            tr = await self._find_transfer(user, rp)
            await self._resume_transfer(tr)
            return

    async def _cancel_file_coro(self, task_id: str, file_id: str) -> None:
        if not self._client:
            return
        from aioslsk.transfer.model import TransferDirection
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = str(f.get("remote_path") or "")
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, canceled=True)
            # Abort the specific transfer
            try:
                tm = getattr(self._client, "transfers", None)
                if tm is not None and hasattr(tm, "abort"):
                    tr = await self._find_transfer(user, _slsk_norm_remote_path(rp))
                    if tr is not None:
                        res = tm.abort(tr)
                        if asyncio.iscoroutine(res):
                            await res
                        return
            except Exception:
                pass
            try:
                tm_old = getattr(self._client, "transfer_manager", None)
                if tm_old is not None and hasattr(tm_old, "find_transfer") and hasattr(tm_old, "abort"):
                    tr = tm_old.find_transfer(user, rp, TransferDirection.DOWNLOAD)
                    if tr is not None:
                        res = tm_old.abort(tr)
                        if asyncio.iscoroutine(res):
                            await res
                        return
            except Exception:
                pass
            return

    async def _retry_file_coro(self, task_id: str, file_id: str) -> None:
        if not self._client:
            return
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = str(f.get("remote_path") or "")
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, paused=False, canceled=False)
            # Re-create transfer (idempotent)
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "download"):
                res = tm.download(user, rp)
                if asyncio.iscoroutine(res):
                    await res
            else:
                tm_old = getattr(self._client, "transfer_manager", None)
                if tm_old is None or not hasattr(tm_old, "download"):
                    return
                res = tm_old.download(user, rp, paused=False)
                if asyncio.iscoroutine(res):
                    await res
            return


    async def _poll_transfers_loop(self):
        # No event wiring needed; poll transfer state and file sizes for progress
        try:
            from aioslsk.transfer.model import TransferDirection
        except Exception:
            return

        last_overall: Dict[str, Tuple[float, int]] = {}
        while True:
            await asyncio.sleep(1.0)
            if not self._client:
                continue

            # Snapshot Soulseek tasks
            with TASKS_LOCK:
                slsk_tasks = [t for t in TASKS.values() if (t.source or "").lower() == "soulseek" and t.state not in {"done", "error", "canceled"}]

            for t in slsk_tasks:
                if t.cancel_event.is_set():
                    # keep canceling until transfers are aborted
                    set_task(t.id, state="canceling", message="Canceling Soulseek downloads")
                files = []
                try:
                    files = list(t.slsk_files or [])
                except Exception:
                    files = []

                any_active = False
                any_failed = False
                all_complete = True
                overall_done = 0
                overall_total = 0
                current_file = ""
                current_done = 0
                current_total = None

                now = time.time()

                for f in files:
                    user = (f.get("user") or t.slsk_user or "").strip()
                    rp = str(f.get("remote_path") or "")
                    rp_norm = _slsk_norm_remote_path(rp)
                    total = int(f.get("total") or f.get("size") or 0)
                    final_lp = f.get("local_path")
                    if not final_lp:
                        rel = _slsk_relative_under_directory(t.slsk_directory, rp_norm)
                        rel_parts = [x for x in _slsk_norm_remote_path(rel).split("\\") if x]
                        base_dir = _slsk_task_download_dir(t.slsk_directory)
                        final_lp = os.path.join(base_dir, *rel_parts) if rel_parts else base_dir
                    incoming_lp = f.get("incoming_path") or _slsk_expected_incoming_path(rp)
                    f["local_path"] = final_lp
                    f["incoming_path"] = incoming_lp
                    f["total"] = int(total) if total else 0

                    # done bytes from disk if possible (aioslsk may use temp extensions while downloading)
                    done = 0
                    lp_progress = ""
                    for cand in (incoming_lp, final_lp):
                        if not cand:
                            continue
                        p = _slsk_resolve_local_progress_path(cand)
                        try:
                            if p and os.path.exists(p):
                                lp_progress = p
                                break
                        except Exception:
                            continue
                    try:
                        if os.path.exists(lp_progress):
                            done = int(os.path.getsize(lp_progress))
                    except Exception:
                        done = int(f.get("done") or 0)

                    # estimate speed
                    prev_sz = float(f.get("_prev_sz") or 0)
                    prev_t = float(f.get("_prev_t") or 0)
                    speed = 0.0
                    if prev_t > 0 and now > prev_t:
                        speed = max(0.0, (done - prev_sz) / max(0.001, (now - prev_t)))
                    f["_prev_sz"] = float(done)
                    f["_prev_t"] = float(now)
                    f["speed"] = float(speed)
                    f["done"] = int(done)

                    # transfer state from manager if available
                    tr_state = ""
                    tr = None
                    try:
                        tm = getattr(self._client, "transfers", None)
                        if tm is not None and hasattr(tm, "transfers"):
                            for _tr in list(getattr(tm, "transfers", []) or []):
                                try:
                                    if getattr(_tr, "username", "") != user:
                                        continue
                                    tr_rp = getattr(_tr, "filename", "") or getattr(_tr, "remote_path", "") or getattr(_tr, "path", "")
                                    if _slsk_norm_remote_path(str(tr_rp)).lower() != rp_norm.lower():
                                        continue
                                    d = getattr(_tr, "direction", None)
                                    if d is not None and getattr(d, "name", str(d)).upper() != "DOWNLOAD":
                                        continue
                                    tr = _tr
                                    break
                                except Exception:
                                    continue
                        if tr is None:
                            tm_old = getattr(self._client, "transfer_manager", None)
                            if tm_old is not None and hasattr(tm_old, "find_transfer"):
                                tr = tm_old.find_transfer(user, rp, TransferDirection.DOWNLOAD)
                    except Exception:
                        tr = None
                    if tr is not None:
                        try:
                            tr_state = getattr(getattr(tr, "state", ""), "name", str(getattr(tr, "state", "")))
                        except Exception:
                            tr_state = ""
                    # Prefer transfer-provided numbers when available (filesize/bytes received/speed)
                    tr_done, tr_total, tr_speed, tr_state2 = _slsk_extract_transfer_progress(tr)
                    if tr_total > 0:
                        if total <= 0 or tr_total > total:
                            total = int(tr_total)
                    if tr_done > 0 and tr_done > done:
                        done = int(tr_done)
                    if tr_speed > 0:
                        speed = float(tr_speed)
                    if tr_state2:
                        tr_state = tr_state2
                    f["total"] = int(total) if total else 0
                    f["done"] = int(done)
                    f["speed"] = float(speed)

                    # Apply per-file controls and expose raw transfer status/error
                    fid = str(f.get("file_id") or "")
                    ctl = _get_file_control(t.id, fid) if fid else {}
                    paused_ctl = bool(ctl.get("paused"))
                    canceled_ctl = bool(ctl.get("canceled"))
                    paused_tr = _slsk_transfer_is_paused(tr)
                    err = _slsk_extract_transfer_error(tr)
                    if err:
                        f["error"] = str(err)
                    if paused_ctl or paused_tr:
                        f["paused"] = True
                    if canceled_ctl:
                        f["canceled"] = True

                    state_raw = (tr_state or f.get("state") or "")
                    state_tok = _slsk_clean_state_token(state_raw)
                    f["state_raw"] = state_tok or f.get("state_raw") or ""
                    state = _slsk_normalize_state(state_tok, bool(f.get("paused")), bool(f.get("canceled")), int(done), int(total), bool(f.get("error")))
                    f["state"] = state


                    # If a file completed but total is unknown, lock total to done so overall can reach 100
                    if state == "complete" and (total <= 0) and done > 0:
                        total = int(done)
                        f["total"] = int(total)

                    # When a file completes, move it from the incoming folder into the task folder
                    if state == "complete":
                        try:
                            src = _slsk_resolve_local_progress_path(incoming_lp)
                        except Exception:
                            src = incoming_lp
                        dst = final_lp
                        try:
                            if src and dst and os.path.abspath(src) != os.path.abspath(dst) and os.path.exists(src):
                                moved_to = _safe_move_file(src, dst)
                                final_lp = moved_to or dst
                                f["local_path"] = final_lp
                        except Exception:
                            pass

                    if state in {"failed", "incomplete"}:
                        any_failed = True
                    if state not in {"complete"}:
                        all_complete = False
                    if state in {"queued", "downloading", "requesting", "initializing", "connecting"}:
                        any_active = True
                        if not current_file:
                            current_file = rp_norm.split("\\")[-1] if rp_norm else ""
                            current_done = done
                            current_total = total if total > 0 else None

                    overall_done += done
                    overall_total += total

                # Write updates back
                set_task(t.id, slsk_files=files, overall_done=overall_done, overall_total=(overall_total if overall_total > 0 else None), current_file=current_file, current_done=current_done, current_total=current_total)

                if all_complete and files:
                    # mark done
                    saved = []
                    for f in files:
                        lp = f.get("local_path") or ""
                        if lp:
                            saved.append(lp)
                    set_task(t.id, state="done", message="Soulseek download complete", downloaded_files=saved, downloads_complete=True)
                else:
                    if t.cancel_event.is_set():
                        # If canceled, consider it canceled once nothing is active
                        if not any_active:
                            set_task(t.id, state="canceled", message="Canceled", downloads_complete=False)
                    else:
                        any_paused = any(bool(ff.get("paused")) for ff in files)
                        if t.pause_event.is_set() or bool(getattr(t, "paused", False)) or (any_paused and not any_active and not all_complete):
                            set_task(t.id, state="paused", message="Paused")
                        elif any_failed and not any_active:
                            set_task(t.id, state="error", message="Soulseek download finished with errors")
                        else:
                            set_task(t.id, state="downloading", message="Soulseek downloading")


def _slsk_extract_result_speed(r: Any) -> int:
    """
    Best-effort extraction of a user's advertised connection speed from aioslsk search result objects.
    Many Soulseek clients surface a speed value, but different library versions name it differently.
    Returns an integer speed in bytes/sec when possible, else 0.
    """
    if r is None:
        return 0

    # Common attribute names seen across Soulseek client implementations / wrappers
    cand_attrs = (
        "speed",
        "upload_speed",
        "connection_speed",
        "avg_speed",
        "download_speed",
        "ul_speed",
        "dl_speed",
        "bandwidth",
        "rate",
    )
    for a in cand_attrs:
        try:
            v = getattr(r, a, None)
        except Exception:
            v = None
        if v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if not math.isfinite(f) or f <= 0:
            continue
        # Heuristic: some APIs report KB/s; if it looks too small, treat as KB/s.
        if f < 1024 and f > 0:
            f = f * 1024.0
        try:
            return int(f)
        except Exception:
            continue

    # Sometimes the info is nested under a "user" object
    try:
        u = getattr(r, "user", None)
    except Exception:
        u = None
    if u is not None:
        for a in cand_attrs:
            try:
                v = getattr(u, a, None)
            except Exception:
                v = None
            if v is None:
                continue
            try:
                f = float(v)
            except Exception:
                continue
            if not math.isfinite(f) or f <= 0:
                continue
            if f < 1024 and f > 0:
                f = f * 1024.0
            try:
                return int(f)
            except Exception:
                continue

    return 0


def download_stream(url: str, out_path: str, task: Task, file_id: Optional[str] = None) -> None:
    # Supports task-level pause and per-file pause/cancel via TASKS[file].file_controls
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as r:
        r.raise_for_status()
        total = r.headers.get("Content-Length")
        total_i = int(total) if total and str(total).isdigit() else None

        if file_id:
            _update_task_file_entry(task.id, "rd_files", file_id, total=(int(total_i) if total_i is not None else 0))

        set_task(task.id, current_total=total_i, current_done=0)

        done = 0
        last_t = time.time()
        last_done = 0

        # Ensure parent folder exists
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        except Exception:
            pass

        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                check_canceled(task)

                # Task pause
                while True:
                    check_canceled(task)
                    if not task.pause_event.is_set():
                        break
                    if file_id:
                        _update_task_file_entry(task.id, "rd_files", file_id, state="paused")
                    time.sleep(0.15)

                # Per-file control
                if file_id:
                    while True:
                        check_canceled(task)
                        ctl = _get_file_control(task.id, file_id)
                        if ctl.get("canceled"):
                            raise CancelledFile("Canceled file")
                        if ctl.get("paused"):
                            _update_task_file_entry(task.id, "rd_files", file_id, state="paused")
                            time.sleep(0.15)
                            continue
                        break

                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)

                # speed estimate
                now = time.time()
                dt = max(0.001, now - last_t)
                spd = max(0.0, (done - last_done) / dt)
                last_t = now
                last_done = done

                set_task(task.id, current_done=done)
                if file_id:
                    _update_task_file_entry(task.id, "rd_files", file_id, done=int(done), speed=float(spd), state="downloading")



def rd_add_magnet(magnet: str) -> str:
    status, text, js = rd_request("POST", "/torrents/addMagnet", data={"magnet": magnet})
    if status not in (200, 201) or not isinstance(js, dict):
        raise RuntimeError(f"addMagnet failed ({status}): {text[:300]}")
    tid = js.get("id")
    if not tid:
        raise RuntimeError("addMagnet did not return an id")
    return str(tid)


def rd_select_all_files(torrent_id: str) -> None:
    status, text, _ = rd_request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": "all"})
    if status not in (200, 204, 202):
        raise RuntimeError(f"selectFiles failed ({status}): {text[:300]}")



def rd_select_files(torrent_id: str, file_ids: List[int]) -> None:
    clean: List[str] = []
    for x in (file_ids or []):
        try:
            clean.append(str(int(x)))
        except Exception:
            continue
    if not clean:
        raise RuntimeError("No files selected")
    files_str = ",".join(clean)
    status, text, _ = rd_request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": files_str})
    if status not in (200, 204, 202):
        raise RuntimeError(f"selectFiles failed ({status}): {text[:300]}")


def rd_torrent_info(torrent_id: str) -> dict:
    status, text, js = rd_request("GET", f"/torrents/info/{torrent_id}")
    if status != 200 or not isinstance(js, dict):
        raise RuntimeError(f"torrents/info failed ({status}): {text[:300]}")
    return js


def rd_unrestrict(link: str) -> dict:
    status, text, js = rd_request("POST", "/unrestrict/link", data={"link": link})
    if status != 200 or not isinstance(js, dict):
        raise RuntimeError(f"unrestrict/link failed ({status}): {text[:300]}")
    if not js.get("download"):
        raise RuntimeError("unrestrict/link did not return a download url")
    return js


def rd_delete_torrent_best_effort(torrent_id: Optional[str]) -> None:
    if not torrent_id:
        return
    rd_request("DELETE", f"/torrents/delete/{torrent_id}")


# =========================
# Video auto transcode queue
# =========================

VIDEO_BROWSER_TARGET_EXT = "mp4"

_VIDEO_POST_QUEUE: "queue.Queue[Tuple[str, str]]" = queue.Queue()
_VIDEO_POST_THREAD: Optional[threading.Thread] = None
_VIDEO_POST_GUARD = threading.Lock()


def _ensure_video_post_worker() -> None:
    global _VIDEO_POST_THREAD
    with _VIDEO_POST_GUARD:
        if _VIDEO_POST_THREAD is not None and _VIDEO_POST_THREAD.is_alive():
            return
        _VIDEO_POST_THREAD = threading.Thread(target=_video_post_worker, name="video_post_worker", daemon=True)
        _VIDEO_POST_THREAD.start()


def enqueue_video_postprocess(task_id: str, src_path: str) -> None:
    if not AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY:
        return
    if not is_video(src_path):
        return
    try:
        if not os.path.exists(src_path) or not os.path.isfile(src_path):
            return
    except OSError:
        return

    _ensure_video_post_worker()

    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if t:
            t.video_post_total += 1
            t.video_post_state = "queued"
            t.video_post_message = "Queued for browser compatibility"

    _VIDEO_POST_QUEUE.put((task_id, src_path))


def _probe_duration_seconds(path: str) -> float:
    try:
        j = ffprobe_json(path)
        dur = (j.get("format") or {}).get("duration")
        if dur is not None:
            return float(dur)
    except Exception:
        return 0.0
    return 0.0


def _inject_progress_args(args: List[str]) -> List[str]:
    # Insert "-progress pipe:1 -nostats" so we can parse out_time_ms
    out = list(args)
    try:
        i = out.index("-loglevel")
        if i + 1 < len(out):
            insert_at = i + 2
        else:
            insert_at = len(out)
    except ValueError:
        insert_at = 1 if out else 0
    out[insert_at:insert_at] = ["-progress", "pipe:1", "-nostats"]
    return out


def _run_ffmpeg_to_tmp_with_progress(
    args: List[str],
    tmp_path: str,
    *,
    stage: str,
    src_path: str,
    task_id: str,
    cancel_event: threading.Event,
    total_duration_s: float,
) -> Tuple[bool, str]:
    args2 = _inject_progress_args(args)

    total_us = int(max(0.0, float(total_duration_s)) * 1000000.0) if total_duration_s else 0
    set_task(
        task_id,
        video_post_state=stage,
        video_post_message="Running ffmpeg",
        video_post_current_file=os.path.basename(src_path),
        video_post_current_done=0,
        video_post_current_total=(total_us if total_us > 0 else None),
    )

    stderr_lines: List[str] = []
    try:
        p = subprocess.Popen(
            args2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )
    except FileNotFoundError:
        _safe_remove(tmp_path)
        return False, f"Command not found: {args2[0]}"
    except Exception as e:
        _safe_remove(tmp_path)
        return False, str(e)

    def _drain_stderr():
        try:
            if p.stderr:
                for line in p.stderr:
                    stderr_lines.append(line.rstrip("\n"))
        except Exception:
            pass

    th = threading.Thread(target=_drain_stderr, daemon=True)
    th.start()

    out_time_us = 0
    try:
        if p.stdout:
            for line in p.stdout:
                if cancel_event.is_set():
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    break
                line = (line or "").strip()
                if not line or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "out_time_ms":
                    try:
                        # ffmpeg reports microseconds here
                        out_time_us = int(float(v))
                    except Exception:
                        out_time_us = out_time_us
                    if total_us > 0:
                        done_us = min(max(0, out_time_us), total_us)
                        set_task(task_id, video_post_current_done=done_us)
                elif k == "progress" and v == "end":
                    if total_us > 0:
                        set_task(task_id, video_post_current_done=total_us)
    except Exception:
        pass

    try:
        code = p.wait()
    except Exception:
        code = 1

    try:
        th.join(timeout=0.5)
    except Exception:
        pass

    err = "\n".join(stderr_lines).strip()
    out = ""  # progress output not kept

    if cancel_event.is_set():
        _safe_remove(tmp_path)
        try:
            _record_ffmpeg_failure(stage, args2, code, out, err, src_path, tmp_path)
        except Exception:
            pass
        return False, "Canceled"

    if code == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
        return True, ""

    _safe_remove(tmp_path)
    log_path = _record_ffmpeg_failure(stage, args2, code, out, err, src_path, tmp_path)
    msg = err.strip() or "ffmpeg failed"
    if log_path:
        msg = msg + f"\nLog saved to: {log_path}"
    msg = msg + f"\nCache dir: {transcode_cache_dir()}"
    return False, msg


def _unique_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    if not os.path.exists(path):
        return path
    n = 1
    while True:
        cand = f"{base} ({n}){ext}"
        if not os.path.exists(cand):
            return cand
        n += 1


def _video_output_paths(src_path: str) -> Tuple[str, str]:
    base, ext = os.path.splitext(src_path)
    ext_l = (ext or "").lower()
    target_ext = "." + VIDEO_BROWSER_TARGET_EXT
    desired = base + target_ext

    if REPLACE_ORIGINAL:
        # In replace mode, prefer base.mp4 even if src was already mp4 (we will do an atomic replace at the end).
        final_path = desired
    else:
        # Keep original; avoid overwriting existing outputs.
        final_path = desired
        if os.path.abspath(final_path) == os.path.abspath(src_path):
            final_path = base + ".browser" + target_ext
        final_path = _unique_path(final_path)

    tmp_key = sha1_text(os.path.abspath(src_path) + "|browser|" + final_path)
    tmp_path = os.path.join(transcode_cache_dir(), f"{tmp_key}.tmp{target_ext}")
    _safe_remove(tmp_path)
    return final_path, tmp_path


def _finalize_video_output(src_path: str, out_final: str, tmp_path: str) -> str:
    if REPLACE_ORIGINAL:
        # Delete original only after we have a valid tmp output.
        if os.path.abspath(out_final) == os.path.abspath(src_path):
            # Replace in-place.
            try:
                os.replace(tmp_path, src_path)
            except Exception:
                # Fall back to explicit remove then replace
                try:
                    _safe_remove(src_path)
                except Exception:
                    pass
                os.replace(tmp_path, src_path)
            return src_path

        # Replace into base.mp4 and then delete original.
        os.replace(tmp_path, out_final)
        _safe_remove(src_path)
        return out_final

    os.replace(tmp_path, out_final)
    return out_final


def _mark_video_job_done(task_id: str, *, msg: str, state: str, src_path: str, out_path: str) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        t.video_post_done += 1
        t.video_post_state = state
        t.video_post_message = msg
        t.video_post_current_file = ""
        t.video_post_current_done = 0
        t.video_post_current_total = None

        if out_path and src_path and os.path.abspath(out_path) != os.path.abspath(src_path):
            try:
                t.downloaded_files = [out_path if os.path.abspath(p) == os.path.abspath(src_path) else p for p in t.downloaded_files]
            except Exception:
                pass

        # If downloads are finished and all post jobs are done, mark task finished.
        if t.downloads_complete and t.video_post_done >= t.video_post_total and t.state not in ("done", "error", "canceled"):
            t.state = "done"
            t.message = "Finished"


def _ensure_browser_compatible_video(task_id: str, src_path: str) -> str:
    # If already browser compatible (mp4/webm with compatible codecs), skip.
    ext = os.path.splitext(src_path)[1].lower().lstrip(".")
    si = _primary_stream_info(src_path)
    if ext in ("mp4", "m4v", "mov", "webm"):
        v_ok, a_ok = _browser_compatible_for_target(ext, si.get("v_codec"), si.get("v_pix_fmt"), si.get("a_codec"))
        if v_ok and a_ok:
            return src_path

    out_final, tmp_path = _video_output_paths(src_path)

    # Decide transmux vs transcode into mp4.
    v_ok_t, a_ok_t = _browser_compatible_for_target(VIDEO_BROWSER_TARGET_EXT, si.get("v_codec"), si.get("v_pix_fmt"), si.get("a_codec"))
    dur = _probe_duration_seconds(src_path)

    t = get_task(task_id)
    cancel_ev = t.cancel_event if t else threading.Event()

    if v_ok_t and a_ok_t:
        args = _build_transmux_args(src_path, VIDEO_BROWSER_TARGET_EXT, tmp_path, first_audio_only=True)
        ok, err = _run_ffmpeg_to_tmp_with_progress(
            args,
            tmp_path,
            stage="transmuxing",
            src_path=src_path,
            task_id=task_id,
            cancel_event=cancel_ev,
            total_duration_s=dur,
        )
        if not ok:
            if (err or "").strip().lower() == "canceled":
                raise Cancelled("Canceled")
            raise RuntimeError(err.strip() or "transmux failed")
    else:
        args = _build_smart_transcode_args(src_path, VIDEO_BROWSER_TARGET_EXT, tmp_path, video_ok=v_ok_t, audio_ok=a_ok_t)
        ok, err = _run_ffmpeg_to_tmp_with_progress(
            args,
            tmp_path,
            stage="transcoding",
            src_path=src_path,
            task_id=task_id,
            cancel_event=cancel_ev,
            total_duration_s=dur,
        )
        if not ok:
            if (err or "").strip().lower() == "canceled":
                raise Cancelled("Canceled")
            # Fall back to full transcode
            _safe_remove(tmp_path)
            args2 = _build_transcode_args(src_path, VIDEO_BROWSER_TARGET_EXT, tmp_path)
            ok2, err2 = _run_ffmpeg_to_tmp_with_progress(
                args2,
                tmp_path,
                stage="transcoding",
                src_path=src_path,
                task_id=task_id,
                cancel_event=cancel_ev,
                total_duration_s=dur,
            )
            if not ok2:
                if (err2 or "").strip().lower() == "canceled":
                    raise Cancelled("Canceled")
                raise RuntimeError((err2 or err or "transcode failed").strip())

    return _finalize_video_output(src_path, out_final, tmp_path)


def _video_post_worker() -> None:
    while True:
        job = _VIDEO_POST_QUEUE.get()
        try:
            task_id, src_path = job
        except Exception:
            _VIDEO_POST_QUEUE.task_done()
            continue

        try:
            t = get_task(task_id)
            if not t:
                continue
            if t.cancel_event.is_set() or t.state in ("canceled", "error"):
                if t.cancel_event.is_set() and t.state != "canceled":
                    set_task(task_id, state="canceled", message="Canceled", video_post_state="canceled", video_post_message="Canceled")
                _mark_video_job_done(task_id, msg="Canceled" if t.cancel_event.is_set() else "Skipped", state=("canceled" if t.cancel_event.is_set() else "skipped"), src_path=src_path, out_path=src_path)
                continue

            # Mark in-progress
            set_task(task_id, video_post_state="starting", video_post_message="Checking browser compatibility", video_post_current_file=os.path.basename(src_path))

            try:
                out_path = _ensure_browser_compatible_video(task_id, src_path)
                if os.path.abspath(out_path) == os.path.abspath(src_path):
                    _mark_video_job_done(task_id, msg="Already browser compatible", state="skipped", src_path=src_path, out_path=out_path)
                else:
                    _mark_video_job_done(task_id, msg="Browser compatible output created", state="done", src_path=src_path, out_path=out_path)
            except Cancelled:
                set_task(task_id, state="canceled", message="Canceled", video_post_state="canceled", video_post_message="Canceled")
                _mark_video_job_done(task_id, msg="Canceled", state="canceled", src_path=src_path, out_path=src_path)
            except Exception as e:
                # Record error but allow other tasks to continue
                set_task(task_id, state="error", message=str(e), video_post_state="error", video_post_message=str(e))
                _mark_video_job_done(task_id, msg=str(e), state="error", src_path=src_path, out_path=src_path)

        finally:
            _VIDEO_POST_QUEUE.task_done()





def _rd_recompute_overall_from_files(task_id: str) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        files = list(getattr(t, "rd_files", []) or [])
    od = 0
    ot = 0
    have_total = False
    for f in files:
        try:
            d = int(f.get("done") or 0)
            tot = int(f.get("total") or 0)
        except Exception:
            d = 0
            tot = 0
        od += max(0, d)
        if tot > 0:
            ot += tot
            have_total = True
    set_task(task_id, overall_done=int(od), overall_total=(int(ot) if have_total and ot > 0 else None))


def _rd_download_from_queue(task_id: str) -> List[str]:
    task = get_task(task_id)
    if not task:
        return []

    downloaded_paths: List[str] = []

    while True:
        task = get_task(task_id)
        if not task:
            break
        check_canceled(task)

        # Task pause
        while task.pause_event.is_set():
            check_canceled(task)
            time.sleep(0.2)

        # Pick next queued file
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            entries = list(getattr(tcur, "rd_files", []) or []) if tcur else []
        next_entry: Optional[Dict[str, Any]] = None
        for e in entries:
            st = str(e.get("state") or "").lower()
            if st == "queued":
                next_entry = e
                break
        if not next_entry:
            break

        file_id = str(next_entry.get("file_id") or "")
        link = str(next_entry.get("link") or "")
        seq = int(next_entry.get("seq") or 0)
        if not file_id or not link:
            _update_task_file_entry(task_id, "rd_files", file_id, state="failed", error="Missing link")
            _rd_recompute_overall_from_files(task_id)
            continue

        ctl = _get_file_control(task_id, file_id)
        if ctl.get("canceled"):
            _update_task_file_entry(task_id, "rd_files", file_id, state="canceled", error="")
            _rd_recompute_overall_from_files(task_id)
            continue

        try:
            _update_task_file_entry(task_id, "rd_files", file_id, state="requesting", error="")
            un = rd_unrestrict(link)
            dl_url = un["download"]
            filename = sanitize_filename(un.get("filename") or next_entry.get("name") or f"file_{seq or 1}")
        except Exception as e:
            _update_task_file_entry(task_id, "rd_files", file_id, state="failed", error=str(e))
            _rd_recompute_overall_from_files(task_id)
            continue

        # Determine output path (stable per file_id)
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            cur_files = list(getattr(tcur, "rd_files", []) or []) if tcur else []
            existing_out = ""
            for ff in cur_files:
                if str(ff.get("file_id") or "") == file_id:
                    existing_out = str(ff.get("out_path") or "")
                    break

        if existing_out:
            out_path = existing_out
        else:
            out_path = os.path.join(task.task_dir, filename)
            base, ext = os.path.splitext(out_path)
            n = 1
            while os.path.exists(out_path):
                out_path = f"{base} ({n}){ext}"
                n += 1
            _update_task_file_entry(task_id, "rd_files", file_id, out_path=out_path, name=os.path.basename(out_path))

        set_task(task_id, current_file=os.path.basename(out_path), current_done=0, current_total=None)

        try:
            download_stream(dl_url, out_path, task, file_id=file_id)
            downloaded_paths.append(out_path)
            _update_task_file_entry(task_id, "rd_files", file_id, state="complete", error="")
            try:
                enqueue_video_postprocess(task_id, out_path)
            except Exception:
                pass
        except CancelledFile:
            try:
                if out_path and os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            _update_task_file_entry(task_id, "rd_files", file_id, state="canceled", error="")
        except Cancelled:
            raise
        except Exception as e:
            _update_task_file_entry(task_id, "rd_files", file_id, state="failed", error=str(e))

        _rd_recompute_overall_from_files(task_id)

    # Return list of completed file paths (deduped)
    with TASKS_LOCK:
        tcur = TASKS.get(task_id)
        entries = list(getattr(tcur, "rd_files", []) or []) if tcur else []
    completed: List[str] = []
    for e in entries:
        if str(e.get("state") or "").lower() == "complete":
            op = str(e.get("out_path") or "")
            if op:
                completed.append(op)
    # Deduplicate while keeping order
    seen = set()
    uniq: List[str] = []
    for p in completed + downloaded_paths:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def rd_download_remaining_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return
    if (task.source or "").lower() != "rd":
        return
    try:
        set_task(task_id, state="downloading", message="Retrying queued files")
        completed = _rd_download_from_queue(task_id)
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            entries = list(getattr(tcur, "rd_files", []) or []) if tcur else []
        any_failed = any(str(e.get("state") or "").lower() == "failed" for e in entries)
        all_done = all(str(e.get("state") or "").lower() in {"complete", "canceled"} for e in entries) if entries else True
        set_task(task_id, downloaded_files=completed, current_file="", current_done=0, current_total=None, downloads_complete=bool(all_done and not any_failed))
        if any_failed:
            set_task(task_id, state="error", message="Some files failed. You can retry failed files.")
        elif all_done:
            set_task(task_id, state="done", message="Finished")
        else:
            set_task(task_id, state="downloading", message="Downloading")
    except Cancelled:
        set_task(task_id, state="canceled", message="Canceled", current_file="", current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state="error", message=str(e), current_file="", current_done=0, current_total=None)



def worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return

    try:
        check_canceled(task)

        if str(task.source or '').lower() == 'youtube':
            return youtube_worker(task_id)

        torrent_id = task.torrent_id
        if torrent_id:
            set_task(task_id, state="selecting", message="Selecting files")
        else:
            if not task.magnet:
                raise RuntimeError("Missing magnet")
            set_task(task_id, state="adding", message="Adding magnet to Real Debrid")
            torrent_id = rd_add_magnet(task.magnet)
            set_task(task_id, torrent_id=torrent_id)
            check_canceled(task)
            set_task(task_id, state="selecting", message="Selecting files")

        if task.rd_selected_file_ids:
            rd_select_files(torrent_id, task.rd_selected_file_ids)
        else:
            rd_select_all_files(torrent_id)
        check_canceled(task)

        set_task(task_id, state="waiting", message="Waiting for Real Debrid to cache the torrent")
        start = time.time()
        info = {}
        while True:
            check_canceled(task)
            if time.time() - start > MAX_TORRENT_WAIT_SECONDS:
                raise RuntimeError("Timed out waiting for Real Debrid to finish caching the torrent")
            info = rd_torrent_info(torrent_id)
            status = str(info.get("status", "")).lower()
            links = info.get("links") or []
            if status == "downloaded" and isinstance(links, list) and len(links) > 0:
                break
            if status in {"error", "magnet_error", "dead"}:
                raise RuntimeError(f"Real Debrid reported status: {status}")
            time.sleep(POLL_INTERVAL_SECONDS)

        links = info.get("links") or []
        if not isinstance(links, list) or not links:
            raise RuntimeError("No downloadable links available from Real Debrid")

        if len(links) > MAX_FILES_PER_TORRENT:
            links = links[:MAX_FILES_PER_TORRENT]

        set_task(task_id, state="downloading", message=f"Downloading {len(links)} file(s)")

        # Initialize per-file status entries
        rd_files: List[Dict[str, Any]] = []
        for i, lnk in enumerate(links, start=1):
            fid = hashlib.sha1(str(lnk).encode("utf-8", "ignore")).hexdigest()[:16]
            rd_files.append(
                {
                    "file_id": fid,
                    "seq": int(i),
                    "link": str(lnk),
                    "name": "",
                    "out_path": "",
                    "total": 0,
                    "done": 0,
                    "speed": 0.0,
                    "state": "queued",
                    "error": "",
                    "paused": False,
                    "canceled": False,
                }
            )
            _set_file_control(task_id, fid, paused=False, canceled=False)

        set_task(task_id, rd_files=rd_files, overall_done=0, overall_total=None)

        downloaded_paths = _rd_download_from_queue(task_id)

        set_task(
            task_id,
            downloaded_files=downloaded_paths,
            current_file="",
            current_done=0,
            current_total=None,
            downloads_complete=True,
        )
        # Determine whether any files failed so the task can report errors while still keeping completed files
        with TASKS_LOCK:
            _tcur = TASKS.get(task_id)
            _entries = list(getattr(_tcur, "rd_files", []) or []) if _tcur else []
        any_failed = any(str(e.get("state") or "").lower() == "failed" for e in _entries)
        all_ok = all(str(e.get("state") or "").lower() in {"complete", "canceled"} for e in _entries) if _entries else True
        set_task(task_id, downloads_complete=bool(all_ok and not any_failed))

        task2 = get_task(task_id)
        if task2 and task2.video_post_total > task2.video_post_done and task2.state not in ("error", "canceled"):
            set_task(task_id, state="postprocessing", message="Downloaded. Processing videos for browser compatibility")
        else:
            if any_failed:
                set_task(task_id, state="error", message="Some files failed. You can retry failed files.")
            else:
                set_task(task_id, state="done", message="Finished")

    except Cancelled:
        rd_delete_torrent_best_effort(task.torrent_id)
        set_task(task_id, state="canceled", message="Canceled", current_file="", current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state="error", message=str(e), current_file="", current_done=0, current_total=None)


def _youtube_ytdlp_parse_int(raw: Any) -> int:
    try:
        s = str(raw or '').strip()
        if not s or s.lower() in {'none', 'na', 'n/a'}:
            return 0
        return int(float(s))
    except Exception:
        return 0


def _youtube_ytdlp_parse_speed(raw: Any) -> float:
    try:
        s = str(raw or '').strip()
        if not s or s.lower() in {'none', 'na', 'n/a'}:
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def _youtube_find_downloaded_path(task_dir: str, base_title: str, preferred_ext: str = '') -> str:
    folder = str(task_dir or '').strip() or '.'
    stem = sanitize_filename(str(base_title or 'youtube'))
    pref = str(preferred_ext or '').strip().lower().lstrip('.')
    try:
        names = sorted(os.listdir(folder), key=lambda x: os.path.getmtime(os.path.join(folder, x)), reverse=True)
    except Exception:
        return ''
    preferred = []
    fallback = []
    for name in names:
        if not name.startswith(stem):
            continue
        cand = os.path.join(folder, name)
        if not os.path.isfile(cand):
            continue
        ext = os.path.splitext(name)[1].lstrip('.').lower()
        if pref and ext == pref:
            preferred.append(cand)
        else:
            fallback.append(cand)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return ''


def _youtube_pick_next_entry(task_id: str) -> Optional[Dict[str, Any]]:
    with TASKS_LOCK:
        tcur = TASKS.get(task_id)
        entries = list(getattr(tcur, 'rd_files', []) or []) if tcur else []
    for e in entries:
        file_id = str(e.get('file_id') or '')
        st = str(e.get('state') or '').lower()
        ctl = _get_file_control(task_id, file_id) if file_id else {}
        if ctl.get('canceled'):
            _update_task_file_entry(task_id, 'rd_files', file_id, state='canceled', canceled=True, error='')
            continue
        if st == 'queued':
            return e
        if st == 'paused' and not ctl.get('paused'):
            return e
    return None


def _youtube_run_download(task_id: str, entry: Dict[str, Any], seq: int, total_count: int) -> Optional[str]:
    task = get_task(task_id)
    if not task:
        return None
    file_id = str(entry.get('file_id') or '')
    if not file_id:
        raise RuntimeError('Missing file id')
    ctl = _get_file_control(task_id, file_id)
    if ctl.get('canceled'):
        _update_task_file_entry(task_id, 'rd_files', file_id, state='canceled', canceled=True, error='')
        return None
    if ctl.get('paused'):
        _update_task_file_entry(task_id, 'rd_files', file_id, state='paused', paused=True, error='')
        return None

    title = sanitize_filename(str(entry.get('name') or entry.get('title') or 'youtube'))
    ext = str(entry.get('ext') or '').strip().lower() or 'mp4'
    format_id = str(entry.get('format_id') or entry.get('itag') or entry.get('file_id') or '').strip()
    media = str(entry.get('media') or '').strip().lower()
    out_tpl = os.path.join(task.task_dir, title + '.%(ext)s')
    preferred_out = os.path.join(task.task_dir, title + '.' + ext)

    args = _yt_dlp_base_args()
    selector = _yt_stream_format_selector({'format_id': format_id, 'itag': format_id, 'file_id': format_id, 'media': media, 'ext': ext})
    if selector:
        args += ['-f', selector]
    if media != 'audio':
        args += ['--merge-output-format', _yt_selected_output_ext({'media': media, 'ext': ext})]
    args += [
        '--newline',
        '--progress-template', 'download:dp:%(progress.downloaded_bytes)s:%(progress.total_bytes)s:%(progress.speed)s',
        '--print', 'after_move:dp:filepath:%(filepath)s',
        '-o', out_tpl,
        str(entry.get('url') or task.magnet or ''),
    ]

    initial_total = int(entry.get('total') or 0)
    _update_task_file_entry(task_id, 'rd_files', file_id, state='downloading', paused=False, canceled=False, error='', out_path=preferred_out, name=os.path.basename(preferred_out), done=0, speed=0.0, total=initial_total)
    set_task(task_id, current_file=os.path.basename(preferred_out), current_done=0, current_total=(initial_total or None), state='downloading', message=f'Downloading {seq} of {total_count}')
    _rd_recompute_overall_from_files(task_id)

    proc = subprocess.Popen([YTDLP_CMD] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', bufsize=1)
    actual_path = ''
    last_error = ''
    pause_requested = False
    cancel_requested = False
    try:
        while True:
            task = get_task(task_id)
            if not task:
                cancel_requested = True
                break
            ctl = _get_file_control(task_id, file_id)
            if task.cancel_event.is_set():
                cancel_requested = True
            elif ctl.get('canceled'):
                cancel_requested = True
            elif task.pause_event.is_set() or ctl.get('paused'):
                pause_requested = True
            if pause_requested or cancel_requested:
                try:
                    proc.terminate()
                except Exception:
                    pass
            line = proc.stdout.readline() if proc.stdout else ''
            if line:
                s = line.strip()
                if s.startswith('download:dp:'):
                    parts = s.split(':', 4)
                    if len(parts) >= 5:
                        done = _youtube_ytdlp_parse_int(parts[2])
                        total = _youtube_ytdlp_parse_int(parts[3]) or int(entry.get('total') or 0)
                        speed = _youtube_ytdlp_parse_speed(parts[4])
                        _update_task_file_entry(task_id, 'rd_files', file_id, state='downloading', done=done, total=total, speed=speed, error='')
                        set_task(task_id, current_done=done, current_total=(total or None), message=f'Downloading {seq} of {total_count}')
                        _rd_recompute_overall_from_files(task_id)
                elif s.startswith('dp:filepath:'):
                    actual_path = s.split(':', 2)[2].strip()
                elif 'ERROR:' in s:
                    last_error = s.split('ERROR:', 1)[1].strip() or s
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.05)
        rc = proc.wait()
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass

    if cancel_requested:
        _update_task_file_entry(task_id, 'rd_files', file_id, state='canceled', canceled=True, error='')
        _rd_recompute_overall_from_files(task_id)
        return None
    if pause_requested:
        _update_task_file_entry(task_id, 'rd_files', file_id, state='paused', paused=True, error='')
        _rd_recompute_overall_from_files(task_id)
        return None
    if rc != 0:
        raise RuntimeError(last_error or 'yt-dlp failed')

    actual = str(actual_path or '').strip()
    if not actual or not os.path.exists(actual):
        actual = preferred_out if os.path.exists(preferred_out) else _youtube_find_downloaded_path(task.task_dir, title, ext)
    try:
        sz = os.path.getsize(actual) if actual and os.path.exists(actual) else int(entry.get('total') or 0)
    except Exception:
        sz = int(entry.get('total') or 0)
    final_name = os.path.basename(actual) if actual else os.path.basename(preferred_out)
    final_ext = os.path.splitext(final_name)[1].lstrip('.').lower()
    _update_task_file_entry(task_id, 'rd_files', file_id, state='complete', done=sz, total=sz, speed=0.0, out_path=actual or preferred_out, name=final_name, ext=(final_ext or ext), error='', paused=False, canceled=False)
    _rd_recompute_overall_from_files(task_id)
    return actual or preferred_out


def _youtube_finalize_task_state(task_id: str, default_message: str = 'Finished') -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        entries = list(getattr(t, 'rd_files', []) or []) if t else []
    if not entries:
        set_task(task_id, state='error', message='No YouTube formats selected', current_file='', current_done=0, current_total=None)
        return
    any_failed = any(str(e.get('state') or '').lower() == 'failed' for e in entries)
    any_active = any(str(e.get('state') or '').lower() in {'queued', 'requesting', 'downloading'} for e in entries)
    any_paused = any(str(e.get('state') or '').lower() == 'paused' for e in entries)
    all_terminal = all(str(e.get('state') or '').lower() in {'complete', 'canceled', 'failed', 'paused'} for e in entries)
    completed = []
    for e in entries:
        if str(e.get('state') or '').lower() == 'complete':
            p = str(e.get('out_path') or '').strip()
            if p:
                completed.append(p)
    seen = set()
    uniq = []
    for p in completed:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    set_task(task_id, downloaded_files=uniq, current_file='', current_done=0, current_total=None, downloads_complete=bool(all_terminal and not any_failed and not any_active and not any_paused))
    if any_active:
        set_task(task_id, state='downloading', message='Downloading')
    elif any_paused:
        set_task(task_id, state='paused', message='Paused')
    elif any_failed and uniq:
        set_task(task_id, state='error', message='Some YouTube files failed. You can retry failed files.')
    elif any_failed:
        set_task(task_id, state='error', message='YouTube download failed')
    elif uniq or all(str(e.get('state') or '').lower() in {'complete', 'canceled'} for e in entries):
        set_task(task_id, state='done', message=default_message)
    else:
        set_task(task_id, state='error', message='YouTube download failed')


def _youtube_download_from_queue(task_id: str) -> List[str]:
    completed_paths: List[str] = []
    while True:
        task = get_task(task_id)
        if not task:
            break
        check_canceled(task)
        while task.pause_event.is_set():
            set_task(task_id, state='paused', message='Paused')
            time.sleep(0.2)
            task = get_task(task_id)
            if not task:
                return completed_paths
            check_canceled(task)
        nxt = _youtube_pick_next_entry(task_id)
        if not nxt:
            break
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            entries = list(getattr(tcur, 'rd_files', []) or []) if tcur else []
        total_count = len(entries)
        seq = 1
        fid = str(nxt.get('file_id') or '')
        for idx, cur in enumerate(entries, start=1):
            if str(cur.get('file_id') or '') == fid:
                seq = idx
                break
        try:
            out_path = _youtube_run_download(task_id, nxt, seq, total_count)
            if out_path:
                completed_paths.append(out_path)
        except Cancelled:
            raise
        except Exception as e:
            _update_task_file_entry(task_id, 'rd_files', fid, state='failed', error=str(e), paused=False)
            _rd_recompute_overall_from_files(task_id)
    _youtube_finalize_task_state(task_id)
    return completed_paths


def youtube_download_remaining_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return
    if (task.source or '').lower() != 'youtube':
        return
    try:
        set_task(task_id, state='downloading', message='Retrying queued YouTube files')
        _youtube_download_from_queue(task_id)
    except Cancelled:
        set_task(task_id, state='canceled', message='Canceled', current_file='', current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state='error', message=str(e), current_file='', current_done=0, current_total=None)


def youtube_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return
    try:
        entries = list(getattr(task, 'rd_files', []) or [])
        if not entries:
            raise RuntimeError('No YouTube formats selected')
        set_task(task_id, state='downloading', message=f'Downloading {len(entries)} YouTube file(s)', overall_done=0, overall_total=None)
        _youtube_download_from_queue(task_id)
    except Cancelled:
        set_task(task_id, state='canceled', message='Canceled', current_file='', current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state='error', message=str(e), current_file='', current_done=0, current_total=None)


# =========================
# Metadata and artwork cache
# =========================
META_CACHE: Dict[str, Tuple[float, dict]] = {}
META_LOCK = threading.Lock()



def file_meta_cached(abs_path: str) -> dict:
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        return {}

    with META_LOCK:
        hit = META_CACHE.get(abs_path)
        if hit and hit[0] == mtime:
            return hit[1]

    meta: dict = {}
    try:
        js = ffprobe_json(abs_path) or {}
        fmt = js.get("format") or {}
        tags = (fmt.get("tags") or {}) if isinstance(fmt, dict) else {}

        streams = js.get("streams") or []
        audio_stream = None
        if isinstance(streams, list):
            for s in streams:
                if not isinstance(s, dict):
                    continue
                if (s.get("codec_type") or "").lower() != "audio":
                    continue
                if audio_stream is None:
                    audio_stream = s
                stags = s.get("tags")
                if isinstance(stags, dict):
                    for k, v in stags.items():
                        if k not in tags:
                            tags[k] = v

        duration = None
        try:
            duration = float(fmt.get("duration")) if fmt.get("duration") is not None else None
        except Exception:
            duration = None

        def pick(keys: List[str]) -> str:
            for k in keys:
                v = tags.get(k)
                if v:
                    return str(v).strip()
            return ""

        title = pick(["title", "TITLE"]) or os.path.splitext(os.path.basename(abs_path))[0]
        album_artist = pick(["album_artist", "ALBUM_ARTIST", "albumartist", "ALBUMARTIST", "AlbumArtist", "album artist", "ALBUM ARTIST"])
        track_artist = pick(["artist", "ARTIST"])
        artist = track_artist or album_artist
        album = pick(["album", "ALBUM"])
        genre = pick(["genre", "GENRE"])
        track = pick(["track", "TRACK"])

        # Technical display for audio (codec, bit depth, sample rate, bitrate)
        codec = ""
        bits = None
        sample_rate = None
        bit_rate = None
        if isinstance(audio_stream, dict):
            codec = str(audio_stream.get("codec_name") or "").strip()
            for k in ["bits_per_raw_sample", "bits_per_sample"]:
                v = audio_stream.get(k)
                try:
                    iv = int(str(v))
                    if iv > 0:
                        bits = iv
                        break
                except Exception:
                    pass
            try:
                sr = audio_stream.get("sample_rate")
                if sr is not None:
                    sample_rate = int(float(str(sr)))
            except Exception:
                sample_rate = None
            try:
                br = audio_stream.get("bit_rate")
                if br is not None:
                    bit_rate = int(float(str(br)))
            except Exception:
                bit_rate = None

        if bit_rate is None:
            try:
                br = fmt.get("bit_rate") if isinstance(fmt, dict) else None
                if br is not None:
                    bit_rate = int(float(str(br)))
            except Exception:
                bit_rate = None

        tech = ""
        if codec:
            tech = codec.upper()

        if bits and sample_rate:
            khz = sample_rate / 1000.0
            if abs(khz - round(khz)) < 0.05:
                khz_s = str(int(round(khz)))
            else:
                khz_s = f"{khz:.1f}".rstrip("0").rstrip(".")
            tech = (tech + " " if tech else "") + f"{bits}/{khz_s}khz"

        if bit_rate and bit_rate > 0:
            kbps = bit_rate / 1000.0
            if abs(kbps - round(kbps)) < 0.05:
                kbps_s = str(int(round(kbps)))
            else:
                kbps_s = f"{kbps:.1f}".rstrip("0").rstrip(".")
            tech = (tech + " " if tech else "") + f"{kbps_s}kbps"

        meta = {
            "title": title,
            "artist": artist,
            "album_artist": album_artist,
            "album": album,
            "genre": genre,
            "track": track,
            "duration": duration,
            "tech": tech,
        }
    except Exception:
        meta = {
            "title": os.path.splitext(os.path.basename(abs_path))[0],
            "artist": "",
            "album_artist": "",
            "album": "",
            "genre": "",
            "track": "",
            "duration": None,
            "tech": "",
        }

    with META_LOCK:
        META_CACHE[abs_path] = (mtime, meta)
    return meta


def art_cache_path(abs_path: str) -> str:
    key = sha1_text(os.path.abspath(abs_path))
    return os.path.join(art_cache_dir(), f"{key}.jpg")



IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
DIR_ART_CACHE: Dict[str, Tuple[float, Optional[str]]] = {}
DIR_ART_LOCK = threading.Lock()


def pick_folder_art(dir_path: str) -> Optional[str]:
    """Pick an image file inside dir_path to use as album art.

    Priority order is cover, folder, front, album, then any other image.
    Result is cached keyed by directory mtime.
    """
    if not dir_path or not os.path.isdir(dir_path):
        return None
    try:
        d_mtime = os.path.getmtime(dir_path)
    except OSError:
        d_mtime = 0.0

    with DIR_ART_LOCK:
        hit = DIR_ART_CACHE.get(dir_path)
        if hit and hit[0] == d_mtime:
            return hit[1]

    try:
        names = os.listdir(dir_path)
    except OSError:
        names = []

    imgs = []
    for n in names:
        if not n or n.startswith("."):
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext in IMAGE_EXTS:
            imgs.append(n)

    if not imgs:
        with DIR_ART_LOCK:
            DIR_ART_CACHE[dir_path] = (d_mtime, None)
        return None

    prio = ["cover", "folder", "front", "album"]

    def score(fn: str) -> Tuple[int, float, str]:
        base = os.path.splitext(fn)[0].lower().strip()
        # Exact matches win, then prefix matches, then alphabetical.
        for i, key in enumerate(prio):
            if base == key:
                return (i, 0.0, fn.lower())
            if base.startswith(key):
                return (i, 1.0, fn.lower())
        return (len(prio) + 1, 0.0, fn.lower())

    imgs.sort(key=score)
    chosen = os.path.join(dir_path, imgs[0])

    with DIR_ART_LOCK:
        DIR_ART_CACHE[dir_path] = (d_mtime, chosen)

    return chosen


def art_for_media_path(abs_path: str) -> Optional[str]:
    """Return a path to a cover image for an audio file or directory.

    Prefers folder image files, falls back to embedded artwork extraction.
    """
    if not abs_path:
        return None
    if os.path.isdir(abs_path):
        return pick_folder_art(abs_path)
    if os.path.isfile(abs_path):
        d = os.path.dirname(abs_path)
        p = pick_folder_art(d)
        if p:
            return p
        # Fallback to embedded art when no folder image exists.
        if is_audio(abs_path):
            return extract_art(abs_path)
    return None


def extract_art(abs_path: str) -> Optional[str]:
    outp = art_cache_path(abs_path)
    try:
        src_m = os.path.getmtime(abs_path)
    except OSError:
        return None

    if os.path.exists(outp):
        try:
            if os.path.getmtime(outp) >= src_m and os.path.getsize(outp) > 0:
                return outp
        except OSError:
            pass

    base_tmp, ext_tmp = os.path.splitext(outp)
    tmp = base_tmp + ".tmp" + ext_tmp
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass

    args = [
        FFMPEG_PATH,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        abs_path,
        "-an",
        "-vf",
        "scale=400:-1",
        "-frames:v",
        "1",
        tmp,
    ]
    code, _, _ = run_cmd(args)
    if code != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return None

    try:
        os.replace(tmp, outp)
        return outp
    except OSError:
        return None




# =========================
# Playback state (server-side)
# =========================
# Stored in cache folder so it persists across restarts and is shared across devices.
# This keeps:
#   - now_playing (audio or video) with last known position and navigation context
#   - recently_played list (videos always resume, audio grouped into sessions)
PLAYBACK_STATE_LOCK = threading.Lock()

def playback_state_path() -> str:
    return os.path.join(cache_dir(), "playback_state.json")

def _default_playback_state() -> dict:
    return {
        "now": None,              # dict or None
        "recent": [],             # list[dict], newest first
        # session tracking is separate for audio and video so they never overwrite each other
        "audio_session": {
            "session_id": "",
            "last_activity_ts": 0.0,   # updated while playing
            "last_stop_ts": 0.0,       # updated on pause/stop/ended
            # legacy key kept for backward compatibility
            "last_play_ts": 0.0,
        },
        "video_session": {
            "session_id": "",
            "last_activity_ts": 0.0,
            "last_stop_ts": 0.0,
        },
        # legacy unified key kept so older files still load, but it is not used anymore
        "session": {
            "session_id": "",
            "last_activity_ts": 0.0,
            "last_stop_ts": 0.0,
        },
        "ver": 3,
        "updated": 0.0,
    }

PLAYBACK_STATE: dict = _default_playback_state()

def load_playback_state() -> None:
    global PLAYBACK_STATE
    p = playback_state_path()
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                js = json.load(f)
            if isinstance(js, dict):
                base = _default_playback_state()
                base.update(js)

                # recent must be a list
                if not isinstance(base.get("recent"), list):
                    base["recent"] = []

                # normalize audio_session
                a = base.get("audio_session")
                if not isinstance(a, dict):
                    a = {}
                if "session_id" not in a:
                    a["session_id"] = ""
                # support old schema: last_play_ts used instead of last_activity_ts
                if "last_play_ts" not in a:
                    a["last_play_ts"] = 0.0
                if "last_activity_ts" not in a:
                    try:
                        a["last_activity_ts"] = float(a.get("last_play_ts") or 0.0)
                    except Exception:
                        a["last_activity_ts"] = 0.0
                if "last_stop_ts" not in a:
                    a["last_stop_ts"] = 0.0
                base["audio_session"] = a

                # normalize video_session
                v = base.get("video_session")
                if not isinstance(v, dict):
                    v = {}
                if "session_id" not in v:
                    v["session_id"] = ""
                if "last_activity_ts" not in v:
                    v["last_activity_ts"] = 0.0
                if "last_stop_ts" not in v:
                    v["last_stop_ts"] = 0.0
                base["video_session"] = v

                # keep legacy unified session if present, but do not rely on it
                sess = base.get("session")
                if not isinstance(sess, dict):
                    sess = {"session_id": "", "last_activity_ts": 0.0, "last_stop_ts": 0.0}
                if "session_id" not in sess:
                    sess["session_id"] = ""
                if "last_activity_ts" not in sess:
                    sess["last_activity_ts"] = 0.0
                if "last_stop_ts" not in sess:
                    sess["last_stop_ts"] = 0.0
                base["session"] = sess

                PLAYBACK_STATE = base
    except Exception:
        PLAYBACK_STATE = _default_playback_state()

def save_playback_state_best_effort() -> None:
    p = playback_state_path()
    tmp = p + ".tmp"
    try:
        data = None
        with PLAYBACK_STATE_LOCK:
            PLAYBACK_STATE["updated"] = time.time()
            data = json.dumps(PLAYBACK_STATE, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, p)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def _media_key(media: str, root_id: str, rel: str) -> str:
    return f"{(media or '').strip().lower()}::{(root_id or '').strip()}::{(rel or '').strip()}"

def _trim_recent(recent: list, max_items: int = 60) -> list:
    out = recent[:max_items] if isinstance(recent, list) else []
    return out

def _recent_list_key(media: str, root_id: str, rel: str, nav: dict) -> str:
    """Return a stable key that represents the *list context* an item was played from.

    This is used to decide whether the newest recently-played entry should overwrite the previous entry
    (same list), or create a new entry (different list).
    """
    try:
        rid = str(root_id or "").strip()
        rrel = str(rel or "").strip()
        nav_d = nav if isinstance(nav, dict) else {}
        kind = str(nav_d.get("kind") or "").strip().lower()
        nav_rid = str(nav_d.get("root_id") or rid).strip() or rid

        # Directory fallback (for unknown nav kinds)
        dir_rel = ""
        try:
            if "/" in rrel:
                dir_rel = rrel.rsplit("/", 1)[0]
            else:
                dir_rel = ""
        except Exception:
            dir_rel = ""

        base = ""
        if kind == "folder":
            base = "folder|" + nav_rid + "|" + str(nav_d.get("rel") or "")
        elif kind == "metalist":
            base = "meta|" + nav_rid + "|" + str(nav_d.get("level") or "") + "|" + str(nav_d.get("value") or "")
        elif kind:
            base = kind + "|" + nav_rid + "|" + str(nav_d.get("label") or "")
        else:
            base = "dir|" + nav_rid + "|" + dir_rel

        m = str(media or "").strip().lower()
        if m not in ("audio", "video"):
            m = "other"
        return m + "|" + base
    except Exception:
        try:
            m = str(media or "").strip().lower()
            if m not in ("audio", "video"):
                m = "other"
            return m + "|unknown"
        except Exception:
            return "unknown"


def playback_snapshot_public() -> dict:
    with PLAYBACK_STATE_LOCK:
        now = PLAYBACK_STATE.get("now")
        recent = PLAYBACK_STATE.get("recent") or []
        # remove internal fields from each entry if present
        rp = []
        for it in recent:
            if not isinstance(it, dict):
                continue
            d = dict(it)
            d.pop("_key", None)
            d.pop("_sess", None)
            d.pop("_list", None)
            d.pop("_stream_item", None)
            rp.append(d)
        out_now = dict(now) if isinstance(now, dict) else None
        if isinstance(out_now, dict):
            out_now.pop("_key", None)
            out_now.pop("_sess", None)
            out_now.pop("_list", None)
            out_now.pop("_stream_item", None)
        return {"now": out_now, "recent": rp}

def playback_update_from_client(payload: dict) -> dict:
    # payload fields (best-effort):
    #   media: "audio"|"video"
    #   root_id, rel
    #   label, title, artist, album, art
    #   position, duration
    #   playing: bool
    #   nav: dict (navigation context to restore list/album/folder)
    #   event: "start"|"time"|"pause"|"stop"|"ended"
    js = payload if isinstance(payload, dict) else {}
    media = str(js.get("media") or "").strip().lower()
    if media not in ("audio", "video"):
        return {"ok": False, "error": "bad media"}
    root_id = str(js.get("root_id") or "").strip()
    rel = str(js.get("rel") or "").strip()
    stream_item = None
    if root_id == SEARCH_STREAM_ROOT_ID and rel:
        stream_item = _search_stream_get_or_restore(rel)
    if (not root_id or not rel) or (root_id == SEARCH_STREAM_ROOT_ID and not stream_item):
        return {"ok": False, "error": "missing root_id or rel"}

    label = str(js.get("label") or "").strip()
    title = str(js.get("title") or "").strip()
    artist = str(js.get("artist") or "").strip()
    album = str(js.get("album") or "").strip()
    art = str(js.get("art") or "").strip()
    nav = js.get("nav") if isinstance(js.get("nav"), dict) else {}
    ev = str(js.get("event") or "").strip().lower()

    pos = js.get("position")
    dur = js.get("duration")
    try:
        pos_f = float(pos) if pos is not None and str(pos).strip() else 0.0
    except Exception:
        pos_f = 0.0
    try:
        dur_f = float(dur) if dur is not None and str(dur).strip() else None
    except Exception:
        dur_f = None

    playing = bool(js.get("playing")) if "playing" in js else None

    k = _media_key(media, root_id, rel)
    now_entry = {
        "_key": k,
        "media": media,
        "root_id": root_id,
        "rel": rel,
        "label": label,
        "title": title,
        "artist": artist,
        "album": album,
        "art": art,
        "position": max(0.0, pos_f),
        "duration": dur_f,
        "playing": bool(playing) if playing is not None else False,
        "nav": nav,
        "ts": time.time(),
        "streamed": bool(js.get("streamed")),
        "source": str(js.get("source") or "").strip().lower(),
        "ext": str(js.get("ext") or "").strip().lower(),
        "quality": str(js.get("quality") or "").strip(),
    }


    playlist_ctx = js.get("playlist") if isinstance(js.get("playlist"), dict) else None
    if playlist_ctx:
        # best-effort sanity limits
        items = playlist_ctx.get("items")
        if not isinstance(items, list):
            playlist_ctx = None
        else:
            if len(items) > 600:
                playlist_ctx["items"] = items[:600]
            try:
                playlist_ctx["index"] = int(playlist_ctx.get("index") or 0)
            except Exception:
                playlist_ctx["index"] = 0
            # strip unexpected large fields
            clean_items = []
            for itx in playlist_ctx.get("items") or []:
                if not isinstance(itx, dict):
                    continue
                rid = str(itx.get("root_id") or "").strip()
                rrel = str(itx.get("rel") or "").strip()
                m2 = str(itx.get("media") or media).strip().lower()
                lbl2 = str(itx.get("label") or "").strip()
                if not rid or not rrel:
                    continue
                clean_items.append({"root_id": rid, "rel": rrel, "media": m2, "label": lbl2})
            playlist_ctx["items"] = clean_items

    if playlist_ctx:
        now_entry["playlist"] = playlist_ctx
    if stream_item:
        now_entry["streamed"] = True
        now_entry["source"] = str(stream_item.get("source") or now_entry.get("source") or "").strip().lower()
        stream_title = str(stream_item.get("title") or stream_item.get("name") or "").strip()
        stream_name = str(stream_item.get("name") or stream_item.get("title") or "").strip()
        if now_entry.get("source") == "youtube" and stream_title:
            now_entry["title"] = stream_title
            now_entry["label"] = stream_title
        else:
            if not now_entry.get("title"):
                now_entry["title"] = stream_title
            if not now_entry.get("label"):
                now_entry["label"] = stream_name
        if not now_entry.get("album"):
            now_entry["album"] = str(stream_item.get("album") or "")
        if not now_entry.get("artist"):
            now_entry["artist"] = str(stream_item.get("artist") or "")
        if not now_entry.get("art"):
            now_entry["art"] = str(stream_item.get("art") or "")
        if not now_entry.get("ext"):
            now_entry["ext"] = str(stream_item.get("ext") or "").strip().lower()
        if not now_entry.get("quality"):
            now_entry["quality"] = str(stream_item.get("quality") or "")
        keep_keys = (
            "item_id", "queue_index", "queue_count", "session_title",
            "media", "name", "title", "artist", "album", "art", "size",
            "source", "streamed", "ext", "quality", "url", "youtube_url",
            "format_id", "itag", "mime", "requires_local_mux"
        )
        now_entry["_stream_item"] = {k: stream_item.get(k) for k in keep_keys if k in stream_item}

    
    # recently played overwrite key (list or directory context)
    now_entry["_list"] = _recent_list_key(media, root_id, rel, nav)

    with PLAYBACK_STATE_LOCK:
        # update now playing
        if playing is not None:
            now_entry["playing"] = bool(playing)
        PLAYBACK_STATE["now"] = now_entry

        # recent list
        recent = PLAYBACK_STATE.get("recent") or []
        if not isinstance(recent, list):
            recent = []

        # per-media session tracking so audio and video never overwrite each other
        sess_key = "audio_session" if media == "audio" else "video_session"
        sess = PLAYBACK_STATE.get(sess_key) or {}
        if not isinstance(sess, dict):
            sess = {}

        if "session_id" not in sess:
            sess["session_id"] = ""
        if "last_activity_ts" not in sess:
            # migrate from legacy audio_session key if present
            try:
                sess["last_activity_ts"] = float(sess.get("last_play_ts") or 0.0)
            except Exception:
                sess["last_activity_ts"] = 0.0
        if "last_stop_ts" not in sess:
            sess["last_stop_ts"] = 0.0

        now_ts = time.time()
        session_gap_seconds = 150.0

        sess_id = str(sess.get("session_id") or "")
        try:
            last_act = float(sess.get("last_activity_ts") or 0.0)
        except Exception:
            last_act = 0.0
        try:
            last_stop = float(sess.get("last_stop_ts") or 0.0)
        except Exception:
            last_stop = 0.0

        ev_s = (ev or "").strip().lower()
        is_playing_now = bool(now_entry.get("playing"))

        # update markers
        if is_playing_now:
            sess["last_activity_ts"] = now_ts
            last_act = now_ts
            # legacy audio key kept up to date
            if media == "audio":
                sess["last_play_ts"] = now_ts
        if ev_s in ("pause", "stop", "ended"):
            sess["last_stop_ts"] = now_ts
            last_stop = now_ts

        # decide whether to start a new session based on last activity (play or stop)
        last_any = max(last_act, last_stop)
        start_new_session = False
        if not sess_id:
            start_new_session = True
        elif last_any > 0.0 and (now_ts - last_any) > session_gap_seconds:
            start_new_session = True

        # only create a new session id when playback is actually running
        if (ev_s in ("start", "time")) and is_playing_now and start_new_session:
            prefix = "a" if media == "audio" else "v"
            sess_id = prefix + str(int(now_ts)) + "_" + uuid.uuid4().hex[:8]
            sess["session_id"] = sess_id

        if sess_id:
            now_entry["_sess"] = sess_id

                # recently played: overwrite the previous entry when the list/directory context is the same;
        # otherwise add a new entry.
        found_by_key = None
        for i, it2 in enumerate(recent):
            if isinstance(it2, dict) and it2.get("_key") == k:
                found_by_key = i
                break

        if ev_s == "start":
            if recent and isinstance(recent[0], dict) and recent[0].get("_list") == now_entry.get("_list"):
                recent[0] = dict(now_entry)
            else:
                if found_by_key is not None:
                    try:
                        recent.pop(found_by_key)
                    except Exception:
                        pass
                recent.insert(0, dict(now_entry))
        else:
            # Do not reorder on time/pause/stop updates; just refresh fields if we can find a matching entry.
            if found_by_key is not None and isinstance(recent[found_by_key], dict):
                recent[found_by_key].update(dict(now_entry))
            elif recent and isinstance(recent[0], dict) and recent[0].get("_list") == now_entry.get("_list"):
                recent[0].update(dict(now_entry))
            elif not recent and (ev_s in ("time", "start")) and is_playing_now:
                recent.insert(0, dict(now_entry))
        PLAYBACK_STATE[sess_key] = sess
        PLAYBACK_STATE["recent"] = _trim_recent(recent)

    save_playback_state_best_effort()
    return {"ok": True}


# =========================
# Flask app and templates
# =========================
app = Flask(__name__)

SEARCH_STREAMS: Dict[str, Dict[str, Any]] = {}
SEARCH_STREAMS_LOCK = threading.Lock()

MCP_SESSIONS: Dict[str, Dict[str, Any]] = {}
MCP_SESSIONS_LOCK = threading.Lock()
MCP_SSE_KEEPALIVE_SECONDS = 15
MCP_SESSION_TTL_SECONDS = 12 * 60 * 60


def _guess_media_from_name(name: str) -> str:
    ext = os.path.splitext(str(name or "").strip().lower())[1]
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    mime, _ = mimetypes.guess_type(str(name or ""))
    if mime:
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"
    return ""


def _search_stream_rel(session_id: str, item_id: str) -> str:
    return f"{session_id}/{item_id}"


def _search_stream_cleanup_locked(now_ts: Optional[float] = None) -> None:
    if now_ts is None:
        now_ts = time.time()
    stale = []
    for sid, sess in SEARCH_STREAMS.items():
        try:
            ts = float(sess.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        if (now_ts - ts) > SEARCH_STREAM_SESSION_TTL_SECONDS:
            stale.append(sid)
    for sid in stale:
        SEARCH_STREAMS.pop(sid, None)


def _search_stream_get(rel: str) -> Optional[Dict[str, Any]]:
    raw = str(rel or "").strip().strip("/")
    if not raw or "/" not in raw:
        return None
    session_id, item_id = raw.split("/", 1)
    if not session_id or not item_id:
        return None
    with SEARCH_STREAMS_LOCK:
        _search_stream_cleanup_locked()
        sess = SEARCH_STREAMS.get(session_id)
        if not isinstance(sess, dict):
            return None
        sess["ts"] = time.time()
        for it in (sess.get("items") or []):
            if isinstance(it, dict) and str(it.get("item_id") or "") == item_id:
                out = dict(it)
                out["session_id"] = session_id
                out["queue_index"] = int(it.get("queue_index") or 0)
                out["queue_count"] = len(sess.get("items") or [])
                out["session_title"] = str(sess.get("title") or "")
                return out
    return None


def _playback_stream_item_for_rel(rel: str) -> Optional[Dict[str, Any]]:
    raw = str(rel or "").strip().strip("/")
    if not raw:
        return None
    with PLAYBACK_STATE_LOCK:
        candidates = []
        now = PLAYBACK_STATE.get("now")
        if isinstance(now, dict):
            candidates.append(now)
        recent = PLAYBACK_STATE.get("recent") or []
        if isinstance(recent, list):
            candidates.extend([it for it in recent if isinstance(it, dict)])
    for entry in candidates:
        try:
            if str(entry.get("root_id") or "").strip() != SEARCH_STREAM_ROOT_ID:
                continue
            if str(entry.get("rel") or "").strip().strip("/") != raw:
                continue
            stream_item = entry.get("_stream_item")
            if isinstance(stream_item, dict):
                out = dict(stream_item)
                sess_id, item_id = raw.split("/", 1)
                out["session_id"] = sess_id
                out["item_id"] = str(out.get("item_id") or item_id)
                out["queue_index"] = int(out.get("queue_index") or 0)
                out["queue_count"] = int(out.get("queue_count") or 1)
                return out
        except Exception:
            continue
    return None


def _search_stream_get_or_restore(rel: str) -> Optional[Dict[str, Any]]:
    it = _search_stream_get(rel)
    if it:
        return it
    restored = _playback_stream_item_for_rel(rel)
    if not restored:
        return None
    try:
        raw = str(rel or "").strip().strip("/")
        session_id, item_id = raw.split("/", 1)
    except Exception:
        return restored
    with SEARCH_STREAMS_LOCK:
        _search_stream_cleanup_locked()
        sess = SEARCH_STREAMS.get(session_id)
        if not isinstance(sess, dict):
            sess = {"ts": time.time(), "title": str(restored.get("session_title") or restored.get("title") or restored.get("album") or "Search stream"), "source": str(restored.get("source") or ""), "items": []}
            SEARCH_STREAMS[session_id] = sess
        sess["ts"] = time.time()
        items = list(sess.get("items") or [])
        if not any(isinstance(x, dict) and str(x.get("item_id") or "") == item_id for x in items):
            add = dict(restored)
            add["item_id"] = item_id
            items.append(add)
            sess["items"] = items
    return _search_stream_get(rel) or restored


def _rd_wait_for_selected_links(torrent_id: str, selected_ids: List[int], timeout_seconds: int = MAX_TORRENT_WAIT_SECONDS) -> Tuple[dict, List[str]]:
    wanted = [int(x) for x in (selected_ids or []) if str(x).strip()]
    end_time = time.time() + max(30, int(timeout_seconds or 0))
    while time.time() < end_time:
        info = rd_torrent_info(torrent_id)
        links = info.get("links") or []
        if info.get("status") == "downloaded" and isinstance(links, list) and links:
            if wanted and len(links) == len(wanted):
                return info, [str(x) for x in links]
            if not wanted:
                return info, [str(x) for x in links]
        status = str(info.get("status") or "")
        if status in {"error", "virus", "dead"}:
            raise RuntimeError(f"Real Debrid reported status: {status}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError("Timed out waiting for Real Debrid stream links")


def _engine_prepare_stream_session(payload: dict) -> dict:
    src = str(payload.get("source") or "").strip().lower()
    if src == "youtube":
        url = str(payload.get('url') or '').strip()
        selected = payload.get('selected') or []
        title = str(payload.get('title') or payload.get('directory_title') or 'YouTube').strip() or 'YouTube'
        selected_fallback_url = ''
        items = []
        for it in selected:
            if not isinstance(it, dict):
                continue
            format_id = str(it.get('format_id') or it.get('itag') or it.get('file_id') or '').strip()
            if not format_id:
                continue
            name = str(it.get('name') or it.get('title') or ('Format ' + format_id)).strip() or 'Format'
            media = str(it.get('media') or '').strip().lower() or ('audio' if str(it.get('ext') or '').lower() in ('mp3','m4a','aac','ogg','opus','wav','flac') else 'video')
            item_url = str(it.get('url') or '').strip()
            if not selected_fallback_url and item_url:
                selected_fallback_url = item_url
            stream_source_url = url or item_url
            if not stream_source_url:
                continue
            item_id = uuid.uuid4().hex[:12]
            items.append({
                'item_id': item_id,
                'queue_index': len(items),
                'media': media,
                'name': name,
                'title': title,
                'artist': str(payload.get('channel') or payload.get('user') or ''),
                'album': title,
                'art': str(payload.get('thumbnail') or ''),
                'size': int(it.get('size') or 0) if str(it.get('size') or '').strip() else 0,
                'source': src,
                'streamed': True,
                'ext': str(it.get('ext') or '').lower(),
                'quality': str(it.get('quality') or it.get('bitrate') or ''),
                'url': stream_source_url,
                'youtube_url': stream_source_url,
                'format_id': format_id,
                'itag': format_id,
                'mime': '',
                'requires_local_mux': bool(media != 'audio'),
            })
        if not items and selected_fallback_url:
            url = selected_fallback_url
        if not items:
            raise RuntimeError('No selected YouTube formats were streamable')
        session_id = uuid.uuid4().hex
        with SEARCH_STREAMS_LOCK:
            _search_stream_cleanup_locked()
            SEARCH_STREAMS[session_id] = {'ts': time.time(), 'title': title, 'source': src, 'items': items}
        out_items = []
        for it in items:
            rel = _search_stream_rel(session_id, str(it.get('item_id') or ''))
            out_items.append({'root_id': SEARCH_STREAM_ROOT_ID, 'rel': rel, 'media': it.get('media') or '', 'label': it.get('name') or '', 'title': it.get('title') or '', 'artist': it.get('artist') or '', 'album': it.get('album') or '', 'art': it.get('art') or '', 'streamed': True, 'source': it.get('source') or src, 'ext': it.get('ext') or '', 'quality': it.get('quality') or '', 'size': int(it.get('size') or 0)})
        return {'session_id': session_id, 'title': title, 'items': out_items}
    if src != "knaben":
        raise RuntimeError("Streaming is not available for this source")
    torrent_id = str(payload.get("torrent_id") or "").strip()
    selected = payload.get("selected") or []
    title = str(payload.get("title") or payload.get("directory_title") or payload.get("directory") or "Search stream").strip() or "Search stream"
    if not torrent_id:
        raise RuntimeError("Missing torrent id")
    clean_ids = []
    selected_by_id = {}
    for it in selected:
        if not isinstance(it, dict):
            continue
        try:
            fid = int(it.get("file_id"))
        except Exception:
            continue
        clean_ids.append(fid)
        selected_by_id[fid] = it
    if not clean_ids:
        raise RuntimeError("No files selected")
    rd_select_files(torrent_id, clean_ids)
    _info, links = _rd_wait_for_selected_links(torrent_id, clean_ids)
    items = []
    for idx, fid in enumerate(clean_ids):
        meta = selected_by_id.get(fid) or {}
        name = str(meta.get("name") or meta.get("title") or f"File {fid}")
        media = _guess_media_from_name(name)
        if media not in ("audio", "video"):
            continue
        un = rd_unrestrict(str(links[idx]))
        item_id = uuid.uuid4().hex[:12]
        items.append({
            "item_id": item_id,
            "queue_index": len(items),
            "media": media,
            "name": name,
            "title": name,
            "artist": "",
            "album": title,
            "art": "",
            "size": int(meta.get("size") or 0),
            "source": src,
            "streamed": True,
            "ext": str(meta.get("ext") or os.path.splitext(name)[1].lstrip('.')).lower(),
            "quality": str(meta.get("quality") or meta.get("bitrate") or ""),
            "url": str(un.get("download") or ""),
            "mime": str(un.get("mimeType") or un.get("mime_type") or ""),
        })
    if not items:
        raise RuntimeError("No selected files were streamable")
    session_id = uuid.uuid4().hex
    with SEARCH_STREAMS_LOCK:
        _search_stream_cleanup_locked()
        SEARCH_STREAMS[session_id] = {"ts": time.time(), "title": title, "source": src, "items": items}
    out_items = []
    for it in items:
        rel = _search_stream_rel(session_id, str(it.get("item_id") or ""))
        out_items.append({
            "root_id": SEARCH_STREAM_ROOT_ID,
            "rel": rel,
            "media": it.get("media") or "",
            "label": it.get("name") or "",
            "title": it.get("title") or "",
            "artist": it.get("artist") or "",
            "album": it.get("album") or "",
            "art": it.get("art") or "",
            "streamed": True,
            "source": it.get("source") or src,
            "ext": it.get("ext") or "",
            "quality": it.get("quality") or "",
            "size": int(it.get("size") or 0),
        })
    return {"session_id": session_id, "title": title, "items": out_items}


def _mcp_allowed_origins() -> List[str]:
    allowed = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
    try:
        allowed.add((request.host_url or '').rstrip('/'))
    except Exception:
        pass
    return sorted(x for x in allowed if x)


def _mcp_is_loopback_host(host: str) -> bool:
    h = str(host or '').strip().lower().strip('[]')
    if not h:
        return False
    return h in {'localhost', '127.0.0.1', '::1'}


def _mcp_validate_origin() -> Optional[Response]:
    origin = (request.headers.get('Origin') or '').strip()
    if not origin:
        return None
    if origin.lower() == 'null':
        return None
    try:
        parsed = urlparse(origin)
        norm = f"{parsed.scheme}://{parsed.netloc}"
        host = (parsed.hostname or '').strip().lower()
    except Exception:
        norm = origin
        host = ''
    if norm in _mcp_allowed_origins():
        return None
    if _mcp_is_loopback_host(host):
        return None
    try:
        req_host = (request.host or '').split(':', 1)[0].strip().lower()
    except Exception:
        req_host = ''
    if req_host and host and host == req_host:
        return None
    return Response('Forbidden', status=403, mimetype='text/plain')


def _mcp_prune_sessions() -> None:
    now = time.time()
    with MCP_SESSIONS_LOCK:
        stale = []
        for sid, sess in list(MCP_SESSIONS.items()):
            if not isinstance(sess, dict):
                stale.append(sid)
                continue
            try:
                updated = float(sess.get('updated') or sess.get('created') or 0.0)
            except Exception:
                updated = 0.0
            if updated <= 0 or (now - updated) > MCP_SESSION_TTL_SECONDS:
                stale.append(sid)
        for sid in stale:
            MCP_SESSIONS.pop(sid, None)


def _mcp_new_session(client_info: Optional[dict] = None) -> str:
    _mcp_prune_sessions()
    sid = uuid.uuid4().hex
    with MCP_SESSIONS_LOCK:
        MCP_SESSIONS[sid] = {
            'created': time.time(),
            'updated': time.time(),
            'initialized': False,
            'client_info': dict(client_info or {}),
        }
    return sid


def _mcp_touch_session(session_id: str) -> None:
    if not session_id:
        return
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        if isinstance(sess, dict):
            sess['updated'] = time.time()


def _mcp_get_session(session_id: str) -> Optional[dict]:
    if not session_id:
        return None
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        return dict(sess) if isinstance(sess, dict) else None


def _mcp_ensure_session(session_id: str = '', client_info: Optional[dict] = None) -> str:
    sid = str(session_id or '').strip()
    if sid and _mcp_get_session(sid) is not None:
        _mcp_touch_session(sid)
        return sid
    return _mcp_new_session(client_info)


def _mcp_set_initialized(session_id: str, initialized: bool = True) -> None:
    if not session_id:
        return
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        if isinstance(sess, dict):
            sess['initialized'] = bool(initialized)
            sess['updated'] = time.time()


def _mcp_json_response(payload: Any, status: int = 200, session_id: str = '') -> Response:
    resp = jsonify(payload)
    resp.status_code = status
    if session_id:
        resp.headers['Mcp-Session-Id'] = session_id
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


def _mcp_result(msg_id: Any, result: dict, session_id: str = '') -> Response:
    return _mcp_json_response({'jsonrpc': '2.0', 'id': msg_id, 'result': result}, 200, session_id=session_id)


def _mcp_error(msg_id: Any, code: int, message: str, *, data: Any = None, status: int = 400, session_id: str = '') -> Response:
    err = {'code': int(code), 'message': str(message)}
    if data is not None:
        err['data'] = data
    return _mcp_json_response({'jsonrpc': '2.0', 'id': msg_id, 'error': err}, status, session_id=session_id)


def _mcp_sse_response(session_id: str) -> Response:
    sid = _mcp_ensure_session(session_id)

    def gen():
        first = {
            'jsonrpc': '2.0',
            'method': 'notifications/message',
            'params': {
                'level': 'info',
                'data': {
                    'server': 'debripod',
                    'version': str(VERSION),
                    'endpoint': '/mcp',
                    'sessionId': sid,
                },
            },
        }
        yield ': connected\n\n'
        yield 'event: endpoint\n'
        yield 'data: ' + json.dumps({'path': '/mcp', 'sessionId': sid}, ensure_ascii=False) + '\n\n'
        yield 'event: message\n'
        yield 'data: ' + json.dumps(first, ensure_ascii=False) + '\n\n'
        while True:
            time.sleep(MCP_SSE_KEEPALIVE_SECONDS)
            _mcp_touch_session(sid)
            yield ': keepalive\n\n'

    resp = Response(gen(), status=200, mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Connection'] = 'keep-alive'
    resp.headers['X-Accel-Buffering'] = 'no'
    resp.headers['Mcp-Session-Id'] = sid
    return resp


def _mcp_tool_result(structured: dict, text: str, *, is_error: bool = False) -> dict:
    out = {
        'content': [{'type': 'text', 'text': str(text)}],
        'structuredContent': structured if isinstance(structured, dict) else {},
    }
    if is_error:
        out['isError'] = True
    return out


def _mcp_get_limit(args: dict) -> int:
    raw = MCP_SEARCH_RESULT_LIMIT
    if isinstance(args, dict) and args.get('limit') is not None:
        raw = args.get('limit')
    try:
        val = int(raw)
    except Exception:
        val = int(MCP_SEARCH_RESULT_LIMIT)
    return max(1, min(val, max(1, SOULSEEK_SEARCH_MAX_RESULTS)))


def _mcp_identifier_encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _mcp_identifier_decode(token: str) -> dict:
    s = str(token or '').strip()
    if not s:
        raise ValueError('Missing identifier')
    pad = '=' * ((4 - (len(s) % 4)) % 4)
    raw = base64.urlsafe_b64decode((s + pad).encode('ascii'))
    js = json.loads(raw.decode('utf-8'))
    if not isinstance(js, dict):
        raise ValueError('Invalid identifier')
    return js


def _mcp_group_soulseek_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    users: Dict[str, Dict[str, Any]] = {}
    for it in items or []:
        user = str(it.get('user') or '').strip()
        rp = _slsk_norm_remote_path(str(it.get('remote_path') or ''))
        if not user or not rp:
            continue
        try:
            size = int(it.get('size') or 0)
        except Exception:
            size = 0
        try:
            speed = int(it.get('speed') or 0)
        except Exception:
            speed = 0
        parts = rp.split('\\')
        fname = parts[-1] if parts else rp
        directory = '\\'.join(parts[:-1]) if len(parts) > 1 else ''
        kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)
        u = users.get(user)
        if not u:
            u = {'user': user, 'speed': speed, 'dirs': {}, 'total_size': 0, 'total_files': 0}
            users[user] = u
        u['speed'] = max(int(u.get('speed') or 0), speed)
        dirs = u.get('dirs') or {}
        d = dirs.get(directory)
        if not d:
            d = {'directory': directory, 'files': [], 'total_size': 0, 'total_files': 0}
            dirs[directory] = d
            u['dirs'] = dirs
        d['files'].append({
            'name': fname,
            'remote_path': rp,
            'size': size,
            'kind': kind,
            'ext': ext,
            'bitrate': br,
            'bit_depth': bd,
            'sample_rate': sr,
            'duration': dur,
            'vbr': vbr,
            'codec': codec,
        })
        d['total_size'] += size
        d['total_files'] += 1
        u['total_size'] = int(u.get('total_size') or 0) + size
        u['total_files'] = int(u.get('total_files') or 0) + 1
    out: List[Dict[str, Any]] = []
    for u in users.values():
        dirs_list = list((u.get('dirs') or {}).values())
        dirs_list.sort(key=lambda d: (int(d.get('total_size') or 0), int(d.get('total_files') or 0)), reverse=True)
        out.append({
            'user': u.get('user') or '',
            'speed': int(u.get('speed') or 0),
            'dirs': dirs_list,
            'total_size': int(u.get('total_size') or 0),
            'total_files': int(u.get('total_files') or 0),
        })
    out.sort(key=lambda u: (int(u.get('speed') or 0), int(u.get('total_size') or 0), str(u.get('user') or '').lower()), reverse=True)
    return out


def _mcp_search_knaben(query: str, limit: int) -> dict:
    results, err, remaining, reset = knaben_search(query, 1)
    trimmed = list(results or [])[:limit]
    items = []
    for it in trimmed:
        ident = _mcp_identifier_encode({
            'kind': 'knaben_item',
            'title': str(it.get('title') or 'Knaben item'),
            'magnet': str(it.get('magnet') or ''),
            'infohash': str(it.get('infohash') or ''),
        })
        items.append({
            'identifier': ident,
            'title': str(it.get('title') or ''),
            'size': it.get('size'),
            'seeders': it.get('seeders'),
            'leechers': it.get('leechers'),
            'category': str(it.get('category') or ''),
            'infohash': str(it.get('infohash') or ''),
            'href': str(it.get('href') or ''),
        })
    return {
        'engine': 'knaben',
        'query': query,
        'limit': limit,
        'error': str(err or ''),
        'rate_remaining': remaining,
        'rate_reset': reset,
        'results': items,
        'result_count': len(items),
    }


def _mcp_search_soulseek(query: str, limit: int) -> dict:
    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return {'engine': 'soulseek', 'query': query, 'limit': limit, 'results': [], 'result_count': 0, 'error': 'Soulseek service is not ready'}
    items = svc.search(query)
    grouped = _mcp_group_soulseek_items(items)
    out = []
    for u in grouped:
        user = str(u.get('user') or '')
        speed = int(u.get('speed') or 0)
        for d in (u.get('dirs') or []):
            files = list(d.get('files') or [])
            directory = str(d.get('directory') or '')
            ident = _mcp_identifier_encode({
                'kind': 'slsk_dir',
                'user': user,
                'directory': directory,
                'files': [{'remote_path': str(f.get('remote_path') or ''), 'size': int(f.get('size') or 0)} for f in files if str(f.get('remote_path') or '').strip()],
            })
            out.append({
                'identifier': ident,
                'user': user,
                'directory': directory,
                'speed': speed,
                'file_count': int(d.get('total_files') or 0),
                'total_size': int(d.get('total_size') or 0),
                'sample_files': [str(f.get('name') or '') for f in files[:5]],
            })
    out.sort(key=lambda x: (int(x.get('speed') or 0), int(x.get('total_size') or 0), str(x.get('user') or '').lower()), reverse=True)
    out = out[:limit]
    return {'engine': 'soulseek', 'query': query, 'limit': limit, 'results': out, 'result_count': len(out), 'error': ''}


def _mcp_start_rd_download(title: str, magnet: str) -> dict:
    if not magnet.startswith('magnet:?'):
        raise RuntimeError('Invalid magnet')
    torrent_id = rd_add_magnet(magnet)
    info = rd_torrent_info(torrent_id)
    files = info.get('files') or []
    file_ids: List[int] = []
    if isinstance(files, list):
        for f in files:
            if not isinstance(f, dict):
                continue
            fid = f.get('id')
            if fid is None:
                continue
            try:
                file_ids.append(int(fid))
            except Exception:
                continue
    if not file_ids:
        raise RuntimeError('No files found in torrent')
    task_id = uuid.uuid4().hex
    task_dir = build_task_dir(task_id, title)
    os.makedirs(task_dir, exist_ok=True)
    t = Task(
        id=task_id,
        title=title or 'Knaben item',
        magnet=magnet,
        task_dir=task_dir,
        state='queued',
        message='Queued',
        torrent_id=torrent_id,
        rd_selected_file_ids=file_ids,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    threading.Thread(target=worker, args=(task_id,), daemon=True).start()
    return {'task_id': task_id, 'task_dir': task_dir, 'torrent_id': torrent_id, 'selected_file_count': len(file_ids)}


def _mcp_start_slsk_download(user: str, directory: str, files_in: List[Dict[str, Any]], title: str = '') -> dict:
    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        raise RuntimeError('Soulseek is not configured or failed to start')
    task_download_dir = _slsk_task_download_dir(directory)
    try:
        os.makedirs(task_download_dir, exist_ok=True)
    except Exception:
        task_download_dir = SOULSEEK_DOWNLOAD_DIR
    files: List[Dict[str, Any]] = []
    remote_paths: List[str] = []
    for it in files_in or []:
        rp = _slsk_norm_remote_path(str((it or {}).get('remote_path') or '').strip())
        if not rp:
            continue
        try:
            sz = int((it or {}).get('size') or 0)
        except Exception:
            sz = 0
        remote_paths.append(rp)
        rel = _slsk_relative_under_directory(directory, rp)
        rel_parts = [x for x in _slsk_norm_remote_path(rel).split('\\') if x]
        local_path = os.path.join(task_download_dir, *rel_parts) if rel_parts else task_download_dir
        incoming_path = _slsk_expected_incoming_path(rp)
        files.append({
            'user': user,
            'directory': directory,
            'remote_path': rp,
            'file_id': hashlib.sha1((user + '|' + rp).encode('utf-8', 'ignore')).hexdigest()[:16],
            'name': _slsk_norm_remote_path(rp).split('\\')[-1],
            'total': sz,
            'done': 0,
            'state': 'queued',
            'state_raw': 'queued',
            'error': '',
            'paused': False,
            'canceled': False,
            'local_path': local_path,
            'incoming_path': incoming_path,
            'speed': 0.0,
        })
    if not user or not remote_paths:
        raise RuntimeError('Missing user or selected files')
    if not title:
        base = directory.split('\\')[-1] if directory else ''
        title = f"Soulseek: {user} {base}".strip()
    task_id = uuid.uuid4().hex
    t = Task(
        id=task_id,
        title=title,
        magnet='',
        task_dir=task_download_dir,
        source='soulseek',
        state='queued',
        message='Queued',
        torrent_id=None,
        slsk_user=user,
        slsk_directory=directory,
        slsk_files=files,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    svc.enqueue_downloads(task_id, user, remote_paths)
    return {'task_id': task_id, 'task_dir': task_download_dir, 'file_count': len(remote_paths), 'user': user, 'directory': directory}


def _mcp_build_library_tree() -> dict:
    roots_out = []
    for rid, name, root_abs, mode in roots():
        tree = {'name': name, 'root_id': rid, 'path': root_abs, 'mode': mode, 'folders': []}
        index: Dict[str, dict] = {'': tree}
        for base, dirs, _files in os.walk(root_abs):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != CACHE_DIR_NAME]
            rel_base = os.path.relpath(base, root_abs).replace('\\', '/')
            if rel_base == '.':
                rel_base = ''
            parent = index.get(rel_base)
            if parent is None:
                continue
            for d in sorted(dirs, key=lambda x: x.lower()):
                rel = f"{rel_base}/{d}".strip('/')
                node = {'name': d, 'path': rel, 'folders': []}
                parent['folders'].append(node)
                index[rel] = node
        roots_out.append(tree)
    return {'roots': roots_out}


def _mcp_handle_tool_call(name: str, args: dict) -> dict:
    name = str(name or '').strip()
    args = args if isinstance(args, dict) else {}
    if name == 'debripod_knaben_search':
        query = str(args.get('query') or '').strip()
        if not query:
            return _mcp_tool_result({'ok': False, 'error': 'Missing query'}, 'Error: Missing query', is_error=True)
        limit = _mcp_get_limit(args)
        data = _mcp_search_knaben(query, limit)
        ok = not data.get('error')
        text = json.dumps(data, ensure_ascii=False, indent=2)
        data['ok'] = ok
        return _mcp_tool_result(data, text, is_error=not ok)

    if name == 'debripod_soulseek_search':
        query = str(args.get('query') or '').strip()
        if not query:
            return _mcp_tool_result({'ok': False, 'error': 'Missing query'}, 'Error: Missing query', is_error=True)
        limit = _mcp_get_limit(args)
        data = _mcp_search_soulseek(query, limit)
        ok = not data.get('error')
        text = json.dumps(data, ensure_ascii=False, indent=2)
        data['ok'] = ok
        return _mcp_tool_result(data, text, is_error=not ok)

    if name == 'debripod_download':
        ident = str(args.get('identifier') or '').strip()
        if not ident:
            return _mcp_tool_result({'ok': False, 'error': 'Missing identifier'}, 'Error: Missing identifier', is_error=True)
        try:
            payload = _mcp_identifier_decode(ident)
        except Exception as e:
            return _mcp_tool_result({'ok': False, 'error': 'Invalid identifier: ' + str(e)}, 'Error: Invalid identifier: ' + str(e), is_error=True)
        kind = str(payload.get('kind') or '').strip().lower()
        try:
            if kind == 'slsk_dir':
                out = _mcp_start_slsk_download(
                    str(payload.get('user') or '').strip(),
                    _slsk_norm_remote_path(str(payload.get('directory') or '').strip()),
                    payload.get('files') if isinstance(payload.get('files'), list) else [],
                    str(payload.get('title') or '').strip(),
                )
                data = {'ok': True, 'source': 'soulseek', 'status': 'started', **out}
                text = f"Soulseek download started. Files are downloading to {out.get('task_dir')}."
                return _mcp_tool_result(data, text)
            if kind == 'knaben_item':
                out = _mcp_start_rd_download(str(payload.get('title') or 'Knaben item').strip() or 'Knaben item', str(payload.get('magnet') or '').strip())
                data = {'ok': True, 'source': 'knaben', 'status': 'started', **out}
                text = f"Knaben download started. Files are downloading to {out.get('task_dir')}."
                return _mcp_tool_result(data, text)
            return _mcp_tool_result({'ok': False, 'error': 'Unsupported identifier type'}, 'Error: Unsupported identifier type', is_error=True)
        except Exception as e:
            return _mcp_tool_result({'ok': False, 'error': str(e)}, 'Error: ' + str(e), is_error=True)

    if name == 'debripod_get_tasks':
        tasks = []
        for t in list_tasks():
            try:
                tasks.append(task_public_dict(t))
            except Exception:
                continue
        data = {'ok': True, 'tasks': tasks}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    if name == 'debripod_get_library':
        data = {'ok': True, **_mcp_build_library_tree()}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    if name == 'debripod_get_recents':
        try:
            limit = int(args.get('limit') or 20)
        except Exception:
            limit = 20
        limit = max(1, min(limit, 100))
        snap = playback_snapshot_public()
        recent = list((snap.get('recent') or [])[:limit])
        data = {'ok': True, 'recent': recent, 'count': len(recent)}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    return _mcp_tool_result({'ok': False, 'error': 'Unknown tool: ' + name}, 'Error: Unknown tool: ' + name, is_error=True)


def _mcp_tools_list() -> List[dict]:
    return [
        {
            'name': 'debripod_knaben_search',
            'title': 'Debripod Knaben Search',
            'description': 'Search Knaben torrent results. Returns Debripod download identifiers.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'limit': {'type': 'integer', 'minimum': 1},
                },
                'required': ['query'],
            },
        },
        {
            'name': 'debripod_soulseek_search',
            'title': 'Debripod Soulseek Search',
            'description': 'Search Soulseek directory results. Returns Debripod download identifiers.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'limit': {'type': 'integer', 'minimum': 1},
                },
                'required': ['query'],
            },
        },
        {
            'name': 'debripod_download',
            'title': 'Debripod Download',
            'description': 'Start a Debripod download from a search result identifier. Soulseek downloads use whole directories. Knaben downloads queue the whole torrent selection.',
            'inputSchema': {
                'type': 'object',
                'properties': {'identifier': {'type': 'string'}},
                'required': ['identifier'],
            },
        },
        {
            'name': 'debripod_get_tasks',
            'title': 'Debripod Get Tasks',
            'description': 'List current Debripod tasks and their status.',
            'inputSchema': {'type': 'object', 'properties': {}},
        },
        {
            'name': 'debripod_get_library',
            'title': 'Debripod Get Library',
            'description': 'Return a folder tree for every configured library root. Files are omitted.',
            'inputSchema': {'type': 'object', 'properties': {}},
        },
        {
            'name': 'debripod_get_recents',
            'title': 'Debripod Get Recents',
            'description': 'Return recently watched and recently listened items.',
            'inputSchema': {
                'type': 'object',
                'properties': {'limit': {'type': 'integer', 'minimum': 1}},
            },
        },
    ]


def _mcp_handle_message(msg: dict, session_id: str = '') -> Tuple[Optional[dict], str, int]:
    if not isinstance(msg, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}, session_id, 400
    method = str(msg.get('method') or '').strip()
    msg_id = msg.get('id')
    params = msg.get('params') if isinstance(msg.get('params'), dict) else {}
    if method == 'initialize':
        client_info = params.get('clientInfo') if isinstance(params.get('clientInfo'), dict) else {}
        requested_version = str(params.get('protocolVersion') or '').strip() or MCP_PROTOCOL_VERSION
        session_id = _mcp_ensure_session(session_id, client_info)
        result = {
            'protocolVersion': MCP_PROTOCOL_VERSION if requested_version != MCP_PROTOCOL_VERSION else requested_version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'debripod', 'version': str(VERSION)},
            'instructions': 'Use the search tool to get download identifiers, then pass one identifier to the download tool.',
        }
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}, session_id, 200
    if method == 'notifications/initialized':
        session_id = _mcp_ensure_session(session_id)
        _mcp_set_initialized(session_id, True)
        return None, session_id, 202
    if method == 'ping':
        session_id = _mcp_ensure_session(session_id)
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {}}, session_id, 200
    if method == 'tools/list':
        session_id = _mcp_ensure_session(session_id)
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {'tools': _mcp_tools_list()}}, session_id, 200
    if method == 'tools/call':
        session_id = _mcp_ensure_session(session_id)
        tool_name = str(params.get('name') or '').strip()
        tool_args = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': _mcp_handle_tool_call(tool_name, tool_args)}, session_id, 200
    if msg_id is None:
        session_id = _mcp_ensure_session(session_id) if method else session_id
        return None, session_id, 202
    session_id = _mcp_ensure_session(session_id) if method else session_id
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32601, 'message': 'Method not found'}}, session_id, 404


@app.route('/mcp', methods=['GET'])
def mcp_get():
    bad = _mcp_validate_origin()
    if bad is not None:
        return bad
    session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    return _mcp_sse_response(session_id)


@app.route('/mcp', methods=['DELETE'])
def mcp_delete():
    bad = _mcp_validate_origin()
    if bad is not None:
        return bad
    session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    if session_id:
        with MCP_SESSIONS_LOCK:
            MCP_SESSIONS.pop(session_id, None)
    return Response(status=204)


@app.route('/mcp', methods=['POST'])
def mcp_post():
    bad = _mcp_validate_origin()
    if bad is not None:
        return bad
    try:
        body = request.get_json(force=True, silent=False)
    except Exception as e:
        return _mcp_error(None, -32700, 'Parse error', data=str(e), status=400)
    header_session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    msgs = body if isinstance(body, list) else [body]
    replies = []
    status = 200
    session_id = header_session_id
    for msg in msgs:
        reply, session_id, this_status = _mcp_handle_message(msg, session_id=session_id)
        status = max(status, this_status)
        if reply is not None:
            replies.append(reply)
    if not replies:
        session_id = _mcp_ensure_session(session_id or header_session_id) if msgs else session_id
        resp = Response(status=202)
        if session_id:
            resp.headers['Mcp-Session-Id'] = session_id
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    payload = replies if isinstance(body, list) else replies[0]
    return _mcp_json_response(payload, status=200 if status < 400 else status, session_id=session_id)

app.config["SECRET_KEY"] = os.urandom(24)
register_icon_routes(app)
register_lastfm_routes(
    app,
    api_key_provider=lambda: LASTFM_API_KEY,
    api_secret_provider=lambda: LASTFM_API_SECRET,
)
register_task_routes(app)


@app.context_processor
def inject_helpers():
    return {"human_bytes": human_bytes, "human_rate": human_rate}


def render_shell(autorefresh: int = 0, **ctx) -> str:
    try:
        hostport = request.host
    except Exception:
        hostport = f"localhost:{PORT}"
    info_json = json.dumps({"version": VERSION, "host": HOST, "port": PORT, "ddir": DOWNLOAD_DIR, "sdir": SOULSEEK_DOWNLOAD_DIR})
    return render_template(
        "shell.html",
        hostport=hostport,
        port=PORT,
        ddir=DOWNLOAD_DIR,
        autorefresh=autorefresh,
        tasks_poll_ms=TASKS_POLL_MS,
        icon_v=ICON_VERSION,
        info_json=info_json,
        **ctx,
    )
register_shell_routes(app, render_shell)


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
            return [], 0, 0, cache_key, "Soulseek service is not ready"
        try:
            items = svc.search(q)
        except Exception as e:
            return [], 0, 0, cache_key, "Soulseek search failed: " + str(e)
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
            "files_loaded": False,
            "files": [],
            "magnet": str(r.get("magnet") or ""),
            "infohash": str(r.get("infohash") or ""),
            "category": str(r.get("category") or ""),
            "verified": bool(r.get("verified")),
            "href": str(r.get("href") or ""),
            "_score": int(seeders) if isinstance(seeders, int) else 0,
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
                "files_loaded": True,
                "files": files_std,
                "_score": speed if speed > 0 else len(files_std),
            })
    return out


@app.route("/api/libsearch/combined", methods=["GET"])
def api_libsearch_combined():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Missing query", results=[], result_count=0, cache_key="")
    combined_cache_key = _make_search_cache_key("combined", q, {})
    knaben_results, knaben_err, _, _, _ = _search_knaben_cached(q, 1)
    slsk_users, slsk_total_results, dir_count, _, slsk_err = _search_soulseek_cached(q)
    youtube_results, youtube_err, _ = _search_youtube_cached(q)
    results = _standardize_youtube_results(youtube_results) + _standardize_soulseek_results(slsk_users) + _standardize_knaben_results(knaben_results)
    results.sort(key=lambda x: (int(x.get("_score") or 0), int(x.get("size") or 0), str(x.get("title") or "").lower()), reverse=True)
    for r in results:
        r.pop("_score", None)
    try:
        record_search_history(q, "combined", combined_cache_key)
    except Exception:
        pass
    err = "; ".join([x for x in [youtube_err, slsk_err, knaben_err] if x])
    return jsonify(ok=True, q=q, cache_key=combined_cache_key, results=results, result_count=len(results), knaben_results=knaben_results, slsk_users=slsk_users, youtube_results=youtube_results, dir_count=dir_count, file_count=slsk_total_results, error=err)


def _removed_route(*args, **kwargs):
    def deco(fn):
        return fn
    return deco


@_removed_route("/api/libsearch/knaben", methods=["GET"])
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



@_removed_route("/api/libsearch/soulseek_start", methods=["GET"])
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
    except Exception as e:
        _slsk_session_mark_done(sid, error=str(e))
        return jsonify(ok=False, error="Soulseek search failed: " + str(e), sid=sid, done=True, slsk_users=[], file_count=0, dir_count=0, cache_key=cache_key)

    return jsonify(ok=True, q=q, cache_key=cache_key, sid=sid, rev=0, done=False, slsk_users=[], file_count=0, dir_count=0, error="", changed=True)

@_removed_route("/api/libsearch/soulseek_poll", methods=["GET"])
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

@_removed_route("/api/libsearch/soulseek", methods=["GET"])
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
        except Exception as e:
            return jsonify(ok=False, error="Soulseek search failed: " + str(e), slsk_users=[], result_count=0, cache_key=cache_key)

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
    except Exception as e:
        return jsonify(ok=False, error="Soulseek browse failed: " + str(e), user=user, dirs=[], selected_dir=selected_dir)

    dirs = _slsk_group_items_to_dirs(user, items)
    dir_paths = {str(d.get("directory") or "") for d in dirs}
    if selected_dir and selected_dir not in dir_paths:
        selected_dir = ""

    return jsonify(ok=True, user=user, dirs=dirs, selected_dir=selected_dir, file_count=sum(int(d.get("total_files") or 0) for d in dirs), dir_count=len(dirs))


def build_task_dir(task_id: str, title: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = sanitize_folder_name(title)
    folder = f"{stamp}_{base}_{task_id[:6]}"
    folder = sanitize_folder_name(folder)
    return os.path.join(DOWNLOAD_DIR, folder)


@app.route("/enqueue", methods=["POST"])
def enqueue():
    title = (request.form.get("title") or "").strip() or "Knaben item"
    magnet = (request.form.get("magnet") or "").strip()
    if not magnet.startswith("magnet:?"):
        abort(400)

    task_id = uuid.uuid4().hex
    task_dir = build_task_dir(task_id, title)
    os.makedirs(task_dir, exist_ok=True)

    t = Task(id=task_id, title=title, magnet=magnet, task_dir=task_dir, state="queued", message="Queued")
    with TASKS_LOCK:
        TASKS[task_id] = t

    th = threading.Thread(target=worker, args=(task_id,), daemon=True)
    th.start()

    ref = request.headers.get("Referer") or ""
    return redirect(ref or url_for("index", tab="search"))


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
    except Exception as e:
        return jsonify(ok=False, error=str(e), files=[], file_count=0, size=0), 500


@app.route("/api/youtube/channel", methods=["GET"])
def api_youtube_channel():
    channel_id = (request.args.get('channel_id') or '').strip()
    if not channel_id:
        return jsonify(ok=False, error='Missing channel id', results=[], result_count=0), 400
    try:
        results = youtube_channel_browse(channel_id)
        return jsonify(ok=True, results=results, result_count=len(results))
    except Exception as e:
        return jsonify(ok=False, error=str(e), results=[], result_count=0), 500


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
    t = Task(id=task_id, title=title, magnet=url, task_dir=task_dir, source='youtube', state='queued', message='Queued', rd_files=entries)
    with TASKS_LOCK:
        TASKS[task_id] = t
    th = threading.Thread(target=worker, args=(task_id,), daemon=True)
    th.start()
    return jsonify(ok=True, task_id=task_id)


@app.route("/api/search_history", methods=["GET"])
def api_search_history():
    try:
        with _SEARCH_DISK_LOCK:
            items = _load_search_history()
        # hide internal keys from the UI
        out = [{"q": it.get("q") or "", "engine": it.get("engine") or ""} for it in items]
        return jsonify({"ok": True, "items": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "items": []})


@app.route("/api/search_history/clear", methods=["POST"])
def api_search_history_clear():
    try:
        clear_search_history_and_cache()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/libsearch/stream_selected", methods=["POST"])
def api_libsearch_stream_selected():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    try:
        out = _engine_prepare_stream_session(data)
        return jsonify({"ok": True, **out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/rd/preview_files", methods=["POST"])
def api_rd_preview_files():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    magnet = str(data.get("magnet") or "").strip()
    if not magnet.startswith("magnet:?"):
        return jsonify({"ok": False, "error": "Invalid magnet"}), 400
    try:
        torrent_id = rd_add_magnet(magnet)
        info = rd_torrent_info(torrent_id)
        files = info.get("files") or []
        out: List[Dict[str, Any]] = []
        if isinstance(files, list):
            for f in files:
                if not isinstance(f, dict):
                    continue
                fid = f.get("id")
                if fid is None:
                    continue
                path = f.get("path") or f.get("file_path") or f.get("filename") or ""
                b = f.get("bytes")
                if b is None:
                    b = f.get("size") or f.get("filesize") or 0
                try:
                    out.append({"id": int(fid), "path": str(path), "bytes": int(b or 0)})
                except Exception:
                    continue
        return jsonify({"ok": True, "torrent_id": str(torrent_id), "files": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500




@app.route("/api/rd/load_files", methods=["POST"])
def api_rd_load_files():
    # Backwards compatible alias for older frontends.
    return api_rd_preview_files()

@app.route("/api/rd/enqueue_selected", methods=["POST"])
def api_rd_enqueue_selected():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    title = str(data.get("title") or "").strip() or "Knaben item"
    magnet = str(data.get("magnet") or "").strip()
    torrent_id = str(data.get("torrent_id") or "").strip()
    file_ids = data.get("file_ids") or []

    if not torrent_id:
        return jsonify({"ok": False, "error": "Missing torrent id"}), 400

    clean_ids: List[int] = []
    if isinstance(file_ids, list):
        for x in file_ids:
            try:
                clean_ids.append(int(x))
            except Exception:
                continue

    if not clean_ids:
        return jsonify({"ok": False, "error": "No files selected"}), 400

    task_id = uuid.uuid4().hex
    task_dir = build_task_dir(task_id, title)
    os.makedirs(task_dir, exist_ok=True)

    t = Task(
        id=task_id,
        title=title,
        magnet=magnet,
        task_dir=task_dir,
        state="queued",
        message="Queued",
        torrent_id=torrent_id,
        rd_selected_file_ids=clean_ids,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t

    th = threading.Thread(target=worker, args=(task_id,), daemon=True)
    th.start()

    return jsonify({"ok": True, "task_id": task_id})


@app.route("/api/soulseek/enqueue", methods=["POST"])
def api_soulseek_enqueue():
    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return jsonify({"ok": False, "error": "Soulseek is not configured or failed to start"}), 400

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
        source="soulseek",
        state="queued",
        message="Queued",
        torrent_id=None,
        slsk_user=user,
        slsk_directory=directory,
        slsk_files=files,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t

    try:
        svc.enqueue_downloads(task_id, user, remote_paths)
    except Exception as e:
        set_task(task_id, state="error", message="Failed to queue Soulseek download: " + str(e))
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "task_id": task_id})




@app.route("/cancel", methods=["POST"])
def cancel():
    task_id = (request.form.get("task_id") or "").strip()
    if not task_id:
        abort(400)
    cancel_task(task_id)
    return redirect(url_for("tasks"))




# =========================
# Library API
# =========================

@app.route("/api/library/config", methods=["GET"])
def api_library_config():
    rts = []
    for rid, name, ap, mode in roots():
        rts.append({"id": rid, "name": name, "mode": mode})
    return jsonify(
        {
            "roots": rts,
            "preload_enabled": bool(PRELOAD_NEXT_FOR_GAPLESS),
            "preload_bytes": int(PRELOAD_NEXT_CHUNK_BYTES),
            "lastfm_enabled": bool(lastfm_enabled()),
        }
    )





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
    _, _, root_abs, _ = r
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    if not os.path.isdir(abs_path):
        abort(404)

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
    return jsonify({"entries": entries})


def build_index_for_root(root_abs: str) -> dict:
    tracks = []
    videos = []
    for base, dirs, files in os.walk(root_abs):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != CACHE_DIR_NAME]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in AUDIO_EXTS and ext not in VIDEO_EXTS:
                continue
            abs_p = os.path.join(base, fn)
            rel = os.path.relpath(abs_p, root_abs).replace("\\", "/")
            if ext in VIDEO_EXTS:
                meta = file_meta_cached(abs_p)
                videos.append({"rel": rel, "name": fn, "title": meta.get("title") or fn})
                continue

            meta = file_meta_cached(abs_p)
            title = meta.get("title") or os.path.splitext(fn)[0]
            artist = (meta.get("artist") or "").strip()
            album_artist = (meta.get("album_artist") or artist or "").strip()
            artist = album_artist or artist
            album = (meta.get("album") or "").strip()
            genre = (meta.get("genre") or "").strip()
            track = (meta.get("track") or "").strip()
            duration = meta.get("duration")
            tracks.append(
                {
                    "rel": rel,
                    "name": fn,
                    "title": title,
                    "artist": artist,
                    "album_artist": album_artist,
                    "album": album,
                    "genre": genre,
                    "folder": ("/" + os.path.dirname(rel).replace("\\", "/").strip("/")) if os.path.dirname(rel).strip() else "/",
                    "track": track,
                    "duration": duration,
                }
            )
    return {"tracks": tracks, "videos": videos}


def _index_cache_dir() -> str:
    p = os.path.join(cache_dir(), "library_index")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def _index_cache_path(root_id: str) -> str:
    rid = re.sub(r"[^a-fA-F0-9]", "", str(root_id or ""))[:64] or sha1_text(str(root_id or ""))
    return os.path.join(_index_cache_dir(), f"{rid}.json")


def _index_cache_payload(root_id: str, root_abs: str, data: dict) -> dict:
    return {
        "version": 1,
        "root_id": str(root_id or ""),
        "root_abs": os.path.abspath(root_abs),
        "saved_at": time.time(),
        "data": data if isinstance(data, dict) else {"tracks": [], "videos": []},
    }


def _save_index_to_disk(root_id: str, root_abs: str, data: dict) -> None:
    try:
        _atomic_write_json(_index_cache_path(root_id), _index_cache_payload(root_id, root_abs, data))
    except Exception:
        pass


def _load_index_from_disk(root_id: str, root_abs: str) -> Optional[dict]:
    try:
        js = _read_json_file(_index_cache_path(root_id))
        if not isinstance(js, dict):
            return None
        cached_root = os.path.abspath(str(js.get("root_abs") or ""))
        if cached_root != os.path.abspath(root_abs):
            return None
        data = js.get("data")
        if not isinstance(data, dict):
            return None
        tracks = data.get("tracks")
        videos = data.get("videos")
        if not isinstance(tracks, list) or not isinstance(videos, list):
            return None
        return {"tracks": tracks, "videos": videos}
    except Exception:
        return None


def _clear_index_disk_cache() -> None:
    try:
        root = _index_cache_dir()
        for fn in os.listdir(root):
            if fn.endswith('.json'):
                try:
                    os.remove(os.path.join(root, fn))
                except Exception:
                    pass
    except Exception:
        pass


INDEX_CACHE: Dict[str, Tuple[float, dict]] = {}
INDEX_BUILDING: Dict[str, bool] = {}
INDEX_LOCK = threading.Lock()


def ensure_index_async(root_id: str, root_abs: str) -> None:
    now = time.time()
    with INDEX_LOCK:
        hit = INDEX_CACHE.get(root_id)
        if hit and (now - hit[0]) < 600:
            return
        if not hit:
            disk = _load_index_from_disk(root_id, root_abs)
            if disk is not None:
                INDEX_CACHE[root_id] = (now, disk)
                return
        if INDEX_BUILDING.get(root_id):
            return
        INDEX_BUILDING[root_id] = True

    def build():
        try:
            data = build_index_for_root(root_abs)
            _save_index_to_disk(root_id, root_abs, data)
            with INDEX_LOCK:
                INDEX_CACHE[root_id] = (time.time(), data)
        finally:
            with INDEX_LOCK:
                INDEX_BUILDING[root_id] = False

    threading.Thread(target=build, daemon=True).start()


def get_index(root_id: str) -> Optional[dict]:
    with INDEX_LOCK:
        hit = INDEX_CACHE.get(root_id)
        if hit:
            return hit[1]
    r = root_by_id(root_id)
    if not r:
        return None
    _, _, root_abs, _ = r
    disk = _load_index_from_disk(root_id, root_abs)
    if disk is None:
        return None
    with INDEX_LOCK:
        INDEX_CACHE[root_id] = (time.time(), disk)
    return disk


@app.route("/api/library/reindex", methods=["POST"])
def api_library_reindex():
    with INDEX_LOCK:
        INDEX_CACHE.clear()
        INDEX_BUILDING.clear()
    _clear_index_disk_cache()
    return jsonify({"ok": True})

@app.route("/api/library/building", methods=["GET"])
def api_library_building():
    with INDEX_LOCK:
        roots_status = {str(k): bool(v) for k, v in (INDEX_BUILDING or {}).items()}
        any_building = any(roots_status.values())
    return jsonify({"ok": True, "any_building": any_building, "roots": roots_status})



def track_sort_key(track_s: str) -> Tuple[int, str]:
    s = (track_s or "").strip()
    if not s:
        return (10**9, "")
    m = re.match(r"(\d+)", s)
    if not m:
        return (10**9, s)
    return (int(m.group(1)), s)


@app.route("/api/library/metadata", methods=["GET"])
def api_library_metadata():
    root_id = (request.args.get("root_id") or "").strip()
    level = (request.args.get("level") or "").strip().lower()
    value = (request.args.get("value") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    if level == "playlists":
        items = scan_root_playlists(root_abs)
        if not items:
            items = [{"kind": "info", "label": "No playlists found"}]
        return jsonify({"items": items})

    if level == "playlist_tracks":
        if is_smart_playlist_rel(value):
            items = smart_playlist_tracks_for_root(root_abs, value, root_id)
        else:
            items = playlist_tracks_for_root(root_abs, value)
        if not items:
            items = [{"kind": "info", "label": "No playable tracks found in playlist"}]
        return jsonify({"items": items})

    ensure_index_async(root_id, root_abs)
    data = get_index(root_id)
    if data is None:
        if level == "top":
            cats = [
                {"key": "artists", "label": "Artists"},
                {"key": "albums", "label": "Albums"},
                {"key": "songs", "label": "Songs"},
                {"key": "liked_songs", "label": "Liked Songs"},
                {"key": "playlists", "label": "Playlists"},
                {"key": "genres", "label": "Genres"},
                {"key": "videos", "label": "Videos"},
                {"key": "folders", "label": "Folders"},
            ]
            return jsonify({"categories": cats, "building": True})
        return jsonify({"items": [{"kind": "info", "label": "Indexing media files..."}], "building": True})

    tracks = data.get("tracks") or []
    vids = data.get("videos") or []

    if level == "top":
        cats = [
            {"key": "artists", "label": "Artists"},
            {"key": "albums", "label": "Albums"},
            {"key": "songs", "label": "Songs"},
            {"key": "liked_songs", "label": "Liked Songs"},
            {"key": "playlists", "label": "Playlists"},
            {"key": "genres", "label": "Genres"},
            {"key": "videos", "label": "Videos"},
            {"key": "folders", "label": "Folders"},
        ]
        return jsonify({"categories": cats, "building": False})

    if level == "artists":
        s = sorted({(t.get("artist") or "").strip() for t in tracks if (t.get("artist") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "artist", "label": a, "value": a} for a in s] or [{"kind": "info", "label": "No artist tags found"}]
        return jsonify({"items": items})

    if level == "albums":
        artist_filter = value
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
        return jsonify({"items": albums})

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
            return jsonify({"items": [{"kind": "info", "label": "Last.fm not configured"}]})
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
            tr.append({"kind": "track", "label": label, "rel": t.get("rel"), "badge": (t.get("track") or "")})
        tr.sort(key=lambda x: track_sort_key(x.get("badge") or "") + (x.get("label") or "",))
        if not tr:
            tr = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": tr})


    if level == "liked_songs":
        if not lastfm_enabled():
            return jsonify({"items": [{"kind": "info", "label": "Last.fm not configured"}]})
        items = []
        for t in tracks:
            a = (t.get("artist") or "").strip()
            tt = (t.get("title") or t.get("name") or "").strip()
            b = (t.get("album") or "").strip()
            if not a or not tt:
                continue
            if not lastfm_is_loved(a, tt, b):
                continue
            items.append({"kind": "track", "label": (t.get("title") or t.get("name") or "Track"), "rel": t.get("rel"), "badge": (t.get("track") or "")})
        items.sort(key=lambda x: (x.get("label") or "").lower())
        if not items:
            items = [{"kind": "info", "label": "No liked songs found"}]
        return jsonify({"items": items[:3000]})

    if level == "songs":
        s = sorted(tracks, key=lambda x: (x.get("title") or x.get("name") or "").lower())
        items = [{"kind": "track", "label": (t.get("title") or t.get("name") or "Track"), "rel": t.get("rel")} for t in s[:3000]]
        if not items:
            items = [{"kind": "info", "label": "No songs found"}]
        return jsonify({"items": items})

    if level == "genres":
        s = sorted({(t.get("genre") or "").strip() for t in tracks if (t.get("genre") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "genre", "label": g, "value": g} for g in s] or [{"kind": "info", "label": "No genre tags found"}]

        return jsonify({"items": items})

    if level == "genre_albums":
        genre = value
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
        return jsonify({"items": albums})

    if level == "genre_tracks":
        genre = value
        items = []
        for t in tracks:
            if (t.get("genre") or "").strip() != genre:
                continue
            label = t.get("title") or t.get("name") or "Track"
            items.append({"kind": "track", "label": label, "rel": t.get("rel")})
        items.sort(key=lambda x: (x.get("label") or "").lower())
        if not items:
            items = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": items})

    if level == "videos":
        items = []
        for v in sorted(vids, key=lambda x: (x.get("title") or x.get("name") or "").lower())[:3000]:
            items.append({"kind": "file", "label": v.get("name") or v.get("title") or "Video", "rel": v.get("rel"), "media": "video", "badge": "video"})
        if not items:
            items = [{"kind": "info", "label": "No videos found"}]
        return jsonify({"items": items})

    return jsonify({"items": [{"kind": "info", "label": "Unsupported view"}]})


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
        "-hls_fmp4_init_filename", "init.mp4",
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
            except Exception as e:
                raise RuntimeError(str(e))
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
            line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + base + quote(m.group(1), safe="/._-") + '"', line)
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
    except RuntimeError as e:
        return Response(str(e), status=500, mimetype="text/plain")


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


@app.route("/stream/<root_id>/<path:relpath>", methods=["GET", "HEAD"])
def stream(root_id: str, relpath: str):
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(unquote(relpath))
        if not it:
            abort(404)
        if str(it.get("source") or "").strip().lower() == 'youtube':
            try:
                local_path = _prepare_youtube_stream_file(str(it.get('youtube_url') or it.get('url') or ''), it)
            except Exception as e:
                return Response(str(e), status=502, mimetype="text/plain")
            return range_response(local_path)
        headers = {}
        rng = request.headers.get("Range")
        if rng:
            headers["Range"] = rng
        method = "HEAD" if request.method == "HEAD" else "GET"
        try:
            upstream = requests.request(method, str(it.get("url") or ""), headers=headers, stream=True, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        except Exception as e:
            return Response(str(e), status=502, mimetype="text/plain")
        excluded = {"content-encoding", "transfer-encoding", "connection"}
        out_headers = []
        for k2, v2 in upstream.headers.items():
            if str(k2).lower() in excluded:
                continue
            out_headers.append((k2, v2))
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
        return Response(msg, status=500, mimetype="text/plain")

    return range_response(playable)


@app.route("/watch/<root_id>/<path:relpath>", methods=["GET"])
def watch(root_id: str, relpath: str):
    rel = unquote(relpath)
    # legacy endpoint kept for older links, now routed into the Library player
    return redirect("/?tab=library&vroot=" + quote(root_id) + "&vrel=" + quote(rel, safe=""))



def main():
    global SOULSEEK_SERVICE
    ensure_dirs()
    load_playback_state()
    try:
        configure_aioslsk_logging()
    except Exception:
        pass
    if not REAL_DEBRID_API_KEY:
        raise RuntimeError("Set REAL_DEBRID_API_KEY at the top of this file before running")

    # Start Soulseek once at startup and keep it connected for the whole session.
    if (SOULSEEK_USERNAME or "").strip() and (SOULSEEK_PASSWORD or "").strip():
        try:
            SOULSEEK_SERVICE = SoulseekService(
                username=SOULSEEK_USERNAME,
                password=SOULSEEK_PASSWORD,
                download_dir=SOULSEEK_DOWNLOAD_DIR,
                listening_port=SOULSEEK_LISTENING_PORT,
                obfuscated_port=SOULSEEK_OBFUSCATED_PORT,
                search_timeout_sec=SOULSEEK_SEARCH_TIMEOUT_SEC,
                search_max_results=SOULSEEK_SEARCH_MAX_RESULTS,
            )
            if not SOULSEEK_SERVICE.is_ready():
                err = SOULSEEK_SERVICE.start_error() or "Unknown start error"
                print("Soulseek failed to start:", err)
        except Exception as e:
            SOULSEEK_SERVICE = None
            print("Soulseek failed to start:", str(e))
    else:
        SOULSEEK_SERVICE = None

    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
