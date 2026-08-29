from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from ..Services.search.relevance import (
    assess_match,
    extract_season_episode,
    normalize_search_text,
    tokens,
)


MUSIC_SIGNALS = {"song", "track", "album", "artist", "band", "discography", "flac", "mp3", "m4a", "lossless", "hires", "remaster", "lyrics"}
MOVIE_SIGNALS = {"movie", "film", "show", "series", "season", "episode", "1080p", "2160p", "720p", "4k", "bluray", "webrip", "webdl", "hdtv", "x264", "x265", "hevc", "hdr"}
VIDEO_PHRASES = {"how to", "tutorial", "review", "explained", "interview", "podcast", "trailer", "clip", "performance", "live performance", "news", "behind the scenes", "demo", "walkthrough", "guide"}


def tokenize_search_query(q: str) -> list[str]:
    return tokens(q, remove_format_noise=False)


def infer_query_intent(q: str, *, library_hits: list[dict] | None = None) -> dict[str, float]:
    normalized = normalize_search_text(q)
    token_set = set(normalized.split())
    music = min(1.0, 0.05 + 0.30 * len(token_set & MUSIC_SIGNALS))
    movie_show = min(1.0, 0.05 + 0.30 * len(token_set & MOVIE_SIGNALS))
    general_video = 0.05
    if "hi res" in normalized or "live at" in normalized:
        music = min(1.0, music + 0.35)
    if "blu ray" in normalized or "web dl" in normalized:
        movie_show = min(1.0, movie_show + 0.35)
    if any(phrase in normalized for phrase in VIDEO_PHRASES):
        general_video = min(1.0, general_video + 0.35)
    if extract_season_episode(q) != (None, None):
        movie_show = max(movie_show, 0.9)
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", normalized)]
    if any(1900 <= year <= datetime.now().year + 1 for year in years):
        movie_show = max(movie_show, 0.55)
    library = 0.0
    for hit in library_hits or []:
        title = normalize_search_text(hit.get("title") or hit.get("name") or "")
        artist_title = normalize_search_text(f"{hit.get('artist') or ''} {hit.get('title') or ''}")
        title_artist = normalize_search_text(f"{hit.get('title') or ''} {hit.get('artist') or ''}")
        if normalized and normalized in {title, artist_title, title_artist}:
            library = 1.0
            kind = str(hit.get("kind") or "")
            if kind in {"song", "album", "artist", "music_playlist"}:
                music = max(music, 0.75)
            if kind in {"movie", "show", "season", "episode", "video"}:
                movie_show = max(movie_show, 0.7)
        elif normalized and normalized in (title + " " + artist_title):
            library = max(library, 0.6)
    if max(music, movie_show, general_video) <= 0.05:
        general_video = 0.2
    return {"music": music, "movie_show": movie_show, "general_video": general_video, "library": library}


def _source_priority(source: str, intent: dict[str, float]) -> int:
    if source == "local_index":
        source = "torrent"
    music = float(intent.get("music") or 0)
    movie = float(intent.get("movie_show") or 0)
    video = float(intent.get("general_video") or 0)
    if music >= max(movie, video) and music >= 0.35:
        return {"library": 180, "soulseek": 150, "youtube": 105, "torrent": 35}.get(source, 0)
    if movie >= max(music, video) and movie >= 0.35:
        return {"library": 180, "torrent": 150, "youtube": 90, "soulseek": 25}.get(source, 0)
    if video >= max(music, movie) and video >= 0.3:
        return {"library": 180, "youtube": 150, "torrent": 60, "soulseek": 55}.get(source, 0)
    return {"library": 160, "youtube": 75, "soulseek": 65, "torrent": 60}.get(source, 0)


def source_priority_for_intent(intent: dict[str, float]) -> list[str]:
    sources = ["library", "local_index", "torrent", "soulseek", "youtube"]
    return sorted(sources, key=lambda source: (-_source_priority(source, intent), sources.index(source)))


