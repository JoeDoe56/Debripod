from __future__ import annotations

import json
import time
from typing import Any

from .database import database


def load(user_id: str = "") -> dict[str, Any]:
    with database(write=False) as conn:
        rows = conn.execute("SELECT key,value_json FROM app_settings WHERE user_id=?", (str(user_id or ""),)).fetchall()
    out: dict[str, Any] = {}
    for row in rows:
        try:
            out[str(row["key"])] = json.loads(row["value_json"])
        except (TypeError, json.JSONDecodeError):
            continue
    return out


def save(values: dict[str, Any], user_id: str = "") -> None:
    now = time.time()
    clean_user = str(user_id or "")
    with database() as conn:
        conn.execute("DELETE FROM app_settings WHERE user_id=?", (clean_user,))
        conn.executemany("INSERT INTO app_settings(user_id,key,value_json,updated_at) VALUES(?,?,?,?)",
            [(clean_user, str(k), json.dumps(v, separators=(",", ":"), ensure_ascii=False), now) for k, v in values.items()])


def fingerprint(user_id: str = "") -> tuple[int, int]:
    with database(write=False) as conn:
        row = conn.execute("SELECT COALESCE(MAX(updated_at),0),COUNT(*) FROM app_settings WHERE user_id=?", (str(user_id or ""),)).fetchone()
    return int(float(row[0]) * 1_000_000_000), int(row[1])
