from __future__ import annotations

"""Small, cached TVMaze lookup used only to fill missing episode metadata."""

import asyncio
import html
import re
from typing import Any, Iterable

from ..Services.http import HttpClient
from .library_db import load_search_cache, save_search_cache
from .video_parse import normalize_show_key, show_keys_close


_API_URL = "https://api.tvmaze.com/singlesearch/shows"
_CACHE_SECONDS = 30 * 24 * 60 * 60
_TIMEOUT_SECONDS = 8
_HTTP: HttpClient | None = None
_APP_LOOP: asyncio.AbstractEventLoop | None = None


def configure_tvmaze_http(http: HttpClient) -> None:
    global _APP_LOOP, _HTTP
    _HTTP = http
    _APP_LOOP = asyncio.get_running_loop()


def _http() -> HttpClient:
    if _HTTP is None:
        raise RuntimeError("TVMaze HTTP transport is not initialized")
    return _HTTP


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


def _load_cached_payload(show_title: str) -> dict[str, Any]:
    title = str(show_title or "").strip()
    key = _cache_key(title)
    if not title or key.endswith(":"):
        return {}
    try:
        cached = load_search_cache(key)
        payload = cached.get("payload") if isinstance(cached, dict) else None
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


async def episodes_for_show(show_title: str) -> dict[tuple[int, int], dict[str, str]]:
    """Get a show's episode names/dates once, with a persistent cache."""
    title = str(show_title or "").strip()
    key = _cache_key(title)
    if not title or key.endswith(":"):
        return {}
    payload = _load_cached_payload(title)
    if payload:
        return _episode_map(payload)
    try:
        payload = await _http().json(
            "GET",
            _API_URL,
            params={"q": title, "embed": "episodes"},
            headers={"Accept": "application/json", "User-Agent": "Debripod/1.0"},
            timeout=_TIMEOUT_SECONDS,
        )
        if not isinstance(payload, dict):
            return {}
        if not show_keys_close(title, str(payload.get("name") or "")):
            return {}
        save_search_cache(key, "tvmaze", title, {"kind": "episode-metadata"}, payload, ttl_seconds=_CACHE_SECONDS)
        return _episode_map(payload)
    except (OSError, RuntimeError, ValueError):
        return {}


async def _cached_show_payload(show_title: str) -> dict[str, Any]:
    title = str(show_title or "").strip()
    key = _cache_key(title)
    if not title or key.endswith(":"):
        return {}
    payload = _load_cached_payload(title)
    if payload:
        return payload
    await episodes_for_show(title)
    return _load_cached_payload(title)


def _plain_summary(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


async def normalized_episode_information(show_title: str, season: int, episode: int) -> dict[str, Any]:
    """Return only available fields from the existing cached TVmaze show payload."""
    payload = await _cached_show_payload(show_title)
    if not payload:
        return {}
    embedded = payload.get("_embedded") if isinstance(payload.get("_embedded"), dict) else {}
    episodes = embedded.get("episodes") if isinstance(embedded.get("episodes"), list) else []
    selected: dict[str, Any] = {}
    for candidate in episodes:
        if not isinstance(candidate, dict):
            continue
        try:
            if int(candidate.get("season") or 0) == int(season) and int(candidate.get("number") or 0) == int(episode):
                selected = candidate
                break
        except (TypeError, ValueError):
            continue
    network_payload = payload.get("network") if isinstance(payload.get("network"), dict) else {}
    web_channel = payload.get("webChannel") if isinstance(payload.get("webChannel"), dict) else {}
    network = str(network_payload.get("name") or web_channel.get("name") or "").strip()
    result: dict[str, Any] = {
        "show_title": str(payload.get("name") or show_title or "").strip(),
        "episode_title": str(selected.get("name") or "").strip(),
        "number": f"S{int(season):02d}E{int(episode):02d}",
        "airdate": str(selected.get("airdate") or "").strip(),
        "runtime": selected.get("runtime") if selected.get("runtime") is not None else payload.get("runtime"),
        "show_status": str(payload.get("status") or "").strip(),
        "genres": [str(value).strip() for value in (payload.get("genres") or []) if str(value).strip()],
        "network": network,
        "premiered": str(payload.get("premiered") or "").strip(),
        "summary": _plain_summary(selected.get("summary") or payload.get("summary")),
    }
    return {key: value for key, value in result.items() if value not in ("", None, [])}


def _needs_lookup(parsed: dict[str, Any]) -> bool:
    if not parsed.get("show_title") or parsed.get("season") is None or parsed.get("episode") is None:
        return False
    title = normalize_show_key(parsed.get("episode_title"))
    show = normalize_show_key(parsed.get("show_title"))
    if not title or title == show:
        return True
    return title in {"reenc", "rerip", "proper", "episode"}


def _apply_episode_metadata(records: Iterable[dict], episodes_by_show: dict[str, dict[tuple[int, int], dict[str, str]]]) -> bool:
    changed = False
    for record in records:
        parsed = record.get("parse") if isinstance(record.get("parse"), dict) else None
        if not parsed or not _needs_lookup(parsed):
            continue
        show_title = str(parsed.get("show_title") or "")
        episodes = episodes_by_show.get(show_title) or {}
        try:
            lookup = episodes.get((int(parsed.get("season") or 0), int(parsed.get("episode") or 0)))
        except (TypeError, ValueError):
            lookup = None
        if not lookup:
            continue
        if lookup.get("title") and parsed.get("episode_title") != lookup["title"]:
            parsed["episode_title"] = lookup["title"]
            changed = True
        if lookup.get("airdate") and parsed.get("airdate") != lookup["airdate"]:
            parsed["airdate"] = lookup["airdate"]
            changed = True
    return changed


def enrich_cached_episode_metadata(records: Iterable[dict]) -> bool:
    """Apply only persistent TVMaze cache data; safe for library worker threads."""
    rows = list(records)
    shows = {
        str(record.get("parse", {}).get("show_title") or "")
        for record in rows
        if isinstance(record.get("parse"), dict) and _needs_lookup(record["parse"])
    }
    mappings = {title: _episode_map(_load_cached_payload(title)) for title in shows if title}
    return _apply_episode_metadata(rows, mappings)


async def enrich_missing_episode_metadata(records: Iterable[dict]) -> bool:
    """Mutate parsed records only where filenames do not supply an episode title."""
    rows = list(records)
    wanted: set[str] = set()
    for record in rows:
        parsed = record.get("parse") if isinstance(record.get("parse"), dict) else None
        if parsed and _needs_lookup(parsed):
            wanted.add(str(parsed.get("show_title") or ""))
    mappings: dict[str, dict[tuple[int, int], dict[str, str]]] = {}
    for show_title in sorted(wanted):
        if show_title:
            mappings[show_title] = await episodes_for_show(show_title)
    return _apply_episode_metadata(rows, mappings)


def schedule_episode_metadata_enrichment(records: Iterable[dict], on_changed=None) -> bool:
    """Schedule TVMaze lookups from a library worker without creating another HTTP session."""
    loop = _APP_LOOP
    rows = list(records)
    if loop is None or loop.is_closed() or not rows:
        return False

    async def _run() -> None:
        changed = await enrich_missing_episode_metadata(rows)
        if changed and callable(on_changed):
            await asyncio.to_thread(on_changed)

    def _start() -> None:
        loop.create_task(_run(), name="tvmaze-library-enrichment")

    loop.call_soon_threadsafe(_start)
    return True
