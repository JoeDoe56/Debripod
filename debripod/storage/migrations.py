from __future__ import annotations

import sqlite3
import time
import hashlib
import json
import os
from collections.abc import Callable

from .backups import create_backup


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


def _v5(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS media_likes(
      username TEXT NOT NULL,
      media_key TEXT NOT NULL,
      media_type TEXT NOT NULL,
      root_id TEXT,
      rel TEXT,
      source TEXT NOT NULL,
      source_id TEXT,
      title TEXT,
      artist TEXT,
      album TEXT,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      liked INTEGER NOT NULL,
      updated_at REAL NOT NULL,
      PRIMARY KEY(username,media_key)
    );
    CREATE INDEX IF NOT EXISTS idx_media_likes_user_type_liked_updated
      ON media_likes(username,media_type,liked,updated_at);
    """)


def _v6(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    ALTER TABLE tasks ADD COLUMN origin_client_id TEXT NOT NULL DEFAULT '';
    CREATE TABLE IF NOT EXISTS push_subscriptions(
      username TEXT NOT NULL,
      client_id TEXT NOT NULL,
      endpoint TEXT NOT NULL,
      p256dh TEXT NOT NULL,
      auth TEXT NOT NULL,
      expiration_time REAL,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL,
      revoked INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(username,client_id,endpoint)
    );
    CREATE INDEX IF NOT EXISTS idx_push_subscriptions_client
      ON push_subscriptions(username,client_id,revoked);
    CREATE TABLE IF NOT EXISTS notification_deliveries(
      task_id TEXT NOT NULL,
      username TEXT NOT NULL,
      client_id TEXT NOT NULL,
      event TEXT NOT NULL,
      delivered_at REAL NOT NULL,
      status TEXT NOT NULL,
      UNIQUE(task_id,username,client_id,event)
    );
    """)


def _v7(conn: sqlite3.Connection) -> None:
    # Retired before release; retained as a no-op so historical user_version
    # values still advance monotonically.
    pass


def _v8(conn: sqlite3.Connection) -> None:
    # Remove the obsolete generic torrent-source status table from databases
    # that ran the original v7 migration before the fixed-adapter rewrite.
    conn.execute("DROP TABLE IF EXISTS indexer_status")


def _v9(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS auth_sessions(
      token_hash BLOB PRIMARY KEY,
      user_id TEXT NOT NULL DEFAULT '',
      csrf_token TEXT NOT NULL,
      data_json TEXT NOT NULL DEFAULT '{}',
      created_unix INTEGER NOT NULL,
      last_seen_unix INTEGER NOT NULL,
      expires_unix INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_unix);
    CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id,expires_unix);
    """)


def _v10(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS database_backup_events(
      backup_path TEXT PRIMARY KEY,
      automatic INTEGER NOT NULL,
      reason TEXT NOT NULL,
      schema_version INTEGER NOT NULL,
      bytes INTEGER NOT NULL,
      created_at REAL NOT NULL
    );
    """)


