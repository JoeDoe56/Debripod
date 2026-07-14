from __future__ import annotations

import json
import time
from typing import Any

from .database import database


def load(user_id: str = "") -> dict[str, Any]:
    with database(write=False) as conn:
        row = conn.execute("SELECT state_json FROM playback_state WHERE user_id=?", (str(user_id or ""),)).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row[0])
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def save(state: dict[str, Any], user_id: str = "") -> None:
    payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    with database() as conn:
        conn.execute("""INSERT INTO playback_state(user_id,state_json,updated_at) VALUES(?,?,?)
          ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at""",
          (str(user_id or ""), payload, time.time()))
