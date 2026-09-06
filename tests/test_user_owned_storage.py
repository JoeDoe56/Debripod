from __future__ import annotations

import json
import sqlite3
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from debripod.Library.library_db import associated_library_roots, user_library_roots
from debripod.Library.roots import root_by_id, sync_user_roots
from debripod.Library.library_db import clear_search_history, load_search_history, record_search_history_row
from debripod.playback.state import load_playback_runtime, playback_update_from_client
from debripod.runtime_routes import USER_RUNTIME_KEY, _hls_access_allowed, _new_hls_access_token, stream
from debripod.settings import ensure_app_settings, save_app_settings
from debripod.storage import database, migrations, users
from debripod.storage.account_deletion import delete_user_owned_data
from debripod.storage.media_likes import list_media_likes, set_media_like
from debripod.storage.push_subscriptions import save_subscription, subscriptions_for_client


def test_v12_migrates_legacy_username_owned_rows_to_user_ids(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.sqlite3"
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(db_path))
    conn = sqlite3.connect(db_path)
    try:
        all_migrations = migrations.MIGRATIONS
        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations[:11])
        assert migrations.migrate(conn) == 11
        conn.execute("INSERT INTO users(user_id,username,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?)", ("user-alice", "alice", "hash", "owner", 1, 1))
        conn.execute("INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)", ("alice", "DOWNLOAD_DIR", json.dumps("D:/alice"), 1))
        conn.execute("INSERT INTO service_status(user_id,service,saved,keyring_ref,provider_identity,updated_at) VALUES(?,?,?,?,?,?)", ("alice", "SOULSEEK_PASSWORD", 1, "legacy", "", 1))
        conn.execute("INSERT INTO playback_state(user_id,state_json,updated_at) VALUES(?,?,?)", ("alice", json.dumps({"now": {"rel": "alice.mp3"}}), 1))
        conn.execute("INSERT INTO tasks(task_id,owner,source,state_json,created_at,updated_at) VALUES(?,?,?,?,?,?)", ("task-a", "alice", "youtube", "{}", 1, 1))
        conn.execute("INSERT INTO search_history(query,engine,cache_key,ts) VALUES(?,?,?,?)", ("alice search", "combined", "cache-a", 1))
        conn.execute("""INSERT INTO media_likes(username,media_key,media_type,source,metadata_json,liked,updated_at)
                        VALUES(?,?,?,?,?,?,?)""", ("alice", "music::a", "music", "library", "{}", 1, 1))
        conn.execute("""INSERT INTO push_subscriptions(username,client_id,endpoint,p256dh,auth,created_at,updated_at,revoked)
                        VALUES(?,?,?,?,?,?,?,?)""", ("alice", "phone", "https://push.example/a", "key", "auth", 1, 1, 0))
        conn.execute("""INSERT INTO notification_deliveries(task_id,username,client_id,event,delivered_at,status)
                        VALUES(?,?,?,?,?,?)""", ("task-a", "alice", "phone", "done", 1, "sent"))
        conn.execute("INSERT INTO lastfm_loved_tracks(user_id,track_key,loved,metadata_json,updated_at) VALUES(?,?,?,?,?)", ("alice", "artist\\ntrack\\n", 1, "{}", 1))
        conn.commit()
        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations)
        assert migrations.migrate(conn) == migrations.MIGRATIONS[-1][0]

        assert conn.execute("SELECT value_json FROM app_settings WHERE user_id='user-alice'").fetchone()[0] == json.dumps("D:/alice")
        assert conn.execute("SELECT user_id FROM playback_state WHERE user_id='user-alice'").fetchone()[0] == "user-alice"
        assert conn.execute("SELECT owner_user_id FROM tasks WHERE task_id='task-a'").fetchone()[0] == "user-alice"
        assert conn.execute("SELECT user_id FROM search_history WHERE query='alice search'").fetchone()[0] == "user-alice"
        assert conn.execute("SELECT user_id FROM media_likes WHERE media_key='music::a'").fetchone()[0] == "user-alice"
        assert conn.execute("SELECT user_id FROM push_subscriptions WHERE client_id='phone'").fetchone()[0] == "user-alice"
        assert conn.execute("SELECT user_id FROM notification_deliveries WHERE task_id='task-a'").fetchone()[0] == "user-alice"
        assert conn.execute("SELECT user_id FROM lastfm_loved_tracks WHERE track_key='artist\\ntrack\\n'").fetchone()[0] == "user-alice"
    finally:
        conn.close()