def _v11(conn: sqlite3.Connection) -> None:
    user_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(users)")}
    passkey_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(user_passkeys)")}
    challenge_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(passkey_challenges)")}
    if "role" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('owner','user'))")
    if "user_id" not in passkey_columns:
        conn.execute("ALTER TABLE user_passkeys ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    if "user_id" not in challenge_columns:
        conn.execute("ALTER TABLE passkey_challenges ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_user_passkeys_user_id ON user_passkeys(user_id,revoked_at);
    CREATE INDEX IF NOT EXISTS idx_passkey_challenges_user_id ON passkey_challenges(user_id,expires_at);
    """)
    first = conn.execute("SELECT user_id FROM users ORDER BY created_at, user_id LIMIT 1").fetchone()
    if first:
        conn.execute("UPDATE users SET role='user' WHERE role NOT IN ('owner','user') OR role IS NULL")
        conn.execute("UPDATE users SET role='owner' WHERE user_id=?", (str(first[0]),))
    conn.execute("UPDATE user_passkeys SET user_id=COALESCE((SELECT user_id FROM users WHERE users.username=user_passkeys.username), user_id, '') WHERE user_id='' ")
    conn.execute("UPDATE passkey_challenges SET user_id=COALESCE((SELECT user_id FROM users WHERE users.username=passkey_challenges.username), user_id, '') WHERE user_id='' ")


def _v12(conn: sqlite3.Connection) -> None:
    """Move all durable user-owned rows to immutable user IDs.

    Earlier releases used a mixture of username keys and one shared playback /
    search-history record.  The migration keeps username columns temporarily so
    an interrupted upgrade remains recoverable, but every new query uses the
    canonical ``user_id`` columns added here.
    """
    columns = {
        table: {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        for table in ("tasks", "search_history", "media_likes", "push_subscriptions", "notification_deliveries")
    }
    if "owner_user_id" not in columns["tasks"]:
        conn.execute("ALTER TABLE tasks ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''")
    if "user_id" not in columns["search_history"]:
        conn.execute("ALTER TABLE search_history ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    if "user_id" not in columns["media_likes"]:
        conn.execute("ALTER TABLE media_likes ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    if "user_id" not in columns["push_subscriptions"]:
        conn.execute("ALTER TABLE push_subscriptions ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    if "user_id" not in columns["notification_deliveries"]:
        conn.execute("ALTER TABLE notification_deliveries ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")

    # Copy old per-username data to its stable ID before removing legacy keys.
    # INSERT OR IGNORE ensures a newer canonical row always wins on retries.
    conn.execute(
        """INSERT OR IGNORE INTO app_settings(user_id,key,value_json,updated_at)
           SELECT u.user_id,t.key,t.value_json,t.updated_at FROM app_settings AS t
           JOIN users AS u ON u.username=t.user_id WHERE t.user_id<>''"""
    )
    conn.execute("DELETE FROM app_settings WHERE user_id<>'' AND user_id IN (SELECT username FROM users)")
    conn.execute(
        """INSERT OR IGNORE INTO service_status(user_id,service,saved,keyring_ref,provider_identity,updated_at)
           SELECT u.user_id,t.service,t.saved,t.keyring_ref,t.provider_identity,t.updated_at FROM service_status AS t
           JOIN users AS u ON u.username=t.user_id WHERE t.user_id<>''"""
    )
    conn.execute("DELETE FROM service_status WHERE user_id<>'' AND user_id IN (SELECT username FROM users)")
    conn.execute(
        """INSERT OR IGNORE INTO playback_state(user_id,state_json,updated_at)
           SELECT u.user_id,t.state_json,t.updated_at FROM playback_state AS t
           JOIN users AS u ON u.username=t.user_id WHERE t.user_id<>''"""
    )
    conn.execute("DELETE FROM playback_state WHERE user_id<>'' AND user_id IN (SELECT username FROM users)")

    # The first SELECT above cannot be used for tables whose primary-key shape
    # includes a username.  Those retain their legacy column for compatibility
    # and gain a canonical ownership column instead.
    conn.execute("UPDATE tasks SET owner_user_id=COALESCE((SELECT user_id FROM users WHERE users.username=tasks.owner), owner_user_id, '') WHERE owner_user_id='' ")
    conn.execute("UPDATE media_likes SET user_id=COALESCE((SELECT user_id FROM users WHERE users.username=media_likes.username), user_id, '') WHERE user_id='' ")
    conn.execute("UPDATE push_subscriptions SET user_id=COALESCE((SELECT user_id FROM users WHERE users.username=push_subscriptions.username), user_id, '') WHERE user_id='' ")
    conn.execute("UPDATE notification_deliveries SET user_id=COALESCE((SELECT user_id FROM users WHERE users.username=notification_deliveries.username), user_id, '') WHERE user_id='' ")
    conn.execute("""DELETE FROM media_likes AS legacy WHERE legacy.user_id<>'' AND legacy.username<>legacy.user_id
                    AND EXISTS (SELECT 1 FROM media_likes AS canonical WHERE canonical.username=legacy.user_id AND canonical.media_key=legacy.media_key)""")
    conn.execute("UPDATE media_likes SET username=user_id WHERE user_id<>'' AND username<>user_id")
    conn.execute("""DELETE FROM push_subscriptions AS legacy WHERE legacy.user_id<>'' AND legacy.username<>legacy.user_id
                    AND EXISTS (SELECT 1 FROM push_subscriptions AS canonical WHERE canonical.username=legacy.user_id AND canonical.client_id=legacy.client_id AND canonical.endpoint=legacy.endpoint)""")
    conn.execute("UPDATE push_subscriptions SET username=user_id WHERE user_id<>'' AND username<>user_id")
    conn.execute("""DELETE FROM notification_deliveries AS legacy WHERE legacy.user_id<>'' AND legacy.username<>legacy.user_id
                    AND EXISTS (SELECT 1 FROM notification_deliveries AS canonical WHERE canonical.username=legacy.user_id AND canonical.task_id=legacy.task_id AND canonical.client_id=legacy.client_id AND canonical.event=legacy.event)""")
    conn.execute("UPDATE notification_deliveries SET username=user_id WHERE user_id<>'' AND username<>user_id")
    conn.execute(
        """INSERT OR IGNORE INTO lastfm_loved_tracks(user_id,track_key,loved,metadata_json,updated_at)
           SELECT u.user_id,t.track_key,t.loved,t.metadata_json,t.updated_at FROM lastfm_loved_tracks AS t
           JOIN users AS u ON u.username=t.user_id WHERE t.user_id<>''"""
    )
    conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id<>'' AND user_id IN (SELECT username FROM users)")

    # A pre-multiuser shared playback row and history have no trustworthy owner.
    # Preserve them only when there is exactly one account; otherwise leaving
    # them unowned prevents accidental cross-user disclosure.
    users = conn.execute("SELECT user_id FROM users ORDER BY created_at,user_id").fetchall()
    if len(users) == 1:
        user_id = str(users[0][0])
        conn.execute(
            """INSERT OR IGNORE INTO playback_state(user_id,state_json,updated_at)
               SELECT ?,state_json,updated_at FROM playback_state WHERE user_id=''""",
            (user_id,),
        )
        conn.execute("DELETE FROM playback_state WHERE user_id='' ")
        conn.execute("UPDATE search_history SET user_id=? WHERE user_id='' ", (user_id,))

    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_tasks_owner_user_id_updated ON tasks(owner_user_id,updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_search_history_user_recent ON search_history(user_id,ts DESC);
    CREATE INDEX IF NOT EXISTS idx_media_likes_user_id_type_liked_updated ON media_likes(user_id,media_type,liked,updated_at);
    CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user_client ON push_subscriptions(user_id,client_id,revoked);
    CREATE INDEX IF NOT EXISTS idx_notification_deliveries_user_task ON notification_deliveries(user_id,task_id);
    """)


def _v13(conn: sqlite3.Connection) -> None:
    """Create user-to-root associations without duplicating physical roots."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS user_library_roots(
      user_id TEXT NOT NULL,
      root_id TEXT NOT NULL,
      display_name TEXT NOT NULL DEFAULT '',
      mode TEXT NOT NULL DEFAULT 'metadata',
      source TEXT NOT NULL DEFAULT 'library',
      sort_order INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL,
      PRIMARY KEY(user_id,root_id)
    );
    CREATE INDEX IF NOT EXISTS idx_user_library_roots_user_order ON user_library_roots(user_id,sort_order,root_id);
    CREATE INDEX IF NOT EXISTS idx_user_library_roots_root ON user_library_roots(root_id,user_id);
    """)
    now = time.time()
    rows = conn.execute(
        """SELECT user_id,key,value_json FROM app_settings
           WHERE user_id<>'' AND key IN ('LIBRARY_FOLDERS','DOWNLOAD_DIR','SOULSEEK_DOWNLOAD_DIR','YOUTUBE_DOWNLOAD_DIR')"""
    ).fetchall()
    settings_by_user: dict[str, dict[str, object]] = {}
    for user_id, key, raw_value in rows:
        try:
            value = json.loads(str(raw_value or "null"))
        except (TypeError, ValueError):
            value = None
        settings_by_user.setdefault(str(user_id), {})[str(key)] = value
    labels = {
        "DOWNLOAD_DIR": ("Debrid", "debrid"),
        "SOULSEEK_DOWNLOAD_DIR": ("Soulseek", "soulseek"),
        "YOUTUBE_DOWNLOAD_DIR": ("YouTube", "youtube"),
    }
    for user_id, settings in settings_by_user.items():
        raw_value = settings.get("LIBRARY_FOLDERS")
        try:
            folders = raw_value if isinstance(raw_value, list) else []
        except TypeError:
            folders = []
        specs: list[tuple[str, str, str, str]] = []
        for spec in folders:
            if isinstance(spec, dict):
                specs.append((str(spec.get("path") or ""), "", str(spec.get("mode") or "metadata"), "library"))
        for key, (label, source) in labels.items():
            path = settings.get(key)
            if isinstance(path, str) and path.strip():
                specs.append((path, label, "metadata", source))
        seen_paths: set[str] = set()
        for order, (raw_path, display_name, raw_mode, source) in enumerate(specs):
            path = str(raw_path or "").strip().strip('"').strip("'")
            if not path or not os.path.isabs(path):
                continue
            root_abs = os.path.realpath(os.path.abspath(path))
            if os.path.normcase(root_abs) in seen_paths:
                continue
            seen_paths.add(os.path.normcase(root_abs))
            root_id = hashlib.sha1(root_abs.encode("utf-8", "ignore")).hexdigest()
            name = display_name or os.path.basename(root_abs.rstrip("\\/")) or root_abs
            mode = str(raw_mode or "metadata").strip().lower() or "metadata"
            conn.execute(
                """INSERT OR IGNORE INTO library_roots(root_id,root_abs,mode,version,last_scan_started_at,last_scan_finished_at)
                   VALUES(?,?,?,?,?,?)""",
                (root_id, root_abs, mode, 0, None, None),
            )
            conn.execute(
                """INSERT OR IGNORE INTO user_library_roots(user_id,root_id,display_name,mode,source,sort_order,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (str(user_id), root_id, name, mode, source, order, now, now),
            )


def _v14(conn: sqlite3.Connection) -> None:
    """Discard incompatible seven-band visualizer rows after the DB backup.

    The audio source remains playable while index enrichment rebuilds this
    cache, so keeping obsolete blobs provides no migration value.
    """
    conn.execute(
        "DELETE FROM visualizer_analysis WHERE algorithm_version <> ? OR band_count <> ?",
        (3, 9),
    )


MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "structured_state", _v1),
    (2, "compact_palettes", _v2),
    (3, "unified_library_and_auth", _v3),
    (4, "large_value_envelopes", _v4),
    (5, "user_scoped_media_likes", _v5),
    (6, "device_scoped_push_notifications", _v6),
    (7, "retired_torrent_source_state", _v7),
    (8, "drop_legacy_torrent_source_state", _v8),
    (9, "server_side_auth_sessions", _v9),
    (10, "migration_backup_foundation", _v10),
    (11, "immutable_user_roles", _v11),
    (12, "canonical_user_owned_state", _v12),
    (13, "user_library_root_associations", _v13),
    (14, "nine_band_visualizer_analysis", _v14),
)


def migrate(conn: sqlite3.Connection) -> int:
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    pending = [(version, name, migration) for version, name, migration in MIGRATIONS if version > current]
    backup: dict[str, object] | None = None
    if current > 0 and pending:
        backup = create_backup(conn, reason=f"before migration {current} to {pending[-1][0]}", automatic=True)
    for version, name, migration in pending:
        with conn:
            migration(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (version, name, time.time()),
            )
            conn.execute(f"PRAGMA user_version={version}")
        current = version
    if backup is not None:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO database_backup_events(backup_path,automatic,reason,schema_version,bytes,created_at) VALUES(?,?,?,?,?,?)",
                (str(backup["path"]), 1, str(backup["reason"]), int(backup["schema_version"]), int(backup["bytes"]), float(backup["created_at"])),
            )
            conn.commit()
        except sqlite3.Error:
            # The backup itself remains verified even if an old database cannot yet record it.
            pass
    return current
