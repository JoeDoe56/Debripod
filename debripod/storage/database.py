from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .backups import create_backup, restore_backup, storage_report, validate_backup
from .migrations import migrate

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_DB_LOCK = threading.RLock()
_MAINTENANCE = threading.Condition(_DB_LOCK)
_maintenance_active = False
_active_writers = 0


def database_path() -> str:
    override = os.environ.get("DEBRIPOD_DATABASE")
    path = Path(override).expanduser() if override else PACKAGE_ROOT / "data" / "debripod.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def connect(*, initialize: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if initialize:
        migrate(conn)
    return conn


def initialize_database() -> int:
    conn = connect(initialize=False)
    try:
        return migrate(conn)
    finally:
        conn.close()


@contextmanager
def database(*, write: bool = True) -> Iterator[sqlite3.Connection]:
    global _active_writers
    with _MAINTENANCE:
        while write and _maintenance_active:
            _MAINTENANCE.wait()
        if write:
            _active_writers += 1
    conn = connect()
    try:
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()
        if write:
            with _MAINTENANCE:
                _active_writers -= 1
                _MAINTENANCE.notify_all()


def checkpoint(mode: str = "PASSIVE") -> tuple[int, int, int]:
    clean = mode.upper()
    if clean not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
        raise ValueError("Invalid WAL checkpoint mode")
    with connect() as conn:
        row = conn.execute(f"PRAGMA wal_checkpoint({clean})").fetchone()
        return tuple(int(x) for x in row)


@contextmanager
def maintenance() -> Iterator[None]:
    global _maintenance_active
    with _MAINTENANCE:
        _maintenance_active = True
        while _active_writers:
            _MAINTENANCE.wait()
    try:
        yield
    finally:
        with _MAINTENANCE:
            _maintenance_active = False
            _MAINTENANCE.notify_all()


def optimize_and_vacuum() -> dict[str, int | tuple[int, int, int]]:
    path = database_path()
    before = os.path.getsize(path) if os.path.exists(path) else 0
    with maintenance():
        check = checkpoint("TRUNCATE")
        conn = connect()
        try:
            conn.execute("PRAGMA optimize")
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()
    after = os.path.getsize(path) if os.path.exists(path) else 0
    return {"before_bytes": before, "after_bytes": after, "reclaimed_bytes": max(0, before - after), "checkpoint": check}


def create_database_backup(*, reason: str = "manual backup") -> dict[str, object]:
    with maintenance():
        conn = connect()
        try:
            return create_backup(conn, reason=reason, automatic=False)
        finally:
            conn.close()


def database_storage_report() -> dict[str, object]:
    with connect() as conn:
        return storage_report(conn)


def restore_database_backup(source: str) -> dict[str, object]:
    validate_backup(source)
    path = database_path()
    with maintenance():
        current = connect()
        try:
            create_backup(current, reason="before restore", automatic=True)
        finally:
            current.close()
        result = restore_backup(source, path)
        # A restored database is re-opened and checked before callers resume writes.
        restored = connect(initialize=False)
        try:
            if str(restored.execute("PRAGMA integrity_check").fetchone()[0]).lower() != "ok":
                raise ValueError("Restored database integrity check failed")
        finally:
            restored.close()
    return result