def test_user_owned_settings_playback_history_likes_and_push_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "isolated.sqlite3"))
    database.initialize_database()
    alice = users.create_user("alice", "hash", role="owner")
    bob = users.create_user("bob", "hash", role="user")
    save_app_settings({"DOWNLOAD_DIR": "D:/alice"}, user_id=alice["user_id"])
    save_app_settings({"DOWNLOAD_DIR": "D:/bob"}, user_id=bob["user_id"])
    assert ensure_app_settings(user_id=alice["user_id"])["DOWNLOAD_DIR"] == "D:/alice"
    assert ensure_app_settings(user_id=bob["user_id"])["DOWNLOAD_DIR"] == "D:/bob"

    alice_playback = load_playback_runtime(alice["user_id"])
    playback_update_from_client({"media": "audio", "root_id": "a", "rel": "alice.mp3", "event": "start", "playing": True}, alice_playback)
    assert load_playback_runtime(alice["user_id"]).state["now"]["rel"] == "alice.mp3"
    assert load_playback_runtime(bob["user_id"]).state["now"] is None

    record_search_history_row("alice only", "combined", "cache-a", user_id=alice["user_id"])
    record_search_history_row("bob only", "combined", "cache-b", user_id=bob["user_id"])
    assert [item["q"] for item in load_search_history(user_id=alice["user_id"])] == ["alice only"]
    clear_search_history(user_id=alice["user_id"])
    assert [item["q"] for item in load_search_history(user_id=bob["user_id"])] == ["bob only"]

    target = {"media_type": "music", "source": "library", "root_id": "r", "rel": "song.mp3", "title": "Song"}
    set_media_like(alice["user_id"], target, True)
    assert list_media_likes(alice["user_id"])
    assert not list_media_likes(bob["user_id"])
    subscription = {"endpoint": "https://push.example/1", "keys": {"p256dh": "key", "auth": "auth"}}
    save_subscription(alice["user_id"], "phone", subscription)
    assert subscriptions_for_client(alice["user_id"], "phone")
    assert not subscriptions_for_client(bob["user_id"], "phone")


def test_v13_migrates_each_users_existing_library_and_download_roots(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-roots.sqlite3"
    media = tmp_path / "media"
    downloads = tmp_path / "downloads"
    media.mkdir()
    downloads.mkdir()
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(db_path))
    conn = sqlite3.connect(db_path)
    try:
        all_migrations = migrations.MIGRATIONS
        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations[:12])
        assert migrations.migrate(conn) == 12
        conn.execute("INSERT INTO users(user_id,username,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?)", ("user-alice", "alice", "hash", "owner", 1, 1))
        conn.execute("INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)", ("user-alice", "LIBRARY_FOLDERS", json.dumps([{ "path": str(media) }]), 1))
        conn.execute("INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)", ("user-alice", "DOWNLOAD_DIR", json.dumps(str(downloads)), 1))
        conn.commit()

        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations)
        assert migrations.migrate(conn) == migrations.MIGRATIONS[-1][0]
        rows = conn.execute("SELECT display_name,source FROM user_library_roots WHERE user_id=? ORDER BY source", ("user-alice",)).fetchall()
        assert rows == [("Debrid", "debrid"), (media.name, "library")]
    finally:
        conn.close()


def test_v16_preserves_setup_for_existing_library_users(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-setup.sqlite3"
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(db_path))
    conn = sqlite3.connect(db_path)
    try:
        all_migrations = migrations.MIGRATIONS
        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations[:15])
        assert migrations.migrate(conn) == 15
        conn.execute(
            "INSERT INTO users(user_id,username,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("returning-id", "returning", "hash", "owner", 1, 1),
        )
        conn.execute(
            "INSERT INTO users(user_id,username,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("new-id", "new", "hash", "user", 1, 1),
        )
        conn.execute(
            "INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)",
            ("returning-id", "LIBRARY_FOLDERS", json.dumps([{"path": "D:/Music"}]), 1),
        )
        conn.execute(
            "INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)",
            ("returning-id", "SETUP_WIZARD_COMPLETE", "false", 1),
        )
        conn.execute(
            "INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)",
            ("new-id", "LIBRARY_FOLDERS", "[]", 1),
        )
        conn.execute(
            "INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)",
            ("new-id", "SETUP_WIZARD_COMPLETE", "false", 1),
        )
        conn.commit()

        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations)
        assert migrations.migrate(conn) == 16
        returning = conn.execute(
            "SELECT value_json FROM app_settings WHERE user_id=? AND key='SETUP_WIZARD_COMPLETE'",
            ("returning-id",),
        ).fetchone()
        new_user = conn.execute(
            "SELECT value_json FROM app_settings WHERE user_id=? AND key='SETUP_WIZARD_COMPLETE'",
            ("new-id",),
        ).fetchone()
        assert returning[0] == "true"
        assert new_user[0] == "false"
    finally:
        conn.close()


