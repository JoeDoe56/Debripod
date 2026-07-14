from __future__ import annotations

import json
import time

from .database import database


def load_loved(user_id: str = "") -> tuple[dict[str, int], int]:
    with database(write=False) as conn:
        rows = conn.execute("SELECT track_key,loved,updated_at FROM lastfm_loved_tracks WHERE user_id=?", (str(user_id or ""),)).fetchall()
    return ({str(r["track_key"]): int(r["loved"]) for r in rows if r["loved"]}, int(max((r["updated_at"] for r in rows), default=0)))


def save_loved(tracks: dict[str, int], user_id: str = "") -> int:
    now = int(time.time())
    uid = str(user_id or "")
    with database() as conn:
        conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id=?", (uid,))
        conn.executemany("INSERT INTO lastfm_loved_tracks(user_id,track_key,loved,metadata_json,updated_at) VALUES(?,?,?,?,?)",
            [(uid, str(k), 1, "{}", now) for k, value in tracks.items() if value])
    return now
