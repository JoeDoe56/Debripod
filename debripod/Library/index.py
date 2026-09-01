from __future__ import annotations

import os
import re
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple

from .metadata import art_identity_for_media, file_meta_cached, warm_art_palette, warm_audio_analysis, warm_video_audio_analysis, warm_video_frame_palette_analysis
from ..storage.tasks import metadata_for_path
from .library_db import clear_library_cache, load_index_snapshot, load_library_facets, load_show_aliases, root_manifest, root_version, root_versions, save_folder_entries, save_index_snapshot, save_show_aliases, update_media_art_identity
from .roots import source_origin_for_path
from .video_parse import classify_video_records, completion_percent, duration_text, is_canonical_video, parse_video_filename
from .tvmaze import enrich_cached_episode_metadata, schedule_episode_metadata_enrichment
from .roots import root_by_id
from ..media_types import AUDIO_EXTS, VIDEO_EXTS
from ..utils import sha1_text

_progress_provider = lambda _root_id, _rel: {}
_ENRICH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="debripod-enrich")
_ENRICH_LOCK = threading.Condition(threading.RLock())
_ENRICH_PAUSED = False
_ENRICH_QUEUED: set[str] = set()
_ENRICH_RUNNING: set[str] = set()
_ENRICH_STAGE_COUNTS: dict[str, int] = {}
_ENRICH_LAST: dict[str, object] = {"stage": "", "key": "", "finished_at": 0.0}
VIDEO_PARSE_VERSION = 2


def configure_library_index(*, progress_provider=None) -> None:
    global _progress_provider
    if progress_provider is not None:
        _progress_provider = progress_provider


def _cache_dir_name() -> str:
    return "_debripod_cache"


def _queue_enrichment(stage: str, key: str, func) -> None:
    stage_name = str(stage or "enrich")
    job_key = f"{stage_name}:{key}"
    with _ENRICH_LOCK:
        if job_key in _ENRICH_QUEUED or job_key in _ENRICH_RUNNING:
            return
        _ENRICH_QUEUED.add(job_key)
        _ENRICH_STAGE_COUNTS[stage_name] = int(_ENRICH_STAGE_COUNTS.get(stage_name) or 0) + 1

    def run() -> None:
        with _ENRICH_LOCK:
            while _ENRICH_PAUSED:
                _ENRICH_LOCK.wait()
            _ENRICH_QUEUED.discard(job_key)
            _ENRICH_RUNNING.add(job_key)
            _ENRICH_LAST["stage"] = stage_name
            _ENRICH_LAST["key"] = str(key or "")
        try:
            try:
                func()
            except Exception:
                pass
        finally:
            with _ENRICH_LOCK:
                _ENRICH_RUNNING.discard(job_key)
                _ENRICH_STAGE_COUNTS[stage_name] = max(0, int(_ENRICH_STAGE_COUNTS.get(stage_name) or 0) - 1)
                _ENRICH_LAST["finished_at"] = time.time()
                _ENRICH_LOCK.notify_all()

    try:
        _ENRICH_EXECUTOR.submit(run)
    except Exception:
        with _ENRICH_LOCK:
            _ENRICH_QUEUED.discard(job_key)
            _ENRICH_STAGE_COUNTS[stage_name] = max(0, int(_ENRICH_STAGE_COUNTS.get(stage_name) or 0) - 1)


def enrichment_status() -> dict:
    with _ENRICH_LOCK:
        return {
            "queued": len(_ENRICH_QUEUED),
            "running": len(_ENRICH_RUNNING),
            "stages": dict(_ENRICH_STAGE_COUNTS),
            "last": dict(_ENRICH_LAST),
            "paused": _ENRICH_PAUSED,
        }


@contextmanager
def pause_enrichment_writes():
    global _ENRICH_PAUSED
    with _ENRICH_LOCK:
        _ENRICH_PAUSED = True
        while _ENRICH_RUNNING:
            _ENRICH_LOCK.wait()
    try:
        yield
    finally:
        with _ENRICH_LOCK:
            _ENRICH_PAUSED = False
            _ENRICH_LOCK.notify_all()

