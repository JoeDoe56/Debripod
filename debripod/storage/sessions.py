from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .database import database


def token_digest(raw_token: str) -> bytes:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).digest()


def load(raw_token: str, *, now: int | None = None) -> dict[str, Any] | None:
    if not raw_token:
        return None
    timestamp = int(time.time() if now is None else now)
    digest = token_digest(raw_token)
    with database() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_unix<=?", (timestamp,))
        row = conn.execute(
            "SELECT user_id,csrf_token,data_json,created_unix,last_seen_unix,expires_unix FROM auth_sessions WHERE token_hash=?",
            (digest,),
        ).fetchone()
    if row is None:
        return None
    try:
        values = json.loads(str(row["data_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        values = {}
    if not isinstance(values, dict):
        values = {}
    if row["user_id"]:
        values["username"] = str(row["user_id"])
    if row["csrf_token"]:
        values["csrf_token"] = str(row["csrf_token"])
    return {
        "values": values,
        "created_unix": int(row["created_unix"]),
        "last_seen_unix": int(row["last_seen_unix"]),
        "expires_unix": int(row["expires_unix"]),
    }


def save(
    raw_token: str,
    values: dict[str, Any],
    *,
    max_age: int,
    created_unix: int | None = None,
    now: int | None = None,
) -> None:
    timestamp = int(time.time() if now is None else now)
    created = int(created_unix or timestamp)
    expires = timestamp + int(max_age)
    clean = dict(values or {})
    username = str(clean.pop("username", "") or "")
    csrf_token = str(clean.pop("csrf_token", "") or "")
    payload = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
    with database() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE expires_unix<=?", (timestamp,))
        conn.execute(
            """INSERT INTO auth_sessions(token_hash,user_id,csrf_token,data_json,created_unix,last_seen_unix,expires_unix)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(token_hash) DO UPDATE SET
                 user_id=excluded.user_id,
                 csrf_token=excluded.csrf_token,
                 data_json=excluded.data_json,
                 last_seen_unix=excluded.last_seen_unix,
                 expires_unix=excluded.expires_unix""",
            (token_digest(raw_token), username, csrf_token, payload, created, timestamp, expires),
        )


def revoke(raw_token: str) -> None:
    if not raw_token:
        return
    with database() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_digest(raw_token),))


def revoke_user(user_id: str) -> None:
    with database() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (str(user_id or ""),))