def _kind_intent_score(kind: str, intent: dict[str, float]) -> float:
    if kind in {"song", "music_video", "album", "artist", "music_playlist"}:
        return 140 * float(intent.get("music") or 0)
    if kind in {"movie", "show", "season", "episode", "torrent"}:
        return 140 * float(intent.get("movie_show") or 0)
    if kind in {"video", "playlist", "channel", "podcast"}:
        return 140 * float(intent.get("general_video") or 0)
    return 0.0


def _quality_score(result: dict[str, Any]) -> float:
    source = str(result.get("source") or "").lower()
    provider = result.get("provider_data") if isinstance(result.get("provider_data"), dict) else {}
    score = 0.0
    if source in {"torrent", "local_index"}:
        seeders = max(0, int(provider.get("seeders") or 0))
        score += min(120.0, math.log2(seeders + 1) * 12.0)
        if provider.get("verified"):
            score += 35.0
    elif source == "soulseek":
        speed = max(0, int(provider.get("speed") or result.get("speed") or 0))
        score += min(120.0, math.log2(speed + 1) * 6.0)
    if source == "library":
        score += 100.0
    return score


def score_combined_result(result: dict, q: str, intent: dict[str, float]) -> dict[str, float]:
    # The pipeline has already applied the conservative relevance gate and
    # stored its confidence. Reusing it avoids repeating the comparatively
    # expensive fuzzy comparison for every retained row (important at 30k).
    existing_confidence = result.get("match_confidence")
    confidence = float(existing_confidence) if existing_confidence is not None else assess_match(q, result).confidence
    query = normalize_search_text(q, remove_format_noise=True)
    title = normalize_search_text(result.get("title") or "", remove_format_noise=True)
    artist = normalize_search_text(result.get("artist") or "", remove_format_noise=True)
    album = normalize_search_text(result.get("album") or "", remove_format_noise=True)
    exact_artist_title = bool(artist and title and query in {f"{artist} {title}", f"{title} {artist}"})
    exact_album_artist = bool(album and artist and query in {f"{album} {artist}", f"{artist} {album}"})
    query_structured = extract_season_episode(q)
    result_structured = extract_season_episode(" ".join(str(result.get(key) or "") for key in ("title", "subtitle", "search_blob")))
    exact_structured = query_structured != (None, None) and query_structured == result_structured
    textual = confidence * 10_000.0
    exact_bonus = (700.0 if exact_artist_title else 0.0) + (650.0 if exact_album_artist else 0.0) + (600.0 if exact_structured else 0.0)
    kind_score = _kind_intent_score(str(result.get("kind") or ""), intent)
    source_score = float(_source_priority(str(result.get("source") or ""), intent))
    quality = _quality_score(result)
    local = 1200.0 if result.get("source") == "library" and confidence >= 0.8 else 0.0
    total = textual + exact_bonus + kind_score + source_score + quality + local
    return {
        "match_score": textual,
        "intent_score": kind_score,
        "source_priority_score": source_score,
        "quality_score": quality,
        "local_priority_score": local,
        "tie_breaker_score": 0.0,
        "total_score": total,
        "match_confidence": confidence,
    }


def rank_combined_results(results: list[dict], q: str, *, intent: dict[str, float] | None = None) -> list[dict]:
    inferred = intent or infer_query_intent(q, library_hits=[item for item in results if item.get("source") == "library"])
    ranked: list[tuple[dict, dict[str, float]]] = []
    for raw in results:
        item = dict(raw)
        scores = score_combined_result(item, q, inferred)
        item["match_confidence"] = float(scores["match_confidence"])
        item["rank_score"] = float(scores["total_score"])
        ranked.append((item, scores))
    ranked.sort(key=lambda pair: (
        -pair[1]["total_score"],
        -pair[1]["match_score"],
        str(pair[0].get("result_id") or ""),
    ))
    return [item for item, _scores in ranked]
