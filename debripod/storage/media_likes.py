from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .database import database

MEDIA_TYPES = {"music", "movie", "episode", "video", "youtube"}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _normalized_rel(value: Any) -> str:
    return re.sub(r"/+", "/", _text(value).replace("\\", "/")).lstrip("/")


def _normalized_url(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))
    except Exception:
        return raw


def build_media_key(target: dict[str, Any]) -> str:
    root_id = _text(target.get("root_id"))
    rel = _normalized_rel(target.get("rel"))
    source = _text(target.get("source")).lower() or "library"
    source_id = _text(target.get("source_id") or target.get("video_id") or target.get("result_id"))
    source_url = _normalized_url(target.get("source_url") or target.get("url"))
    if root_id and rel:
        return f"local:{root_id}:{rel}"
    if source_id:
        return f"{source}:{source_id}"
    if source_url:
        return f"{source}:{source_url}"
    artist = _text(target.get("artist")).casefold()
    title = _text(target.get("title") or target.get("label")).casefold()
    album = _text(target.get("album")).casefold()
    if artist or title or album:
        return "music:" + "\x1f".join((artist, title, album))
    raise ValueError("A stable media identity is required")


def _public(row: Any) -> dict[str, Any]:
    data = dict(row)
    try:
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    except Exception:
        data["metadata"] = {}
        data.pop("metadata_json", None)
    data["liked"] = bool(data.get("liked"))
    return data


def set_media_like(username: str, target: dict[str, Any], liked: bool) -> dict[str, Any]:
    user = _text(username)
    if not user:
        raise ValueError("A username is required")
    media_type = _text(target.get("media_type") or target.get("type")).lower()
    if media_type not in MEDIA_TYPES:
        raise ValueError("Unsupported media type")
    media_key = build_media_key(target)
    source = _text(target.get("source")).lower() or "library"
    metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
    for key in ("year", "show_key", "show_title", "season", "episode", "source_url", "art", "ext", "quality"):
        if target.get(key) not in (None, ""):
            metadata.setdefault(key, target.get(key))
    now = time.time()
    with database() as conn:
        conn.execute(
            """
            INSERT INTO media_likes(
              username,media_key,media_type,root_id,rel,source,source_id,title,artist,album,
              metadata_json,liked,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(username,media_key) DO UPDATE SET
              media_type=excluded.media_type,root_id=excluded.root_id,rel=excluded.rel,
              source=excluded.source,source_id=excluded.source_id,title=excluded.title,
              artist=excluded.artist,album=excluded.album,metadata_json=excluded.metadata_json,
              liked=excluded.liked,updated_at=excluded.updated_at
            """,
            (
                user,
                media_key,
                media_type,
                _text(target.get("root_id")),
                _normalized_rel(target.get("rel")),
                source,
                _text(target.get("source_id") or target.get("video_id") or target.get("result_id")),
                _text(target.get("title") or target.get("label")),
                _text(target.get("artist")),
                _text(target.get("album")),
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                int(bool(liked)),
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM media_likes WHERE username=? AND media_key=?",
            (user, media_key),
        ).fetchone()
    return _public(row)


def get_media_like(username: str, media_key: str) -> dict[str, Any] | None:
    with database(write=False) as conn:
        row = conn.execute(
            "SELECT * FROM media_likes WHERE username=? AND media_key=?",
            (_text(username), _text(media_key)),
        ).fetchone()
    return _public(row) if row else None


def list_media_likes(username: str, *, media_type: str = "", root_id: str = "") -> list[dict[str, Any]]:
    clauses = ["username=?", "liked=1"]
    values: list[Any] = [_text(username)]
    if media_type:
        clauses.append("media_type=?")
        values.append(_text(media_type).lower())
    if root_id:
        clauses.append("root_id=?")
        values.append(_text(root_id))
    sql = "SELECT * FROM media_likes WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC"
    with database(write=False) as conn:
        rows = conn.execute(sql, values).fetchall()
    return [_public(row) for row in rows]
