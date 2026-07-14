from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_STARTUP_IMPORT_LOCK = threading.Lock()
_startup_import_complete = False


def _recorded(conn: sqlite3.Connection, path: Path) -> bool:
    return bool(conn.execute("SELECT 1 FROM legacy_imports WHERE source_path=?", (str(path.resolve()),)).fetchone())


def _finish(conn: sqlite3.Connection, path: Path, kind: str, counts: dict[str, int]) -> None:
    backup = path.with_name(path.name + ".migrated.local")
    conn.execute("INSERT OR REPLACE INTO legacy_imports(source_path,source_kind,imported_at,row_counts_json,backup_path) VALUES(?,?,?,?,?)",
        (str(path.resolve()), kind, time.time(), json.dumps(counts, sort_keys=True), str(backup)))
    try:
        if not backup.exists():
            path.replace(backup)
    except OSError:
        pass


def _copy_database(conn: sqlite3.Connection, path: Path, kind: str) -> dict[str, int]:
    if not path.is_file() or _recorded(conn, path):
        return {}
    source = sqlite3.connect(str(path))
    source.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    try:
        tables = [str(r[0]) for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            target_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not target_exists:
                continue
            src_cols = [str(r[1]) for r in source.execute(f'SELECT * FROM pragma_table_info("{table}")')]
            dst_cols = {str(r[1]) for r in conn.execute(f'SELECT * FROM pragma_table_info("{table}")')}
            cols = [c for c in src_cols if c in dst_cols]
            if not cols:
                continue
            quoted = ",".join(f'"{c}"' for c in cols)
            placeholders = ",".join("?" for _ in cols)
            row_count = 0
            for row in source.execute(f'SELECT {quoted} FROM "{table}"'):
                conn.execute(f'INSERT OR REPLACE INTO "{table}"({quoted}) VALUES({placeholders})', tuple(row[c] for c in cols))
                row_count += 1
            counts[table] = row_count
    finally:
        source.close()
    _finish(conn, path, kind, counts)
    return counts


def import_legacy_databases(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    candidates = [PACKAGE_ROOT / "config" / "auth.sqlite3"]
    candidates.extend(PACKAGE_ROOT.glob("data/**/library.sqlite3"))
    out: dict[str, dict[str, int]] = {}
    primary = (PACKAGE_ROOT / "data" / "debripod.sqlite3").resolve()
    for path in dict.fromkeys(Path(p) for p in candidates):
        if path.resolve() == primary:
            continue
        counts = _copy_database(conn, path, "auth" if path.name == "auth.sqlite3" else "library")
        if counts:
            out[str(path)] = counts
    return out


def run_startup_import_once() -> dict[str, dict[str, int]]:
    """Perform legacy import once before the web app begins serving requests."""
    global _startup_import_complete
    with _STARTUP_IMPORT_LOCK:
        if _startup_import_complete:
            return {}
        from .database import database
        from .palettes import migrate_legacy_palette_data
        with database() as conn:
            # Serialize separate launcher processes before touching legacy files.
            conn.execute("BEGIN IMMEDIATE")
            imported = import_legacy_databases(conn)
            migrate_legacy_palette_data(conn)
        _startup_import_complete = True
        return imported


def import_json_file(conn: sqlite3.Connection, path: Path, kind: str, callback) -> bool:
    if not path.is_file() or _recorded(conn, path):
        return False
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    callback(value)
    _finish(conn, path, kind, {"records": len(value) if hasattr(value, "__len__") else 1})
    return True


def read_json(path: str | Path) -> Any:
    source = Path(path)
    if not source.is_file():
        return None
    with source.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def retire(path: str | Path) -> None:
    source = Path(path)
    if not source.is_file():
        return
    target = source.with_name(source.name + ".migrated.local")
    try:
        if target.exists():
            source.unlink()
        else:
            source.replace(target)
    except OSError:
        pass


def migrate_runtime_json(cache_path: str | Path) -> dict[str, int]:
    from .codec import encode
    from .database import database
    from .lastfm import save_loved
    from .playback import load as load_playback, save as save_playback
    from . import settings as settings_repository
    from ..secrets import set_secret

    cache = Path(cache_path)
    counts = {"playback": 0, "lastfm_session": 0, "lastfm_loved": 0, "task_manifests": 0}
    playback_path = cache / "playback_state.json"
    value = read_json(playback_path)
    if isinstance(value, dict) and not load_playback():
        save_playback(value)
        retire(playback_path)
        counts["playback"] += 1
    session_path = cache / "lastfm_session.json"
    value = read_json(session_path)
    if isinstance(value, dict):
        set_secret("global", "LASTFM_SESSION_KEY", str(value.get("sk") or ""))
        stored = settings_repository.load("")
        stored.update({"LASTFM_USERNAME": str(value.get("username") or ""), "LASTFM_SESSION_UPDATED": int(value.get("ts") or 0)})
        settings_repository.save(stored, "")
        retire(session_path)
        counts["lastfm_session"] += 1
    loved_path = cache / "lastfm_loved.json"
    value = read_json(loved_path)
    if isinstance(value, dict) and isinstance(value.get("tracks"), dict):
        save_loved(value["tracks"])
        retire(loved_path)
        counts["lastfm_loved"] += 1
    with database() as conn:
        for manifest in PACKAGE_ROOT.glob("data/**/.debripod-task.json"):
            value = read_json(manifest)
            if not isinstance(value, dict):
                continue
            task_id = str(value.get("task_id") or "")
            if not task_id:
                continue
            source = {"selected_file_ids": value.get("selected_file_ids") or [], "remote_file_names": value.get("remote_file_names") or []}
            blob, codec_name, raw_len = encode(json.dumps(source, separators=(",", ":"), ensure_ascii=False).encode())
            conn.execute("""INSERT OR IGNORE INTO tasks(task_id,source,title,original_result_title,task_dir,source_blob,source_codec,
              source_uncompressed_bytes,state_json,created_at,updated_at,version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (task_id, str(value.get("source") or "debrid"), str(value.get("task_title") or ""),
               str(value.get("original_result_title") or ""), str(manifest.parent), blob, codec_name, raw_len, "{}",
               float(value.get("created") or time.time()), float(value.get("updated") or time.time()), str(value.get("debripod_version") or "")))
            selected = {str(x) for x in value.get("selected_file_ids") or []}
            for index, name in enumerate(value.get("remote_file_names") or []):
                file_id = str(index)
                conn.execute("INSERT OR IGNORE INTO task_files(task_id,file_id,remote_name,local_path,selected,state_json,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (task_id, file_id, str(name), str(manifest.parent / Path(str(name)).name), int(file_id in selected), "{}", time.time()))
            retire(manifest)
            counts["task_manifests"] += 1
    return counts
