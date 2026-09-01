from __future__ import annotations

import sqlite3

import pytest

from debripod.storage import backups, database, migrations


def test_migration_creates_verified_backup_before_advancing(tmp_path, monkeypatch):
    db_path = tmp_path / "debripod.sqlite3"
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("DEBRIPOD_BACKUP_DIRECTORY", str(backup_dir))
    conn = sqlite3.connect(db_path)
    try:
        all_migrations = migrations.MIGRATIONS
        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations[:9])
        assert migrations.migrate(conn) == 9
        monkeypatch.setattr(migrations, "MIGRATIONS", all_migrations)
        assert migrations.migrate(conn) == migrations.MIGRATIONS[-1][0]
    finally:
        conn.close()

    created = backups.list_backups(db_path)
    assert len(created) == 1
    assert created[0]["automatic"] is True
    assert created[0]["schema_version"] == 9
    assert created[0]["integrity"].lower() == "ok"


def test_backup_validation_restore_and_storage_report(tmp_path, monkeypatch):
    db_path = tmp_path / "debripod.sqlite3"
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(db_path))
    monkeypatch.setenv("DEBRIPOD_BACKUP_DIRECTORY", str(backup_dir))
    database.initialize_database()
    with database.database() as conn:
        conn.execute("INSERT INTO users(user_id,username,password_hash,created_at,updated_at) VALUES(?,?,?,?,?)", ("u1", "alice", "hash", 1, 1))
    backup = database.create_database_backup(reason="test")
    assert backups.validate_backup(backup["path"])["integrity"].lower() == "ok"

    with database.database() as conn:
        conn.execute("INSERT INTO users(user_id,username,password_hash,created_at,updated_at) VALUES(?,?,?,?,?)", ("u2", "bob", "hash", 1, 1))
    database.restore_database_backup(str(backup["path"]))
    with database.database(write=False) as conn:
        assert [row[0] for row in conn.execute("SELECT username FROM users ORDER BY username")] == ["alice"]
    report = database.database_storage_report()
    assert report["tables"]["users"]["row_count"] == 1

    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(ValueError):
        backups.validate_backup(corrupt)
