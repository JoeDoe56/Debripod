from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from ..storage.database import database
from ..storage.palettes import load_palette as load_packed_palette, save_palette as save_packed_palette
from ..storage.codec import CodecError, decode as decode_blob, encode as encode_blob

SCHEMA_VERSION = 5
ANALYSIS_ALGORITHM_VERSION = 3
ANALYSIS_BAND_COUNT = 9
ANALYSIS_DELTA_ENCODING = "delta-zlib-v1"
_DB_LOCK = threading.RLock()


@contextmanager
def library_db() -> Iterator[sqlite3.Connection]:
    with _DB_LOCK:
        with database() as conn:
            yield conn


@contextmanager
def auth_db() -> Iterator[sqlite3.Connection]:
    with _DB_LOCK:
        with database() as conn:
            yield conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS library_roots (
          root_id TEXT PRIMARY KEY,
          root_abs TEXT NOT NULL,
          mode TEXT NOT NULL DEFAULT '',
          version INTEGER NOT NULL DEFAULT 0,
          last_scan_started_at REAL,
          last_scan_finished_at REAL
        );

        CREATE TABLE IF NOT EXISTS library_items (
          root_id TEXT NOT NULL,
          rel TEXT NOT NULL,
          abs_path TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT '',
          ext TEXT NOT NULL DEFAULT '',
          size INTEGER NOT NULL DEFAULT 0,
          mtime_ns INTEGER NOT NULL DEFAULT 0,
          deleted INTEGER NOT NULL DEFAULT 0,
          changed_at_version INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(root_id, rel)
        );

        CREATE INDEX IF NOT EXISTS idx_library_items_root_deleted ON library_items(root_id, deleted, kind);
        CREATE INDEX IF NOT EXISTS idx_library_items_abs_identity ON library_items(abs_path, size, mtime_ns);

        CREATE TABLE IF NOT EXISTS folder_entries (
          root_id TEXT NOT NULL,
          rel TEXT NOT NULL DEFAULT '',
          root_version INTEGER NOT NULL DEFAULT 0,
          dir_mtime_ns INTEGER NOT NULL DEFAULT 0,
          saved_at REAL NOT NULL,
          entries_json TEXT NOT NULL,
          PRIMARY KEY(root_id, rel)
        );

        CREATE TABLE IF NOT EXISTS media_files (
          media_id TEXT PRIMARY KEY,
          root_id TEXT NOT NULL DEFAULT '',
          root_abs TEXT NOT NULL DEFAULT '',
          rel_path TEXT NOT NULL DEFAULT '',
          abs_path TEXT NOT NULL,
          media_type TEXT NOT NULL DEFAULT '',
          size INTEGER NOT NULL DEFAULT 0,
          mtime_ns INTEGER NOT NULL DEFAULT 0,
          duration REAL,
          title TEXT NOT NULL DEFAULT '',
          artist TEXT NOT NULL DEFAULT '',
          album_artist TEXT NOT NULL DEFAULT '',
          album TEXT NOT NULL DEFAULT '',
          genre TEXT NOT NULL DEFAULT '',
          track TEXT NOT NULL DEFAULT '',
          tech TEXT NOT NULL DEFAULT '',
          folder TEXT NOT NULL DEFAULT '',
          indexed_at REAL NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          UNIQUE(root_id, rel_path)
        );

        CREATE INDEX IF NOT EXISTS idx_media_files_root_type ON media_files(root_id, media_type);
        CREATE INDEX IF NOT EXISTS idx_media_files_abs_identity ON media_files(abs_path, size, mtime_ns);

        CREATE TABLE IF NOT EXISTS media_metadata (
          root_id TEXT NOT NULL,
          rel TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          artist TEXT NOT NULL DEFAULT '',
          album_artist TEXT NOT NULL DEFAULT '',
          album TEXT NOT NULL DEFAULT '',
          genre TEXT NOT NULL DEFAULT '',
          track TEXT NOT NULL DEFAULT '',
          duration REAL,
          tech TEXT NOT NULL DEFAULT '',
          codec TEXT NOT NULL DEFAULT '',
          bit_depth INTEGER,
          sample_rate INTEGER,
          bitrate INTEGER,
          size INTEGER NOT NULL DEFAULT 0,
          mtime_ns INTEGER NOT NULL DEFAULT 0,
          saved_at REAL NOT NULL,
          PRIMARY KEY(root_id, rel)
        );

        CREATE TABLE IF NOT EXISTS metadata_cache (
          abs_path TEXT PRIMARY KEY,
          size INTEGER NOT NULL DEFAULT 0,
          mtime_ns INTEGER NOT NULL DEFAULT 0,
          saved_at REAL NOT NULL,
          meta_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS art_palette_cache (
          cache_key TEXT PRIMARY KEY,
          root_id TEXT NOT NULL DEFAULT '',
          rel TEXT NOT NULL DEFAULT '',
          source_kind TEXT NOT NULL DEFAULT '',
          source_identity TEXT NOT NULL DEFAULT '',
          size INTEGER NOT NULL DEFAULT 0,
          mtime_ns INTEGER NOT NULL DEFAULT 0,
          version INTEGER NOT NULL DEFAULT 1,
          saved_at REAL NOT NULL,
          palette_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS visualizer_analysis (
          analysis_key TEXT PRIMARY KEY,
          media_id TEXT NOT NULL DEFAULT '',
          root_id TEXT NOT NULL DEFAULT '',
          rel TEXT NOT NULL DEFAULT '',
          abs_path TEXT NOT NULL,
          size INTEGER NOT NULL DEFAULT 0,
          mtime_ns INTEGER NOT NULL DEFAULT 0,
          duration REAL,
          analysis_rate_hz INTEGER NOT NULL DEFAULT 30,
          band_count INTEGER NOT NULL DEFAULT 9,
          compression TEXT NOT NULL DEFAULT 'none',
          decoder_settings_hash TEXT NOT NULL DEFAULT '',
          algorithm_version INTEGER NOT NULL DEFAULT 1,
          saved_at REAL NOT NULL,
          frame_count INTEGER NOT NULL DEFAULT 0,
          feature_blob BLOB NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS library_facets (
          root_id TEXT NOT NULL,
          facet TEXT NOT NULL,
          root_version INTEGER NOT NULL DEFAULT 0,
          saved_at REAL NOT NULL,
          data_json TEXT NOT NULL,
          PRIMARY KEY(root_id, facet)
        );

        CREATE TABLE IF NOT EXISTS search_cache (
          cache_key TEXT PRIMARY KEY,
          source TEXT NOT NULL DEFAULT '',
          query TEXT NOT NULL DEFAULT '',
          extra_json TEXT NOT NULL DEFAULT '{}',
          saved_at REAL NOT NULL,
          expires_at REAL,
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS search_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          query TEXT NOT NULL DEFAULT '',
          engine TEXT NOT NULL DEFAULT '',
          cache_key TEXT NOT NULL DEFAULT '',
          ts REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_search_history_recent ON search_history(ts DESC);

        CREATE TABLE IF NOT EXISTS show_aliases (
          root_id TEXT NOT NULL,
          alias_key TEXT NOT NULL,
          show_key TEXT NOT NULL,
          updated_at REAL NOT NULL,
          PRIMARY KEY(root_id, alias_key)
        );

        CREATE TABLE IF NOT EXISTS user_passkeys (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL,
          credential_id TEXT NOT NULL UNIQUE,
          public_key TEXT NOT NULL,
          sign_count INTEGER NOT NULL DEFAULT 0,
          transports TEXT NOT NULL DEFAULT '[]',
          aaguid TEXT NOT NULL DEFAULT '',
          device_label TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL,
          last_used_at REAL,
          revoked_at REAL,
          user_verified_required INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_user_passkeys_username ON user_passkeys(username, revoked_at);

        CREATE TABLE IF NOT EXISTS passkey_challenges (
          id TEXT PRIMARY KEY,
          username TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL,
          challenge_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          expires_at REAL NOT NULL
        );
        """
    )
    _ensure_column(conn, "search_cache", "extra_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "art_palette_cache", "root_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "art_palette_cache", "rel", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "visualizer_analysis", "root_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "visualizer_analysis", "rel", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "visualizer_analysis", "analysis_rate_hz", "INTEGER NOT NULL DEFAULT 30")
    _ensure_column(conn, "visualizer_analysis", "band_count", "INTEGER NOT NULL DEFAULT 9")
    _ensure_column(conn, "visualizer_analysis", "compression", "TEXT NOT NULL DEFAULT 'none'")
    _ensure_column(conn, "visualizer_analysis", "decoder_settings_hash", "TEXT NOT NULL DEFAULT ''")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    try:
        cols = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except sqlite3.Error:
        pass


def ensure_passkey_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_passkeys (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL,
          credential_id TEXT NOT NULL UNIQUE,
          public_key TEXT NOT NULL,
          sign_count INTEGER NOT NULL DEFAULT 0,
          transports TEXT NOT NULL DEFAULT '[]',
          aaguid TEXT NOT NULL DEFAULT '',
          device_label TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL,
          last_used_at REAL,
          revoked_at REAL,
          user_verified_required INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_user_passkeys_username ON user_passkeys(username, revoked_at);

        CREATE TABLE IF NOT EXISTS passkey_challenges (
          id TEXT PRIMARY KEY,
          username TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL,
          challenge_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          expires_at REAL NOT NULL
        );
        """
    )


def file_identity(abs_path: str) -> tuple[int, int]:
    try:
        st = os.stat(abs_path)
        return int(st.st_size), int(st.st_mtime_ns)
    except OSError:
        return 0, 0


def load_metadata(abs_path: str) -> Optional[dict]:
    size, mtime_ns = file_identity(abs_path)
    if not size and not mtime_ns:
        return None
    with library_db() as conn:
        row = conn.execute(
            "SELECT meta_json FROM metadata_cache WHERE abs_path = ? AND size = ? AND mtime_ns = ?",
            (os.path.abspath(abs_path), size, mtime_ns),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(str(row["meta_json"] or "{}"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_metadata(abs_path: str, meta: dict) -> None:
    size, mtime_ns = file_identity(abs_path)
    if not size and not mtime_ns:
        return
    payload = json.dumps(meta if isinstance(meta, dict) else {}, ensure_ascii=False, sort_keys=True)
    with library_db() as conn:
        conn.execute(
            """
            INSERT INTO metadata_cache(abs_path, size, mtime_ns, saved_at, meta_json)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(abs_path) DO UPDATE SET
              size=excluded.size,
              mtime_ns=excluded.mtime_ns,
              saved_at=excluded.saved_at,
              meta_json=excluded.meta_json
            """,
            (os.path.abspath(abs_path), size, mtime_ns, time.time(), payload),
        )


def _root_mtime_ns(root_abs: str) -> int:
    try:
        return int(os.stat(root_abs).st_mtime_ns)
    except OSError:
        return 0


def _path_mtime_ns(abs_path: str) -> int:
    try:
        return int(os.stat(abs_path).st_mtime_ns)
    except OSError:
        return 0


def root_version(root_id: str) -> int:
    with library_db() as conn:
        row = conn.execute("SELECT version FROM library_roots WHERE root_id = ?", (str(root_id or ""),)).fetchone()
    return int(row["version"] or 0) if row else 0


def root_versions() -> dict[str, int]:
    with library_db() as conn:
        rows = conn.execute("SELECT root_id, version FROM library_roots").fetchall()
    return {str(row["root_id"]): int(row["version"] or 0) for row in rows}


def user_library_roots(user_id: str) -> list[dict[str, Any]]:
    """Return only physical roots explicitly associated with one user."""
    with library_db() as conn:
        rows = conn.execute(
            """SELECT association.root_id,association.display_name,association.mode,association.source,association.sort_order,
                      physical.root_abs,physical.version
               FROM user_library_roots AS association
               JOIN library_roots AS physical ON physical.root_id=association.root_id
               WHERE association.user_id=?
               ORDER BY association.sort_order,association.root_id""",
            (str(user_id or ""),),
        ).fetchall()
    return [dict(row) for row in rows]


def associated_library_roots() -> list[dict[str, Any]]:
    """One row per referenced physical root for shared watchers/indexing."""
    with library_db() as conn:
        rows = conn.execute(
            """SELECT physical.root_id,physical.root_abs,physical.mode,physical.version,
                      MIN(association.display_name) AS display_name,MIN(association.source) AS source
               FROM library_roots AS physical
               JOIN user_library_roots AS association ON association.root_id=physical.root_id
               GROUP BY physical.root_id,physical.root_abs,physical.mode,physical.version
               ORDER BY physical.root_id"""
        ).fetchall()
    return [dict(row) for row in rows]


def user_has_library_root(user_id: str, root_id: str) -> bool:
    with library_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_library_roots WHERE user_id=? AND root_id=?",
            (str(user_id or ""), str(root_id or "")),
        ).fetchone()
    return row is not None


def replace_user_library_roots(user_id: str, roots: list[dict[str, Any]]) -> list[str]:
    """Replace one user's root memberships and return newly-unreferenced IDs."""
    owner = str(user_id or "").strip()
    if not owner:
        raise ValueError("A user ID is required")
    now = time.time()
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, item in enumerate(roots or []):
        root_id = str(item.get("root_id") or item.get("id") or "").strip()
        raw_path = str(item.get("path") or item.get("root_abs") or "").strip()
        if not root_id or not raw_path or not os.path.isabs(raw_path) or root_id in seen:
            continue
        root_abs = os.path.realpath(os.path.abspath(raw_path))
        seen.add(root_id)
        clean.append({
            "root_id": root_id,
            "root_abs": root_abs,
            "display_name": str(item.get("name") or item.get("display_name") or os.path.basename(root_abs.rstrip("\\/")) or root_abs),
            "mode": str(item.get("mode") or "metadata").strip().lower() or "metadata",
            "source": str(item.get("source") or "library").strip().lower() or "library",
            "sort_order": order,
        })
    with library_db() as conn:
        existing = {str(row[0]) for row in conn.execute("SELECT root_id FROM user_library_roots WHERE user_id=?", (owner,)).fetchall()}
        wanted = {row["root_id"] for row in clean}
        conn.execute("DELETE FROM user_library_roots WHERE user_id=?", (owner,))
        for row in clean:
            conn.execute(
                """INSERT INTO library_roots(root_id,root_abs,mode,version,last_scan_started_at,last_scan_finished_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(root_id) DO UPDATE SET root_abs=excluded.root_abs,mode=excluded.mode""",
                (row["root_id"], row["root_abs"], row["mode"], 0, None, None),
            )
            conn.execute(
                """INSERT INTO user_library_roots(user_id,root_id,display_name,mode,source,sort_order,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (owner, row["root_id"], row["display_name"], row["mode"], row["source"], row["sort_order"], now, now),
            )
        orphan_rows = conn.execute(
            """SELECT root_id FROM library_roots WHERE root_id IN ({})
               AND NOT EXISTS (SELECT 1 FROM user_library_roots WHERE user_library_roots.root_id=library_roots.root_id)""".format(",".join("?" for _ in existing - wanted) if existing - wanted else "''"),
            tuple(existing - wanted),
        ).fetchall() if existing - wanted else []
    return [str(row[0]) for row in orphan_rows]


def delete_user_library_roots(user_id: str) -> list[str]:
    owner = str(user_id or "").strip()
    with library_db() as conn:
        previous = [str(row[0]) for row in conn.execute("SELECT root_id FROM user_library_roots WHERE user_id=?", (owner,)).fetchall()]
        conn.execute("DELETE FROM user_library_roots WHERE user_id=?", (owner,))
        if not previous:
            return []
        placeholders = ",".join("?" for _ in previous)
        rows = conn.execute(
            f"""SELECT root_id FROM library_roots WHERE root_id IN ({placeholders})
                AND NOT EXISTS (SELECT 1 FROM user_library_roots WHERE user_library_roots.root_id=library_roots.root_id)""",
            previous,
        ).fetchall()
    return [str(row[0]) for row in rows]


def load_show_aliases(root_id: str) -> dict[str, str]:
    with library_db() as conn:
        rows = conn.execute("SELECT alias_key, show_key FROM show_aliases WHERE root_id = ?", (str(root_id or ""),)).fetchall()
    return {str(row["alias_key"]): str(row["show_key"]) for row in rows if str(row["alias_key"] or "") and str(row["show_key"] or "")}


def save_show_aliases(root_id: str, aliases: dict[str, str]) -> None:
    clean = {str(alias): str(show) for alias, show in (aliases or {}).items() if str(alias or "") and str(show or "")}
    if not clean:
        return
    with library_db() as conn:
        conn.executemany(
            """
            INSERT INTO show_aliases(root_id, alias_key, show_key, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(root_id, alias_key) DO UPDATE SET show_key=excluded.show_key, updated_at=excluded.updated_at
            """,
            [(str(root_id or ""), alias, show, time.time()) for alias, show in clean.items()],
        )


def _track_sort_tuple(track_s: str) -> tuple[int, str]:
    s = (track_s or "").strip()
    if not s:
        return (10**9, "")
    digits = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return (10**9, s)
    try:
        return (int("".join(digits)), s)
    except Exception:
        return (10**9, s)


def _track_item(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "track",
        "label": str(track.get("title") or track.get("name") or "Track"),
        "rel": track.get("rel"),
        "badge": str(track.get("track") or ""),
    }


def _album_value(*, artist: str = "", album: str = "", genre: str = "", liked: bool = False) -> str:
    payload: dict[str, Any] = {}
    if artist:
        payload["artist"] = artist
    if album:
        payload["album"] = album
    if genre:
        payload["genre"] = genre
    if liked:
        payload["liked"] = True
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _track_key(*, artist: str = "", album: str = "", genre: str = "") -> str:
    return json.dumps({"artist": artist, "album": album, "genre": genre}, ensure_ascii=False, sort_keys=True)


def _build_metadata_facets(data: dict) -> dict[str, Any]:
    tracks = [t for t in (data.get("tracks") or []) if isinstance(t, dict)]
    videos = [v for v in (data.get("videos") or []) if isinstance(v, dict)]

    artists = sorted({str(t.get("artist") or "").strip() for t in tracks if str(t.get("artist") or "").strip()}, key=str.lower)
    genres = sorted({str(t.get("genre") or "").strip() for t in tracks if str(t.get("genre") or "").strip()}, key=str.lower)

    albums_all: list[dict[str, Any]] = []
    albums_by_artist: dict[str, list[dict[str, Any]]] = {}
    genre_albums: dict[str, list[dict[str, Any]]] = {}
    seen_all: set[tuple[str, str]] = set()
    seen_artist: set[tuple[str, str]] = set()
    seen_genre: set[tuple[str, str, str]] = set()
    any_genre: set[str] = set()

    tracks_by_key: dict[str, list[dict[str, Any]]] = {}
    songs = sorted(tracks, key=lambda t: str(t.get("title") or t.get("name") or "").lower())
    for t in tracks:
        artist = str(t.get("artist") or "").strip()
        album = str(t.get("album") or "").strip()
        genre = str(t.get("genre") or "").strip()
        item = _track_item(t)
        for key in (
            _track_key(artist=artist, album=album),
            _track_key(artist=artist),
            _track_key(genre=genre),
            _track_key(genre=genre, artist=artist, album=album),
        ):
            tracks_by_key.setdefault(key, []).append(item)
        if artist:
            albums_by_artist.setdefault(artist, [])
        if genre:
            any_genre.add(genre)
            genre_albums.setdefault(genre, [])
        if album:
            if (artist, album) not in seen_all:
                seen_all.add((artist, album))
                label = album + (f"   {artist}" if artist else "")
                albums_all.append({"kind": "album", "label": label, "value": _album_value(artist=artist, album=album)})
            if artist and (artist, album) not in seen_artist:
                seen_artist.add((artist, album))
                albums_by_artist.setdefault(artist, []).append({"kind": "album", "label": album, "value": _album_value(artist=artist, album=album)})
            if genre and (genre, artist, album) not in seen_genre:
                seen_genre.add((genre, artist, album))
                label = album + (f"   {artist}" if artist else "")
                genre_albums.setdefault(genre, []).append({"kind": "album", "label": label, "value": _album_value(genre=genre, artist=artist, album=album)})

    albums_all.sort(key=lambda x: str(x.get("label") or "").lower())
    for artist, items in list(albums_by_artist.items()):
        items.sort(key=lambda x: str(x.get("label") or "").lower())
        albums_by_artist[artist] = [
            {"kind": "album", "label": "Liked Songs", "value": _album_value(artist=artist, liked=True)},
            {"kind": "album", "label": "All Songs", "value": _album_value(artist=artist)},
        ] + items
    for genre, items in list(genre_albums.items()):
        items.sort(key=lambda x: str(x.get("label") or "").lower())
        if genre in any_genre:
            genre_albums[genre] = [
                {"kind": "album", "label": "Liked Songs", "value": _album_value(genre=genre, liked=True)},
                {"kind": "album", "label": "All Songs", "value": _album_value(genre=genre)},
            ] + items

    for key, items in tracks_by_key.items():
        items.sort(key=lambda x: _track_sort_tuple(str(x.get("badge") or "")) + (str(x.get("label") or ""),))

    return {
        "artists": [{"kind": "artist", "label": a, "value": a} for a in artists],
        "albums": albums_all,
        "albums_by_artist": albums_by_artist,
        "songs": [{"kind": "track", "label": str(t.get("title") or t.get("name") or "Track"), "rel": t.get("rel")} for t in songs[:3000]],
        "genres": [{"kind": "genre", "label": g, "value": g} for g in genres],
        "genre_albums": genre_albums,
        "tracks_by_key": tracks_by_key,
        "videos": [
            {"kind": "file", "label": v.get("name") or v.get("title") or "Video", "rel": v.get("rel"), "media": "video", "badge": "video"}
            for v in sorted(videos, key=lambda x: str(x.get("title") or x.get("name") or "").lower())[:3000]
        ],
        "movies": list(data.get("movies") or []),
        "shows": list(data.get("shows") or []),
    }


def load_index_snapshot(root_id: str, root_abs: str) -> Optional[dict]:
    with library_db() as conn:
        row = conn.execute(
            "SELECT root_abs, version FROM library_roots WHERE root_id = ?",
            (str(root_id or ""),),
        ).fetchone()
        if not row:
            return None
        if os.path.abspath(str(row["root_abs"] or "")) != os.path.abspath(root_abs):
            return None
        version = int(row["version"] or 0)
        rows = conn.execute(
            """
            SELECT mf.media_type, mf.metadata_json
            FROM media_files mf
            JOIN library_items li ON li.root_id = mf.root_id AND li.rel = mf.rel_path
            WHERE mf.root_id = ? AND li.deleted = 0
            ORDER BY mf.rel_path COLLATE NOCASE
            """,
            (str(root_id or ""),),
        ).fetchall()
    tracks = []
    videos = []
    for item in rows:
        try:
            payload = json.loads(str(item["metadata_json"] or "{}"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if str(item["media_type"] or "") == "video":
            # Video parser changes are not backward-compatible with old
            # snapshots; rebuild instead of presenting stale release names.
            if int(payload.get("parse_version") or 0) != 2:
                return None
            videos.append(payload)
        else:
            tracks.append(payload)
    if not tracks and not videos:
        return None
    out = {"tracks": tracks, "videos": videos}
    if version:
        out["version"] = version
    return out
    return None


def save_index_snapshot(root_id: str, root_abs: str, data: dict, *, mode: str = "") -> int:
    root_id = str(root_id or "")
    root_abs_norm = os.path.abspath(root_abs)
    payload_data = data if isinstance(data, dict) else {"tracks": [], "videos": []}
    now = time.time()
    with library_db() as conn:
        existing = conn.execute(
            "SELECT rel, size, mtime_ns, deleted FROM library_items WHERE root_id = ?",
            (root_id,),
        ).fetchall()
        old = {str(row["rel"]): (int(row["size"] or 0), int(row["mtime_ns"] or 0), int(row["deleted"] or 0)) for row in existing}
        next_items: dict[str, tuple[str, str, int, int]] = {}
        persisted_videos = payload_data.get("video_records") or payload_data.get("videos") or []
        for media_type, items in (("audio", payload_data.get("tracks") or []), ("video", persisted_videos)):
            for item in items:
                if not isinstance(item, dict):
                    continue
                rel = str(item.get("rel") or "")
                if not rel:
                    continue
                abs_path = os.path.abspath(os.path.join(root_abs_norm, rel.replace("/", os.sep)))
                size, mtime_ns = file_identity(abs_path)
                next_items[rel] = (abs_path, media_type, size, mtime_ns)
        changed = False
        for rel, (_, _, size, mtime_ns) in next_items.items():
            prev = old.get(rel)
            if prev is None or prev[0] != size or prev[1] != mtime_ns or prev[2]:
                changed = True
                break
        if not changed:
            for rel, prev in old.items():
                if not prev[2] and rel not in next_items:
                    changed = True
                    break

        row = conn.execute("SELECT version FROM library_roots WHERE root_id = ?", (root_id,)).fetchone()
        old_version = int(row["version"] or 0) if row else 0
        version = old_version + 1 if changed else old_version
        conn.execute(
            """
            INSERT INTO library_roots(root_id, root_abs, mode, version, last_scan_started_at, last_scan_finished_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_id) DO UPDATE SET
              root_abs=excluded.root_abs,
              mode=excluded.mode,
              version=excluded.version,
              last_scan_started_at=excluded.last_scan_started_at,
              last_scan_finished_at=excluded.last_scan_finished_at
            """,
            (root_id, root_abs_norm, str(mode or ""), version, now, now),
        )
        for rel, prev in old.items():
            if not prev[2] and rel not in next_items:
                conn.execute(
                    "UPDATE library_items SET deleted = 1, changed_at_version = ? WHERE root_id = ? AND rel = ?",
                    (version, root_id, rel),
                )
        for rel, (abs_path, media_type, size, mtime_ns) in next_items.items():
            ext = os.path.splitext(rel)[1].lower()
            changed_at = version if changed else old_version
            conn.execute(
                """
                INSERT INTO library_items(root_id, rel, abs_path, kind, ext, size, mtime_ns, deleted, changed_at_version)
                VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(root_id, rel) DO UPDATE SET
                  abs_path=excluded.abs_path,
                  kind=excluded.kind,
                  ext=excluded.ext,
                  size=excluded.size,
                  mtime_ns=excluded.mtime_ns,
                  deleted=0,
                  changed_at_version=CASE
                    WHEN library_items.size != excluded.size OR library_items.mtime_ns != excluded.mtime_ns OR library_items.deleted != 0
                    THEN excluded.changed_at_version
                    ELSE library_items.changed_at_version
                  END
                """,
                (root_id, rel, abs_path, media_type, ext, size, mtime_ns, changed_at),
            )
        for media_type, items in (("audio", payload_data.get("tracks") or []), ("video", persisted_videos)):
            for item in items:
                if not isinstance(item, dict):
                    continue
                rel = str(item.get("rel") or "")
                abs_path = os.path.abspath(os.path.join(root_abs_norm, rel.replace("/", os.sep)))
                size, mtime_ns = file_identity(abs_path)
                media_id = f"{root_id}:{rel}"
                conn.execute(
                    """
                    INSERT INTO media_files(
                      media_id, root_id, root_abs, rel_path, abs_path, media_type, size, mtime_ns,
                      duration, title, artist, album_artist, album, genre, track, tech, folder, indexed_at, metadata_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(root_id, rel_path) DO UPDATE SET
                      media_id=excluded.media_id,
                      root_abs=excluded.root_abs,
                      abs_path=excluded.abs_path,
                      media_type=excluded.media_type,
                      size=excluded.size,
                      mtime_ns=excluded.mtime_ns,
                      duration=excluded.duration,
                      title=excluded.title,
                      artist=excluded.artist,
                      album_artist=excluded.album_artist,
                      album=excluded.album,
                      genre=excluded.genre,
                      track=excluded.track,
                      tech=excluded.tech,
                      folder=excluded.folder,
                      indexed_at=excluded.indexed_at,
                      metadata_json=excluded.metadata_json
                    """,
                    (
                        media_id,
                        root_id,
                        root_abs_norm,
                        rel,
                        abs_path,
                        media_type,
                        size,
                        mtime_ns,
                        item.get("duration"),
                        str(item.get("title") or ""),
                        str(item.get("artist") or ""),
                        str(item.get("album_artist") or ""),
                        str(item.get("album") or ""),
                        str(item.get("genre") or ""),
                        str(item.get("track") or ""),
                        str(item.get("tech") or ""),
                        str(item.get("folder") or ""),
                        now,
                        json.dumps(item, ensure_ascii=False, sort_keys=True),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO media_metadata(
                      root_id, rel, title, artist, album_artist, album, genre, track, duration,
                      tech, codec, bit_depth, sample_rate, bitrate, size, mtime_ns, saved_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(root_id, rel) DO UPDATE SET
                      title=excluded.title,
                      artist=excluded.artist,
                      album_artist=excluded.album_artist,
                      album=excluded.album,
                      genre=excluded.genre,
                      track=excluded.track,
                      duration=excluded.duration,
                      tech=excluded.tech,
                      codec=excluded.codec,
                      bit_depth=excluded.bit_depth,
                      sample_rate=excluded.sample_rate,
                      bitrate=excluded.bitrate,
                      size=excluded.size,
                      mtime_ns=excluded.mtime_ns,
                      saved_at=excluded.saved_at
                    """,
                    (
                        root_id,
                        rel,
                        str(item.get("title") or ""),
                        str(item.get("artist") or ""),
                        str(item.get("album_artist") or ""),
                        str(item.get("album") or ""),
                        str(item.get("genre") or ""),
                        str(item.get("track") or ""),
                        item.get("duration"),
                        str(item.get("tech") or ""),
                        str(item.get("codec") or ""),
                        item.get("bit_depth"),
                        item.get("sample_rate"),
                        item.get("bitrate"),
                        size,
                        mtime_ns,
                        now,
                    ),
                )
        facets = _build_metadata_facets(payload_data)
        conn.execute(
            """
            INSERT INTO library_facets(root_id, facet, root_version, saved_at, data_json)
            VALUES(?, 'metadata', ?, ?, ?)
            ON CONFLICT(root_id, facet) DO UPDATE SET
              root_version=excluded.root_version,
              saved_at=excluded.saved_at,
              data_json=excluded.data_json
            """,
            (root_id, version, now, json.dumps(facets, ensure_ascii=False, sort_keys=True)),
        )
        for folder in payload_data.get("folder_entries") or []:
            if not isinstance(folder, dict):
                continue
            rel = str(folder.get("rel") or "").replace("\\", "/").strip("/")
            abs_dir = str(folder.get("abs_path") or "")
            entries = folder.get("entries") if isinstance(folder.get("entries"), list) else []
            conn.execute(
                """
                INSERT INTO folder_entries(root_id, rel, root_version, dir_mtime_ns, saved_at, entries_json)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_id, rel) DO UPDATE SET
                  root_version=excluded.root_version,
                  dir_mtime_ns=excluded.dir_mtime_ns,
                  saved_at=excluded.saved_at,
                  entries_json=excluded.entries_json
                """,
                (root_id, rel, version, _path_mtime_ns(abs_dir), now, json.dumps(entries, ensure_ascii=False, sort_keys=True)),
            )
        conn.execute("DELETE FROM folder_entries WHERE root_id = ? AND root_version < ?", (root_id, version))
        active_media_identity = {
            rel: (size, mtime_ns)
            for rel, (_abs_path, media_type, size, mtime_ns) in next_items.items()
            if media_type in ("audio", "video")
        }
        rows = conn.execute(
            "SELECT analysis_key, rel, size, mtime_ns, algorithm_version FROM visualizer_analysis WHERE root_id = ?",
            (root_id,),
        ).fetchall()
        for row in rows:
            rel = str(row["rel"] or "")
            ident = active_media_identity.get(rel)
            stale = (
                ident is None
                or int(row["size"] or 0) != int(ident[0] or 0)
                or int(row["mtime_ns"] or 0) != int(ident[1] or 0)
                or int(row["algorithm_version"] or 0) != ANALYSIS_ALGORITHM_VERSION
            )
            if stale:
                conn.execute("DELETE FROM visualizer_analysis WHERE analysis_key = ?", (str(row["analysis_key"] or ""),))
    return version


def load_library_facets(root_id: str, facet: str = "metadata") -> Optional[dict[str, Any]]:
    version = root_version(root_id)
    if not version:
        return None
    with library_db() as conn:
        row = conn.execute(
            """
            SELECT root_version, data_json
            FROM library_facets
            WHERE root_id = ? AND facet = ?
            """,
            (str(root_id or ""), str(facet or "metadata")),
        ).fetchone()
    if not row or int(row["root_version"] or 0) != version:
        return None
    try:
        data = json.loads(str(row["data_json"] or "{}"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def load_folder_entries(root_id: str, rel: str, dir_abs: str) -> Optional[dict]:
    rel_norm = str(rel or "").replace("\\", "/").strip("/")
    dir_mtime_ns = _path_mtime_ns(dir_abs)
    version = root_version(root_id)
    with library_db() as conn:
        row = conn.execute(
            """
            SELECT root_version, dir_mtime_ns, entries_json
            FROM folder_entries
            WHERE root_id = ? AND rel = ?
            """,
            (str(root_id or ""), rel_norm),
        ).fetchone()
    if not row:
        return None
    if int(row["root_version"] or 0) != version or int(row["dir_mtime_ns"] or 0) != dir_mtime_ns:
        return None
    try:
        entries = json.loads(str(row["entries_json"] or "[]"))
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    return {"entries": entries, "version": version, "stale": False}


def save_folder_entries(root_id: str, rel: str, dir_abs: str, entries: list[dict[str, Any]]) -> int:
    rel_norm = str(rel or "").replace("\\", "/").strip("/")
    version = root_version(root_id)
    payload = json.dumps(entries if isinstance(entries, list) else [], ensure_ascii=False, sort_keys=True)
    with library_db() as conn:
        conn.execute(
            """
            INSERT INTO folder_entries(root_id, rel, root_version, dir_mtime_ns, saved_at, entries_json)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(root_id, rel) DO UPDATE SET
              root_version=excluded.root_version,
              dir_mtime_ns=excluded.dir_mtime_ns,
              saved_at=excluded.saved_at,
              entries_json=excluded.entries_json
            """,
            (str(root_id or ""), rel_norm, version, _path_mtime_ns(dir_abs), time.time(), payload),
        )
    return version


def root_manifest(root_id: str, *, since_version: int = 0) -> Optional[dict[str, Any]]:
    version = root_version(root_id)
    if not version:
        return None
    params: list[Any] = [str(root_id or "")]
    where = "root_id = ?"
    if since_version:
        where += " AND changed_at_version > ?"
        params.append(int(since_version))
    with library_db() as conn:
        rows = conn.execute(
            f"""
            SELECT rel, kind, size, mtime_ns, deleted, changed_at_version
            FROM library_items
            WHERE {where}
            ORDER BY rel COLLATE NOCASE
            """,
            params,
        ).fetchall()
    return {
        "root_id": str(root_id or ""),
        "version": version,
        "items": [
            {
                "id": f"{root_id}:{row['rel']}",
                "rel": str(row["rel"] or ""),
                "mtime_ns": int(row["mtime_ns"] or 0),
                "size": int(row["size"] or 0),
                "media": str(row["kind"] or ""),
                "metadata_version": int(row["changed_at_version"] or 0),
                "deleted": bool(row["deleted"]),
            }
            for row in rows
        ],
    }


def load_search_cache(cache_key: str) -> Optional[dict[str, Any]]:
    now = time.time()
    with library_db() as conn:
        row = conn.execute(
            """
            SELECT source, query, extra_json, saved_at, expires_at, payload_json
            FROM search_cache
            WHERE cache_key = ?
            """,
            (str(cache_key or ""),),
        ).fetchone()
    if not row:
        return None
    expires_at = row["expires_at"]
    if expires_at is not None and float(expires_at or 0) > 0 and float(expires_at or 0) < now:
        return None
    try:
        extra = json.loads(str(row["extra_json"] or "{}"))
    except Exception:
        extra = {}
    try:
        payload = json.loads(str(row["payload_json"] or "{}"))
    except Exception:
        payload = {}
    return {
        "created": float(row["saved_at"] or 0),
        "engine": str(row["source"] or ""),
        "q": str(row["query"] or ""),
        "extra": extra if isinstance(extra, dict) else {},
        "payload": payload if isinstance(payload, dict) else {},
    }


def save_search_cache(cache_key: str, engine: str, q: str, extra: Optional[dict], payload: dict, *, ttl_seconds: int = 0) -> None:
    now = time.time()
    expires_at = now + int(ttl_seconds or 0) if int(ttl_seconds or 0) > 0 else None
    with library_db() as conn:
        conn.execute(
            """
            INSERT INTO search_cache(cache_key, source, query, extra_json, saved_at, expires_at, payload_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              source=excluded.source,
              query=excluded.query,
              extra_json=excluded.extra_json,
              saved_at=excluded.saved_at,
              expires_at=excluded.expires_at,
              payload_json=excluded.payload_json
            """,
            (
                str(cache_key or ""),
                str(engine or "").strip().lower(),
                str(q or "").strip(),
                json.dumps(extra if isinstance(extra, dict) else {}, ensure_ascii=False, sort_keys=True),
                now,
                expires_at,
                json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False, sort_keys=True),
            ),
        )


def load_search_history(max_items: int = 0, *, user_id: str = "") -> list[dict[str, Any]]:
    limit = max(0, int(max_items or 0))
    sql = "SELECT query, engine, cache_key, ts FROM search_history WHERE user_id=? ORDER BY ts DESC"
    params: list[Any] = [str(user_id or "")]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with library_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "q": str(row["query"] or ""),
            "engine": str(row["engine"] or ""),
            "cache_key": str(row["cache_key"] or ""),
            "ts": float(row["ts"] or 0),
        }
        for row in rows
    ]


def record_search_history_row(q: str, engine: str, cache_key: str, *, max_items: int = 0, user_id: str = "") -> None:
    qq = str(q or "").strip()
    eng = str(engine or "").strip().lower()
    key = str(cache_key or "").strip()
    if not qq or not eng or not key:
        return
    owner = str(user_id or "")
    with library_db() as conn:
        conn.execute("DELETE FROM search_history WHERE user_id=? AND query=? AND engine=?", (owner, qq, eng))
        conn.execute(
            "INSERT INTO search_history(user_id, query, engine, cache_key, ts) VALUES(?, ?, ?, ?, ?)",
            (owner, qq, eng, key, time.time()),
        )
        limit = max(0, int(max_items or 0))
        if limit:
            conn.execute(
                """
                DELETE FROM search_history
                WHERE user_id=? AND id NOT IN (
                  SELECT id FROM search_history WHERE user_id=? ORDER BY ts DESC LIMIT ?
                )
                """,
                (owner, owner, limit),
            )


def clear_search_history(*, user_id: str) -> None:
    with library_db() as conn:
        conn.execute("DELETE FROM search_history WHERE user_id=?", (str(user_id or ""),))


def clear_search_cache() -> None:
    with library_db() as conn:
        conn.execute("DELETE FROM search_cache")


def clear_library_cache() -> None:
    with library_db() as conn:
        conn.execute("DELETE FROM media_files")
        conn.execute("DELETE FROM media_metadata")
        conn.execute("DELETE FROM metadata_cache")
        conn.execute("DELETE FROM folder_entries")
        conn.execute("DELETE FROM library_facets")
        conn.execute("DELETE FROM library_items")
        conn.execute("DELETE FROM library_roots")
        conn.execute("DELETE FROM art_palette_cache")
        conn.execute("DELETE FROM media_palettes")
        conn.execute("DELETE FROM visualizer_analysis")


def update_media_art_identity(root_id: str, rels: list[str], art_identity: str) -> None:
    clean_rels = [str(rel or "") for rel in (rels or []) if str(rel or "")]
    identity = str(art_identity or "")
    if not clean_rels or not identity:
        return
    with library_db() as conn:
        for rel in clean_rels:
            row = conn.execute(
                "SELECT metadata_json FROM media_files WHERE root_id = ? AND rel_path = ?",
                (str(root_id or ""), rel),
            ).fetchone()
            if not row:
                continue
            try:
                payload = json.loads(str(row["metadata_json"] or "{}"))
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload["art_identity"] = identity
            payload["artIdentity"] = identity
            conn.execute(
                "UPDATE media_files SET metadata_json = ? WHERE root_id = ? AND rel_path = ?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), str(root_id or ""), rel),
            )


def load_palette(cache_key: str) -> Optional[dict]:
    return load_packed_palette(str(cache_key or ""))


def load_palette_for_media(root_id: str, rel: str) -> Optional[dict]:
    with library_db() as conn:
        media_row = conn.execute(
            "SELECT metadata_json FROM media_files WHERE root_id = ? AND rel_path = ?",
            (str(root_id or ""), str(rel or "")),
        ).fetchone()
    if media_row:
        try:
            media_payload = json.loads(str(media_row["metadata_json"] or "{}"))
        except Exception:
            media_payload = {}
        if isinstance(media_payload, dict):
            art_identity = str(media_payload.get("art_identity") or media_payload.get("artIdentity") or "")
            if art_identity:
                palette = load_palette(art_identity)
                if palette is not None:
                    return palette
    return load_packed_palette(root_id=str(root_id or ""), rel=str(rel or ""))


def save_palette(cache_key: str, palette: dict, *, source_kind: str = "", source_identity: str = "", root_id: str = "", rel: str = "") -> None:
    save_packed_palette(str(cache_key or ""), palette, source_kind=source_kind, source_identity=source_identity, root_id=root_id, rel=rel)


def _delta_decode_analysis_blob(delta_blob: bytes, frame_stride: int) -> bytes:
    stride = max(1, int(frame_stride or 0))
    payload = bytes(delta_blob or b"")
    if not payload or len(payload) % stride:
        raise ValueError("Invalid delta analysis payload")
    decoded = bytearray(payload[:stride])
    previous = bytearray(payload[:stride])
    for offset in range(stride, len(payload), stride):
        frame = payload[offset:offset + stride]
        restored = bytearray(stride)
        for index, value in enumerate(frame):
            restored[index] = (previous[index] + value) & 0xFF
        decoded.extend(restored)
        previous = restored
    return bytes(decoded)


def load_visualizer_analysis(analysis_key: str, *, decoder_settings_hash: str = "") -> Optional[dict[str, Any]]:
    with library_db() as conn:
        row = conn.execute(
            """
            SELECT media_id, root_id, rel, abs_path, size, mtime_ns, duration, analysis_rate_hz,
                   band_count, compression, decoder_settings_hash, algorithm_version,
                   frame_count, feature_blob, metadata_json
            FROM visualizer_analysis
            WHERE analysis_key = ?
            """,
            (str(analysis_key or ""),),
        ).fetchone()
    if not row:
        return None
    if int(row["algorithm_version"] or 0) != ANALYSIS_ALGORITHM_VERSION:
        return None
    if int(row["band_count"] or 0) != ANALYSIS_BAND_COUNT:
        return None
    if decoder_settings_hash and str(row["decoder_settings_hash"] or "") != str(decoder_settings_hash):
        return None
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except Exception:
        metadata = {}
    stored_blob = bytes(row["feature_blob"] or b"")
    try:
        feature_blob = decode_blob(stored_blob)
        storage_compression = "envelope"
    except CodecError:
        # Ordered migration of pre-envelope analysis values.
        if str(row["compression"] or "") == "zlib":
            import zlib
            feature_blob = zlib.decompress(stored_blob)
        else:
            feature_blob = stored_blob
        envelope, storage_compression, _ = encode_blob(feature_blob)
        with library_db() as migrate_conn:
            migrate_conn.execute("UPDATE visualizer_analysis SET feature_blob=?,compression=? WHERE analysis_key=?",
                (envelope, "none", str(analysis_key or "")))
    compression = str(row["compression"] or "none")
    if compression == ANALYSIS_DELTA_ENCODING:
        try:
            import zlib
            stride = int(metadata.get("frame_stride") or (int(row["band_count"] or 0) + 2))
            feature_blob = _delta_decode_analysis_blob(zlib.decompress(feature_blob), stride)
        except Exception:
            return None
    elif compression not in {"", "none", "raw", "zlib"}:
        return None
    frame_stride = int(metadata.get("frame_stride") or (int(row["band_count"] or 0) + 2))
    frame_count = int(row["frame_count"] or 0)
    if frame_stride != ANALYSIS_BAND_COUNT + 2 or frame_count <= 0 or len(feature_blob) != frame_stride * frame_count:
        return None
    return {
        "analysis_key": str(analysis_key or ""),
        "media_id": str(row["media_id"] or ""),
        "root_id": str(row["root_id"] or ""),
        "rel": str(row["rel"] or ""),
        "abs_path": str(row["abs_path"] or ""),
        "size": int(row["size"] or 0),
        "mtime_ns": int(row["mtime_ns"] or 0),
        "duration": row["duration"],
        "analysis_rate_hz": int(row["analysis_rate_hz"] or 30),
        "band_count": int(row["band_count"] or ANALYSIS_BAND_COUNT),
        "compression": "none",
        "storage_compression": storage_compression,
        "decoder_settings_hash": str(row["decoder_settings_hash"] or ""),
        "algorithm_version": int(row["algorithm_version"] or ANALYSIS_ALGORITHM_VERSION),
        "frame_count": frame_count,
        "feature_blob": feature_blob,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def load_visualizer_analysis_for_media(root_id: str, rel: str, *, decoder_settings_hash: str = "") -> Optional[dict[str, Any]]:
    with library_db() as conn:
        row = conn.execute(
            """
            SELECT va.analysis_key
            FROM visualizer_analysis va
            JOIN media_files mf
              ON mf.root_id = va.root_id
             AND mf.rel_path = va.rel
             AND mf.size = va.size
             AND mf.mtime_ns = va.mtime_ns
            WHERE va.root_id = ?
              AND va.rel = ?
              AND va.algorithm_version = ?
              AND va.band_count = ?
              AND mf.media_type IN ('audio', 'video')
            ORDER BY va.saved_at DESC
            LIMIT 1
            """,
            (str(root_id or ""), str(rel or ""), ANALYSIS_ALGORITHM_VERSION, ANALYSIS_BAND_COUNT),
        ).fetchone()
    if not row:
        return None
    return load_visualizer_analysis(str(row["analysis_key"] or ""), decoder_settings_hash=decoder_settings_hash)


def save_visualizer_analysis(
    analysis_key: str,
    *,
    media_id: str,
    root_id: str = "",
    rel: str = "",
    abs_path: str,
    duration: Optional[float],
    analysis_rate_hz: int,
    band_count: int,
    frame_count: int,
    feature_blob: bytes,
    compression: str = "none",
    decoder_settings_hash: str = "",
    metadata: Optional[dict] = None,
) -> None:
    size, mtime_ns = file_identity(abs_path)
    raw_blob = bytes(feature_blob or b"")
    if compression == "zlib":
        import zlib
        raw_blob = zlib.decompress(raw_blob)
    envelope, _storage_compression, _raw_len = encode_blob(raw_blob)
    with library_db() as conn:
        conn.execute(
            """
            INSERT INTO visualizer_analysis(
              analysis_key, media_id, root_id, rel, abs_path, size, mtime_ns, duration,
              analysis_rate_hz, band_count, compression, decoder_settings_hash,
              algorithm_version, saved_at, frame_count, feature_blob, metadata_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(analysis_key) DO UPDATE SET
              media_id=excluded.media_id,
              root_id=excluded.root_id,
              rel=excluded.rel,
              abs_path=excluded.abs_path,
              size=excluded.size,
              mtime_ns=excluded.mtime_ns,
              duration=excluded.duration,
              analysis_rate_hz=excluded.analysis_rate_hz,
              band_count=excluded.band_count,
              compression=excluded.compression,
              decoder_settings_hash=excluded.decoder_settings_hash,
              algorithm_version=excluded.algorithm_version,
              saved_at=excluded.saved_at,
              frame_count=excluded.frame_count,
              feature_blob=excluded.feature_blob,
              metadata_json=excluded.metadata_json
            """,
            (
                str(analysis_key or ""),
                str(media_id or ""),
                str(root_id or ""),
                str(rel or ""),
                os.path.abspath(abs_path),
                size,
                mtime_ns,
                duration,
                int(analysis_rate_hz or 30),
                int(band_count or ANALYSIS_BAND_COUNT),
                str(compression or "none"),
                str(decoder_settings_hash or ""),
                ANALYSIS_ALGORITHM_VERSION,
                time.time(),
                int(frame_count or 0),
                envelope,
                json.dumps(metadata if isinstance(metadata, dict) else {}, ensure_ascii=False, sort_keys=True),
            ),
        )


def save_passkey_challenge(challenge_id: str, *, user_id: str, action: str, challenge: dict[str, Any], ttl_seconds: int = 300) -> None:
    now = time.time()
    with auth_db() as conn:
        conn.execute("DELETE FROM passkey_challenges WHERE expires_at < ?", (now,))
        conn.execute(
            """
            INSERT INTO passkey_challenges(id, username, user_id, action, challenge_json, created_at, expires_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              username=excluded.username,
              user_id=excluded.user_id,
              action=excluded.action,
              challenge_json=excluded.challenge_json,
              created_at=excluded.created_at,
              expires_at=excluded.expires_at
            """,
            (
                str(challenge_id or ""),
                "",
                str(user_id or ""),
                str(action or ""),
                json.dumps(challenge if isinstance(challenge, dict) else {}, ensure_ascii=False, sort_keys=True),
                now,
                now + int(ttl_seconds or 300),
            ),
        )


def pop_passkey_challenge(challenge_id: str, *, action: str = "") -> Optional[dict[str, Any]]:
    now = time.time()
    with auth_db() as conn:
        row = conn.execute(
            "SELECT user_id, action, challenge_json, expires_at FROM passkey_challenges WHERE id = ?",
            (str(challenge_id or ""),),
        ).fetchone()
        conn.execute("DELETE FROM passkey_challenges WHERE id = ?", (str(challenge_id or ""),))
        conn.execute("DELETE FROM passkey_challenges WHERE expires_at < ?", (now,))
    if not row:
        return None
    if float(row["expires_at"] or 0) < now:
        return None
    if action and str(row["action"] or "") != str(action):
        return None
    try:
        challenge = json.loads(str(row["challenge_json"] or "{}"))
    except Exception:
        challenge = {}
    return {"user_id": str(row["user_id"] or ""), "action": str(row["action"] or ""), "challenge": challenge}


def passkeys_for_user(user_id: str, *, include_revoked: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM user_passkeys WHERE user_id = ?"
    params: list[Any] = [str(user_id or "")]
    if not include_revoked:
        sql += " AND revoked_at IS NULL"
    sql += " ORDER BY created_at DESC"
    with auth_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({key: row[key] for key in row.keys()})
    return out


def passkey_by_credential_id(credential_id: str) -> Optional[dict[str, Any]]:
    with auth_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_passkeys WHERE credential_id = ? AND revoked_at IS NULL",
            (str(credential_id or ""),),
        ).fetchone()
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def save_user_passkey(
    *,
    user_id: str,
    credential_id: str,
    public_key: str,
    sign_count: int,
    transports: list[str] | None = None,
    aaguid: str = "",
    device_label: str = "",
    user_verified_required: bool = False,
) -> None:
    with auth_db() as conn:
        conn.execute(
            """
            INSERT INTO user_passkeys(
              username, user_id, credential_id, public_key, sign_count, transports, aaguid,
              device_label, created_at, user_verified_required
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(credential_id) DO UPDATE SET
              user_id=excluded.user_id,
              public_key=excluded.public_key,
              sign_count=excluded.sign_count,
              transports=excluded.transports,
              aaguid=excluded.aaguid,
              device_label=excluded.device_label,
              revoked_at=NULL,
              user_verified_required=excluded.user_verified_required
            """,
            (
                "",
                str(user_id or ""),
                str(credential_id or ""),
                str(public_key or ""),
                int(sign_count or 0),
                json.dumps(transports or [], ensure_ascii=False),
                str(aaguid or ""),
                str(device_label or "This device"),
                time.time(),
                1 if user_verified_required else 0,
            ),
        )


def update_passkey_sign_count(credential_id: str, sign_count: int) -> None:
    with auth_db() as conn:
        conn.execute(
            "UPDATE user_passkeys SET sign_count = ?, last_used_at = ? WHERE credential_id = ?",
            (int(sign_count or 0), time.time(), str(credential_id or "")),
        )


def revoke_passkey(user_id: str, credential_id: str) -> None:
    with auth_db() as conn:
        conn.execute(
            "UPDATE user_passkeys SET revoked_at = ? WHERE user_id = ? AND credential_id = ?",
            (time.time(), str(user_id or ""), str(credential_id or "")),
        )


def rename_passkey(user_id: str, credential_id: str, device_label: str) -> None:
    label = str(device_label or "").strip()[:80] or "This device"
    with auth_db() as conn:
        conn.execute(
            "UPDATE user_passkeys SET device_label = ? WHERE user_id = ? AND credential_id = ? AND revoked_at IS NULL",
            (label, str(user_id or ""), str(credential_id or "")),
        )
