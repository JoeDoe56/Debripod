from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

RUNTIME_CACHE_SUBDIRS = (
    "search",
    "debrid",
    "ytdlp",
    "hls",
    "transcode",
    "thumbnails",
    "palettes",
    "visualizer_art",
    "incoming",
)


def configure_paths() -> None:
    """Retained as a no-argument startup hook for compatibility."""
    return None


def cache_dir() -> str:
    package_root = Path(__file__).resolve().parent.parent
    return str(package_root / "data" / "runtime_cache")


def transcode_cache_dir() -> str:
    return os.path.join(cache_dir(), "transcode")


def art_cache_dir() -> str:
    return os.path.join(cache_dir(), "thumbnails")


def visualizer_art_cache_dir() -> str:
    """Rebuildable artwork fields used by the visualizer, never database data."""
    return os.path.join(cache_dir(), "visualizer_art")


def ensure_runtime_cache_dirs() -> None:
    os.makedirs(cache_dir(), exist_ok=True)
    for name in RUNTIME_CACHE_SUBDIRS:
        os.makedirs(os.path.join(cache_dir(), name), exist_ok=True)


def _migration_complete() -> bool:
    try:
        from .storage.database import database
        with database(write=False) as conn:
            row = conn.execute(
                "SELECT value_json FROM app_settings WHERE user_id='' AND key='runtime_cache_migration_v1'"
            ).fetchone()
        return bool(row and json.loads(row["value_json"] or "false"))
    except Exception:
        return False


def _record_migration_complete() -> None:
    from .storage.database import database
    with database() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES('','runtime_cache_migration_v1','true',?)
            ON CONFLICT(user_id,key) DO UPDATE SET value_json='true',updated_at=excluded.updated_at
            """,
            (time.time(),),
        )


def _content_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def migrate_legacy_runtime_caches(download_roots: list[str]) -> dict[str, int]:
    """Move recognizable immediate legacy cache contents into the central cache once."""
    if _migration_complete():
        return {"moved": 0, "failed": 0}
    ensure_runtime_cache_dirs()
    aliases = {
        "search": "search",
        "debrid": "debrid",
        "ytdlp": "ytdlp",
        "youtube": "ytdlp",
        "hls": "hls",
        "transcoded": "transcode",
        "transcode": "transcode",
        "art": "thumbnails",
        "thumbnails": "thumbnails",
        "palettes": "palettes",
        "incoming": "incoming",
    }
    moved = 0
    failed = 0
    for raw_root in download_roots:
        root = os.path.abspath(str(raw_root or "").strip()) if str(raw_root or "").strip() else ""
        legacy = os.path.join(root, "_debripod_cache") if root and os.path.isdir(root) else ""
        if not legacy or not os.path.isdir(legacy):
            continue
        for child in list(os.scandir(legacy)):
            target_name = aliases.get(child.name.lower())
            if not target_name:
                continue
            sources = list(os.scandir(child.path)) if child.is_dir(follow_symlinks=False) else [child]
            target_dir = os.path.join(cache_dir(), target_name)
            for source in sources:
                if not source.is_file(follow_symlinks=False):
                    continue
                destination = os.path.join(target_dir, source.name)
                try:
                    if os.path.exists(destination):
                        if _content_digest(source.path) == _content_digest(destination):
                            os.unlink(source.path)
                            moved += 1
                            continue
                        stem, ext = os.path.splitext(source.name)
                        destination = os.path.join(target_dir, f"{stem}.{int(os.path.getmtime(source.path))}{ext}")
                        if os.path.exists(destination):
                            failed += 1
                            continue
                    shutil.move(source.path, destination)
                    moved += 1
                except OSError:
                    failed += 1
            if child.is_dir(follow_symlinks=False):
                try:
                    os.rmdir(child.path)
                except OSError:
                    pass
        try:
            os.rmdir(legacy)
        except OSError:
            pass
    if failed == 0:
        _record_migration_complete()
    return {"moved": moved, "failed": failed}
