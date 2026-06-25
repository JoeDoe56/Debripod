from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple

from .metadata import file_meta_cached, warm_art_palette, warm_audio_analysis, warm_video_analysis
from .library_db import clear_library_cache, load_index_snapshot, load_library_facets, root_manifest, root_version, root_versions, save_index_snapshot
from .roots import root_by_id
from ..media_types import AUDIO_EXTS, VIDEO_EXTS
from ..utils import sha1_text

_cache_dir_name_provider = lambda: "_debripod_cache"
_ENRICH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="debripod-enrich")
_ENRICH_LOCK = threading.Lock()
_ENRICH_QUEUED: set[str] = set()


def configure_library_index(*, cache_dir_name_provider) -> None:
    global _cache_dir_name_provider
    _cache_dir_name_provider = cache_dir_name_provider


def _cache_dir_name() -> str:
    return str(_cache_dir_name_provider() or "_debripod_cache")


def _queue_video_enrichment(abs_path: str, root_id: str, rel: str, media_id: str, duration) -> None:
    key = f"video:{root_id}:{rel}"
    with _ENRICH_LOCK:
        if key in _ENRICH_QUEUED:
            return
        _ENRICH_QUEUED.add(key)

    def run() -> None:
        try:
            try:
                warm_art_palette(abs_path, root_id=root_id, rel=rel)
            except Exception:
                pass
            try:
                warm_video_analysis(abs_path, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
            except Exception:
                pass
        finally:
            with _ENRICH_LOCK:
                _ENRICH_QUEUED.discard(key)

    try:
        _ENRICH_EXECUTOR.submit(run)
    except Exception:
        with _ENRICH_LOCK:
            _ENRICH_QUEUED.discard(key)

def build_index_for_root(root_abs: str, *, full_video_sync: bool = False, progress=None) -> dict:
    tracks = []
    videos = []
    folder_entries = []
    root_id_for_items = sha1_text(os.path.abspath(root_abs))
    total_playable = 0
    processed_playable = 0
    if progress:
        try:
            for base, dirs, files in os.walk(root_abs):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != _cache_dir_name()]
                total_playable += sum(1 for fn in files if os.path.splitext(fn)[1].lower() in AUDIO_EXTS or os.path.splitext(fn)[1].lower() in VIDEO_EXTS)
        except Exception:
            total_playable = 0
        try:
            progress(0, max(1, total_playable), "scan")
        except Exception:
            pass
    for base, dirs, files in os.walk(root_abs):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != _cache_dir_name()]
        rel_dir = os.path.relpath(base, root_abs).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir.strip("/")
        entries = []
        for d in sorted(dirs, key=lambda x: x.lower()):
            relp = f"{rel_dir}/{d}" if rel_dir else d
            entries.append({"type": "dir", "name": d, "rel": relp})
        playable_files = []
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in AUDIO_EXTS and ext not in VIDEO_EXTS:
                continue
            playable_files.append(fn)
        for fn in sorted(playable_files, key=lambda x: x.lower()):
            ext = os.path.splitext(fn)[1].lower()
            relp = f"{rel_dir}/{fn}" if rel_dir else fn
            entries.append({"type": "file", "name": fn, "rel": relp, "media": "video" if ext in VIDEO_EXTS else "audio"})
        folder_entries.append({"rel": rel_dir, "abs_path": base, "entries": entries})
        for fn in playable_files:
            ext = os.path.splitext(fn)[1].lower()
            abs_p = os.path.join(base, fn)
            rel = os.path.relpath(abs_p, root_abs).replace("\\", "/")
            if progress:
                try:
                    progress(processed_playable, max(1, total_playable), "metadata")
                except Exception:
                    pass
            if ext in VIDEO_EXTS:
                meta = file_meta_cached(abs_p)
                duration = meta.get("duration")
                media_id = f"{root_id_for_items}:{rel}"
                videos.append({"rel": rel, "name": fn, "title": meta.get("title") or fn, "duration": duration})
                if full_video_sync:
                    try:
                        warm_art_palette(abs_p, root_id=root_id_for_items, rel=rel)
                    except Exception:
                        pass
                    try:
                        warm_video_analysis(abs_p, root_id=root_id_for_items, rel=rel, media_id=media_id, duration=duration)
                    except Exception:
                        pass
                else:
                    _queue_video_enrichment(abs_p, root_id_for_items, rel, media_id, duration)
                processed_playable += 1
                if progress:
                    try:
                        progress(processed_playable, max(1, total_playable), "video analysis")
                    except Exception:
                        pass
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
                    "codec": meta.get("codec") or "",
                    "bit_depth": meta.get("bit_depth"),
                    "sample_rate": meta.get("sample_rate"),
                    "bitrate": meta.get("bitrate"),
                }
            )
            media_id = f"{root_id_for_items}:{rel}"
            try:
                warm_art_palette(abs_p, root_id=root_id_for_items, rel=rel)
            except Exception:
                pass
            try:
                warm_audio_analysis(abs_p, root_id=root_id_for_items, rel=rel, media_id=media_id, duration=duration)
            except Exception:
                pass
            processed_playable += 1
            if progress:
                try:
                    progress(processed_playable, max(1, total_playable), "audio analysis")
                except Exception:
                    pass
    return {"tracks": tracks, "videos": videos, "folder_entries": folder_entries}


def _save_index_to_sqlite(root_id: str, root_abs: str, data: dict, *, mode: str = "") -> int:
    version = 0
    try:
        version = save_index_snapshot(root_id, root_abs, data, mode=mode)
    except Exception:
        pass
    return version


