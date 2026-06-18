from __future__ import annotations

import os
import re
import threading
import time
from typing import Dict, Optional, Tuple

from .metadata import file_meta_cached
from .library_db import clear_library_cache, load_index_snapshot, root_manifest, root_version, root_versions, save_index_snapshot
from .roots import root_by_id
from ..media_types import AUDIO_EXTS, VIDEO_EXTS

_cache_dir_name_provider = lambda: "_debripod_cache"


def configure_library_index(*, cache_dir_name_provider) -> None:
    global _cache_dir_name_provider
    _cache_dir_name_provider = cache_dir_name_provider


def _cache_dir_name() -> str:
    return str(_cache_dir_name_provider() or "_debripod_cache")

def build_index_for_root(root_abs: str) -> dict:
    tracks = []
    videos = []
    for base, dirs, files in os.walk(root_abs):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != _cache_dir_name()]
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


def _save_index_to_disk(root_id: str, root_abs: str, data: dict, *, mode: str = "") -> int:
    version = 0
    try:
        version = save_index_snapshot(root_id, root_abs, data, mode=mode)
    except Exception:
        pass
    return version


def _load_index_from_disk(root_id: str, root_abs: str) -> Optional[dict]:
    try:
        data = load_index_snapshot(root_id, root_abs)
        if data is not None:
            return data
    except Exception:
        pass
    return None


def _clear_index_disk_cache() -> None:
    try:
        clear_library_cache()
    except Exception:
        pass


INDEX_CACHE: Dict[str, Tuple[float, dict]] = {}
INDEX_BUILDING: Dict[str, bool] = {}
INDEX_LOCK = threading.Lock()


def ensure_index_async(root_id: str, root_abs: str, *, mode: str = "") -> None:
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
            version = _save_index_to_disk(root_id, root_abs, data, mode=mode)
            if version:
                data["version"] = version
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
    _clear_index_disk_cache()


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
            version = _save_index_to_disk(root_id, root_abs, data, mode=mode)
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