def test_account_deletion_removes_only_the_target_users_records(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "deletion.sqlite3"))
    database.initialize_database()
    alice = users.create_user("alice", "hash", role="owner")
    bob = users.create_user("bob", "hash", role="user")
    with database.database() as conn:
        for user in (alice, bob):
            owner = user["user_id"]
            conn.execute("INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)", (owner, "DOWNLOAD_DIR", '"D:/downloads"', 1))
            conn.execute("INSERT INTO service_status(user_id,service,saved,keyring_ref,provider_identity,updated_at) VALUES(?,?,?,?,?,?)", (owner, "SOULSEEK_PASSWORD", 1, "ref", "", 1))
            conn.execute("INSERT INTO playback_state(user_id,state_json,updated_at) VALUES(?,?,?)", (owner, "{}", 1))
            conn.execute("INSERT INTO tasks(task_id,owner,owner_user_id,source,state_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", ("task-" + owner, owner, owner, "youtube", "{}", 1, 1))
            conn.execute("INSERT INTO task_files(task_id,file_id,state_json,updated_at) VALUES(?,?,?,?)", ("task-" + owner, "file", "{}", 1))
            conn.execute("INSERT INTO search_history(user_id,query,engine,cache_key,ts) VALUES(?,?,?,?,?)", (owner, "query", "combined", "cache", 1))
            conn.execute("""INSERT INTO media_likes(username,user_id,media_key,media_type,source,metadata_json,liked,updated_at)
                            VALUES(?,?,?,?,?,?,?,?)""", (owner, owner, "music::" + owner, "music", "library", "{}", 1, 1))
            conn.execute("INSERT INTO lastfm_loved_tracks(user_id,track_key,loved,metadata_json,updated_at) VALUES(?,?,?,?,?)", (owner, "track", 1, "{}", 1))
            conn.execute("""INSERT INTO push_subscriptions(username,user_id,client_id,endpoint,p256dh,auth,created_at,updated_at,revoked)
                            VALUES(?,?,?,?,?,?,?,?,?)""", (owner, owner, "phone", "https://push.example/" + owner, "key", "auth", 1, 1, 0))
            conn.execute("""INSERT INTO notification_deliveries(task_id,username,user_id,client_id,event,delivered_at,status)
                            VALUES(?,?,?,?,?,?,?)""", ("task-" + owner, owner, owner, "phone", "done", 1, "sent"))
            conn.execute("""INSERT INTO user_passkeys(username,user_id,credential_id,public_key,sign_count,transports,aaguid,device_label,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?)""", (user["username"], owner, "credential-" + owner, "key", 0, "[]", "", "", 1))
            conn.execute("INSERT INTO passkey_challenges(id,username,user_id,action,challenge_json,created_at,expires_at) VALUES(?,?,?,?,?,?,?)", ("challenge-" + owner, user["username"], owner, "login", "{}", 1, 2))
            conn.execute("INSERT INTO auth_sessions(token_hash,user_id,csrf_token,data_json,created_unix,last_seen_unix,expires_unix) VALUES(?,?,?,?,?,?,?)", (owner.encode(), owner, "csrf", "{}", 1, 1, 2))
        # Shared indexed media must survive account deletion.
        conn.execute("""INSERT INTO media_files(media_id,root_id,root_abs,rel_path,abs_path,media_type,size,mtime_ns,indexed_at)
                        VALUES(?,?,?,?,?,?,?,?,?)""", ("shared", "root", "D:/media", "song.mp3", "D:/media/song.mp3", "audio", 1, 1, 1))

    delete_user_owned_data(alice["user_id"])
    with database.database(write=False) as conn:
        for table in ("app_settings", "service_status", "playback_state", "tasks", "search_history", "media_likes", "lastfm_loved_tracks", "push_subscriptions", "notification_deliveries", "user_passkeys", "passkey_challenges", "auth_sessions"):
            column = "owner_user_id" if table == "tasks" else "user_id"
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (alice["user_id"],)).fetchone()[0] == 0
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (bob["user_id"],)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM task_files WHERE task_id=?", ("task-" + alice["user_id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM media_files WHERE media_id='shared'").fetchone()[0] == 1


