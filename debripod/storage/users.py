from __future__ import annotations

import time
from typing import Any

from .database import database


def list_users() -> list[dict[str, Any]]:
    with database(write=False) as conn:
        rows = conn.execute("SELECT user_id,username,password_hash,created_at,updated_at FROM users ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def replace_users(users: list[dict[str, Any]]) -> None:
    now = time.time()
    with database() as conn:
        conn.execute("DELETE FROM users")
        for item in users:
            username = str(item.get("username") or "").strip()
            if not username:
                continue
            conn.execute("INSERT INTO users(user_id,username,password_hash,created_at,updated_at) VALUES(?,?,?,?,?)",
                (str(item.get("id") or item.get("user_id") or username), username,
                 str(item.get("password_hash") or item.get("password") or ""), float(item.get("created_at") or now), now))
