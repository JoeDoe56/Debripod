from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable


def _v1(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
      version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS app_settings (
      user_id TEXT NOT NULL DEFAULT '', key TEXT NOT NULL, value_json TEXT NOT NULL,
      updated_at REAL NOT NULL, PRIMARY KEY(user_id, key)
    );
    CREATE TABLE IF NOT EXISTS service_status (
      user_id TEXT NOT NULL DEFAULT '', service TEXT NOT NULL, saved INTEGER NOT NULL DEFAULT 0,
      keyring_ref TEXT NOT NULL DEFAULT '', provider_identity TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL,
      PRIMARY KEY(user_id, service)
    );
    CREATE TABLE IF NOT EXISTS users (
      user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      created_at REAL NOT NULL, updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS playback_state (
      user_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tasks (
      task_id TEXT PRIMARY KEY, owner TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'debrid',
      title TEXT NOT NULL DEFAULT '', original_result_title TEXT NOT NULL DEFAULT '', task_dir TEXT NOT NULL DEFAULT '',
      provider TEXT NOT NULL DEFAULT '', remote_task_id TEXT NOT NULL DEFAULT '', source_blob BLOB,
      source_codec TEXT NOT NULL DEFAULT 'raw', source_uncompressed_bytes INTEGER NOT NULL DEFAULT 0,
      state_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL, version TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_tasks_dir ON tasks(task_dir);
    CREATE TABLE IF NOT EXISTS task_files (
      task_id TEXT NOT NULL, file_id TEXT NOT NULL, remote_name TEXT NOT NULL DEFAULT '', local_path TEXT NOT NULL DEFAULT '',
      selected INTEGER NOT NULL DEFAULT 0, state_json TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL,
      PRIMARY KEY(task_id, file_id), FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_task_files_local_path ON task_files(local_path);
    CREATE TABLE IF NOT EXISTS lastfm_loved_tracks (
      user_id TEXT NOT NULL DEFAULT '', track_key TEXT NOT NULL, loved INTEGER NOT NULL DEFAULT 1,
      metadata_json TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL, PRIMARY KEY(user_id, track_key)
    );
    CREATE TABLE IF NOT EXISTS legacy_imports (
      source_path TEXT PRIMARY KEY, source_kind TEXT NOT NULL, imported_at REAL NOT NULL,
      row_counts_json TEXT NOT NULL DEFAULT '{}', backup_path TEXT NOT NULL DEFAULT ''
    );
    """)


def _v2(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS media_palettes (
      palette_key TEXT PRIMARY KEY, root_id TEXT NOT NULL DEFAULT '', rel TEXT NOT NULL DEFAULT '',
      source_kind TEXT NOT NULL DEFAULT '', source_identity TEXT NOT NULL DEFAULT '', color_count INTEGER NOT NULL,
      colors_blob BLOB NOT NULL, encoding_version INTEGER NOT NULL, compression TEXT NOT NULL DEFAULT 'raw',
      uncompressed_bytes INTEGER NOT NULL, saved_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_media_palettes_media ON media_palettes(root_id, rel);
    CREATE TABLE IF NOT EXISTS video_palette_timelines (
      analysis_key TEXT PRIMARY KEY, media_id TEXT NOT NULL DEFAULT '', root_id TEXT NOT NULL DEFAULT '',
      rel TEXT NOT NULL DEFAULT '', abs_path TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
      mtime_ns INTEGER NOT NULL DEFAULT 0, encoding_version INTEGER NOT NULL, sample_rate_hz INTEGER NOT NULL,
      sample_count INTEGER NOT NULL, payload_blob BLOB NOT NULL, compression TEXT NOT NULL DEFAULT 'raw',
      uncompressed_bytes INTEGER NOT NULL, saved_at REAL NOT NULL
    );
    """)


def _v3(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS library_roots(root_id TEXT PRIMARY KEY,root_abs TEXT NOT NULL,mode TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 0,last_scan_started_at REAL,last_scan_finished_at REAL);
    CREATE TABLE IF NOT EXISTS library_items(root_id TEXT NOT NULL,rel TEXT NOT NULL,abs_path TEXT NOT NULL,kind TEXT NOT NULL DEFAULT '',ext TEXT NOT NULL DEFAULT '',size INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0,changed_at_version INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(root_id,rel));
    CREATE INDEX IF NOT EXISTS idx_library_items_root_deleted ON library_items(root_id,deleted,kind);
    CREATE INDEX IF NOT EXISTS idx_library_items_abs_identity ON library_items(abs_path,size,mtime_ns);
    CREATE TABLE IF NOT EXISTS folder_entries(root_id TEXT NOT NULL,rel TEXT NOT NULL DEFAULT '',root_version INTEGER NOT NULL DEFAULT 0,dir_mtime_ns INTEGER NOT NULL DEFAULT 0,saved_at REAL NOT NULL,entries_json TEXT NOT NULL,PRIMARY KEY(root_id,rel));
    CREATE TABLE IF NOT EXISTS media_files(media_id TEXT PRIMARY KEY,root_id TEXT NOT NULL DEFAULT '',root_abs TEXT NOT NULL DEFAULT '',rel_path TEXT NOT NULL DEFAULT '',abs_path TEXT NOT NULL,media_type TEXT NOT NULL DEFAULT '',size INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,duration REAL,title TEXT NOT NULL DEFAULT '',artist TEXT NOT NULL DEFAULT '',album_artist TEXT NOT NULL DEFAULT '',album TEXT NOT NULL DEFAULT '',genre TEXT NOT NULL DEFAULT '',track TEXT NOT NULL DEFAULT '',tech TEXT NOT NULL DEFAULT '',folder TEXT NOT NULL DEFAULT '',indexed_at REAL NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',UNIQUE(root_id,rel_path));
    CREATE INDEX IF NOT EXISTS idx_media_files_root_type ON media_files(root_id,media_type);
    CREATE INDEX IF NOT EXISTS idx_media_files_abs_identity ON media_files(abs_path,size,mtime_ns);
    CREATE TABLE IF NOT EXISTS media_metadata(root_id TEXT NOT NULL,rel TEXT NOT NULL,title TEXT NOT NULL DEFAULT '',artist TEXT NOT NULL DEFAULT '',album_artist TEXT NOT NULL DEFAULT '',album TEXT NOT NULL DEFAULT '',genre TEXT NOT NULL DEFAULT '',track TEXT NOT NULL DEFAULT '',duration REAL,tech TEXT NOT NULL DEFAULT '',codec TEXT NOT NULL DEFAULT '',bit_depth INTEGER,sample_rate INTEGER,bitrate INTEGER,size INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,saved_at REAL NOT NULL,PRIMARY KEY(root_id,rel));
    CREATE TABLE IF NOT EXISTS metadata_cache(abs_path TEXT PRIMARY KEY,size INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,saved_at REAL NOT NULL,meta_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS art_palette_cache(cache_key TEXT PRIMARY KEY,root_id TEXT NOT NULL DEFAULT '',rel TEXT NOT NULL DEFAULT '',source_kind TEXT NOT NULL DEFAULT '',source_identity TEXT NOT NULL DEFAULT '',size INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 1,saved_at REAL NOT NULL,palette_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS visualizer_analysis(analysis_key TEXT PRIMARY KEY,media_id TEXT NOT NULL DEFAULT '',root_id TEXT NOT NULL DEFAULT '',rel TEXT NOT NULL DEFAULT '',abs_path TEXT NOT NULL,size INTEGER NOT NULL DEFAULT 0,mtime_ns INTEGER NOT NULL DEFAULT 0,duration REAL,analysis_rate_hz INTEGER NOT NULL DEFAULT 30,band_count INTEGER NOT NULL DEFAULT 7,compression TEXT NOT NULL DEFAULT 'raw',decoder_settings_hash TEXT NOT NULL DEFAULT '',algorithm_version INTEGER NOT NULL DEFAULT 1,saved_at REAL NOT NULL,frame_count INTEGER NOT NULL DEFAULT 0,feature_blob BLOB NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS library_facets(root_id TEXT NOT NULL,facet TEXT NOT NULL,root_version INTEGER NOT NULL DEFAULT 0,saved_at REAL NOT NULL,data_json TEXT NOT NULL,PRIMARY KEY(root_id,facet));
    CREATE TABLE IF NOT EXISTS search_cache(cache_key TEXT PRIMARY KEY,source TEXT NOT NULL DEFAULT '',query TEXT NOT NULL DEFAULT '',extra_json TEXT NOT NULL DEFAULT '{}',saved_at REAL NOT NULL,expires_at REAL,payload_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS search_history(id INTEGER PRIMARY KEY AUTOINCREMENT,query TEXT NOT NULL DEFAULT '',engine TEXT NOT NULL DEFAULT '',cache_key TEXT NOT NULL DEFAULT '',ts REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_search_history_recent ON search_history(ts DESC);
    CREATE TABLE IF NOT EXISTS show_aliases(root_id TEXT NOT NULL,alias_key TEXT NOT NULL,show_key TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(root_id,alias_key));
    CREATE TABLE IF NOT EXISTS user_passkeys(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL,credential_id TEXT NOT NULL UNIQUE,public_key TEXT NOT NULL,sign_count INTEGER NOT NULL DEFAULT 0,transports TEXT NOT NULL DEFAULT '[]',aaguid TEXT NOT NULL DEFAULT '',device_label TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,last_used_at REAL,revoked_at REAL,user_verified_required INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_user_passkeys_username ON user_passkeys(username,revoked_at);
    CREATE TABLE IF NOT EXISTS passkey_challenges(id TEXT PRIMARY KEY,username TEXT NOT NULL DEFAULT '',action TEXT NOT NULL,challenge_json TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL);
    """)


def _v4(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    ALTER TABLE folder_entries ADD COLUMN entries_blob BLOB;
    ALTER TABLE folder_entries ADD COLUMN entries_codec TEXT NOT NULL DEFAULT 'raw';
    ALTER TABLE folder_entries ADD COLUMN entries_uncompressed_bytes INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE library_facets ADD COLUMN data_blob BLOB;
    ALTER TABLE library_facets ADD COLUMN data_codec TEXT NOT NULL DEFAULT 'raw';
    ALTER TABLE library_facets ADD COLUMN data_uncompressed_bytes INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE search_cache ADD COLUMN payload_blob BLOB;
    ALTER TABLE search_cache ADD COLUMN payload_codec TEXT NOT NULL DEFAULT 'raw';
    ALTER TABLE search_cache ADD COLUMN payload_uncompressed_bytes INTEGER NOT NULL DEFAULT 0;
    """)


MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "structured_state", _v1),
    (2, "compact_palettes", _v2),
    (3, "unified_library_and_auth", _v3),
    (4, "large_value_envelopes", _v4),
)


def migrate(conn: sqlite3.Connection) -> int:
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for version, name, migration in MIGRATIONS:
        if version <= current:
            continue
        with conn:
            migration(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (version, name, time.time()),
            )
            conn.execute(f"PRAGMA user_version={version}")
        current = version
    return current
