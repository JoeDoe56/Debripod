from __future__ import annotations

"""Small, cached TVMaze lookup used only to fill missing episode metadata."""

from typing import Any, Iterable

import requests

from .library_db import load_search_cache, save_search_cache
from .video_parse import normalize_show_key, show_keys_close


_API_URL = "https://api.tvmaze.com/singlesearch/shows"
_CACHE_SECONDS = 30 * 24 * 60 * 60
_TIMEOUT_SECONDS = 8


def _cache_key(show_title: str) -> str:
    return "tvmaze:episodes:v1:" + normalize_show_key(show_title)


def _episode_map(payload: dict[str, Any]) -> dict[tuple[int, int], dict[str, str]]:
    embedded = payload.get("_embedded") if isinstance(payload, dict) else {}
    episodes = embedded.get("episodes") if isinstance(embedded, dict) else []
    result: dict[tuple[int, int], dict[str, str]] = {}
    for episode in episodes if isinstance(episodes, list) else []:
        if not isinstance(episode, dict):
            continue
        try:
            season = int(episode.get("season") or 0)
            number = int(episode.get("number") or 0)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        title = str(episode.get("name") or "").strip()
        airdate = str(episode.get("airdate") or "").strip()
        if title or airdate:
            result[(season, number)] = {"title": title, "airdate": airdate}
    return result


def episodes_for_show(show_title: str) -> dict[tuple[int, int], dict[str, str]]:
    """Get a show's episode names/dates once, with a persistent cache."""
    title = str(show_title or "").strip()
    key = _cache_key(title)
    if not title or key.endswith(":"):
        return {}
    try:
        cached = load_search_cache(key)
        payload = cached.get("payload") if isinstance(cached, dict) else None
        if isinstance(payload, dict):
            return _episode_map(payload)
    except Exception:
        pass
    try:
        response = requests.get(
            _API_URL,
            params={"q": title, "embed": "episodes"},
            headers={"Accept": "application/json", "User-Agent": "Debripod/1.0"},
            timeout=_TIMEOUT_SECONDS,
        )
        if not response.ok:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        if not show_keys_close(title, str(payload.get("name") or "")):
            return {}
        save_search_cache(key, "tvmaze", title, {"kind": "episode-metadata"}, payload, ttl_seconds=_CACHE_SECONDS)
        return _episode_map(payload)
    except (requests.RequestException, ValueError):
        return {}


def _needs_lookup(parsed: dict[str, Any]) -> bool:
    if not parsed.get("show_title") or parsed.get("season") is None or parsed.get("episode") is None:
        return False
    title = normalize_show_key(parsed.get("episode_title"))
    show = normalize_show_key(parsed.get("show_title"))
    if not title or title == show:
        return True
    return title in {"reenc", "rerip", "proper", "episode"}


def enrich_missing_episode_metadata(records: Iterable[dict]) -> None:
    """Mutate parsed records only where filenames do not supply an episode title."""
    wanted: dict[str, list[dict]] = {}
    for record in records:
        parsed = record.get("parse") if isinstance(record.get("parse"), dict) else None
        if parsed and _needs_lookup(parsed):
            wanted.setdefault(str(parsed.get("show_title") or ""), []).append(record)
    for show_title, show_records in wanted.items():
        episodes = episodes_for_show(show_title)
        if not episodes:
            continue
        for record in show_records:
            parsed = record.get("parse") or {}
            try:
                lookup = episodes.get((int(parsed.get("season") or 0), int(parsed.get("episode") or 0)))
            except (TypeError, ValueError):
                lookup = None
            if not lookup:
                continue
            if lookup.get("title"):
                parsed["episode_title"] = lookup["title"]
            if lookup.get("airdate"):
                parsed["airdate"] = lookup["airdate"]
