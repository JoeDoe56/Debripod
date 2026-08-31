from __future__ import annotations

import time
import uuid
from typing import Any

from .database import database


def list_users() -> list[dict[str, Any]]:
    with database(write=False) as conn:
        rows = conn.execute("SELECT user_id,username,password_hash,role,created_at,updated_at FROM users ORDER BY created_at,user_id").fetchall()
    return [dict(r) for r in rows]


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with database(write=False) as conn:
        row = conn.execute("SELECT user_id,username,password_hash,role,created_at,updated_at FROM users WHERE user_id=?", (str(user_id or ""),)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with database(write=False) as conn:
        row = conn.execute("SELECT user_id,username,password_hash,role,created_at,updated_at FROM users WHERE lower(username)=lower(?)", (str(username or "").strip(),)).fetchone()
    return dict(row) if row else None


def create_user(username: str, password_hash: str, *, role: str = "user") -> dict[str, Any]:
    username = str(username or "").strip()
    if not username:
        raise ValueError("Username is required")
    clean_role = "owner" if role == "owner" else "user"
    now = time.time()
    item = {"user_id": str(uuid.uuid4()), "username": username, "password_hash": str(password_hash or ""), "role": clean_role, "created_at": now, "updated_at": now}
    with database() as conn:
        conn.execute("INSERT INTO users(user_id,username,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?)", tuple(item.values()))
    return item


def update_password_hash(user_id: str, password_hash: str) -> None:
    with database() as conn:
        conn.execute("UPDATE users SET password_hash=?,updated_at=? WHERE user_id=?", (str(password_hash or ""), time.time(), str(user_id or "")))


def update_username(user_id: str, username: str) -> None:
    with database() as conn:
        conn.execute("UPDATE users SET username=?,updated_at=? WHERE user_id=?", (str(username or "").strip(), time.time(), str(user_id or "")))


def set_role(user_id: str, role: str) -> None:
    if role not in {"owner", "user"}:
        raise ValueError("Invalid role")
    with database() as conn:
        conn.execute("UPDATE users SET role=?,updated_at=? WHERE user_id=?", (role, time.time(), str(user_id or "")))


def delete_user(user_id: str) -> None:
    with database() as conn:
        conn.execute("DELETE FROM users WHERE user_id=?", (str(user_id or ""),))


def transfer_ownership(owner_user_id: str, recipient_user_id: str) -> None:
    with database() as conn:
        owner = conn.execute("SELECT role FROM users WHERE user_id=?", (str(owner_user_id or ""),)).fetchone()
        recipient = conn.execute("SELECT user_id FROM users WHERE user_id=?", (str(recipient_user_id or ""),)).fetchone()
        if not owner or str(owner[0]) != "owner" or not recipient or str(owner_user_id) == str(recipient_user_id):
            raise ValueError("Invalid ownership transfer")
        conn.execute("UPDATE users SET role='user',updated_at=? WHERE user_id=?", (time.time(), str(owner_user_id)))
        conn.execute("UPDATE users SET role='owner',updated_at=? WHERE user_id=?", (time.time(), str(recipient_user_id)))


def bootstrap_legacy_users(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = list_users()
    if existing:
        return existing
    now = time.time()
    prepared: list[dict[str, Any]] = []
    for index, item in enumerate(users or []):
        username = str(item.get("username") or "").strip()
        password_hash = str(item.get("password_hash") or "").strip()
        if not username or not password_hash:
            continue
        prepared.append({"user_id": str(item.get("id") or item.get("user_id") or uuid.uuid4()), "username": username, "password_hash": password_hash, "role": "owner" if not prepared else "user", "created_at": float(item.get("created_at") or now + index / 1000), "updated_at": now})
    if prepared:
        replace_users(prepared)
    return list_users()


def replace_users(users: list[dict[str, Any]]) -> None:
    now = time.time()
    with database() as conn:
        conn.execute("DELETE FROM users")
        for index, item in enumerate(users):
            username = str(item.get("username") or "").strip()
            if not username:
                continue
            conn.execute("INSERT INTO users(user_id,username,password_hash,role,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (str(item.get("id") or item.get("user_id") or username), username,
                 str(item.get("password_hash") or item.get("password") or ""), str(item.get("role") or ("owner" if index == 0 else "user")), float(item.get("created_at") or now), now))
