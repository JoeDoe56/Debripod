
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
from flask import Flask, request, redirect, url_for, render_template_string, abort, Response, jsonify

from .Tasks.manager import TASKS, TASKS_LOCK, Task, get_task, list_tasks, set_task

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

# =========================
# Helpers
# =========================

AUDIO_EXTS = {
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".alac",
}
VIDEO_EXTS = {
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts", ".m2ts",
}
PLAYLIST_EXTS = {
    ".m3u", ".m3u8", ".pls",
}
PLAYLISTS_FOLDER_NAME = "Debripod-Playlists"
SMART_PLAYLISTS_FOLDER_NAME = "Debripod-SmartPlaylists"
SMART_PLAYLIST_RULES_FILENAME = "rules.txt"
SMART_PLAYLIST_MEDIA_FILENAME = "playlist.m3u8"

SMART_PLAYLIST_RULES_TEMPLATE = """[name]
[any|all]{
#liked=(\"true\"|\"false\")
#artist(is|not)=(\"artist 1\", \"artist 2\")
#albumartist(is|not)=(\"artist 1\", \"artist 2\")
#album(is|not)=(\"album 1\", \"album 2\")
#genre(is|not)=(\"genre 1\", \"genre 2\")
#folder(is|not)=(\"/dir1\", \"/dir2\")
}"""


def ensure_dirs() -> None:
    if not os.path.isabs(DOWNLOAD_DIR):
        raise ValueError("DOWNLOAD_DIR must be an absolute path")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(SOULSEEK_DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(soulseek_incoming_dir(), exist_ok=True)
    os.makedirs(cache_dir(), exist_ok=True)
    os.makedirs(transcode_cache_dir(), exist_ok=True)
    os.makedirs(art_cache_dir(), exist_ok=True)

    # Init Last.fm cache paths and load cached data
    global _LASTFM_SESSION_CACHE_PATH, _LASTFM_LOVED_DB_PATH
    _LASTFM_SESSION_CACHE_PATH = os.path.join(cache_dir(), "lastfm_session.json")
    _LASTFM_LOVED_DB_PATH = os.path.join(cache_dir(), "lastfm_loved.json")
    _lastfm_load_session_cache()
    _lastfm_loved_load()
    # Best-effort: refresh loved cache occasionally so ♥ shows for existing likes
    try:
        with _LASTFM_LOVED_LOCK:
            last_upd = int(_LASTFM_LOVED.get('updated') or 0)
        if lastfm_enabled() and (time.time() - float(last_upd or 0)) > 6 * 3600:
            _lastfm_async(lastfm_sync_loved_from_remote, lastfm_username())
    except Exception:
        pass


def cache_dir() -> str:
    return os.path.join(DOWNLOAD_DIR, CACHE_DIR_NAME)


def transcode_cache_dir() -> str:
    return os.path.join(cache_dir(), "transcoded")


def art_cache_dir() -> str:
    return os.path.join(cache_dir(), "art")


# =========================
# Search history + server-side search results cache (disk)
# =========================

SEARCH_HISTORY_MAX_ITEMS = 50
SEARCH_DISK_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
_SEARCH_DISK_LOCK = threading.Lock()


def _search_cache_root_dir() -> str:
    p = os.path.join(cache_dir(), "search_cache")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def _search_history_path() -> str:
    return os.path.join(_search_cache_root_dir(), "search_history.json")


def _search_cache_file_path(key: str) -> str:
    key2 = re.sub(r"[^a-fA-F0-9]", "", str(key or ""))[:64]
    if not key2:
        key2 = sha1_text(str(key or ""))
    return os.path.join(_search_cache_root_dir(), f"res_{key2}.json")


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _read_json_file(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _make_search_cache_key(engine: str, q: str, extra: Optional[dict] = None) -> str:
    eng = (engine or "").strip().lower()
    qq = (q or "").strip()
    extra2 = extra if isinstance(extra, dict) else {}
    payload = {"engine": eng, "q": qq, "extra": extra2}
    return sha1_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _disk_cache_get(key: str) -> Optional[dict]:
    p = _search_cache_file_path(key)
    d = _read_json_file(p)
    if not d:
        return None
    try:
        created = float(d.get("created") or 0.0)
    except Exception:
        created = 0.0
    if created > 0 and (time.time() - created) > SEARCH_DISK_CACHE_TTL_SECONDS:
        return None
    return d


def _disk_cache_set(key: str, engine: str, q: str, extra: Optional[dict], payload: dict) -> None:
    p = _search_cache_file_path(key)
    d = {
        "created": time.time(),
        "engine": (engine or "").strip().lower(),
        "q": (q or "").strip(),
        "extra": extra if isinstance(extra, dict) else {},
        "payload": payload if isinstance(payload, dict) else {},
    }
    _atomic_write_json(p, d)


def _load_search_history() -> List[dict]:
    p = _search_history_path()
    d = _read_json_file(p)
    items = d.get("items") if isinstance(d, dict) else None
    out: List[dict] = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            q = str(it.get("q") or "").strip()
            eng = str(it.get("engine") or "").strip().lower()
            key = str(it.get("cache_key") or "").strip()
            try:
                ts = float(it.get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if not q or eng not in ("knaben", "soulseek", "youtube", "combined") or not key:
                continue
            out.append({"q": q, "engine": eng, "cache_key": key, "ts": ts})
    out.sort(key=lambda x: float(x.get("ts") or 0.0), reverse=True)
    return out[:SEARCH_HISTORY_MAX_ITEMS]


def _save_search_history(items: List[dict]) -> None:
    p = _search_history_path()
    out = []
    for it in (items or [])[:SEARCH_HISTORY_MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        q = str(it.get("q") or "").strip()
        eng = str(it.get("engine") or "").strip().lower()
        key = str(it.get("cache_key") or "").strip()
        ts = float(it.get("ts") or 0.0) if it.get("ts") is not None else 0.0
        if not q or eng not in ("knaben", "soulseek", "youtube", "combined") or not key:
            continue
        out.append({"q": q, "engine": eng, "cache_key": key, "ts": ts})
    _atomic_write_json(p, {"items": out})


def record_search_history(q: str, engine: str, cache_key: str) -> None:
    qq = (q or "").strip()
    eng = (engine or "").strip().lower()
    key = (cache_key or "").strip()
    if not qq or eng not in ("knaben", "soulseek", "youtube", "combined") or not key:
        return
    with _SEARCH_DISK_LOCK:
        items = _load_search_history()
        # de-dupe by (engine, q)
        items = [it for it in items if not (it.get("engine") == eng and it.get("q") == qq)]
        items.insert(0, {"q": qq, "engine": eng, "cache_key": key, "ts": time.time()})
        _save_search_history(items)


def clear_search_history_and_cache() -> None:
    with _SEARCH_DISK_LOCK:
        try:
            p = _search_history_path()
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
        # Remove cached result json files
        try:
            root = _search_cache_root_dir()
            for fn in os.listdir(root):
                if fn.startswith("res_") and fn.endswith(".json"):
                    try:
                        os.remove(os.path.join(root, fn))
                    except Exception:
                        pass
        except Exception:
            pass


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return "download"
    return name[:240]


def sanitize_folder_name(name: str) -> str:
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        return "task"
    if len(name) > 80:
        name = name[:80].rstrip()
    return name


def human_bytes(n: Optional[int]) -> str:
    if n is None or n < 0:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024.0 or u == units[-1]:
            if u == "B":
                return f"{int(f)} {u}"
            return f"{f:.2f} {u}"
        f /= 1024.0
    return f"{int(n)} B"


def human_rate(bps: Optional[int]) -> str:
    if bps is None or bps <= 0:
        return "?"
    return f"{human_bytes(int(bps))}/s"



def sha1_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def is_playlist_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in PLAYLIST_EXTS


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


def run_cmd(args: List[str]) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", f"Command not found: {args[0]}"
    except Exception as e:
        return 1, "", str(e)


def ffprobe_json(path: str) -> dict:
    code, out, err = run_cmd([FFPROBE_PATH, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if code != 0:
        raise RuntimeError(err.strip() or "ffprobe failed")
    try:
        return json.loads(out)
    except Exception:
        raise RuntimeError("ffprobe returned invalid json")


def pick_mime(path: str) -> str:
    mt, _ = mimetypes.guess_type(path)
    if mt:
        return mt
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mkv":
        return "video/x-matroska"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".m4a":
        return "audio/mp4"
    if ext == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


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
def range_response(file_path: str) -> Response:
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        abort(404)

    file_size = os.path.getsize(file_path)
    mime = pick_mime(file_path)
    range_header = request.headers.get("Range", "")
    method = request.method.upper()

    if not range_header:
        headers = {"Content-Length": str(file_size), "Accept-Ranges": "bytes"}
        if method == "HEAD":
            return Response(status=200, headers=headers, mimetype=mime)

        def gen():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return Response(gen(), status=200, headers=headers, mimetype=mime)

    m = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        headers = {"Content-Length": str(file_size), "Accept-Ranges": "bytes"}
        if method == "HEAD":
            return Response(status=200, headers=headers, mimetype=mime)
        return Response(open(file_path, "rb"), status=200, headers=headers, mimetype=mime)

    start = int(m.group(1))
    end_s = m.group(2)
    end = int(end_s) if end_s and end_s.isdigit() else file_size - 1
    start = max(0, min(start, file_size - 1))
    end = max(start, min(end, file_size - 1))
    length = end - start + 1

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "no-cache",
    }

    if method == "HEAD":
        return Response(status=206, headers=headers, mimetype=mime)

    def gen():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return Response(gen(), status=206, headers=headers, mimetype=mime)


def _parse_library_folder_spec(spec: str) -> Optional[Tuple[str, str, str]]:
    """Parse one LIBRARY_FOLDERS entry into (display_name, abs_path, mode).

    Supported forms:
      - r"C:\\path\\to\\music"           -> mode defaults to 'folders'
      - r"C:\\path\\to\\music:list"      -> mode 'folders'
      - r"C:\\path\\to\\music:meta"      -> mode 'metadata'

    Note: Windows drive letters contain ':', so we only treat the final ':' as a mode suffix when the suffix
    matches a known mode keyword.
    """
    spec = (spec or "").strip()
    if not spec:
        return None

    mode = None
    path = spec

    if ":" in spec:
        p, suf = spec.rsplit(":", 1)
        suf_l = (suf or "").strip().lower()
        if suf_l in ("meta", "metadata", "m"):
            mode = "metadata"
            path = p
        elif suf_l in ("list", "folders", "folder", "l"):
            mode = "folders"
            path = p

    if mode is None:
        mode = "folders"

    path = (path or "").strip().strip('"').strip("'")
    if not path or not os.path.isabs(path):
        return None

    ap = os.path.abspath(path)
    name = os.path.basename(ap.rstrip("\\/")) or ap
    return name, ap, mode


def roots() -> List[Tuple[str, str, str, str]]:
    # Start with configured roots
    parsed: List[Tuple[str, str, str]] = []

    for spec in (LIBRARY_FOLDERS or []):
        p = _parse_library_folder_spec(spec)
        if not p:
            continue
        name, ap, mode = p
        parsed.append((name, ap, mode))

    out: List[Tuple[str, str, str, str]] = []
    seen = set()
    for name, ap, mode in parsed:
        ap2 = os.path.abspath(ap)
        if ap2 in seen:
            continue
        seen.add(ap2)
        rid = sha1_text(ap2)
        out.append((rid, name, ap2, mode))
    return out


def root_by_id(root_id: str) -> Optional[Tuple[str, str, str, str]]:
    for rid, name, ap, mode in roots():
        if rid == root_id:
            return rid, name, ap, mode
    return None


def safe_path_join(root_abs: str, rel: str) -> str:
    rel = rel or ""
    rel = rel.replace("\\", "/")
    rel = rel.lstrip("/")
    joined = os.path.abspath(os.path.join(root_abs, rel.replace("/", os.sep)))
    root_abs = os.path.abspath(root_abs)
    try:
        common = os.path.commonpath([root_abs, joined])
    except Exception:
        raise ValueError("Invalid path")
    if common != root_abs:
        raise ValueError("Path escapes root")
    return joined


# =========================
# =========================
# Last.fm scrobbling + likes (Web Services API / Scrobbling 2.0)
# =========================
LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
LASTFM_REQUEST_TIMEOUT_SECONDS = 12

_LASTFM_SESSION_LOCK = threading.Lock()
_LASTFM_SESSION_CACHE_PATH = ""  # set after CACHE_DIR is initialized
_LASTFM_LOVED_DB_PATH = ""       # set after CACHE_DIR is initialized

_LASTFM_SESSION = {
    "sk": "",
    "username": "",
    "ts": 0,
}

_LASTFM_LOVED = {
    "version": 1,
    "updated": 0,
    "tracks": {},  # key -> 1
}
_LASTFM_LOVED_LOCK = threading.Lock()


def lastfm_enabled() -> bool:
    # Enabled when we have API credentials and a session key.
    return bool((LASTFM_API_KEY or "").strip() and (LASTFM_API_SECRET or "").strip() and (lastfm_session_key() or "").strip())


def _md5_hex(s: str) -> str:
    return hashlib.md5((s or "").encode("utf-8", "ignore")).hexdigest()


def _lastfm_param_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def lastfm_session_key() -> str:
    # Prefer explicit config override, otherwise use cached session.
    sk = (LASTFM_SESSION_KEY or "").strip()
    if sk:
        return sk
    with _LASTFM_SESSION_LOCK:
        return str(_LASTFM_SESSION.get("sk") or "").strip()


def lastfm_username() -> str:
    with _LASTFM_SESSION_LOCK:
        return str(_LASTFM_SESSION.get("username") or "").strip()


def _lastfm_sign(params: Dict[str, Any]) -> str:
    # Per Last.fm auth spec: sort params by name, concat <name><value>, exclude format/callback, append secret, md5.
    items = []
    for k, v in (params or {}).items():
        if k in ("format", "callback"):
            continue
        items.append((str(k), _lastfm_param_str(v)))
    items.sort(key=lambda kv: kv[0])
    s = "".join([k + v for k, v in items]) + (LASTFM_API_SECRET or "")
    return _md5_hex(s)


def _lastfm_api_post(method: str, params: Dict[str, Any], require_auth: bool = True) -> Dict[str, Any]:
    if not (LASTFM_API_KEY or "").strip() or not (LASTFM_API_SECRET or "").strip():
        raise RuntimeError("Last.fm API key/secret not configured")

    base: Dict[str, Any] = {"method": method, "api_key": (LASTFM_API_KEY or "").strip(), "format": "json"}
    if params:
        base.update(params)

    if require_auth:
        sk = lastfm_session_key()
        if not sk:
            raise RuntimeError("Last.fm session key not configured")
        base["sk"] = sk

    base["api_sig"] = _lastfm_sign(base)

    r = requests.post(
        LASTFM_API_ROOT,
        data={k: _lastfm_param_str(v) for k, v in base.items()},
        timeout=LASTFM_REQUEST_TIMEOUT_SECONDS,
    )
    try:
        js = r.json()
    except Exception:
        js = {}
    if isinstance(js, dict) and js.get("error"):
        raise RuntimeError(str(js.get("message") or "Last.fm API error"))
    return js if isinstance(js, dict) else {}



def _lastfm_api_get(method: str, params: Optional[Dict[str, Any]] = None, require_auth: bool = False) -> Dict[str, Any]:
    # Some Last.fm methods are typically called via GET. This helper mirrors _lastfm_api_post.
    if not (LASTFM_API_KEY or "").strip() or not (LASTFM_API_SECRET or "").strip():
        raise RuntimeError("Last.fm API key/secret not configured")

    base: Dict[str, Any] = {"method": method, "api_key": (LASTFM_API_KEY or "").strip(), "format": "json"}
    if params:
        base.update(params)

    if require_auth:
        sk = lastfm_session_key()
        if not sk:
            raise RuntimeError("Last.fm session key not configured")
        base["sk"] = sk

    # Only sign if we have a secret; keep consistent with authspec rules.
    base["api_sig"] = _lastfm_sign(base)

    r = requests.get(
        LASTFM_API_ROOT,
        params={k: _lastfm_param_str(v) for k, v in base.items()},
        timeout=LASTFM_REQUEST_TIMEOUT_SECONDS,
    )
    try:
        js = r.json()
    except Exception:
        js = {}
    if isinstance(js, dict) and js.get("error"):
        raise RuntimeError(str(js.get("message") or "Last.fm API error"))
    return js if isinstance(js, dict) else {}


def _lastfm_load_session_cache() -> None:
    global _LASTFM_SESSION_CACHE_PATH
    if not _LASTFM_SESSION_CACHE_PATH:
        return
    try:
        if os.path.isfile(_LASTFM_SESSION_CACHE_PATH):
            with open(_LASTFM_SESSION_CACHE_PATH, "r", encoding="utf-8") as f:
                js = json.load(f) or {}
            with _LASTFM_SESSION_LOCK:
                _LASTFM_SESSION["sk"] = str(js.get("sk") or "").strip()
                _LASTFM_SESSION["username"] = str(js.get("username") or "").strip()
                _LASTFM_SESSION["ts"] = int(js.get("ts") or 0)
    except Exception:
        pass


def _lastfm_save_session_cache(sk: str, username: str = "") -> None:
    global _LASTFM_SESSION_CACHE_PATH
    if not _LASTFM_SESSION_CACHE_PATH:
        return
    try:
        js = {"sk": (sk or "").strip(), "username": (username or "").strip(), "ts": int(time.time())}
        with open(_LASTFM_SESSION_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(js, f, indent=2)
        with _LASTFM_SESSION_LOCK:
            _LASTFM_SESSION.update(js)
    except Exception:
        pass


def lastfm_auth_start() -> Dict[str, Any]:
    # Desktop auth flow: auth.getToken + user approves in browser.
    # Docs: https://www.last.fm/api/authspec
    js = _lastfm_api_post("auth.getToken", {}, require_auth=False)
    token = ""
    try:
        token = str(((js.get("token") or {}).get("#text") if isinstance(js.get("token"), dict) else js.get("token")) or "").strip()
    except Exception:
        token = str(js.get("token") or "").strip()
    if not token:
        raise RuntimeError("Could not get Last.fm token")
    auth_url = f"https://www.last.fm/api/auth/?api_key={quote((LASTFM_API_KEY or '').strip())}&token={quote(token)}"
    cb = (LASTFM_CALLBACK_URL or "").strip()
    if cb:
        auth_url += f"&cb={quote(cb, safe='')}"
    return {"token": token, "auth_url": auth_url}


def lastfm_auth_finish(token: str) -> Dict[str, Any]:
    token = (token or "").strip()
    if not token:
        raise RuntimeError("Missing token")
    js = _lastfm_api_post("auth.getSession", {"token": token}, require_auth=False)
    sess = js.get("session") if isinstance(js, dict) else None
    if not isinstance(sess, dict):
        raise RuntimeError("Invalid session response")
    sk = str(sess.get("key") or "").strip()
    name = str(sess.get("name") or "").strip()
    if not sk:
        raise RuntimeError("Missing session key")
    _lastfm_save_session_cache(sk, name)
    # Best-effort: pull loved tracks so UI can show ♥ immediately for existing likes.
    _lastfm_async(lastfm_sync_loved_from_remote, name)
    return {"sk": sk, "username": name}



def lastfm_sync_loved_from_remote(username: str = "", max_pages: int = 20, limit: int = 200) -> int:
    # Fetch the user's loved tracks from Last.fm and cache them locally.
    # This allows fast loved lookups without hitting Last.fm for every track.
    user = (username or "").strip() or lastfm_username()
    if not user:
        return 0

    max_pages_i = int(max(1, max_pages))
    limit_i = int(min(200, max(10, limit)))

    page = 1
    seen = 0
    total_pages = None

    while page <= max_pages_i and (total_pages is None or page <= total_pages):
        js = _lastfm_api_get("user.getLovedTracks", {"user": user, "limit": str(limit_i), "page": str(page)}, require_auth=False)
        loved = js.get("lovedtracks") if isinstance(js, dict) else None
        if not isinstance(loved, dict):
            break

        # totalPages lives under @attr in most responses
        if total_pages is None:
            try:
                attr = loved.get("@attr") if isinstance(loved.get("@attr"), dict) else {}
                total_pages = int(attr.get("totalPages") or 0) or None
            except Exception:
                total_pages = None

        tracks_obj = loved.get("track")
        tracks_list: List[dict] = []
        if isinstance(tracks_obj, list):
            tracks_list = tracks_obj
        elif isinstance(tracks_obj, dict):
            tracks_list = [tracks_obj]
        else:
            tracks_list = []

        if not tracks_list:
            break

        with _LASTFM_LOVED_LOCK:
            db = _LASTFM_LOVED.get("tracks") or {}
            for tr in tracks_list:
                try:
                    title = str(tr.get("name") or "").strip()
                    artist_obj = tr.get("artist")
                    artist = ""
                    if isinstance(artist_obj, dict):
                        artist = str(artist_obj.get("name") or artist_obj.get("#text") or "").strip()
                    else:
                        artist = str(artist_obj or "").strip()
                    if not artist or not title:
                        continue
                    # Store album-blank key for broad matching
                    k = _lastfm_track_key(artist, title, "")
                    if k.strip():
                        db[k] = 1
                        seen += 1
                except Exception:
                    continue
            _LASTFM_LOVED["tracks"] = db

        page += 1

    if seen > 0:
        _lastfm_loved_save()
    return seen


def _lastfm_track_key(artist: str, title: str, album: str = "") -> str:
    a = (artist or "").strip().lower()
    t = (title or "").strip().lower()
    b = (album or "").strip().lower()
    return a + "\n" + t + "\n" + b


def _lastfm_loved_load() -> None:
    global _LASTFM_LOVED_DB_PATH
    if not _LASTFM_LOVED_DB_PATH:
        return
    try:
        if os.path.isfile(_LASTFM_LOVED_DB_PATH):
            with open(_LASTFM_LOVED_DB_PATH, "r", encoding="utf-8") as f:
                js = json.load(f) or {}
            if isinstance(js, dict) and isinstance(js.get("tracks"), dict):
                with _LASTFM_LOVED_LOCK:
                    _LASTFM_LOVED["version"] = int(js.get("version") or 1)
                    _LASTFM_LOVED["updated"] = int(js.get("updated") or 0)
                    _LASTFM_LOVED["tracks"] = dict(js.get("tracks") or {})
    except Exception:
        pass


def _lastfm_loved_save() -> None:
    global _LASTFM_LOVED_DB_PATH
    if not _LASTFM_LOVED_DB_PATH:
        return
    try:
        with _LASTFM_LOVED_LOCK:
            js = {"version": int(_LASTFM_LOVED.get("version") or 1), "updated": int(time.time()), "tracks": dict(_LASTFM_LOVED.get("tracks") or {})}
        with open(_LASTFM_LOVED_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(js, f, indent=2)
        with _LASTFM_LOVED_LOCK:
            _LASTFM_LOVED["updated"] = int(js.get("updated") or 0)
    except Exception:
        pass


def lastfm_is_loved(artist: str, title: str, album: str = "") -> bool:
    # Check exact match first, then fallback to album-blank key so remote loved tracks
    # (which often don't include album) still show as loved.
    k = _lastfm_track_key(artist, title, album)
    if not k.strip():
        return False
    k2 = _lastfm_track_key(artist, title, "")
    with _LASTFM_LOVED_LOCK:
        tracks = _LASTFM_LOVED.get("tracks") or {}
        return bool(tracks.get(k) or tracks.get(k2))


def lastfm_remote_is_loved(artist: str, title: str, username: str = "") -> Optional[bool]:
    # Best-effort remote check for whether the user has loved this track.
    # Uses track.getInfo with username; returns True/False on success, or None on failure.
    a = (artist or "").strip()
    t = (title or "").strip()
    if not a or not t:
        return None
    user = (username or "").strip() or lastfm_username()
    if not user:
        return None
    try:
        js = _lastfm_api_get(
            "track.getInfo",
            {"artist": a, "track": t, "username": user, "autocorrect": "1"},
            require_auth=False,
        )
        tr = js.get("track") if isinstance(js, dict) else None
        if not isinstance(tr, dict):
            return None
        val = tr.get("userloved")
        # Last.fm commonly returns "1" / "0" here.
        if val is None:
            return None
        try:
            return str(val).strip() == "1"
        except Exception:
            return None
    except Exception:
        return None


def lastfm_set_loved_local(artist: str, title: str, album: str, loved: bool) -> bool:
    # Store both album-specific and album-blank keys for better matching across sources.
    k = _lastfm_track_key(artist, title, album)
    k2 = _lastfm_track_key(artist, title, "")
    if not k.strip():
        return False
    with _LASTFM_LOVED_LOCK:
        tracks = _LASTFM_LOVED.get("tracks") or {}
        if loved:
            tracks[k] = 1
            tracks[k2] = 1
        else:
            tracks.pop(k, None)
            tracks.pop(k2, None)
        _LASTFM_LOVED["tracks"] = tracks
    _lastfm_loved_save()
    return True


def lastfm_love_track(artist: str, title: str) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return False
    _lastfm_api_post("track.love", {"artist": artist, "track": title}, require_auth=True)
    return True


def lastfm_unlove_track(artist: str, title: str) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return False
    _lastfm_api_post("track.unlove", {"artist": artist, "track": title}, require_auth=True)
    return True


def lastfm_update_now_playing(artist: str, title: str, album: str = "", duration: Optional[int] = None) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    album = (album or "").strip()
    if not artist or not title:
        return False
    params: Dict[str, Any] = {"artist": artist, "track": title}
    if album:
        params["album"] = album
    if duration and int(duration) > 0:
        params["duration"] = str(int(duration))
    _lastfm_api_post("track.updateNowPlaying", params, require_auth=True)
    return True


def lastfm_scrobble(artist: str, title: str, album: str = "", duration: Optional[int] = None, start_ts: Optional[int] = None) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    album = (album or "").strip()
    if not artist or not title:
        return False
    ts = int(start_ts) if start_ts else int(time.time())
    params: Dict[str, Any] = {"artist[0]": artist, "track[0]": title, "timestamp[0]": str(ts)}
    if album:
        params["album[0]"] = album
    if duration and int(duration) > 0:
        params["duration[0]"] = str(int(duration))
    _lastfm_api_post("track.scrobble", params, require_auth=True)
    return True


def _lastfm_async(fn, *args, **kwargs) -> None:
    if not lastfm_enabled():
        return

    def _run():
        try:
            fn(*args, **kwargs)
        except Exception:
            pass

    th = threading.Thread(target=_run, daemon=True)
    th.start()
# =========================
# Real Debrid helpers
# =========================
def rd_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {REAL_DEBRID_API_KEY}",
        "User-Agent": "Debripod/1.0",
    }


def rd_request(method: str, path: str, params=None, data=None) -> Tuple[int, str, dict]:
    url = RD_BASE + path
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=rd_headers(),
            params=params,
            data=data,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        text = resp.text or ""
        js = {}
        if text.strip().startswith("{") or text.strip().startswith("["):
            try:
                js = resp.json()
            except Exception:
                js = {}
        return resp.status_code, text, js
    except requests.RequestException as e:
        return 0, str(e), {}


# =========================
# knaben API client with cache + backoff
# =========================
KNABEN_SESSION = requests.Session()
KNABEN_SESSION.headers.update(
    {
        "User-Agent": "Debripod/1.0",
        "Accept": "application/json",
    }
)
if KNABEN_API_KEY.strip():
    KNABEN_SESSION.headers["x-api-key"] = KNABEN_API_KEY.strip()

KNABEN_LOCK = threading.Lock()
KNABEN_LAST_REQUEST_AT = 0.0

# cache key: (q_lower, page) -> (ts, results, err_string, rate_remaining, rate_reset)
KNABEN_CACHE: Dict[Tuple[str, int], Tuple[float, List[dict], str, str, str]] = {}


def _sleep_to_respect_min_interval() -> None:
    global KNABEN_LAST_REQUEST_AT
    with KNABEN_LOCK:
        now = time.time()
        wait = (KNABEN_LAST_REQUEST_AT + KNABEN_MIN_SECONDS_BETWEEN_REQUESTS) - now
        if wait > 0:
            time.sleep(wait)
        KNABEN_LAST_REQUEST_AT = time.time()



def _knaben_fetch_json(body: dict) -> dict:
    last_err = ""
    for attempt in range(KNABEN_MAX_RETRIES):
        _sleep_to_respect_min_interval()
        try:
            resp = KNABEN_SESSION.post(KNABEN_API_BASE, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = int(retry_after)
                else:
                    delay = min(60, 2 ** attempt)
                time.sleep(delay)
                last_err = f"Knaben API rate limited (429). Retrying after {delay} seconds."
                continue

            if resp.status_code >= 500:
                delay = min(30, 2 ** attempt)
                time.sleep(delay)
                last_err = f"Knaben API server error ({resp.status_code}). Retrying after {delay} seconds."
                continue

            resp.raise_for_status()
            js = resp.json()
            if not isinstance(js, dict):
                raise ValueError("Knaben API returned invalid JSON")
            return js
        except requests.RequestException as e:
            last_err = str(e)
            delay = min(30, 2 ** attempt)
            time.sleep(delay)
        except ValueError as e:
            last_err = str(e) or "Knaben API returned invalid JSON"
            delay = min(30, 2 ** attempt)
            time.sleep(delay)

    raise RuntimeError(last_err or "Failed to fetch from Knaben API")


def make_magnet(infohash: str, title: str) -> str:
    ih = (infohash or "").strip()
    dn = quote((title or "").strip(), safe="")
    if dn:
        return f"magnet:?xt=urn:btih:{ih}&dn={dn}"
    return f"magnet:?xt=urn:btih:{ih}"



def knaben_search(q: str, page: int) -> Tuple[List[dict], str, str, str]:
    """
    Search using Knaben Database API v1 (https://api.knaben.org/v1).
    Kept as knaben_search() to avoid changing the rest of the app.
    """
    q_key = q.strip().lower()
    cache_key = (q_key, page)
    now = time.time()

    cached = KNABEN_CACHE.get(cache_key)
    if cached and (now - cached[0]) <= KNABEN_CACHE_TTL_SECONDS:
        return cached[1], cached[2], cached[3], cached[4]

    offset = max(0, (page - 1) * RESULTS_PER_PAGE)

    body = {
        "search_type": "100%",
        "search_field": "title",
        "query": q,
        "order_by": "seeders",
        "order_direction": "desc",
        "from": offset,
        "size": RESULTS_PER_PAGE,
        "hide_unsafe": True,
        "hide_xxx": False,
    }

    try:
        js = _knaben_fetch_json(body)
    except Exception as e:
        results: List[dict] = []
        err = str(e)
        KNABEN_CACHE[cache_key] = (time.time(), results, err, "", "")
        return results, err, "", ""

    raw_hits = js.get("hits") or []
    results: List[dict] = []

    if isinstance(raw_hits, list):
        for h in raw_hits:
            if not isinstance(h, dict):
                continue

            title = str(h.get("title") or "").strip()
            if not title:
                continue

            magnet = str(h.get("magnetUrl") or "").strip()
            infohash = str(h.get("hash") or "").strip()

            # If we don't have a magnet URL, attempt to build one from the infohash.
            if not magnet:
                if infohash:
                    magnet = make_magnet(infohash, title)
                else:
                    continue

            if not infohash:
                m = re.search(r'btih:([0-9A-Fa-f]{40})', magnet)
                if m:
                    infohash = m.group(1).upper()

            size = h.get("bytes")
            category = str(h.get("category") or "").strip()
            seeders = h.get("seeders")
            peers = h.get("peers")  # Knaben returns peers, not leechers

            details = str(h.get("details") or h.get("link") or "").strip()
            tid = str(h.get("id") or "").strip()

            results.append(
                {
                    "id": tid or infohash or title,
                    "title": title,
                    "infohash": infohash,
                    "magnet": magnet,
                    "size": int(size) if isinstance(size, int) else None,
                    "category": category,
                    "seeders": int(seeders) if isinstance(seeders, int) else None,
                    "leechers": int(peers) if isinstance(peers, int) else None,
                    "verified": False,
                    "href": details or f"{KNABEN_WEB_BASE}/?q={quote(title)}",
                }
            )

    err = ""
    KNABEN_CACHE[cache_key] = (time.time(), results, err, "", "")
    return results, err, "", ""



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


def cancel_task(task_id: str) -> bool:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        if t.state in {"done", "error", "canceled"}:
            return True
        t.cancel_event.set()
        t.state = "canceling"
        t.message = "Cancel requested"
        src = (t.source or "rd").lower()
    # For Soulseek tasks, also abort in the Soulseek client if available
    if src == "soulseek":
        try:
            svc = SOULSEEK_SERVICE
        except Exception:
            svc = None
        if svc:
            try:
                svc.abort_task(task_id)
            except Exception:
                pass
    return True



def pause_task(task_id: str) -> bool:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        if t.state in {"done", "canceled"}:
            return True
        if not t.paused:
            t.paused = True
            t.pause_event.set()
            t.pre_pause_state = t.state or ""
            t.pre_pause_message = t.message or ""
            t.state = "paused"
            t.message = "Paused"
        src = (t.source or "rd").lower()

    if src == "soulseek":
        try:
            svc = SOULSEEK_SERVICE
        except Exception:
            svc = None
        if svc:
            try:
                svc.pause_task(task_id)
            except Exception:
                pass
    return True


def resume_task(task_id: str) -> bool:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        if not t.paused:
            return True
        t.paused = False
        t.pause_event.clear()
        prev_state = (t.pre_pause_state or "").strip()
        prev_msg = (t.pre_pause_message or "").strip()
        if t.state == "paused":
            # Resume to previous non-paused state when possible
            t.state = prev_state if prev_state and prev_state != "paused" else "downloading"
            t.message = prev_msg if prev_msg else "Resumed"
        src = (t.source or "rd").lower()

    if src == "soulseek":
        try:
            svc = SOULSEEK_SERVICE
        except Exception:
            svc = None
        if svc:
            try:
                svc.resume_task(task_id)
            except Exception:
                pass
    return True


def _get_file_control(task_id: str, file_id: str) -> Dict[str, Any]:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return {}
        ctl = t.file_controls.get(file_id) if isinstance(t.file_controls, dict) else None
        return dict(ctl or {})


def _set_file_control(task_id: str, file_id: str, **kwargs) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        if not isinstance(t.file_controls, dict):
            t.file_controls = {}
        cur = t.file_controls.get(file_id) or {}
        if not isinstance(cur, dict):
            cur = {}
        cur.update(kwargs)
        t.file_controls[file_id] = cur


def _update_task_file_entry(task_id: str, which: str, file_id: str, **kwargs) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        lst = getattr(t, which, None)
        if not isinstance(lst, list):
            return
        for f in lst:
            try:
                if str(f.get("file_id") or "") == str(file_id):
                    f.update(kwargs)
                    break
            except Exception:
                continue


def task_file_action(task_id: str, file_id: str, action: str) -> bool:
    action = (action or "").strip().lower()
    if not task_id or not file_id or action not in {"pause", "resume", "cancel", "retry"}:
        return False

    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        src = (t.source or "rd").lower()

    if src == "soulseek":
        # Update display state immediately
        if action == "pause":
            _set_file_control(task_id, file_id, paused=True, canceled=False)
            _update_task_file_entry(task_id, "slsk_files", file_id, paused=True, state="paused")
        elif action == "resume":
            _set_file_control(task_id, file_id, paused=False)
            _update_task_file_entry(task_id, "slsk_files", file_id, paused=False)
        elif action == "cancel":
            _set_file_control(task_id, file_id, canceled=True)
            _update_task_file_entry(task_id, "slsk_files", file_id, canceled=True, state="canceled")
        elif action == "retry":
            _set_file_control(task_id, file_id, paused=False, canceled=False)
            _update_task_file_entry(task_id, "slsk_files", file_id, paused=False, canceled=False, done=0, speed=0.0, error="", state="queued")

        try:
            svc = SOULSEEK_SERVICE
        except Exception:
            svc = None
        if svc:
            try:
                if action == "pause":
                    svc.pause_file(task_id, file_id)
                elif action == "resume":
                    svc.resume_file(task_id, file_id)
                elif action == "cancel":
                    svc.cancel_file(task_id, file_id)
                elif action == "retry":
                    svc.retry_file(task_id, file_id)
            except Exception:
                pass
        return True

    # Local downloading style tasks (Real Debrid and YouTube) are handled by our own worker via file_controls
    if action == "pause":
        _set_file_control(task_id, file_id, paused=True, canceled=False)
        _update_task_file_entry(task_id, "rd_files", file_id, paused=True, state="paused")
        return True
    if action == "resume":
        _set_file_control(task_id, file_id, paused=False)
        # state will be updated by worker; clear paused flag for display
        _update_task_file_entry(task_id, "rd_files", file_id, paused=False)
        return True
    if action == "cancel":
        _set_file_control(task_id, file_id, canceled=True)
        _update_task_file_entry(task_id, "rd_files", file_id, canceled=True, state="canceled")
        return True
    if action == "retry":
        _set_file_control(task_id, file_id, paused=False, canceled=False)
        _update_task_file_entry(task_id, "rd_files", file_id, paused=False, canceled=False, done=0, speed=0.0, error="", state="queued")
        # If the main worker already finished, spin up a lightweight worker to retry queued files
        with TASKS_LOCK:
            t = TASKS.get(task_id)
            st = (t.state or "").lower() if t else ""
            src2 = (t.source or "rd").lower() if t else "rd"
        if st in {"done", "error", "canceled"}:
            target = youtube_download_remaining_worker if src2 == "youtube" else rd_download_remaining_worker
            th = threading.Thread(target=target, args=(task_id,), daemon=True)
            th.start()
        return True

    return False




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


# =========================
# App icons (favicon / homescreen)
# =========================
ICON_VERSION = "57"

# Embedded PNG bytes (base64). This avoids runtime SVG rendering issues.
ICON_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAlgAAAJYCAYAAAC+ZpjcAAAACXBIWXMAAXEYAAFxGAHswbAIAAAAGXRFWHRTb2Z0d2FyZQB3d3cuaW5rc2NhcGUub3Jnm+48GgAAIABJREFUeJzs3XucnHV99//357pmdpOQ4x5yICS7m4OHWzxgUdF6rLditdT2VrFqFRBrSpFkN4BYtU33tkURyAkVQ1XE3tUWtbYefneLt7W2tp5Qa8VDTcjuJgSS3dkcIcnuznV9fn8EKRRIdjfXNd+5Zl7Px8M/VOR6GWZn3jtzzXWZuwsAAADZiUIHAAAANBoGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSsFDoAaAbWr1LPgeH2tOyzVC3NkHymJEUTPjuJo3LoPjSeOEkn0rLdf+Lf2TGVqsejCTs6sGDhqG9QNWwd0PjM3UM3AIV2dr9ajhzav9rcupVWu2XWZfJul5a4rN2kDknzQ3cCD3PQpYrJR022R6YhdxtS6kPeEg3MmdO2464NGg8dCRQZAwuYgp6+g/NVHX+Ox9HTZHqqUp3t5k80Ge9CoWG4fMLc/lOR7pLrx1Ga/shmlb9z9wcWHArdBhQFAws4iVVX7l82kfiLTOlzJT1P0pMl49xFNCFP5fZTRf5vSuxb5ZnRN7Zf13ZP6CqgXjGwgIexfpWWV4afE8fxK13+UjedI5eF7gLqkmvAIn3NFX+lnIz+v+1bV42FTgLqBQMLTW/Z+ntmlnz2+e7V10n2SsnPCN0EFI/dL/lXIpU+64cO3jFwa/fx0EVASAwsNCW7UHHXopGXK7Y3SvYqyWeHbgIahcsOR5Z+WVX/zGDHwq/6BqWhm4BaY2ChqXT3HV0iP/q7Lr3dpK7QPUDDc90bmf2lSuO37LxhyVDoHKBWGFhoCl3rRl8aSVe4pa/gJHUgBE9M0d+7+9bBLR1fD10D5I2BhYZ17hqVKzOHf1Nu62X2rNA9AB7yH3J91A7f/384VwuNioGFhrN67Y7WiWjBpXJ/p0xnhu4B8Njc/Z5I9sEz2jo+wYVN0WgYWGgY565ReWTm6OvN/Y9k6gndA2By3P0eSZta/NAtXOoBjYKBhcIzk/WsHXldYvanJnWH7gEwbTul9D2Dmxd+PnQIcLoYWCi07r7KMy3VDW56fugWABlx/55ZtH5gc/t3QqcA08XAQiGt6B1elJpdK9eb+FYg0Ig8lexT5bT6nu1bF4+ErgGmioGFwunuHX6NFN8keUfoFgA5Mx1QqvcMbe34uLt4wUJhMLBQGD19e7vdSx+W9LLQLQBqzf45bkkvu/uDndtDlwCTwUcrqHtmsp7eyhpX+d/FuAKalL8wGY++u6K38nuhS4DJ4B0s1LXVa/d2Vi3e5ma/EboFQL2I7rCJ5G0DH+7cG7oEeDwMLNSt7itGft3j6BaTLwrdAqC+uNneOEnetnPrwjtCtwCPhYGFumMm61pXuUry9/ENQQCPy+SR2w0DC9r/yDcoDZ0DPBwDC3Vl2frDbXE6cZvk54duAVAM5vb36UTpoqGPzDsQugX4JQYW6saK3uGnJYo+x9XYAUzDzrScvHbX9YvuCh0CSHyLEHVixTv2vyxR/I+MKwDTtCKaKP1z97qRV4YOASQGFupAz7qRS5JS8rcmnxu6BUCR+WyZPt/TW1kTugRgYCEYM1lP3+i1brbNZOXQPQAagcUu3dTdO/o+M1noGjQvzsFCENavqPtA5SMuvTV0C4DGZKaPDc7veAffMEQIDCzUnF2ouGvpyC1ye3PoFgAN76+HFnRc4htUDR2C5sLAQk2d3a+W+w+O/KXcXh26BUBzMNMXzpjf8ea7Nmg8dAuaB+dgoWbsQsUPHKjcxrgCUEvu+u37D4x82vpVCt2C5sHAQk1Yv6LuM0c+4dJrQrcAaEb2m90HRz5m/bzuoTZ4oCF3ZrKuAyM3uewNoVsANC93e2PXgcpH+XYhaoGBhdx1947+mWS/F7oDACRd3L1u/5+EjkDj4yR35Kq7b+Stcvto6A4AeLjI9Y6dWzpuCd2BxsXAQm56rhg+32P7gmScWAqgrrh8Iq7Gv7XzQ21fDd2CxsTAQi5O3Lg5/rrJ54RuAYDH4tIhRdGLhza2/SR0CxoP52Ahc11/cGhB6tFnGVcA6plJ85Smf3vWO460h25B42FgIVPWrygqV2+TqSd0CwCcikld5dI4l29A5nhAIVPdB/ZvcPNXhO4AgMly+au6Doy8O3QHGgvnYCEz3VeM/LpK9rdyrjEDoGg89TT6jaGt7f8vdAkaAwMLmVi9dm/neFz+vrkvDt0CANPhsn2xknN3bl64L3QLio+PCJGJqkq3MK4AFJnJF6Wyj4TuQGNgYOG09fRW1nikV4XuAIDTZxd0945cGroCxcdHhDgt3Vfv61G19EO5zwrdUo/cbG/kfrfMh9yj3eZpJbVo1JQcc48Phu5D4zNL5rvimZGn7W5Rh1m6TG5dqWyVyReF7qtPdn9UGj9n5w1LhkKXoLi4wjamzUzWvTb+iBvj6kGjlurbMvuWp7pzonX8P/bcsKQSOgp4PKuu3rdwYrz01Mh0rqTzXP5cSW2hu8Lz2Wm15UOSLghdguLiHSxM24re4bekij4WuiMkk37g8i+nkf397nkdP/ANSkM3AdNl/YpWHBn9lWTCX2HSb7jpnNBNIZnpooFNHZ8J3YFiYmBhWlb0Di9KFf1ITfjbrks7ItltXq7ePnj9ooHQPUBeutYPr4jcXu9uF0laEbqn1lw2Ui2NP513ojEdDCxMS3ffyMfl9ubQHbXjiZl9UVXdPPihjm+4ix8cNA0zWdfayosV+R/IdYFkTfMFKZM+PrC547LQHSgeBhambPn6yrlR6t9shidZl41FSj/h5XQz71YB0vJ3Dq+MJqzP3S42qSV0T/48iWI/b+eNC38UugTFwsDClJw4sb3ydTc9L3RLvjwx2SfjOLp2x41tu0PXAPVmZe+B5YmS90r+Zsni0D25cvvG4Jb2l4XOQLEwsDAlPb0jr3fZX4TuyJO5fT2Kq1fdvXHRj0O3APWu56rRJ3lV10t+fuiWXLm9fnBL+xdCZ6A4GFiYtLP71XLkQOUuk7pDt+TBZcOR0isHNnf+degWoGi6eytvdNn1Ju8M3ZIL191DbR1P9Q2qhk5BMTT8OTTIztEDlYsadVzJdHtSbXk64wqYnsHNHZ+ulsafbtLnQ7fkwrSy++DI74bOQHHwDhYmZfXaHa3jNu9nZnZW6JYsuXTIpHWDmzs+HboFaBQreoffkijeZPI5oVuy5NLQnAUdT7lrg8ZDt6D+8Q4WJmXC5r2tAcfVL6KSvYBxBWRr5+aFnyq1pOfJ/aehW7JkUtfRA5WLQnegGBhYOKWz+9Ui2dWhO7Jk8r89NuHnDdzQ/vPQLUAjuvuDndtnzLAXSP6l0C1ZSuTvsn5uM4dTY2DhlI4cGL1QpjNDd2TFpA8NLuj8neEPd94fugVoZD+/ruPI0JbO10YWvS90S1ZMtqx7f+W1oTtQ/1jhOCWTrwvdkAmTm+tdA5s7NoVOAZrFibsetL2vu7dyXNKfhe7JSJ+kvwodgfrGO1g4qe4rRn9N0tNDd5w+T6NUVzCugDAGN3dcb2brZMW/zZSbzum5ovLi0B2obwwsnJRFWhu64bSZ3GTrdm7puCV0CtDMBja132yy3tAdmTA1xjv7yA2XacDjWnXl/mXVJPlF0W+DYdI1vHMF1I+edaPvdPM/Dd1xejxJomjV7o3te0KXoD7xDhYeV5rq4sKPK9MmxhVQXwa2tH/QpA+F7jg9FsdJenHoCtQvBhYek12oOEmTS0J3nA6T/+3g/I4/DN0B4NEG7+242lJ9JXTH6XCzi62f11E8Nh4YeExdi0ZeXugLi7r/9IEJvdU3KA2dAuDR/HYlJUUXufSL0C3TZVJXz8j+l4buQH1iYOGxlewNoROmy6VDcatex3WugPq2fWvbYTN7nWSF/Vn1cvLG0A2oTwwsPErPJYMz3O2VoTumKzKtvfuDndtDdwA4tcFN7T8zT68M3TFdqUe/2XPJ4IzQHag/DCw82vz5rzD53NAZ02K6fWBTx2dCZwCYvIEtnbea6QuhO6bD5HNszryXhe5A/WFg4VHcq68L3TA9Vikn1b7QFQCmbjyeuNxlI6E7psOjKrfOwaMwsPAIq9fuaJXs10N3TIcp7du+dXEhn6CBZrfnhiUVSdeE7piOVNFvnN2vltAdqC8MLDzCuBa8QPLZoTumylxfG9jc+dehOwBM39Dm9v8j2b+E7pgqk895oFJ5XugO1BcGFh7BIn956Iap8yRpSa4OXQHg9EVxsl7yJHTHVFlsnIeFR2Bg4b/x80MXTJXJPrnr+kV3he4AcPp23rjwR5L9ZeiOqUrlrwjdgPrCwMJDVl25f5lkTw7dMRUuG4vj6NrQHQCyY1b9U5dPhO6YEtPZ3X1Hl4TOQP1gYOEh1Yn0haEbpsosvXXHjW27Q3cAyM7ApsWDkexToTumxGWWHn1R6AzUDwYWHmKxfjV0w9R44uabQ1cAyF418hslL9StrjxyTnTHQxhYeIi7Pzd0w1SY7O+GNi7cGboDQPZ2b+zcIenLoTumxI2BhYcwsCBJ6uk7OF9Soc6/UqqbQycAyI97VLCfcT975bsOzAtdgfrAwIIkyZLxZ0tWmMeDSzsGb+r459AdAPKza2v7P8o1ELpj8iyqHk2fFboC9aEwL6jIl1v8jNANUxG5fdJdHroDQH5O/Ix7oU52t8ifHroB9YGBBUmSmz81dMNUpHHyudANAPLnsRfq5u1mfnboBtQHBhYeVJwnBZN+wMntQHN48Gf9R6E7JsvdCvNcinwxsKDVa3e0uvSE0B2T5fJifbMIwGkxRV8K3TBZLnvSuWtUDt2B8BhY0FjrnNUmK8wTQlyK/iF0A4AainVH6ITJMnnr/pmVFaE7EB4DC4qqLV2hG6ZgdOec9u+HjgBQO4O7274n6WDojsly957QDQiPgQXJq4V5MjD3b/kGFerqzgBOj9+uxNy+Hbpj0syK9EsrcsLAgiRbHrpgstzsW6EbAAQQpcX52WdgQQwsSDJTcZ4MEuPjQaAJpUn0vdANk8ZHhBADC5LcfWnohskq28SPQzcAqL0oSe8K3TBpBXpORX4YWJBkHaELJsPN9m7fungkdAeA2hv4cOdelxXi5z+VtYduQHil0AEIz6V2Cx0xCZH73aEb6omZbNUVaqnGgzNLSUe5mhyLk6g495PEo8Wpp6V4ZlKNKxOlpPvY9q0aC91UT0zpTsk6Q3ecipkYWGBgNbtz16hsszS3EHf1Mx8KnRCS9fdHK46tnaPjx+dNeDS3p680q1q1SMlcVTUuxbHi0JE4PbFO/LNM5qqq/Vqx3tNqUj3aUiof8rId3vmBBYddhfhpzYfZkFzPCZ1xaj7fLlTstysJXYJwGFhNbv/M4TZ5VIQ3sOQe7Q7dEMKTLq3MOT6r3LGsfHl7WvWS1KpYkldDlyFvXrUoVnl2MqHZmvCly9ZXqt0TyejsNBq568Od94fuq7XIbSgtxL60aNXivW0SpzQ0MwZWk6u2aHY0Hrpicsx8NHRDLT3pmsqcY8eqy6IzWuaaEsVVPv1rdnE1KsmiRQ/EWtS1fv8RHY/vHfrIvAOhu2oldR9VIX4dlCZabbYkBlYTY2A1OUtLrSrIdTtTt0rohlpYfPW+M1rG1RN7eXakltA5qFNRVXNUSp7YtX7/kbF4YnDv9YseCN2Ut8jSSlqQ72ZFEzE/vE2OgdXkoiRp8YL8ShgrPhy6IU/Wr6j74MHlM720SG7F+IeC4KKq5sxMS2f39O3dNzh/8a5GvtOBe8shWVE+G09bQxcgrGL8KoDcmEWF+S3LfaIgH2ZO3bL198zsOXDgbCXpYqWMK0xRaqakZXHP6PBTl665b1bonLx4WpzngGpUnOdW5IOB1eSSNC3Mk4CnRTlbbGqWrT/cVq7OfKqn3rAvjKgNV2lma6udvWz9PW2hW/IRFeayFTbBO1jNjoHV5KLUCvPNfjNvuK88r167t7OUTqx2cf0qZMPVEpXSmatX9A4vCt2StSI9B0QWcQpOk+NJHQiku6+ypKqWlXwkiMylZp6Werr7KktCpwDNioEFBLD0qvs6LEmKc5NtFJIlSdfqtXvr/srnQCNiYAE1tnrt/rkt1ZaVUjl0ChpeWdWovGL12v1zQ5cAzYaBBdTQuWu+Xx63dDUfC6JmUrNxS1efu4ZFD9QSAwuoocqs7lWRR7zQoaYij8qVWfetCt0BNBMGFlAjqy7bt9ASmxe6A83JktZ5SzgfC6gZBhZQA9av0kRLvCx0B5pbi5WWWz938ABqgYEF1EDPyMGlfDSI0CKPyisOHDgzdAfQDBhYQM6sXyUrJQtDdwCS5OnYYt7FAvLHwAJytmp0/+K0QFfMR2NztURLR/cvDt0BNDoGFpCziTjl3SvUlVKcLjQTlwoBcsTAAnLU0zc435KoMDfURnOwJGpZ8fYDXHwUyBEDC8hRksxqD90APJaJ1omO0A1AI2NgATmK4ojrXqEu8dgE8sXAAnKybP09M/l4EPXKkqilp39wRugOoFExsICctMblOaEbgJOJ987kPCwgJwwsICept84M3QCcTBqnPEaBnDCwgJz4WMKLF+pbqcxHhEBOGFhATqwlaQ3dAJxUmjKwgJwwsICcJNWI25GgrqVxxB0GgJwwsICclMz4+UJdS51bOAF54QUAyEmaVnnxQl2LeYwCuWFgAbkphw4AToHHKJAXBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkjIEFAACQMQYWAABAxhhYAAAAGWNgAQAAZIyBBQAAkDEGFgAAQMYYWAAAABljYAEAAGSMgQUAAJAxBhYAAEDGGFgAAAAZY2ABAABkrBQ6AED9sTh9Xer22tAdRRCZf86T6LOhOwDUF97BAgAAyBgDCwAAIGMMLAAAgIwxsAAAADLGwAIAAMgYAwsAACBjDCwAAICMMbAAAAAyxsACAADIGAMLAAAgYwwsAACAjDGwAAAAMsbAAgAAyBgDCwAAIGMMLAAAgIwxsAAAADLGwAIAAMgYAwsAACBjDCwAAICMMbAAAAAyxsACAADIGAMLAAAgYwwsAACAjDGwAAAAMsbAAgAAyBgDCwAAIGMMLAAAgIwxsAAAADLGwAIAAMgYAwsAACBjDCwAAICMMbAAAAAyxsACAADIGAMLAAAgYwwsAACAjDGwAAAAMlYKHQCg/piin0SWhs4oBFP0Ew8dAaDuMLAAPEqa6KdS9NPQHUXAuALwWPiIEAAAIGMMLAAAgIwxsAAAADLGwAIAAMgYAwsAACBjDCwAAICMMbAAAAAyxsACAADIGAMLAAAgYwwsAACAjDGwAAAAMsbAAgAAyBgDCwAAIGMMLAAAgIwxsAAAADLGwAIAAMgYAwsAACBjDCwAAICMMbAAAAAyxsACAADIGAMLAAAgYwwsAACAjDGwAAAAMsbAAgAAyBgDCwAAIGMMLAAAgIwxsAAAADLGwAIAAMgYAwsAACBjDCwAAICMMbAAAAAyxsACAADIGAMLAAAgYwwsAACAjDGwAAAAMsbAAgAAyBgDCwAAIGMMLAAAgIwxsIDcTIQOAE6BxyiQFwYWkJMoKiWhG4CTSXiMArlhYAE5qbqnoRuAk4nMGVhAThhYQE7iUloN3QCcTJSkDCwgJwwsICc+Ho+FbgBOKoqOh04AGhUDC8iJtcbHQjcAJ1WdYGABOWFgATmJbIyBhboWJRGPUSAnDCwgJ2PJxJHQDcDJJIuPHQ7dADQqBhaQk90bzzrmcToeugN4LB6n4wMbuvmIEMgJAwvIUZqkh0I3AI/FrXwwdAPQyBhYQI7Ks8qV0A3AY2mpJjw2gRwxsIAc3f2BBYf4mBD1xuN0fMdNbZwjCOSIgQXkrJxEw6EbgIerJmPD7vLQHUAjY2ABOdvR3rY3ibglCepDFHmyp33p3tAdQKNjYAE58w2qlqrjvIuFOjG+zzeI2zgBOWNgATUw0LlkT2rpROgONLfU0omdC/7z3tAdQDNgYAE14BtUbfHqrtAdaG7VcuuQb3gx714BNcDAAmpk+9bFIx4718VCGC1+cM8Nc7g0A1AjDCyghjqODu7gsg2otdTSifYj7XeH7gCaCQMLqKE7t/3KRDmJdihyviKP2ogmvMWj7XduE+cAAjXEwAJqbPvWtsPjpfG7xesdcjeh46nv3L61jZs6AzXGwAIC2HPDkorH8VDoDjSyCWlGNHjf1sUjoUuAZsTAAgIZ3NRxX0njd/NxITIXuVtkAwMf7OSCokAgDCwgoO1bF49Uo2PbTeNp6BY0hijyJB0v/WLn5oX7QrcAzYyBBQS2e+NZ+ydK1R9Xo+rR0C0oNlP12PFj4z8Z+si8A6FbgGbHwALqwO6NZx27Z8HCuxSP7+UjQ0xZ5G4t0X0D7Qt/vGfbEoY6UAdKoQMAnOAblEqLBxdfvW+kNSl3R1XNCd2E+peWdKT6wPgAwwqoLwwsoM7svX7RA5J+8qRrKnOOj9tZlti80E2oP2lJR3Q8vndoKx8HAvWIgQXUqZ9f13FE0s/Ovnxk9v1R2pmW4/a4GjXOz6wl8+XRYildlEbxYlO6UBbNszSdK7P57j7bIp0hSUq97KYZkmSu44psQpI81QMW6UjqOmiyw5IfdtNwlPheKdonS/fK44MB/19mKvG0GpdKlTPGJyp3be28P3QPgMfXOE/WQIO668Od90u636TBFWsOzLXZPnfCNTeWn+FVq/vzKN0UxZ72VKPoCSZfIXmPyVe5NFd24suTpuTBvziRmyS5ZNJDZ6PZI/5+M+Q+48H/fI67Fp/4r0/8xeaSR5L04N/bksMu2yHZgMt2ltL0F4lFA+aq+29umjxNSvZA2XTYJnRo8EMdR9zFOXpAATCwgIJwybVtwSFJD90wevXaHa3prPYZ0dGxliSaE1WTY3E5ngj6c12K4tKE2zOT1J8VmZ0jt2cksWbZw/aMn1hMNRk4Ls2W9AzJn2FyJbEkTx9II/93pf7vcWTfK5v/oJom1Vr0PJ6JpFwtxTOTY+mRdNas1vHo6Ojx7VtXjT3iL9oaKA7AlDGwgAJ78AX4YS/CZwTpWH5F5UxF0fmRVV+WJNFLZJptZifeajFJ9feuyyxze57Mnpe6NOZ2RNI/pRbfoarfseumjnvDpf3yn+GCcAkAThsDC8C0nPXuPe12tPX8kut34lgvcqWRFD3i47wCmSNFF0TuF1istHtd5buppV+IjkVfGNzWcV/oOADFw8ACMGmr1+5onYjm/oYUXVxW6wtdiryYg+pxuRTJdF6k6Dybqff39Fb+ydP0ttntC7981waNh+4DUAwMLACn1LV+eIWl8aWKFrxR8g5JdfeZXx78xMWYf01R9Gv3HxitdPfq00qqHxu8adFA6DYA9Y2BBeBxda8dOUcluyzy6EKXx6F7wvIOSWstjt/RvW7kDiulNw7cuOjboasA1CcGFoBH6endf74reZciO1dpc7xbNVknPkK0V3gSv6K7t/KdSOl1Ozcv/GroLgD1hYEF4CHdfcPPlUd/LOn5RT1bvcaekyr6m+7eke/JStcPblrwf0MHAagPDCwAWrF2+OlpFL1fil4QuqWY7Fny5Pbu3so/xUny7rtvWvTj0EUAwmJgAU1s2frDbXFafZfF0dvlavJzrDLx4jSOv9m9vvLXpTh5747rFw2HDgIQRt3fZgNA9qxf0fK+4cvidPwuKb3MGVeZcSlSqjdUx+MfdvVW1lg/z7NAM+IHH2gyy9cOr+w6UPlK5NEHJc0J3dOwTHNNuqHrwPBXe64YfVLoHAC1xcACmoRdqLhr7eg1URR9V9LzQ/c0j+jZHuub3b2Vq+1C3ikEmgUDC2gCq9+9t3P50srnLfL3SmoJ3dN8vFXSH3edWflS95rKktA1APLHwAIaXM/6yosmjpb+zVwvDd0CvUAz7d9W9A6/LHQIgHwxsIAGZRcq7u4debdSfVHS4tA9+CXvcIs+3927/4PnrlE5dA2AfDCwgAa06up9C7uXVL4g2R86P+d1x10mpZdVZla+yEeGQGPiiRdoMCvWj7ygOlH6jpteEroFp/R8zdC/dvcNPzd0CIBsMbCABtK9dvh/pW5/8+CNiVEEpk55/KWedfteHToFQHYYWECDWN47/AcWR5+Ua0boFkyVtyqKb1veN3px6BIA2WBgAQVn/Yq6eke2RIquO3FuD4rIXXEs39rdt3996BYAp4+BBRSYXah4+YHKR0z21tAtOH3uMnna3923/3pusQMUGz/AQEGd3a+WriWjt5n0ptAtyJinv991cPTPuYwDUFwMLKCA7ELFRw6O3iJzToxuVO4XjswavYV3soBi4gcXKBgzWdeZI1vN/TWhW5C7Y2WcAAAgAElEQVQvc39t14HKDaE7AEwdAwsoEDNZ17qRrZK9JXQLaub3OPEdKB4GFlAgy9eOvEuyi0N3oLZM6Z909Y4yqoECYWABBdG1duS1UWR/GLoDtecui8y3ruit/GboFgCTw8ACCmBl78jzLbJtXOeqebkrdulj3FYHKAYGFlDnVvQOL0pkn5TUEroFYbk00zz66xXvONgVugXAyTGwgDpmFypOFX1c0qLQLagPLi1IS8mnl62/Z2boFgCPj4EF1LHlSyrvlfSi0B2oN/60WDO2hK4A8PgYWECdWrlu9KWRia/n47GlesPytZU3hM4A8NgYWEAdWnX1voWJ+TbnZxQnEUe+afna4ZWhOwA8Gk/eQJ2xfkXJePwxcd4VTsFlZ0RRtM36VQrdAuCRGFhAnVl+YPSdbnpJ6A4UxnOW7x/lo2SgzjCwgDqy8h2VJ5h0VegOFIuZX9NzxeiTQncA+C8MLKBOWL+iJNaHJW8N3YLCafE4/Yj185wO1As+twfqxLKDw2tk0XmhO8KwMTP/aer6iSz6T0uqu6LSjHsije0fU+v+dN7c43s26KgkLe3XrOjQ4RmtGmtL1dqWpseXpVFpuXn6RHM9RdL/UFNelNWetfxA5VKp489DlwBgYAF1YdXV+xZGHv9R6I5aMamayr5jkX3VbOJftf/Yvw/c2n18Mv/bE0Nr7lFJ+0/8J3O/+/D/vueSwRk+f9Y58uj5JnuZ5M/yJnmuM2nDE6+67wv/ecOSSugWoNk1xZMOUO+q49EfyzQndEeeTErl+kZq9jmfWfrS0PvnHcjjOA8OtW89+K/rl60/3BZp4gJL/bUmvbDBL30x73hSeq+k3tAhQLNjYAGBrVg7/HSLojd76JCcmHQg9fQTUdJy684PzR+q9fF3b5y7X9Jtkm7r6TvY7T5+SaToEpcW1LqlFiLZxavW7fvYji2L7grdAjQzBhYQWBpF71cDvqti0n2JpxuTtoWf+uX5U6ENbJo/KGnD0n5dFx8cvijyaL2kxYGzMuWuuGrx+yVdELoFaGYN96QOFEn3lZWXSHpB6I6MHXL391aj40/ftWXhR+tlXD3cng06umvTwpsnjk083S36I0lHQjdl7MUrekdeGDoCaGYMLCCkxBvmxHYzueSfai1NPGNoS+eW3RvPOha66VT2bFtydGhT2+byrOrTXfo/J/4/NAZX9N7QDUAzY2ABgfT07j9fsmeF7sjIkJm/anBz5+VF/Abb9msXjwxt7rhM0m/KtSt0TxZc/tyV60ZfGroDaFYMLCAQV/Ku0A2ZcH0xnhH/6s6Nnf8SOuV0DWzq+CeLSr8qpV8K3ZKF1HRN6AagWTGwgAC6+4afK9m5oTtOj42lSq8Z2trxu3d/YMGh0DVZGdg0/+Dg5oVvTD1aK9lY6J7T4fLnrlh/+NmhO4BmxMACQnBdETrhNO119/N3bV74EffGOW/p4XZtabs1VvnXJSvcR54Pl6YTRX+sAYXEwAJqrGv98ApT9KrQHdNl0s9KE9GvDW3p+H7olrzdvXnu92JPX17k87LM/ILuK/b1hO4Amg0DC6i1JH5bYa8mbvrRxKyxX9/x4bbdoVNq5e4tndsjS39Nsv8I3TId7ooVR28N3QE0m2I+yQMFtXrtjtZIemPojmkx/ShujV91z7VLR0On1NrOzQv3mcWvMtlPQrdMi9ubzu5vxhtgA+EwsIAaGte8C9y8PXTHlJl+Xp059upGOpl9qgY2zT/ox/y3C/lxoanzgYPDrwydATQTBhZQQxbZRaEbpmFvaTz6X834ztV/N7it475Y/ltFPPHdPS7iYw8oLAYWUCPdaypLTCrY7UtsTKbXN9M5V6dy95bO7XFUel3RLuFg5i9ZdfW+haE7gGbBwAJqJJ2Z/nbRTm53+XsGN3X8IHRHvbl747w709QLdfkDd8UTE/GrQ3cAzaJQT/ZAkUUe/Xbohilx+7uhzR3bQmfUq11bOz4j01+F7pgKk/5X6AagWTCwgBpYdtnoUjMV6YraQ/HM6PLQEfVuRovWSxoK3TFZJj2v5/KRxaE7gGbAwAJqIJ5h5xfl40EzuWJd0czfGJysn1/XcSSK/DKzYlzN3qUobYleFroDaAaFeMIHCi9NCvOi5u5/MXhjx9dDdxTFzo2d/5JKnw7dMVnmennoBqAZMLCAnJ24wKO9OHTHJB0pldP+0BFF0zKz+kdyHQ7dMTn+0nPXqBy6Amh0DCwgZ0cPjJwn0+zQHZPh7tftuH7RcOiOotl+7eKRNI5uCN0xSXMqs4efFToCaHQMLCBnqfT80A2TtLd6vPrnoSOKynX0oybdF7pjMrwaF+UxCRRWKXQA0OhM9pwinAGdenrjnm1LjobusAsV95x1+FdSH3+hUp2jSE+Qa7GkMx78Sx4w6T53bVekH8be8o2dC+Z+3zcoDdm9e+NZx7r7RrbI7QMhOybDTOeFbgAaHQMLyJFdqLjrTNX9xzEmHUjaFn4qZMPqtfvPmrDq27uXRK9PU535y7DH+H7efJfmy/RkuX4z0bi6D1T2dPWmf52Oxbfsvrl9T43THzIxv/PWlgOVd7rUFqphcvw8u1Cx364kdAnQqPiIEMhRz5nDT5E0J3THqaSefmLPBgV59+qJV93X0d03snUiSn8ki/rcHhxXU+DSUlO0Pm71/+jqG9l81rv3BLmh9p4NOuqe3hbi2FM0Z+WSfU8OHQE0MgYWkKMkis8J3XAqZnJLPcgo6Fo3cuF4tfwDuV0iqSWDv2WLuV1aPtr6g661I6/N4O83ZRa1fMIU9uPKyZiw0jNCNwCNjIEF5MhSe0rohlNK9U+DNy0aqOUhz12jcve6kQ+Z2cddWpD139+lNovs1q7ekS21viTBwKb5gy59s5bHnKb6f2wCBcbAAnKVnh264FTSyD5by+MtXXPfrMrM0b+S2UV5H8tkb63MHP3M0jX3zcr7WA+XevS5Wh5vOkxe949NoMgYWECOrM7fJTCpqhmlL9fqeOeuUbk8s+UvJK/h1cT9/JYZ5b86ccHX2kjPOPZFszo/gdzr+7EJFB0DC8jJE6+6r6Puv03m9t2h9887UKvDVWaMbKrtuDrBTS85cnDkg7U63j3XLh111521Ot60mDq7/vBQ5h/PAjiBgQXk5PhEuSt0w6l45F+t1bGW9468vhYfCz4ec7u0u3f4NbU6nqdWsz/b6YqOj9f9YxQoKgYWkBPztO5fvMztX2pxnGXrD7fFHl1Xi2OdjCnaVKtLOJTjpO5PdDe35aEbgEbFwAJy4nGpzl+8bEyHjvyoFkeKfexP3DzItakezqUFpaOt76nFscZs/AeSxmtxrOlK5N2hG4BGxcACcmKenhW64eT8ZwO3dh/P+yjLLhtdKrc35X2cKbho1eX7l+V9kN0bzzom2c/zPs7pMMV1/hgFiouBBeTEzTpCN5yMS3fV4jhxS7JG2VxENCstE+Xq22pxIDOvyZ/xtNXBu4pAo2JgATmJUq/vbxBa9J+5H6JfkVl0Yd7HmarIo9+xCxXnfRy36Bd5H+N0uBhYQF4YWEBO3KyuX7wsqe7K+xg9hw6f69LSvI8zVW46c+XyQ7nfKsbTJPc/49MR1ftlRIACY2ABufH5oQtOJirNuCfvY6Q+/sK8jzFd1SR5Ud7HiOJ0d97HOB3uDCwgLwwsIDdW09uzTFWi45XcD+LpM3M/xnS5534j7qgajeZ9jNM0I3QA0KgYWEBe3OvpxO5Ha23N/QrupmhV3seYLpNW532MsTPG9+d9jNPUGjoAaFQMLCAnZiqHbjiZdOxI7pdokLS4BseYHs+/zUejY3kf43SY1dW3O4GGwsAC8lLnL1733HNW7hfBdOmMvI8xXW6anfcx7j2wZCzvY5wm3sECcsLAAoC8PEUWOgFAGAwsIC9e37dJOeuse3J/h82kB/I+xnSZ6/68j3FmfV1g9bHU+ztsQGExsICceJ3fh06aO7MGB9lbg2NMj+XfNvvIfXX9TVKv818CgCJjYAG5sYnQBSdj1eML8j6GK92R9zGmy6XteR+jerxc79eZ4h0sICcMLCA3fjR0wcnEUZz/vRIt+kHux5imNLLc25JyWtdX85dUi2+SAk2JgQXkxZT7daZOhys5K+9jxN7yjbyPMV2WpP+c9zE8tWV5H+N0mFTvF0IFCouBBeTEvL5fvNKotDzvY+xcMPf7cuV+S55p2L2rreOHeR/EIsv9z/h0uKzeL4QKFBYDC8hJavX94mVp+sS8j+EblLqlt+d9nKlyT2/3DUprcKjc/4xPj9f1LwFAkTGwgJyY1/eLl0lPqcVx0rH4FtXVNyptzNPolpocyu1/1OQ40xbV9S8BQJExsICceBTtDt1wcvbknksGc7/Z7+6b2/e4+V/kfZzJ80/uuqnj3ryPsnTNfbMkf1Lexzkd7sme0A1Ao2JgATmxpLordMPJeavPn3VOTQ41o6Xf3IK/o2fS/uqssffX4litZ5R+RXV+odHYbCB0A9CoGFhATlxRnQ8sSYp+tRZHGXr/vAOpp1fV4lgn45723nPt0poMvSStzZ/t6XDzAjxGgWJiYAE5Sc4YGwzdcCrm9vJaHWtoa+fnXP6JWh3vUVy3DG5Z+IVaHc6UvKxWx5qudEbLUOgGoFExsICc3HPt0tF6+Fjs5PxZy9YfrtnVxnfd27le7l+u1fEe4v4PQ20d19TqcE+86r4Os+hXanW8aRoeev+8ur5WG1BkDCwgR25+V+iGk3GpFGnigpod73YlE8erl0r2D7U6ptz/fuJ49S2+QdVaHXKsWnq1u+JaHW86TKrrxyZQdAwsIEdm9pPQDadiqb+2lsfbs23J0Y5j7W9w84/nfjDXLUNtnW/Ys21JjW9bZDX9M52O1Ov/sQkUGQMLyFFagHcJzPSi7iv29dTymHdu08TQps5eKb04n49RrSJP3zK4pePKWr5zJUk9fQe7zVT3J7ibOwMLyBEDC8hR7MmPQjecirvMY7s4xLEHNy/8fDUuP1PSn0s2dvp/RxuTtM1nlp5ZyxPaH8594lJ3WYhjT4WXqv8eugFoZAwsIEcDCxbeJdfh0B2nYoreuvjqfWeEOPbujXP3D27uWJ8m/jRXunFa9y503eOe3pgm/rTBzR1XhTp5++z+kdmSXRLi2FN0aNe8xT8LHQE0slLoAKCR+QalXX36nrleGrrlFOa3TNhFkj4SKuDBq6tvsH71rzxy6JxqkrxI7ueYtFryM106Q5JMesBleyTtSCP7gSXpP+9q6/hhje4teFJHDuoSk+aF7jg1+049/HkBjYyBBeTN7duS1/vAUqSob+ma+z5Z+xPCH+nEC/+870v6fsiOqVrar1llt97QHZNi/q3QCUCj4yNCIGclpd8M3TBJi0uzWt8eOqKoyof2XyZpYeiOybAoKcpjEigsBhaQswXHOr9ThPOwJMnS9Jqey0cWh+4omlVX71uoNL0ydMckHRycu+jO0BFAo2NgATm7c5smZOk3QndMiml2WrYNoTOKpprEfyppTuiOSTH7eq0vXQE0IwYWUAOpl74aumGyItObuq+svCR0R1Gs6B15obl+J3THZLnrjtANQDNgYAG1kKb/YCrGt7bcZarqQyvfdaAA34YLa3X//rmp281FuO6VJJkpiZUUZuwDRcbAAmpg100d9574NmFBmJYnxyduNivGcAhl/KBvkWl56I7Jcte/7dy8cF/oDqAZMLCAGknN/yZ0w9REFyzrHf790BX1qruv8jbz2t7H8fT550MXAM2CgQXUSDThf2emJHTHVEQe/enK3sPPCt1Rb1asP/xsuX0gdMdUmFQtz0q+GLoDaBYMLKBGBj7cuVeuYnyb8L+0JJq4fdX6kVWhQ+rFyndUnuDJxO2St4ZumQqX/eP2axePhO4AmgUDC6ghT9PbQjdMnXckqX159dr9Z4UuCa17TWVJUtIX3Lw9dMtURfICPvaA4mJgATU0u33hlyWrhO6YKpeWViP/XE/fwfmhW0Lp+sNDC2yW/lYqzkntDzPcdqzj/4aOAJoJAwuoobs2aFzSp0N3TIfLnyKv3rHsstGloVtqrefykcV2vPoVd/2P0C3T4ulf3rlNE6EzgGbCwAJqzKPk40U72f2XXHpy3OJ3rFw3sjp0S62sXDey2sv2Nbk/NXTLdJgpsajlE6E7gGbDwAJqbGjjwp2e6iuhO6bNtDyx6I6V6w+dGzolbyt7Dz8rVfRVFfNjQUmSy744sGn+YOgOoNkwsJpcGnlh3klxtzh0Q1ZK5fLG0A2nxzuStPr3y9ftvyR0SV6W9VbemGr8K0U8of3hYi/fFLohK6lZKXTDZKWecr/HJsfAanJxFI2Hbpgsi9KW0A1Z2XHDvO9L+k7ojtPjrZGlW7vXV2550jWVYtzoeBJW9++f2907+olY2ubSzNA9p8Nl/3r35rnfC92RFVNamEtjeDkaC92AsBhYzc6SwjwJmJfKoRuyFCm9LnRDJlK94fiYvtXTV3lx6JTT1d03+msT+9NvSf660C1ZsNgb4zH2IIvKhfklq5SmhfnlFflgYDW5NI0L8ySQRGlD3Xx45+aFX5WrOPcnPLkuSV/s6qt8dNXV+xaGjpmqnstHFnevr9wi978r0r0FT8Zl/zp4Y8fXQ3dka6JAlwnhHaxmx8Bqcl6gd7AiTwt9LsxjsVh/GrohK+4yc72pOhH/+/L1+/uWrrlvVuimU1nar1nd6/df6SX7oVK9IXRPlsqWvC90Q9Y8tbbQDZOVlpPC/PKKfDCwmlxLNT0SumGy3KKO0A1ZG9jY8Q1J/xS6I2NzojT93+WZ5f/o7h15x+Kr950ROui/O7t/ZHZX78ja8v7KXUrTP5FpduimLLnpazs2LfzX0B1Zs8gK8xww4cV5bkU+GFhNbsfexfslT0N3TIZZuix0Qx7iJHl3Ua+LdQqLJHv/jIn4593rhv939xX7ekIHda0fXtHdO/K++w/Yz032ZzJ1hm7KmklVJdG7Q3fkweUF+fjW03t3LTkQugJhFeYrr8iH366ku88OybUgdMspuXWFTsjD3Tct+nF338inJGvUSx7Ml0V9VlJvd2/lm6lHn03POPbFe65dOlqLgz/xqvs6xqqlV0v22siiX3XJanHcUFy6dWhr209Dd+TCvasY//jsgN/ekL80YQoYWJBS7ZfV/8BKzVaGbshLeWbyvokHSq+RaW7olry4yyS9ILL0BfGx1k3dvZU7PbWvluPkm2M2/oPdG886lsVxlq2/Z2ZL2vorVdcLzPQys/IzJcUPNjS6g9VZY38WOiIvrmiFqf7/Ibprf+gGhGfeBM84OLnu3pF/kew5oTsmo5xWl27fungkdEceunora0y6IXRHIBMy/dSkn7hFv/A02RUp2hV5un/sjPH9s5PW8Z9f13FEOnH+1MSR6ozq8XJb2pq0pUm0zMy6ZHqCUnuK5E+W1FCX9Jg87x3c3Pnx0BV56Ll8ZLGXbVfojskw928PbOl8YegOhMU7WJCZ3VuUnT1u5adJ+lrojjzsWtDx590HRl/j8ueGbgmgLNfTXXq6PJXJ5HIlZiodbdVxSd29lQf/UpNUPvHslcQnPjDyB/9VgHc38pN+d2jBwltDV+TFLH6qqxCni0pme0InIDxOcockDYYOmKzI1LD3v/MNSiNPL5fpeOgWFI2NWRJf7huKskCmLo2TZ4dumDSzgdAJCI+BBXnqhXjb/UHnhQ7I091bOrfL9cHQHSgY8w8M3NT+89AZubK4OO/sug+FTkB4DCxIboOhEybL5c+1/sZ+3A4t6LjRpH8M3YGCcH17aE/HptAZebILFUtpcd7BYmBBDCxI8paoSG9nt/UcGm3YjwmlEx8VxuXk9yTtDd2COuc6HFt8aaNfEqBr6fCzJRXmNjlRyXaGbkB4DCyo80jbdpcKc1uHNPHzQzfkbcf1i4YV6+2mxj2nBqfP5X13b15QpI/4p8VUennohsly2djOuR0MLDCwIN25TRPm+kXojsky6TdCN9TC4I0dX3f59aE7UJ9c+tjQls7bQ3fUgnt6QeiGyYrkP/MNqobuQHgMLEiSzPzHoRsmy03nLFs/sip0Ry0MLei8Vo13r0KcNr+zJT34rtAVtbDyysoTJD0tdMfk+V2hC1AfGFiQJLmsUE8KJdfrQjfUgm9QWionl0raF7oFdcI1koxFv7t966qx0Cm1kFT1+tANU+Gyn4RuQH1gYEGSFKXpj0I3TIWn9hazQtyU7LTtuH7RsCx9s0mZ3EoGxWWmo2b2ht03tzfFhSytX5Gb3hy6Yyo8tUI9lyI/DCxIkjxu+a7kxTmh2rSya23lxaEzamVw08JvyaO3mDi3o1mZKbFEbxvY3P6d0C21snz/6EtM6g7dMXmetMi+G7oC9YGBBUnSwKb5B+X209AdUxL5H4ROqKWBLW1/n7gusyLc7RaZMpOnsit2bu34UuiWWoqUXh66YSpM9uPtW9sOh+5AfWBg4b9E/m+hE6bEdcHydw6vDJ1RS7u2dPyVK/qT0B2orVTRHw9tav+L0B21tPKdI6vd9MrQHVNiBXsORa4YWPgviX0rdMLUWBRNWF/oilob3NS20d1uCt2BGnHdMrSpbXPojFpLJ+wqyYr1GuUq2HMo8lSsBy9yVZ4ZfSN0w1S528Urew8sD91Ra7u2tr/HTX8ZugN5s88OtXVcHbqi1rrWD69I3X83dMeUmNzN/jl0BuoHAwsP2X5d2z2SF+orxia1pJa8J3RHrbnLO492XCGzprjQZFMyu73jWPsa39B8V/OPUnuvycqhO6bE9R+DmzruC52B+sHAwiOY2R2hG6bK3S/q7qs8M3RHrd25TRNDm9vfJvctoVuQMYs+OjS//ffu3KaJ0Cm11n3lyDkuvTF0x5SZ/UPoBNQXBhYewatFfJKwyNw+ELoiBHf54JbO96ZKr+HbhcV34p+hv39wU9vVzfjOlZnMqrapcOdeSbLEvxq6AfWlcA9i5KtsB/5VsvtDd0yVy1/c01d5Q+iOUHZtXviRquv3peZ7x6NRmClJza4Y3Nx5beiWUHrWDb/ZTc8L3TFVLjt8RnsHJ7jjERhYeIQTt9/wr4TumA53bVx19b6FoTtC2b2549Oy+E1mOhq6BVNjpqPy6PVDG9tvC90SytKr7utIFRfynejI0i/dtUHjoTtQXxhYeJRIpc+Gbpim9qQaN93X2R9ucNOC/+tKf0uySugWTJJrxKzlgoHNbQX8eD475aR0s+QdoTumw1X6XOgG1B8GFh7FDx28w6VDoTumw12vXdE7/JbQHSENblr4rWRMz5f8e6FbcHJm+mF8PH7xzo1zm/r2Kt3rKm+T26tDd0zTwXIy+v9CR6D+MLDwKAO3dh+PrJgfE0pSonjTit7KE0N3hLT75vY95fTQr0vRzaFb8DjMbz1jfsf/vHvbgl2hU0LqWr//KTK7PnTHtJl/6cSpFcAjMbDw2Kr+mdAJ02XyOYn8s0+6pjIndEtI27euGhvc3PbONNXbJR0J3YMHuQ67/K2DmzrXNvt5OyvfdWCe0vSzkp8RumW6PI0+HboB9YmBhcc02LHwqy4v7G/WJnvS8TH/pF2oOHRLaLu2dnwmPhafZ27cJy04/57S5PlDmzuLep5jZuxCxemx9DaTVoVumTbXwK629q+HzkB9YmDhMfkGpeZW8G802QVdZ45sDV1RD+7etmDXYFv7q9ztfZLxcUbN2ZhM/UP3dr5s8KZFA6Fr6kH30pEb3bxYN3P+byzyTzbj9cowOQwsPK7yjOhWyZPQHafHfq+7t9J093J7LL5B1aEt7R/0KHm2JO6ZViuub0fyXx3c1HGD366C/zxlo6d35F3u9gehO06PV5OWMwr+SyjyZO5c/BmPr6d39Asuf1XojtNlZusGNrVzwveDrF/R8gOVS03aIGle6J4GdVDyPxna0vkJd66y/0vd60Yul9mm0B2nz780uLnzNaErUL94Bwsn5e4N8RGbyzf39I1eFrqjXvgGpUObO/7cZ5afKkU3m1QN3dQoTEoV6TPlWdVnDm7u/Djj6r909468Q5FtDN2Rhagq7gGKk+IdLJxST2/luy49I3RHRt4zuLmjuF8Jz8mqdfvOrlr8fkkvDt1SZG76mpLo3UNb234auqXe9PSN/KG79YfuyIK5f39gS+dzQ3egvjGwcEo9fZU3uKthzjUw08cG53es9Q28a/Pf9Vy57zxP4j+S9MLQLQXzHYv0voGNHd8IHVJv7ELF3WeObHRZw7yDHMnftJNvguIUGFg4pXPXqDwyY+Q/zeys0C1ZMfcvlzy+ePvWtsOhW+rRyvXD/zNJomtkOi90Sz0zt3/zSNcNbmr/x9At9Wjluw7MS4+ltxX924IP59LQrgUdT+YXNJwKAwuT0rOu8vtuaojzsX7JpR2KotcNbWz7SeiWetXTN/IMN/sDS/U6l0qhe+qBSam73xHFrdc3+y1uTmZFb+WJifyzJntS6JZMmf/+4KbOT4TOQP1jYGFSzu5Xy5EDIz812fLQLdmy+83TvoEtnQ3zEWgeuq/Y16MoulSyN8rUGbonkGHJP21W/vjApvmDoWPqWXffyFvl0Y1FvkL7Y3INdBzvOPvObZoInYL6x8DCpJ140rSPhu7Ig0l/U0qrV2zfungkdEs9O7tfLQ8cHH6le3yRmb/EvbGvlG+mxN2+Zl79VPvxRf8fL6wnt+rqfQuTiehDLvut0C15iNwu3bml/S9Cd6AYGFiYtHPXqFyZWfmxpBWhW/JhFZfe+f+3d++/ddd1HMdf78/pGRjGWHt65hbEnm5gVJBJIoIREwTxEogGJyQKQRcFUdjWORLhB4WSYUBhaze8EW9B4mXGK6BBxaEhQdEE0U0St/W0mxujPe3GBlPW8/2+/WF4DeK2ftrPuTwff8Grv5w8+718viMDpXtSL2kGJ31sX5fyg28vuF9sZm9plVuIh24B6tHc8u93SN8dGpj3VOpNjc5MVlk+doWb3cxx5DMAAAnUSURBVCapK/We6eDSn7fv6l7MYbE4XAQWjkilb3SJFJr2Q9CHxx81hVXVgdJvUi9pFr3XjM3Pi+GtJl0g+ZvVfIeXPi3ZRpd+VlD2AFF1+Cqrxs6wut3hpnNSb5lOIS8sGVrXeW/qHWgeBBaOWO+K2i9a/cdU8lyye8zqq6tr5w+nXtNMrF8dPXtHz/S88CYznSX3s2Wak3rXf3Dtk9kjkv9Glj88Mnfeb3kr7Mj0fGx0YXD7hLveK1lLH1ptbhurg6W3pd6B5kJg4YhVVo2doUyPtPqPqiS5fDLI7q4Hv2PHmvLW1HuakfUrLJp46tWT1vFaSacG91NdOm0GH5YfNdfmXLZJpj8pTD62/YT5T/CR3qOzaFXtFXmuVbn75SYrpt4z/TwrhPz129a89I+pl6C5EFg4KpW+2l2SPpB6x8zxXNJ9ysLnRu4sbeTzJ1PXc8PTneFvB3uU5z25QsWscKKUd0lWMnmXu3eZwvFuXjB50WWH3khzPSNTXbK6PH/Ggu1xt3GZJiSbcM92FGTDbr5dKg5X187dm/hPbXrWr/Dy8fHzLOQfkXRhO/xz9U/mdw2vLV+begaaD4GFo3LK8t3lyVB8XPLu1FtmnKsq+d2FY7Rh26fLW1LPAabLolW1V2SZX+qyK0yqpN4z01z2VB6Ki3esmTOReguaD4GFo1ZZXrtMQV9NvSOxx03hXskfGN5V+h1vGKGZ2aUq9Jw4+npTx9vc84sknZ56U0rB/fKhwfKG1DvQnAgsTEmlr3a/pAtS72gQe032iCz/dZ6F34Ys31T9bHl36lHA/9J7zdh8s8Jr8o7sTPNwdm7+Bmu+N0Cnhbn9uDpYasnzvDAzCCxMSe/K3RX34mMtd2JzNFYzz7e62YiZ7ZD7mCkfz6VnQ679mRW44oVpU8gs5B31OUE6zhVKMiu7+0mSV6SwqC1v8R8Gl+0vFuy1W+/o2pF6C5oXgYUpW9hXuzKXPpt6BwDEYO4frg6W2/3xB0wRgYUoevtq33Lp3al3AMCUmP9weG35ktQz0Pza51VbTKuDHZPXSvZk6h0AcNRcu+qTx16degZaA4GFKHbevqAW8uzK58+LAoAm45mkpX+58/jx1EvQGggsRDO0bt5P5XZL6h0AcKRM4abhwe6NqXegdfAMFqIyk/X0jW2Q27tSbwGAw2Hu9w2vKy/hCw2IiStYiMpdbipeKde21FsA4P9xaWt4ScdS4gqxEViIrrp27t58VnaJy/al3gIAL2KvmS3Zdmvn06mHoPUQWJgW2z/z0k0h8/e4dDD1FgD4by6fdLf3Dq8tPZF6C1oTgYVpU13f/VBwX5Z6BwD8B5MXPFw9Mlh6MPUUtC4CC9Pq0GnIdlvqHQDwD0Fh9dBg6eupd6C18RYhpt3zbxaul9tVqbcAaG8m/3x1oLwi9Q60Pq5gYdq5y0cGysvMxLe9ACRj8nuGO8srU+9AeyCwMCPc5cM7uz8q6TuptwBoQ+Y/HO4sX+U3iq9NYEYQWJgxvkHZ7M7upWb6fuotANqHSd+bPbd8md+oeuotaB88g4UZZ5eq0HNi7QtyvT/1FgCtzeTfHO4sf5C4wkwjsJCEmay3r3Z77uIYBwDTw/yukbnl5dwWRAoEFpIxk1VWTNzkym9IvQVACzG5ebilOtB1c+opaF8EFpJb2Dd6RSb7vMmKqbcAaHZel9vy4cHuL6VegvZGYKEhVJaNn+cF/7ZJJ6TeAqA5uWx/yLL3VdfPeyD1FoC3CNEQhteXfqEQzpVrW+otAJqPu7aY6RziCo2CwELDGFnTtbno4SyT/yD1FgDNw2T3h9DxRj7cjEbCLUI0HDNZz4radZLfLFkh9R4AjcqzYIVPVed23cKbgmg0BBYaVs+K8fPN/CuSFqTeAqDR+E7LbGl1ffdDqZcAL4RbhGhYI4OlB806Fsu0IfUWAI3D5D+o1499HXGFRsYVLDSFSt/YB6XwGclnp94CIA2X7Q+Wr6quLX8t9Rbg/yGw0DQqKw8skD+7XrJ3pt4CYGaZ7CdBYdm2gc7tqbcAh4PAQtOp9I0ucRUGTT4v9RYA08tlo5KuHxko3ZN6C3AkCCw0pZddu79U7HhutcuXSsazhEDL8UymL2d2zCd3rJkzkXoNcKQILDS13uvGX+l1u13K35p6C4A4TPaQKbtuaGDeH1JvAY4WgYWWUFkxfrGb32LSyam3ADg67tpSsI4bhgbm/ij1FmCqCCy0DOtX6NkzerE8rJZpUeo9AA6Py7eb260jXd1f8xtVT70HiIHAQss5rV+zDkzUPpCZf9xkJ6XeA+CFuTRi8lu7/1q++3df1GTqPUBMBBZalvUr9Ozd8w55/XrJzkq9B8AhJv0+l63b3ln6Fles0KoILLSF3mW1c2Va4cHfzvcNgRQ8k/TjUNfg0J3lX6VeA0w3AgttpbKytkCuy+X6kEy9qfcArc93BoVvmMIXOSQU7YTAQluyfoXesYnzvZi9L3e7yKQTUm8CWshemd/refjG9q7SRr9ReepBwEwjsND2Tlm+9ZiDoXRBUP2SXOEikx+fehPQbFy2L1h+n6vjO8Vs/Odb1p38XOpNQEoEFvBvrF8dPXtrpweFC93zC910hlyWehfQkFxVM92fu90/y/c8TFQB/0JgAS+isvLAAtOBc+V+tsvOkfzVPCSP9uSZZJvN/GHl9msP+uXw2u4nU68CGhWBBRyBU5ZPzMlynZUX8sUW/FR3O82lV5k0K/U2IBaXPRfkT8h8s7tt8twenyV7dMu6rn2ptwHNgsACpsj61dG7p7Yoz3yhBeuRWY/kFbmfmMtKZuqSVEq9E/g34+6aCKaapF0yq8p9RO4jocOGhuZ0D3E+FTA1BBYwA6xf4eTx3aXJY2x2IS8Us1yzJSlkflxmgatfiK7g+cG8YM9KUqHo+zPP68Xn/JmtpfnjvNUHTD8CCwAAILKQegAAAECrIbAAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAiI7AAAAAi+zvWXpaV9AECowAAAABJRU5ErkJggg=="

_ICON_BASE_BYTES: Optional[bytes] = None
_ICON_PNG_CACHE: Dict[int, bytes] = {}
_FAVICON_ICO_CACHE: Optional[bytes] = None

def _base_icon_bytes() -> bytes:
    global _ICON_BASE_BYTES
    if _ICON_BASE_BYTES is None:
        import base64
        _ICON_BASE_BYTES = base64.b64decode(ICON_PNG_B64.encode("ascii"))
    return _ICON_BASE_BYTES

def _icon_png(size: int) -> bytes:
    size = int(size)
    if size in _ICON_PNG_CACHE:
        return _ICON_PNG_CACHE[size]

    src = _base_icon_bytes()

    # Try to resize to requested size if Pillow is available, otherwise return the embedded PNG as is.
    out = src
    if size and size > 0:
        try:
            from PIL import Image  # type: ignore
            import io
            im = Image.open(io.BytesIO(src)).convert("RGBA")
            if im.size != (size, size):
                im = im.resize((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            out = buf.getvalue()
        except Exception:
            out = src

    _ICON_PNG_CACHE[size] = out
    return out

def _favicon_ico_bytes() -> bytes:
    global _FAVICON_ICO_CACHE
    if _FAVICON_ICO_CACHE is not None:
        return _FAVICON_ICO_CACHE

    src = _base_icon_bytes()
    try:
        from PIL import Image  # type: ignore
        import io
        im = Image.open(io.BytesIO(src)).convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        _FAVICON_ICO_CACHE = buf.getvalue()
    except Exception:
        _FAVICON_ICO_CACHE = src
    return _FAVICON_ICO_CACHE

@app.route("/favicon.ico")
def favicon_ico():
    ico_bytes = _favicon_ico_bytes()
    mt = "image/x-icon" if ico_bytes[:4] == b"\x00\x00\x01\x00" else "image/png"
    return Response(ico_bytes, mimetype=mt, headers={"Cache-Control": "public, max-age=86400"})

@app.route("/apple-touch-icon.png")
def apple_touch_icon():
    png_bytes = _icon_png(180)
    return Response(png_bytes, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})

@app.route("/apple-touch-icon-precomposed.png")
def apple_touch_icon_precomposed():
    png_bytes = _icon_png(180)
    return Response(png_bytes, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})

@app.route("/icon-192.png")
def icon_192():
    png_bytes = _icon_png(192)
    return Response(png_bytes, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})

@app.route("/icon-512.png")
def icon_512():
    png_bytes = _icon_png(512)
    return Response(png_bytes, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})

@app.route("/site.webmanifest")
def site_webmanifest():
    manifest = {
        "name": "Debripod",
        "short_name": "Debripod",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0b0c",
        "theme_color": "#0b0b0c",
        "icons": [
            {"src": f"/icon-192.png?v={ICON_VERSION}", "sizes": "192x192", "type": "image/png"},
            {"src": f"/icon-512.png?v={ICON_VERSION}", "sizes": "512x512", "type": "image/png"},
        ],
    }
    return Response(json.dumps(manifest), mimetype="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


SHELL_PAGE = r"""

<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Debripod</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="/favicon.ico?v={{ icon_v }}">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png?v={{ icon_v }}">
  <link rel="apple-touch-icon-precomposed" href="/apple-touch-icon-precomposed.png?v={{ icon_v }}">
  <link rel="manifest" href="/site.webmanifest?v={{ icon_v }}">
  <meta name="theme-color" content="#000000">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Debripod">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
  {% if autorefresh %}
  <meta http-equiv="refresh" content="{{ autorefresh }}">
  {% endif %}
  <style>
    :root{
      color-scheme: dark;
      --bg:#000000;
      --surface: rgba(28,28,30,.70);
      --surface2: rgba(44,44,46,.55);
      --surface3: rgba(118,118,128,.24);
      --text: rgba(255,255,255,.92);
      --muted: rgba(235,235,245,.60);
      --muted2: rgba(235,235,245,.38);
      --border: rgba(255,255,255,.10);
      --border2: rgba(255,255,255,.06);
      --primary:#0a84ff;
      --primary2:#0a84ff;
      --theme-accent: rgba(10,132,255,.88);
      --theme-accent-strong: rgba(10,132,255,1);
      --theme-accent-soft: rgba(10,132,255,.18);
      --theme-accent-outline: rgba(10,132,255,.42);
      --theme-accent-bar: rgba(10,132,255,.92);
      --theme-accent-glow: rgba(10,132,255,.36);
      --theme-visualizer-a: rgba(10,132,255,.42);
      --theme-visualizer-b: rgba(94,92,230,.30);
      --theme-visualizer-c: rgba(255,69,58,.18);
      --viz-energy: .0;
      --viz-bass: .0;
      --viz-mid: .0;
      --viz-treble: .0;
      --viz-x1: 50%;
      --viz-y1: 28%;
      --viz-x2: 22%;
      --viz-y2: 68%;
      --viz-x3: 78%;
      --viz-y3: 64%;
      --viz-r1: 40%;
      --viz-r2: 48%;
      --viz-r3: 44%;
      --viz-blur: 6px;
      --danger:#ff453a;
      --ok:#30d158;
      --shadow: 0 14px 44px rgba(0,0,0,.55);
      --shadow2: 0 8px 22px rgba(0,0,0,.38);
      --radius: 20px;
      --radiusSm: 14px;
      --barBlur: 26px;
      --uiFont: "Open Sans", "Segoe UI", Arial, sans-serif;
    }
    *{box-sizing:border-box}
    html{height:100%}
    body{min-height:100%}
    body{
      margin:0;
      background: var(--bg);
      color:var(--text);
      font-family: var(--uiFont);
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
      padding-bottom: calc(18px + env(safe-area-inset-bottom, 0px));
      scroll-padding-bottom: calc(18px + env(safe-area-inset-bottom, 0px));
      overscroll-behavior-y: contain;
      }
    body, button, input, select, textarea{font-family: var(--uiFont);}
    .wrap{max-width:none;margin:0 auto;padding:0}
    .topbar{
      position: sticky;
      top: 0;
      z-index: 200;
      width: 100vw;
      margin-left: calc(50% - 50vw);
      margin-right: calc(50% - 50vw);
      padding: calc(8px + env(safe-area-inset-top, 0px)) 12px 8px;
      border-bottom: 1px solid var(--border2);
      background: rgba(18,18,20,.72);
    }
    @supports ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))){
      .topbar{
        -webkit-backdrop-filter: blur(var(--barBlur)) saturate(1.25);
        backdrop-filter: blur(var(--barBlur)) saturate(1.25);
        background: rgba(28,28,30,.42);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
      transition: background .45s ease, border-color .45s ease, box-shadow .45s ease;
      }
    }
    .topbarInner{
      max-width:1100px;
      margin:0 auto;
      display:flex;
      gap:10px;
      align-items:center;
      flex-wrap:wrap;
    }
    .title{
      font-size: 15px;
      line-height: 1;
      font-weight: 700;
      letter-spacing: .1px;
      display:flex;
      align-items:center;
      gap:10px;
      user-select:none;
    }
    .brandLogo{
      width: 1em;
      height: 1em;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      opacity: .92;
    }
    .brandLogo svg,
    .brandLogo img{
      width: 1em;
      height: 1em;
      display: block;
    }
    .dot{
      width: 9px;
      height: 9px;
      border-radius:999px;
      background: var(--primary);
      box-shadow: 0 0 0 6px rgba(10,132,255,.16);
    }
    .chip{
      display:inline-flex;
      align-items:center;
      gap:8px;
      border:1px solid var(--border2);
      border-radius:999px;
      padding: 6px 9px;
      background: rgba(44,44,46,.30);
      color: var(--muted);
      font-size: 11px;
      line-height: 1;
      user-select:none;
      min-height:  26px;
    }
    button.chip{
      cursor:pointer;
      color: var(--text);
      background: rgba(44,44,46,.40);
      transition: background .12s ease, transform .06s ease, filter .12s ease;
    }
    button.chip:hover{background: rgba(44,44,46,.55)}
    button.chip:active{transform: translateY(1px)}
    .spacer{margin-left:auto}
    .row{display:flex; gap:12px; align-items:center; flex-wrap:wrap}

    
    @media (max-height: 720px){
      .topbar{padding: calc(6px + env(safe-area-inset-top, 0px)) 10px 6px}
      .topbarInner{gap:8px}
      .title{font-size:14px}
      .dot{width:8px;height:8px;box-shadow: 0 0 0 5px rgba(10,132,255,.14)}
      .chip{font-size:10px;min-height:24px;padding:5px 8px}
    }

.searchbar{
      margin-top:14px;
      border:1px solid var(--border2);
      border-radius: var(--radius);
      background: rgba(28,28,30,.60);
      box-shadow: var(--shadow2);
      padding:14px;
    }
    @supports ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))){
      .searchbar{
        -webkit-backdrop-filter: blur(22px) saturate(1.2);
        backdrop-filter: blur(22px) saturate(1.2);
        background: rgba(28,28,30,.44);
      }
    }

    input[type="text"]{
      width: min(760px, 100%);
      padding: 12px 14px;
      font-size: 15px;
      border-radius: 14px;
      border: 1px solid transparent;
      background: rgba(118,118,128,.24);
      color: var(--text);
      outline: none;
    }
    input[type="text"]:focus{
      border-color: rgba(10,132,255,.55);
      box-shadow: 0 0 0 4px rgba(10,132,255,.18);
    }

    select{
      padding: 12px 14px;
      font-size: 14px;
      border-radius: 14px;
      border: 1px solid transparent;
      background: rgba(118,118,128,.24);
      color: var(--text);
      outline:none;
      cursor:pointer;
    }
    select:focus{
      border-color: rgba(10,132,255,.55);
      box-shadow: 0 0 0 4px rgba(10,132,255,.18);
    }

    .btn{
      border: 1px solid rgba(10,132,255,.55);
      background: rgba(10,132,255,.22);
      color: var(--text);
      font-size: 14px;
      font-weight: 700;
      padding: 12px 14px;
      border-radius: 14px;
      cursor: pointer;
      transition: background .12s ease, transform .06s ease, filter .12s ease;
      user-select: none;
      min-height: 44px;
    }
    .btn:hover{background: rgba(10,132,255,.28)}
    .btn:active{transform: translateY(1px)}
    .btn.secondary{
      border:1px solid var(--border2);
      background: rgba(44,44,46,.35);
      color: var(--text);
      font-weight: 600;
    }

.filesHdr{font-weight:700;margin:10px 0 6px 0;}
.fileRow{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:8px 0;border-top:1px solid rgba(255,255,255,0.08);}
.fileMeta{flex:1;min-width:0;}
.fileName{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.fileSub{font-size:12px;opacity:0.85;margin-top:2px;}
.fileErr{font-size:12px;color:#ff9a9a;margin-top:4px;white-space:pre-wrap;}
.fileBtns{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;}
.btn.sm{padding:6px 10px;font-size:12px;line-height:1.1;}


    .btn.secondary:hover{background: rgba(44,44,46,.50)}
    .btn.danger{
      border: 1px solid rgba(255,69,58,.55);
      background: rgba(255,69,58,.16);
      color: rgba(255,255,255,.92);
    }
    .btn.danger:hover{background: rgba(255,69,58,.22)}

    a{color: var(--primary2); text-decoration:none}
    a:hover{text-decoration:underline}

    .grid{display:grid; grid-template-columns: 1fr; gap:12px; margin-top:14px}

    .card{
      border:1px solid var(--border2);
      border-radius: var(--radius);
      background: rgba(28,28,30,.60);
      box-shadow: var(--shadow2);
      padding: 14px;
    }
    @supports ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))){
      .card{
        -webkit-backdrop-filter: blur(22px) saturate(1.18);
        backdrop-filter: blur(22px) saturate(1.18);
        background: rgba(28,28,30,.44);
      }
    }
    .card h3{margin:0; font-size:15px; line-height:1.25; font-weight: 700}

    .meta{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      align-items:center;
      margin-top:8px;
      color:var(--muted);
      font-size:12px
    }

    .pill{
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--theme-accent-outline) 84%, rgba(255,255,255,0.12));
      background: color-mix(in srgb, var(--theme-accent-soft) 78%, rgba(255,255,255,0.08));
      color: rgba(255,255,255,0.96);
      font-size: 12px;
      line-height: 1;
      min-height: 26px;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);
      transition: background .45s ease, border-color .45s ease, box-shadow .45s ease;
    }
    .pill.ok{border-color: rgba(48,209,88,.40); background: rgba(48,209,88,.18); color: rgba(255,255,255,.96)}
    .pill.bad{border-color: rgba(255,69,58,.45); background: rgba(255,69,58,.18); color: rgba(255,255,255,.96)}
    .pill.v{border-color: rgba(10,132,255,.45); background: rgba(10,132,255,.18); color: rgba(255,255,255,.96)}

    details{margin-top:10px}
    summary{cursor:pointer; color: var(--muted)}
    .mono{font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; word-break: break-all}
    .actions{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:10px}
    .err{
      border: 1px solid rgba(255,69,58,.45);
      background: rgba(255,69,58,.12);
      color: rgba(255,255,255,.92);
      padding: 10px 12px;
      border-radius: 14px;
      margin-top: 12px;
    }
    .subrow{
      display:flex;
      align-items:center;
      gap:10px;
      flex-wrap:wrap;
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .right{margin-left:auto}

    .barwrap{
      border:1px solid var(--border2);
      border-radius:999px;
      overflow:hidden;
      height:10px;
      width:min(520px,100%);
      background: rgba(118,118,128,.18);
      margin-top:8px;
    }
    .bar{
      height:10px;
      width:0%;
      background: rgba(10,132,255,.92);
    }
    .taskdir{margin-top:10px; color: var(--muted2); font-size: 12px; line-height: 1.35}


    /* iPod layout */
    .ipodStage{
      width: 100vw;
      max-width: 100vw;
      margin-left: calc(50% - 50vw);
      margin-right: calc(50% - 50vw);
      display:flex;
      flex-direction: column;
      align-items: center;
      min-height: calc(100vh - var(--topbarH, 0px));
      padding-bottom: 0;
    }
.topPills{
      width: 100vw;
      max-width: 100vw;
      padding: 10px 12px 8px;
      display:flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      pointer-events: auto;
    }
.pathPill{
      display:inline-flex;
      align-items:center;
      max-width: calc(100vw - 24px);
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(28,28,30,.28);
      transition: background .45s ease, border-color .45s ease, box-shadow .45s ease;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.1;
      overflow:hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      user-select:none;
      opacity: 1;
      transform: translateY(0);
      transition: opacity .22s ease, transform .22s ease;
      will-change: opacity, transform;
      transition: opacity .22s ease, transform .22s ease, background .45s ease, border-color .45s ease, box-shadow .45s ease;
    }
    @supports ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))){
      .pathPill{
        -webkit-backdrop-filter: blur(18px) saturate(1.16);
        backdrop-filter: blur(18px) saturate(1.16);
        background: rgba(28,28,30,.34);
      }
    }
    .pathPill.pathPillHidden{
      opacity: 0;
      transform: translateY(10px);
      pointer-events: none;
    }
    .wheelZone{
      width: 100%;
      flex: 1 1 auto;
      min-height: calc(var(--wheelSize) + (var(--wheelGap) * 2));
      display:flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      padding-top: var(--wheelGap);
      padding-bottom: var(--wheelGap);
    }

    /* Keep the iPod UI clear of the bottom tab bar on shorter viewports */
    @media (max-height: 880px){
      .wheel{width: 260px; height: 260px;}
      .wheelCenter{width: 94px; height: 94px;}
    }
    @media (max-height: 760px){
      .ipodWheelWrap{width:auto; flex: 0 0 auto; margin-top: 0;}
    }
        .ipodScreen{
      flex: 0 0 auto;
      width: 100vw;
      max-width: 100vw;
      margin-left: calc(50% - 50vw);
      margin-right: calc(50% - 50vw);
      aspect-ratio: 1 / 1;
      height: auto;
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 20px;
      background: rgba(28,28,30,.42);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
      padding: 0;
      position: relative;
      overflow:hidden;
      display:flex;
      flex-direction: column;
      isolation:isolate;
      transition: background .45s ease, border-color .45s ease, box-shadow .45s ease;
    }
    @supports ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))){
      .ipodScreen{
        -webkit-backdrop-filter: blur(18px) saturate(1.16);
        backdrop-filter: blur(18px) saturate(1.16);
        background: rgba(28,28,30,.34);
      }
    }

    .visualizerBg{
      position:fixed;
      inset:0;
      z-index:0;
      pointer-events:none;
      opacity:0;
      transition: opacity .55s ease, filter .38s ease, transform .38s ease, background .24s linear;
      background:
        radial-gradient(circle at var(--viz-x1) var(--viz-y1), var(--theme-visualizer-a) 0%, rgba(0,0,0,0) var(--viz-r1)),
        radial-gradient(circle at var(--viz-x2) var(--viz-y2), var(--theme-visualizer-b) 0%, rgba(0,0,0,0) var(--viz-r2)),
        radial-gradient(circle at var(--viz-x3) var(--viz-y3), var(--theme-visualizer-c) 0%, rgba(0,0,0,0) var(--viz-r3)),
        radial-gradient(circle at 50% 52%, rgba(255,255,255,calc(.03 + var(--viz-energy) * .08)) 0%, rgba(0,0,0,0) 24%),
        linear-gradient(180deg, rgba(255,255,255,calc(.015 + var(--viz-treble) * .03)) 0%, rgba(0,0,0,0) 28%),
        linear-gradient(0deg, rgba(0,0,0,.22) 0%, rgba(0,0,0,0) 28%),
        radial-gradient(circle at 50% 50%, rgba(0,0,0,.06) 0%, rgba(0,0,0,.44) 58%, rgba(0,0,0,.96) 100%);
      filter: saturate(calc(1.0 + var(--viz-energy) * .7)) blur(var(--viz-blur));
      transform: scale(calc(1 + var(--viz-energy) * .018));
      will-change: opacity, filter, transform, background;
    }
    .visualizerBg::before{
      content:"";
      position:absolute;
      inset:-8%;
      border-radius:999px;
      pointer-events:none;
      opacity: calc(.12 + var(--viz-energy) * .18);
      mix-blend-mode: screen;
      background:
        radial-gradient(circle at calc(46% + (var(--viz-bass) * 8%)) calc(50% - (var(--viz-mid) * 8%)), var(--theme-visualizer-a) 0%, rgba(0,0,0,0) 24%),
        radial-gradient(circle at calc(56% - (var(--viz-mid) * 7%)) calc(56% + (var(--viz-treble) * 7%)), var(--theme-visualizer-b) 0%, rgba(0,0,0,0) 28%);
      filter: blur(calc(12px + var(--viz-energy) * 16px));
      transform: scale(calc(.98 + var(--viz-energy) * .08));
      transition: opacity .24s ease, filter .24s ease, transform .24s ease, background .16s linear;
      will-change: opacity, filter, transform, background;
    }
    .visualizerBg.active{ opacity:1; }
    .visualizerBg.off{ opacity:0; filter: saturate(.85) blur(0px); transform: scale(1); }

    .ipodHeader{
      position:relative;
      z-index:2;
      display:flex;
      align-items:center;
      gap:10px;
      color: var(--muted);
      font-size: 12px;
      padding: 12px 12px 10px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      background: rgba(28,28,30,.28);
      transition: background .45s ease, border-color .45s ease;
      user-select:none;
    }
    .libControlsRow{
      display:flex;
      align-items:center;
      gap:8px;
      flex-wrap:wrap;
    }
    .libInput{
      flex:1;
      min-width: 140px;
      padding: 7px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.10);
      background: rgba(10,10,12,0.35);
      color: var(--text);
      outline: none;
      font-size: 12px;
    }
    .libInput::placeholder{
      color: rgba(255,255,255,0.35);
    }
    .ipodLabel{
      display:block;
      flex: 1;
      min-width: 0;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
      padding-right: 8px;
    }
    .ipodPills{
      display:flex;
      gap:6px;
      flex-wrap:wrap;
      justify-content:flex-end;
      align-items:center;
      margin-left:auto;
    }
    
    .ipodItem.twoLine{
      flex-direction:column;
      align-items:stretch;
    }
    .ipodItem.twoLine .ipodLabel{
      margin-bottom: 6px;
      margin-right: 0;
      white-space: normal;
      line-height: 1.25;
    }
    .ipodItem.twoLine .ipodPills{
      margin-left: 0;
      justify-content:flex-start;
    }
    .ipodLabelWrap{
      display:block;
      flex: 1;
      min-width: 0;
    }
    .ipodSubLabel{
      display:block;
      margin-top: 3px;
      font-size: .92em;
      opacity: .82;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .ipodItem.twoLine .ipodSubLabel{
      white-space: normal;
      line-height: 1.2;
    }
    .libInlineInput{
      display:block;
      width: 100%;
      flex: 1 1 auto;
      min-width: 0;
      min-height: 0;
      height: 1.2em;
      max-height: 1.2em;
      border: none;
      border-radius: 0;
      padding: 0;
      margin: 0;
      background: transparent;
      color: #fff;
      outline: none;
      font: inherit;
      font-size: inherit;
      line-height: 1.2;
      vertical-align: middle;
      -webkit-appearance: none;
      appearance: none;
      box-shadow: none;
      caret-color: #fff;
    }
    .libInlineInput:focus,
    .libInlineInput:focus-visible{
      outline: none;
      border: none;
      box-shadow: none;
    }
    .ipodItem.editing{
      min-height: 44px;
      background: color-mix(in srgb, var(--theme-accent-soft) 88%, rgba(255,255,255,0.03));
      outline: 1px solid color-mix(in srgb, var(--theme-accent-outline) 94%, rgba(255,255,255,0.10));
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04), 0 0 0 1px rgba(0,0,0,0.08), 0 10px 26px rgba(0,0,0,0.12);
      transition: background .45s ease, outline-color .45s ease, box-shadow .45s ease;
    }
    .ipodItem.editing .libInlineInput{
      align-self: center;
    }
.ipodPill{
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--theme-accent-outline) 84%, rgba(255,255,255,0.12));
      background: color-mix(in srgb, var(--theme-accent-soft) 78%, rgba(255,255,255,0.08));
      color: rgba(255,255,255,0.96);
      font-size: 11px;
      line-height: 1;
      white-space:nowrap;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);
      transition: background .45s ease, border-color .45s ease, box-shadow .45s ease;
    }

    .ipodPill.bar{
      position: relative;
      min-width: 140px;
      padding: 0;
      height: 18px;
      overflow: hidden;
    }
    .ipodPill.bar .pillBarFill{
      position:absolute;
      left:0;
      top:0;
      bottom:0;
      width:0%;
      background: color-mix(in srgb, var(--theme-accent-bar) 58%, rgba(255,255,255,0.16));
    }
    .ipodPill.bar.ok .pillBarFill{
      background: rgba(120,255,160,0.28);
    }
    .ipodPill.bar.warn .pillBarFill{
      background: rgba(255,214,120,0.28);
    }
    .ipodPill.bar .pillBarText{
      position: relative;
      z-index: 1;
      padding: 0 8px;
      font-size: 11px;
      line-height: 18px;
      color: rgba(255,255,255,0.96);
    }
    .ipodPill.ok{
      border-color: rgba(120,255,160,0.35);
      background: rgba(120,255,160,0.16);
      color: rgba(255,255,255,0.96);
    }
    .ipodPill.warn{
      border-color: rgba(255,214,120,0.35);
      background: rgba(255,214,120,0.16);
      color: rgba(255,255,255,0.96);
    }
    .ipodItem{
      display:flex;
      align-items:center;
      gap:10px;
    }

    .ipodList{
      position:relative;
      z-index:2;
      list-style:none;
      padding:0;
      margin: 12px;
      overflow:auto;
      border-radius: 20px;
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(18,18,20,.88);
      flex: 1 1 auto;
      min-height: 0;
      opacity: 1;
      transform: translateY(0);
      transition: opacity .22s ease, transform .22s ease, background .45s ease, border-color .45s ease;
      will-change: opacity, transform;
    }
    @supports ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))){
      .ipodList{
        -webkit-backdrop-filter: blur(20px) saturate(1.10);
        backdrop-filter: blur(20px) saturate(1.10);
        background: rgba(18,18,20,.82);
      }
    }
    .ipodList.pageFadeHidden{
      opacity: 0;
      transform: translateY(10px);
      pointer-events: none;
    }

    /* Keep lib list border visible under Now Playing */
    #libList.npUnderlay{pointer-events:none; background: transparent; border-color: transparent; -webkit-backdrop-filter: none !important; backdrop-filter: none !important; box-shadow: none !important;}
    #libList.npUnderlay .ipodItem{opacity:0;}
    .ipodItem{
      padding: 11px 12px;
      border-bottom: 1px solid rgba(255,255,255,.06);
      display:flex;
      gap: 10px;
      align-items:center;
      user-select:none;
      cursor: default;
      min-height: 44px;
    }
    .ipodItem:last-child{border-bottom:none}
    .ipodItem.sel{
      background: var(--theme-accent-soft);
      outline: 1px solid var(--theme-accent-outline);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.04), 0 0 0 1px rgba(0,0,0,.08), 0 10px 26px rgba(0,0,0,.12);
      transition: background .45s ease, outline-color .45s ease, box-shadow .45s ease;
    }
    .ipodItem.info{cursor:default; opacity:.78}
    .ipodItem.random{justify-content:center; letter-spacing:.02em}
    .ipodItem.random.sel{background: color-mix(in srgb, var(--theme-accent-soft) 86%, rgba(255,255,255,.04)); outline: 1px solid color-mix(in srgb, var(--theme-accent-outline) 92%, rgba(255,255,255,.08))}
    .ipodBadge{
      margin-left:auto;
      color: rgba(235,235,245,.55);
      font-size: 12px;
    }

        .ipodWheelWrap{width:auto; flex: 0 0 auto; margin-top: 0;}
    .wheel{
      position: relative;
      z-index:2;
      width: 300px;
      height: 300px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(28,28,30,.42);
      position: relative;
      box-shadow: none;
      user-select:none;
      touch-action: none;
    }
    .wheelCenter{
      position:absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%,-50%);
      width: 130px;
      height: 130px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(28,28,30,.42);
      box-shadow: none;
      cursor:pointer;
      touch-action: none;
    }
    .wheelLabel{
      position:absolute;
      color: rgba(235,235,245,.62);
      font-weight: 700;
      font-size: 16px;
      letter-spacing: .3px;
      text-shadow: 0 1px 0 rgba(0,0,0,.55);
      pointer-events: none;
      user-select: none;
      display:flex;
      align-items:center;
      justify-content:center;
      min-width: 26px;
      min-height: 26px;
      line-height: 1;
      padding: 0;
    }
    .wheelLabel svg{
      width: 18px;
      height: 18px;
      display:block;
      overflow: visible;
    }
    .wheelLabel .menuWord{
      font-size: 14px;
      letter-spacing: .9px;
      font-weight: 800;
      color: #FFFFFF;
      line-height: 1;
    }

      .wheelLabel .wheelSvgIcon{
        width: auto;
        height: 14px;
        max-width: none;
        display: block;
        object-fit: contain;
        object-position: center;
        margin: 0;
        padding: 0;
        border: 0;
        flex: 0 0 auto;
      }
      .wheelLabel .wheelSvgIcon.isInactive{ opacity:.72; }
    .wheelLabel.top,.wheelLabel.wlTop{left:50%; top:18px; transform: translateX(-50%);}
    .wheelLabel.bottom,.wheelLabel.wlBottom{left:50%; bottom:18px; transform: translateX(-50%);}
    .wheelLabel.left,.wheelLabel.wlLeft{left:18px; top:50%; transform: translateY(-50%);}
    .wheelLabel.right,.wheelLabel.wlRight{right:18px; top:50%; transform: translateY(-50%);}

    .wheelHit{
      position:absolute;
      border-radius: 999px;
      opacity:0;
      touch-action: none;
    }

    /* Now Playing */
    .nowPlaying{
       display:none;
       position:absolute;
       left:0;
       top:0;
       width:100%;
       height:100%;
       overflow:hidden;
       overscroll-behavior: contain;
       text-align: left;
       border-radius: 20px;
       opacity: 0;
       transform: translateY(10px);
       transition: opacity .22s ease, transform .22s ease;
       will-change: opacity, transform;
       pointer-events: none;
     }
    .nowPlaying.npPageActive{
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }

    
.nowPlaying::before{
  content:"";
  position:absolute;
  inset:0;
  background: transparent;
  pointer-events:none;
  z-index: 2;
}
.npArt{
  position:absolute;
  inset:0;
  width:100%;
  height:100%;
  margin:0;
  max-width:none;
  aspect-ratio: auto;
  border-radius: inherit;
  border: none;
  background: transparent;
  object-fit: cover;
  z-index: 1;
}
.npArtSwapLayer{
  z-index: 3;
  pointer-events: none;
  opacity: 1;
  transform: translateY(0) scale(1);
  transition: opacity .22s ease, transform .22s ease;
  will-change: opacity, transform;
}
.npArtSwapLayer.npArtSwapHidden{
  opacity: 0;
  transform: translateY(10px) scale(1.015);
}
.npOverlayPill{
  position:absolute;
  left: 12px;
  right: 12px;
  bottom: 12px;
  z-index: 5;
  border-radius: 20px;
  border: 1px solid rgba(255,255,255,.14);
  background: rgba(28,28,30,.48);
  box-shadow: 0 12px 32px rgba(0,0,0,.38), inset 0 1px 0 rgba(255,255,255,.08);
  padding: 8px 10px 8px;
  -webkit-backdrop-filter: blur(18px) saturate(1.20);
  backdrop-filter: blur(18px) saturate(1.20);
  opacity: 1;
  transform: translateY(0);
  transition: opacity .22s ease, transform .22s ease;
}
.npOverlayPill.npPillHidden{
  opacity: 0;
  transform: translateY(10px);
  pointer-events: none;
}
.npOverlayPill.npPillSwapHidden{
  opacity: 0;
  transform: translateY(10px);
}
.npOverlayPill .npTitle{
  font-weight: 800;
  font-size: 14px;
  margin: 0;
  white-space: nowrap;
  overflow:hidden;
  text-overflow: ellipsis;
  text-shadow: 0 1px 0 rgba(0,0,0,.55);
}
.npOverlayPill .npSub{
  color: rgba(235,235,245,.62);
  font-size: 12px;
  margin-top: 2px;
  white-space: nowrap;
  overflow:hidden;
  text-overflow: ellipsis;
  text-shadow: 0 1px 0 rgba(0,0,0,.55);
}
.npOverlayPill .npBarArea{margin-top: 8px;}
.npOverlayPill .npTime{margin-top: 4px; display:flex; align-items:center; gap: 8px; font-size: 11px; color: rgba(235,235,245,.62); text-shadow: 0 1px 0 rgba(0,0,0,.55);} 
.npOverlayPill .npTime #npCur, .npOverlayPill .npTime #npDur{min-width: 44px;} 
.npOverlayPill .npTime .npTechInline{flex:1; text-align:center; white-space: nowrap; overflow:hidden; text-overflow: ellipsis;}

.npVideoOverlay{
      position:absolute;
      inset:0;
      z-index: 20;
      display:none;
      align-items: stretch;
      justify-content: stretch;
      background: #000;
      border-radius: inherit;
    }
    .npVideoOverlay video{
      width:100%;
      height:100%;
      background:#000;
      border-radius: inherit;
    }
    .npRow{display:flex; gap: 12px; align-items: center;}
    .npText{flex: 1 1 auto; overflow:hidden;}
    .npTitle{
      font-weight: 800;
      font-size: 15px;
      white-space: nowrap;
      overflow:hidden;
      text-overflow: ellipsis;
    }
    .npSub{
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      white-space: nowrap;
      overflow:hidden;
      text-overflow: ellipsis;
    }
    .artistStrong{font-weight: 700; color: inherit;}
    .npSeek{width: 100%; margin: 0;}
    input[type="range"].npSeek{
      accent-color: var(--theme-accent-strong);
      height: 24px;
      transition: accent-color .45s ease;
    }
    .npBarArea{margin-top: 10px;}
    .npProgressWrap{position: relative;}
    .npBufferedBar{
      position:absolute;
      left: 9px;
      right: 9px;
      top: 50%;
      height: 4px;
      transform: translateY(-50%);
      background: rgba(118,118,128,.16);
      border-radius: 999px;
      overflow: hidden;
      pointer-events: none;
    }
    .npBufferedFill{
      height: 100%;
      width: 0%;
      background: rgba(160,160,170,.62);
      border-radius: 999px;
      transition: width .15s linear;
    }
    .npSeekIndicator{
      position:absolute;
      top: 2px;
      bottom: 2px;
      width: 2px;
      background: rgba(235,235,245,.88);
      border-radius: 2px;
      display:none;
      pointer-events:none;
    }
    .npVolumeWrap{display:none;}
    .npVolumeBar{
      height: 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(118,118,128,.18);
      overflow:hidden;
    }
    .npVolumeFill{height: 100%; width: 0%; background: rgba(235,235,245,.88);}
    .npTime{
      display:flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
    }
    .npHint{
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
      line-height: 1.35;
    }

    @media (max-width: 820px){
      .wheel{width: 280px; height: 280px;}
    }

    /* Small polish */
    ::selection{background: rgba(10,132,255,.35)}
    ::-webkit-scrollbar{height:10px; width:10px}
    ::-webkit-scrollbar-thumb{background: rgba(118,118,128,.30); border-radius: 999px}
    ::-webkit-scrollbar-thumb:hover{background: rgba(118,118,128,.44)}

    .wheelHit{
      position:absolute;
      background: transparent;
      border-radius: 999px;
      opacity:0;
    }
    .hitTop{
      left: 22%;
      top: 4%;
      width: 56%;
      height: 22%;
    }
    .hitBottom{
      left: 22%;
      bottom: 4%;
      width: 56%;
      height: 22%;
    }
    .hitLeft{
      left: 4%;
      top: 22%;
      width: 22%;
      height: 56%;
    }
    .hitRight{
      right: 4%;
      top: 22%;
      width: 22%;
      height: 56%;
    }
    .wheelBtn{
      cursor:pointer;
      background: transparent;
    }

        /* Tab transitions (fade like the Now Playing info pill) */
    /* (display is controlled with .show; opacity + slight Y shift controlled with .active / .fadingOut) */


    /* Search loading animation */
    .searchResultsWrap{
      position: relative;
      margin-top: 14px;
      min-height: 96px;
    }
    .searchLoader{
      display:none;
      align-items:center;
      justify-content:center;
      flex-direction: column;
      gap: 10px;
      padding: 16px;
      border:1px solid var(--border2);
      border-radius: var(--radius);
      background: rgba(28,28,30,.50);
      box-shadow: var(--shadow2);
      opacity:0;
      transform: translateY(10px);
      transition: opacity .22s ease, transform .22s ease;
    }
    .searchLoader.on{
      display:flex;
      opacity:1;
      transform: translateY(0);
    }
    .searchLoader .spinner{
      width: 28px;
      height: 28px;
      border-radius: 999px;
      border: 3px solid rgba(235,235,245,18);
      border-top-color: rgba(10,132,255,75);
      animation: dpSpin .9s linear infinite;
    }
    @keyframes dpSpin{ to { transform: rotate(360deg);} }
    .searchLoader .loaderText{
      font-size: 12px;
      color: rgba(235,235,245,62);
      text-align:center;
      line-height: 1.35;
    }
    .searchResultsInner{
      transition: opacity .22s ease, transform .22s ease;
      opacity:1;
      transform: translateY(0);
    }
    .searchResultsInner.off{
      opacity:0;
      transform: translateY(10px);
      pointer-events:none;
    }

    /* ===== Viewport fit: prevent page vertical scrolling ===== */
    html, body{
      height: 100%;
      width: 100%;
      margin: 0;
      overflow: hidden;
      overscroll-behavior: none;
    }
    body{
      padding-bottom: 0 !important;
      scroll-padding-bottom: 0 !important;
    }
    .wrap{
      position: relative;
      height: 100vh;
      height: 100dvh;
      overflow: hidden;
      isolation: isolate;
      background: #000;
    }
    .ipodStage{
      position: relative;
      z-index: 1;
      height: 100%;
      min-height: 100% !important;
    }
    :root{
      --wheelSize: 300px;
      --topPillsH: 70px;
          --wheelGap: 22px;
    }
    @media (max-height: 880px){
      :root{ --wheelSize: 260px; }
    }
    @media (max-width: 820px){
      :root{ --wheelSize: 280px; }
    }
    .ipodScreen{
      width: clamp(220px, min(100vw, calc(100vh - var(--topPillsH) - var(--wheelSize) - (var(--wheelGap) * 2) - 44px - env(safe-area-inset-bottom, 0px))), 100vw);
      width: clamp(220px, min(100vw, calc(100dvh - var(--topPillsH) - var(--wheelSize) - (var(--wheelGap) * 2) - 44px - env(safe-area-inset-bottom, 0px))), 100vw);
      max-width: 100vw;
      height: auto;
      margin-left: auto;
      margin-right: auto;
    }
    @media (min-width: 821px){
      .ipodScreen{
        position: fixed;
        inset: 0;
        width: 100vw;
        max-width: 100vw;
        height: 100vh;
        height: 100dvh;
        margin: 0;
        border-radius: 0;
        aspect-ratio: auto;
        z-index: 50;
      }
    }
</style>
</head>
<body>
  <div class="wrap" id="divwrap">
    <div class="visualizerBg off" id="visualizerBg"></div>
    <div style="margin-top:0;">
      <div id="tab-library">
        <div class="ipodStage">
          <div class="topPills">
            <div class="pathPill" id="libHeader">Library</div>
          </div>

          <div class="ipodScreen" id="ipodScreen">

              <div class="nowPlaying" id="nowPlaying">
                <img class="npArt" id="npArt" alt="">
                <img class="npArt npArtSwapLayer npArtSwapHidden" id="npArtSwap" alt="">

                <div class="npOverlayPill" id="npOverlayPill">
                <div class="npTitle" id="npTitle"></div>
                <div class="npSub" id="npSub"></div>

                <div class="npBarArea">
                  <div class="npProgressWrap" id="npProgressWrap">
                    <input class="npSeek" id="npSeek" type="range" min="0" max="1000" value="0">
                    <div class="npSeekIndicator" id="npSeekIndicator"></div>
                  </div>

                  <div class="npVolumeWrap" id="npVolumeWrap">
                    <div class="npVolumeBar"><div class="npVolumeFill" id="npVolumeFill"></div></div>
                  </div>
                </div>

                <div class="npTime">
                  <div id="npCur">0:00</div>
                  <div class="npTechInline" id="npTech"></div>
                  <div id="npDur">0:00</div>
                </div>
                </div>


                <div class="npVideoOverlay" id="npVideoOverlay" style="display:none;">
                  <video id="npVideo" controls autoplay playsinline></video>
                </div>

                <audio id="audioMain" preload="auto" playsinline></audio>
              </div>

              <ul class="ipodList" id="libList"></ul>
            </div>

          <div class="wheelZone" id="wheelZone">
            <div class="ipodWheelWrap">
              <div class="wheel" id="wheel">
                <div class="wheelLabel wlTop"><span class="menuWord">MENU</span></div>
                <div class="wheelLabel wlLeft"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 7 6 12l5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M18 7l-5 5 5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
                <div class="wheelLabel wlRight"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m13 7 5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><path d="m6 7 5 5-5 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
                <div class="wheelLabel wlBottom"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.5c2 0 3.3 0 4.4.8 1.1.7 2 2 3 3.4 1-1.4 1.9-2.7 3-3.4 1.1-.8 2.4-.8 4.4-.8" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/><path d="M17 7h3v3" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/><path d="M17 17h3v-3" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg></div>

                <div class="wheelHit hitTop wheelBtn" id="btnMenu" title="Menu"></div>
                <div class="wheelHit hitLeft wheelBtn" id="btnRev" title="Previous track"></div>
                <div class="wheelHit hitRight wheelBtn" id="btnFwd" title="Next track"></div>
                <div class="wheelHit hitBottom wheelBtn" id="btnPlay" title="Play or pause"></div>

                <div class="wheelCenter" id="btnCenter" title="Select"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
      </div>
    </div>
  </div>

  

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script>
(function(){
  const APP_INFO = {{ info_json|safe }};
  function humanBytes(bytes){
    const v = Number(bytes || 0);
    if(!isFinite(v) || v <= 0) return "0 B";
    const units = ["B","KB","MB","GB","TB"];
    let n = v;
    let i = 0;
    while(n >= 1024 && i < units.length - 1){
      n /= 1024;
      i += 1;
    }
    const p = n >= 100 ? 0 : (n >= 10 ? 1 : 2);
    return n.toFixed(p) + " " + units[i];
  }

  async function apiPost(url, payload){
    const res = await fetch(url, {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload || {}),
      cache:"no-store"
    });
    let j = null;
    try{ j = await res.json(); }catch(e){}
    return {ok: res.ok, status: res.status, json: j};
  }

const libHeader = document.getElementById("libHeader");

  // ===== path pill show/hide (like Now Playing info pill) =====
  let pathPillPinned = false;
  let pathPillHideTimer = null;
  try{
    pathPillPinned = (localStorage.getItem("debripod_path_pill_pinned") || "") === "1";
  }catch(e){}

  function isLibraryTabActive(){
    try{
      const t = document.getElementById("tab-library");
      if(!t) return true;
      return (t.style.display !== "none");
    }catch(e){
      return true;
    }
  }

  function showPathPill(pinned){
    const effectivePinned = !!pinned || !!pathPillPinned;
    try{
      if(!libHeader) return;
      libHeader.classList.remove("pathPillHidden");
    }catch(e){}
    if(effectivePinned){
      try{ if(pathPillHideTimer) clearTimeout(pathPillHideTimer); }catch(e){}
      pathPillHideTimer = null;
    }
  }

  function scheduleHidePathPill(ms){
    try{
      if(!libHeader) return;
      try{ if(pathPillHideTimer) clearTimeout(pathPillHideTimer); }catch(e){}
      pathPillHideTimer = setTimeout(()=>{
        try{
          if(!isLibraryTabActive()) return;
          if(pathPillPinned) return;
          const ae = document.activeElement;
          if(ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.tagName === "SELECT" || ae.isContentEditable)) return;
          libHeader.classList.add("pathPillHidden");
        }catch(e){}
      }, (ms || 2500));
    }catch(e){}
  }

  function pathPillActivity(pinned){
    const effectivePinned = !!pinned || !!pathPillPinned;
    showPathPill(effectivePinned);
    if(!effectivePinned) scheduleHidePathPill(2500);
  }

  function setPathPillPinned(on){
    pathPillPinned = !!on;
    try{ localStorage.setItem("debripod_path_pill_pinned", pathPillPinned ? "1" : "0"); }catch(e){}
    if(pathPillPinned){
      showPathPill(true);
    }else{
      pathPillActivity(false);
    }
  }

  if(libHeader){
    libHeader.addEventListener("click", ()=>{
      try{
        setPathPillPinned(!pathPillPinned);
      }catch(e){}
    });
  }

  window.addEventListener("pointerdown", ()=>{
    try{
      if(isLibraryTabActive()) pathPillActivity(false);
    }catch(e){}
  }, {passive:true});

  const libList = document.getElementById("libList");
  const ipodScreen = document.getElementById("ipodScreen");
  const visualizerBg = document.getElementById("visualizerBg");
  let npPageFadeTimer = null;
  let npPageFadeToken = 0;
  const nowPlaying = document.getElementById("nowPlaying");
  const npArt = document.getElementById("npArt");
  const npTitle = document.getElementById("npTitle");
  const npSub = document.getElementById("npSub");
  const npSeek = document.getElementById("npSeek");
  const npCur = document.getElementById("npCur");
  const npDur = document.getElementById("npDur");
  const npTech = document.getElementById("npTech");
  const npProgressWrap = document.getElementById("npProgressWrap");
  const npVideoOverlay = document.getElementById("npVideoOverlay");
  const npVideo = document.getElementById("npVideo");
  const npVolumeWrap = document.getElementById("npVolumeWrap");
  const npVolumeFill = document.getElementById("npVolumeFill");
  const npSeekIndicator = document.getElementById("npSeekIndicator");
  const npOverlayPill = document.getElementById("npOverlayPill");
  const npArtSwap = document.getElementById("npArtSwap");

  const audioMain = document.getElementById("audioMain");
  const npBufferedFill = document.getElementById("npBufferedFill");
  let activeAudio = audioMain;
  let standbyAudio = null;
  let activeAudioHls = null;
  let activeVideoHls = null;
  let preloadAudioHls = null;
  let preloadAudioEl = null;
  let preloadRequestNonce = 0;

// ===== volume (wheel controlled; native media element volume) =====
let userVol = 1.0;
try{
  const v = parseFloat(localStorage.getItem("debripod_volume") || "");
  if(!isNaN(v)) userVol = Math.max(0, Math.min(1, v));
}catch(e){}

function destroyHlsController(which){
  try{
    if(which === "audio" && activeAudioHls){
      try{ activeAudioHls.destroy(); }catch(e){}
      activeAudioHls = null;
    }
    if(which === "video" && activeVideoHls){
      try{ activeVideoHls.destroy(); }catch(e){}
      activeVideoHls = null;
    }
    if(which === "preload" && preloadAudioHls){
      try{ preloadAudioHls.destroy(); }catch(e){}
      preloadAudioHls = null;
    }
  }catch(e){}
}

function clearBufferedBar(){
  try{ if(npBufferedFill) npBufferedFill.style.width = "0%"; }catch(e){}
}

function updateBufferedBarFor(el){
  try{
    if(!npBufferedFill || !el) return;
    const d = Number(el.duration || 0);
    if(!(d > 0) || !el.buffered || !el.buffered.length){
      npBufferedFill.style.width = "0%";
      return;
    }
    const t = Number(el.currentTime || 0);
    let end = 0;
    for(let i=0;i<el.buffered.length;i++){
      const s = Number(el.buffered.start(i) || 0);
      const e = Number(el.buffered.end(i) || 0);
      if(t >= s - 0.25 && t <= e + 0.25) end = Math.max(end, e);
    }
    if(!(end > 0)){
      end = Number(el.buffered.end(el.buffered.length - 1) || 0);
    }
    npBufferedFill.style.width = Math.max(0, Math.min(100, (end / d) * 100)).toFixed(2) + "%";
  }catch(e){}
}

function applyVolume(){
  const v = userVol;
  try{
    if(activeAudio){
      activeAudio.muted = false;
      activeAudio.volume = v;
    }
  }catch(e){}
  try{ if(preloadAudioEl){ preloadAudioEl.muted = true; preloadAudioEl.volume = 0; } }catch(e){}
  try{ if(npVideo){ npVideo.muted = false; npVideo.volume = v; } }catch(e){}
  try{
    if(npVolumeFill){
      npVolumeFill.style.width = Math.round(v * 100) + "%";
    }
  }catch(e){}
}

function resetGaplessPrime(){
  try{
    preloadRequestNonce++;
    destroyHlsController("preload");
    if(preloadAudioEl){
      try{ preloadAudioEl.pause(); }catch(e){}
      try{ preloadAudioEl.removeAttribute("src"); preloadAudioEl.load(); }catch(e){}
      preloadAudioEl = null;
    }
  }catch(e){}
}

function enforceSingleAudio(){
  try{
    if(activeAudio){ activeAudio.muted = false; activeAudio.volume = userVol; }
    if(preloadAudioEl){ preloadAudioEl.muted = true; preloadAudioEl.volume = 0; }
  }catch(e){}
}

function hlsManifestUrl(rootId, rel){
  return "/hls/manifest?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel);
}

function canUseHlsJs(){
  try{ return !!(window.Hls && window.Hls.isSupported && window.Hls.isSupported()); }catch(e){ return false; }
}

function loadHlsIntoElement(el, manifestUrl, kind){
  return new Promise((resolve, reject)=>{
    try{
      if(!el) throw new Error("media element missing");
      if(kind === "audio") destroyHlsController("audio");
      else if(kind === "video") destroyHlsController("video");
      else if(kind === "preload") destroyHlsController("preload");

      const onReady = ()=>resolve(true);

      if(el.canPlayType && el.canPlayType("application/vnd.apple.mpegurl")){
        try{ el.src = manifestUrl; el.load(); }catch(e){}
        el.addEventListener("loadedmetadata", onReady, {once:true});
        el.addEventListener("loadeddata", onReady, {once:true});
        setTimeout(onReady, 1200);
        return;
      }

      if(!canUseHlsJs()) throw new Error("HLS playback is not supported in this browser");
      const hls = new window.Hls({
        autoStartLoad: true,
        enableWorker: true,
        backBufferLength: 90,
        maxBufferLength: 90,
        maxMaxBufferLength: 180,
        maxBufferSize: 120 * 1000 * 1000,
        manifestLoadingMaxRetry: 6,
        levelLoadingMaxRetry: 6,
        fragLoadingMaxRetry: 6
      });
      if(kind === "audio") activeAudioHls = hls;
      else if(kind === "video") activeVideoHls = hls;
      else if(kind === "preload") preloadAudioHls = hls;
      hls.attachMedia(el);
      hls.on(window.Hls.Events.MEDIA_ATTACHED, ()=>{
        try{ hls.loadSource(manifestUrl); }catch(err){ reject(err); }
      });
      hls.on(window.Hls.Events.MANIFEST_PARSED, ()=>resolve(true));
      hls.on(window.Hls.Events.ERROR, (evt, data)=>{
        if(data && data.fatal){
          reject(new Error((data.details || data.type || "hls error") + ""));
        }
      });
    }catch(err){ reject(err); }
  });
}

async function preloadNextAudio(){
  state.preloadedIndex = null;
  resetGaplessPrime();
  if(!state.preloadEnabled) return;
  if(!state.playlist.length) return;
  const ni = nextIndexPeek();
  if(ni === null) return;
  const next = state.playlist[ni];
  if(!next || !next.root || !next.rel) return;
  state.preloadedIndex = ni;
  const nonce = ++preloadRequestNonce;
  const manifestUrl = hlsManifestUrl(next.root.id, next.rel);
  try{
    preloadAudioEl = document.createElement("audio");
    preloadAudioEl.preload = "auto";
    preloadAudioEl.muted = true;
    preloadAudioEl.volume = 0;
    preloadAudioEl.playsInline = true;
    await loadHlsIntoElement(preloadAudioEl, manifestUrl, "preload");
    if(nonce !== preloadRequestNonce) return;
    try{
      if(preloadAudioHls && preloadAudioHls.startLoad) preloadAudioHls.startLoad(0);
      else if(preloadAudioEl.load) preloadAudioEl.load();
    }catch(e){}
    try{
      if(preloadAudioEl.play){
        const p = preloadAudioEl.play();
        if(p && p.then){
          p.then(()=>{
            try{ preloadAudioEl.pause(); preloadAudioEl.currentTime = 0; }catch(e){}
          }).catch(()=>{});
        }
      }
    }catch(e){}
  }catch(e){
    if(nonce === preloadRequestNonce) resetGaplessPrime();
  }
}

function gaplessPrimeMaybe(d, t){}
function gaplessEarlyHandoffMaybe(d, t){ return false; }
function gaplessHandoffToNext(ni){ return false; }


let volBarTimer = null;
let seekMode = false;
let seekChanged = false;
let seekPreview = 0;
let seekIdleTimer = null;

let npPillHideTimer = null;
let npArtSwapTimer = null;
let npPillSwapTimer = null;
let visualizerEnabled = false;
let visualizerActive = false;
let visualizerTrackKey = "";
let visualizerSampleNonce = 0;
const defaultTheme = {
  accent: "rgba(10,132,255,.88)",
  accentStrong: "rgba(10,132,255,1)",
  accentSoft: "rgba(10,132,255,.18)",
  accentOutline: "rgba(10,132,255,.42)",
  accentBar: "rgba(10,132,255,.92)",
  accentGlow: "rgba(10,132,255,.36)",
  visualizerA: "rgba(10,132,255,.42)",
  visualizerB: "rgba(94,92,230,.30)",
  visualizerC: "rgba(255,69,58,.18)"
};

let visualizerAudioCtx = null;
let visualizerAnalyser = null;
let visualizerData = null;
let visualizerSources = new WeakMap();
let visualizerFrameHandle = 0;
let visualizerLastFrameTs = 0;
let visualizerEnergy = 0;
let visualizerBass = 0;
let visualizerMid = 0;
let visualizerTreble = 0;

function currentVisualizerMediaElement(){
  try{
    if(isVideoActive && isVideoActive() && npVideo) return npVideo;
  }catch(e){}
  try{
    if(activeAudio && activeAudio.src && !activeAudio.paused) return activeAudio;
  }catch(e){}
  return null;
}

function ensureVisualizerAudioGraphFor(el){
  try{
    if(!el || !(window.AudioContext || window.webkitAudioContext)) return false;
    if(!visualizerAudioCtx){
      const Ctx = window.AudioContext || window.webkitAudioContext;
      visualizerAudioCtx = new Ctx();
    }
    if(!visualizerAnalyser){
      visualizerAnalyser = visualizerAudioCtx.createAnalyser();
      visualizerAnalyser.fftSize = 128;
      visualizerAnalyser.smoothingTimeConstant = 0.68;
      visualizerData = new Uint8Array(visualizerAnalyser.frequencyBinCount);
    }
    if(!visualizerSources.has(el)){
      const srcNode = visualizerAudioCtx.createMediaElementSource(el);
      srcNode.connect(visualizerAnalyser);
      visualizerAnalyser.connect(visualizerAudioCtx.destination);
      visualizerSources.set(el, srcNode);
    }
    if(visualizerAudioCtx.state === "suspended"){
      try{ visualizerAudioCtx.resume(); }catch(e){}
    }
    return true;
  }catch(e){
    return false;
  }
}

function setVisualizerMotionVars(energy, bass, mid, treble){
  const root = document.documentElement;
  const e = Math.max(0, Math.min(1, Number(energy || 0)));
  const b = Math.max(0, Math.min(1, Number(bass || 0)));
  const m = Math.max(0, Math.min(1, Number(mid || 0)));
  const t = Math.max(0, Math.min(1, Number(treble || 0)));
  try{
    root.style.setProperty("--viz-energy", e.toFixed(4));
    root.style.setProperty("--viz-bass", b.toFixed(4));
    root.style.setProperty("--viz-mid", m.toFixed(4));
    root.style.setProperty("--viz-treble", t.toFixed(4));
    root.style.setProperty("--viz-x1", (50 + ((m - .5) * 24)).toFixed(2) + "%");
    root.style.setProperty("--viz-y1", (30 + ((b - .5) * 24)).toFixed(2) + "%");
    root.style.setProperty("--viz-x2", (20 + (b * 16)).toFixed(2) + "%");
    root.style.setProperty("--viz-y2", (74 - (t * 22)).toFixed(2) + "%");
    root.style.setProperty("--viz-x3", (80 - (m * 18)).toFixed(2) + "%");
    root.style.setProperty("--viz-y3", (64 - (b * 14) + (t * 12)).toFixed(2) + "%");
    root.style.setProperty("--viz-r1", (30 + (b * 30) + (e * 8)).toFixed(2) + "%");
    root.style.setProperty("--viz-r2", (34 + (m * 32) + (e * 7)).toFixed(2) + "%");
    root.style.setProperty("--viz-r3", (30 + (t * 34) + (e * 8)).toFixed(2) + "%");
    root.style.setProperty("--viz-blur", (1.5 + (e * 8)).toFixed(2) + "px");
  }catch(e){}
}

function visualizerFrame(ts){
  try{
    const nowTs = Number(ts || performance.now() || 0);
    if(visualizerLastFrameTs && (nowTs - visualizerLastFrameTs) < 33){
      visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
      return;
    }
    visualizerLastFrameTs = nowTs;
    const el = currentVisualizerMediaElement();
    const canAnalyze = !!(visualizerEnabled && visualizerActive && el && ensureVisualizerAudioGraphFor(el) && visualizerAnalyser && visualizerData);
    let nextBass = 0;
    let nextMid = 0;
    let nextTreble = 0;
    let nextEnergy = 0;
    if(canAnalyze){
      try{ visualizerAnalyser.getByteFrequencyData(visualizerData); }catch(e){}
      const n = visualizerData.length || 0;
      if(n > 0){
        const bassEnd = Math.max(1, Math.floor(n * 0.16));
        const midEnd = Math.max(bassEnd + 1, Math.floor(n * 0.50));
        let bassSum = 0, midSum = 0, trebleSum = 0, allSum = 0;
        for(let i = 0; i < n; i++){
          const v = Number(visualizerData[i] || 0) / 255;
          allSum += v;
          if(i < bassEnd) bassSum += v;
          else if(i < midEnd) midSum += v;
          else trebleSum += v;
        }
        nextBass = bassSum / Math.max(1, bassEnd);
        nextMid = midSum / Math.max(1, midEnd - bassEnd);
        nextTreble = trebleSum / Math.max(1, n - midEnd);
        nextEnergy = allSum / n;
        const bassPeak = Math.min(1, Math.max(0, (nextBass - 0.08) * 1.90));
        const midPeak = Math.min(1, Math.max(0, (nextMid - 0.06) * 1.62));
        const treblePeak = Math.min(1, Math.max(0, (nextTreble - 0.05) * 1.72));
        const energyPeak = Math.min(1, Math.max(0, (nextEnergy - 0.05) * 1.85));
        nextBass = Math.min(1, (nextBass * 0.55) + (bassPeak * 0.95));
        nextMid = Math.min(1, (nextMid * 0.62) + (midPeak * 0.88));
        nextTreble = Math.min(1, (nextTreble * 0.58) + (treblePeak * 0.92));
        nextEnergy = Math.min(1, (nextEnergy * 0.45) + (energyPeak * 1.05) + (bassPeak * 0.12));
      }
    }
    const easeUp = 0.42;
    const easeDown = 0.18;
    const mixVal = (prev, nxt)=> prev + (nxt - prev) * (nxt > prev ? easeUp : easeDown);
    visualizerBass = mixVal(visualizerBass, nextBass);
    visualizerMid = mixVal(visualizerMid, nextMid);
    visualizerTreble = mixVal(visualizerTreble, nextTreble);
    visualizerEnergy = mixVal(visualizerEnergy, nextEnergy);
    setVisualizerMotionVars(visualizerEnergy, visualizerBass, visualizerMid, visualizerTreble);
  }catch(e){}
  visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
}

function ensureVisualizerFrameLoop(){
  try{
    if(visualizerFrameHandle) return;
    visualizerFrameHandle = requestAnimationFrame(visualizerFrame);
  }catch(e){}
}
try{
  visualizerEnabled = (localStorage.getItem("debripod_visualizer") || "") === "1";
}catch(e){}

let npPillPinned = false;
try{
  npPillPinned = (localStorage.getItem("debripod_np_pill_pinned") || "") === "1";
}catch(e){}

function setNpPillPinned(on){
  npPillPinned = !!on;
  try{ localStorage.setItem("debripod_np_pill_pinned", npPillPinned ? "1" : "0"); }catch(e){}
  if(npPillPinned){
    showNpPill(true);
  }else{
    npPillActivity(false);
  }
}

function hideNpPillImmediate(){
  try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
  npPillHideTimer = null;
  try{
    if(npOverlayPill) npOverlayPill.classList.add("npPillHidden");
  }catch(e){}
}

if(npArt){
  npArt.addEventListener("click", ()=>{
    if(nowPlaying.style.display !== "block") return;
    if(isNpPillShown()){
      npPillPinned = false;
      try{ localStorage.setItem("debripod_np_pill_pinned", "0"); }catch(e){}
      hideNpPillImmediate();
    }else{
      setNpPillPinned(true);
    }
  });
}


function clampByte(n){
  const v = Math.round(Number(n || 0));
  if(!isFinite(v)) return 0;
  return Math.max(0, Math.min(255, v));
}

function rgbaFrom(rgb, a){
  return "rgba(" + clampByte(rgb.r) + "," + clampByte(rgb.g) + "," + clampByte(rgb.b) + "," + Number(a).toFixed(3).replace(/0+$/,'').replace(/\.$/,'') + ")";
}

function mixRgb(a, b, t){
  const p = Math.max(0, Math.min(1, Number(t || 0)));
  return {
    r: Math.round((a.r || 0) + ((b.r || 0) - (a.r || 0)) * p),
    g: Math.round((a.g || 0) + ((b.g || 0) - (a.g || 0)) * p),
    b: Math.round((a.b || 0) + ((b.b || 0) - (a.b || 0)) * p)
  };
}

function themeFromBase(base){
  const white = {r:255,g:255,b:255};
  const black = {r:0,g:0,b:0};
  const a = mixRgb(base, white, .16);
  const b = mixRgb(base, {r:94,g:92,b:230}, .32);
  const c = mixRgb(base, {r:255,g:69,b:58}, .22);
  return {
    accent: rgbaFrom(a, .88),
    accentStrong: rgbaFrom(mixRgb(base, white, .12), 1),
    accentSoft: rgbaFrom(mixRgb(base, black, .06), .20),
    accentOutline: rgbaFrom(mixRgb(base, white, .10), .46),
    accentBar: rgbaFrom(mixRgb(base, white, .10), .94),
    accentGlow: rgbaFrom(base, .34),
    visualizerA: rgbaFrom(a, .46),
    visualizerB: rgbaFrom(b, .34),
    visualizerC: rgbaFrom(c, .22)
  };
}

function applyThemeVars(theme){
  const t = theme || defaultTheme;
  const root = document.documentElement;
  try{
    root.style.setProperty("--theme-accent", t.accent || defaultTheme.accent);
    root.style.setProperty("--theme-accent-strong", t.accentStrong || defaultTheme.accentStrong);
    root.style.setProperty("--theme-accent-soft", t.accentSoft || defaultTheme.accentSoft);
    root.style.setProperty("--theme-accent-outline", t.accentOutline || defaultTheme.accentOutline);
    root.style.setProperty("--theme-accent-bar", t.accentBar || defaultTheme.accentBar);
    root.style.setProperty("--theme-accent-glow", t.accentGlow || defaultTheme.accentGlow);
    root.style.setProperty("--theme-visualizer-a", t.visualizerA || defaultTheme.visualizerA);
    root.style.setProperty("--theme-visualizer-b", t.visualizerB || defaultTheme.visualizerB);
    root.style.setProperty("--theme-visualizer-c", t.visualizerC || defaultTheme.visualizerC);
  }catch(e){}
}

function visualizerShouldShow(){
  try{
    const hasArt = !!(state && state.now && state.nowMeta && state.nowMeta.art);
    const media = currentVisualizerMediaElement();
    return !!(visualizerEnabled && hasArt && media);
  }catch(e){
    return false;
  }
}

function setVisualizerActive(on){
  visualizerActive = !!on;
  try{
    if(!visualizerBg) return;
    visualizerBg.classList.toggle("active", !!on);
    visualizerBg.classList.toggle("off", !on);
  }catch(e){}
}

function updateVisualizerState(){
  ensureVisualizerFrameLoop();
  setVisualizerActive(visualizerShouldShow());
}

function setVisualizerEnabled(on){
  visualizerEnabled = !!on;
  try{ localStorage.setItem("debripod_visualizer", visualizerEnabled ? "1" : "0"); }catch(e){}
  updateVisualizerState();
  try{ if(state && state.current && state.current.kind === "libinfo") viewLibInfo(false); }catch(e){}
}

function sampleThemeFromArt(src){
  const art = nowPlayingArtSrcValue(src);
  const key = nowPlayingArtCompareKey(art);
  if(!key || !art){
    visualizerTrackKey = "";
    applyThemeVars(defaultTheme);
    updateVisualizerState();
    return;
  }
  visualizerTrackKey = key;
  const myNonce = ++visualizerSampleNonce;
  const img = new Image();
  img.decoding = "async";
  img.onload = ()=>{
    if(myNonce !== visualizerSampleNonce) return;
    try{
      const w = Math.max(8, Math.min(40, img.naturalWidth || 24));
      const h = Math.max(8, Math.min(40, img.naturalHeight || 24));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d", {willReadFrequently:true});
      if(!ctx) throw new Error("no canvas context");
      ctx.drawImage(img, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h).data;
      let r = 0, g = 0, b = 0, c = 0;
      for(let i = 0; i < data.length; i += 4){
        const a = Number(data[i + 3] || 0);
        if(a < 24) continue;
        const rr = Number(data[i] || 0);
        const gg = Number(data[i + 1] || 0);
        const bb = Number(data[i + 2] || 0);
        const mx = Math.max(rr, gg, bb);
        const mn = Math.min(rr, gg, bb);
        const sat = mx ? (mx - mn) / mx : 0;
        const lum = (rr * .299 + gg * .587 + bb * .114) / 255;
        if(lum < .08 || lum > .95) continue;
        const weight = Math.max(.18, sat) * (0.65 + (1 - Math.abs(lum - .5) * 1.2));
        r += rr * weight;
        g += gg * weight;
        b += bb * weight;
        c += weight;
      }
      if(!(c > 0)) throw new Error("empty sample");
      const base = {r: Math.round(r / c), g: Math.round(g / c), b: Math.round(b / c)};
      applyThemeVars(themeFromBase(base));
    }catch(err){
      applyThemeVars(defaultTheme);
    }
    updateVisualizerState();
  };
  img.onerror = ()=>{
    if(myNonce !== visualizerSampleNonce) return;
    applyThemeVars(defaultTheme);
    updateVisualizerState();
  };
  img.src = art;
}

function nowPlayingArtSrcValue(src){
  return String(src || "").trim();
}

function nowPlayingArtCompareKey(src){
  const v = nowPlayingArtSrcValue(src);
  if(!v) return "";
  try{
    const u = new URL(v, window.location.href);
    return (u.pathname || "") + "|" + (u.searchParams.get("v") || "");
  }catch(e){
    const q = v.split("?");
    let ver = "";
    try{
      const sp = new URLSearchParams(q[1] || "");
      ver = sp.get("v") || "";
    }catch(err){}
    return (q[0] || "") + "|" + ver;
  }
}

function currentNowPlayingArtSrc(){
  try{
    if(!npArt) return "";
    return nowPlayingArtSrcValue(npArt.getAttribute("src") || "");
  }catch(e){
    return "";
  }
}

function setNowPlayingArtSrc(src){
  try{
    if(!npArt) return;
    const v = nowPlayingArtSrcValue(src);
    if(v){
      npArt.src = v;
    }else{
      npArt.removeAttribute("src");
    }
  }catch(e){}
}

function escapeHtml(s){
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function artistAlbumHtml(artist, album){
  const a = String(artist || "").trim();
  const b = String(album || "").trim();
  if(a && b) return '<span class="artistStrong">' + escapeHtml(a) + '</span>   ' + escapeHtml(b);
  if(a) return '<span class="artistStrong">' + escapeHtml(a) + '</span>';
  return escapeHtml(b);
}

function setNowPlayingOverlayText(meta, fallbackLabel){
  const m = meta || {};
  try{ npTitle.textContent = m.title || fallbackLabel || "Track"; }catch(e){}
  try{ npSub.innerHTML = artistAlbumHtml(m.artist || "", m.album || ""); }catch(e){}
  try{ if(npTech) npTech.textContent = m.tech || ""; }catch(e){}
}

function isNpPillShown(){
  try{
    return !!(npOverlayPill && !npOverlayPill.classList.contains("npPillHidden"));
  }catch(e){
    return false;
  }
}

async function updateNowPlayingDisplay(meta, fallbackLabel, opts){
  const m = meta || {};
  const options = opts || {};
  const nextArt = nowPlayingArtSrcValue(m.art);
  const currentArt = currentNowPlayingArtSrc();
  const currentArtKey = nowPlayingArtCompareKey(currentArt);
  const nextArtKey = nowPlayingArtCompareKey(nextArt);
  const animateArt = !!(options.animateArt && npArt && npArtSwap && currentArtKey && nextArtKey && currentArtKey !== nextArtKey);
  const animatePill = !!(options.animatePill && isNpPillShown());
  sampleThemeFromArt(nextArt);
  const swapMs = 220;

  try{ if(npArtSwapTimer) clearTimeout(npArtSwapTimer); }catch(e){}
  npArtSwapTimer = null;
  try{ if(npPillSwapTimer) clearTimeout(npPillSwapTimer); }catch(e){}
  npPillSwapTimer = null;

  if(animateArt){
    try{
      if(currentArt){
        npArtSwap.src = currentArt;
      }else{
        npArtSwap.removeAttribute("src");
      }
      const prevTransition = npArtSwap.style.transition;
      npArtSwap.style.transition = "none";
      npArtSwap.classList.remove("npArtSwapHidden");
      void npArtSwap.offsetWidth;
      npArtSwap.style.transition = prevTransition || "";
    }catch(e){}
  }

  if(animatePill){
    try{
      npOverlayPill.classList.add("npPillSwapHidden");
    }catch(e){}
  }

  setNowPlayingArtSrc(nextArt);

  if(animateArt){
    requestAnimationFrame(()=>{
      requestAnimationFrame(()=>{
        try{ npArtSwap.classList.add("npArtSwapHidden"); }catch(e){}
      });
    });
    npArtSwapTimer = setTimeout(()=>{
      try{
        if(!npArtSwap) return;
        npArtSwap.removeAttribute("src");
        npArtSwap.classList.add("npArtSwapHidden");
      }catch(e){}
      npArtSwapTimer = null;
    }, swapMs + 40);
  }

  if(animatePill){
    npPillSwapTimer = setTimeout(()=>{
      try{ setNowPlayingOverlayText(m, fallbackLabel); }catch(e){}
      requestAnimationFrame(()=>{
        try{ if(npOverlayPill) npOverlayPill.classList.remove("npPillSwapHidden"); }catch(e){}
      });
      npPillSwapTimer = null;
    }, swapMs);
  }else{
    setNowPlayingOverlayText(m, fallbackLabel);
  }
}

function showNpPill(pinned){
  const effectivePinned = !!pinned || !!npPillPinned;
  try{
    if(!npOverlayPill) return;
    npOverlayPill.classList.remove("npPillHidden");
  }catch(e){}
  if(effectivePinned){
    try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
    npPillHideTimer = null;
  }
}


function scheduleHideNpPill(ms){
  try{
    if(!npOverlayPill) return;
    try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
    npPillHideTimer = setTimeout(()=>{
      try{
        if(nowPlaying.style.display !== "block") return;
        if(seekMode) return;
        if(npPillPinned) return;
        const m = wheelMedia();
        if(!m) return;
        if(m.paused) return;
        npOverlayPill.classList.add("npPillHidden");
      }catch(e){}
    }, (ms || 2500));
  }catch(e){}
}

function npPillActivity(pinned){
  const effectivePinned = !!pinned || !!npPillPinned;
  showNpPill(effectivePinned);
  if(!effectivePinned) scheduleHideNpPill(2500);
}


function showProgressBar(){
  try{
    npProgressWrap.style.display = "block";
    npVolumeWrap.style.display = "none";
  }catch(e){}
}

function showVolumeBar(){
  try{
    npProgressWrap.style.display = "none";
    npVolumeWrap.style.display = "block";
    if(npVolumeFill) npVolumeFill.style.width = Math.round(userVol * 100) + "%";
  }catch(e){}
}

function scheduleHideVolumeBar(){
  try{
    if(volBarTimer) clearTimeout(volBarTimer);
    volBarTimer = setTimeout(()=>{
      if(!seekMode && nowPlaying.style.display === "block"){
        showProgressBar();
      }
    }, 700);
  }catch(e){}
}

function resetSeekIdle(){
  try{
    if(seekIdleTimer) clearTimeout(seekIdleTimer);
    seekIdleTimer = setTimeout(()=>{
      cancelSeekMode();
    }, 2500);
  }catch(e){}
}

function updateSeekIndicator(){
  try{
    const m = wheelMedia();
    const d = (m && m.duration) ? m.duration : 0;
    if(d <= 0){
      npSeekIndicator.style.left = "0%";
      return;
    }
    const pct = Math.max(0, Math.min(1, (seekPreview || 0) / d)) * 100;
    npSeekIndicator.style.left = "calc(" + pct + "% - 1px)";
  }catch(e){}
}

function enterSeekMode(){
  if(nowPlaying.style.display !== "block") return;
  seekMode = true;
  seekChanged = false;
  showNpPill(true);
  const m = wheelMedia();
  seekPreview = (m && m.currentTime) ? m.currentTime : 0;
  showProgressBar();
  try{ npSeekIndicator.style.display = "block"; }catch(e){}
  updateSeekIndicator();
  resetSeekIdle();
  updateWheelLabels();
  scheduleHideNpPill(2000);
}

function cancelSeekMode(){
  if(!seekMode) return;
  seekMode = false;
  seekChanged = false;
  try{ if(seekIdleTimer) clearTimeout(seekIdleTimer); }catch(e){}
  seekIdleTimer = null;
  try{ npSeekIndicator.style.display = "none"; }catch(e){}
  showProgressBar();
  updateWheelLabels();
}

function commitSeekMode(){
  if(!seekMode) return;
  const m = wheelMedia();
  const d = (m && m.duration) ? m.duration : 0;
  if(d > 0){
    try{
      if(m) m.currentTime = Math.max(0, Math.min(d, seekPreview));
    }catch(e){}
  }
  cancelSeekMode();
}

function wheelLabelSvg(name, active){
  const filled = !!active;
  const icon = (b64, cls='') => '<img class="wheelSvgIcon' + (cls ? ' ' + cls : '') + '" aria-hidden="true" alt="" src="data:image/svg+xml;base64,' + b64 + '">';
  if(name === "menu") return '<span class="menuWord">MENU</span>';
  if(name === "heart") return icon(filled ? "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTE2LjQzMDcsMi43MjgwNUMyMC4wNDg1LDIuNzI4MDUgMjIuNDc5NCw2LjEyODk3IDIyLjQ3OTQsOS4zMDE2NEMyMi40Nzk0LDE1LjcyNjkgMTIuMzkwNywyMC45ODggMTIuMjA4MSwyMC45ODhDMTIuMDI1NSwyMC45ODggMS45MzY4OCwxNS43MjY5IDEuOTM2ODgsOS4zMDE2NEMxLjkzNjg4LDYuMTI4OTcgNC4zNjc3NCwyLjcyODA1IDcuOTg1NSwyLjcyODA1QzEwLjA2MjYsMi43MjgwNSAxMS40MjA3LDMuNzY2NTkgMTIuMjA4MSw0LjY3OTU4QzEyLjk5NTYsMy43NjY1OSAxNC4zNTM3LDIuNzI4MDUgMTYuNDMwNywyLjcyODA1TDE2LjQzMDcsMi43MjgwNVoiIHN0cm9rZT0iI0ZGRkZGRiIgc3Ryb2tlLXdpZHRoPSIyLjI4MjciIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbD0iI0ZGRkZGRiIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L2c+Cjwvc3ZnPgo=" : "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggc3Ryb2tlPSIjRkZGRkZGIiBzdHJva2Utd2lkdGg9IjIuMjgyNyIgZD0iTTE2LjQzMDcsMi43MjgwNUMyMC4wNDg1LDIuNzI4MDUgMjIuNDc5NCw2LjEyODk3IDIyLjQ3OTQsOS4zMDE2NEMyMi40Nzk0LDE1LjcyNjkgMTIuMzkwNywyMC45ODggMTIuMjA4MSwyMC45ODhDMTIuMDI1NSwyMC45ODggMS45MzY4OCwxNS43MjY5IDEuOTM2ODgsOS4zMDE2NEMxLjkzNjg4LDYuMTI4OTcgNC4zNjc3NCwyLjcyODA1IDcuOTg1NSwyLjcyODA1QzEwLjA2MjYsMi43MjgwNSAxMS40MjA3LDMuNzY2NTkgMTIuMjA4MSw0LjY3OTU4QzEyLjk5NTYsMy43NjY1OSAxNC4zNTM3LDIuNzI4MDUgMTYuNDMwNywyLjcyODA1TDE2LjQzMDcsMi43MjgwNVoiIGZpbGw9IiNGRkZGRkYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbC1vcGFjaXR5PSIwIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+CjwvZz4KPC9zdmc+Cg==");
  if(name === "play") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTMuMDAzMzUsMjBMMTQuMzM2NiwxMkwzLjAwMzM1LDRMMy4wMDMzNSwyMEwzLjAwMzM1LDIwWiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNMTkuMDAzNCw0TDE2LjMzNjcsNEwxNi4zMzY3LDIwTDE5LjAwMzQsMjBMMTkuMDAzNCw0TDE5LjAwMzQsNFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTIzLjcyMDksNEwyMS4wNTQyLDRMMjEuMDU0MiwyMEwyMy43MjA5LDIwTDIzLjcyMDksNEwyMy43MjA5LDRaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==", filled ? 'isActive' : 'isInactive');
  if(name === "pause") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTMuMDAzMzUsMjBMMTQuMzM2NiwxMkwzLjAwMzM1LDRMMy4wMDMzNSwyMEwzLjAwMzM1LDIwWiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNMTkuMDAzNCw0TDE2LjMzNjcsNEwxNi4zMzY3LDIwTDE5LjAwMzQsMjBMMTkuMDAzNCw0TDE5LjAwMzQsNFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTIzLjcyMDksNEwyMS4wNTQyLDRMMjEuMDU0MiwyMEwyMy43MjA5LDIwTDIzLjcyMDksNEwyMy43MjA5LDRaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==", 'isPaused');
  if(name === "shuffle") return icon(filled ? "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsNTEyLDUxMiIgc3R5bGU9ImVuYWJsZS1iYWNrZ3JvdW5kOm5ldyAwIDAgNTEyIDUxMjsiIHZlcnNpb249IjEuMSI+CjxkZWZzLz4KPGcgaWQ9ImxheWVyMCI+CjxwYXRoIGQ9Ik01MDMuODMsMzk3LjA3M0wzNzAuOTI4LDUwMy44M0w0MjcuNTc1LDM5Ny4wNzNMMzcwLjkyOCwyOTAuMzE2TDUwMy44MywzOTcuMDczWiIgZmlsbD0iI0ZFRkZGRiIvPgo8cGF0aCBkPSJNMzE2LjY1NSwxOTcuNzY4QzMxNy42MjgsMTk1LjE3OSAzMjQuNjc4LDE4OS44MDEgMzI3LjM1NCwxODkuNTVMMzYyLjc1OCwxODkuNTVMMzYyLjc1OCwyMjEuNjg2QzM2Mi43NTgsMjI0LjgzIDM2NC41NjIsMjI3LjY5NSAzNjcuMzk2LDIyOS4wNTNDMzcwLjIzMSwyMzAuNDE0IDM3My41OTIsMjMwLjAyNiAzNzYuMDQ0LDIyOC4wNTVMNTA4Ljk0NiwxMjEuMjk4QzUxMC44NzYsMTE5Ljc0OCA1MTEuOTk5LDExNy40MDYgNTExLjk5OSwxMTQuOTI5QzUxMS45OTksMTEyLjQ1MiA1MTAuODc2LDExMC4xMSA1MDguOTQ2LDEwOC41NkwzNzYuMDQ1LDEuODAxQzM3My41OTQsLTAuMTY3IDM3MC4yMzEsLTAuNTU3IDM2Ny4zOTcsMC44MDNDMzY0LjU2MiwyLjE2MyAzNjIuNzU5LDUuMDI2IDM2Mi43NTksOC4xN0wzNjIuNzU5LDQwLjMwNkwzMjcuMzU1LDQwLjMwNkMyOTMuNzExLDQwLjMwNiAyNTkuNDQzLDUyLjMxMiAyMzAuODYyLDc0LjExMkMyMDIuMjgyLDk1LjkxMiAxODEuNjQyLDEyNS43ODggMTcyLjc0NywxNTguMjM2TDE1NC40MiwyMjUuMDk4TDE0NS43MjMsMTkzLjM3QzE0My4xNCwxODMuOTUgMTI5LjA1OCwxNzMuMjA4IDExOS4yODksMTczLjIwOEwxNi4zNDEsMTczLjIwOEwxNi4zNDEsNTYuNjQ3TDExOS4yODYsNTYuNjQ3QzE0NC4zOSw1Ni42NDcgMTY5Ljc5MSw2NC4wNyAxOTIuNzQzLDc4LjExNUMxOTYuNTkyLDgwLjQ2OSAyMDEuNjIsNzkuMjU4IDIwMy45NzYsNzUuNDExQzIwNi4zMzEsNzEuNTYyIDIwNS4xMiw2Ni41MzMgMjAxLjI3MSw2NC4xNzZDMTc1Ljc1Miw0OC41NiAxNDcuNDAyLDQwLjMwNiAxMTkuMjg2LDQwLjMwNkw4LjE3MSw0MC4zMDZDMy42NTksNDAuMzA2IDAuMDAwOTk5NDUxLDQzLjk2NCAwLjAwMDk5OTQ1MSw0OC40NzZMMC4wMDA5OTk0NTEsMTgxLjM3OEMwLjAwMDk5OTQ1MSwxODUuODkxIDMuNjU5LDE4OS41NDggOC4xNzEsMTg5LjU0OEwxMTkuMjA3LDE4OS41NDZDMTIxLjk2MiwxODkuNzk5IDEyOS4wMTIsMTk1LjE3NyAxMjkuOTYyLDE5Ny42OTFMMTQ1Ljk0NiwyNTYuMDAyTDEyOS45ODUsMzE0LjIzM0MxMjkuMDEyLDMxNi44MjIgMTIxLjk2MiwzMjIuMTk5IDExOS4yODYsMzIyLjQ1MUw4LjE3MSwzMjIuNDUxQzMuNjU5LDMyMi40NTEgMC4wMDA5OTk0NTEsMzI2LjEwOCAwLjAwMDk5OTQ1MSwzMzAuNjIxTDAuMDAwOTk5NDUxLDQ2My41MjNDMC4wMDA5OTk0NTEsNDY4LjAzNiAzLjY1OSw0NzEuNjkzIDguMTcxLDQ3MS42OTNMMTE5LjI4Niw0NzEuNjkzQzE1Mi45Myw0NzEuNjkzIDE4Ny4xOTgsNDU5LjY4NyAyMTUuNzc5LDQzNy44ODdDMjQ0LjM1OSw0MTYuMDg3IDI2NC45OTksMzg2LjIxMSAyNzMuODk0LDM1My43NjNMMjg4LjgwNiwyOTkuMzYzTDMxNi42NTUsMTk3Ljc2OEwzMTYuNjU1LDE5Ny43NjhaTTIwNS44NjksNDI0Ljg5NkMxODAuMTE5LDQ0NC41MzcgMTQ5LjM2OSw0NTUuMzUzIDExOS4yODUsNDU1LjM1M0wxNi4zNDEsNDU1LjM1M0wxNi4zNDEsMzM4Ljc5MkwxMTkuMjg2LDMzOC43OTJDMTI5LjA1NSwzMzguNzkyIDE0My4xMzgsMzI4LjA1MSAxNDUuNzIyLDMxOC42MjhMMTg4LjUwNiwxNjIuNTU1QzE5Ni40NTksMTMzLjU0MiAyMTUuMDIyLDEwNi43NDcgMjQwLjc3Miw4Ny4xMDRDMjY2LjUyMSw2Ny40NjUgMjk3LjI3MSw1Ni42NDggMzI3LjM1NCw1Ni42NDhMMzcwLjkyOCw1Ni42NDhDMzc1LjQ0LDU2LjY0OCAzNzkuMDk4LDUyLjk5MSAzNzkuMDk4LDQ4LjQ3OEwzNzkuMDk4LDI1LjIxNEw0OTAuNzg0LDExNC45MjhMMzc5LjA5OCwyMDQuNjQzTDM3OS4wOTgsMTgxLjM3OUMzNzkuMDk4LDE3Ni44NjYgMzc1LjQ0LDE3My4yMDkgMzcwLjkyOCwxNzMuMjA5TDMyNy4zNTQsMTczLjIwOUMzMTcuNTg1LDE3My4yMDkgMzAzLjUwMiwxODMuOTUgMzAwLjkxOCwxOTMuMzczTDI1OC4xMzUsMzQ5LjQ0NkMyNTAuMTgxLDM3OC40NTggMjMxLjYxOSw0MDUuMjU0IDIwNS44NjksNDI0Ljg5NkwyMDUuODY5LDQyNC44OTZaIiBmaWxsPSIjRkVGRkZGIi8+CjxwYXRoIGQ9Ik0yMTAuODIzLDgwLjYwOUMxODMuNjU4LDU5Ljg4OSAxNTEuMTQ5LDQ4LjQ3NyAxMTkuMjg1LDQ4LjQ3N0w4LjE3MSw0OC40NzdMOC4xNzEsMTgxLjM3OUwxMTkuMjg2LDE4MS4zNzlDMTI1LjMyMSwxODEuMzc5IDEzNi4yNDUsMTg5LjcxMiAxMzcuODQxLDE5NS41MzJMMTgwLjYyNSwzNTEuNjA1TDI2Ni4wMTUsMTYwLjM5N0MyNTcuNTksMTI5LjY2NiAyMzcuOTksMTAxLjMzMSAyMTAuODIzLDgwLjYwOUwyMTAuODIzLDgwLjYwOVoiIGZpbGw9IiNGRUZGRkYiLz4KPHBhdGggZD0iTTUwMy44MywxMTQuOTI4TDM3MC45MjgsMjIxLjY4Nkw0MjcuNTc1LDExNC45MjhMMzcwLjkyOCw4LjE3MUw1MDMuODMsMTE0LjkyOFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTQ2MC4yNTYsMzk3LjA3M0wzNzAuOTI4LDI5MC4zMTZMMzcwLjkyOCwzMzAuNjIyTDMyNy4zNTQsMzMwLjYyMkMzMjEuNywzMzAuNjIyIDMxMS43NjUsMzIzLjMxMiAzMDkuMjE2LDMxNy42MTVMMjQ5LjYzOSw0NDAuODQ0QzI3My42Nyw0NTUuNTYxIDMwMC43Myw0NjMuNTI1IDMyNy4zNTQsNDYzLjUyNUwzNzAuOTI4LDQ2My41MjVMMzcwLjkyOCw1MDMuODMxTDQ2MC4yNTYsMzk3LjA3M0w0NjAuMjU2LDM5Ny4wNzNaIiBmaWxsPSIjRkVGRkZGIi8+CjxwYXRoIGQ9Ik0zMDkuMjE2LDMxNy42MTVMMjk3LjUyNywzNjAuMjQyQzI4OS4zMzUsMzkwLjE0NSAyNzIuNjM1LDQxOC4wNzYgMjQ5LjYzOSw0NDAuODQ0QzI0NC45LDQzNy45NTcgMjQwLjI4MSw0MzQuNzk4IDIzNS44MTUsNDMxLjM4OEMyMDguNjQ2LDQxMC42NjggMTg5LjA0OSwzODIuMzM0IDE4MC42MjgsMzUxLjYwM0wyNjYuMDEyLDE2MC4zOThMMzA4LjgwMiwzMTYuNDcxQzMwOC45LDMxNi44NDIgMzA5LjA0MSwzMTcuMjIzIDMwOS4yMTYsMzE3LjYxNUwzMDkuMjE2LDMxNy42MTVaIiBmaWxsPSIjRkZGRkZGIi8+CjxwYXRoIGQ9Ik00NjAuMjU2LDExNC45MjhMMzcwLjkyOCw4LjE3MUwzNzAuOTI4LDQ4LjQ3N0wzMjcuMzU0LDQ4LjQ3N0MyOTUuNDksNDguNDc3IDI2Mi45ODEsNTkuODg5IDIzNS44MTYsODAuNjA5QzIwOC42NDksMTAxLjMzIDE4OS4wNSwxMjkuNjY1IDE4MC42MjYsMTYwLjM5NkwxMzcuODQyLDMxNi40NjlDMTM2LjI0NiwzMjIuMjg5IDEyNS4zMjEsMzMwLjYyMiAxMTkuMjg3LDMzMC42MjJMOC4xNzEsMzMwLjYyMkw4LjE3MSw0NjMuNTI0TDExOS4yODYsNDYzLjUyNEMxNTEuMTUsNDYzLjUyNCAxODMuNjU5LDQ1Mi4xMTIgMjEwLjgyNCw0MzEuMzkyQzIzNy45OTEsNDEwLjY3MSAyNTcuNTksMzgyLjMzNiAyNjYuMDE0LDM1MS42MDVMMzA4Ljc5OCwxOTUuNTMyQzMxMC4zOTQsMTg5LjcxMiAzMjEuMzE5LDE4MS4zNzkgMzI3LjM1MywxODEuMzc5TDM3MC45MjcsMTgxLjM3OUwzNzAuOTI3LDIyMS42ODVMNDYwLjI1NiwxMTQuOTI4TDQ2MC4yNTYsMTE0LjkyOFoiIGZpbGw9IiNGRkZGRkYiLz4KPHBhdGggZD0iTTUwOC45NDcsMzkwLjcwNUwzNzYuMDQ1LDI4My45NDdDMzczLjU5NCwyODEuOTc3IDM3MC4yMzEsMjgxLjU4OSAzNjcuMzk3LDI4Mi45NDlDMzY0LjU2MiwyODQuMzA3IDM2Mi43NTksMjg3LjE3MiAzNjIuNzU5LDI5MC4zMTZMMzYyLjc1OSwzMjIuNDUxTDMyNy40MzMsMzIyLjQ1M0MzMjQuNjg3LDMyMi4yMDEgMzE3LjY2OCwzMTYuODUzIDMxNi42NjQsMzE0LjI1NkMzMTUuNDQ5LDMwOS45MzcgMzEwLjk3NSwzMDcuNDA2IDMwNi42MzksMzA4LjU4OUMzMDIuMjg3LDMwOS43ODMgMjk5LjcyNywzMTQuMjc4IDMwMC45MiwzMTguNjNDMzAzLjUwNCwzMjguMDUxIDMxNy41ODYsMzM4Ljc5MiAzMjcuMzU2LDMzOC43OTJMMzcwLjkzLDMzOC43OTJDMzc1LjQ0MiwzMzguNzkyIDM3OS4xLDMzNS4xMzUgMzc5LjEsMzMwLjYyMkwzNzkuMSwzMDcuMzU5TDQ5MC43ODYsMzk3LjA3M0wzNzkuMSw0ODYuNzg4TDM3OS4xLDQ2My41MjRDMzc5LjEsNDU5LjAxMSAzNzUuNDQyLDQ1NS4zNTQgMzcwLjkzLDQ1NS4zNTRMMzI3LjM1Niw0NTUuMzU0QzMwMi4yNTIsNDU1LjM1NCAyNzYuODUxLDQ0Ny45MzEgMjUzLjg5OSw0MzMuODg2QzI1MC4wNSw0MzEuNTMzIDI0NS4wMjEsNDMyLjc0MiAyNDIuNjY1LDQzNi41OUMyNDAuMzEsNDQwLjQzOSAyNDEuNTIxLDQ0NS40NjggMjQ1LjM3LDQ0Ny44MjVDMjcwLjg4OSw0NjMuNDQxIDI5OS4yNCw0NzEuNjk1IDMyNy4zNTUsNDcxLjY5NUwzNjIuNzU5LDQ3MS42OTVMMzYyLjc1OSw1MDMuODMxQzM2Mi43NTksNTA2Ljk3NSAzNjQuNTYzLDUwOS44NCAzNjcuMzk3LDUxMS4xOThDMzY4LjUyMSw1MTEuNzM3IDM2OS43MjcsNTEyLjAwMSAzNzAuOTI4LDUxMi4wMDFDMzcyLjc1NSw1MTIuMDAxIDM3NC41NjYsNTExLjM4OCAzNzYuMDQ2LDUxMC4yTDUwOC45NDgsNDAzLjQ0M0M1MTAuODc4LDQwMS44OTMgNTEyLjAwMSwzOTkuNTUxIDUxMi4wMDEsMzk3LjA3NEM1MTIuMDAxLDM5NC41OTcgNTEwLjg3NywzOTIuMjU0IDUwOC45NDcsMzkwLjcwNUw1MDguOTQ3LDM5MC43MDVaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==" : "PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsNTEyLDUxMiIgc3R5bGU9ImVuYWJsZS1iYWNrZ3JvdW5kOm5ldyAwIDAgNTEyIDUxMjsiIHZlcnNpb249IjEuMSI+CjxkZWZzLz4KPGcgaWQ9ImxheWVyMCI+CjxwYXRoIGQ9Ik01MDguOTQ3LDM5MC43MDVMMzc2LjA0NSwyODMuOTQ3QzM3My41OTQsMjgxLjk3NyAzNzAuMjMxLDI4MS41ODkgMzY3LjM5NywyODIuOTQ5QzM2NC41NjIsMjg0LjMwNyAzNjIuNzU5LDI4Ny4xNzIgMzYyLjc1OSwyOTAuMzE2TDM2Mi43NTksMzIyLjQ1MUwzMjcuNDMzLDMyMi40NTNDMzI0LjY4NywzMjIuMjAxIDMxNy42NjgsMzE2Ljg1MyAzMTYuNjY0LDMxNC4yNTZDMzE1LjQ0OSwzMDkuOTM3IDMxMC45NzUsMzA3LjQwNiAzMDYuNjM5LDMwOC41ODlDMzAyLjI4NywzMDkuNzgzIDI5OS43MjcsMzE0LjI3OCAzMDAuOTIsMzE4LjYzQzMwMy41MDQsMzI4LjA1MSAzMTcuNTg2LDMzOC43OTIgMzI3LjM1NiwzMzguNzkyTDM3MC45MywzMzguNzkyQzM3NS40NDIsMzM4Ljc5MiAzNzkuMSwzMzUuMTM1IDM3OS4xLDMzMC42MjJMMzc5LjEsMzA3LjM1OUw0OTAuNzg2LDM5Ny4wNzNMMzc5LjEsNDg2Ljc4OEwzNzkuMSw0NjMuNTI0QzM3OS4xLDQ1OS4wMTEgMzc1LjQ0Miw0NTUuMzU0IDM3MC45Myw0NTUuMzU0TDMyNy4zNTYsNDU1LjM1NEMzMDIuMjUyLDQ1NS4zNTQgMjc2Ljg1MSw0NDcuOTMxIDI1My44OTksNDMzLjg4NkMyNTAuMDUsNDMxLjUzMyAyNDUuMDIxLDQzMi43NDIgMjQyLjY2NSw0MzYuNTlDMjQwLjMxLDQ0MC40MzkgMjQxLjUyMSw0NDUuNDY4IDI0NS4zNyw0NDcuODI1QzI3MC44ODksNDYzLjQ0MSAyOTkuMjQsNDcxLjY5NSAzMjcuMzU1LDQ3MS42OTVMMzYyLjc1OSw0NzEuNjk1TDM2Mi43NTksNTAzLjgzMUMzNjIuNzU5LDUwNi45NzUgMzY0LjU2Myw1MDkuODQgMzY3LjM5Nyw1MTEuMTk4QzM2OC41MjEsNTExLjczNyAzNjkuNzI3LDUxMi4wMDEgMzcwLjkyOCw1MTIuMDAxQzM3Mi43NTUsNTEyLjAwMSAzNzQuNTY2LDUxMS4zODggMzc2LjA0Niw1MTAuMkw1MDguOTQ4LDQwMy40NDNDNTEwLjg3OCw0MDEuODkzIDUxMi4wMDEsMzk5LjU1MSA1MTIuMDAxLDM5Ny4wNzRDNTEyLjAwMSwzOTQuNTk3IDUxMC44NzcsMzkyLjI1NCA1MDguOTQ3LDM5MC43MDVMNTA4Ljk0NywzOTAuNzA1WiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNNTAzLjgzLDM5Ny4wNzNMMzcwLjkyOCw1MDMuODNMNDI3LjU3NSwzOTcuMDczTDM3MC45MjgsMjkwLjMxNkw1MDMuODMsMzk3LjA3M1oiIGZpbGw9IiNGRUZGRkYiIGZpbGwtb3BhY2l0eT0iMCIvPgo8cGF0aCBkPSJNMzE2LjY1NSwxOTcuNzY4QzMxNy42MjgsMTk1LjE3OSAzMjQuNjc4LDE4OS44MDEgMzI3LjM1NCwxODkuNTVMMzYyLjc1OCwxODkuNTVMMzYyLjc1OCwyMjEuNjg2QzM2Mi43NTgsMjI0LjgzIDM2NC41NjIsMjI3LjY5NSAzNjcuMzk2LDIyOS4wNTNDMzcwLjIzMSwyMzAuNDE0IDM3My41OTIsMjMwLjAyNiAzNzYuMDQ0LDIyOC4wNTVMNTA4Ljk0NiwxMjEuMjk4QzUxMC44NzYsMTE5Ljc0OCA1MTEuOTk5LDExNy40MDYgNTExLjk5OSwxMTQuOTI5QzUxMS45OTksMTEyLjQ1MiA1MTAuODc2LDExMC4xMSA1MDguOTQ2LDEwOC41NkwzNzYuMDQ1LDEuODAxQzM3My41OTQsLTAuMTY3IDM3MC4yMzEsLTAuNTU3IDM2Ny4zOTcsMC44MDNDMzY0LjU2MiwyLjE2MyAzNjIuNzU5LDUuMDI2IDM2Mi43NTksOC4xN0wzNjIuNzU5LDQwLjMwNkwzMjcuMzU1LDQwLjMwNkMyOTMuNzExLDQwLjMwNiAyNTkuNDQzLDUyLjMxMiAyMzAuODYyLDc0LjExMkMyMDIuMjgyLDk1LjkxMiAxODEuNjQyLDEyNS43ODggMTcyLjc0NywxNTguMjM2TDE1NC40MiwyMjUuMDk4TDE0NS43MjMsMTkzLjM3QzE0My4xNCwxODMuOTUgMTI5LjA1OCwxNzMuMjA4IDExOS4yODksMTczLjIwOEwxNi4zNDEsMTczLjIwOEwxNi4zNDEsNTYuNjQ3TDExOS4yODYsNTYuNjQ3QzE0NC4zOSw1Ni42NDcgMTY5Ljc5MSw2NC4wNyAxOTIuNzQzLDc4LjExNUMxOTYuNTkyLDgwLjQ2OSAyMDEuNjIsNzkuMjU4IDIwMy45NzYsNzUuNDExQzIwNi4zMzEsNzEuNTYyIDIwNS4xMiw2Ni41MzMgMjAxLjI3MSw2NC4xNzZDMTc1Ljc1Miw0OC41NiAxNDcuNDAyLDQwLjMwNiAxMTkuMjg2LDQwLjMwNkw4LjE3MSw0MC4zMDZDMy42NTksNDAuMzA2IDAuMDAwOTk5NDUxLDQzLjk2NCAwLjAwMDk5OTQ1MSw0OC40NzZMMC4wMDA5OTk0NTEsMTgxLjM3OEMwLjAwMDk5OTQ1MSwxODUuODkxIDMuNjU5LDE4OS41NDggOC4xNzEsMTg5LjU0OEwxMTkuMjA3LDE4OS41NDZDMTIxLjk2MiwxODkuNzk5IDEyOS4wMTIsMTk1LjE3NyAxMjkuOTYyLDE5Ny42OTFMMTQ1Ljk0NiwyNTYuMDAyTDEyOS45ODUsMzE0LjIzM0MxMjkuMDEyLDMxNi44MjIgMTIxLjk2MiwzMjIuMTk5IDExOS4yODYsMzIyLjQ1MUw4LjE3MSwzMjIuNDUxQzMuNjU5LDMyMi40NTEgMC4wMDA5OTk0NTEsMzI2LjEwOCAwLjAwMDk5OTQ1MSwzMzAuNjIxTDAuMDAwOTk5NDUxLDQ2My41MjNDMC4wMDA5OTk0NTEsNDY4LjAzNiAzLjY1OSw0NzEuNjkzIDguMTcxLDQ3MS42OTNMMTE5LjI4Niw0NzEuNjkzQzE1Mi45Myw0NzEuNjkzIDE4Ny4xOTgsNDU5LjY4NyAyMTUuNzc5LDQzNy44ODdDMjQ0LjM1OSw0MTYuMDg3IDI2NC45OTksMzg2LjIxMSAyNzMuODk0LDM1My43NjNMMjg4LjgwNiwyOTkuMzYzTDMxNi42NTUsMTk3Ljc2OEwzMTYuNjU1LDE5Ny43NjhaTTIwNS44NjksNDI0Ljg5NkMxODAuMTE5LDQ0NC41MzcgMTQ5LjM2OSw0NTUuMzUzIDExOS4yODUsNDU1LjM1M0wxNi4zNDEsNDU1LjM1M0wxNi4zNDEsMzM4Ljc5MkwxMTkuMjg2LDMzOC43OTJDMTI5LjA1NSwzMzguNzkyIDE0My4xMzgsMzI4LjA1MSAxNDUuNzIyLDMxOC42MjhMMTg4LjUwNiwxNjIuNTU1QzE5Ni40NTksMTMzLjU0MiAyMTUuMDIyLDEwNi43NDcgMjQwLjc3Miw4Ny4xMDRDMjY2LjUyMSw2Ny40NjUgMjk3LjI3MSw1Ni42NDggMzI3LjM1NCw1Ni42NDhMMzcwLjkyOCw1Ni42NDhDMzc1LjQ0LDU2LjY0OCAzNzkuMDk4LDUyLjk5MSAzNzkuMDk4LDQ4LjQ3OEwzNzkuMDk4LDI1LjIxNEw0OTAuNzg0LDExNC45MjhMMzc5LjA5OCwyMDQuNjQzTDM3OS4wOTgsMTgxLjM3OUMzNzkuMDk4LDE3Ni44NjYgMzc1LjQ0LDE3My4yMDkgMzcwLjkyOCwxNzMuMjA5TDMyNy4zNTQsMTczLjIwOUMzMTcuNTg1LDE3My4yMDkgMzAzLjUwMiwxODMuOTUgMzAwLjkxOCwxOTMuMzczTDI1OC4xMzUsMzQ5LjQ0NkMyNTAuMTgxLDM3OC40NTggMjMxLjYxOSw0MDUuMjU0IDIwNS44NjksNDI0Ljg5NkwyMDUuODY5LDQyNC44OTZaIiBmaWxsPSIjRkVGRkZGIi8+CjxwYXRoIGQ9Ik0yMTAuODIzLDgwLjYwOUMxODMuNjU4LDU5Ljg4OSAxNTEuMTQ5LDQ4LjQ3NyAxMTkuMjg1LDQ4LjQ3N0w4LjE3MSw0OC40NzdMOC4xNzEsMTgxLjM3OUwxMTkuMjg2LDE4MS4zNzlDMTI1LjMyMSwxODEuMzc5IDEzNi4yNDUsMTg5LjcxMiAxMzcuODQxLDE5NS41MzJMMTgwLjYyNSwzNTEuNjA1TDI2Ni4wMTUsMTYwLjM5N0MyNTcuNTksMTI5LjY2NiAyMzcuOTksMTAxLjMzMSAyMTAuODIzLDgwLjYwOUwyMTAuODIzLDgwLjYwOVoiIGZpbGw9IiNGRUZGRkYiIGZpbGwtb3BhY2l0eT0iMCIvPgo8cGF0aCBkPSJNNTAzLjgzLDExNC45MjhMMzcwLjkyOCwyMjEuNjg2TDQyNy41NzUsMTE0LjkyOEwzNzAuOTI4LDguMTcxTDUwMy44MywxMTQuOTI4WiIgZmlsbD0iI0ZGRkZGRiIgZmlsbC1vcGFjaXR5PSIwIi8+CjxwYXRoIGQ9Ik00NjAuMjU2LDM5Ny4wNzNMMzcwLjkyOCwyOTAuMzE2TDM3MC45MjgsMzMwLjYyMkwzMjcuMzU0LDMzMC42MjJDMzIxLjcsMzMwLjYyMiAzMTEuNzY1LDMyMy4zMTIgMzA5LjIxNiwzMTcuNjE1TDI0OS42MzksNDQwLjg0NEMyNzMuNjcsNDU1LjU2MSAzMDAuNzMsNDYzLjUyNSAzMjcuMzU0LDQ2My41MjVMMzcwLjkyOCw0NjMuNTI1TDM3MC45MjgsNTAzLjgzMUw0NjAuMjU2LDM5Ny4wNzNMNDYwLjI1NiwzOTcuMDczWiIgZmlsbD0iI0ZFRkZGRiIgZmlsbC1vcGFjaXR5PSIwIi8+CjxwYXRoIGQ9Ik0zMDkuMjE2LDMxNy42MTVMMjk3LjUyNywzNjAuMjQyQzI4OS4zMzUsMzkwLjE0NSAyNzIuNjM1LDQxOC4wNzYgMjQ5LjYzOSw0NDAuODQ0QzI0NC45LDQzNy45NTcgMjQwLjI4MSw0MzQuNzk4IDIzNS44MTUsNDMxLjM4OEMyMDguNjQ2LDQxMC42NjggMTg5LjA0OSwzODIuMzM0IDE4MC42MjgsMzUxLjYwM0wyNjYuMDEyLDE2MC4zOThMMzA4LjgwMiwzMTYuNDcxQzMwOC45LDMxNi44NDIgMzA5LjA0MSwzMTcuMjIzIDMwOS4yMTYsMzE3LjYxNUwzMDkuMjE2LDMxNy42MTVaIiBmaWxsPSIjRkZGRkZGIiBmaWxsLW9wYWNpdHk9IjAiLz4KPHBhdGggZD0iTTQ2MC4yNTYsMTE0LjkyOEwzNzAuOTI4LDguMTcxTDM3MC45MjgsNDguNDc3TDMyNy4zNTQsNDguNDc3QzI5NS40OSw0OC40NzcgMjYyLjk4MSw1OS44ODkgMjM1LjgxNiw4MC42MDlDMjA4LjY0OSwxMDEuMzMgMTg5LjA1LDEyOS42NjUgMTgwLjYyNiwxNjAuMzk2TDEzNy44NDIsMzE2LjQ2OUMxMzYuMjQ2LDMyMi4yODkgMTI1LjMyMSwzMzAuNjIyIDExOS4yODcsMzMwLjYyMkw4LjE3MSwzMzAuNjIyTDguMTcxLDQ2My41MjRMMTE5LjI4Niw0NjMuNTI0QzE1MS4xNSw0NjMuNTI0IDE4My42NTksNDUyLjExMiAyMTAuODI0LDQzMS4zOTJDMjM3Ljk5MSw0MTAuNjcxIDI1Ny41OSwzODIuMzM2IDI2Ni4wMTQsMzUxLjYwNUwzMDguNzk4LDE5NS41MzJDMzEwLjM5NCwxODkuNzEyIDMyMS4zMTksMTgxLjM3OSAzMjcuMzUzLDE4MS4zNzlMMzcwLjkyNywxODEuMzc5TDM3MC45MjcsMjIxLjY4NUw0NjAuMjU2LDExNC45MjhMNDYwLjI1NiwxMTQuOTI4WiIgZmlsbD0iI0ZGRkZGRiIgZmlsbC1vcGFjaXR5PSIwIi8+CjwvZz4KPC9zdmc+Cg==");
  if(name === "prev") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTIyLDE4LjM0MjlMMTMuMjU3MSwxMi4xNzE0TDIyLDZMMjIsMTguMzQyOUwyMiwxOC4zNDI5WiIgZmlsbD0iI0ZGRkZGRiIvPgo8cGF0aCBkPSJNNC41Mjg1NSwxMi4xNzE0TDEzLjI3MTUsMTguMzQyOUwxMy4yNzE1LDZMNC41Mjg1NSwxMi4xNzE0TDQuNTI4NTUsMTIuMTcxNFpNNC41Mjg1NSwxMi4xNzE0TDQuNTI4NTUsNkwyLjUyODU1LDZMMi41Mjg1NSwxOEw0LjUyODU1LDE4TDQuNTI4NTUsMTIuMTcxNEw0LjUyODU1LDEyLjE3MTRaIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiIGZpbGw9IiNGRkZGRkYiLz4KPC9nPgo8L3N2Zz4K");
  if(name === "next") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMjQsMjQiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDI0IDI0OyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTIuNTI4NTUsMTguMzQyOUwxMS4yNzE1LDEyLjE3MTRMMi41Mjg1NSw2TDIuNTI4NTUsMTguMzQyOUwyLjUyODU1LDE4LjM0MjlaIiBmaWxsPSIjRkZGRkZGIi8+CjxwYXRoIGQ9Ik0yMCwxMi4xNzE0TDExLjI1NzEsMTguMzQyOUwxMS4yNTcxLDZMMjAsMTIuMTcxNEwyMCwxMi4xNzE0Wk0yMCwxMi4xNzE0TDIwLDZMMjIsNkwyMiwxOEwyMCwxOEwyMCwxMi4xNzE0TDIwLDEyLjE3MTRaIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiIGZpbGw9IiNGRkZGRkYiLz4KPC9nPgo8L3N2Zz4K");
  if(name === "back15") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMzIsMzIiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDMyIDMyOyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTEuMDA3LDEuNDEyQzEuMjUzLDEuNDEyIDEuNTAzLDEuNTAzIDEuNzA3LDEuNzA3TDQuNjg2LDQuNjg2QzcuNTgyLDEuNzkxIDExLjU4MiwwIDE2LDBDMjQuODM3LDAgMzIsNy4xNjMgMzIsMTZDMzIsMjQuODM3IDI0LjgzNywzMiAxNiwzMkM3LjE2MywzMiAwLDI0LjgzNyAwLDE2QzAsMTUuMzIxIDAsMi40MTQgMCwyLjQxNEMwLDEuODExIDAuNDkzLDEuNDEyIDEuMDA3LDEuNDEyTDEuMDA3LDEuNDEyWk0yLDEzTDEwLjA4NiwxM0w2LjE3Nyw5LjEyOEM4LjM1LDYuMDMyIDExLjkzOSw0IDE2LDRDMjIuNjE3LDQgMjgsOS4zODMgMjgsMTZDMjgsMjIuNjE3IDIyLjYxNywyOCAxNiwyOEM5LjM4MywyOCA0LDIyLjYxNyA0LDE2QzQsMTUuMzIzIDQuMDgxLDE0LjY0NSA0LjE5MywxNEwyLDE0TDIsMTZDMiwyMy43MiA4LjI4LDMwIDE2LDMwQzIzLjcyLDMwIDMwLDIzLjcyIDMwLDE2QzMwLDguMjggMjMuNzIsMiAxNiwyQzEyLjI2LDIgOC43NDUsMy40NTYgNi4xMDEsNi4xTDQuNjg3LDcuNTE0TDIsNC44MjhMMiwxM0wyLDEzWk0xMS4yOTMsMTRMNS4xOTEsMTRDNS4wNzEsMTQuNjQyIDUsMTUuMzIzIDUsMTZDNSwyMi4wNzUgOS45MjUsMjcgMTYsMjdDMjIuMDc1LDI3IDI3LDIyLjA3NSAyNywxNkMyNyw5LjkyNSAyMi4wNzUsNSAxNiw1QzEyLjU3NCw1IDkuNTI2LDYuNTc1IDcuNTA5LDkuMDNMMTEuNjQ3LDEzLjE0NkMxMS45NjEsMTMuNDYxIDExLjczOCwxNCAxMS4yOTMsMTRMMTEuMjkzLDE0WiIgZmlsbD0iI0ZGRkZGRiIvPgo8L2c+Cjwvc3ZnPgo=");
  if(name === "forward15") return icon("PD94bWwgdmVyc2lvbj0nMS4wJyBlbmNvZGluZz0ndXRmLTgnPz4KPCEtLSBHZW5lcmF0b3I6IGltYWVuZ2luZSA2LjAgICAtLT4KPHN2ZyB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB2aWV3Qm94PSIwLDAsMzIsMzIiIHN0eWxlPSJlbmFibGUtYmFja2dyb3VuZDpuZXcgMCAwIDMyIDMyOyIgdmVyc2lvbj0iMS4xIj4KPGRlZnMvPgo8ZyBpZD0ibGF5ZXIwIj4KPHBhdGggZD0iTTMwLjk5MywxLjQxMkMzMC43NDcsMS40MTIgMzAuNDk3LDEuNTAzIDMwLjI5MywxLjcwN0wyNy4zMTQsNC42ODZDMjQuNDE4LDEuNzkxIDIwLjQxOCwwIDE2LDBDNy4xNjMsMCAwLDcuMTYzIDAsMTZDMCwyNC44MzcgNy4xNjMsMzIgMTYsMzJDMjQuODM3LDMyIDMyLDI0LjgzNyAzMiwxNkMzMiwxNS4zMjEgMzIsMi40MTQgMzIsMi40MTRDMzIsMS44MTEgMzEuNTA3LDEuNDEyIDMwLjk5MywxLjQxMkwzMC45OTMsMS40MTJaTTMwLDEzTDIxLjkxNCwxM0wyNS44MjMsOS4xMjhDMjMuNjUsNi4wMzIgMjAuMDYxLDQgMTYsNEM5LjM4Myw0IDQsOS4zODMgNCwxNkM0LDIyLjYxNyA5LjM4MywyOCAxNiwyOEMyMi42MTcsMjggMjgsMjIuNjE3IDI4LDE2QzI4LDE1LjMyMyAyNy45MTksMTQuNjQ1IDI3LjgwNywxNEwzMCwxNEwzMCwxNkMzMCwyMy43MiAyMy43MiwzMCAxNiwzMEM4LjI4LDMwIDIsMjMuNzIgMiwxNkMyLDguMjggOC4yOCwyIDE2LDJDMTkuNzQsMiAyMy4yNTUsMy40NTYgMjUuODk5LDYuMUwyNy4zMTMsNy41MTRMMzAsNC44MjhMMzAsMTNMMzAsMTNaTTIwLjcwNywxNEwyNi44MDksMTRDMjYuOTI5LDE0LjY0MiAyNywxNS4zMjMgMjcsMTZDMjcsMjIuMDc1IDIyLjA3NSwyNyAxNiwyN0M5LjkyNSwyNyA1LDIyLjA3NSA1LDE2QzUsOS45MjUgOS45MjUsNSAxNiw1QzE5LjQyNiw1IDIyLjQ3NCw2LjU3NSAyNC40OTEsOS4wM0wyMC4zNTMsMTMuMTQ2QzIwLjAzOSwxMy40NjEgMjAuMjYyLDE0IDIwLjcwNywxNEwyMC43MDcsMTRaIiBmaWxsPSIjRkZGRkZGIi8+CjwvZz4KPC9zdmc+Cg==");
  return '';
}

function setWheelLabelContent(el, html){
  try{ if(el) el.innerHTML = html || ""; }catch(e){}
}

function updateWheelLabels(){
  try{
    const lMenu = document.querySelector(".wheelLabel.wlTop, .wheelLabel.top");
    const lRev = document.querySelector(".wheelLabel.wlLeft, .wheelLabel.wlRev");
    const lFwd = document.querySelector(".wheelLabel.wlRight, .wheelLabel.wlFwd");
    const lPlay = document.querySelector(".wheelLabel.wlBottom, .wheelLabel.wlPlay");
    if(!lMenu || !lRev || !lFwd || !lPlay) return;

    if(state.current && state.current.kind === "np_playlist_add"){
      setWheelLabelContent(lMenu, "");
      setWheelLabelContent(lRev, "");
      setWheelLabelContent(lFwd, "");
      setWheelLabelContent(lPlay, "");
      lPlay.style.whiteSpace = "";
      lPlay.style.lineHeight = "";
      lPlay.style.fontSize = "";
      return;
    }

    if(nowPlaying.style.display === "block" && seekMode){
      if(!isVideoActive() && lastfmIsEnabled()){
        setWheelLabelContent(lMenu, wheelLabelSvg("heart", !!(lastfmState.lovedKnown && lastfmState.loved)));
      }else{
        setWheelLabelContent(lMenu, wheelLabelSvg("menu"));
      }
      setWheelLabelContent(lRev, wheelLabelSvg("back15"));
      setWheelLabelContent(lFwd, wheelLabelSvg("forward15"));
      if(isVideoActive()){
        const m = wheelMedia();
        setWheelLabelContent(lPlay, wheelLabelSvg((m && m.paused) ? "play" : "pause", !(m && m.paused)));
        lPlay.style.whiteSpace = "";
        lPlay.style.lineHeight = "";
        lPlay.style.fontSize = "";
      }else{
        setWheelLabelContent(lPlay, wheelLabelSvg("shuffle", !!state.shuffleEnabled));
        lPlay.style.whiteSpace = "";
        lPlay.style.lineHeight = "";
        lPlay.style.fontSize = "";
      }
    }else{
      setWheelLabelContent(lMenu, wheelLabelSvg("menu"));
      setWheelLabelContent(lRev, wheelLabelSvg("prev"));
      setWheelLabelContent(lFwd, wheelLabelSvg("next"));
      if(nowPlaying.style.display === "block"){
        const m = wheelMedia();
        setWheelLabelContent(lPlay, wheelLabelSvg((m && m.paused) ? "play" : "pause", !(m && m.paused)));
      }else if(state.now){
        const m = wheelMedia();
        const isPaused = m ? !!m.paused : !(state.serverNow && state.serverNow.playing);
        setWheelLabelContent(lPlay, wheelLabelSvg(isPaused ? "play" : "pause", !isPaused));
      }else{
        setWheelLabelContent(lPlay, wheelLabelSvg("play", false));
      }
      lPlay.style.whiteSpace = "";
      lPlay.style.lineHeight = "";
      lPlay.style.fontSize = "";
    }
  }catch(e){}
}



function adjustSeekPreview(dir){
  const m = wheelMedia();
  const d = (m && m.duration) ? m.duration : 0;
  if(d <= 0) return;
  const step = Math.max(2, d / 200);
  seekPreview = Math.max(0, Math.min(d, (seekPreview || 0) + (dir * step)));
  seekChanged = true;
  updateSeekIndicator();
  resetSeekIdle();
}




function scheduleVideoResume(targetSec){
  try{
    const tgtRaw = Number(targetSec || 0);
    if(!(tgtRaw > 0)) return;
    if(!npVideo) return;

    const startedAt = Date.now();
    const maxMs = 15000;
    let fallbackUsed = false;

    const clampTarget = ()=>{
      const d = (npVideo && isFinite(npVideo.duration)) ? Number(npVideo.duration) : 0;
      if(!(d > 0)) return null;
      const t = Math.min(Math.max(0, tgtRaw), Math.max(0, d - 0.5));
      return t;
    };

    const attempt = ()=>{
      try{
        if(!npVideo) return;
        if(Date.now() - startedAt > maxMs) return;

        const t = clampTarget();
        if(t === null){
          setTimeout(attempt, 200);
          return;
        }

        const cur = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
        if(Math.abs(cur - t) <= 1.5){
          return;
        }

        // Try direct seek first
        try{ npVideo.currentTime = t; }catch(e){}

        setTimeout(()=>{
          try{
            const cur2 = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
            if(Math.abs(cur2 - t) > 2.0 && !fallbackUsed){
              fallbackUsed = true;
              try{ resumeVideoViaSeekInputs(t); }catch(e){}
            }
          }catch(e){}
        }, 350);

        setTimeout(attempt, 800);
      }catch(e){}
    };

    // Trigger on key readiness events too
    try{
      const h = ()=>{ setTimeout(attempt, 0); };
      npVideo.addEventListener("loadedmetadata", h, {once:true});
      npVideo.addEventListener("loadeddata", h, {once:true});
      npVideo.addEventListener("canplay", h, {once:true});
      npVideo.addEventListener("canplaythrough", h, {once:true});
    }catch(e){}

    setTimeout(attempt, 250);
    setTimeout(attempt, 900);
  }catch(e){}
}

function resumeVideoViaSeekInputs(targetSec){
  try{
    if(!isVideoActive() || !npVideo) return;
    if(nowPlaying.style.display !== "block"){
      try{ showNowPlaying(true); }catch(e){}
    }

    // Ensure a clean seek mode state
    try{ if(seekMode) cancelSeekMode(); }catch(e){}

    // Enter seek mode using the same path as a center press
    try{ centerPress(); }catch(e){ try{ enterSeekMode(); }catch(e2){} }
    if(!seekMode){
      try{ enterSeekMode(); }catch(e){}
    }

    // Start preview from the actual current playback position for this video
    try{
      seekPreview = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
    }catch(e){ seekPreview = 0; }

    const startMs = Date.now();
    const maxMs = 120000;

    const tick = ()=>{
      try{
        if(!isVideoActive() || !npVideo) return;

        const d = (npVideo && isFinite(npVideo.duration)) ? Number(npVideo.duration) : 0;
        if(!(d > 0)){
          if(Date.now() - startMs < maxMs){
            setTimeout(tick, 60);
          }else{
            try{ cancelSeekMode(); }catch(e){}
          }
          return;
        }

        const tgt = Math.min(Math.max(0, Number(targetSec || 0)), Math.max(0, d - 0.5));
        const stepSec = Math.max(2, d / 200);

        if(!(isFinite(seekPreview))){
          seekPreview = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0;
        }

        let diff = tgt - (seekPreview || 0);
        if(Math.abs(diff) <= (stepSec / 2)){
          try{ centerPress(); }catch(e){ try{ commitSeekMode(); }catch(e2){} }
          try{ npVideo.play(); }catch(e){}
          return;
        }

        const dir = diff > 0 ? 1 : -1;

        // Simulate fast wheel rotation by applying many seek preview steps per tick
        const maxStepsPerTick = 120;
        const steps = Math.max(1, Math.min(maxStepsPerTick, Math.floor(Math.abs(diff) / stepSec)));

        for(let i = 0; i < steps; i++){
          adjustSeekPreview(dir);
        }

        // Continue until close enough, then commit via center press
        if(Date.now() - startMs < maxMs){
          setTimeout(tick, 10);
        }else{
          try{ cancelSeekMode(); }catch(e){}
        }
      }catch(e){
        try{ cancelSeekMode(); }catch(e2){}
      }
    };

    // Give the video a moment to start so seeking behaves like real user input
    setTimeout(tick, 250);
  }catch(e){}
}



function setVolume(v){
  userVol = Math.max(0, Math.min(1, v));
  try{ localStorage.setItem("debripod_volume", String(userVol)); }catch(e){}
  applyVolume();
}

function adjustVolumeStep(dir){
  const step = 0.03;
  setVolume(userVol + (dir * step));
  if(nowPlaying.style.display === "block" && !seekMode){
    showVolumeBar();
    scheduleHideVolumeBar();
    npPillActivity(false);
  }
}

applyVolume();

function fmtTime(sec){
    sec = Math.max(0, sec || 0);
    const m = Math.floor(sec/60);
    const s = Math.floor(sec%60);
    return m + ":" + (s<10 ? "0"+s : s);
  }

  function swapAudios(){
    activeAudio = audioMain;
    standbyAudio = null;
  }

  function canMediaSession(){
    return !!(navigator.mediaSession && window.MediaMetadata);
  }

  function ensurePlaybackAudioSession(){
    try{
      if("audioSession" in navigator && navigator.audioSession){
        if(navigator.audioSession.type !== "playback") navigator.audioSession.type = "playback";
      }
    }catch(e){}
  }

  function mediaSessionHasPrev(){
    try{
      if(isVideoActive()) return !!(Array.isArray(state.videoPlaylist) && state.videoPlaylist.length > 1 && prevVideoIndexPeek() !== null);
      return !!(Array.isArray(state.playlist) && state.playlist.length > 1 && prevIndexPeek() !== null);
    }catch(e){ return false; }
  }

  function mediaSessionHasNext(){
    try{
      if(isVideoActive()) return !!(Array.isArray(state.videoPlaylist) && state.videoPlaylist.length > 1 && nextVideoIndexPeek() !== null);
      return !!(Array.isArray(state.playlist) && state.playlist.length > 1 && nextIndexPeek() !== null);
    }catch(e){ return false; }
  }

  function syncMediaSessionPosition(){
    if(!canMediaSession()) return;
    const ms = navigator.mediaSession;
    if(!ms || typeof ms.setPositionState !== "function") return;
    try{
      const m = isVideoActive() ? npVideo : activeAudio;
      if(!m) return;
      const d = Number(m.duration || 0);
      const t = Number(m.currentTime || 0);
      const rate = Number(m.playbackRate || 1) || 1;
      if(!(d > 0) || !isFinite(d) || !isFinite(t) || !isFinite(rate)) return;
      ms.setPositionState({
        duration: d,
        playbackRate: rate,
        position: Math.max(0, Math.min(t, d))
      });
    }catch(e){}
  }

  function updateMediaSession(meta){
    if(!canMediaSession()) return;
    try{
      navigator.mediaSession.metadata = new MediaMetadata({
        title: meta.title || "",
        artist: meta.artist || "",
        album: meta.album || "",
        artwork: meta.art ? [{src: meta.art, sizes: "400x400", type: "image/jpeg"}] : []
      });
    }catch(e){}
    try{ syncMediaSessionControls(); }catch(e){}
    try{ syncMediaSessionPosition(); }catch(e){}
  }

  function setMediaActionHandler(name, handler){
    if(!canMediaSession()) return;
    try{ navigator.mediaSession.setActionHandler(name, handler); }catch(e){}
  }

  function syncMediaSessionControls(){
    if(!canMediaSession()) return;
    const ms = navigator.mediaSession;
    try{
      ms.playbackState = ((isVideoActive() ? npVideo : activeAudio) && !(isVideoActive() ? npVideo : activeAudio).paused) ? "playing" : "paused";
    }catch(e){}
    setMediaActionHandler("play", ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      if(isVideoActive()){
        try{ npVideo.play().catch(()=>{}); }catch(e){}
        return;
      }
      try{ if(standbyAudio && !standbyAudio.paused) standbyAudio.pause(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ activeAudio.play().catch(()=>{}); }catch(e){}
    });
    setMediaActionHandler("pause", ()=>{
      try{
        const m = isVideoActive() ? npVideo : activeAudio;
        if(m) m.pause();
      }catch(e){}
    });
    setMediaActionHandler("stop", ()=>{
      try{
        const m = isVideoActive() ? npVideo : activeAudio;
        if(m) m.pause();
      }catch(e){}
    });
    setMediaActionHandler("seekbackward", null);
    setMediaActionHandler("seekforward", null);
    setMediaActionHandler("seekto", null);
    setMediaActionHandler("previoustrack", mediaSessionHasPrev() ? ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      if(isVideoActive()){
        try{ playVideoPrev(); }catch(e){}
      }else{
        try{ playPrev(); }catch(e){}
      }
      setTimeout(()=>{ try{ syncMediaSessionControls(); }catch(e){} }, 50);
    } : null);
    setMediaActionHandler("nexttrack", mediaSessionHasNext() ? ()=>{
      try{ ensurePlaybackAudioSession(); }catch(e){}
      if(isVideoActive()){
        try{ playVideoNext(); }catch(e){}
      }else{
        try{ playNext(); }catch(e){}
      }
      setTimeout(()=>{ try{ syncMediaSessionControls(); }catch(e){} }, 50);
    } : null);
  }
  syncMediaSessionControls();

  // Last.fm scrobbling
  const lastfmState = {
    key: "",
    startTs: 0,
    duration: 0,
    meta: null,
    sentNow: false,
    sentScrobble: false,
    lovedKnown: false,
    loved: false
  };

  function lastfmIsEnabled(){
    return !!state.lastfmEnabled;
  }

  function lastfmTrackKey(meta){
    const a = (meta && meta.artist ? meta.artist : "").trim().toLowerCase();
    const t = (meta && meta.title ? meta.title : "").trim().toLowerCase();
    const b = (meta && meta.album ? meta.album : "").trim().toLowerCase();
    return a + "\n" + t + "\n" + b;
  }

  async function lastfmPost(path, payload){
    if(!lastfmIsEnabled()) return;
    try{
      await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {}),
        keepalive: true
      });
    }catch(e){}
  }

  async function lastfmGetLoved(meta){
    if(!lastfmIsEnabled()) return;
    try{
      const a = encodeURIComponent((meta && meta.artist) ? meta.artist : "");
      const t = encodeURIComponent((meta && meta.title) ? meta.title : "");
      const b = encodeURIComponent((meta && meta.album) ? meta.album : "");
      if(!a || !t) return;
      const js = await apiGet("/api/lastfm/loved?artist=" + a + "&title=" + t + "&album=" + b);
      if(js && js.ok){
        lastfmState.loved = !!js.loved;
        lastfmState.lovedKnown = true;
        updateWheelLabels();
      }
    }catch(e){}
  }

  async function lastfmToggleLoved(meta){
    if(!lastfmIsEnabled()) return;
    let prevKnown = false;
    let prevLoved = false;
    let havePrev = false;
    try{
      const artist = (meta && meta.artist) ? meta.artist : "";
      const title = (meta && meta.title) ? meta.title : "";
      const album = (meta && meta.album) ? meta.album : "";
      if(!artist.trim() || !title.trim()) return;

      prevKnown = !!lastfmState.lovedKnown;
      prevLoved = !!lastfmState.loved;
      havePrev = true;

      // Optimistic flip so the UI responds immediately.
      const optimistic = prevKnown ? (!prevLoved) : true;
      lastfmState.loved = optimistic;
      lastfmState.lovedKnown = true;
      updateWheelLabels();

      const res = await apiPost("/api/lastfm/toggle_loved", {artist: artist, title: title, album: album});
      const js = (res && res.json) ? res.json : null;

      if(res && res.ok && js && js.ok){
        lastfmState.loved = !!js.loved;
        lastfmState.lovedKnown = true;
        updateWheelLabels();

        // Reconcile after propagation and any metadata normalization differences.
        setTimeout(()=>{ lastfmGetLoved(meta); }, 1500);
      }else{
        // Revert if server rejected.
        lastfmState.loved = prevLoved;
        lastfmState.lovedKnown = prevKnown;
        updateWheelLabels();
      }
    }catch(e){
      if(havePrev){
        lastfmState.loved = prevLoved;
        lastfmState.lovedKnown = prevKnown;
        updateWheelLabels();
      }
    }
  }

  // Server-side playback sync (Now Playing + Recently Played)
  async function playbackPost(payload){
    try{
      await fetch("/api/playback/update", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {}),
        cache: "no-store",
        keepalive: true
      });
    }catch(e){}
  }

  async function syncPlaybackFromServer(){
    try{
      const js = await apiGet("/api/playback/snapshot");
      state.serverNow = (js && js.now) ? js.now : null;
      state.serverRecent = (js && Array.isArray(js.recent)) ? js.recent : [];
      state.serverLoaded = true;
      if(state.serverNow && state.serverNow.root_id && state.serverNow.rel){
        state.now = {rootId: state.serverNow.root_id, rel: state.serverNow.rel, media: state.serverNow.media || "", streamed: !!state.serverNow.streamed};
      }else{
        // keep local state.now if it exists; otherwise clear
        if(!state.now) state.now = null;
      }
    }catch(e){
      state.serverLoaded = false;
    }
  }

  function nowBadgeText(){
    try{
      if(isVideoActive()){
        return (npVideo && !npVideo.paused) ? "playing" : "";
      }
      if(activeAudio && !activeAudio.paused){
        return "playing";
      }
      if(state.serverNow && state.serverNow.playing){
        return "playing";
      }
      return "";
    }catch(e){
      return "";
    }
  }

  function captureNavContext(){
    const nav = {};
    try{
      if(state.root && state.root.id){
        nav.root_id = state.root.id;
        nav.root_name = state.root.name || "";
      }
      if(state.current && state.current.kind){
        nav.kind = state.current.kind;
        nav.label = state.current.label || "";
        if(state.current.kind === "folder"){
          nav.rel = state.current.rel || "";
        }else if(state.current.kind === "metatop"){
          // nothing extra
        }else if(state.current.kind === "metalist"){
          nav.level = state.current.level || "";
          nav.value = state.current.value || "";
        }
      }
      // if we're on now playing screen, try to use the last non-now view for better restore
      if(nowPlaying && nowPlaying.style.display === "block" && state.history && state.history.length){
        const v = state.history[state.history.length - 1];
        if(v && v.kind){
          nav.kind = v.kind;
          nav.label = v.label || nav.label || "";
          if(v.kind === "folder") nav.rel = v.rel || "";
          if(v.kind === "metalist"){ nav.level = v.level || ""; nav.value = v.value || ""; }
        }
      }
    }catch(e){}
    return nav;
  }

  async function openNavContext(nav){
    try{
      if(!nav || !nav.root_id){
        return;
      }
      const cfg = await loadConfig();
      const root = (cfg.roots || []).find(r => r.id === nav.root_id);
      if(!root) return;

      state.root = root;
      state.history = [];
      state.current = null;

      if(nav.kind === "folder"){
        const rel = (nav.rel || "").trim();
        if(rel){
          const segs = rel.split("/");
          state.history.push(folderViewObj(root, "", ""));
          for(let i = 0; i < segs.length - 1; i++){
            const r = segs.slice(0, i + 1).join("/");
            state.history.push(folderViewObj(root, r, segs[i]));
          }
        }
        showNowPlaying(false);
        await setView(folderViewObj(root, rel, rel ? rel.split("/").slice(-1)[0] : ""), false);
        return;
      }

      if((root.mode || "folders") === "metadata"){
        if(nav.kind === "metalist" && nav.level){
          await viewMetaList(root, nav.level, nav.value || "", nav.label || nav.level, false);
          return;
        }
        await viewMetaTop(root, false);
        return;
      }

      // fallback
      await viewFolder(root, "", "", false);
    }catch(e){}
  }

  function lastfmSendNowPlaying(){
    if(!lastfmIsEnabled()) return;
    if(lastfmState.sentNow) return;
    const m = lastfmState.meta;
    if(!m) return;
    if(!m.title || !m.artist) return;
    lastfmState.sentNow = true;
    lastfmPost("/api/lastfm/nowplaying", {
      title: m.title || "",
      artist: m.artist || "",
      album: m.album || "",
      duration: (lastfmState.duration && isFinite(lastfmState.duration)) ? Math.round(lastfmState.duration) : null
    });
  }

  function lastfmOnTrack(meta){
    if(!lastfmIsEnabled()) return;
    if(!meta) return;
    const k = lastfmTrackKey(meta);
    if(!k.trim()) return;
    if(k !== lastfmState.key){
      lastfmState.key = k;
      lastfmState.startTs = Math.floor(Date.now()/1000);
      lastfmState.sentNow = false;
      lastfmState.sentScrobble = false;
      lastfmState.lovedKnown = false;
      lastfmState.loved = false;
      lastfmGetLoved(meta);
    }
    lastfmState.meta = meta;
    const d0 = (meta.duration && isFinite(meta.duration)) ? meta.duration : 0;
    const d1 = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
    const d = d0 || d1 || 0;
    lastfmState.duration = d;
    lastfmSendNowPlaying();
  }

  function lastfmMaybeScrobble(force){
    if(!lastfmIsEnabled()) return;
    if(lastfmState.sentScrobble) return;
    const m = lastfmState.meta;
    if(!m) return;
    if(!m.title || !m.artist) return;
    const d0 = (lastfmState.duration && isFinite(lastfmState.duration)) ? lastfmState.duration : 0;
    const d1 = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
    const d = d0 || d1 || 0;
    if(!(d > 0)) return;
    if(d < 30) return;
    const t = (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0;
    const need = Math.min(240, d * 0.5);
    if(force || t >= need){
      lastfmState.sentScrobble = true;
      lastfmPost("/api/lastfm/scrobble", {
        title: m.title || "",
        artist: m.artist || "",
        album: m.album || "",
        duration: Math.round(d),
        start_ts: lastfmState.startTs || Math.floor(Date.now()/1000)
      });
    }
  }

  const state = {
    root: null,
    roots: [],
    history: [],
    current: null,
    rootView: null,
    items: [],
    sel: 0,
    playlist: [],
    playIndex: -1,
    videoPlaylist: [],
    videoIndex: -1,
    now: null,
    libSearch: {q: "", filter: "", engine: "combined", cache_key: "", result_source: "combined", last_count: 0, results: [], knaben_results: [], slsk_users: [], editField: "", editValue: ""},
    playlistCreate: {editing: false, editValue: "", submitting: false},
    playlistEdit: {rel: "", label: "", editingName: false, editNameValue: "", submitting: false},
    libTasks: {tasks: []},
    pendingLibSearch: null,
    nowMeta: null,
    serverNow: null,
    serverRecent: [],
    serverLoaded: false,
    lastfmEnabled: false,
    preloadEnabled: true,
    preloadBytes: 2097152,
    shuffleEnabled: false,
    playOrder: null,
    orderPos: 0,
    playOrderPlaylist: null,
    preloadedIndex: null,
    visualizerEnabled: visualizerEnabled,
    streamQueue: [],
    streamQueueIndex: -1
  };

  let npPlaylistReturnView = null;

  try{
    state.shuffleEnabled = (localStorage.getItem("debripod_shuffle") === "1");
  }catch(e){ state.shuffleEnabled = false; }
  applyThemeVars(defaultTheme);
  updateVisualizerState();

  let playbackLastPostTs = 0;
  let playbackLastPos = -1;
  function playbackMaybePost(media, rootId, rel, metaObj, pos, dur, playing, ev){
    const nowTs = Date.now();
    const p = (pos && isFinite(pos)) ? Number(pos) : 0;
    if(ev === "time"){
      if(nowTs - playbackLastPostTs < 2000 && Math.abs(p - playbackLastPos) < 1.0) return;
      playbackLastPostTs = nowTs;
      playbackLastPos = p;
    }else{
      playbackLastPostTs = nowTs;
      playbackLastPos = p;
    }
    const m = metaObj || {};

    // include the current playback playlist context so next/prev works when restoring from server state
    let playlistCtx = null;
    try{
      if(media === "audio" && Array.isArray(state.playlist) && state.playlist.length){
        const items = state.playlist.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: String(it.media || "audio"),
          label: it.label || "",
          streamed: !!it.streamed,
          source: it.source || "",
          ext: it.ext || "",
          quality: it.quality || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
      }else if(media === "video" && Array.isArray(state.videoPlaylist) && state.videoPlaylist.length){
        const items = state.videoPlaylist.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: String(it.media || "video"),
          label: it.label || "",
          streamed: !!it.streamed,
          source: it.source || "",
          ext: it.ext || "",
          quality: it.quality || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (state.videoIndex >= 0 ? state.videoIndex : 0)};
      }
    }catch(e){ playlistCtx = null; }
    playbackPost({
      media: media,
      root_id: rootId,
      rel: rel,
      playlist: playlistCtx,
      label: m.label || "",
      title: m.title || "",
      artist: m.artist || "",
      album: m.album || "",
      art: m.art || "",
      position: p,
      duration: (dur && isFinite(dur)) ? Number(dur) : null,
      playing: !!playing,
      nav: captureNavContext(),
      event: ev || "time",
      streamed: !!m.streamed,
      source: m.source || "",
      ext: m.ext || "",
      quality: m.quality || ""
    });
  }


  function layoutNowPlayingToLibList(){
    try{
      const screen = document.querySelector(".ipodScreen");
      if(!screen || !nowPlaying || !libList) return;
      const sr = screen.getBoundingClientRect();
      const lr = libList.getBoundingClientRect();
      const pad = 2; // keep libList border visible
      const left = (lr.left - sr.left) + pad;
      const top = (lr.top - sr.top) + pad;
      const w = lr.width - (pad * 2);
      const h = lr.height - (pad * 2);
      nowPlaying.style.left = Math.max(0, left) + "px";
      nowPlaying.style.top = Math.max(0, top) + "px";
      nowPlaying.style.width = Math.max(0, w) + "px";
      nowPlaying.style.height = Math.max(0, h) + "px";
      nowPlaying.style.right = "auto";
      nowPlaying.style.bottom = "auto";
      nowPlaying.style.borderRadius = "20px";
    }catch(e){}
  }

  function resetNowPlayingLayout(){
    try{
      if(!nowPlaying) return;
      nowPlaying.style.left = "";
      nowPlaying.style.top = "";
      nowPlaying.style.width = "";
      nowPlaying.style.height = "";
      nowPlaying.style.right = "";
      nowPlaying.style.bottom = "";
      nowPlaying.style.borderRadius = "";
    }catch(e){}
  }

  function waitNowPlayingFade(ms){
    return new Promise(resolve=> setTimeout(resolve, ms || 220));
  }

  function showNowPlaying(on){
    const fadeMs = 220;
    try{ if(libList) libList.style.display = "block"; }catch(e){}
    try{
      if(npPageFadeTimer){
        clearTimeout(npPageFadeTimer);
        npPageFadeTimer = null;
      }
    }catch(e){}
    npPageFadeToken += 1;
    const fadeToken = npPageFadeToken;

    if(on){
      try{ libList.classList.add("npUnderlay"); }catch(e){}
      layoutNowPlayingToLibList();
      nowPlaying.style.display = "block";
      try{ nowPlaying.classList.remove("npPageActive"); }catch(e){}
      updateVisualizerState();
      requestAnimationFrame(()=>{
        requestAnimationFrame(()=>{
          try{
            if(fadeToken !== npPageFadeToken) return;
            nowPlaying.classList.add("npPageActive");
          }catch(e){}
        });
      });
      npPillActivity(false);
    }else{
      try{ libList.classList.remove("npUnderlay"); }catch(e){}
      try{ nowPlaying.classList.remove("npPageActive"); }catch(e){}
      npPageFadeTimer = setTimeout(()=>{
        try{
          if(fadeToken !== npPageFadeToken) return;
          nowPlaying.style.display = "none";
          resetNowPlayingLayout();
          if(npOverlayPill) npOverlayPill.classList.add("npPillHidden");
        }catch(e){}
        npPageFadeTimer = null;
      }, fadeMs);
      try{ if(npPillHideTimer) clearTimeout(npPillHideTimer); }catch(e){}
      npPillHideTimer = null;
    }
    if(!on){
      stopVideoOverlay();
      try{ if(volBarTimer) clearTimeout(volBarTimer); }catch(e){}
      volBarTimer = null;
    }
    cancelSeekMode();
    showProgressBar();
  }

  function syncWheelZoneHeight(){
    try{
      const wrapEl = document.getElementById("divwrap") || document.querySelector(".wrap");
      const screenEl = document.querySelector("#tab-library .ipodScreen");
      const wheelZoneEl = document.getElementById("wheelZone") || document.querySelector("#tab-library .wheelZone");
      if(!wrapEl || !screenEl || !wheelZoneEl) return;
      const wrapRect = wrapEl.getBoundingClientRect();
      const screenRect = screenEl.getBoundingClientRect();
      const rootStyle = getComputedStyle(document.documentElement);
      const wheelSize = parseFloat(rootStyle.getPropertyValue("--wheelSize")) || 0;
      const wheelGap = parseFloat(rootStyle.getPropertyValue("--wheelGap")) || 0;
      const minNeeded = Math.ceil(wheelSize + (wheelGap * 2));
      const available = Math.max(0, Math.round(wrapRect.bottom - screenRect.bottom));
      const target = Math.max(available, minNeeded);
      wheelZoneEl.style.height = target + "px";
      wheelZoneEl.style.minHeight = target + "px";
      wheelZoneEl.style.flex = "0 0 " + target + "px";
    }catch(e){}
  }


  window.addEventListener("resize", ()=>{
    try{ syncWheelZoneHeight(); }catch(e){}
    try{
      if(nowPlaying && nowPlaying.style.display === "block"){
        layoutNowPlayingToLibList();
      }
    }catch(e){}
  });

  function bringToNowPlayingIfPlaying(){
    if(!state.now) return;
    if(activeAudio && !activeAudio.paused){
      setTab("library");
      showNowPlaying(true);
    }
  }

  window.addEventListener("focus", bringToNowPlayingIfPlaying);
  document.addEventListener("visibilitychange", ()=>{
    if(document.hidden){
      try{ saveResumeNowPlaying(); }catch(e){}
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
    }else{
      bringToNowPlayingIfPlaying();
      try{ ensurePlaybackAudioSession(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
    }
  });

  window.addEventListener("pagehide", ()=>{
    try{ saveResumeNowPlaying(); }catch(e){}
  });

  window.addEventListener("beforeunload", ()=>{
    try{ saveResumeNowPlaying(); }catch(e){}
  });

  function saveResumeNowPlaying(){
    if(!state.now) return;
    try{
      localStorage.setItem("debripod_tab", "library");
      localStorage.setItem("debripod_resume_np", JSON.stringify({rootId: state.now.rootId, rel: state.now.rel, playing: (activeAudio && !activeAudio.paused), ts: Date.now()}));
    }catch(e){}
  }

  function encodeRel(rel){
    return (rel||"").split("\\").join("/").split("/").map(encodeURIComponent).join("/");
  }

  function escapeHtml(s){
    const str = String(s ?? "");
    return str
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }


  async function apiGet(url){
    const r = await fetch(url, {cache:"no-store"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  }

  async function loadConfig(){
    const js = await apiGet("/api/library/config");
        state.preloadEnabled = !!js.preload_enabled;
    state.preloadBytes = js.preload_bytes || state.preloadBytes;
    state.roots = js.roots || [];
    state.lastfmEnabled = !!js.lastfm_enabled;
    return js;
  }

  function headerText(){
    const parts = [];
    if(state.root && state.root.name) parts.push(state.root.name);
    for(const v of state.history){
      if(v && v.label) parts.push(v.label);
    }
    if(state.current && state.current.label) parts.push(state.current.label);
    return parts.length ? parts.join(" > ") : "Library";
  }

  function setHeader(){
    libHeader.textContent = headerText();
    try{ pathPillActivity(false); }catch(e){}
    try{
      const k = state.current ? state.current.kind : "";
      if(k !== "libsearch" && k !== "libsearch_files"){
        libControlsHide();
      }
    }catch(e){}
  }

  function beginPlaylistCreateEdit(){
    try{
      if(!state.playlistCreate) state.playlistCreate = {editing:false, editValue:"", submitting:false};
      if(state.playlistCreate.submitting) return;
      state.playlistCreate.editing = true;
      if(typeof state.playlistCreate.editValue !== "string") state.playlistCreate.editValue = "";
      renderList();
    }catch(e){}
  }

  function beginSmartPlaylistCreateEdit(){
    try{
      if(!state.smartPlaylistCreate) state.smartPlaylistCreate = {editing:false, editValue:"", submitting:false};
      if(state.smartPlaylistCreate.submitting) return;
      state.smartPlaylistCreate.editing = true;
      if(typeof state.smartPlaylistCreate.editValue !== "string") state.smartPlaylistCreate.editValue = "";
      renderList();
    }catch(e){}
  }

  async function closeNowPlayingPlaylistMode(){
    try{
      const prev = npPlaylistReturnView;
      npPlaylistReturnView = null;
      if(prev){
        await runLibraryPageTransition(async ()=>{
          state.current = prev;
          setHeader();
          await prev.load();
        });
      }
    }catch(e){}
    showNowPlaying(true);
    updateWheelLabels();
  }

  async function addCurrentNowPlayingTrackToPlaylist(playlistRel){
    const cur = state.current || {};
    const root = cur.root || null;
    const trackRel = String(cur.trackRel || "");
    const rel = String(playlistRel || "");
    if(!root || !root.id || !trackRel || !rel) return false;
    const res = await apiPost("/api/library/playlist_add", {root_id: root.id, rel: rel, tracks: [trackRel]});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      if(js && js.error && String(js.error) === "No songs added"){
        return true;
      }
      throw new Error((js && js.error) ? js.error : "Failed to add song");
    }
    return true;
  }

  async function viewNowPlayingPlaylistMode(){
    const currentNow = state.now || null;
    const currentMedia = String((currentNow && currentNow.media) || (isVideoActive() ? "video" : "audio"));
    if(!currentNow || currentMedia !== "audio" || !currentNow.rootId || !currentNow.rel){
      return;
    }
    let root = null;
    try{
      if(!state.roots || !state.roots.length){
        await loadConfig();
      }
      root = (state.roots || []).find(r => r && r.id === currentNow.rootId) || null;
    }catch(e){ root = null; }
    if(!root) return;
    const alreadyInMode = !!(state.current && state.current.kind === "np_playlist_add");
    const existingAdded = (state.current && state.current.kind === "np_playlist_add" && state.current._added instanceof Set) ? state.current._added : new Set();
    if(!alreadyInMode){
      snapshotListState();
      npPlaylistReturnView = state.current || null;
    }
    const view = {
      kind: "np_playlist_add",
      label: "Add to playlist",
      root: root,
      trackRel: String(currentNow.rel || ""),
      _added: existingAdded,
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=playlists&value=");
        const items = [
          {kind:"np_playlist_close", label:"Close"},
          {kind:"playlist_create", label:"Create playlist"},
          {kind:"smart_playlist_create", label:"Create smart playlist"}
        ];
        const all = Array.isArray(js.items) ? js.items : [];
        const playlistItems = all.filter(it => it && String(it.kind || "") === "playlist" && !it.smart);
        for(const it of playlistItems){
          const rel = String(it.rel || "");
          const added = !!(this._added && this._added.has(rel));
          items.push({
            kind:"np_playlist_entry",
            label:String(it.label || "Playlist"),
            rel:rel,
            root:root,
            selectable:true,
            selected:added,
            pills:[{text: added ? "✓" : "+", _selectPill:true}]
          });
        }
        if(!playlistItems.length){
          items.push({kind:"info", label:"No playlists found"});
        }
        resetList(items);
      }
    };
    state.current = view;
    setHeader();
    resetList([
      {kind:"np_playlist_close", label:"Close"},
      {kind:"playlist_create", label:"Create playlist"},
          {kind:"smart_playlist_create", label:"Create smart playlist"},
      {kind:"info", label:"Loading playlists..."}
    ]);
    showNowPlaying(false);
    await runLibraryPageTransition(async ()=>{
      await view.load();
    });
    updateWheelLabels();
  }

  async function submitPlaylistCreate(rawName){
    try{
      if(!state.playlistCreate) state.playlistCreate = {editing:false, editValue:"", submitting:false};
      const name = String(rawName || "").trim();
      const root = state.current && state.current.root ? state.current.root : null;
      if(!root || !root.id){
        state.playlistCreate.submitting = false;
        return;
      }
      state.playlistCreate.submitting = true;
      const res = await apiPost("/api/library/playlist_create", {root_id: root.id, name: name});
      const js = (res && res.json) ? res.json : {};
      state.playlistCreate.submitting = false;
      state.playlistCreate.editing = false;
      state.playlistCreate.editValue = "";
      if(!res || !res.ok || !js.ok){
        if(js && js.error){
          alert(String(js.error));
        }
        renderList();
        return;
      }
      if(state.current && state.current.kind === "np_playlist_add"){
        await viewNowPlayingPlaylistMode();
        try{
          const wantRel = String(js.rel || "");
          if(wantRel){
            const idx = state.items.findIndex(x => x && x.kind === "np_playlist_entry" && x.rel === wantRel);
            if(idx >= 0){
              state.sel = idx;
              renderList();
            }
          }
        }catch(e){}
        return;
      }
      await viewMetaList(root, "playlists", "", "Playlists", false);
      try{
        const wantRel = String(js.rel || "");
        if(wantRel){
          const idx = state.items.findIndex(x => x && x.kind === "playlist" && x.rel === wantRel);
          if(idx >= 0){
            state.sel = idx;
            renderList();
          }
        }
      }catch(e){}
    }catch(e){
      try{ state.playlistCreate.submitting = false; }catch(e2){}
      try{ state.playlistCreate.editing = false; state.playlistCreate.editValue = ""; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  async function submitSmartPlaylistCreate(rawName){
    try{
      if(!state.smartPlaylistCreate) state.smartPlaylistCreate = {editing:false, editValue:"", submitting:false};
      const name = String(rawName || "").trim();
      const root = state.current && state.current.root ? state.current.root : null;
      if(!root || !root.id){
        state.smartPlaylistCreate.submitting = false;
        return;
      }
      state.smartPlaylistCreate.submitting = true;
      const res = await apiPost("/api/library/smart_playlist_create", {root_id: root.id, name: name});
      const js = (res && res.json) ? res.json : {};
      state.smartPlaylistCreate.submitting = false;
      state.smartPlaylistCreate.editing = false;
      state.smartPlaylistCreate.editValue = "";
      if(!res || !res.ok || !js.ok){
        if(js && js.error) alert(String(js.error));
        renderList();
        return;
      }
      if(state.current && state.current.kind === "np_playlist_add"){
        await viewNowPlayingPlaylistMode();
        return;
      }
      await viewMetaList(root, "playlists", "", "Playlists", false);
      try{
        const wantRel = String(js.rel || "");
        if(wantRel){
          const idx = state.items.findIndex(x => x && x.kind === "playlist" && x.rel === wantRel);
          if(idx >= 0){
            state.sel = idx;
            renderList();
          }
        }
      }catch(e){}
    }catch(e){
      try{ state.smartPlaylistCreate.submitting = false; }catch(e2){}
      try{ state.smartPlaylistCreate.editing = false; state.smartPlaylistCreate.editValue = ""; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  function isSmartPlaylistRel(rel){
    const v = String(rel || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "").toLowerCase();
    return v === "debripod-smartplaylists" || v.startsWith("debripod-smartplaylists/");
  }

  async function viewSmartPlaylistRules(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    await setView({
      kind: "smart_playlist_rules",
      label: "Edit rules",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      load: async function(){
        const js = await apiGet("/api/library/smart_playlist_rules?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.playlistRel || ""));
        if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
        state.smartPlaylistRules.text = String(js.text || "");
        state.smartPlaylistRules.saving = false;
        resetList([
          {kind:"smart_playlist_rules_text", label:"Rules"},
          {kind:"smart_playlist_rules_save", label:"Save rules"},
          {kind:"smart_playlist_rules_cancel", label:"Back"},
          {kind:"smart_playlist_rules_delete", label:"Delete playlist"}
        ]);
      }
    }, !!push);
  }

  async function saveSmartPlaylistRules(){
    const cur = state.current || {};
    if(cur.kind !== "smart_playlist_rules" || !cur.root || !cur.root.id) return;
    if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
    state.smartPlaylistRules.saving = true;
    try{
      const res = await apiPost("/api/library/smart_playlist_rules", {root_id: cur.root.id, rel: cur.playlistRel || "", text: String(state.smartPlaylistRules.text || "")});
      const js = (res && res.json) ? res.json : {};
      state.smartPlaylistRules.saving = false;
      if(!res || !res.ok || !js.ok){
        alert(String((js && js.error) ? js.error : "Failed to save rules"));
        renderList();
        return;
      }
      await goBack();
    }catch(e){
      state.smartPlaylistRules.saving = false;
      alert(String(e && e.message ? e.message : e));
      try{ renderList(); }catch(e2){}
    }
  }


  function beginPlaylistRenameEdit(){
    try{
      const cur = state.current || {};
      if(cur.kind !== "playlist_edit_menu") return;
      if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
      if(state.playlistEdit.submitting) return;
      state.playlistEdit.rel = String(cur.playlistRel || state.playlistEdit.rel || "");
      state.playlistEdit.label = String(cur.playlistLabel || state.playlistEdit.label || "");
      state.playlistEdit.editingName = true;
      if(typeof state.playlistEdit.editNameValue !== "string" || !state.playlistEdit.editNameValue){
        state.playlistEdit.editNameValue = state.playlistEdit.label || "";
      }
      renderList();
    }catch(e){}
  }

  async function submitPlaylistRename(rawName){
    try{
      if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
      const cur = state.current || {};
      const root = cur.root || null;
      const playlistRel = String(cur.playlistRel || state.playlistEdit.rel || "");
      const name = String(rawName || "").trim();
      if(!root || !root.id || !playlistRel){
        state.playlistEdit.submitting = false;
        return;
      }
      state.playlistEdit.submitting = true;
      const res = await apiPost("/api/library/playlist_rename", {root_id: root.id, rel: playlistRel, name: name});
      const js = (res && res.json) ? res.json : {};
      state.playlistEdit.submitting = false;
      if(!res || !res.ok || !js.ok){
        if(js && js.error){
          alert(String(js.error));
        }
        renderList();
        return;
      }
      const newRel = String(js.rel || playlistRel);
      const newLabel = String(js.label || name || state.playlistEdit.label || "Playlist");
      state.playlistEdit.rel = newRel;
      state.playlistEdit.label = newLabel;
      state.playlistEdit.editNameValue = newLabel;
      state.playlistEdit.editingName = false;
      if(state.current && state.current.kind === "playlist_edit_menu"){
        state.current.playlistRel = newRel;
        state.current.playlistLabel = newLabel;
      }
      try{
        for(const h of (state.history || [])){
          if(h && h.kind === "metalist" && h.level === "playlist_tracks" && String(h.value || "") === playlistRel){
            h.value = newRel;
            h.label = newLabel;
          }
        }
      }catch(e){}
      renderList();
    }catch(e){
      try{ state.playlistEdit.submitting = false; }catch(e2){}
      try{ alert(String(e && e.message ? e.message : e)); }catch(e2){}
      try{ renderList(); }catch(e2){}
    }
  }

  async function viewPlaylistEditMenu(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    await setView({
      kind: "playlist_edit_menu",
      label: "Edit",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      load: async function(){
        if(!state.playlistEdit) state.playlistEdit = {rel:"", label:"", editingName:false, editNameValue:"", submitting:false};
        state.playlistEdit.rel = String(this.playlistRel || "");
        state.playlistEdit.label = String(this.playlistLabel || "");
        state.playlistEdit.editingName = false;
        state.playlistEdit.submitting = false;
        state.playlistEdit.editNameValue = state.playlistEdit.label || "";
        if(isSmartPlaylistRel(this.playlistRel || "")){
          resetList([
            {kind:"smart_playlist_rules_entry", label:"Edit rules"}
          ]);
        }else{
          resetList([
            {kind:"playlist_edit_name", label:"Edit name"},
            {kind:"playlist_edit_add", label:"Add songs"},
            {kind:"playlist_edit_remove", label:"Remove songs"},
            {kind:"playlist_edit_delete", label:"Delete playlist"}
          ]);
        }
      }
    }, !!push);
  }



  async function viewPlaylistDeleteConfirm(root, playlistRel, playlistLabel, returnKind, push){
    showNowPlaying(false);
    await setView({
      kind: "playlist_delete_confirm",
      label: "Delete",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      returnKind: returnKind || "",
      load: async function(){
        resetList([
          {kind:"info", label:"Are you sure?"},
          {kind:"playlist_delete_no", label:"No"},
          {kind:"playlist_delete_yes", label:"Yes"}
        ]);
      }
    }, !!push);
  }

  async function confirmDeletePlaylist(){
    const cur = state.current || {};
    if(cur.kind !== "playlist_delete_confirm" || !cur.root || !cur.root.id) return;
    try{
      const res = await apiPost("/api/library/playlist_delete", {root_id: cur.root.id, rel: cur.playlistRel || ""});
      const js = (res && res.json) ? res.json : {};
      if(!res || !res.ok || !js.ok){
        alert(String((js && js.error) ? js.error : "Failed to delete playlist"));
        return;
      }
      state.history = [];
      await viewMetaList(cur.root, "playlists", "", "Playlists", false);
    }catch(e){
      alert(String(e && e.message ? e.message : e));
    }
  }

  async function playlistAddSongsToCurrentView(rels){
    const cur = state.current || {};
    const root = cur.root || null;
    const playlistRel = String(cur.playlistRel || "");
    if(!root || !root.id || !playlistRel) return false;
    const clean = Array.isArray(rels) ? rels.map(x=>String(x || "")).filter(Boolean) : [];
    if(!clean.length) return false;
    const res = await apiPost("/api/library/playlist_add", {root_id: root.id, rel: playlistRel, tracks: clean});
    const js = (res && res.json) ? res.json : {};
    if(!res || !res.ok || !js.ok){
      throw new Error((js && js.error) ? js.error : "Failed to add songs");
    }
    return true;
  }


  function playlistBrowseStartRel(playlistRel){
    const rel = String(playlistRel || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if(!rel) return "";
    const lower = rel.toLowerCase();
    if(lower === "debripod-playlists" || lower.startsWith("debripod-playlists/") || lower === "debripod-smartplaylists" || lower.startsWith("debripod-smartplaylists/")){
      return "";
    }
    const idx = rel.lastIndexOf("/");
    if(idx < 0) return "";
    const out = rel.slice(0, idx).replace(/^\/+|\/+$/g, "");
    if(!out || out.toLowerCase() === "debripod-playlists") return "";
    return out;
  }

  async function viewPlaylistAddSongs(root, playlistRel, rel, push){
    showNowPlaying(false);
    const prevAdded = (state.current && state.current.kind === "playlist_add" && state.current._added instanceof Set) ? state.current._added : null;
    await setView({
      kind: "playlist_add",
      label: "Add songs",
      root: root,
      playlistRel: playlistRel || "",
      rel: rel || "",
      _added: prevAdded || new Set(),
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel || "");
        const js = await apiGet(url);
        const items = [];
        if(this.rel){
          items.push({kind:"up", label:".."});
        }
        const dirs = [];
        const songs = [];
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            dirs.push({kind:"playlist_add_dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file" && e.media === "audio"){
            const relv = String(e.rel || "");
            const added = !!(this._added && this._added.has(relv));
            songs.push({kind:"playlist_add_file", label:e.name, rel:relv, root:root, media:"audio", selectable:true, selected:added});
          }
        }
        if(songs.length){
          const addedCount = songs.filter(x => x && x.selected).length;
          items.push({kind:"playlist_add_selectall", label:"Select all", badge: addedCount ? (String(addedCount) + " added") : String(songs.length)});
        }
        for(const d of dirs) items.push(d);
        for(const s of songs) items.push(s);
        if(!dirs.length && !songs.length){
          items.push({kind:"info", label:"No songs found"});
        }
        resetList(items);
      }
    }, !!push);
  }

  function refreshPlaylistRemoveSelectionUI(){
    const cur = state.current || {};
    if(!cur || cur.kind !== "playlist_remove") return;
    const selected = (cur.selected instanceof Set) ? cur.selected : new Set();
    let trackCount = 0;
    let selectedCount = 0;
    for(const it of (state.items || [])){
      if(!it) continue;
      if(it.kind === "playlist_remove_track"){
        trackCount += 1;
        const relv = String(it.rel || "");
        const on = !!(relv && selected.has(relv));
        it.selected = on;
        if(on) selectedCount += 1;
      }else if(it.kind === "playlist_remove_selectall"){
        it.badge = selectedCount ? String(selectedCount) : (trackCount ? String(trackCount) : "");
      }else if(it.kind === "playlist_remove_commit"){
        it.badge = selectedCount ? String(selectedCount) : "";
      }
    }
    renderList();
  }

  async function viewPlaylistRemoveSongs(root, playlistRel, playlistLabel, push){
    showNowPlaying(false);
    const prevSelected = (state.current && state.current.kind === "playlist_remove" && state.current.selected instanceof Set) ? state.current.selected : null;
    await setView({
      kind: "playlist_remove",
      label: "Remove songs",
      root: root,
      playlistRel: playlistRel || "",
      playlistLabel: playlistLabel || "",
      selected: prevSelected || new Set(),
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=playlist_tracks&value=" + encodeURIComponent(this.playlistRel || ""));
        const items = [];
        const tracks = [];
        for(const it of (js.items || [])){
          if(!it || it.kind !== "track") continue;
          const relv = String(it.rel || "");
          tracks.push({kind:"playlist_remove_track", label:String(it.label || "Track"), rel:relv, root:root, badge:String(it.badge || ""), selectable:true, selected:!!(this.selected && this.selected.has(relv))});
        }
        if(tracks.length){
          items.push({kind:"playlist_remove_selectall", label:"Select all", badge:(this.selected && this.selected.size) ? String(this.selected.size) : ""});
          items.push({kind:"playlist_remove_commit", label:"Remove selected", badge:(this.selected && this.selected.size) ? String(this.selected.size) : ""});
        }
        for(const tr of tracks) items.push(tr);
        if(!tracks.length){
          items.push({kind:"info", label:"No songs found"});
        }
        resetList(items);
      }
    }, !!push);
  }

  function renderList(){
    const prevScroll = (libList ? libList.scrollTop : 0);
    let editInputToFocus = null;
    libList.innerHTML = "";
    for(let i=0;i<state.items.length;i++){
      const it = state.items[i];
      const li = document.createElement("li");

      const isSel = (i === state.sel);
      const twoLine = (it.kind === "libsearch_result" || it.kind === "libsearch_file" || it.kind === "libtask_file");
      li.className = "ipodItem" + (isSel ? " sel" : "") + (it.kind === "info" ? " info" : "") + (it.kind === "random" ? " random" : "") + (twoLine ? " twoLine" : "");

      if(it.kind === "smart_playlist_rules_text"){
        li.className += " editing";
        const ta = document.createElement("textarea");
        ta.className = "libInlineInput";
        ta.style.minHeight = "220px";
        ta.style.height = "220px";
        ta.style.whiteSpace = "pre";
        ta.value = (state.smartPlaylistRules && typeof state.smartPlaylistRules.text === "string") ? state.smartPlaylistRules.text : "";
        ta.placeholder = "Enter smart playlist rules";
        ta.addEventListener("input", ()=>{
          try{
            if(!state.smartPlaylistRules) state.smartPlaylistRules = {text:"", saving:false};
            state.smartPlaylistRules.text = ta.value || "";
          }catch(e){}
        });
        li.appendChild(ta);
        editInputToFocus = ta;
        libList.appendChild(li);
        continue;
      }

      // Special inline input rows for Library search query/filter and playlist creation
      if(it.kind === "libsearch_query" || it.kind === "libsearch_filter" || it.kind === "playlist_create" || it.kind === "smart_playlist_create" || it.kind === "playlist_edit_name"){
        const isPlaylistCreate = (it.kind === "playlist_create");
        const isSmartPlaylistCreate = (it.kind === "smart_playlist_create");
        const isPlaylistRename = (it.kind === "playlist_edit_name");
        const field = (isPlaylistCreate || isSmartPlaylistCreate || isPlaylistRename) ? "name" : ((it.kind === "libsearch_filter") ? "filter" : "q");
        const placeholder = isPlaylistCreate ? "Create playlist" : (isSmartPlaylistCreate ? "Create smart playlist" : (isPlaylistRename ? "Edit name" : ((it.kind === "libsearch_filter") ? "Enter filters" : "Enter query")));
        const isEditing = (isPlaylistCreate || isSmartPlaylistCreate)
          ? !!(isSel && (isSmartPlaylistCreate ? state.smartPlaylistCreate : state.playlistCreate) && (isSmartPlaylistCreate ? state.smartPlaylistCreate.editing : state.playlistCreate.editing))
          : (isPlaylistRename ? !!(isSel && state.playlistEdit && state.playlistEdit.editingName) : !!(isSel && state.libSearch && state.libSearch.editField === field));
        if(isEditing){
          li.className += " editing";
          const inp = document.createElement("input");
          inp.type = "text";
          inp.className = "libInlineInput";
          inp.value = isPlaylistCreate
            ? ((state.playlistCreate && typeof state.playlistCreate.editValue === "string") ? state.playlistCreate.editValue : "")
            : (isSmartPlaylistCreate
                ? ((state.smartPlaylistCreate && typeof state.smartPlaylistCreate.editValue === "string") ? state.smartPlaylistCreate.editValue : "")
            : (isPlaylistRename
                ? ((state.playlistEdit && typeof state.playlistEdit.editNameValue === "string") ? state.playlistEdit.editNameValue : "")
                : ((state.libSearch && typeof state.libSearch.editValue === "string") ? state.libSearch.editValue : ((state.libSearch && typeof state.libSearch[field] === "string") ? state.libSearch[field] : ""))));
          inp.placeholder = placeholder;
          inp.addEventListener("input", ()=>{
            try{
              if(isPlaylistCreate){
                if(!state.playlistCreate) return;
                state.playlistCreate.editValue = inp.value || "";
              }else if(isSmartPlaylistCreate){
                if(!state.smartPlaylistCreate) return;
                state.smartPlaylistCreate.editValue = inp.value || "";
              }else if(isPlaylistRename){
                if(!state.playlistEdit) return;
                state.playlistEdit.editNameValue = inp.value || "";
              }else{
                if(!state.libSearch) return;
                state.libSearch.editValue = inp.value || "";
                state.libSearch[field] = inp.value || "";
              }
            }catch(e){}
          });
          inp.addEventListener("keydown", (ev)=>{
            if(ev.key === "Enter"){
              ev.preventDefault();
              if(isPlaylistCreate){
                try{
                  if(state.playlistCreate){
                    state.playlistCreate.editValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitPlaylistCreate(inp.value || ""); }catch(e){}
              }else if(isSmartPlaylistCreate){
                try{
                  if(state.smartPlaylistCreate){
                    state.smartPlaylistCreate.editValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitSmartPlaylistCreate(inp.value || ""); }catch(e){}
              }else if(isPlaylistRename){
                try{
                  if(state.playlistEdit){
                    state.playlistEdit.editNameValue = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                try{ submitPlaylistRename(inp.value || ""); }catch(e){}
              }else{
                try{
                  if(state.libSearch){
                    state.libSearch.editValue = inp.value || "";
                    state.libSearch[field] = inp.value || "";
                  }
                }catch(e){}
                try{ inp.blur(); }catch(e){}
                if(field === "q") {
                  try{ libDoSearch((state.libSearch && state.libSearch.engine) ? state.libSearch.engine : "combined", inp.value || ""); }catch(e){}
                }
              }
              return;
            }
            if(ev.key === "Escape"){
              ev.preventDefault();
              if(isPlaylistCreate){
                try{
                  if(state.playlistCreate){
                    state.playlistCreate.editing = false;
                    state.playlistCreate.editValue = "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else if(isSmartPlaylistCreate){
                try{
                  if(state.smartPlaylistCreate){
                    state.smartPlaylistCreate.editing = false;
                    state.smartPlaylistCreate.editValue = "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else if(isPlaylistRename){
                try{
                  if(state.playlistEdit){
                    state.playlistEdit.editingName = false;
                    state.playlistEdit.editNameValue = state.playlistEdit.label || "";
                  }
                }catch(e){}
                try{ renderList(); }catch(e){}
              }else{
                try{ inp.blur(); }catch(e){}
              }
              return;
            }
          });
          inp.addEventListener("blur", ()=>{
            try{
              if(isPlaylistCreate){
                if(!state.playlistCreate) return;
                if(state.playlistCreate.editing){
                  state.playlistCreate.editing = false;
                  state.playlistCreate.editValue = "";
                }
              }else if(isSmartPlaylistCreate){
                if(!state.smartPlaylistCreate) return;
                if(state.smartPlaylistCreate.editing){
                  state.smartPlaylistCreate.editing = false;
                  state.smartPlaylistCreate.editValue = "";
                }
              }else if(isPlaylistRename){
                if(!state.playlistEdit) return;
                if(state.playlistEdit.editingName){
                  state.playlistEdit.editingName = false;
                  if(!state.playlistEdit.submitting){
                    state.playlistEdit.editNameValue = state.playlistEdit.label || "";
                  }
                }
              }else{
                if(!state.libSearch) return;
                state.libSearch[field] = inp.value || "";
                if(state.libSearch.editField === field){
                  state.libSearch.editField = "";
                  state.libSearch.editValue = "";
                }
              }
            }catch(e){}
            try{
              if(isPlaylistCreate || isSmartPlaylistCreate || isPlaylistRename){
                renderList();
              }else if(field === "filter"){
                libRefreshList(true);
              }else{
                renderList();
              }
            }catch(e){}
          });
          li.appendChild(inp);
          editInputToFocus = inp;
        }else{
          const labelSpan = document.createElement("span");
          labelSpan.className = "ipodLabel";
          const v = isPlaylistCreate
            ? ((state.playlistCreate && typeof state.playlistCreate.editValue === "string") ? state.playlistCreate.editValue : "")
            : (isSmartPlaylistCreate
                ? ((state.smartPlaylistCreate && typeof state.smartPlaylistCreate.editValue === "string") ? state.smartPlaylistCreate.editValue : "")
            : (isPlaylistRename
                ? ((state.playlistEdit && typeof state.playlistEdit.editNameValue === "string") ? state.playlistEdit.editNameValue : ((state.playlistEdit && state.playlistEdit.label) ? state.playlistEdit.label : ""))
                : ((state.libSearch && typeof state.libSearch[field] === "string") ? state.libSearch[field] : "")));
          labelSpan.textContent = (v && v.trim()) ? v : placeholder;
          li.appendChild(labelSpan);

          const wrap = document.createElement("span");
          wrap.className = "ipodPills";
          const sp = document.createElement("span");
          sp.className = "ipodPill" + ((!isPlaylistCreate && !isPlaylistRename && field === "q") ? " v" : "");
          sp.textContent = isPlaylistCreate ? "New" : (isSmartPlaylistCreate ? "Smart" : (isPlaylistRename ? "Name" : ((field === "q") ? "Query" : "Filters")));
          wrap.appendChild(sp);
          // extra pills (status etc.)
          if(Array.isArray(it.pills)){
            for(const p of it.pills){
              if(!p) continue;
              const sp2 = document.createElement("span");
              if(typeof p === "string"){
                sp2.className = "ipodPill";
                sp2.textContent = p;
              }else{
                const tone = String(p.tone || "");
                sp2.className = "ipodPill" + (tone ? (" " + tone) : "");
                sp2.textContent = String(p.text || "");
              }
              wrap.appendChild(sp2);
            }
          }
          li.appendChild(wrap);
        }

        li.addEventListener("click", ()=>{
          const wasSel = (state.sel === i);
          state.sel = i;
          if(isPlaylistCreate){
            if(wasSel) beginPlaylistCreateEdit();
            else renderList();
          }else if(isSmartPlaylistCreate){
            if(wasSel) beginSmartPlaylistCreateEdit();
            else renderList();
          }else if(isPlaylistRename){
            if(wasSel) beginPlaylistRenameEdit();
            else renderList();
          }else if(!(state.libSearch && state.libSearch.editField === field)){
            renderList();
          }
        });

        libList.appendChild(li);
        continue;
      }

      const labelWrap = document.createElement("span");
      labelWrap.className = "ipodLabelWrap";
      const labelSpan = document.createElement("span");
      labelSpan.className = "ipodLabel";
      if(it && it.label_html){
        labelSpan.innerHTML = String(it.label_html || "");
      }else if(it && it.kind === "album") {
        let rendered = false;
        try{
          const raw = (typeof it.value === "string") ? JSON.parse(it.value) : (it.value || {});
          const artist = String((raw && raw.artist) || "").trim();
          const album = String((raw && raw.album) || "").trim();
          if(artist && album){
            labelSpan.innerHTML = escapeHtml(album) + '   ' + '<span class="artistStrong">' + escapeHtml(artist) + '</span>';
            rendered = true;
          }
        }catch(e){}
        if(!rendered) labelSpan.textContent = it.label || "";
      }else{
        labelSpan.textContent = it.label || "";
      }
      labelWrap.appendChild(labelSpan);
      if(it && it.sub_label){
        const sub = document.createElement("span");
        sub.className = "ipodSubLabel";
        sub.textContent = String(it.sub_label || "");
        labelWrap.appendChild(sub);
      }
      li.appendChild(labelWrap);

      const pills = [];
      if(Array.isArray(it.pills)){
        for(const p of it.pills){
          if(!p) continue;
          if(typeof p === "string"){
            pills.push({text: p, tone: "", bar: null});
          }else if(typeof p === "object"){
            const bar = (p.bar != null && isFinite(Number(p.bar))) ? Math.max(0, Math.min(1, Number(p.bar))) : null;
            pills.push({text: String(p.text || ""), tone: String(p.tone || ""), bar: bar});
          }
        }
      }
      if(it.badge){
        pills.push({text: String(it.badge), tone: "warn"});
      }

      if(it.selectable){
        pills.push({text: it.selected ? "Selected" : "Select", tone: it.selected ? "ok" : "" , _selectPill: true});
      }

      if(pills.length){
        const wrap = document.createElement("span");
        wrap.className = "ipodPills";
        for(const p of pills){
          const sp = document.createElement("span");
          const toneCls = p.tone ? (" " + p.tone) : "";
          if(p.bar != null && isFinite(Number(p.bar))){
            sp.className = "ipodPill bar" + toneCls;
            const fill = document.createElement("span");
            fill.className = "pillBarFill";
            fill.style.width = (Math.max(0, Math.min(1, Number(p.bar))) * 100).toFixed(1) + "%";
            const txt = document.createElement("span");
            txt.className = "pillBarText";
            txt.textContent = p.text || "";
            sp.appendChild(fill);
            sp.appendChild(txt);
          }else{
            sp.className = "ipodPill" + toneCls;
            sp.textContent = p.text || "";
          }
          if(p._selectPill){
            sp.addEventListener("click", (ev)=>{
              ev.preventDefault();
              ev.stopPropagation();
              state.sel = i;
              try{
                if(it.kind === "playlist_add_file"){
                  const act = selectItem(it);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(it.kind === "np_playlist_entry"){
                  const act = selectItem(it);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(it.kind === "playlist_remove_track"){
                  const cur = state.current || {};
                  if(!cur.selected) cur.selected = new Set();
                  const rp = String(it.rel || "");
                  if(rp){
                    if(cur.selected.has(rp)) cur.selected.delete(rp);
                    else cur.selected.add(rp);
                  }
                  const act = viewPlaylistRemoveSongs(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", false);
                  if(act && typeof act.catch === "function") act.catch(()=>{});
                  return;
                }
                if(typeof it.onToggle === "function"){
                  it.onToggle();
                }else{
                  it.selected = !it.selected;
                }
              }catch(e){}
              renderList();
            });
          }
          wrap.appendChild(sp);
        }
        li.appendChild(wrap);
      }

      li.addEventListener("click", ()=>{
        state.sel = i;
        renderList();
        try{
          const p = selectItem(it);
          if(p && typeof p.catch === "function"){ p.catch(()=>{}); }
        }catch(e){}
      });
      libList.appendChild(li);
    }
    if(state.items.length === 0){
      const li = document.createElement("li");
      li.className = "ipodItem info";
      li.textContent = "Empty";
      libList.appendChild(li);
    }

    // restore scroll position first, then ensure selection is visible without jumping to top
    try{
      if(libList) libList.scrollTop = prevScroll;
    }catch(e){}
    const selEl = libList.querySelector(".ipodItem.sel");
    if(selEl){
      selEl.scrollIntoView({block: "nearest"});
    }
    if(editInputToFocus){
      try{
        editInputToFocus.focus();
        editInputToFocus.click();
        const n = editInputToFocus.value.length;
        editInputToFocus.setSelectionRange(n, n);
      }catch(e){}
    }
  }

function vibeTick(){
  try{
    if(navigator && typeof navigator.vibrate === "function"){
      navigator.vibrate(8);
    }
  }catch(e){}
}

// ===== library actions (reindex, last.fm auth, forced fullscreen) =====
  let forceFullscreen = false;

  async function doLibraryReindex(){
    try{
      await fetch("/api/library/reindex", {method: "POST"});
      return true;
    }catch(e){
      alert("Reindex failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }
  }

  async function getAnyIndexBuilding(){
    try{
      const js = await apiGet("/api/library/building");
      return !!(js && js.ok && js.any_building);
    }catch(e){
      return false;
    }
  }

  async function startLastfmLoginFlow(){
    let token = null;
    let authUrl = null;

    try{
      const r = await fetch("/api/lastfm/auth/start", {method: "GET"});
      const j = await r.json();
      if(!j || !j.ok){
        throw new Error((j && j.error) ? j.error : "Last.fm auth start failed");
      }
      token = j.token;
      authUrl = j.auth_url;
    }catch(e){
      alert("Last.fm login failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }

    try{
      if(authUrl){
        window.open(authUrl, "_blank", "noopener");
      }
    }catch(e){}

    let proceed = true;
    try{
      proceed = confirm("A Last.fm approval page was opened. After you approve Debripod, click OK to finish login.");
    }catch(e){}

    if(!proceed){
      return false;
    }

    try{
      const r2 = await fetch("/api/lastfm/auth/finish", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token: token})
      });
      const j2 = await r2.json();
      if(!j2 || !j2.ok){
        throw new Error((j2 && j2.error) ? j2.error : "Last.fm auth finish failed");
      }
      alert("Last.fm login complete.");
      return true;
    }catch(e){
      alert("Last.fm login failed: " + (e && e.message ? e.message : String(e)));
      return false;
    }
  }

  async function forceFullscreenOn(){
    forceFullscreen = true;
    try{
      if(!document.fullscreenElement && document.documentElement && document.documentElement.requestFullscreen){
        await document.documentElement.requestFullscreen();
      }
    }catch(e){}
  }

  document.addEventListener("fullscreenchange", ()=>{
    if(forceFullscreen && !document.fullscreenElement){
      setTimeout(async ()=>{
        if(forceFullscreen && !document.fullscreenElement){
          try{
            if(document.documentElement && document.documentElement.requestFullscreen){
              await document.documentElement.requestFullscreen();
            }
          }catch(e){}
        }
      }, 150);
    }
  });
;


  function scrollSel(delta){
    if(!state.items.length) return;
    const n = state.items.length;
    const prev = state.sel;
    state.sel = Math.max(0, Math.min(n - 1, state.sel + delta));
    if(state.sel !== prev){
      try{
        if(state.playlistCreate) state.playlistCreate.editing = false;
        if(state.smartPlaylistCreate) state.smartPlaylistCreate.editing = false;
        if(state.playlistEdit) state.playlistEdit.editingName = false;
        if(state.libSearch && state.libSearch.editField) state.libSearch.editField = "";
      }catch(e){}
      vibeTick();
    }
    renderList();
  }

  function _randomEligibleItem(it){
    if(!it) return false;
    const k = (it.kind || "");
    if(!k) return false;
    if(k === "info" || k === "up" || k === "random" || k === "playlist_create" || k === "smart_playlist_create" || k === "playlist_edit_entry") return false;
    return true;
  }

  function _shouldAddRandom(items){
    try{
      if(!state.current) return false;
      const vk = state.current.kind || "";
      // Remove Random from the top-level Browse screen
      if(vk !== "folder" && vk !== "metalist") return false;

      // Remove Random from individual album tracklists
      if(vk === "metalist" && (state.current.level || "") === "tracks") return false;

      for(const it of (items || [])){
        if(_randomEligibleItem(it)) return true;
      }
      return false;
    }catch(e){
      return false;
    }
  }

  function resetList(items){
    const arr = Array.isArray(items) ? items.slice() : [];
    if(_shouldAddRandom(arr)){
      const btn = {kind:"random", label:"Random"};
      let insertAt = 0;
      while(insertAt < arr.length){
        const k = (arr[insertAt] && arr[insertAt].kind) ? arr[insertAt].kind : "";
        if(k === "up" || k === "playlist_create" || k === "smart_playlist_create" || k === "playlist_edit_entry"){
          insertAt += 1;
          continue;
        }
        break;
      }
      arr.splice(insertAt, 0, btn);
    }
    state.items = arr;

    // Restore selection and scroll when returning to a list via Menu/back
    let restoreSel = null;
    let restoreScroll = null;
    try{
      if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
        restoreSel = Number(state.current.savedSel);
      }
      if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
        restoreScroll = Number(state.current.savedScroll);
      }
    }catch(e){ restoreSel = null; restoreScroll = null; }

    if(restoreSel != null){
      const max = Math.max(0, arr.length - 1);
      state.sel = Math.max(0, Math.min(max, restoreSel));
    }else{
      state.sel = 0;
    }

    setHeader();
    renderList();

    if(restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
    }
  }

  function snapshotListState(){
    try{
      if(state.current){
        state.current.savedSel = state.sel;
        if(libList) state.current.savedScroll = libList.scrollTop;
      }
    }catch(e){}
  }

  function waitLibPageFade(ms){
    return new Promise(resolve=> setTimeout(resolve, ms || 220));
  }

  async function runLibraryPageTransition(loadFn){
    try{
      if(libList){
        libList.classList.add("pageFadeHidden");
        await waitLibPageFade(220);
      }
      await loadFn();
      if(libList){
        requestAnimationFrame(()=>{
          requestAnimationFrame(()=>{
            try{ libList.classList.remove("pageFadeHidden"); }catch(e){}
          });
        });
      }
    }catch(e){
      try{ if(libList) libList.classList.remove("pageFadeHidden"); }catch(_e){}
      throw e;
    }
  }

  async function setView(view, push){
    await runLibraryPageTransition(async ()=>{
      if(push && state.current){
        snapshotListState();
        state.history.push(state.current);
      }
      state.current = view;
      setHeader();
      await view.load();
    });
  }

  function rootViewObj(){
    return {
      kind: "roots",
      label: "",
      savedSel: 0,
      savedScroll: 0,
      load: async function(){
        await showRoots(false);
      }
    };
  }

  async function showRoots(resetHistory){
    const shouldResetHistory = (resetHistory !== false);
    showNowPlaying(false);
    const cfg = await loadConfig();
    await syncPlaybackFromServer();
    state.root = null;
    if(shouldResetHistory){
      state.history = [];
    }
    if(!state.rootView){
      state.rootView = rootViewObj();
    }
    state.current = state.rootView;
    const items = [{kind:"libsearch_entry", label:"Search"},{kind:"libtasks_entry", label:"Tasks"}].concat((cfg.roots||[]).map(r=>({kind:"root", label:r.name, root:r})));
    if(state.now || state.serverNow){
      items.push({kind:"nowplaying", label:"Now Playing"});
      if(state.serverRecent && state.serverRecent.length){
        items.push({kind:"recently", label:"Recently Played"});
      }
    }else{
      // show Recently Played only if there is history (even without now playing)
      if(state.serverRecent && state.serverRecent.length){
        items.push({kind:"recently", label:"Recently Played"});
      }
    }
    items.push({kind:"libinfo_entry", label:"Info"});
    resetList(items);
  }


  
  

  function libControlsHide(){}

  function libControlsShow(html){}

  function libSetStatus(msg, tone){
    try{
      if(!state.libSearch) state.libSearch = {q:"", filter:"", engine:"combined", cache_key:"", result_source:"combined", last_count:0, results:[], knaben_results:[], slsk_users:[]};
      state.libSearch.status_msg = msg ? String(msg) : "";
      state.libSearch.status_tone = tone ? String(tone) : "";
    }catch(e){}
    // legacy element (if present)
    const el = document.getElementById("libSearchStatus");
    if(!el) return;
    if(!msg){
      el.style.display = "none";
      el.textContent = "";
      el.className = "ipodPill";
      return;
    }
    el.style.display = "inline-flex";
    el.textContent = String(msg);
    el.className = "ipodPill" + (tone ? (" " + tone) : "");
  }

  function libSetFileStatus(msg, tone){
    const view = state.current || null;
    if(view){
      view._fileStatus = msg ? String(msg) : "";
      view._fileStatusTone = tone ? String(tone) : "";
      const target = (view._searchResult || view._rd || view._slsk || view._slskbrowse || null);
      if(target && typeof target.buildItems === "function"){
        try{ libSearchRebuildFilesList(target.buildItems()); }catch(e){}
      }
    }
  }

  function libParseFilter(q){
    const s = String(q || "").trim().toLowerCase();
    const tokens = s.split(/\s+/).filter(Boolean);

    const out = {exts: new Set(), bitDepth: 0, sampleRate: 0, source: "", rest: []};

    for(const t of tokens){
      if(t === "source:knaben" || t === "src:knaben"){ out.source = "knaben"; continue; }
      else if(t === "source:soulseek" || t === "src:soulseek" || t === "source:slsk" || t === "src:slsk"){ out.source = "soulseek"; continue; }
      else if(t === "source:youtube" || t === "src:youtube" || t === "source:yt" || t === "src:yt"){ out.source = "youtube"; continue; }
      else if(t === "source:combined" || t === "src:combined"){ out.source = "combined"; continue; }
      if(t === "flac" || t === ".flac") out.exts.add("flac");
      else if(t === "mp3" || t === ".mp3") out.exts.add("mp3");
      else if(t === "m4a" || t === ".m4a") out.exts.add("m4a");
      else if(t === "aac" || t === ".aac") out.exts.add("aac");
      else if(t === "ogg" || t === ".ogg") out.exts.add("ogg");
      else if(t === "wav" || t === ".wav") out.exts.add("wav");
      else if(t === "alac" || t === ".alac") out.exts.add("alac");
      else if(t === "opus" || t === ".opus") out.exts.add("opus");
      else if(t === "16" || t === "16bit" || t === "16-bit") out.bitDepth = 16;
      else if(t === "24" || t === "24bit" || t === "24-bit") out.bitDepth = 24;
      else if(t === "32" || t === "32bit" || t === "32-bit") out.bitDepth = 32;
      else if(t === "44" || t === "44.1" || t === "44100" || t === "44khz" || t === "44.1khz") out.sampleRate = 44100;
      else if(t === "48" || t === "48000" || t === "48khz") out.sampleRate = 48000;
      else if(t === "88" || t === "88.2" || t === "88200" || t === "88khz" || t === "88.2khz") out.sampleRate = 88200;
      else if(t === "96" || t === "96000" || t === "96khz") out.sampleRate = 96000;
      else if(t === "176" || t === "176.4" || t === "176khz" || t === "176.4khz") out.sampleRate = 176400;
      else if(t === "192" || t === "192000" || t === "192khz") out.sampleRate = 192000;
      else out.rest.push(t);
    }
    return out;
  }

  function libTextHasAllTokens(text, tokens){
    const t = String(text || "").toLowerCase();
    for(const x of (tokens || [])){
      if(!x) continue;
      if(!t.includes(x)) return false;
    }
    return true;
  }

  function libGuessFromName(name){
    const s = String(name || "").toLowerCase();
    const mExt = s.match(/\.([a-z0-9]{2,5})$/);
    const ext = mExt ? mExt[1] : "";
    let bd = 0;
    let sr = 0;
    if(/\b24\s*bit\b/.test(s) || /\b24bit\b/.test(s)) bd = 24;
    else if(/\b16\s*bit\b/.test(s) || /\b16bit\b/.test(s)) bd = 16;
    else if(/\b32\s*bit\b/.test(s) || /\b32bit\b/.test(s)) bd = 32;

    const mK = s.match(/\b(44\.1|48|88\.2|96|176\.4|192)\s*k(?:hz)?\b/);
    if(mK){
      const v = mK[1];
      if(v === "44.1") sr = 44100;
      else if(v === "48") sr = 48000;
      else if(v === "88.2") sr = 88200;
      else if(v === "96") sr = 96000;
      else if(v === "176.4") sr = 176400;
      else if(v === "192") sr = 192000;
    }
    return {ext: ext, bitDepth: bd, sampleRate: sr};
  }

  function libHumanSpeed(v){
    const n = Number(v || 0);
    if(!n) return "";
    if(n >= 1000000) return (n/1000000).toFixed(1) + " MBps";
    if(n >= 1000) return (n/1000).toFixed(0) + " KBps";
    return String(Math.round(n)) + " Bps";
  }

  function libResultsToItems(){
    const q = state.libSearch.q || "";
    const filt = libParseFilter(state.libSearch.filter || "");
    const items = [];

    const stMsg = (state.libSearch && state.libSearch.status_msg) ? String(state.libSearch.status_msg) : "";
    const stTone = (state.libSearch && state.libSearch.status_tone) ? String(state.libSearch.status_tone) : "";
    const qPills = [];
    if(stMsg){
      qPills.push({text: stMsg, tone: stTone || ""});
    }
    items.push({kind:"libsearch_query", label:"Enter query", pills: qPills});
    items.push({kind:"libsearch_filter", label:"Enter filters"});

    items.push({kind:"libsearch_action", label:"Clear"});
    items.push({kind:"libsearch_action", label:"Search history"});

    for(const r of (state.libSearch.results || [])){
      const source = String(r.source || "").toLowerCase();
      if(filt.source && source !== filt.source) continue;

      const title = String(r.title || r.label || "Result");
      const user = String(r.user || "").trim();
      const searchable = [
        source,
        user,
        title,
        String(r.directory || ""),
        String(r.infohash || ""),
        String(r.category || ""),
        ...(Array.isArray(r.files) ? r.files.map(f => [f.name || "", f.ext || "", f.quality || ""].join(" ")) : [])
      ].join(" ").toLowerCase();
      if(filt.rest.length && !libTextHasAllTokens(searchable, filt.rest)) continue;

      const files = Array.isArray(r.files) ? r.files : [];
      if(filt.exts.size || filt.bitDepth || filt.sampleRate){
        let ok = false;
        for(const f of files){
          const ext = String(f.ext || "").toLowerCase();
          const bd = Number(f.bit_depth || 0);
          const sr = Number(f.sample_rate || 0);
          if(filt.exts.size && (!ext || !filt.exts.has(ext))) continue;
          if(filt.bitDepth && (!bd || bd !== filt.bitDepth)) continue;
          if(filt.sampleRate && (!sr || sr !== filt.sampleRate)) continue;
          ok = true;
          break;
        }
        if(!ok) continue;
      }

      const pills = [];
      pills.push({text: String(r.source_label || source || "source")});
      if(Number(r.file_count || 0) > 0) pills.push({text: String(r.file_count) + " files"});
      if(Number(r.size || 0) > 0) pills.push({text: humanBytes(Number(r.size || 0))});
      if(source === "soulseek" && Number(r.speed || 0) > 0){
        pills.push({text: libHumanSpeed(Number(r.speed || 0))});
      }else if(source === "knaben"){
        const s = Number(r.seeders || 0);
        const l = Number(r.leechers || 0);
        pills.push({text: "S " + String(s) + " L " + String(l)});
      }else if(source === "youtube"){
        if(r.length) pills.push({text: String(r.length)});
        if(r.published) pills.push({text: String(r.published)});
      }

      const primary = user ? ('<span class="artistStrong">' + escapeHtml(user) + '</span>') : ('<span class="artistStrong">' + escapeHtml(title) + '</span>');
      const sub = user ? title : String(r.directory_title || r.directory || r.category || "");

      items.push({
        kind:"libsearch_result",
        label: user || title,
        label_html: primary,
        sub_label: sub || "",
        source: source,
        result_id: r.result_id || "",
        raw: r,
        pills: pills
      });
    }

    return items;
  }

  function libRefreshList(preserveSel){
    const items = libResultsToItems();
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);

    let restoreSel = null;
    let restoreScroll = null;
    try{
      if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
        restoreSel = Number(state.current.savedSel);
      }
      if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
        restoreScroll = Number(state.current.savedScroll);
      }
    }catch(e){ restoreSel = null; restoreScroll = null; }

    state.items = Array.isArray(items) ? items : [];
    if(preserveSel){
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, prevSel));
    }else if(restoreSel != null){
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, restoreSel));
    }else{
      state.sel = 0;
    }

    setHeader();
    renderList();

    if(!preserveSel && restoreScroll != null && libList){
      const top = Math.max(0, restoreScroll);
      requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
    }else{
      try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    }
  }

  function libSearchRebuildFilesList(items){
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    const arr = Array.isArray(items) ? items : [];
    state.items = arr;
    const max = Math.max(0, arr.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
  }



  async function viewLibSearch(push){
    showNowPlaying(false);
    await setView({
      kind:"libsearch",
      label:"Search",
      load: async function(){
        libControlsHide();
        // keep existing query/filter text; list rows handle editing/focus
        state.libSearch.engine = state.libSearch.engine || "";
        libRefreshList(false);
      }
    }, push);
  }

// Library-root Tasks view (parity with Tasks tab, but in the iPod list UI)
async function viewLibTasks(push){
  showNowPlaying(false);
  await setView({
    kind:"libtasks",
    label:"Tasks",
    load: async function(){
      libControlsHide();
      try{
        const js = await apiGet("/api/tasks");
        state.libTasks.tasks = (js && js.tasks) ? js.tasks : [];
      }catch(e){
        state.libTasks.tasks = [];
      }
      libTasksRefreshList(false);
    }
  }, push);
}

function libTasksBuildItems(){
  const tasks = Array.isArray(state.libTasks.tasks) ? state.libTasks.tasks : [];
  const items = [];
  items.push({kind:"libtasks_action", label:"Clear all tasks", action:"clear_all"});
  for(const t of tasks){
    const id = String(t.id || "");
    const title = String(t.title || "Task");
    const src = String(t.source || "rd").toLowerCase();
    const stLower = String(t.state || "").toLowerCase();
    const pills = [];
    pills.push(src === "soulseek" ? "Soulseek" : (src === "youtube" ? "YouTube" : "Debrid"));
    if(t.paused) pills.push({text:"paused", tone:"warn"});
    if(stLower){
      let tone = "";
      if(stLower === "done") tone = "ok";
      else if(stLower === "error" || stLower === "canceled") tone = "warn";
      pills.push({text: stLower, tone: tone});
    }
    // light overall percent indicator when available
    try{
      const ot = Number(t.overall_total || 0);
      const od = Number(t.overall_done || 0);
      if(ot > 0){
        const pct = Math.max(0, Math.min(100, Math.floor((od / ot) * 100)));
        pills.push(String(pct) + "%");
      }
    }catch(e){}
    items.push({kind:"libtask_entry", label:title, task_id:id, pills:pills});
  }
  if(tasks.length === 0){
    items.push({kind:"info", label:"No tasks"});
  }
  return items;
}

function libTasksRefreshList(preserveSel){
  const items = libTasksBuildItems();
  const prevSel = state.sel;
  const prevScroll = (libList ? libList.scrollTop : 0);

  let restoreSel = null;
  let restoreScroll = null;
  try{
    if(state.current && typeof state.current.savedSel === "number" && isFinite(state.current.savedSel)){
      restoreSel = Number(state.current.savedSel);
    }
    if(state.current && typeof state.current.savedScroll === "number" && isFinite(state.current.savedScroll)){
      restoreScroll = Number(state.current.savedScroll);
    }
  }catch(e){ restoreSel = null; restoreScroll = null; }

  state.items = Array.isArray(items) ? items : [];
  if(preserveSel){
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
  }else if(restoreSel != null){
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, restoreSel));
  }else{
    state.sel = 0;
  }

  setHeader();
  renderList();

  if(!preserveSel && restoreScroll != null && libList){
    const top = Math.max(0, restoreScroll);
    requestAnimationFrame(()=>{ try{ libList.scrollTop = top; }catch(e){} });
  }else{
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
  }
}

function libTaskFilesForTask(t){
  const src = String((t && t.source) || "rd").toLowerCase();
  if(src === "soulseek"){
    return Array.isArray(t.slsk_files) ? t.slsk_files : [];
  }
  return Array.isArray(t.rd_files) ? t.rd_files : [];
}

function libTaskBuildItemsForView(view){
  const t = (view && view.task) ? view.task : {};
  const files = libTaskFilesForTask(t);
  const items = [];
  const selCount = (view && view.selected && view.selected.size) ? view.selected.size : 0;

  items.push({kind:"libtask_action", label:"Pause selected", action:"pause_selected", badge: selCount ? String(selCount) : ""});
  items.push({kind:"libtask_action", label:"Cancel selected", action:"cancel_selected", badge: selCount ? String(selCount) : ""});
  items.push({kind:"libtask_action", label:"Select all", action:"selectall"});
  items.push({kind:"libtask_action", label:"Clear task", action:"clear_task"});

  const msg = String((t && t.message) || "");
  if(msg){
    items.push({kind:"info", label: msg});
  }

  for(const f of files){
    const fid = String((f && f.file_id) || "");
    const rp = String((f && (f.name || f.remote_path || f.out_path)) || "");
    const name = (rp.split("\\").pop() || rp || fid || "File");
    const stLower = String((f && f.state) || "queued").toLowerCase();
    const done = Number((f && f.done) || 0);
    const total = Number((f && f.total) || 0);

    let pct = 0;
    let bar = 0;
    let pctText = "?";
    if(total > 0){
      pct = Math.max(0, Math.min(100, Math.floor((done / total) * 100)));
      bar = pct / 100;
      pctText = String(pct) + "%";
    }else if(stLower === "complete" || stLower === "done"){
      pct = 100;
      bar = 1;
      pctText = "100%";
    }else{
      pct = 0;
      bar = 0;
      pctText = "0%";
    }

    let stTone = "";
    if(stLower === "complete" || stLower === "done") stTone = "ok";
    else if(stLower === "failed" || stLower === "error" || stLower === "canceled" || stLower === "aborted" || stLower === "incomplete" || stLower === "paused") stTone = "warn";

    const stLabel = slskDownloadLabel(stLower) || String(stLower || "").toUpperCase();
    const pills = [
      {text: stLabel, tone: stTone},
      {text: pctText, tone: ""},
      {text: "", tone: "", bar: bar}
    ];

    const item = {
      kind:"libtask_file",
      label:name,
      task_id:String(view.task_id || ""),
      file_id:fid,
      selectable:true,
      selected:(view && view.selected && fid) ? view.selected.has(fid) : false,
      pills:pills
    };
    item.onToggle = ()=>{
      if(!view.selected) view.selected = new Set();
      if(view.selected.has(fid)) view.selected.delete(fid);
      else view.selected.add(fid);
      item.selected = view.selected.has(fid);
    };
    items.push(item);
  }

  if(!files.length){
    items.push({kind:"info", label:"No files"});
  }
  return items;
}

async function viewLibTask(push, taskId){
  showNowPlaying(false);
  await setView({
    kind:"libtask",
    label:"Task",
    task_id: String(taskId || ""),
    task: null,
    selected: new Set(),
    load: async function(){
      libControlsHide();
      try{
        const js = await apiGet("/api/tasks");
        const tasks = (js && js.tasks) ? js.tasks : [];
        const t = tasks.find(x => String(x.id || "") === String(this.task_id || ""));
        this.task = t || this.task || null;
        if(t && t.title){
          this.label = String(t.title);
        }
      }catch(e){}
      setHeader();
      resetList(libTaskBuildItemsForView(this));
    }
  }, push);
}

async function libTasksPollTick(){
  const vk = (state.current && state.current.kind) ? state.current.kind : "";
  if(vk !== "libtasks" && vk !== "libtask") return;
  try{
    const js = await apiGet("/api/tasks");
    const tasks = (js && js.tasks) ? js.tasks : [];
    if(vk === "libtasks"){
      state.libTasks.tasks = tasks;
      libTasksRefreshList(true);
    }else if(vk === "libtask"){
      const view = state.current;
      const t = tasks.find(x => String(x.id || "") === String(view.task_id || ""));
      if(t){
        view.task = t;
        if(t.title) view.label = String(t.title);
      }
      const prevSel = state.sel;
      const prevScroll = (libList ? libList.scrollTop : 0);
      state.items = libTaskBuildItemsForView(view);
      const max = Math.max(0, state.items.length - 1);
      state.sel = Math.max(0, Math.min(max, prevSel));
      setHeader();
      renderList();
      try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    }
  }catch(e){}
}

// start/refresh library tasks poller
if(window.dpLibTasksTimer) clearInterval(window.dpLibTasksTimer);
window.dpLibTasksTimer = setInterval(()=>{ libTasksPollTick(); }, {{ tasks_poll_ms }});

async function libDoSearch(engine, q){
    const qq = String(q || "").trim();
    if(!qq){
      libSetStatus("Enter a query", "warn");
      return;
    }
    const useEngine = String(engine || "combined").toLowerCase() || "combined";
    state.libSearch.q = qq;
    state.libSearch.engine = useEngine;
    libSetStatus("Searching", "");
    try{
      const endpoint = (useEngine === "youtube") ? "/api/libsearch/youtube?q=" : "/api/libsearch/combined?q=";
      const js = await apiGet(endpoint + encodeURIComponent(qq));
      if(!js || !js.ok){
        throw new Error((js && js.error) ? js.error : "Search failed");
      }
      state.libSearch.result_source = useEngine;
      state.libSearch.cache_key = js.cache_key || "";
      state.libSearch.results = Array.isArray(js.results) ? js.results : [];
      state.libSearch.knaben_results = js.knaben_results || [];
      state.libSearch.slsk_users = js.slsk_users || [];
      state.libSearch.last_count = Number(js.result_count || state.libSearch.results.length || 0);
      libSetStatus(String(state.libSearch.last_count) + " results", "ok");
      libRefreshList(true);
    }catch(e){
      libSetStatus("Error", "warn");
      alert(String(e && e.message ? e.message : e));
    }
  }

  async function viewLibSearchHistory(push){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_history",
      label:"Search history",
      load: async function(){
        libControlsHide();
        let items = [];
        items.push({kind:"libsearch_history_action", label:"Clear", action:"clear_history"});
        try{
          const js = await apiGet("/api/search_history");
          const hist = (js && js.ok && Array.isArray(js.items)) ? js.items : [];
          for(const h of hist){
            const q = h.q || "";
            const engine = h.engine || "";
            const when = h.when || "";
            const lbl = q ? q : "(empty)";
            const pills = [];
            if(engine) pills.push(engine);
            if(when) pills.push(String(when));
            items.push({kind:"libsearch_history_entry", label: lbl, engine: engine, q: q, pills: pills});
          }
          if(!items.length){
            items.push({kind:"info", label:"No search history"});
          }
        }catch(e){
          items = [{kind:"info", label:"Failed to load history"}];
        }
        resetList(items);
      }
    }, push);
  }
  
  async function viewLibInfo(push){
    showNowPlaying(false);
    await setView({
      kind:"libinfo",
      label:"Info",
      load: async function(){
        libControlsHide();
        const items = [];

        const v = (APP_INFO && APP_INFO.version) ? String(APP_INFO.version) : "";
        const vPills = [];
        if(v) vPills.push("v" + v);
        items.push({kind:"info", label:"Debripod", pills: vPills});

        const host = (APP_INFO && APP_INFO.host) ? String(APP_INFO.host) : (location.hostname || "");
        const port = (APP_INFO && (APP_INFO.port !== undefined && APP_INFO.port !== null)) ? String(APP_INFO.port) : (location.port || "");
        const hp = [];
        if(host) hp.push(host);
        if(port) hp.push(port);
        items.push({kind:"info", label:"Host and port", pills: hp});

        const ddir = (APP_INFO && APP_INFO.ddir) ? String(APP_INFO.ddir) : "";
        const dP = [];
        if(ddir) dP.push(ddir);
        items.push({kind:"info", label:"Debrid download dir", pills: dP});

        const sdir = (APP_INFO && APP_INFO.sdir) ? String(APP_INFO.sdir) : "";
        const sP = [];
        if(sdir) sP.push(sdir);
        items.push({kind:"info", label:"Soulseek download dir", pills: sP});

        let anyBuilding = false;
        try{
          anyBuilding = await getAnyIndexBuilding();
        }catch(e){}
        const rp = anyBuilding ? ["indexing"] : [];
        items.push({kind:"libinfo_action", label:"Reindex", action:"reindex", pills: rp});

        let lfUser = "";
        try{
          const js = await apiGet("/api/lastfm/status");
          if(js && js.ok && js.username) lfUser = String(js.username || "");
        }catch(e){}
        const lp = [];
        if(lfUser) lp.push("logged in as " + lfUser);
        items.push({kind:"libinfo_action", label:"Login to Last.fm", action:"lastfm_login", pills: lp});

        items.push({kind:"libinfo_action", label:"Full Screen", action:"force_fullscreen"});
        items.push({kind:"libinfo_action", label:"Visualizer", action:"toggle_visualizer", pills:[visualizerEnabled ? "On" : "Off"]});
        items.push({kind:"libinfo_action", label:"Binds", action:"binds_menu"});

        resetList(items);
      }
    }, push);
  }


  async function viewLibBinds(push){
    showNowPlaying(false);
    await setView({
      kind:"libbinds",
      label:"Binds",
      load: async function(){
        libControlsHide();
        const items = [];

        items.push({kind:"info", label:"Navigation"});
        items.push({kind:"info", label:"W", pills:["Back or menu"]});
        items.push({kind:"info", label:"A", pills:["Previous or left"]});
        items.push({kind:"info", label:"S", pills:["Select or center"]});
        items.push({kind:"info", label:"D", pills:["Next or right"]});
        items.push({kind:"info", label:"Space", pills:["Play or pause"]});
        items.push({kind:"info", label:"Q", pills:["Scroll up"]});
        items.push({kind:"info", label:"E", pills:["Scroll down"]});
        items.push({kind:"info", label:"Mouse wheel", pills:["Scroll lists"]});
        items.push({kind:"info", label:"Arrow Up", pills:["Scroll up","Now Playing volume up","Seek left in seek mode"]});
        items.push({kind:"info", label:"Arrow Down", pills:["Scroll down","Now Playing volume down","Seek right in seek mode"]});

        resetList(items);
      }
    }, push);
  }

  function libBuildFileItemsFromRD(preview, title, magnet){
    const torrentId = preview.torrent_id || "";
    const files = preview.files || [];
    const view = state.current;
    view._rd = {title: title, magnet: magnet, torrent_id: torrentId, files: files, selected: new Set(), filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : "")};

    const build = ()=>{
      const f = libParseFilter(view._rd.filter || "");
      const items = [];
      const selCount = view._rd.selected.size;
      const statusMsg = String(view._fileStatus || "");

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      items.push({kind:"libsearch_file_action", label:"Download selected", action:"rd_download", badge: selCount ? String(selCount) : ""});
      items.push({kind:"libsearch_file_action", label:"Select all", action:"rd_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"rd_clear"});

      for(const ff of files){
        const name = ff.path || "";
        const guess = libGuessFromName(name);
        const ft = (name || "").toLowerCase();
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size){
          if(!guess.ext || !f.exts.has(guess.ext)) continue;
        }
        if(f.bitDepth){
          if(!guess.bitDepth || guess.bitDepth !== f.bitDepth) continue;
        }
        if(f.sampleRate){
          if(!guess.sampleRate || guess.sampleRate !== f.sampleRate) continue;
        }

        const id = String(ff.id);
        const pills = [];
        if(guess.ext) pills.push(guess.ext);
        if(ff.bytes) pills.push(humanBytes(ff.bytes));
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"knaben",
          file_id:id,
          selectable:true,
          selected:view._rd.selected.has(id),
          pills:pills,
          onToggle: ()=>{
            if(view._rd.selected.has(id)) view._rd.selected.delete(id);
            else view._rd.selected.add(id);
          }
        });
      }
      return items;
    };
    view._rd.buildItems = build;
    return build();
  }

  async function viewLibSearchKnabenFiles(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Files",
      source:"knaben",
      load: async function(){
        const title = item.label || "Knaben item";
        const magnet = item.magnet || "";
        resetList([{kind:"info", label:"Loading files"}]);
        libSetFileStatus("", "");
        try{
          const res = await apiPost("/api/rd/preview_files", {magnet: magnet});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load files");
          }
          libSetFileStatus("", "");
          resetList(libBuildFileItemsFromRD(js, title, magnet));
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load files"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  function libStandardizePreviewFilesForKnaben(preview){
    const out = [];
    const files = Array.isArray(preview && preview.files) ? preview.files : [];
    for(const ff of files){
      const name = String(ff.path || ff.name || "");
      const guess = libGuessFromName(name);
      const bitDepth = Number(guess.bitDepth || 0);
      const sampleRate = Number(guess.sampleRate || 0);
      const quality = [];
      if(bitDepth) quality.push(String(bitDepth) + " bit");
      if(sampleRate) quality.push(String(Math.round(Number(sampleRate)/100)/10) + " kHz");
      out.push({
        name: name,
        title: name,
        ext: guess.ext || "",
        quality: quality.join(" "),
        bitrate: "",
        size: Number(ff.bytes || 0),
        file_id: String(ff.id || ""),
        bit_depth: bitDepth,
        sample_rate: sampleRate,
        source: "knaben",
        selectable: true
      });
    }
    return out;
  }

  function libBuildGenericResultItems(result){
    const view = state.current;
    const src = String((result && result.source) || "").toLowerCase();
    const prev = view._searchResult || null;
    let selected = new Map();
    if(prev && prev.result_id === String(result.result_id || "") && prev.selected instanceof Map){
      selected = prev.selected;
    }
    view._searchResult = {
      result_id: String(result.result_id || ""),
      result: result || {},
      source: src,
      selected: selected,
      downloadQueued: !!(prev && prev.downloadQueued),
      filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : ""),
      loadingBrowse: (prev && prev.loadingBrowse) ? true : false
    };

    const build = ()=>{
      const target = view._searchResult;
      const rr = target.result || {};
      const f = libParseFilter(target.filter || "");
      const items = [];
      const files = Array.isArray(rr.files) ? rr.files : [];
      const selCount = target.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const statusTone = String(view._fileStatusTone || "");
      const streamPills = [];
      const downloadPills = [];
      if(selCount){
        const countPill = {text: String(selCount), tone: ""};
        streamPills.push(countPill);
        downloadPills.push({text: String(selCount), tone: ""});
      }
      if(target.downloadQueued){
        downloadPills.push({text: "Queued", tone: "warn"});
      }
      const streamMsg = statusMsg.toLowerCase();
      if(streamMsg && rr.stream_available && (streamMsg.includes("stream") || streamMsg.includes("prepare"))){
        streamPills.push({text: statusMsg, tone: statusTone || ""});
      }
      if(rr.browse_available){
        items.push({kind:"libsearch_file_action", label:(src === "youtube" ? "Browse channel" : "Browse share"), action:"result_browse", badge: target.loadingBrowse ? "Loading" : ""});
      }
      if(rr.stream_available){
        items.push({kind:"libsearch_file_action", label:"Stream selected", action:"result_stream", pills: streamPills});
      }
      items.push({kind:"libsearch_file_action", label:"Download selected", action:"result_download", pills: downloadPills});
      items.push({kind:"libsearch_file_action", label:"Select all", action:"result_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"result_clear"});

      let visibleFileCount = 0;
      for(const ff of files){
        const name = String(ff.name || ff.title || ff.label || "");
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        const fileSource = String(ff.source || src || "").toLowerCase();
        const searchText = [fileSource, name, ext, String(ff.quality || ""), String(ff.bitrate || "")].join(" ").toLowerCase();
        if(f.source && fileSource && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(searchText, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;
        visibleFileCount += 1;
        const key = src === "knaben" ? ("file:" + String(ff.file_id || name)) : (src === "youtube" ? ("itag:" + String(ff.itag || ff.file_id || name)) : (String(ff.remote_path || name)));
        const dlState = normalizeSlskDownloadState(String(ff.download_state || ""));
        const pills = [];
        if(fileSource) pills.push({text:fileSource});
        if(ext) pills.push(ext);
        if(ff.quality) pills.push(String(ff.quality));
        if(ff.bitrate) pills.push(String(ff.bitrate));
        if(Number(ff.size || 0) > 0) pills.push(humanBytes(Number(ff.size || 0)));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:src,
          selectable: !dlState,
          selected: !dlState && target.selected.has(key),
          pills:pills,
          remote_path: String(ff.remote_path || ""),
          file_id: String(ff.file_id || ""),
          size: Number(ff.size || 0),
          source: fileSource || src,
          onToggle: ()=>{
            if(dlState) return;
            if(target.selected.has(key)) target.selected.delete(key);
            else target.selected.set(key, {key:key, remote_path:String(ff.remote_path || ""), file_id:String(ff.file_id || ""), itag:String(ff.itag || ff.format_id || ff.file_id || ""), format_id:String(ff.format_id || ff.itag || ff.file_id || ""), size:Number(ff.size || 0), name:name, source:String(ff.source || src || ""), ext:String(ff.ext || ""), quality:String(ff.quality || ""), bitrate:String(ff.bitrate || ""), media:String(ff.media || ""), direct_url:String(ff.direct_url || ""), url:String((target.result && target.result.url) || "")});
          }
        });
      }
      if(files.length && !visibleFileCount){
        items.push({kind:"info", label:"No files match the current filter"});
      }else if(!files.length){
        items.push({kind:"info", label:"No files available"});
      }
      return items;
    };
    view._searchResult.buildItems = build;
    return build();
  }

  function libBuildStreamQueue(items){
    return (Array.isArray(items) ? items : []).map(it=>({
      kind:"file",
      media:String(it.media || ""),
      root:{id:String(it.root_id || "")},
      rel:String(it.rel || ""),
      label:String(it.label || it.title || ""),
      streamed:!!it.streamed,
      source:String(it.source || ""),
      ext:String(it.ext || ""),
      quality:String(it.quality || "")
    })).filter(it=>it.root.id && it.rel && (it.media === "audio" || it.media === "video"));
  }

  async function startSearchStreamQueue(queue, index){
    const pl = libBuildStreamQueue(queue);
    if(!pl.length) throw new Error("No streamable items");
    const idx = Math.max(0, Math.min(pl.length - 1, Number(index || 0)));
    state.streamQueue = pl;
    state.streamQueueIndex = idx;
    const first = pl[idx];
    if(first.media === "video"){
      state.videoPlaylist = pl;
      state.videoIndex = idx;
      await startVideoFromItem(first, true, 0);
    }else{
      state.playlist = pl;
      state.playIndex = idx;
      await startAudioFromItem(first, pl, idx, true, 0);
    }
  }

  function isSearchStreamActive(){
    try{
      return !!(state.now && state.now.rootId === "__search_stream__" && Array.isArray(state.streamQueue) && state.streamQueue.length);
    }catch(e){
      return false;
    }
  }

  async function playStreamQueueIndex(i, forceShow){
    const q = Array.isArray(state.streamQueue) ? state.streamQueue : [];
    if(i < 0 || i >= q.length) return;
    state.streamQueueIndex = i;
    const item = q[i];
    if(item.media === "video"){
      state.videoPlaylist = q;
      state.videoIndex = i;
      await startVideoFromItem(item, (typeof forceShow === "boolean" ? forceShow : true), 0);
    }else{
      state.playlist = q;
      state.playIndex = i;
      await startAudioFromItem(item, q, i, (typeof forceShow === "boolean" ? forceShow : true), 0);
    }
  }

  async function viewLibSearchResultDetails(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_result_detail",
      label:"Files",
      source:String(item.source || ""),
      load: async function(){
        const raw = Object.assign({}, item.raw || {});
        resetList([{kind:"info", label:"Loading files"}]);
        libSetFileStatus("", "");
        try{
          if(String(raw.source || item.source || "") === "knaben" && !raw.files_loaded){
            const res = await apiPost("/api/rd/preview_files", {magnet: raw.magnet || ""});
            const js = (res && res.json) ? res.json : {};
            if(!res || !res.ok || !js.ok){
              throw new Error((js && js.error) ? js.error : "Failed to load files");
            }
            raw.preview = js;
            raw.torrent_id = js.torrent_id || raw.torrent_id || "";
            raw.files = libStandardizePreviewFilesForKnaben(js);
            raw.file_count = raw.files.length;
            raw.files_loaded = true;
          }else if(String(raw.source || item.source || "") === "youtube" && !raw.files_loaded){
            const js = await apiGet("/api/youtube/files?url=" + encodeURIComponent(raw.url || ""));
            if(!js || !js.ok){
              throw new Error((js && js.error) ? js.error : "Failed to load YouTube formats");
            }
            raw.files = Array.isArray(js.files) ? js.files : [];
            raw.file_count = Number(js.file_count || raw.files.length || 0);
            raw.size = Number(js.size || 0);
            raw.files_loaded = true;
          }
          resetList(libBuildGenericResultItems(raw));
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load files"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  function normalizeSlskDownloadState(v){
    const s = String(v || "").trim().toLowerCase();
    if(!s) return "";
    if(s === "canceled") return "aborted";
    if(s === "requesting" || s === "connecting") return "initializing";
    return s;
  }

  function slskDownloadTone(v){
    const s = normalizeSlskDownloadState(v);
    if(s === "complete") return "ok";
    if(s === "failed" || s === "incomplete" || s === "aborted" || s === "paused") return "warn";
    return "";
  }

  function slskDownloadLabel(v){
    const s = normalizeSlskDownloadState(v);
    return s ? s.toUpperCase() : "";
  }

  function libBuildFileItemsFromSlsk(user, directory, files){
    const view = state.current;
    const prev = view._slsk || null;
    const prevSel = (prev && prev.selected instanceof Map) ? prev.selected : new Map();
    view._slsk = {user: user, directory: directory, files: files || [], selected: prevSel, downloadQueued: !!(prev && prev.downloadQueued), filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : ""), loadingBrowse: (prev && prev.loadingBrowse) ? true : false};

    const build = ()=>{
      const f = libParseFilter(view._slsk.filter || "");
      const items = [];
      const selCount = view._slsk.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const downloadPills = [];
      if(selCount) downloadPills.push({text: String(selCount)});
      if(view._slsk.downloadQueued) downloadPills.push({text:"Queued", tone:"warn"});

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      items.push({kind:"libsearch_file_action", label:"Browse user share", action:"slsk_browse_user", badge: view._slsk.loadingBrowse ? "Loading user shares" : ""});
      items.push({kind:"libsearch_file_action", label:"Download selected", action:"slsk_download", pills: downloadPills});
      items.push({kind:"libsearch_file_action", label:"Select all", action:"slsk_selectall"});
      items.push({kind:"libsearch_file_action", label:"Clear selection", action:"slsk_clear"});

      for(const ff of (view._slsk.files || [])){
        const name = ff.name || ff.remote_path || "";
        const fileSource = String(ff.source || "soulseek").toLowerCase();
        const ft = (fileSource + " " + name + " " + (ff.codec||"") + " " + (ff.kind||"") ).toLowerCase();
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        if(f.source && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;

        const remote = ff.remote_path || "";
        const size = Number(ff.size || 0);
        const selInfo = view._slsk.selected.get(remote);
        const dlState = normalizeSlskDownloadState((selInfo && selInfo.download_state) || ff.download_state || "");
        const pills = [];
        if(fileSource) pills.push({text:fileSource});
        if(ext) pills.push(ext);
        if(bd) pills.push(String(bd) + " bit");
        if(sr) pills.push(String(Math.round(sr/100)/10) + " kHz");
        if(ff.bitrate) pills.push(String(ff.bitrate) + " kbps");
        if(size) pills.push(humanBytes(size));
        if(ff.codec) pills.push(String(ff.codec));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"soulseek",
          remote_path:remote,
          size:size,
          selectable:!dlState,
          selected:!dlState && view._slsk.selected.has(remote),
          pills:pills,
          onToggle: ()=>{
            if(dlState) return;
            if(view._slsk.selected.has(remote)) view._slsk.selected.delete(remote);
            else view._slsk.selected.set(remote, {remote_path: remote, size: size});
          }
        });
      }
      return items;
    };
    view._slsk.buildItems = build;
    return build();
  }

  function slskBrowseParentPath(path){
    const parts = String(path || "").split("\\").filter(Boolean);
    if(parts.length <= 1) return "";
    return parts.slice(0, -1).join("\\");
  }

  function libBuildBrowseItemsFromSlsk(user, allDirs, currentDir, selectedPath){
    const view = state.current;
    const prev = view._slskbrowse || null;
    const prevSel = (prev && prev.selected instanceof Map) ? prev.selected : new Map();
    view._slskbrowse = {
      user: user || "",
      dirs: Array.isArray(allDirs) ? allDirs : [],
      current_dir: String(currentDir || ""),
      selected_path: String(selectedPath || ""),
      selected: prevSel,
      downloadQueued: !!(prev && prev.downloadQueued),
      filter: ((state.libSearch && state.libSearch.filter) ? state.libSearch.filter : "")
    };

    const build = ()=>{
      const f = libParseFilter(view._slskbrowse.filter || "");
      const items = [];
      const cur = String(view._slskbrowse.current_dir || "");
      const dirs = Array.isArray(view._slskbrowse.dirs) ? view._slskbrowse.dirs : [];
      const curPrefix = cur ? (cur + "\\") : "";
      let curEntry = null;
      const childMap = new Map();

      for(const d of dirs){
        const dp = String((d && d.directory) || "");
        if(dp === cur){
          curEntry = d;
        }
        if(cur){
          if(!dp || dp === cur) continue;
          if(!dp.startsWith(curPrefix)) continue;
        }else if(!dp){
          continue;
        }
        const rest = cur ? dp.slice(curPrefix.length) : dp;
        if(!rest) continue;
        const parts = rest.split("\\").filter(Boolean);
        if(!parts.length) continue;
        const childName = parts[0];
        const childPath = cur ? (cur + "\\" + childName) : childName;
        let agg = childMap.get(childPath);
        if(!agg){
          agg = {name: childName, path: childPath, fileCount: 0, totalSize: 0};
          childMap.set(childPath, agg);
        }
        agg.fileCount += Number((d && d.total_files) || ((d && d.files) ? d.files.length : 0) || 0);
        agg.totalSize += Number((d && d.total_size) || 0);
      }

      const files = (curEntry && Array.isArray(curEntry.files)) ? curEntry.files : [];
      const selCount = view._slskbrowse.selected.size;
      const statusMsg = String(view._fileStatus || "");
      const downloadPills = [];
      if(selCount) downloadPills.push({text: String(selCount)});
      if(view._slskbrowse.downloadQueued) downloadPills.push({text:"Queued", tone:"warn"});

      if(statusMsg) items.push({kind:"info", label: statusMsg});
      if(cur){
        items.push({kind:"libsearch_file_action", label:"..", action:"slsk_browse_up"});
      }
      if(files.length){
        items.push({kind:"libsearch_file_action", label:"Download selected", action:"slsk_download", pills: downloadPills});
        items.push({kind:"libsearch_file_action", label:"Select all", action:"slsk_selectall"});
        items.push({kind:"libsearch_file_action", label:"Clear selection", action:"slsk_clear"});
      }

      const childDirs = Array.from(childMap.values()).sort((a,b)=> String(a.name || "").localeCompare(String(b.name || "")));
      for(const d of childDirs){
        const ft = (String(d.name || "") + " " + String(d.path || "")).toLowerCase();
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        const pills = [];
        if(d.fileCount) pills.push(String(d.fileCount) + " files");
        if(d.totalSize) pills.push(humanBytes(d.totalSize));
        items.push({
          kind:"slsk_browse_dir",
          label:String(d.name || "") || "(dir)",
          browse_path:String(d.path || ""),
          pills:pills
        });
      }

      for(const ff of files){
        const name = ff.name || ff.remote_path || "";
        const fileSource = String(ff.source || "soulseek").toLowerCase();
        const ft = (fileSource + " " + name + " " + (ff.codec||"") + " " + (ff.kind||"") ).toLowerCase();
        const ext = String(ff.ext || "").toLowerCase();
        const bd = Number(ff.bit_depth || 0);
        const sr = Number(ff.sample_rate || 0);
        if(f.source && fileSource !== f.source) continue;
        if(f.rest.length && !libTextHasAllTokens(ft, f.rest)) continue;
        if(f.exts.size && (!ext || !f.exts.has(ext))) continue;
        if(f.bitDepth && (!bd || bd !== f.bitDepth)) continue;
        if(f.sampleRate && (!sr || sr !== f.sampleRate)) continue;

        const remote = ff.remote_path || "";
        const size = Number(ff.size || 0);
        const selInfo = view._slskbrowse.selected.get(remote);
        const dlState = normalizeSlskDownloadState((selInfo && selInfo.download_state) || ff.download_state || "");
        const pills = [];
        if(ext) pills.push(ext);
        if(bd) pills.push(String(bd) + " bit");
        if(sr) pills.push(String(Math.round(sr/100)/10) + " kHz");
        if(ff.bitrate) pills.push(String(ff.bitrate) + " kbps");
        if(size) pills.push(humanBytes(size));
        if(ff.codec) pills.push(String(ff.codec));
        if(dlState) pills.push({text: slskDownloadLabel(dlState), tone: slskDownloadTone(dlState)});
        items.push({
          kind:"libsearch_file",
          label:name,
          source:"soulseek",
          remote_path:remote,
          size:size,
          selectable:!dlState,
          selected:!dlState && view._slskbrowse.selected.has(remote),
          pills:pills,
          onToggle: ()=>{
            if(dlState) return;
            if(view._slskbrowse.selected.has(remote)) view._slskbrowse.selected.delete(remote);
            else view._slskbrowse.selected.set(remote, {remote_path: remote, size: size});
          }
        });
      }

      return items;
    };

    view._slskbrowse.buildItems = build;
    return build();
  }

  async function viewLibSearchSlskBrowse(push, user, selectedDir){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Browse",
      source:"soulseek",
      load: async function(){
        const browseUser = user || "";
        const wantedDir = String(selectedDir || "");
        libSetFileStatus("Loading shares", "");
        try{
          const js = await apiGet("/api/soulseek/browse_user?user=" + encodeURIComponent(browseUser) + "&selected_dir=" + encodeURIComponent(wantedDir));
          if(!js || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load user shares");
          }
          const selectedPath = String(js.selected_dir || wantedDir || "");
          const currentDir = selectedPath ? slskBrowseParentPath(selectedPath) : "";
          libSetFileStatus("", "");
          const built = libBuildBrowseItemsFromSlsk(browseUser, js.dirs || [], currentDir, selectedPath);
          resetList(built);
          if(selectedPath){
            const idx = (state.items || []).findIndex(x=>x && x.kind === "slsk_browse_dir" && String(x.browse_path || "") === selectedPath);
            if(idx >= 0){
              state.sel = idx;
              renderList();
            }
          }
        }catch(e){
          libSetFileStatus("Error", "warn");
          resetList([{kind:"info", label:"Failed to load user shares"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  async function viewLibSearchYouTubeChannel(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_result_list",
      label:"Channel",
      source:"youtube",
      load: async function(){
        resetList([{kind:"info", label:"Loading channel"}]);
        try{
          const js = await apiGet("/api/youtube/channel?channel_id=" + encodeURIComponent(item.channel_id || ""));
          if(!js || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to load channel videos");
          }
          const vids = Array.isArray(js.results) ? js.results : [];
          const items2 = [];
          for(const r of vids){
            const pills = [{text:"YouTube"}];
            if(Number(r.file_count || 0) > 0) pills.push({text:String(r.file_count) + " files"});
            if(Number(r.size || 0) > 0) pills.push({text:humanBytes(Number(r.size || 0))});
            if(r.published) pills.push({text:String(r.published)});
            items2.push({kind:"libsearch_result", label:r.user || r.title || "Video", label_html:'<span class="artistStrong">' + escapeHtml(String(r.user || r.title || "Video")) + '</span>', sub_label:String(r.title || ""), source:"youtube", result_id:r.result_id || "", raw:r, pills:pills});
          }
          if(!items2.length) items2.push({kind:"info", label:"No channel videos found"});
          resetList(items2);
        }catch(e){
          resetList([{kind:"info", label:"Failed to load channel videos"}]);
          alert(String(e && e.message ? e.message : e));
        }
      }
    }, push);
  }

  async function viewLibSearchSlskFiles(push, item){
    showNowPlaying(false);
    await setView({
      kind:"libsearch_files",
      label:"Files",
      source:"soulseek",
      load: async function(){
        const user = item.user || "";
        const directory = item.directory || "";
        const files = item.files || [];
        libSetFileStatus("", "");
        resetList(libBuildFileItemsFromSlsk(user, directory, files));
      }
    }, push);
  }

async function viewRecently(push){
    showNowPlaying(false);
    await syncPlaybackFromServer();
    await setView({
      kind: "recently",
      label: "Recently Played",
      root: null,
      load: async function(){
        let rec = [];
        try{
          const js = await apiGet("/api/playback/recent");
          rec = (js && Array.isArray(js.recent)) ? js.recent : [];
        }catch(e){ rec = []; }
        const items = [];
        if(state.history.length){
          items.push({kind:"up", label:".."});
        }
        for(const r of rec){
          if(!r || !r.root_id || !r.rel) continue;
          const media = (r.media || "").toLowerCase();
          let label = "";
          if(media === "audio"){
            const a = (r.artist || "").trim();
            const t = (r.title || "").trim();
            if(a && t) label = a + " - " + t;
            else if(t) label = t;
            else label = (r.label || r.rel || "").split("/").slice(-1)[0];
          }else{
            label = (r.title || r.label || r.rel || "").split("/").slice(-1)[0];
          }
          const pills = [];
          const extText = (()=>{
            const ex = String(r.ext || "").trim().toLowerCase();
            if(ex) return ex;
            const rel = String(r.rel || "");
            const base = rel.split("/").slice(-1)[0] || "";
            const dot = base.lastIndexOf(".");
            return (dot > 0 && dot < (base.length - 1)) ? base.slice(dot + 1).toLowerCase() : "";
          })();
          if(r.streamed) pills.push("Streamed");
          if(extText) pills.push(extText);
          if(r.quality) pills.push(String(r.quality));
          items.push({
            kind: "recent_item",
            label: label || "item",
            pills: pills,
            media: media,
            rootId: r.root_id,
            rel: r.rel,
            position: (r.position || 0),
            playing: !!r.playing,
            nav: r.nav || {},
            title: r.title || "",
            artist: r.artist || "",
            album: r.album || "",
            art: r.art || "",
            source: r.source || "",
            ext: r.ext || "",
            quality: r.quality || "",
            streamed: !!r.streamed,
            playlist: (r.playlist || null)
          });
        }
        if(items.length === (state.history.length ? 1 : 0)){
          items.push({kind:"info", label:"Empty"});
        }
        resetList(items);
      }
    }, !!push);
  }


  function folderViewObj(root, rel, label){
    return {
      kind: "folder",
      label: label || (rel ? rel.split("/").slice(-1)[0] : ""),
      root: root,
      rel: rel || "",
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel);
        const js = await apiGet(url);
        const items = [];
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            items.push({kind:"dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file"){
            const mediaPill = e.media === "video" ? "video" : (e.media === "audio" ? "audio" : "");
            const pills = mediaPill ? [mediaPill] : [];
            items.push({kind:"file", label:e.name, pills: pills, rel:e.rel, root: root, media: e.media});
          }
        }
        resetList(items);
      }
    };
  }

  async function openNowFolder(){
    if(!state.now){
      showNowPlaying(false);
      await showRoots();
      return;
    }
    const cfg = await loadConfig();
    const root = (cfg.roots || []).find(r => r.id === state.now.rootId);
    if(!root){
      showNowPlaying(false);
      await showRoots();
      return;
    }

    let folderRel = "";
    try{
      const parts = (state.now.rel || "").split("/");
      parts.pop();
      folderRel = parts.join("/");
    }catch(e){ folderRel = ""; }

    state.root = root;
    state.history = [];
    state.current = null;

    if(folderRel){
      const segs = folderRel.split("/");
      state.history.push(folderViewObj(root, "", ""));
      for(let i = 0; i < segs.length - 1; i++){
        const rel = segs.slice(0, i + 1).join("/");
        state.history.push(folderViewObj(root, rel, segs[i]));
      }
    }

    showNowPlaying(false);
    await setView(folderViewObj(root, folderRel, folderRel ? folderRel.split("/").slice(-1)[0] : ""), false);
  }

  
  async function resumeFromServerNow(forceShow){
    await syncPlaybackFromServer();
    const sn = state.serverNow;
    if(!sn || !sn.root_id || !sn.rel){
      if(forceShow){
        showNowPlaying(false);
        await showRoots();
      }
      return;
    }

    // restore browsing context first so Menu goes back to where it was started
    if(sn.nav && sn.nav.root_id){
      await openNavContext(sn.nav);
    }

    if((sn.media || "") === "video"){
      try{
        if(sn.playlist && Array.isArray(sn.playlist.items) && sn.playlist.items.length){
          state.videoPlaylist = sn.playlist.items.map(x=>({kind:"file", media:"video", root:{id:x.root_id}, rel:x.rel, label:x.label || ""})).filter(x=>x.root.id && x.rel);
          const vi = isFinite(sn.playlist.index) ? Number(sn.playlist.index) : 0;
          state.videoIndex = Math.max(0, Math.min(state.videoPlaylist.length - 1, vi));
        }
      }catch(e){}
      await startVideoFromItem({kind:"file", media:"video", root:{id: sn.root_id}, rel: sn.rel, label: sn.label || ""}, true, (sn.position || 0));
      return;
    }

    // audio
    const it = {kind:"file", media:"audio", root:{id: sn.root_id}, rel: sn.rel, label: sn.label || ""};

    // Prefer server-provided playlist context (more reliable than rebuilding from the current view)
    let pl = null;
    let idx = -1;
    try{
      if(sn.playlist && Array.isArray(sn.playlist.items) && sn.playlist.items.length){
        pl = sn.playlist.items.map(x=>({kind:"file", media:"audio", root:{id:x.root_id}, rel:x.rel, label:x.label || ""})).filter(x=>x.root.id && x.rel);
        idx = isFinite(sn.playlist.index) ? Number(sn.playlist.index) : 0;
      }
    }catch(e){ pl = null; idx = -1; }

    if(!pl || !pl.length){
      pl = buildPlaylistFromItems(state.items);
      try{
        idx = pl.findIndex(x => x.rel === it.rel && x.root && x.root.id === it.root.id);
      }catch(e){ idx = -1; }
    }
    if(!pl || !pl.length){
      pl = [it];
      idx = 0;
    }else{
      idx = Math.max(0, Math.min(pl.length - 1, (idx >= 0 ? idx : 0)));
    }
    await startAudioFromItem(it, pl, idx, true, (sn.position || 0));
  }


async function goBack(){
    if(nowPlaying.style.display === "block"){
      if(seekMode){
        showNpPill(true);
      }else{
        npPillActivity(false);
      }
      showNowPlaying(false);
      await waitNowPlayingFade(220);
      return;
    }
    if(state.history.length){
      await runLibraryPageTransition(async ()=>{
        state.current = state.history.pop();
        setHeader();
        await state.current.load();
        if(state.pendingLibSearch && state.current && state.current.kind === "libsearch"){
          const p = state.pendingLibSearch;
          state.pendingLibSearch = null;
          try{
            if(p && p.q) state.libSearch.q = p.q;
            const inQ = document.getElementById("libSearchInput");
            if(inQ && p && p.q) inQ.value = p.q;
            if(p && p.engine && p.q){
              await libDoSearch(p.engine, p.q);
            }
          }catch(e){}
        }
      });
      return;
    }
    await runLibraryPageTransition(async ()=>{
      await showRoots();
    });
  }

  function buildPlaylistFromItems(items){
    const pl = [];
    for(const it of items){
      if(it.kind === "track" || (it.kind === "file" && it.media === "audio")){
        pl.push(it);
      }
    }
    return pl;
  }

  function buildVideoPlaylistFromItems(items){
    const pl = [];
    for(const it of items){
      if(it && it.kind === "file" && it.media === "video"){
        pl.push(it);
      }
    }
    return pl;
  }

  async function refreshNowPlayingMeta(item){
    if(!item) return;
    const rootId = item.root.id;
    const rel = item.rel;

    // establish a video playlist context from the current view so next/prev works
    try{
      const vpl = buildVideoPlaylistFromItems(state.items || []);
      if(vpl && vpl.length){
        state.videoPlaylist = vpl;
        const vidx = vpl.findIndex(x => x && x.rel === rel && x.root && x.root.id === rootId);
        state.videoIndex = (vidx >= 0 ? vidx : 0);
      }else{
        // fallback to a single-item playlist
        state.videoPlaylist = [item];
        state.videoIndex = 0;
      }
    }catch(e){
      state.videoPlaylist = [item];
      state.videoIndex = 0;
    }
    try{
      const meta = Object.assign({}, await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel)), {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
      state.now = {rootId: rootId, rel: rel, media: "audio", streamed: !!item.streamed};
      state.nowMeta = meta;
      saveResumeNowPlaying();
      await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: true, animatePill: true});
      npPillActivity(false);
      updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
      try{ syncMediaSessionControls(); }catch(e){}
      lastfmOnTrack(meta);
    }catch(e){}
  }
  let videoOverlayActive = false;


  function isVideoActive(){
    try{
      return !!(videoOverlayActive && npVideoOverlay && npVideo && npVideoOverlay.style.display !== "none" && npVideo.src);
    }catch(e){ return false; }
  }

  function wheelMedia(){
    return isVideoActive() ? npVideo : activeAudio;
  }

  function stopVideoOverlay(){
    if(!npVideoOverlay || !npVideo) return;

    // Only write playback state when a real video overlay is active.
    const wasActive = isVideoActive();

    if(wasActive){
      let d = 0;
      let t = 0;
      try{ d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? Number(npVideo.duration) : 0; }catch(e){ d = 0; }
      try{ t = (npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0; }catch(e){ t = 0; }
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "stop");
        }
      }catch(e){}
    }

    videoOverlayActive = false;
    try{ npVideo.pause(); }catch(e){}
    try{
      npVideo.removeAttribute("src");
      npVideo.load();
    }catch(e){}
    try{ npVideoOverlay.style.display = "none"; }catch(e){}
  }



  async function startVideoFromItem(item, forceShow, resumeTime){
    if(typeof forceShow !== "boolean") forceShow = true;
    if(forceShow) showNowPlaying(true);

    try{ if(activeAudio) activeAudio.pause(); }catch(e){}
    resetGaplessPrime();
    destroyHlsController("audio");

    if(npVideoOverlay) npVideoOverlay.style.display = "flex";
    videoOverlayActive = true;

    const rootId = item.root.id;
    const rel = item.rel;

    try{
      if(isVideoActive() && state.now && state.now.media === "video" && state.now.rootId === rootId && state.now.rel === rel){
        const rt0 = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
        if(rt0 > 0){
          try{ setTimeout(()=>{ resumeVideoViaSeekInputs(rt0); }, 200); }catch(e){}
        }
        if(forceShow) showNowPlaying(true);
        return;
      }
    }catch(e){}

    let meta = {};
    try{
      meta = Object.assign({}, await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel)), {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
    }catch(e){ meta = {}; }

    state.now = {rootId: rootId, rel: rel, media: "video", streamed: !!item.streamed};
    state.nowMeta = meta;
    saveResumeNowPlaying();

    await updateNowPlayingDisplay(meta, item.label || "Video", {animateArt: true, animatePill: true});
    updateMediaSession({title: meta.title || item.label || "Video", artist: meta.artist || "", album: meta.album || "", art: meta.art || ""});
    try{ syncMediaSessionControls(); }catch(e){}

    const src = hlsManifestUrl(rootId, rel);
    try{
      try{ npVideo.pause(); }catch(e){}
      destroyHlsController("video");
      npVideo.removeAttribute("src");
      try{ npVideo.load(); }catch(e){}
      applyVolume();
      await loadHlsIntoElement(npVideo, src, "video");

      const rt = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
      try{
        const pos0 = (rt > 0) ? rt : ((npVideo && isFinite(npVideo.currentTime)) ? Number(npVideo.currentTime) : 0);
        playbackMaybePost("video", rootId, rel, meta || {}, (pos0 || 0), null, true, "start");
      }catch(e){}

      const p = npVideo.play();
      try{ if(rt > 0) scheduleVideoResume(rt); }catch(e){}
      if(p && p.catch) p.catch(()=>{});
    }catch(e){}
  }



  async function startAudioFromItem(item, playlist, index, forceShow, resumeTime){
    if(typeof forceShow !== "boolean") forceShow = true;
    stopVideoOverlay();
    const rootId = item.root.id;
    const rel = item.rel;

    const same = state.now && state.now.rootId === rootId && state.now.rel === rel;
    if(same){
      state.playlist = playlist || state.playlist || [item];
      if(typeof index === "number") state.playIndex = index;
      ensurePlayOrder(false);
      if(forceShow) showNowPlaying(true);

      const meta = Object.assign({}, state.nowMeta || {}, {streamed: !!item.streamed, source: item.source || "", ext: item.ext || "", quality: item.quality || ""});
      await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: false, animatePill: false});
      updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
      try{ syncMediaSessionControls(); }catch(e){}
      lastfmOnTrack(meta);

      try{ applyVolume(); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}

      let playlistCtx = null;
      try{
        if(Array.isArray(state.playlist) && state.playlist.length){
          const items = state.playlist.slice(0, 500).map(it=>({
            root_id: (it.root && it.root.id) ? it.root.id : "",
            rel: it.rel || "",
            media: "audio",
            label: it.label || ""
          })).filter(x=>x.root_id && x.rel);
          playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
        }
      }catch(e){ playlistCtx = null; }

      playbackPost({
        media: "audio",
        root_id: rootId,
        rel: rel,
        playlist: playlistCtx,
        label: item.label || "",
        title: meta.title || "",
        artist: meta.artist || "",
        album: meta.album || "",
        art: meta.art || "",
        position: (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0,
        duration: (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : null,
        playing: (activeAudio && !activeAudio.paused),
        nav: captureNavContext(),
        event: "time"
      });

      preloadNextAudio();
      return;
    }

    if(forceShow) showNowPlaying(true);

    const meta = await apiGet("/api/library/filemeta?root_id=" + encodeURIComponent(rootId) + "&rel=" + encodeURIComponent(rel));
    const src = hlsManifestUrl(rootId, rel);

    try{ if(activeAudio) activeAudio.pause(); }catch(e){}
    destroyHlsController("audio");
    resetGaplessPrime();
    try{ activeAudio.removeAttribute("src"); activeAudio.load(); }catch(e){}

    try{ applyVolume(); }catch(e){}
    try{ enforceSingleAudio(); }catch(e){}

    await loadHlsIntoElement(activeAudio, src, "audio");

    const rt = (resumeTime && isFinite(resumeTime)) ? Number(resumeTime) : 0;
    if(rt > 0){
      try{
        await new Promise((resolve)=>{
          let done = false;
          const finish = ()=>{
            if(done) return;
            done = true;
            try{ activeAudio.removeEventListener("loadedmetadata", onMeta); }catch(e){}
            resolve();
          };
          const onMeta = ()=>finish();
          activeAudio.addEventListener("loadedmetadata", onMeta, {once:true});
          setTimeout(finish, 1200);
        });
        const maxT = (activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : rt;
        activeAudio.currentTime = Math.max(0, Math.min(rt, maxT));
      }catch(e){}
    }

    state.playlist = playlist || [item];
    state.playIndex = (typeof index === "number") ? index : 0;
    ensurePlayOrder(false);

    state.now = {rootId: rootId, rel: rel};
    state.nowMeta = meta;
    saveResumeNowPlaying();

    let playlistCtx = null;
    try{
      if(Array.isArray(state.playlist) && state.playlist.length){
        const items = state.playlist.slice(0, 500).map(it=>({
          root_id: (it.root && it.root.id) ? it.root.id : "",
          rel: it.rel || "",
          media: "audio",
          label: it.label || ""
        })).filter(x=>x.root_id && x.rel);
        playlistCtx = {items: items, index: (state.playIndex >= 0 ? state.playIndex : 0)};
      }
    }catch(e){ playlistCtx = null; }

    playbackPost({
      media: "audio",
      root_id: rootId,
      rel: rel,
      playlist: playlistCtx,
      label: item.label || "",
      title: meta.title || "",
      artist: meta.artist || "",
      album: meta.album || "",
      art: meta.art || "",
      position: (rt && isFinite(rt)) ? rt : 0,
      duration: (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : (meta && meta.duration ? meta.duration : null),
      playing: true,
      nav: captureNavContext(),
      event: "start"
    });

    await updateNowPlayingDisplay(meta, item.label || "Track", {animateArt: true, animatePill: true});
    updateMediaSession({title: meta.title, artist: meta.artist, album: meta.album, art: meta.art});
    try{ syncMediaSessionControls(); }catch(e){}
    lastfmOnTrack(meta);

    try{ ensurePlaybackAudioSession(); }catch(e){}
    try{
      await activeAudio.play();
      if(canMediaSession()) navigator.mediaSession.playbackState = "playing";
    }catch(e){
      if(canMediaSession()) navigator.mediaSession.playbackState = "paused";
    }

    setTimeout(()=>{ try{ preloadNextAudio(); }catch(e){} }, 250);
  }

  function togglePlay(){
    if(!isVideoActive() && !state.now) return;
    const m = wheelMedia();
    if(!m) return;
    if(m.paused){

      try{ m.play().catch(()=>{}); }catch(e){}
      if(!isVideoActive() && canMediaSession()) navigator.mediaSession.playbackState = "playing";
      try{ syncMediaSessionControls(); }catch(e){}
    }else{
      try{ m.pause(); }catch(e){}
      if(!isVideoActive() && canMediaSession()) navigator.mediaSession.playbackState = "paused";
      try{ syncMediaSessionControls(); }catch(e){}
    }
  }

  function seek(delta){
    if(nowPlaying.style.display !== "block") return;
    const m = wheelMedia();
    if(!m) return;
    const d = m.duration || 0;
    const t = m.currentTime || 0;
    const nt = Math.max(0, Math.min(d || (t + delta), t + delta));
    try{ m.currentTime = nt; }catch(e){}
    if(seekMode){
      seekPreview = nt;
      seekChanged = true;
      updateSeekIndicator();
      resetSeekIdle();
    }
  }

  function ensurePlayOrder(forceRebuild){
    if(!state.shuffleEnabled){
      state.playOrder = null;
      state.orderPos = 0;
      state.playOrderPlaylist = null;
      return;
    }
    const pl = state.playlist || [];
    const n = pl.length || 0;
    if(n <= 0){
      state.playOrder = [];
      state.orderPos = 0;
      state.playOrderPlaylist = pl;
      return;
    }
    const idx = (typeof state.playIndex === "number" && state.playIndex >= 0 && state.playIndex < n) ? state.playIndex : 0;

    const same = (!forceRebuild &&
      state.playOrderPlaylist === pl &&
      Array.isArray(state.playOrder) &&
      state.playOrder.length === n);

    if(same){
      const p = state.playOrder.indexOf(idx);
      if(p >= 0){
        state.orderPos = p;
        return;
      }
    }

    const rest = [];
    for(let i=0;i<n;i++){
      if(i !== idx) rest.push(i);
    }
    for(let i=rest.length-1;i>0;i--){
      const j = Math.floor(Math.random() * (i + 1));
      const tmp = rest[i];
      rest[i] = rest[j];
      rest[j] = tmp;
    }
    state.playOrder = [idx].concat(rest);
    state.orderPos = 0;
    state.playOrderPlaylist = pl;
  }

  function nextIndexPeek(){
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const p = (state.orderPos || 0) + 1;
      if(p < state.playOrder.length) return state.playOrder[p];
      return null;
    }
    const ni = (state.playIndex || 0) + 1;
    if(ni >= 0 && ni < state.playlist.length) return ni;
    return null;
  }

  function prevIndexPeek(){
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const p = (state.orderPos || 0) - 1;
      if(p >= 0 && p < state.playOrder.length) return state.playOrder[p];
      return null;
    }
    const pi = (state.playIndex || 0) - 1;
    if(pi >= 0 && pi < state.playlist.length) return pi;
    return null;
  }

  function setShuffleEnabled(on){
    state.shuffleEnabled = !!on;
    try{ localStorage.setItem("debripod_shuffle", state.shuffleEnabled ? "1" : "0"); }catch(e){}
    ensurePlayOrder(true);
    preloadNextAudio();
    updateWheelLabels();
  }

  function toggleShuffle(){
    setShuffleEnabled(!state.shuffleEnabled);
  }

  async function playIndex(i, forceShow){
    if(i < 0 || i >= state.playlist.length) return;
    if(typeof forceShow !== "boolean") forceShow = (nowPlaying.style.display === "block");
    const item = state.playlist[i];
    state.playIndex = i;
    await startAudioFromItem(item, state.playlist, i, forceShow);
  }

  function playNext(){
    if(isSearchStreamActive()){
      const ni = (state.streamQueueIndex || 0) + 1;
      if(ni >= 0 && ni < state.streamQueue.length){
        playStreamQueueIndex(ni, true);
      }
      return;
    }
    if(!state.playlist.length) return;
    const ni = nextIndexPeek();
    if(ni === null) return;
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const np = (state.orderPos || 0) + 1;
      if(np >= 0 && np < state.playOrder.length) state.orderPos = np;
    }
    playIndex(ni);
  }

  function playPrev(){
    if(isSearchStreamActive()){
      const pi = (state.streamQueueIndex || 0) - 1;
      if(pi >= 0 && pi < state.streamQueue.length){
        playStreamQueueIndex(pi, true);
      }
      return;
    }
    if(!state.playlist.length) return;
    const pi = prevIndexPeek();
    if(pi === null) return;
    if(state.shuffleEnabled && Array.isArray(state.playOrder)){
      const pp = (state.orderPos || 0) - 1;
      if(pp >= 0 && pp < state.playOrder.length) state.orderPos = pp;
    }
    playIndex(pi);
  }


  function playVideoIndex(i, forceShow, resumeTime){
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length) return;
      if(i < 0 || i >= state.videoPlaylist.length) return;
      state.videoIndex = i;
      const it = state.videoPlaylist[i];
      startVideoFromItem(it, (typeof forceShow === "boolean" ? forceShow : true), (resumeTime || 0));
    }catch(e){}
  }

  function playVideoNext(){
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length){
        state.videoPlaylist = buildVideoPlaylistFromItems(state.items || []);
        state.videoIndex = 0;
      }
      const ni = (state.videoIndex || 0) + 1;
      if(ni >= 0 && ni < state.videoPlaylist.length){
        playVideoIndex(ni, true, 0);
      }
    }catch(e){}
  }

  function playVideoPrev(){
    try{
      if(!Array.isArray(state.videoPlaylist) || !state.videoPlaylist.length){
        state.videoPlaylist = buildVideoPlaylistFromItems(state.items || []);
        state.videoIndex = 0;
      }
      const pi = (state.videoIndex || 0) - 1;
      if(pi >= 0 && pi < state.videoPlaylist.length){
        playVideoIndex(pi, true, 0);
      }
    }catch(e){}
  }


  function wireAudio(el){
    el.addEventListener("timeupdate", ()=>{
      if(el !== activeAudio) return;
      const d = el.duration || 0;
      const t = el.currentTime || 0;
      if(d > 0){
        npSeek.value = Math.floor((t / d) * 1000);
      }
      try{ syncMediaSessionPosition(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      npCur.textContent = fmtTime(t);
      npDur.textContent = fmtTime(d);
      lastfmMaybeScrobble(false);
      try{ updateBufferedBarFor(el); }catch(e){}
      try{ enforceSingleAudio(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      try{ syncMediaSessionControls(); }catch(e){}
      try{
        if(state.now && state.now.rootId && state.now.rel){
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, (!activeAudio.paused), "time");
        }
      }catch(e){}
    });
    el.addEventListener("ended", ()=>{
      if(el !== activeAudio) return;
      lastfmMaybeScrobble(true);
      try{
        if(state.now && state.now.rootId && state.now.rel){
          const d = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
          const t = d || ((activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0);
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "ended");
        }
      }catch(e){}
      clearBufferedBar();
      playNext();
    });
    el.addEventListener("play", ()=>{
      if(el !== activeAudio) return;
      try{ ensureVisualizerAudioGraphFor(el); }catch(e){}
      updateVisualizerState();
      if(canMediaSession()) navigator.mediaSession.playbackState = "playing";
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      npPillActivity(false);
    });
    el.addEventListener("pause", ()=>{
      if(el !== activeAudio) return;
      updateVisualizerState();
      if(canMediaSession()) navigator.mediaSession.playbackState = "paused";
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      showNpPill(true);
      try{
        if(state.now && state.now.rootId && state.now.rel){
          const d = (activeAudio && activeAudio.duration && isFinite(activeAudio.duration)) ? activeAudio.duration : 0;
          const t = (activeAudio && isFinite(activeAudio.currentTime)) ? activeAudio.currentTime : 0;
          playbackMaybePost("audio", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "pause");
        }
      }catch(e){}
    });
  }
  try{ ensurePlaybackAudioSession(); }catch(e){}
  wireAudio(audioMain);
  try{ ensureVisualizerFrameLoop(); }catch(e){}
  if(npVideo){
    npVideo.addEventListener("timeupdate", ()=>{
      if(!isVideoActive()) return;
      const d = npVideo.duration || 0;
      const t = npVideo.currentTime || 0;
      if(d > 0){
        npSeek.value = Math.floor((t / d) * 1000);
      }
      try{ updateBufferedBarFor(npVideo); }catch(e){}
      npCur.textContent = fmtTime(t);
      npDur.textContent = fmtTime(d);
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, (!npVideo.paused), "time");
        }
      }catch(e){}
    });

    npVideo.addEventListener("play", ()=>{
      if(!isVideoActive()) return;
      try{ ensureVisualizerAudioGraphFor(npVideo); }catch(e){}
      updateVisualizerState();
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      npPillActivity(false);
    });

    npVideo.addEventListener("pause", ()=>{
      if(!isVideoActive()) return;
      updateVisualizerState();
      try{ syncMediaSessionControls(); }catch(e){}
      try{ syncMediaSessionPosition(); }catch(e){}
      showNpPill(true);
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          const d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? npVideo.duration : 0;
          const t = (npVideo && isFinite(npVideo.currentTime)) ? npVideo.currentTime : 0;
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "pause");
        }
      }catch(e){}
    });

    npVideo.addEventListener("ended", ()=>{
      if(!isVideoActive()) return;
      updateVisualizerState();
      try{
        if(state.now && state.now.media === "video" && state.now.rootId && state.now.rel){
          const d = (npVideo && npVideo.duration && isFinite(npVideo.duration)) ? npVideo.duration : 0;
          const t = d || ((npVideo && isFinite(npVideo.currentTime)) ? npVideo.currentTime : 0);
          playbackMaybePost("video", state.now.rootId, state.now.rel, state.nowMeta || {}, t, d, false, "ended");
        }
      }catch(e){}
      if(isSearchStreamActive()) playNext();
    });
  }

  npSeek.addEventListener("input", ()=>{
    const m = wheelMedia();
    const d = (m && m.duration) ? m.duration : 0;
    if(d > 0){
      try{ m.currentTime = (parseInt(npSeek.value, 10) / 1000) * d; }catch(e){}
    }
  });

  // ===== views =====
  async function viewFolder(root, rel, label, push){
    showNowPlaying(false);
    await setView({
      kind: "folder",
      label: label || (rel ? rel.split("/").slice(-1)[0] : ""),
      root: root,
      rel: rel || "",
      load: async function(){
        const url = "/api/library/browse?root_id=" + encodeURIComponent(root.id) + "&rel=" + encodeURIComponent(this.rel);
        const js = await apiGet(url);
        const items = [];
        if(state.history.length || this.rel){
          items.push({kind:"up", label:".."});
        }
        for(const e of (js.entries || [])){
          if(e.type === "dir"){
            items.push({kind:"dir", label:e.name, rel:e.rel, root: root});
          }else if(e.type === "file"){
            const mediaPill = e.media === "video" ? "video" : (e.media === "audio" ? "audio" : "");
            const pills = mediaPill ? [mediaPill] : [];
            items.push({kind:"file", label:e.name, pills: pills, rel:e.rel, root: root, media: e.media});
          }
        }
        resetList(items);
      }
    }, !!push);
  }

  async function viewMetaTop(root, push){
    showNowPlaying(false);
    await setView({
      kind: "metatop",
      label: "Browse",
      root: root,
      load: async function(){
        const js = await apiGet("/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=top");
        const items = [];
        for(const c of (js.categories || [])){
          items.push({kind:"metacat", label:c.label, cat:c.key, root: root, badge: js.building ? "indexing" : ""});
        }
        if(js.building){
          items.push({kind:"info", label:"Indexing media files in background..."});
        }
        resetList(items);
      }
    }, !!push);
  }

  async function viewMetaList(root, level, value, label, push){
    showNowPlaying(false);
    await setView({
      kind: "metalist",
      label: label || level,
      root: root,
      level: level,
      value: value || "",
      load: async function(){
        const url = "/api/library/metadata?root_id=" + encodeURIComponent(root.id) + "&level=" + encodeURIComponent(this.level) + (this.value ? "&value=" + encodeURIComponent(this.value) : "");
        const js = await apiGet(url);
        const items = [];
        if(this.level === "playlists"){
          items.push({kind:"playlist_create", label:"Create playlist"});
          items.push({kind:"smart_playlist_create", label:"Create smart playlist"});
        }
        if(this.level === "playlist_tracks"){
          items.push({kind:"playlist_edit_entry", label:(isSmartPlaylistRel(this.value || "") ? "Edit rules" : "Edit"), rel:(this.value || ""), playlistLabel:(this.label || ""), root: root});
        }
        for(const it of (js.items || [])){
          if(it.kind === "info"){
            items.push({kind:"info", label: it.label || ""});
            continue;
          }
          const out = Object.assign({}, it);
          out.root = root;
          items.push(out);
        }
        if(js.building){
          items.push({kind:"info", label:"Indexing media files in background..."});
        }
        resetList(items);
      }
    }, !!push);
  }

  function currentItem(){
    if(state.items.length === 0) return null;
    return state.items[state.sel] || null;
  }

  async function selectItem(forcedItem){
    const it = forcedItem || currentItem();
if(!it) return;
    if(it.kind === "info") return;

    if(it.kind === "libsearch_query" || it.kind === "libsearch_filter"){
      const field = (it.kind === "libsearch_filter") ? "filter" : "q";
      try{
        if(!state.libSearch) state.libSearch = {q:"", filter:"", engine:"combined", cache_key:"", result_source:"combined", last_count:0, results:[], knaben_results:[], slsk_users:[], editField:"", editValue:""};
        state.libSearch.editField = field;
        state.libSearch.editValue = (typeof state.libSearch[field] === "string") ? state.libSearch[field] : "";
        renderList();
        try{
          const activeEdit = libList ? libList.querySelector(".ipodItem.sel .libInlineInput") : null;
          if(activeEdit){
            activeEdit.focus();
            activeEdit.click();
            const n = activeEdit.value.length;
            activeEdit.setSelectionRange(n, n);
          }
        }catch(e){}
      }catch(e){}
      return;
    }

    if(it.kind === "playlist_create"){
      beginPlaylistCreateEdit();
      return;
    }

    if(it.kind === "smart_playlist_create"){
      beginSmartPlaylistCreateEdit();
      return;
    }

    if(it.kind === "playlist_edit_name"){
      beginPlaylistRenameEdit();
      return;
    }

    if(it.kind === "playlist_edit_entry"){
      if(isSmartPlaylistRel(it.rel || "")){
        await viewSmartPlaylistRules(it.root, it.rel || "", it.playlistLabel || it.label || "Playlist", true);
      }else{
        await viewPlaylistEditMenu(it.root, it.rel || "", it.playlistLabel || it.label || "Playlist", true);
      }
      return;
    }

    if(it.kind === "smart_playlist_rules_entry"){
      const cur = state.current || {};
      await viewSmartPlaylistRules(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", true);
      return;
    }

    if(it.kind === "smart_playlist_rules_save"){
      await saveSmartPlaylistRules();
      return;
    }

    if(it.kind === "smart_playlist_rules_cancel"){
      await goBack();
      return;
    }

    if(it.kind === "playlist_edit_add"){
      const cur = state.current || {};
      const startRel = playlistBrowseStartRel(cur.playlistRel || "");
      await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", startRel, true);
      return;
    }

    if(it.kind === "playlist_edit_remove"){
      const cur = state.current || {};
      await viewPlaylistRemoveSongs(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", true);
      return;
    }


    if(it.kind === "playlist_edit_delete"){
      const cur = state.current || {};
      await viewPlaylistDeleteConfirm(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", "playlist_edit_menu", true);
      return;
    }

    if(it.kind === "smart_playlist_rules_delete"){
      const cur = state.current || {};
      await viewPlaylistDeleteConfirm(cur.root, cur.playlistRel || "", cur.playlistLabel || "Playlist", "smart_playlist_rules", true);
      return;
    }

    if(it.kind === "playlist_delete_no"){
      await goBack();
      return;
    }

    if(it.kind === "playlist_delete_yes"){
      await confirmDeletePlaylist();
      return;
    }

    if(it.kind === "playlist_add_dir"){
      const cur = state.current || {};
      await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", it.rel || "", true);
      return;
    }

    if(it.kind === "playlist_add_selectall"){
      const cur = state.current || {};
      const rels = (state.items || []).filter(x => x && x.kind === "playlist_add_file" && !x.selected).map(x => x.rel).filter(Boolean);
      if(!rels.length) return;
      try{
        await playlistAddSongsToCurrentView(rels);
        if(cur._added){
          for(const rp of rels) cur._added.add(String(rp));
        }
        await viewPlaylistAddSongs(cur.root, cur.playlistRel || "", cur.rel || "", false);
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_add_file"){
      if(it.selected) return;
      const cur = state.current || {};
      try{
        await playlistAddSongsToCurrentView([it.rel || ""]);
        if(cur._added && it.rel) cur._added.add(String(it.rel));
        it.selected = true;
        renderList();
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_remove_selectall"){
      const cur = state.current || {};
      if(!cur.selected) cur.selected = new Set();
      const tracks = (state.items || []).filter(x => x && x.kind === "playlist_remove_track");
      let anyUnsel = false;
      for(const tr of tracks){
        if(tr && tr.rel && !cur.selected.has(String(tr.rel))){
          anyUnsel = true;
          break;
        }
      }
      if(anyUnsel){
        for(const tr of tracks){
          if(tr && tr.rel) cur.selected.add(String(tr.rel));
        }
      }else{
        for(const tr of tracks){
          if(tr && tr.rel) cur.selected.delete(String(tr.rel));
        }
      }
      refreshPlaylistRemoveSelectionUI();
      return;
    }

    if(it.kind === "playlist_remove_commit"){
      const cur = state.current || {};
      const rels = cur.selected ? Array.from(cur.selected.values()) : [];
      if(!rels.length) return;
      try{
        const res = await apiPost("/api/library/playlist_remove", {root_id: cur.root.id, rel: cur.playlistRel || "", tracks: rels});
        const js = (res && res.json) ? res.json : {};
        if(!res || !res.ok || !js.ok){
          throw new Error((js && js.error) ? js.error : "Failed to remove songs");
        }
        cur.selected = new Set();
        await viewMetaList(cur.root, "playlist_tracks", cur.playlistRel || "", cur.playlistLabel || "Playlist", false);
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "playlist_remove_track"){
      const cur = state.current || {};
      if(!cur.selected) cur.selected = new Set();
      const rp = String(it.rel || "");
      if(rp){
        if(cur.selected.has(rp)) cur.selected.delete(rp);
        else cur.selected.add(rp);
      }
      refreshPlaylistRemoveSelectionUI();
      return;
    }

    if(it.kind === "np_playlist_close"){
      await closeNowPlayingPlaylistMode();
      return;
    }

    if(it.kind === "np_playlist_entry"){
      if(it.selected) return;
      const cur = state.current || {};
      try{
        await addCurrentNowPlayingTrackToPlaylist(it.rel || "");
        if(cur._added && it.rel) cur._added.add(String(it.rel));
        it.selected = true;
        try{
          if(Array.isArray(it.pills) && it.pills.length){
            it.pills[0].text = "✓";
          }
        }catch(e){}
        renderList();
      }catch(e){
        alert(String(e && e.message ? e.message : e));
      }
      return;
    }

    if(it.kind === "random"){
      const idxs = [];
      for(let i=0;i<state.items.length;i++){
        const cand = state.items[i];
        if(_randomEligibleItem(cand)) idxs.push(i);
      }
      if(!idxs.length) return;
      const ri = idxs[Math.floor(Math.random() * idxs.length)];
      state.sel = ri;
      renderList();
      try{ await new Promise(r=>setTimeout(r, 20)); }catch(e){}
      await selectItem();
      return;
    }


    if(it.kind === "up"){
      await goBack();
      return;
    }
    
    if(it.kind === "libsearch_entry"){
      await viewLibSearch(true);
      return;
    }



if(it.kind === "libtasks_entry"){
  await viewLibTasks(true);
  return;
}

    if(it.kind === "libinfo_entry"){
      await viewLibInfo(true);
      return;
    }

    if(it.kind === "libsearch_action"){
      if(it.label === "Clear"){
        state.libSearch.q = "";
        state.libSearch.filter = "";
        state.libSearch.engine = "combined";
        state.libSearch.cache_key = "";
        state.libSearch.result_source = "combined";
        state.libSearch.results = [];
        state.libSearch.knaben_results = [];
        state.libSearch.slsk_users = [];
        state.libSearch.last_count = 0;
        libSetStatus("", "");
        await viewLibSearch(false);
        return;
      }
      if(it.label === "Search history"){
        await viewLibSearchHistory(true);
        return;
      }
      if(it.engine){
        await libDoSearch(it.engine, state.libSearch.q || "");
        return;
      }
    }

    
    if(it.kind === "libinfo_action"){
      if(it.action === "reindex"){
        await doLibraryReindex();
        await viewLibInfo(false);
        return;
      }
      if(it.action === "lastfm_login"){
        await startLastfmLoginFlow();
        await viewLibInfo(false);
        return;
      }
      if(it.action === "force_fullscreen"){
        await forceFullscreenOn();
        // keep menu open
        await viewLibInfo(false);
        return;
      }
      if(it.action === "binds_menu"){
        await viewLibBinds(true);
        return;
      }
      if(it.action === "toggle_visualizer"){
        setVisualizerEnabled(!visualizerEnabled);
        await viewLibInfo(false);
        return;
      }
    }

if(it.kind === "libsearch_history_action"){
      if(it.action === "clear_history"){
        try{
          const res = await apiPost("/api/search_history/clear", {});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to clear history");
          }
        }catch(e){
          alert(String(e && e.message ? e.message : e));
        }
        await viewLibSearchHistory(false);
        return;
      }
    }

    if(it.kind === "libsearch_history_entry"){
      state.pendingLibSearch = {engine: it.engine || "", q: it.q || ""};
      await goBack();
      return;
    }

    if(it.kind === "libsearch_result"){
      await viewLibSearchResultDetails(true, it);
      return;
    }

    if(it.kind === "libsearch_file_action"){
      const view = state.current || {};
      if((it.action === "result_selectall" || it.action === "result_clear" || it.action === "result_download" || it.action === "result_browse" || it.action === "result_stream") && view._searchResult){
        const target = view._searchResult;
        const src = String(target.source || "");
        if(it.action === "result_browse"){
          if(src === "soulseek"){
            target.loadingBrowse = true;
            libSearchRebuildFilesList(target.buildItems());
            try{
              await viewLibSearchSlskBrowse(true, String((target.result && target.result.user) || ""), String((target.result && target.result.directory) || ""));
            }catch(e){
              target.loadingBrowse = false;
              libSearchRebuildFilesList(target.buildItems());
              throw e;
            }
          }else if(src === "youtube"){
            await viewLibSearchYouTubeChannel(true, target.result || {});
          }
          return;
        }
        if(it.action === "result_selectall"){
          const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file" && x.selectable);
          let anyUnsel = false;
          for(const v of visible){
            const key = src === "knaben" ? ("file:" + String(v.file_id || v.label || "")) : (src === "youtube" ? ("itag:" + String(v.itag || v.file_id || v.label || "")) : String(v.remote_path || v.label || ""));
            if(key && !target.selected.has(key)){ anyUnsel = true; break; }
          }
          target.downloadQueued = false;
          if(anyUnsel){
            for(const v of visible){
              const key = src === "knaben" ? ("file:" + String(v.file_id || v.label || "")) : (src === "youtube" ? ("itag:" + String(v.itag || v.file_id || v.label || "")) : String(v.remote_path || v.label || ""));
              if(!key) continue;
              target.selected.set(key, {key:key, remote_path:String(v.remote_path || ""), file_id:String(v.file_id || ""), itag:String(v.itag || v.format_id || v.file_id || ""), format_id:String(v.format_id || v.itag || v.file_id || ""), size:Number(v.size || 0), name:String(v.label || ""), source:String(v.source || src || ""), ext:String(v.ext || ((((v.pills || [])[1] && typeof (v.pills || [])[1] === "string") ? (v.pills || [])[1] : "") || "")), quality:String(v.quality || ""), bitrate:String(v.bitrate || ""), media:String(v.media || ""), direct_url:String(v.direct_url || ""), url:String((target.result && target.result.url) || "")});
            }
          }else{
            for(const v of visible){
              const key = src === "knaben" ? ("file:" + String(v.file_id || v.label || "")) : (src === "youtube" ? ("itag:" + String(v.itag || v.file_id || v.label || "")) : String(v.remote_path || v.label || ""));
              if(key) target.selected.delete(key);
            }
          }
          libSearchRebuildFilesList(target.buildItems());
          return;
        }
        if(it.action === "result_clear"){
          target.selected = new Map();
          target.downloadQueued = false;
          libSearchRebuildFilesList(target.buildItems());
          return;
        }
        if(it.action === "result_stream"){
          if(!target.selected || target.selected.size === 0){
            libSetFileStatus("Select files", "warn");
            return;
          }
          libSetFileStatus("Preparing stream", "");
          try{
            const rr = target.result || {};
            const sel = Array.from(target.selected.values()).map(x=>({remote_path:x.remote_path || "", file_id:x.file_id || "", itag:x.itag || x.format_id || x.file_id || "", format_id:x.format_id || x.itag || x.file_id || "", size:x.size || 0, name:x.name || "", source:x.source || src || "", ext:x.ext || "", quality:x.quality || "", bitrate:x.bitrate || "", media:x.media || "", direct_url:x.direct_url || "", url:x.url || rr.url || ""}));
            const res = await apiPost("/api/libsearch/stream_selected", {
              source: src,
              torrent_id: rr.torrent_id || "",
              magnet: rr.magnet || "",
              url: rr.url || "",
              channel: rr.channel || rr.user || "",
              thumbnail: rr.thumbnail || rr.art || "",
              title: rr.title || rr.directory_title || rr.directory || "Search stream",
              selected: sel
            });
            const js = (res && res.json) ? res.json : {};
            if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to prepare stream");
            libSetFileStatus("", "");
            await startSearchStreamQueue(js.items || [], 0);
          }catch(e){
            libSetFileStatus("Error", "warn");
            alert(String(e && e.message ? e.message : e));
          }
          return;
        }
        if(it.action === "result_download"){
          if(!target.selected || target.selected.size === 0){
            libSetFileStatus("Select files", "warn");
            return;
          }
          libSetFileStatus("Queuing", "");
          try{
            if(src === "knaben"){
              const ids = Array.from(target.selected.values()).map(x=>String(x.file_id || "")).filter(Boolean);
              const rr = target.result || {};
              const res = await apiPost("/api/rd/enqueue_selected", {torrent_id: rr.torrent_id || "", file_ids: ids, title: rr.title || "Knaben item", magnet: rr.magnet || ""});
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
            }else if(src === "youtube"){
              const rr = target.result || {};
              const sel = Array.from(target.selected.values()).map(x=>({
                file_id:String(x.file_id || x.itag || x.format_id || ""),
                itag:String(x.itag || x.format_id || x.file_id || ""),
                format_id:String(x.format_id || x.itag || x.file_id || ""),
                name:String(x.name || x.title || x.label || ""),
                title:String(x.title || x.name || x.label || ""),
                ext:String(x.ext || ""),
                media:String(x.media || ""),
                direct_url:String(x.direct_url || ""),
                url:String(x.url || rr.url || ""),
                size:Number(x.size || 0)
              })).filter(x=>x.itag || x.format_id || x.file_id || x.url);
              const res = await apiPost("/api/youtube/enqueue", {
                title: rr.title || rr.directory_title || rr.name || "YouTube",
                url: rr.url || "",
                selected: sel
              });
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
              target.downloadQueued = true;
            }else if(src === "soulseek"){
              const rr = target.result || {};
              const sel = Array.from(target.selected.values()).map(x=>({remote_path:x.remote_path, size:x.size || 0})).filter(x=>x.remote_path);
              const dirPath = String(rr.directory || "");
              const dirBase = dirPath.split("\\").filter(Boolean).slice(-1)[0] || "";
              const title = "Soulseek: " + String(rr.user || "") + " " + dirBase;
              const res = await apiPost("/api/soulseek/enqueue", {user: rr.user || "", directory: dirPath, title: title, files: sel});
              const js = (res && res.json) ? res.json : {};
              if(!res || !res.ok || !js.ok) throw new Error((js && js.error) ? js.error : "Failed to queue download");
              for(const x of sel){
                const key = String(x.remote_path || "");
                if(!key) continue;
                target.selected.set(key, {key:key, remote_path:key, size:Number(x.size || 0), download_state:"queued"});
                try{
                  const srcFiles = Array.isArray(rr.files) ? rr.files : [];
                  const hit = srcFiles.find(fx => String((fx && fx.remote_path) || "") === key);
                  if(hit) hit.download_state = "queued";
                }catch(e){}
              }
            }
            libSetFileStatus("", "");
            libSearchRebuildFilesList(target.buildItems());
          }catch(e){
            libSetFileStatus("Error", "warn");
            alert(String(e && e.message ? e.message : e));
          }
          return;
        }
      }
      if(it.action === "rd_selectall" && view._rd){
        const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file");
        let anyUnsel = false;
        for(const v of visible){
          if(v && v.file_id && !view._rd.selected.has(String(v.file_id))){
            anyUnsel = true;
            break;
          }
        }
        if(anyUnsel){
          for(const v of visible){
            if(v && v.file_id) view._rd.selected.add(String(v.file_id));
          }
        }else{
          for(const v of visible){
            if(v && v.file_id) view._rd.selected.delete(String(v.file_id));
          }
        }
        libSearchRebuildFilesList(view._rd.buildItems());
        return;
      }
      if(it.action === "rd_clear" && view._rd){
        view._rd.selected = new Set();
        libSearchRebuildFilesList(view._rd.buildItems());
        return;
      }
      if(it.action === "rd_download" && view._rd){
        if(!view._rd.selected || view._rd.selected.size === 0){
          libSetFileStatus("Select files", "warn");
          return;
        }
        libSetFileStatus("Queuing", "");
        try{
          const ids = Array.from(view._rd.selected.values());
          const res = await apiPost("/api/rd/enqueue_selected", {torrent_id: view._rd.torrent_id, file_ids: ids, title: view._rd.title || "Knaben item", magnet: view._rd.magnet || ""});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to queue download");
          }
          libSetFileStatus("", "");
        }catch(e){
          libSetFileStatus("Error", "warn");
          alert(String(e && e.message ? e.message : e));
        }
        return;
      }

      if(it.action === "slsk_browse_user" && view._slsk){
        view._slsk.loadingBrowse = true;
        libSearchRebuildFilesList(view._slsk.buildItems());
        try{
          await viewLibSearchSlskBrowse(true, view._slsk.user || "", view._slsk.directory || "");
        }catch(e){
          view._slsk.loadingBrowse = false;
          libSearchRebuildFilesList(view._slsk.buildItems());
          throw e;
        }
        return;
      }
      if(it.action === "slsk_browse_up" && view._slskbrowse){
        view._slskbrowse.current_dir = slskBrowseParentPath(view._slskbrowse.current_dir || "");
        view._slskbrowse.selected_path = "";
        libSearchRebuildFilesList(view._slskbrowse.buildItems());
        return;
      }
      if(it.action === "slsk_selectall" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        target.downloadQueued = false;
        const visible = (state.items || []).filter(x=>x && x.kind === "libsearch_file");
        let anyUnsel = false;
        for(const v of visible){
          if(v && v.remote_path && !target.selected.has(String(v.remote_path))){
            anyUnsel = true;
            break;
          }
        }
        if(anyUnsel){
          for(const v of visible){
            if(v && v.remote_path){
              const rp = String(v.remote_path);
              target.selected.set(rp, {remote_path: rp, size: Number(v.size || 0)});
            }
          }
        }else{
          for(const v of visible){
            if(v && v.remote_path) target.selected.delete(String(v.remote_path));
          }
        }
        libSearchRebuildFilesList(target.buildItems());
        return;
      }
      if(it.action === "slsk_clear" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        target.selected = new Map();
        target.downloadQueued = false;
        libSearchRebuildFilesList(target.buildItems());
        return;
      }
      if(it.action === "slsk_download" && (view._slsk || view._slskbrowse)){
        const target = view._slsk || view._slskbrowse;
        if(!target.selected || target.selected.size === 0){
          libSetFileStatus("Select files", "warn");
          return;
        }
        libSetFileStatus("Queuing", "");
        try{
          const sel = Array.from(target.selected.values()).map(x=>({remote_path: x.remote_path, size: x.size || 0}));
          const dirPath = String((target.directory || target.current_dir) || "");
          const dirBase = dirPath.split("\\").filter(Boolean).slice(-1)[0] || "";
          const title = "Soulseek: " + (target.user || "") + " " + dirBase;
          const res = await apiPost("/api/soulseek/enqueue", {user: target.user || "", directory: dirPath, title: title, files: sel});
          const js = (res && res.json) ? res.json : {};
          if(!res || !res.ok || !js.ok){
            throw new Error((js && js.error) ? js.error : "Failed to queue download");
          }
          target.downloadQueued = true;
          if(typeof target.buildItems === "function") libSearchRebuildFilesList(target.buildItems());
          libSetFileStatus("", "");
        }catch(e){
          libSetFileStatus("Error", "warn");
          alert(String(e && e.message ? e.message : e));
        }
        return;
      }
    }

    if(it.kind === "libsearch_file"){
      if(it.selectable){
        try{
          if(typeof it.onToggle === "function") it.onToggle();
          else it.selected = !it.selected;
        }catch(e){}
        const view = state.current || {};
        if(view._searchResult && typeof view._searchResult.buildItems === "function"){
          libSearchRebuildFilesList(view._searchResult.buildItems());
        }else if(view._rd && typeof view._rd.buildItems === "function"){
          libSearchRebuildFilesList(view._rd.buildItems());
        }else if(view._slsk && typeof view._slsk.buildItems === "function"){
          libSearchRebuildFilesList(view._slsk.buildItems());
        }else if(view._slskbrowse && typeof view._slskbrowse.buildItems === "function"){
          libSearchRebuildFilesList(view._slskbrowse.buildItems());
        }else{
          renderList();
        }
        return;
      }
    }

    if(it.kind === "slsk_browse_dir") {
      const view = state.current || {};
      if(view._slskbrowse && typeof view._slskbrowse.buildItems === "function"){
        view._slskbrowse.current_dir = String(it.browse_path || "");
        view._slskbrowse.selected_path = "";
        libSearchRebuildFilesList(view._slskbrowse.buildItems());
      }
      return;
    }



if(it.kind === "libtasks_action"){
  if(it.action === "clear_all"){
    await apiPost("/api/tasks/clear_all", {});
    try{
      const js = await apiGet("/api/tasks");
      state.libTasks.tasks = (js && js.tasks) ? js.tasks : [];
    }catch(e){
      state.libTasks.tasks = [];
    }
    libTasksRefreshList(false);
    return;
  }
}

if(it.kind === "libtask_entry"){
  await viewLibTask(true, it.task_id || "");
  return;
}

if(it.kind === "libtask_action"){
  const view = state.current || {};
  const tid = String(view.task_id || "");
  if(!tid) return;

  if(it.action === "selectall"){
    const visible = (state.items || []).filter(x=>x && x.kind === "libtask_file");
    let anyUnsel = false;
    for(const v of visible){
      if(v && v.file_id && view.selected && !view.selected.has(String(v.file_id))){
        anyUnsel = true; break;
      }
    }
    if(!view.selected) view.selected = new Set();
    if(anyUnsel){
      for(const v of visible){
        if(v && v.file_id) view.selected.add(String(v.file_id));
      }
    }else{
      for(const v of visible){
        if(v && v.file_id) view.selected.delete(String(v.file_id));
      }
    }
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    state.items = libTaskBuildItemsForView(view);
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }

  if(it.action === "clear"){
    view.selected = new Set();
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    state.items = libTaskBuildItemsForView(view);
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }

  if(it.action === "pause_selected" || it.action === "cancel_selected"){
    if(!view.selected || view.selected.size === 0){
      return;
    }
    const action = (it.action === "pause_selected") ? "pause" : "cancel";
    for(const fid of Array.from(view.selected)){
      try{
        await apiPost("/api/tasks/file_action", {task_id: tid, file_id: String(fid), action: action});
      }catch(e){}
    }
    await libTasksPollTick();
    return;
  }

  if(it.action === "pause_task"){
    await apiPost("/api/tasks/pause", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "resume_task"){
    await apiPost("/api/tasks/resume", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "cancel_task"){
    await apiPost("/api/tasks/cancel", {task_id: tid});
    await libTasksPollTick();
    return;
  }
  if(it.action === "clear_task"){
    await apiPost("/api/tasks/clear", {task_id: tid});
    await libTasksPollTick();
    return;
  }
}

if(it.kind === "libtask_file"){
  if(it.selectable){
    try{
      if(typeof it.onToggle === "function") it.onToggle();
      else it.selected = !it.selected;
    }catch(e){}
    const view = state.current || {};
    const prevSel = state.sel;
    const prevScroll = (libList ? libList.scrollTop : 0);
    state.items = libTaskBuildItemsForView(view);
    const max = Math.max(0, state.items.length - 1);
    state.sel = Math.max(0, Math.min(max, prevSel));
    setHeader();
    renderList();
    try{ if(libList) libList.scrollTop = prevScroll; }catch(e){}
    return;
  }
}

if(it.kind === "root"){
      state.root = it.root;
      setHeader();
      if((it.root.mode || "folders") === "metadata"){
        await viewMetaTop(it.root, true);
      }else{
        await viewFolder(it.root, "", "", true);
      }
      return;
    }
    if(it.kind === "nowplaying"){
      await resumeFromServerNow(true);
      showNowPlaying(true);
      return;
    }
    if(it.kind === "recently"){
      await viewRecently(true);
      return;
    }
    if(it.kind === "recent_item"){
      // Restore the last browsing context first, then play
      const nav = (it.nav && typeof it.nav === "object") ? it.nav : {};
      if(nav && nav.root_id){
        await openNavContext(nav);
      }else{
        // fallback to folder containing the file
        try{
          const cfg = await loadConfig();
          const root = (cfg.roots || []).find(r => r.id === it.rootId);
          if(root){
            let folderRel = "";
            try{
              const parts = (it.rel || "").split("/");
              parts.pop();
              folderRel = parts.join("/");
            }catch(e){ folderRel = ""; }
            state.root = root;
            state.history = [];
            state.current = null;
            if(folderRel){
              const segs = folderRel.split("/");
              state.history.push(folderViewObj(root, "", ""));
              for(let i = 0; i < segs.length - 1; i++){
                const r = segs.slice(0, i + 1).join("/");
                state.history.push(folderViewObj(root, r, segs[i]));
              }
            }
            showNowPlaying(false);
            await setView(folderViewObj(root, folderRel, folderRel ? folderRel.split("/").slice(-1)[0] : ""), false);
          }
        }catch(e){}
      }

      // If selecting current now playing while it is still playing, just open it
      const sn = state.serverNow;
      const sameAsServer = (sn && sn.root_id === it.rootId && sn.rel === it.rel && (sn.media || "") === it.media);
      if(it.media === "audio"){
        const itemObj = {kind:"file", media:"audio", root:{id: it.rootId}, rel: it.rel, label: it.label};
        let pl = null;
        let idx = -1;
        try{
          if(it.playlist && Array.isArray(it.playlist.items) && it.playlist.items.length){
            pl = it.playlist.items.map(x=>({kind:"file", media:String(x.media || "audio"), root:{id:x.root_id}, rel:x.rel, label:x.label || "", streamed:!!x.streamed, source:x.source || "", ext:x.ext || "", quality:x.quality || ""})).filter(x=>x.root.id && x.rel);
            idx = isFinite(it.playlist.index) ? Number(it.playlist.index) : 0;
          }
        }catch(e){ pl = null; idx = -1; }
        if(!pl || !pl.length){
          pl = buildPlaylistFromItems(state.items);
          try{
            idx = pl.findIndex(x => x.rel === itemObj.rel && x.root && x.root.id === itemObj.root.id);
          }catch(e){ idx = -1; }
        }
        if(!pl || !pl.length){
          pl = [itemObj];
          idx = 0;
        }else{
          idx = Math.max(0, Math.min(pl.length - 1, (idx >= 0 ? idx : 0)));
        }
        const resume = (sameAsServer && state.serverNow && state.serverNow.playing && isFinite(state.serverNow.position)) ? Number(state.serverNow.position) : 0;
        if(itemObj.root.id === "__search_stream__") {
          state.streamQueue = pl;
          state.streamQueueIndex = idx;
        }
        await startAudioFromItem(itemObj, pl, idx, true, resume);
        return;
      }
      if(it.media === "video"){
        try{
          if(it.playlist && Array.isArray(it.playlist.items) && it.playlist.items.length){
            state.videoPlaylist = it.playlist.items.map(x=>({kind:"file", media:String(x.media || "video"), root:{id:x.root_id}, rel:x.rel, label:x.label || "", streamed:!!x.streamed, source:x.source || "", ext:x.ext || "", quality:x.quality || ""})).filter(x=>x.root.id && x.rel);
            const vi = isFinite(it.playlist.index) ? Number(it.playlist.index) : 0;
            state.videoIndex = Math.max(0, Math.min(state.videoPlaylist.length - 1, vi));
          }
        }catch(e){}
        const resume = (sameAsServer && state.serverNow && isFinite(state.serverNow.position)) ? Number(state.serverNow.position) : ((it.position && isFinite(it.position)) ? Number(it.position) : 0);
        if(it.rootId === "__search_stream__") {
          state.streamQueue = Array.isArray(state.videoPlaylist) ? state.videoPlaylist.slice() : [];
          state.streamQueueIndex = state.videoIndex || 0;
        }
        await startVideoFromItem({kind:"file", media:"video", root:{id: it.rootId}, rel: it.rel, label: it.label, streamed: !!it.streamed, source: it.source || "", ext: it.ext || "", quality: it.quality || ""}, true, resume);
        return;
      }
      return;
    }
    if(it.kind === "dir"){
      await viewFolder(it.root, it.rel, it.label, true);
      return;
    }
    if(it.kind === "metacat"){
      if(it.cat === "folders"){
        await viewFolder(it.root, "", "", true);
        return;
      }
      if(it.cat === "artists"){
        await viewMetaList(it.root, "artists", "", it.label, true);
        return;
      }
      if(it.cat === "albums"){
        await viewMetaList(it.root, "albums", "", it.label, true);
        return;
      }
      if(it.cat === "songs"){
        await viewMetaList(it.root, "songs", "", it.label, true);
        return;
      }
      if(it.cat === "liked_songs"){
        await viewMetaList(it.root, "liked_songs", "", it.label, true);
        return;
      }
      if(it.cat === "playlists"){
        await viewMetaList(it.root, "playlists", "", it.label, true);
        return;
      }
      if(it.cat === "genres"){
        await viewMetaList(it.root, "genres", "", it.label, true);
        return;
      }
      if(it.cat === "videos"){
        await viewMetaList(it.root, "videos", "", it.label, true);
        return;
      }
      return;
    }
    if(it.kind === "artist"){
      await viewMetaList(it.root, "albums", it.value, it.label, true);
      return;
    }
    if(it.kind === "album"){
      await viewMetaList(it.root, "tracks", it.value, it.label, true);
      return;
    }
    if(it.kind === "genre"){
      await viewMetaList(it.root, "genre_albums", it.value, it.label, true);
      return;
    }
    if(it.kind === "playlist"){
      await viewMetaList(it.root, "playlist_tracks", it.rel || "", it.label, true);
      return;
    }
    if(it.kind === "track"){
      const pl = buildPlaylistFromItems(state.items);
      const idx = pl.findIndex(x => x.rel === it.rel && x.root.id === it.root.id);
      await startAudioFromItem(it, pl, idx >= 0 ? idx : 0, true);
      return;
    }
    if(it.kind === "file"){
      if(it.media === "video"){
        await startVideoFromItem(it, true);
        return;
      }
      if(it.media === "audio"){
        const pl = buildPlaylistFromItems(state.items);
        const idx = pl.findIndex(x => x.rel === it.rel && x.root.id === it.root.id);
        await startAudioFromItem(it, pl, idx >= 0 ? idx : 0, true);
        return;
      }
    }
  }

  // ===== wheel controls =====
  const wheel = document.getElementById("wheel");
  const btnMenu = document.getElementById("btnMenu");
  const btnRev = document.getElementById("btnRev");
  const btnFwd = document.getElementById("btnFwd");
  const btnPlay = document.getElementById("btnPlay");
  const btnCenter = document.getElementById("btnCenter");

  
  const copyStreamBtn = document.getElementById("copyStreamBtn");
  if(copyStreamBtn){
    copyStreamBtn.addEventListener("click", ()=>{
      const el = document.getElementById("directStreamLink");
      if(!el) return;
      try{
        el.focus();
        el.select();
        el.setSelectionRange(0, el.value.length);
      }catch(e){}
      const txt = el.value;
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(txt).catch(()=>{ try{ document.execCommand("copy"); }catch(e){} });
      }else{
        try{ document.execCommand("copy"); }catch(e){}
      }
    });
  }
btnMenu.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return;
    vibeTick();
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block") npPillActivity(false);
    if(nowPlaying.style.display === "block" && seekMode && !isVideoActive() && lastfmIsEnabled()){
      lastfmToggleLoved(lastfmState.meta);
      resetSeekIdle();
      return;
    }
    goBack();
  });

  function playButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && seekMode && !isVideoActive()){
      toggleShuffle();
      resetSeekIdle();
    }else{
      togglePlay();
    }
  }

  function revButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && seekMode){
      seek(-15);
      resetSeekIdle();
    }else{
      if(isVideoActive()){
        playVideoPrev();
      }else{
        playPrev();
      }
    }
  }

  function fwdButtonPress(){
    if(state.current && state.current.kind === "np_playlist_add") return;
    if(nowPlaying.style.display === "block" && seekMode){
      seek(15);
      resetSeekIdle();
    }else{
      if(isVideoActive()){
        playVideoNext();
      }else{
        playNext();
      }
    }
  }

  btnPlay.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); playButtonPress(); });
  btnRev.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); revButtonPress(); });
  btnFwd.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); fwdButtonPress(); });

  function centerPress(){
    if(nowPlaying.style.display === "block"){
      if(seekMode){
        if(!seekChanged && !isVideoActive()){
          const p = viewNowPlayingPlaylistMode();
          if(p && typeof p.catch === "function") p.catch(()=>{});
        }else{
          commitSeekMode();
        }
      }else{
        enterSeekMode();
      }
      return;
    }
    selectItem();
  }

  btnCenter.addEventListener("click", ()=>{ if(isWheelClickSuppressed()) return; vibeTick(); if(nowPlaying.style.display === "block") npPillActivity(false); centerPress(); });

  updateWheelLabels();

  // rotation scroll on wheel ring
  let wheelPointerDown = false;
  let dragging = false;
  let lastAngle = 0;
  let accum = 0;
  let wheelStartX = 0;
  let wheelStartY = 0;
  let wheelDownOnButton = false;
  let wheelClickSuppressUntil = 0;
  const step = 18;
  const dragPx = 8;

  function isWheelClickSuppressed(){
    return Date.now() < wheelClickSuppressUntil;
  }
  function suppressWheelClicks(ms){
    const dur = Number(ms || 0);
    const until = Date.now() + (dur > 0 ? dur : 0);
    if(until > wheelClickSuppressUntil) wheelClickSuppressUntil = until;
  }

  function angleFromEvent(ev){
    const rect = wheel.getBoundingClientRect();
    const cx = rect.left + rect.width/2;
    const cy = rect.top + rect.height/2;
    const x = (ev.clientX - cx);
    const y = (ev.clientY - cy);
    return Math.atan2(y, x) * 180 / Math.PI;
  }

  function normDelta(a, b){
    let d = a - b;
    while(d > 180) d -= 360;
    while(d < -180) d += 360;
    return d;
  }

  wheel.addEventListener("pointerdown", (ev)=>{
    wheelPointerDown = true;
    dragging = false;
    wheelDownOnButton = false;
    try{
      if(ev.target === btnCenter) wheelDownOnButton = true;
      else if(ev.target && ev.target.closest && ev.target.closest(".wheelBtn")) wheelDownOnButton = true;
    }catch(e){
      wheelDownOnButton = false;
    }
    wheelStartX = ev.clientX;
    wheelStartY = ev.clientY;
    lastAngle = angleFromEvent(ev);
    accum = 0;

    // Avoid capturing immediately so taps on buttons stay reliable.
    // If the user drags, we will capture on move after a small threshold.
  }, {passive:false});

  wheel.addEventListener("pointermove", (ev)=>{
    if(!wheelPointerDown) return;

    if(!dragging){
      const dx = (ev.clientX - wheelStartX);
      const dy = (ev.clientY - wheelStartY);
      const dist = Math.hypot(dx, dy);
      if(dist < dragPx) return;

      dragging = true;
      if(wheelDownOnButton){
        // User started on a button area but is dragging, treat as wheel rotation.
        suppressWheelClicks(450);
      }
      try{ wheel.setPointerCapture(ev.pointerId); }catch(e){}
      try{ ev.preventDefault(); }catch(e){}
    }

    if(!dragging) return;

    const ang = angleFromEvent(ev);
    const d = normDelta(ang, lastAngle);
    lastAngle = ang;
    accum += d;

    if(nowPlaying.style.display === "block"){
      if(seekMode){
        showNpPill(true);
      }else{
        npPillActivity(false);
      }
      if(Math.abs(accum) >= step){
        if(seekMode){
          adjustSeekPreview(accum > 0 ? 1 : -1);
        }else{
          adjustVolumeStep(accum > 0 ? 1 : -1);
        }
        accum = 0;
      }
      return;
    }

    if(Math.abs(accum) >= step){
      scrollSel(accum > 0 ? 1 : -1);
      accum = 0;
    }
  }, {passive:false});

  function wheelPointerEnd(){
    wheelPointerDown = false;
    dragging = false;
    wheelDownOnButton = false;
  }

  wheel.addEventListener("pointerup", wheelPointerEnd, {passive:false});
  wheel.addEventListener("pointercancel", wheelPointerEnd, {passive:false});

  // keyboard and mouse wheel bindings
  window.addEventListener("wheel", (ev)=>{
    // Let normal browser zoom and text input scrolling work.
    if(ev.ctrlKey) return;
    const tgt = ev.target;
    if(tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable)) return;

    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}


    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}

    ev.preventDefault();
    const dir = ev.deltaY > 0 ? 1 : -1;
    if(nowPlaying.style.display === "block"){
      if(seekMode){
        adjustSeekPreview(dir);
      }else{
        adjustVolumeStep(dir);
      }
    }else{
      scrollSel(dir);
    }
  }, {passive:false});

  window.addEventListener("keydown", (ev)=>{

    // Don't hijack typing inside inputs/textareas/selects/contenteditable elements
    const tgt = ev.target;
    if(tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable)) return;

    try{ if(isLibraryTabActive()) pathPillActivity(false); }catch(e){}

    const k = ev.key;

    // iPod clickwheel shortcuts
    // w = top, a = left, s = middle, space = bottom, d = right
    if(k === "w" || k === "W"){
      ev.preventDefault();
      if(state.current && state.current.kind === "np_playlist_add") return;
      goBack();
    }else if(k === "a" || k === "A"){
      ev.preventDefault();
      revButtonPress();
    }else if(k === "s" || k === "S"){
      ev.preventDefault();
      centerPress();
    }else if(k === " "){
      ev.preventDefault();
      if(state.current && state.current.kind === "np_playlist_add") return;
      playButtonPress();
    }else if(k === "d" || k === "D"){
      ev.preventDefault();
      fwdButtonPress();
    }else if(k === "q" || k === "Q"){
      ev.preventDefault();
      scrollSel(-1);
    }else if(k === "e" || k === "E"){
      ev.preventDefault();
      scrollSel(1);
    }else if(k === "ArrowUp"){
      ev.preventDefault();
      if(nowPlaying.style.display === "block"){
        if(seekMode){
          adjustSeekPreview(-1);
        }else{
          adjustVolumeStep(1);
        }
      }else{
        scrollSel(-1);
      }
    }else if(k === "ArrowDown"){
      ev.preventDefault();
      if(nowPlaying.style.display === "block"){
        if(seekMode){
          adjustSeekPreview(1);
        }else{
          adjustVolumeStep(-1);
        }
      }else{
        scrollSel(1);
      }
    }
  });



async function maybeOpenFromUrl(){
  try{
    const p = new URLSearchParams(location.search || "");
    const rid = (p.get("root_id") || "").trim();
    if(!rid) return;
    const rel = (p.get("rel") || "").trim();
    const cfg = await loadConfig();
    const root = (cfg.roots || []).find(r => r.id === rid);
    if(!root) return;
    await viewFolder(root, rel, rel ? rel.split("/").pop() : root.name, false);
  }catch(e){}
}


  function updateTopbarVar(){
    try{
      const tb = document.querySelector(".topbar");
      const h = tb ? tb.getBoundingClientRect().height : 0;
      document.documentElement.style.setProperty("--topbarH", (h ? (h + "px") : "0px"));
    }catch(e){}
  }
  window.addEventListener("resize", updateTopbarVar);
  window.addEventListener("load", syncWheelZoneHeight);
  updateTopbarVar();
  syncWheelZoneHeight();


  // start
  (async ()=>{
    await showRoots();
    await maybeOpenFromUrl();
    syncWheelZoneHeight();
  })().catch(()=>{});
})();
</script>
</body>
</html>
"""







@app.context_processor
def inject_helpers():
    return {"human_bytes": human_bytes, "human_rate": human_rate}


def render_shell(autorefresh: int = 0, **ctx) -> str:
    try:
        hostport = request.host
    except Exception:
        hostport = f"localhost:{PORT}"
    info_json = json.dumps({"version": VERSION, "host": HOST, "port": PORT, "ddir": DOWNLOAD_DIR, "sdir": SOULSEEK_DOWNLOAD_DIR})
    return render_template_string(
        SHELL_PAGE,
        hostport=hostport,
        port=PORT,
        ddir=DOWNLOAD_DIR,
        autorefresh=autorefresh,
        tasks_poll_ms=TASKS_POLL_MS,
        icon_v=ICON_VERSION,
        icon_png_b64=ICON_PNG_B64,
        info_json=info_json,
        **ctx,
    )
@app.route("/favicon.ico")
def favicon():
    return Response(status=204)


@app.route("/", methods=["GET"])
def index():
    return render_shell(autorefresh=0)


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





def _json_safe(v: Any, depth: int = 0) -> Any:
    # Make values safe for jsonify by converting unknown objects to strings.
    if depth > 6:
        return str(v)
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x, depth + 1) for x in list(v)]
    if isinstance(v, dict):
        out: Dict[str, Any] = {}
        for k, val in v.items():
            try:
                ks = str(k)
            except Exception:
                ks = "key"
            out[ks] = _json_safe(val, depth + 1)
        return out
    try:
        return str(v)
    except Exception:
        return "<?>"


def task_public_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "task_dir": t.task_dir,
        "created": t.created,
        "paused": bool(getattr(t, "paused", False)),
        "state": t.state,
        "message": t.message,
        "torrent_id": t.torrent_id,

"source": t.source,
"overall_done": int(t.overall_done or 0),
"overall_total": (int(t.overall_total) if t.overall_total is not None else None),
"slsk_user": t.slsk_user,
"slsk_directory": t.slsk_directory,
"slsk_files": _json_safe(list(t.slsk_files or [])),
        "rd_files": _json_safe(list(getattr(t, "rd_files", []) or [])),
        "downloaded_files": _json_safe(list(t.downloaded_files or [])),
        "current_file": t.current_file,
        "current_done": int(t.current_done or 0),
        "current_total": (int(t.current_total) if t.current_total is not None else None),
        "video_post_total": int(t.video_post_total or 0),
        "video_post_done": int(t.video_post_done or 0),
        "video_post_state": t.video_post_state,
        "video_post_message": t.video_post_message,
        "video_post_current_file": t.video_post_current_file,
        "video_post_current_done": int(t.video_post_current_done or 0),
        "video_post_current_total": (int(t.video_post_current_total) if t.video_post_current_total is not None else None),
        "downloads_complete": bool(t.downloads_complete),
    }



def clear_task(task_id: str) -> bool:
    task_id = (task_id or "").strip()
    if not task_id:
        return False

    src = "rd"
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        src = (t.source or "rd").lower()
        if t.state not in ("done", "error", "canceled"):
            try:
                t.cancel_event.set()
            except Exception:
                pass
        TASKS.pop(task_id, None)

    if src == "soulseek":
        try:
            svc = SOULSEEK_SERVICE
        except Exception:
            svc = None
        if svc:
            try:
                svc.abort_task(task_id)
            except Exception:
                pass

    return True



def clear_all_tasks() -> None:
    slsk_ids: List[str] = []
    with TASKS_LOCK:
        for t in list(TASKS.values()):
            if t.state not in ("done", "error", "canceled"):
                try:
                    t.cancel_event.set()
                except Exception:
                    pass
            if (t.source or "").lower() == "soulseek":
                slsk_ids.append(t.id)
        TASKS.clear()

    if slsk_ids:
        try:
            svc = SOULSEEK_SERVICE
        except Exception:
            svc = None
        if svc:
            for tid in slsk_ids:
                try:
                    svc.abort_task(tid)
                except Exception:
                    pass


@app.route("/api/tasks", methods=["GET"])
def api_tasks_list():
    out: List[dict] = []
    for t in list_tasks():
        try:
            out.append(task_public_dict(t))
        except Exception as e:
            try:
                out.append({
                    "id": getattr(t, "id", ""),
                    "title": getattr(t, "title", "Task"),
                    "task_dir": getattr(t, "task_dir", ""),
                    "created": getattr(t, "created", time.time()),
                    "paused": bool(getattr(t, "paused", False)),
                    "state": "error",
                    "message": "Task serialization error: " + str(e),
                    "torrent_id": getattr(t, "torrent_id", None),
                    "source": getattr(t, "source", "rd"),
                    "overall_done": 0,
                    "overall_total": None,
                    "slsk_user": "",
                    "slsk_directory": "",
                    "slsk_files": [],
                    "rd_files": [],
                    "downloaded_files": [],
                    "current_file": "",
                    "current_done": 0,
                    "current_total": None,
                    "video_post_total": 0,
                    "video_post_done": 0,
                    "video_post_state": "",
                    "video_post_message": "",
                    "video_post_current_file": "",
                    "video_post_current_done": 0,
                    "video_post_current_total": None,
                    "downloads_complete": False,
                })
            except Exception:
                continue
    return jsonify({"tasks": out})
@app.route("/api/tasks/pause", methods=["POST"])
def api_tasks_pause():
    data = request.get_json(silent=True) or {}
    task_id = (data.get("task_id") or "").strip()
    ok = pause_task(task_id)
    return jsonify({"ok": bool(ok)})


@app.route("/api/tasks/resume", methods=["POST"])
def api_tasks_resume():
    data = request.get_json(silent=True) or {}
    task_id = (data.get("task_id") or "").strip()
    ok = resume_task(task_id)
    return jsonify({"ok": bool(ok)})


@app.route("/api/tasks/file_action", methods=["POST"])
def api_tasks_file_action():
    data = request.get_json(silent=True) or {}
    task_id = (data.get("task_id") or "").strip()
    file_id = (data.get("file_id") or "").strip()
    action = (data.get("action") or "").strip()
    ok = task_file_action(task_id, file_id, action)
    return jsonify({"ok": bool(ok)})


@app.route("/api/tasks/cancel", methods=["POST"])
def api_tasks_cancel():
    data = request.get_json(silent=True) or {}
    tid = (data.get("task_id") or request.form.get("task_id") or "").strip()
    if not tid:
        return jsonify({"ok": False, "error": "missing task_id"}), 400
    ok = bool(cancel_task(tid))
    return jsonify({"ok": ok})


@app.route("/api/tasks/clear", methods=["POST"])
def api_tasks_clear():
    data = request.get_json(silent=True) or {}
    tid = (data.get("task_id") or request.form.get("task_id") or "").strip()
    if not tid:
        return jsonify({"ok": False, "error": "missing task_id"}), 400
    ok = bool(clear_task(tid))
    return jsonify({"ok": ok})


@app.route("/api/tasks/clear_all", methods=["POST"])
def api_tasks_clear_all():
    clear_all_tasks()
    return jsonify({"ok": True})

@app.route("/api/lastfm/nowplaying", methods=["POST"])
def api_lastfm_nowplaying():
    if not lastfm_enabled():
        return jsonify({"ok": False, "disabled": True})
    js = request.get_json(silent=True) or {}
    artist = str(js.get("artist") or "").strip()
    title = str(js.get("title") or "").strip()
    album = str(js.get("album") or "").strip()
    duration = js.get("duration")
    try:
        duration_i = int(float(str(duration))) if duration is not None and str(duration).strip() else None
    except Exception:
        duration_i = None

    if not artist or not title:
        return jsonify({"ok": False, "error": "missing artist or title"})

    _lastfm_async(lastfm_update_now_playing, artist, title, album, duration_i)
    return jsonify({"ok": True})


@app.route("/api/lastfm/scrobble", methods=["POST"])
def api_lastfm_scrobble():
    if not lastfm_enabled():
        return jsonify({"ok": False, "disabled": True})
    js = request.get_json(silent=True) or {}
    artist = str(js.get("artist") or "").strip()
    title = str(js.get("title") or "").strip()
    album = str(js.get("album") or "").strip()
    duration = js.get("duration")
    start_ts = js.get("start_ts")
    try:
        duration_i = int(float(str(duration))) if duration is not None and str(duration).strip() else None
    except Exception:
        duration_i = None
    try:
        start_i = int(float(str(start_ts))) if start_ts is not None and str(start_ts).strip() else None
    except Exception:
        start_i = None

    if not artist or not title:
        return jsonify({"ok": False, "error": "missing artist or title"})

    _lastfm_async(lastfm_scrobble, artist, title, album, duration_i, start_i)
    return jsonify({"ok": True})

@app.route("/api/lastfm/status", methods=["GET"])
def api_lastfm_status():
    return jsonify({"ok": True, "enabled": bool(lastfm_enabled()), "username": lastfm_username()})


@app.route("/api/lastfm/auth/start", methods=["GET"])
def api_lastfm_auth_start():
    if not (LASTFM_API_KEY or "").strip() or not (LASTFM_API_SECRET or "").strip():
        return jsonify({"ok": False, "error": "Last.fm API key/secret not configured"}), 400
    try:
        out = lastfm_auth_start()
        return jsonify({"ok": True, "auth_url": out.get("auth_url"), "token": out.get("token")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/lastfm/auth/finish", methods=["POST"])
def api_lastfm_auth_finish():
    if not (LASTFM_API_KEY or "").strip() or not (LASTFM_API_SECRET or "").strip():
        return jsonify({"ok": False, "error": "Last.fm API key/secret not configured"}), 400
    js = request.get_json(silent=True) or {}
    token = str(js.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "missing token"}), 400
    try:
        out = lastfm_auth_finish(token)
        return jsonify({"ok": True, "username": out.get("username")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/lastfm/loved", methods=["GET"])
def api_lastfm_loved():
    artist = str(request.args.get("artist") or "").strip()
    title = str(request.args.get("title") or "").strip()
    album = str(request.args.get("album") or "").strip()
    if not artist or not title:
        return jsonify({"ok": False, "error": "missing artist or title"}), 400

    local = bool(lastfm_is_loved(artist, title, album))
    if local:
        return jsonify({"ok": True, "loved": True})

    # If not known locally, do a best-effort remote check for the current track and
    # seed the local cache so the UI can show ♥ reliably.
    if lastfm_enabled():
        remote = lastfm_remote_is_loved(artist, title)
        if remote is True:
            lastfm_set_loved_local(artist, title, album, True)
            return jsonify({"ok": True, "loved": True})
        if remote is False:
            return jsonify({"ok": True, "loved": False})

    return jsonify({"ok": True, "loved": False})


@app.route("/api/lastfm/toggle_loved", methods=["POST"])
def api_lastfm_toggle_loved():
    js = request.get_json(silent=True) or {}
    artist = str(js.get("artist") or "").strip()
    title = str(js.get("title") or "").strip()
    album = str(js.get("album") or "").strip()
    if not artist or not title:
        return jsonify({"ok": False, "error": "missing artist or title"}), 400

    cur = bool(lastfm_is_loved(artist, title, album))
    loved = not cur

    # Optimistic local update so the UI can flip immediately.
    lastfm_set_loved_local(artist, title, album, loved)

    # Keep local and remote consistent: attempt the remote write now, and revert on failure.
    if lastfm_enabled():
        try:
            if loved:
                lastfm_love_track(artist, title)
            else:
                lastfm_unlove_track(artist, title)
        except Exception as e:
            try:
                app.logger.exception("Last.fm love/unlove failed")
            except Exception:
                pass
            # Revert local state if remote failed.
            lastfm_set_loved_local(artist, title, album, cur)
            return jsonify({"ok": False, "error": str(e) or "Last.fm update failed", "loved": bool(cur)}), 500

    return jsonify({"ok": True, "loved": bool(loved)})


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