def _media_group_key(record: dict) -> str:
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    album_artist = str(meta.get("album_artist") or meta.get("artist") or "").strip().lower()
    album = str(meta.get("album") or "").strip().lower()
    folder = os.path.dirname(str(record.get("rel") or "")).replace("\\", "/").strip("/").lower()
    media = str(record.get("media") or "")
    return "|".join([str(record.get("root_id") or ""), album_artist, album, folder, media])


def _queue_palette_group(group_key: str, records: list[dict]) -> None:
    clean = [dict(r) for r in records if isinstance(r, dict) and r.get("abs_path") and r.get("rel")]
    if not clean:
        return

    def run() -> None:
        identities: dict[str, dict] = {}
        for record in clean:
            info = art_identity_for_media(
                str(record.get("abs_path") or ""),
                root_id=str(record.get("root_id") or ""),
                rel=str(record.get("rel") or ""),
                meta=record.get("meta") if isinstance(record.get("meta"), dict) else None,
            )
            if not info:
                continue
            identity = str(info.get("art_identity") or info.get("cache_key") or "")
            if not identity:
                continue
            bucket = identities.setdefault(identity, {"info": info, "records": []})
            bucket["records"].append(record)
        for identity, bucket in identities.items():
            refs = bucket.get("records") or []
            first = refs[0] if refs else None
            if not first:
                continue
            palette = warm_art_palette(
                str(first.get("abs_path") or ""),
                root_id=str(first.get("root_id") or ""),
                rel=str(first.get("rel") or ""),
                art_info=bucket.get("info") if isinstance(bucket.get("info"), dict) else None,
                linked_count=len(refs),
            )
            if palette:
                rels = [str(r.get("rel") or "") for r in refs]
                update_media_art_identity(str(first.get("root_id") or ""), rels, identity)

    _queue_enrichment("stage3_album_cover_palette", group_key, run)


