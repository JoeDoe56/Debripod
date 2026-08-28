from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse

from .search.dedup import deduplicate_youtube
from .search.identity import youtube_result_id
from .search.identity import soundcloud_result_id
from .search.models import ProviderSearchResponse
from .ytdlp_runner import run_flat_entries


YOUTUBE_MUSIC_SEARCHES = [
    ("songs", "Songs"),
    ("videos", "Music Videos"),
    ("albums", "Albums"),
    ("artists", "Artists"),
    ("playlists", "Music Playlists"),
    ("podcasts", "Podcasts"),
    ("episodes", "Episodes"),
]
YOUTUBE_SEARCHES = [
    ("videos", "Videos", "EgIQAQ%3D%3D"),
    ("playlists", "Playlists", "EgIQAw%3D%3D"),
    ("channels", "Channels", "EgIQAg%3D%3D"),
]
_MUSIC_PARAMS = {
    key: "EgWKAQ" + value + "AWoMEA4QChADEAQQCRAF"
    for key, value in {"songs": "II", "videos": "IQ", "albums": "IY", "artists": "Ig", "podcasts": "JQ", "episodes": "JI"}.items()
}
_MUSIC_PARAMS["playlists"] = "Eg-KAQwIABAAGAAgACgBMABqChAEEAMQCRAFEAo%3D"
_KIND = {
    "songs": "song", "videos_music": "music_video", "albums": "album", "artists": "artist",
    "playlists_music": "music_playlist", "podcasts": "podcast", "episodes": "episode",
    "videos": "video", "playlists": "playlist", "channels": "channel",
}
SOUNDCLOUD_SEARCHES = [
    ("tracks", "Songs", "sctracksearch:", "song"),
    ("artists", "Artists", "scartistsearch:", "artist"),
    ("albums", "Albums", "scalbumsearch:", "album"),
    ("playlists", "Music Playlists", "scplaylistsearch:", "music_playlist"),
]


def youtube_music_search_url(query: str, category: str) -> str:
    return f"https://music.youtube.com/search?q={quote(str(query or ''))}&sp={_MUSIC_PARAMS[category]}"


def youtube_search_url(query: str, category: str) -> str:
    params = next(value for key, _label, value in YOUTUBE_SEARCHES if key == category)
    return f"https://www.youtube.com/results?search_query={quote(str(query or ''))}&sp={params}"


def _url_ids(value: Any) -> tuple[str, str, str, str]:
    raw = str(value or "")
    parsed = urlparse(raw if "://" in raw else "https://www.youtube.com/" + raw.lstrip("/"))
    query = parse_qs(parsed.query)
    parts = [part for part in parsed.path.split("/") if part]
    video = str((query.get("v") or [""])[0])
    playlist = str((query.get("list") or [""])[0])
    channel = parts[1] if len(parts) > 1 and parts[0] in {"channel", "c", "user"} else ""
    browse = parts[-1] if parts and parts[0] == "browse" else ""
    if parsed.hostname == "youtu.be" and parts:
        video = parts[0]
    return video, playlist, channel, browse


def _thumbnail(entry: dict[str, Any]) -> str:
    direct = str(entry.get("thumbnail") or "")
    if direct:
        return direct
    thumbs = entry.get("thumbnails")
    if isinstance(thumbs, list):
        for item in reversed(thumbs):
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    return ""


def normalize_youtube_entry(entry: dict[str, Any], category: str, label: str, *, youtube_music: bool) -> dict[str, Any] | None:
    category_key = category + "_music" if youtube_music and category in {"videos", "playlists"} else category
    kind = _KIND[category_key]
    title = str(entry.get("title") or entry.get("fulltitle") or entry.get("channel") or entry.get("uploader") or "").strip()
    if not title:
        return None
    urls = [entry.get("webpage_url"), entry.get("original_url"), entry.get("url")]
    video = str(entry.get("video_id") or "").strip()
    playlist = str(entry.get("playlist_id") or "").strip()
    channel = str(entry.get("channel_id") or entry.get("uploader_id") or "").strip()
    browse = str(entry.get("browse_id") or "").strip()
    for raw_url in urls:
        url_video, url_playlist, url_channel, url_browse = _url_ids(raw_url)
        video = video or url_video
        playlist = playlist or url_playlist
        channel = channel or url_channel
        browse = browse or url_browse
    entry_id = str(entry.get("id") or "").strip()
    if kind in {"song", "music_video", "episode", "video"}:
        video = video or entry_id
    elif kind in {"album", "music_playlist", "podcast", "playlist"}:
        playlist = playlist or (entry_id[2:] if entry_id.startswith("VL") else entry_id)
    else:
        channel = channel or entry_id
    canonical = str(entry.get("webpage_url") or entry.get("original_url") or "").strip()
    if not canonical:
        if video:
            canonical = "https://www.youtube.com/watch?v=" + video
        elif playlist:
            canonical = "https://www.youtube.com/playlist?list=" + playlist
        elif channel:
            canonical = "https://www.youtube.com/channel/" + channel
    result_id = youtube_result_id(kind, video_id=video, playlist_id=playlist, channel_id=channel, browse_id=browse, canonical_url=canonical)
    if not result_id.rsplit(":", 1)[-1]:
        return None
    artist = str(entry.get("artist") or entry.get("channel") or entry.get("uploader") or "").strip()
    album = str(entry.get("album") or "").strip()
    subtitle = str(entry.get("description") or artist or album).strip()
    return {
        "result_id": result_id, "provider_group": "ytdlp", "source": "youtube", "source_label": "YouTube",
        "kind": kind, "kind_label": label, "title": title, "subtitle": subtitle, "artist": artist, "album": album,
        "year": str(entry.get("release_year") or entry.get("upload_date") or "")[:4],
        "duration": float(entry.get("duration") or 0), "thumbnail": _thumbnail(entry), "canonical_url": canonical,
        "stable_source_id": result_id, "search_blob": "", "filter_values": {"sources": [], "types": [], "indexers": [], "media": []},
        "match_confidence": 0.0, "rank_score": 0.0, "browse_available": kind in {"album", "artist", "music_playlist", "podcast", "playlist", "channel"},
        "stream_available": kind in {"song", "music_video", "episode", "video"}, "download_available": True,
        "files_loaded": False, "file_count": int(entry.get("playlist_count") or 0), "size": 0, "files": [],
        "provider_data": {"video_id": video, "playlist_id": playlist, "channel_id": channel, "browse_id": browse, "youtube_music": youtube_music, "search_category": category},
    }


