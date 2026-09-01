from __future__ import annotations

import json
import sqlite3

from debripod.Library.library_db import clear_search_history, load_search_history, record_search_history_row
from debripod.playback.state import load_playback_runtime, playback_update_from_client
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
        assert migrations.migrate(conn) == 12

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