def _load_index_from_sqlite(root_id: str, root_abs: str) -> Optional[dict]:
    try:
        data = load_index_snapshot(root_id, root_abs)
        if data is not None:
            return data
    except Exception:
        pass
    return None


def _clear_index_sqlite_cache() -> None:
    try:
        clear_library_cache()
    except Exception:
        pass


INDEX_CACHE: Dict[str, Tuple[float, dict]] = {}
INDEX_BUILDING: Dict[str, bool] = {}
INDEX_LOCK = threading.Lock()
WATCHERS: Dict[str, object] = {}
WATCHER_TIMERS: Dict[str, threading.Timer] = {}


def ensure_index_async(root_id: str, root_abs: str, *, mode: str = "", force: bool = False) -> None:
    now = time.time()
    with INDEX_LOCK:
        hit = INDEX_CACHE.get(root_id)
        if hit and not force:
            return
        if not hit:
            cached = _load_index_from_sqlite(root_id, root_abs)
            if cached is not None:
                INDEX_CACHE[root_id] = (now, cached)
                if not force:
                    return
        if INDEX_BUILDING.get(root_id):
            return
        INDEX_BUILDING[root_id] = True

    def build():
        try:
            data = build_index_for_root(root_abs)
            version = _save_index_to_sqlite(root_id, root_abs, data, mode=mode)
            if version:
                data["version"] = version
            with INDEX_LOCK:
                INDEX_CACHE[root_id] = (time.time(), data)
        finally:
            with INDEX_LOCK:
                INDEX_BUILDING[root_id] = False

    threading.Thread(target=build, daemon=True).start()


def watch_index_root(root_id: str, root_abs: str, *, mode: str = "") -> bool:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except Exception:
        return False
    root_id = str(root_id or "")
    root_abs = os.path.abspath(root_abs)
    if not root_id or not os.path.isdir(root_abs):
        return False
    with INDEX_LOCK:
        if root_id in WATCHERS:
            return True

    class LibraryIndexEventHandler(FileSystemEventHandler):
        def on_any_event(self, event):
            try:
                src = str(getattr(event, "src_path", "") or "")
                dest = str(getattr(event, "dest_path", "") or "")
                paths = [p for p in (src, dest) if p]
                if not paths:
                    return
                if any(_cache_dir_name() in os.path.normpath(p).split(os.sep) for p in paths):
                    return
                if not bool(getattr(event, "is_directory", False)):
                    exts = {os.path.splitext(p)[1].lower() for p in paths}
                    if not any(ext in AUDIO_EXTS or ext in VIDEO_EXTS for ext in exts):
                        return
                _debounce_watch_reindex(root_id, root_abs, mode)
            except Exception:
                pass

    try:
        observer = Observer()
        observer.schedule(LibraryIndexEventHandler(), root_abs, recursive=True)
        observer.daemon = True
        observer.start()
        with INDEX_LOCK:
            WATCHERS[root_id] = observer
        return True
    except Exception:
        return False


def _debounce_watch_reindex(root_id: str, root_abs: str, mode: str) -> None:
    def run():
        with INDEX_LOCK:
            WATCHER_TIMERS.pop(root_id, None)
        ensure_index_async(root_id, root_abs, mode=mode, force=True)

    with INDEX_LOCK:
        old = WATCHER_TIMERS.get(root_id)
        if old:
            try:
                old.cancel()
            except Exception:
                pass
        timer = threading.Timer(1.25, run)
        timer.daemon = True
        WATCHER_TIMERS[root_id] = timer
        timer.start()


def get_index(root_id: str) -> Optional[dict]:
    with INDEX_LOCK:
        hit = INDEX_CACHE.get(root_id)
        if hit:
            return hit[1]
    r = root_by_id(root_id)
    if not r:
        return None
    _, _, root_abs, _ = r
    cached = _load_index_from_sqlite(root_id, root_abs)
    if cached is None:
        return None
    with INDEX_LOCK:
        INDEX_CACHE[root_id] = (time.time(), cached)
    return cached


def track_sort_key(track_s: str) -> Tuple[int, str]:
    s = (track_s or "").strip()
    if not s:
        return (10**9, "")
    m = re.match(r"(\d+)", s)
    if not m:
        return (10**9, s)
    return (int(m.group(1)), s)




def clear_index_cache() -> None:
    with INDEX_LOCK:
        INDEX_CACHE.clear()
        INDEX_BUILDING.clear()
    _clear_index_sqlite_cache()


def index_building_status() -> Tuple[bool, Dict[str, bool]]:
    with INDEX_LOCK:
        roots_status = {str(k): bool(v) for k, v in (INDEX_BUILDING or {}).items()}
        any_building = any(roots_status.values())
    return any_building, roots_status


def set_index_cache(root_id: str, data: dict) -> None:
    with INDEX_LOCK:
        INDEX_CACHE[root_id] = (time.time(), data)
    try:
        r = root_by_id(root_id)
        if r:
            _, _, root_abs, mode = r
            version = _save_index_to_sqlite(root_id, root_abs, data, mode=mode)
            if version:
                data["version"] = version
    except Exception:
        pass


def library_root_versions() -> dict[str, int]:
    return root_versions()


def library_root_version(root_id: str) -> int:
    return root_version(root_id)


def library_manifest(root_id: str, *, since_version: int = 0) -> Optional[dict]:
    return root_manifest(root_id, since_version=since_version)


def library_metadata_facets(root_id: str) -> Optional[dict]:
    return load_library_facets(root_id, "metadata")


def library_watch_root(root_id: str, root_abs: str, *, mode: str = "") -> bool:
    return watch_index_root(root_id, root_abs, mode=mode)