def normalize_soundcloud_entry(entry: dict[str, Any], category: str, label: str, kind: str) -> dict[str, Any] | None:
    title = str(entry.get("title") or entry.get("username") or entry.get("uploader") or "").strip()
    permalink = str(entry.get("permalink_url") or entry.get("webpage_url") or entry.get("url") or "").strip()
    numeric_id = str(entry.get("soundcloud_id") or entry.get("id") or "").strip()
    if not title or not permalink:
        return None
    result_id = soundcloud_result_id(kind, numeric_id, permalink)
    uploader = str(entry.get("artist") or entry.get("uploader") or entry.get("channel") or "").strip()
    return {
        "result_id": result_id, "provider_group": "ytdlp", "source": "soundcloud", "source_label": "SoundCloud",
        "kind": kind, "kind_label": label, "title": title, "subtitle": uploader, "artist": uploader,
        "album": str(entry.get("album") or ""), "year": str(entry.get("release_year") or ""),
        "duration": float(entry.get("duration") or 0), "thumbnail": _thumbnail(entry), "canonical_url": permalink,
        "stable_source_id": result_id, "search_blob": "", "filter_values": {"sources": [], "types": [], "indexers": [], "media": []},
        "match_confidence": 0.0, "rank_score": 0.0, "browse_available": kind in {"artist", "album", "music_playlist"},
        "stream_available": kind == "song", "download_available": True, "files_loaded": False,
        "file_count": int(entry.get("track_count") or entry.get("playlist_count") or 0), "size": 0, "files": [],
        "provider_data": {"soundcloud_id": numeric_id, "permalink_url": permalink, "set_type": str(entry.get("set_type") or ""), "track_count": int(entry.get("track_count") or 0)},
    }


class YtdlpSearchProvider:
    provider_group = "ytdlp"

    def __init__(self, runner: Callable[[str], list[dict[str, Any]]] = run_flat_entries, *, max_concurrent: int = 4):
        self.runner = runner
        self.max_concurrent = max(1, int(max_concurrent))

    def _search_youtube(self, query: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        jobs: list[tuple[str, str, str, bool]] = []
        jobs.extend((category, label, youtube_music_search_url(query, category), True) for category, label in YOUTUBE_MUSIC_SEARCHES)
        jobs.extend((category, label, youtube_search_url(query, category), False) for category, label, _params in YOUTUBE_SEARCHES)
        rows: list[dict[str, Any]] = []
        status: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_concurrent, thread_name_prefix="ytdlp-search") as executor:
            futures = {executor.submit(self.runner, url): (category, label, url, is_music) for category, label, url, is_music in jobs}
            for future in as_completed(futures):
                category, label, _url, is_music = futures[future]
                try:
                    entries = future.result()
                    parsed = [item for entry in entries if (item := normalize_youtube_entry(entry, category, label, youtube_music=is_music))]
                    rows.extend(parsed)
                    status.append({"source": "youtube", "category": category, "youtube_music": is_music, "status": "ok", "result_count": len(parsed)})
                except Exception as exc:
                    status.append({"source": "youtube", "category": category, "youtube_music": is_music, "status": "error", "error": str(exc), "result_count": 0})
        return deduplicate_youtube(rows), status

    def search(self, query: str, context: Any) -> ProviderSearchResponse:
        started = time.monotonic()
        rows, status = self._search_youtube(query)
        # SoundCloud uses separate extractor prefixes and is intentionally
        # appended only after YouTube's internal duplicate merge.
        with ThreadPoolExecutor(max_workers=self.max_concurrent, thread_name_prefix="soundcloud-search") as executor:
            futures = {
                executor.submit(self.runner, prefix + query): (category, label, kind)
                for category, label, prefix, kind in SOUNDCLOUD_SEARCHES
            }
            for future in as_completed(futures):
                category, label, kind = futures[future]
                try:
                    parsed = [item for entry in future.result() if (item := normalize_soundcloud_entry(entry, category, label, kind))]
                    rows.extend(parsed)
                    status.append({"source": "soundcloud", "category": category, "status": "ok", "result_count": len(parsed)})
                except Exception as exc:
                    status.append({"source": "soundcloud", "category": category, "status": "error", "error": str(exc), "result_count": 0})
        return ProviderSearchResponse("ytdlp", status, rows, duration_ms=int((time.monotonic() - started) * 1000))
