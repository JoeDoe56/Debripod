from __future__ import annotations

import contextlib
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

from .metadata import parse_release_name
from .schema import (
    LOCAL_SOURCE_DMM,
    LOCAL_SOURCE_TORRENTS_CSV,
    connect,
    initialize,
    rebuild_fts,
    suspend_fts,
)
from .search import search_rows


DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "torrent_index.sqlite"


def decode_infohash(value: str | bytes | bytearray | memoryview) -> bytes:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    else:
        text = str(value or "").strip().lower()
        try:
            raw = bytes.fromhex(text)
        except ValueError as exc:
            raise ValueError("infohash must be 40 hexadecimal characters") from exc
    if len(raw) != 20:
        raise ValueError("infohash must decode to exactly 20 bytes")
    return raw


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


class LocalTorrentIndex:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)

    def open(self) -> sqlite3.Connection:
        conn = connect(self.path)
        initialize(conn)
        return conn

    def initialize(self) -> None:
        with contextlib.closing(self.open()):
            pass

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.open()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
        row = conn.execute("SELECT value FROM local_index_meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else default

    @staticmethod
    def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
        conn.execute(
            "INSERT INTO local_index_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(key), str(value)),
        )

    @classmethod
    def increment_generation(cls, conn: sqlite3.Connection) -> int:
        generation = int(cls.get_meta(conn, "local_index_generation", "0") or 0) + 1
        cls.set_meta(conn, "local_index_generation", generation)
        return generation

    @staticmethod
    def _parsed(name: str) -> tuple[str, int | None, int | None, int | None]:
        parsed = parse_release_name(name)
        return parsed["parsed_title"], parsed["year"], parsed["resolution"], parsed["quality"]

    def add_dmm(
        self,
        conn: sqlite3.Connection,
        infohash: str | bytes,
        name: str,
        size_bytes: Any = None,
    ) -> None:
        raw_hash = decode_infohash(infohash)
        title = str(name or "").strip() or raw_hash.hex()
        parsed_title, year, resolution, quality = self._parsed(title)
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO torrents(
              infohash,name,size_bytes,parsed_title,year,resolution,quality,
              source_mask,dmm_refcount,updated_unix
            ) VALUES(?,?,?,?,?,?,?, ?,1,?)
            ON CONFLICT(infohash) DO UPDATE SET
              dmm_refcount=torrents.dmm_refcount+1,
              source_mask=torrents.source_mask | ?,
              name=CASE WHEN torrents.name='' THEN excluded.name ELSE torrents.name END,
              size_bytes=COALESCE(torrents.size_bytes,excluded.size_bytes),
              parsed_title=COALESCE(NULLIF(torrents.parsed_title,''),excluded.parsed_title),
              year=COALESCE(torrents.year,excluded.year),
              resolution=COALESCE(torrents.resolution,excluded.resolution),
              quality=COALESCE(torrents.quality,excluded.quality),
              updated_unix=excluded.updated_unix
            """,
            (
                raw_hash,
                title,
                _integer(size_bytes),
                parsed_title,
                year,
                resolution,
                quality,
                LOCAL_SOURCE_DMM,
                now,
                LOCAL_SOURCE_DMM,
            ),
        )

    def remove_dmm(self, conn: sqlite3.Connection, infohash: str | bytes) -> None:
        raw_hash = decode_infohash(infohash)
        conn.execute(
            """
            UPDATE torrents SET
              dmm_refcount=CASE WHEN dmm_refcount > 0 THEN dmm_refcount-1 ELSE 0 END,
              source_mask=CASE WHEN dmm_refcount <= 1 THEN source_mask & ? ELSE source_mask END,
              updated_unix=?
            WHERE infohash=?
            """,
            (~LOCAL_SOURCE_DMM, int(time.time()), raw_hash),
        )
        conn.execute("DELETE FROM torrents WHERE infohash=? AND source_mask=0", (raw_hash,))

    def set_csv(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        raw_hash = decode_infohash(row.get("infohash") or row.get("hash") or b"")
        title = str(row.get("name") or row.get("title") or "").strip() or raw_hash.hex()
        parsed_title, year, resolution, quality = self._parsed(title)
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO torrents(
              infohash,name,size_bytes,parsed_title,year,resolution,quality,source_mask,
              csv_present,csv_seeders,csv_leechers,csv_completed,csv_created_unix,
              csv_scraped_unix,updated_unix
            ) VALUES(?,?,?,?,?,?,?, ?,1,?,?,?,?,?,?)
            ON CONFLICT(infohash) DO UPDATE SET
              source_mask=torrents.source_mask | ?, csv_present=1,
              name=excluded.name, size_bytes=COALESCE(excluded.size_bytes,torrents.size_bytes),
              parsed_title=excluded.parsed_title, year=excluded.year,
              resolution=excluded.resolution, quality=excluded.quality,
              csv_seeders=excluded.csv_seeders, csv_leechers=excluded.csv_leechers,
              csv_completed=excluded.csv_completed, csv_created_unix=excluded.csv_created_unix,
              csv_scraped_unix=excluded.csv_scraped_unix, updated_unix=excluded.updated_unix
            """,
            (
                raw_hash,
                title,
                _integer(row.get("size_bytes") if "size_bytes" in row else row.get("size")),
                parsed_title,
                year,
                resolution,
                quality,
                LOCAL_SOURCE_TORRENTS_CSV,
                _integer(row.get("seeders")),
                _integer(row.get("leechers")),
                _integer(row.get("completed")),
                _integer(row.get("created_unix") if "created_unix" in row else row.get("created")),
                _integer(row.get("scraped_unix") if "scraped_unix" in row else row.get("scraped")),
                now,
                LOCAL_SOURCE_TORRENTS_CSV,
            ),
        )

    def remove_csv(self, conn: sqlite3.Connection, infohash: str | bytes) -> None:
        raw_hash = decode_infohash(infohash)
        conn.execute(
            """
            UPDATE torrents SET source_mask=source_mask & ?, csv_present=0,
              csv_seeders=NULL,csv_leechers=NULL,csv_completed=NULL,
              csv_created_unix=NULL,csv_scraped_unix=NULL,updated_unix=?
            WHERE infohash=?
            """,
            (~LOCAL_SOURCE_TORRENTS_CSV, int(time.time()), raw_hash),
        )
        conn.execute("DELETE FROM torrents WHERE infohash=? AND source_mask=0", (raw_hash,))

    def replace_dmm_snapshot(self, hashlists: Iterable[Iterable[dict[str, Any]]], commit_sha: str) -> int:
        count = 0
        with self.transaction() as conn:
            suspend_fts(conn)
            conn.execute(
                "UPDATE torrents SET dmm_refcount=0, source_mask=source_mask & ?",
                (~LOCAL_SOURCE_DMM,),
            )
            conn.execute("DELETE FROM torrents WHERE source_mask=0")
            for entries in hashlists:
                unique: dict[bytes, dict[str, Any]] = {}
                for entry in entries:
                    try:
                        unique[decode_infohash(entry.get("hash") or entry.get("infohash") or "")] = entry
                    except (AttributeError, ValueError):
                        continue
                for raw_hash, entry in unique.items():
                    self.add_dmm(conn, raw_hash, str(entry.get("filename") or entry.get("name") or ""), entry.get("bytes") or entry.get("size"))
                    count += 1
            rebuild_fts(conn)
            self.set_meta(conn, "dmm_commit_sha", commit_sha)
            self.set_meta(conn, "dmm_last_success_unix", int(time.time()))
            self.increment_generation(conn)
        return count

    def replace_csv_snapshot(self, rows: Iterable[dict[str, Any]], commit_sha: str) -> int:
        count = 0
        with self.transaction() as conn:
            suspend_fts(conn)
            conn.execute(
                """
                UPDATE torrents SET source_mask=source_mask & ?,csv_present=0,
                  csv_seeders=NULL,csv_leechers=NULL,csv_completed=NULL,
                  csv_created_unix=NULL,csv_scraped_unix=NULL
                """,
                (~LOCAL_SOURCE_TORRENTS_CSV,),
            )
            conn.execute("DELETE FROM torrents WHERE source_mask=0")
            for row in rows:
                try:
                    self.set_csv(conn, row)
                    count += 1
                except ValueError:
                    continue
            rebuild_fts(conn)
            self.set_meta(conn, "torrents_csv_commit_sha", commit_sha)
            self.set_meta(conn, "torrents_csv_last_success_unix", int(time.time()))
            self.increment_generation(conn)
        return count

    def search(self, query: str) -> list[dict[str, Any]]:
        with contextlib.closing(self.open()) as conn:
            return search_rows(conn, query)

    def diagnostics(self) -> dict[str, Any]:
        with contextlib.closing(self.open()) as conn:
            counts = conn.execute(
                """
                SELECT COUNT(*) AS total,
                  SUM(CASE WHEN source_mask & ? THEN 1 ELSE 0 END) AS dmm,
                  SUM(CASE WHEN source_mask & ? THEN 1 ELSE 0 END) AS torrents_csv,
                  SUM(CASE WHEN source_mask = ? THEN 1 ELSE 0 END) AS overlap
                FROM torrents
                """,
                (LOCAL_SOURCE_DMM, LOCAL_SOURCE_TORRENTS_CSV, LOCAL_SOURCE_DMM | LOCAL_SOURCE_TORRENTS_CSV),
            ).fetchone()
            meta = {row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM local_index_meta")}
        return {
            "ready": self.path.is_file(),
            "path": str(self.path),
            "size_bytes": self.path.stat().st_size if self.path.is_file() else 0,
            "total": int(counts["total"] or 0),
            "dmm": int(counts["dmm"] or 0),
            "torrents_csv": int(counts["torrents_csv"] or 0),
            "overlap": int(counts["overlap"] or 0),
            "meta": meta,
        }
