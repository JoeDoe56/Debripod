from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
AUTOMATIC_BACKUP_RETENTION = 12


def _database_file(conn: sqlite3.Connection) -> Path | None:
    for _seq, name, path in conn.execute("PRAGMA database_list"):
        if name == "main" and path:
            return Path(path)
    return None


def backup_directory(database_file: Path | None = None) -> Path:
    override = os.environ.get("DEBRIPOD_BACKUP_DIRECTORY", "").strip()
    if override:
        directory = Path(override).expanduser()
    elif database_file:
        directory = database_file.parent / "backups"
    else:
        directory = PACKAGE_ROOT / "data" / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def validate_backup(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise ValueError("Backup file does not exist or is empty")
    uri = f"file:{candidate.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise ValueError("Backup is not a readable SQLite database") from exc
    try:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.lower() != "ok":
            raise ValueError("Backup integrity check failed")
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error as exc:
        raise ValueError("Backup validation failed") from exc
    finally:
        conn.close()
    return {"path": str(candidate), "schema_version": version, "integrity": integrity, "bytes": candidate.stat().st_size}


def _write_metadata(path: Path, payload: dict[str, Any]) -> None:
    path.with_suffix(path.suffix + ".json").write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def _prune_automatic_backups(directory: Path, *, keep: int = AUTOMATIC_BACKUP_RETENTION) -> None:
    automatic = sorted(directory.glob("auto-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True)
    for obsolete in automatic[max(1, int(keep)):]:
        obsolete.unlink(missing_ok=True)
        obsolete.with_suffix(obsolete.suffix + ".json").unlink(missing_ok=True)


def create_backup(conn: sqlite3.Connection, *, reason: str, automatic: bool = False) -> dict[str, Any]:
    database_file = _database_file(conn)
    if database_file is None or not database_file.exists():
        raise ValueError("Cannot create a file backup for an in-memory or missing database")
    directory = backup_directory(database_file)
    prefix = "auto" if automatic else "manual"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = directory / f"{prefix}-{stamp}-{time.time_ns()}.sqlite3"
    target = sqlite3.connect(destination)
    try:
        conn.backup(target)
    finally:
        target.close()
    validated = validate_backup(destination)
    metadata = {
        **validated,
        "created_at": time.time(),
        "automatic": bool(automatic),
        "reason": str(reason or "backup"),
        "source_database": str(database_file),
    }
    _write_metadata(destination, metadata)
    if automatic:
        _prune_automatic_backups(directory)
    return metadata


def list_backups(database_file: str | Path | None = None) -> list[dict[str, Any]]:
    directory = backup_directory(Path(database_file) if database_file else None)
    backups: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            metadata_path = path.with_suffix(path.suffix + ".json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            backups.append({**validate_backup(path), **metadata})
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return backups


def storage_report(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = [str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    table_bytes: dict[str, int] = {}
    try:
        for name, total in conn.execute("SELECT name, COALESCE(SUM(pgsize), 0) FROM dbstat GROUP BY name"):
            if name in tables:
                table_bytes[str(name)] = int(total or 0)
    except sqlite3.Error:
        table_bytes = {}
    rows: dict[str, dict[str, int]] = {}
    for table in tables:
        count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        blob_bytes = 0
        for column in conn.execute(f'PRAGMA table_info("{table}")'):
            name, type_name = str(column[1]), str(column[2]).upper()
            if "BLOB" in type_name:
                blob_bytes += int(conn.execute(f'SELECT COALESCE(SUM(LENGTH("{name}")), 0) FROM "{table}"').fetchone()[0] or 0)
        rows[table] = {"row_count": count, "bytes": int(table_bytes.get(table, 0)), "blob_bytes": blob_bytes}
    video_rows = 0
    audio_rows = 0
    if "visualizer_analysis" in tables and "media_files" in tables:
        try:
            video_rows = int(conn.execute("SELECT COUNT(*) FROM visualizer_analysis va JOIN media_files mf ON mf.media_id=va.media_id WHERE lower(mf.media_type)='video'").fetchone()[0])
            audio_rows = int(conn.execute("SELECT COUNT(*) FROM visualizer_analysis va LEFT JOIN media_files mf ON mf.media_id=va.media_id WHERE lower(COALESCE(mf.media_type, 'audio')) <> 'video'").fetchone()[0])
        except sqlite3.Error:
            pass
    page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    return {"database_bytes": page_count * page_size, "tables": rows, "visualizer": {"audio_rows": audio_rows, "video_rows": video_rows}}


def restore_backup(source: str | Path, destination: str | Path) -> dict[str, Any]:
    source_path = Path(source)
    destination_path = Path(destination)
    validated = validate_backup(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source_path)
    destination_conn = sqlite3.connect(destination_path)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()
    return validated


__all__ = ["AUTOMATIC_BACKUP_RETENTION", "backup_directory", "create_backup", "list_backups", "restore_backup", "storage_report", "validate_backup"]