def test_library_roots_are_user_scoped_and_shared_physical_roots_are_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "roots.sqlite3"))
    database.initialize_database()
    alice = users.create_user("alice", "hash", role="owner")
    bob = users.create_user("bob", "hash", role="user")
    alice_only = tmp_path / "alice-only"
    bob_only = tmp_path / "bob-only"
    shared = tmp_path / "shared"
    for directory in (alice_only, bob_only, shared):
        directory.mkdir()

    sync_user_roots(alice["user_id"], {"LIBRARY_FOLDERS": [{"path": str(alice_only)}, {"path": str(shared)}]})
    sync_user_roots(bob["user_id"], {"LIBRARY_FOLDERS": [{"path": str(bob_only)}, {"path": str(shared)}]})

    alice_rows = user_library_roots(alice["user_id"])
    bob_rows = user_library_roots(bob["user_id"])
    alice_ids = {row["root_id"] for row in alice_rows}
    bob_ids = {row["root_id"] for row in bob_rows}
    shared_id = next(row["root_id"] for row in alice_rows if row["root_abs"] == str(shared.resolve()))
    bob_only_id = next(row["root_id"] for row in bob_rows if row["root_abs"] == str(bob_only.resolve()))

    assert shared_id in bob_ids
    assert alice_ids - {shared_id}
    assert bob_ids - {shared_id}
    assert root_by_id(bob_only_id, alice["user_id"]) is None
    assert root_by_id(bob_only_id, bob["user_id"])
    assert [row["root_id"] for row in associated_library_roots()].count(shared_id) == 1

    orphaned = sync_user_roots(alice["user_id"], {"LIBRARY_FOLDERS": []})
    assert shared_id not in orphaned
    assert not user_library_roots(alice["user_id"])
    assert root_by_id(shared_id, bob["user_id"])
    assert any(row["root_id"] == shared_id for row in associated_library_roots())


def test_full_cache_clear_preserves_user_root_discovery_and_index_save(tmp_path, monkeypatch):
    from debripod.Library.library_db import clear_library_cache, save_index_snapshot
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "reindex.sqlite3"))
    database.initialize_database()
    alice = users.create_user("alice", "hash", role="owner")
    bob = users.create_user("bob", "hash", role="user")
    folder = tmp_path / "media"
    folder.mkdir()
    sync_user_roots(alice["user_id"], {"LIBRARY_FOLDERS": [{"path": str(folder)}]})
    root = user_library_roots(alice["user_id"])[0]
    data = {"tracks": [{"rel": "song.flac", "title": "Song", "artist": "Artist", "album": "Album"}], "videos": [], "movies": [], "shows": []}
    before = save_index_snapshot(root["root_id"], str(folder), data, mode="metadata")
    clear_library_cache()
    assert root_by_id(root["root_id"], alice["user_id"])
    assert not root_by_id(root["root_id"], bob["user_id"])
    version = save_index_snapshot(root["root_id"], str(folder), data, mode="metadata")
    assert version > before
    assert user_library_roots(alice["user_id"])[0]["version"] == version


def test_stream_route_rejects_a_root_not_associated_with_the_user(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "hls-roots.sqlite3"))
    database.initialize_database()
    alice = users.create_user("alice", "hash", role="owner")
    bob = users.create_user("bob", "hash", role="user")
    bob_root = tmp_path / "bob-library"
    bob_root.mkdir()
    (bob_root / "private.mp3").write_bytes(b"not a real mp3")
    sync_user_roots(bob["user_id"], {"LIBRARY_FOLDERS": [{"path": str(bob_root)}]})
    bob_root_id = user_library_roots(bob["user_id"])[0]["root_id"]

    request = make_mocked_request("GET", f"/stream/{bob_root_id}/private.mp3", match_info={"root_id": bob_root_id, "relpath": "private.mp3"})
    request[USER_RUNTIME_KEY] = SimpleNamespace(user_id=alice["user_id"])
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(stream(request))


def test_hls_segment_token_requires_the_manifest_users_root_membership(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "hls-token-roots.sqlite3"))
    database.initialize_database()
    alice = users.create_user("alice", "hash", role="owner")
    bob = users.create_user("bob", "hash", role="user")
    bob_root = tmp_path / "bob-library"
    bob_root.mkdir()
    sync_user_roots(bob["user_id"], {"LIBRARY_FOLDERS": [{"path": str(bob_root)}]})
    bob_root_id = user_library_roots(bob["user_id"])[0]["root_id"]
    token = _new_hls_access_token(bob["user_id"], bob_root_id, "cache-key")

    assert _hls_access_allowed(token, bob["user_id"], "cache-key")
    assert not _hls_access_allowed(token, alice["user_id"], "cache-key")
    sync_user_roots(bob["user_id"], {"LIBRARY_FOLDERS": []})
    assert not _hls_access_allowed(token, bob["user_id"], "cache-key")


def test_mobile_library_folder_controls_are_capability_based_and_read_only():
    project_root = Path(__file__).resolve().parents[1]
    platform = (project_root / "debripod/static/js/platform.js").read_text(encoding="utf-8")
    settings_ui = (project_root / "debripod/static/js/settings-ui.js").read_text(encoding="utf-8")
    assert "canEditLibraryFolders" in platform
    assert "pointer: coarse" in platform
    assert "Library folders can be changed from a desktop browser." in settings_ui
    assert "disabled:!editable" in settings_ui
