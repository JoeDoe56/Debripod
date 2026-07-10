from __future__ import annotations

import math
import os
import re
import unicodedata
from datetime import datetime
from typing import Any


WEAK_MATCH_TOKENS = {
    "official", "video", "audio", "lyrics", "lyric", "visualizer", "remaster", "remastered",
    "deluxe", "explicit", "clean", "full", "album", "movie", "film", "episode", "season",
    "1080p", "2160p", "720p", "480p", "4k", "hdr", "bluray", "webrip", "webdl", "hdtv",
    "x264", "x265", "hevc", "aac", "mp3", "flac", "m4a", "opus",
}
MUSIC_SIGNALS = {"song", "track", "album", "artist", "band", "discography", "flac", "mp3", "m4a", "lossless", "hires", "remaster", "lyrics"}
MOVIE_SIGNALS = {"movie", "film", "show", "series", "season", "episode", "1080p", "2160p", "720p", "4k", "bluray", "webrip", "webdl", "hdtv", "x264", "x265", "hevc", "hdr"}
VIDEO_PHRASES = {"how to", "tutorial", "review", "explained", "interview", "podcast", "trailer", "clip", "performance", "live performance", "news", "behind the scenes", "demo", "walkthrough", "guide"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def normalize_search_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("'", "").replace("`", "")
    text = re.sub(r"[_\.\[\]{}()\\/,:;!?+\-=@#$%^&*|<>~]+", " ", text)
    words = [ROMAN.get(word, word) for word in re.findall(r"[a-z0-9]+", text)]
    return " ".join(words)


def tokenize_search_query(q: str) -> list[str]:
    return [token for token in normalize_search_text(q).split() if token]


def _match_text(value: object) -> str:
    tokens = normalize_search_text(value).split()
    return " ".join(token for token in tokens if token not in WEAK_MATCH_TOKENS)


def infer_query_intent(q: str, *, library_hits: list[dict] | None = None) -> dict[str, float]:
    normalized = normalize_search_text(q)
    tokens = set(normalized.split())
    music = min(1.0, 0.05 + 0.30 * len(tokens & MUSIC_SIGNALS))
    movie_show = min(1.0, 0.05 + 0.30 * len(tokens & MOVIE_SIGNALS))
    general_video = 0.05
    if "hi res" in normalized or "live at" in normalized:
        music = min(1.0, music + 0.35)
    if "blu ray" in normalized or "web dl" in normalized:
        movie_show = min(1.0, movie_show + 0.35)
    for phrase in VIDEO_PHRASES:
        if phrase in normalized:
            general_video = min(1.0, general_video + 0.35)
    if re.search(r"\bs\d{1,2}(?:e\d{1,4})?\b|\be\d{1,4}\b", normalized):
        movie_show = max(movie_show, 0.9)
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", normalized)]
    if any(1900 <= year <= datetime.now().year + 1 for year in years):
        movie_show = max(movie_show, 0.55)
    library = 0.0
    for hit in library_hits or []:
        if not isinstance(hit, dict):
            continue
        title = normalize_search_text(hit.get("title") or hit.get("name") or "")
        artist_title = normalize_search_text(f"{hit.get('artist') or ''} {hit.get('title') or ''}")
        if normalized and normalized in {title, artist_title}:
            library = 1.0
            if str(hit.get("media") or "") == "audio":
                music = max(music, 0.75)
            if str(hit.get("media") or "") == "video":
                movie_show = max(movie_show, 0.7)
        elif normalized and normalized in (title + " " + artist_title):
            library = max(library, 0.6)
    if max(music, movie_show, general_video) <= 0.05:
        general_video = 0.2
    return {
        "music": max(0.0, min(1.0, music)),
        "movie_show": max(0.0, min(1.0, movie_show)),
        "general_video": max(0.0, min(1.0, general_video)),
        "library": max(0.0, min(1.0, library)),
    }


def _source_priority(source: str, intent: dict[str, float]) -> int:
    music = float(intent.get("music") or 0)
    movie = float(intent.get("movie_show") or 0)
    video = float(intent.get("general_video") or 0)
    if music >= max(movie, video) and music >= 0.35:
        return {"library": 180, "soulseek": 150, "youtube": 95, "knaben": 30}.get(source, 0)
    if movie >= max(music, video) and movie >= 0.35:
        return {"library": 180, "knaben": 150, "youtube": 90, "soulseek": 25}.get(source, 0)
    if video >= max(music, movie) and video >= 0.3:
        return {"library": 180, "youtube": 150, "soulseek": 55, "knaben": 55}.get(source, 0)
    return {"library": 160, "youtube": 70, "soulseek": 65, "knaben": 60}.get(source, 0)


def source_priority_for_intent(intent: dict[str, float]) -> list[str]:
    sources = ["library", "soulseek", "knaben", "youtube"]
    return sorted(sources, key=lambda source: (-_source_priority(source, intent), sources.index(source)))


def score_combined_result(result: dict, q: str, intent: dict[str, float]) -> dict:
    query = normalize_search_text(q)
    query_tokens = tokenize_search_query(q)
    title_raw = result.get("title") or result.get("directory_title") or result.get("name") or ""
    title = normalize_search_text(title_raw)
    title_match = _match_text(title_raw) or title
    filename = normalize_search_text(os.path.splitext(str(result.get("name") or ""))[0])
    artist = normalize_search_text(result.get("artist") or result.get("user") or "")
    album = normalize_search_text(result.get("album") or "")
    artist_title = normalize_search_text(f"{artist} {title}")
    album_artist = normalize_search_text(f"{album} {artist}")
    candidates = [value for value in {title, title_match, filename, artist_title, album_artist, normalize_search_text(result.get("directory") or "")} if value]
    match_score = 0.0
    if query and artist and title and query == artist_title:
        match_score = 1100
    elif query and album and artist and query == album_artist:
        match_score = 1050
    elif query and query in {title, title_match, filename}:
        match_score = 1000
    elif query and any(query in candidate for candidate in candidates):
        match_score = 800
    else:
        token_set = set(query_tokens)
        candidate_tokens = set(" ".join(candidates).split())
        present = len(token_set & candidate_tokens)
        coverage = present / max(1, len(token_set))
        if token_set and coverage >= 1.0:
            match_score = 650 + min(100, len(token_set) * 10)
        elif present:
            match_score = 350 + 250 * coverage
            if present == 1 and len(token_set) > 1:
                match_score = min(250, match_score)
            elif len(token_set) == 1:
                match_score = min(500, match_score)
    source = str(result.get("source") or "").lower()
    media = str(result.get("media") or "").lower()
    intent_score = 0
    if media == "audio":
        intent_score = int(120 * float(intent.get("music") or 0))
    elif media == "video" or source in {"youtube", "knaben"}:
        intent_score = int(120 * max(float(intent.get("movie_show") or 0), float(intent.get("general_video") or 0)))
    source_priority_score = min(180, _source_priority(source, intent))
    quality_score = 0
    if source == "knaben":
        quality_score = min(120, int(math.log2(max(1, int(result.get("seeders") or 0) + 1)) * 12))
    elif source == "soulseek":
        quality_score = min(120, int(math.log2(max(1, int(result.get("speed") or 0) + 1)) * 6))
    elif result.get("quality"):
        quality_score = 30
    # A local result is immediately usable.  Once it is a close textual match,
    # keep it ahead of remote alternatives; a substantially better remote match
    # can still win rather than making library results blanket-first.
    local_priority_score = 2000 if source == "library" and match_score >= 650 else 0
    tie_breaker_score = min(20, int(math.log2(max(1, int(result.get("size") or 0) + 1))))
    total_score = match_score * 10 + intent_score + source_priority_score + quality_score + local_priority_score + tie_breaker_score
    return {
        "match_score": match_score,
        "intent_score": intent_score,
        "source_priority_score": source_priority_score,
        "quality_score": quality_score,
        "local_priority_score": local_priority_score,
        "tie_breaker_score": tie_breaker_score,
        "total_score": total_score,
    }


def rank_combined_results(results: list[dict], q: str, *, intent: dict[str, float] | None = None) -> list[dict]:
    inferred = intent or infer_query_intent(q, library_hits=[item for item in results if item.get("source") == "library"])
    ranked: list[tuple[dict, dict]] = []
    for raw in results:
        item = dict(raw)
        scores = score_combined_result(item, q, inferred)
        ranked.append((item, scores))
    ranked.sort(key=lambda pair: (
        -float(pair[1]["total_score"]),
        -float(pair[1]["match_score"]),
        str(pair[0].get("title") or pair[0].get("name") or "").lower(),
        str(pair[0].get("result_id") or ""),
    ))
    return [item for item, _scores in ranked]