def _queue_index_enrichment(data: dict) -> None:
    jobs = data.get("_enrichment_jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, dict):
        return
    for group_key, records in (jobs.get("palette_groups") or {}).items():
        _queue_palette_group(str(group_key or ""), records if isinstance(records, list) else [])
    for record in jobs.get("music_audio") or []:
        if not isinstance(record, dict):
            continue
        _queue_enrichment(
            "stage4_music_audio_analysis",
            f"{record.get('root_id')}:{record.get('rel')}",
            lambda r=dict(record): warm_audio_analysis(str(r.get("abs_path") or ""), root_id=str(r.get("root_id") or ""), rel=str(r.get("rel") or ""), media_id=str(r.get("media_id") or ""), duration=r.get("duration")),
        )


def queue_audio_analysis_warm(abs_path: str, *, root_id: str, rel: str, media_id: str = "", duration=None) -> bool:
    record = {
        "abs_path": os.path.abspath(abs_path),
        "root_id": str(root_id or ""),
        "rel": str(rel or ""),
        "media_id": str(media_id or f"{root_id}:{rel}"),
        "duration": duration,
    }
    if not record["root_id"] or not record["rel"] or not os.path.isfile(record["abs_path"]):
        return False
    _queue_enrichment(
        "stage4_music_audio_analysis",
        f"{record.get('root_id')}:{record.get('rel')}",
        lambda r=dict(record): warm_audio_analysis(str(r.get("abs_path") or ""), root_id=str(r.get("root_id") or ""), rel=str(r.get("rel") or ""), media_id=str(r.get("media_id") or ""), duration=r.get("duration")),
    )
    return True


def queue_video_analysis_warm(abs_path: str, *, root_id: str, rel: str, media_id: str = "", duration=None) -> bool:
    record = {
        "abs_path": os.path.abspath(abs_path),
        "root_id": str(root_id or ""),
        "rel": str(rel or ""),
        "media_id": str(media_id or f"{root_id}:{rel}"),
        "duration": duration,
    }
    if not record["root_id"] or not record["rel"] or not os.path.isfile(record["abs_path"]):
        return False
    _queue_enrichment(
        "stage5_video_audio_analysis",
        f"{record.get('root_id')}:{record.get('rel')}",
        lambda r=dict(record): warm_video_audio_analysis(str(r.get("abs_path") or ""), root_id=str(r.get("root_id") or ""), rel=str(r.get("rel") or ""), media_id=str(r.get("media_id") or ""), duration=r.get("duration")),
    )
    _queue_enrichment(
        "stage6_video_frame_palette",
        f"{record.get('root_id')}:{record.get('rel')}",
        lambda r=dict(record): warm_video_frame_palette_analysis(str(r.get("abs_path") or ""), root_id=str(r.get("root_id") or ""), rel=str(r.get("rel") or ""), media_id=str(r.get("media_id") or ""), duration=r.get("duration")),
    )
    return True


class _IndexBuildCancelled(Exception):
    pass


def _raise_if_index_build_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _IndexBuildCancelled()


def build_index_for_root(
    root_abs: str,
    *,
    full_video_sync: bool = False,
    progress=None,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    tracks = []
    video_records = []
    folder_entries = []
    media_records: list[dict] = []
    root_abs_norm = os.path.abspath(root_abs)
    root_id_for_items = sha1_text(root_abs_norm)
    if progress:
        try:
            progress(0, 1, "stage 1 quick scan")
        except Exception:
            pass

    for base, dirs, files in os.walk(root_abs_norm):
        _raise_if_index_build_cancelled(cancel_event)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != _cache_dir_name()]
        rel_dir = os.path.relpath(base, root_abs_norm).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir.strip("/")
        entries = []
        for d in sorted(dirs, key=lambda x: x.lower()):
            relp = f"{rel_dir}/{d}" if rel_dir else d
            entries.append({"type": "dir", "name": d, "rel": relp})
        playable_files = []
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
                playable_files.append(fn)
        for fn in sorted(playable_files, key=lambda x: x.lower()):
            _raise_if_index_build_cancelled(cancel_event)
            ext = os.path.splitext(fn)[1].lower()
            relp = f"{rel_dir}/{fn}" if rel_dir else fn
            media = "video" if ext in VIDEO_EXTS else "audio"
            entries.append({"type": "file", "name": fn, "rel": relp, "media": media})
            media_records.append({
                "root_id": root_id_for_items,
                "abs_path": os.path.join(base, fn),
                "rel": relp,
                "name": fn,
                "media": media,
                "ext": ext,
            })
        folder = {"rel": rel_dir, "abs_path": base, "entries": entries}
        folder_entries.append(folder)
        try:
            save_folder_entries(root_id_for_items, rel_dir, base, entries)
        except Exception:
            pass

    total_playable = max(1, len(media_records))
    if progress:
        try:
            progress(0, total_playable, "stage 2 metadata")
        except Exception:
            pass

    palette_groups: dict[str, list[dict]] = {}
    music_audio_jobs: list[dict] = []
    processed_playable = 0
    for record in sorted(media_records, key=lambda r: str(r.get("rel") or "").lower()):
        _raise_if_index_build_cancelled(cancel_event)
        abs_p = str(record.get("abs_path") or "")
        rel = str(record.get("rel") or "")
        fn = str(record.get("name") or os.path.basename(abs_p))
        meta = file_meta_cached(abs_p)
        record["meta"] = meta
        duration = meta.get("duration") if isinstance(meta, dict) else None
        media_id = f"{root_id_for_items}:{rel}"
        record["media_id"] = media_id
        record["duration"] = duration
        if record.get("media") == "video":
            manifest = metadata_for_path(abs_p, root_abs_norm)
            source = str(manifest.get("source") or source_origin_for_path(abs_p) or "unknown").strip().lower()
            if source not in {"youtube", "debrid", "soulseek", "library", "unknown"}:
                source = "unknown"
            parent = os.path.dirname(rel).replace("\\", "/")
            parent_name = os.path.basename(parent)
            folder_title = os.path.basename(os.path.dirname(parent)) if re.match(r"(?i)^(?:season[ ._-]*\d+|s\d{1,2}|specials)$", parent_name) else parent_name
            parsed = parse_video_filename(rel, folder_title=folder_title, source=source, metadata=meta)
            try:
                file_size = os.path.getsize(abs_p)
            except OSError:
                file_size = 0
            progress_state = _progress_provider(root_id_for_items, rel) or {}
            generated_copy = bool(re.search(r"(?i)(?:[ ._-](?:browser|transcoded|compatible))\.[^.]+$", fn))
            video_records.append({
                "root_id": root_id_for_items,
                "rel": rel,
                "name": fn,
                "title": parsed.get("title") or ((meta.get("title") if isinstance(meta, dict) else "") or fn),
                "duration": duration,
                "duration_text": duration_text(duration),
                "source": source,
                "source_url": str(manifest.get("source_url") or ""),
                "manifest": manifest,
                "parse": parsed,
                "parse_version": VIDEO_PARSE_VERSION,
                "quality": parsed.get("quality") or "",
                "browser_friendly": bool(parsed.get("browser_friendly")),
                "completion_percent": completion_percent(progress_state, duration),
                "position": float(progress_state.get("position") or 0),
                "ended": bool(progress_state.get("ended")),
                "canonical": is_canonical_video(rel, size=file_size, duration=duration),
                "generated_copy": generated_copy,
                "size": file_size,
                "meta": dict(meta) if isinstance(meta, dict) else {},
            })
        else:
            audio_manifest = metadata_for_path(abs_p, root_abs_norm)
            audio_source = str(audio_manifest.get("source") or source_origin_for_path(abs_p) or "unknown").strip().lower()
            title = (meta.get("title") if isinstance(meta, dict) else "") or os.path.splitext(fn)[0]
            artist = ((meta.get("artist") if isinstance(meta, dict) else "") or "").strip()
            album_artist = ((meta.get("album_artist") if isinstance(meta, dict) else "") or artist or "").strip()
            artist = album_artist or artist
            album = ((meta.get("album") if isinstance(meta, dict) else "") or "").strip()
            genre = ((meta.get("genre") if isinstance(meta, dict) else "") or "").strip()
            track = ((meta.get("track") if isinstance(meta, dict) else "") or "").strip()
            tracks.append(
                {
                    "root_id": root_id_for_items,
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
                    "codec": meta.get("codec") if isinstance(meta, dict) else "",
                    "bit_depth": meta.get("bit_depth") if isinstance(meta, dict) else None,
                    "sample_rate": meta.get("sample_rate") if isinstance(meta, dict) else None,
                    "bitrate": meta.get("bitrate") if isinstance(meta, dict) else None,
                    "source": audio_source if audio_source in {"youtube", "debrid", "soulseek", "library", "unknown"} else "unknown",
                    "manifest": audio_manifest,
                }
            )
            music_audio_jobs.append(dict(record))
        palette_groups.setdefault(_media_group_key(record), []).append(dict(record))
        processed_playable += 1
        if progress:
            try:
                progress(processed_playable, total_playable, "stage 2 metadata")
            except Exception:
                pass

    # Metadata probing above only inspects stream headers.  It never invokes
    # video transcoding/analysis; that work remains playback-triggered.
    _raise_if_index_build_cancelled(cancel_event)
    enrich_cached_episode_metadata(video_records)
    aliases = load_show_aliases(root_id_for_items)
    movies, shows, videos, next_aliases = classify_video_records(video_records, aliases=aliases)
    save_show_aliases(root_id_for_items, next_aliases)
    return {
        "tracks": tracks,
        "videos": videos,
        "movies": movies,
        "shows": shows,
        "video_records": video_records,
        "folder_entries": folder_entries,
        "_enrichment_jobs": {
            "palette_groups": palette_groups,
            "music_audio": music_audio_jobs,
        },
    }


def _save_index_to_sqlite(
    root_id: str,
    root_abs: str,
    data: dict,
    *,
    mode: str = "",
    schedule_tvmaze: bool = True,
) -> int:
    version = 0
    try:
        version = save_index_snapshot(root_id, root_abs, data, mode=mode)
    except Exception:
        pass
    records = list(data.get("video_records") or [])
    if schedule_tvmaze and records:
        def persist_enriched() -> None:
            aliases = load_show_aliases(root_id)
            movies, shows, videos, next_aliases = classify_video_records(records, aliases=aliases)
            data["movies"] = movies
            data["shows"] = shows
            data["videos"] = videos
            save_show_aliases(root_id, next_aliases)
            refreshed_version = _save_index_to_sqlite(
                root_id,
                root_abs,
                data,
                mode=mode,
                schedule_tvmaze=False,
            )
            if refreshed_version:
                data["version"] = refreshed_version
            with INDEX_LOCK:
                INDEX_CACHE[root_id] = (time.time(), data)

        schedule_episode_metadata_enrichment(records, persist_enriched)
    return version


def _load_index_from_sqlite(root_id: str, root_abs: str) -> Optional[dict]:
    try:
        data = load_index_snapshot(root_id, root_abs)
        if data is not None:
            raw_videos = list(data.get("videos") or [])
            movies, shows, videos, aliases = classify_video_records(raw_videos, aliases=load_show_aliases(root_id))
            data["video_records"] = raw_videos
            data["movies"] = movies
            data["shows"] = shows
            data["videos"] = videos
            save_show_aliases(root_id, aliases)
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
WATCHER_CHANGED_PATHS: Dict[str, set[str]] = {}
INDEX_BUILD_THREADS: Dict[str, tuple[threading.Thread, threading.Event]] = {}


def ensure_index_async(root_id: str, root_abs: str, *, mode: str = "", force: bool = False) -> None:
    now = time.time()
    cancel_event = threading.Event()

    def build():
        try:
            data = build_index_for_root(root_abs, cancel_event=cancel_event)
            _raise_if_index_build_cancelled(cancel_event)
            version = _save_index_to_sqlite(root_id, root_abs, data, mode=mode)
            _raise_if_index_build_cancelled(cancel_event)
            if version:
                data["version"] = version
            with INDEX_LOCK:
                INDEX_CACHE[root_id] = (time.time(), data)
            _queue_index_enrichment(data)
        except _IndexBuildCancelled:
            return
        finally:
            current = threading.current_thread()
            with INDEX_LOCK:
                active = INDEX_BUILD_THREADS.get(root_id)
                if active is not None and active[0] is current:
                    INDEX_BUILD_THREADS.pop(root_id, None)
                    INDEX_BUILDING[root_id] = False

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
        thread = threading.Thread(target=build, daemon=True, name=f"debripod-index-{root_id[:12]}")
        INDEX_BUILD_THREADS[root_id] = (thread, cancel_event)
        thread.start()


def watch_index_root(root_id: str, root_abs: str, *, mode: str = "") -> bool:
    from .fswatch import FilesystemChange, create_watcher

    root_id = str(root_id or "")
    root_abs = os.path.abspath(root_abs)
    if not root_id or not os.path.isdir(root_abs):
        return False
    with INDEX_LOCK:
        if root_id in WATCHERS:
            return True

    def on_change(change: FilesystemChange) -> None:
        try:
            paths = [path for path in (change.old_path, change.path) if path]
            if change.kind == "overflow":
                _debounce_watch_reindex(root_id, root_abs, mode, [root_abs])
                return
            if not paths or any(_cache_dir_name() in os.path.normpath(path).split(os.sep) for path in paths):
                return
            if not change.is_directory:
                extensions = {os.path.splitext(path)[1].lower() for path in paths}
                if not any(ext in AUDIO_EXTS or ext in VIDEO_EXTS for ext in extensions):
                    return
            _debounce_watch_reindex(root_id, root_abs, mode, paths)
        except Exception:
            pass

    try:
        observer = create_watcher(root_abs, on_change)
        observer.start()
        with INDEX_LOCK:
            WATCHERS[root_id] = observer
        return True
    except Exception:
        return False


def stop_all_index_watchers() -> None:
    with INDEX_LOCK:
        watchers = list(WATCHERS.values())
        WATCHERS.clear()
        timers = list(WATCHER_TIMERS.values())
        WATCHER_TIMERS.clear()
        WATCHER_CHANGED_PATHS.clear()
        builds = list(INDEX_BUILD_THREADS.values())
        for _thread, cancel_event in builds:
            cancel_event.set()
    for timer in timers:
        try:
            timer.cancel()
        except Exception:
            pass
    for watcher in watchers:
        try:
            watcher.stop()
        except Exception:
            pass
    deadline = time.monotonic() + 10.0
    for thread, _cancel_event in builds:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            thread.join(remaining)
        except Exception:
            pass


def stop_index_watcher(root_id: str) -> None:
    """Stop one physical root watcher when its last user association is gone."""
    root = str(root_id or "")
    with INDEX_LOCK:
        watcher = WATCHERS.pop(root, None)
        timer = WATCHER_TIMERS.pop(root, None)
        WATCHER_CHANGED_PATHS.pop(root, None)
        build = INDEX_BUILD_THREADS.pop(root, None)
        INDEX_BUILDING.pop(root, None)
        INDEX_CACHE.pop(root, None)
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass
    if build is not None:
        try:
            build[1].set()
        except Exception:
            pass
    if watcher is not None:
        try:
            watcher.stop()
        except Exception:
            pass


def _folder_entries_for_dir(root_abs: str, dir_abs: str) -> tuple[str, list[dict]]:
    rel_dir = os.path.relpath(dir_abs, root_abs).replace("\\", "/")
    rel_dir = "" if rel_dir == "." else rel_dir.strip("/")
    try:
        names = os.listdir(dir_abs)
    except OSError:
        names = []
    dirs = []
    files = []
    for name in names:
        if not name or name.startswith(".") or name == _cache_dir_name():
            continue
        path = os.path.join(dir_abs, name)
        if os.path.isdir(path):
            dirs.append(name)
        elif os.path.isfile(path):
            ext = os.path.splitext(name)[1].lower()
            if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
                files.append(name)
    entries = []
    for name in sorted(dirs, key=lambda x: x.lower()):
        relp = f"{rel_dir}/{name}" if rel_dir else name
        entries.append({"type": "dir", "name": name, "rel": relp})
    for name in sorted(files, key=lambda x: x.lower()):
        relp = f"{rel_dir}/{name}" if rel_dir else name
        ext = os.path.splitext(name)[1].lower()
        entries.append({"type": "file", "name": name, "rel": relp, "media": "video" if ext in VIDEO_EXTS else "audio"})
    return rel_dir, entries


def _refresh_changed_folder_entries(root_id: str, root_abs: str, paths: set[str]) -> None:
    if not paths or len(paths) > 8:
        return
    dirs: set[str] = set()
    root_abs_norm = os.path.abspath(root_abs)
    for path in paths:
        p = os.path.abspath(path)
        if not p.startswith(root_abs_norm):
            continue
        dirs.add(p if os.path.isdir(p) else os.path.dirname(p))
    for dir_abs in dirs:
        try:
            if not os.path.isdir(dir_abs):
                continue
            rel_dir, entries = _folder_entries_for_dir(root_abs_norm, dir_abs)
            save_folder_entries(root_id, rel_dir, dir_abs, entries)
        except Exception:
            pass


def _debounce_watch_reindex(root_id: str, root_abs: str, mode: str, paths: Optional[list[str]] = None) -> None:
    def run():
        with INDEX_LOCK:
            WATCHER_TIMERS.pop(root_id, None)
            changed_paths = WATCHER_CHANGED_PATHS.pop(root_id, set())
        _refresh_changed_folder_entries(root_id, root_abs, changed_paths)
        ensure_index_async(root_id, root_abs, mode=mode, force=True)

    with INDEX_LOCK:
        bucket = WATCHER_CHANGED_PATHS.setdefault(root_id, set())
        for path in paths or []:
            if path:
                bucket.add(os.path.abspath(path))
        old = WATCHER_TIMERS.get(root_id)
        if old:
            try:
                old.cancel()
            except Exception:
                pass
        change_count = len(bucket)
        delay = 1.5 if change_count <= 8 else (5.0 if change_count <= 60 else 10.0)
        timer = threading.Timer(delay, run)
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
    with _ENRICH_LOCK:
        _ENRICH_QUEUED.clear()
        _ENRICH_RUNNING.clear()
        _ENRICH_STAGE_COUNTS.clear()
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
            _queue_index_enrichment(data)
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


def library_stop_watchers() -> None:
    stop_all_index_watchers()
