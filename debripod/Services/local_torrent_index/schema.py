from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1
LOCAL_SOURCE_DMM = 1
LOCAL_SOURCE_TORRENTS_CSV = 2

CORE_DDL = """
CREATE TABLE IF NOT EXISTS torrents (
    id INTEGER PRIMARY KEY,
    infohash BLOB NOT NULL UNIQUE CHECK(length(infohash) = 20),
    name TEXT NOT NULL,
    size_bytes INTEGER,
    parsed_title TEXT,
    year INTEGER,
    resolution INTEGER,
    quality INTEGER,
    source_mask INTEGER NOT NULL DEFAULT 0,
    dmm_refcount INTEGER NOT NULL DEFAULT 0 CHECK(dmm_refcount >= 0),
    csv_present INTEGER NOT NULL DEFAULT 0 CHECK(csv_present IN (0, 1)),
    csv_seeders INTEGER,
    csv_leechers INTEGER,
    csv_completed INTEGER,
    csv_created_unix INTEGER,
    csv_scraped_unix INTEGER,
    updated_unix INTEGER
);
CREATE INDEX IF NOT EXISTS torrents_source_mask_idx ON torrents(source_mask);
CREATE TABLE IF NOT EXISTS local_index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS torrent_search USING fts5(
    name,
    parsed_title,
    content='torrents',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
"""

TRIGGERS_DDL = """
CREATE TRIGGER IF NOT EXISTS torrents_ai AFTER INSERT ON torrents BEGIN
  INSERT INTO torrent_search(rowid, name, parsed_title) VALUES (new.id, new.name, new.parsed_title);
END;
CREATE TRIGGER IF NOT EXISTS torrents_ad AFTER DELETE ON torrents BEGIN
  INSERT INTO torrent_search(torrent_search, rowid, name, parsed_title)
  VALUES ('delete', old.id, old.name, old.parsed_title);
END;
CREATE TRIGGER IF NOT EXISTS torrents_au AFTER UPDATE OF name, parsed_title ON torrents BEGIN
  INSERT INTO torrent_search(torrent_search, rowid, name, parsed_title)
  VALUES ('delete', old.id, old.name, old.parsed_title);
  INSERT INTO torrent_search(rowid, name, parsed_title) VALUES (new.id, new.name, new.parsed_title);
END;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(CORE_DDL)
    conn.executescript(TRIGGERS_DDL)
    conn.execute(
        "INSERT INTO local_index_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )


def suspend_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER IF EXISTS torrents_ai")
    conn.execute("DROP TRIGGER IF EXISTS torrents_ad")
    conn.execute("DROP TRIGGER IF EXISTS torrents_au")


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO torrent_search(torrent_search) VALUES('rebuild')")
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS torrents_ai AFTER INSERT ON torrents BEGIN
        INSERT INTO torrent_search(rowid, name, parsed_title) VALUES (new.id, new.name, new.parsed_title);
        END"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS torrents_ad AFTER DELETE ON torrents BEGIN
        INSERT INTO torrent_search(torrent_search, rowid, name, parsed_title)
        VALUES ('delete', old.id, old.name, old.parsed_title);
        END"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS torrents_au AFTER UPDATE OF name, parsed_title ON torrents BEGIN
        INSERT INTO torrent_search(torrent_search, rowid, name, parsed_title)
        VALUES ('delete', old.id, old.name, old.parsed_title);
        INSERT INTO torrent_search(rowid, name, parsed_title) VALUES (new.id, new.name, new.parsed_title);
        END"""
    )
