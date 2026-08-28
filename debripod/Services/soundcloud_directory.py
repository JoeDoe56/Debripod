from __future__ import annotations

from typing import Any, Callable

from ..Library.search_cache import _SEARCH_DISK_LOCK, _disk_cache_get, _disk_cache_set
from .ytdlp_runner import run_flat_entries
from .ytdlp_search import normalize_soundcloud_entry


class SoundCloudDirectoryService:
    def __init__(self, runner: Callable[[str], list[dict[str, Any]]] = run_flat_entries):
        self.runner = runner

    @staticmethod
    def cache_key(artist_url: str, section: str) -> str:
        return f"soundcloud-artist:{artist_url.rstrip('/')}:{section}"

    def _load_url(self, artist_url: str, suffix: str) -> list[dict[str, Any]]:
        return self.runner(artist_url.rstrip("/") + "/" + suffix)

    @staticmethod
    def _stable_id(entry: dict[str, Any]) -> str:
        return str(entry.get("soundcloud_id") or entry.get("id") or entry.get("url") or entry.get("webpage_url") or "")

    def load_section(self, artist_url: str, section: str) -> list[dict[str, Any]]:
        section = str(section or "").strip().lower()
        if section not in {"tracks", "albums", "playlists"}:
            raise ValueError("section must be tracks, albums, or playlists")
        key = self.cache_key(artist_url, section)
        with _SEARCH_DISK_LOCK:
            cached = _disk_cache_get(key)
        if cached and isinstance(cached.get("payload"), dict):
            return list(cached["payload"].get("results") or [])
        if section == "tracks":
            entries = self._load_url(artist_url, "tracks")
            label, kind = "Songs", "song"
        elif section == "albums":
            entries = self._load_url(artist_url, "albums")
            label, kind = "Albums", "album"
        else:
            albums = self._load_url(artist_url, "albums")
            album_ids = {self._stable_id(entry) for entry in albums}
            entries = [entry for entry in self._load_url(artist_url, "sets") if self._stable_id(entry) not in album_ids]
            label, kind = "Music Playlists", "music_playlist"
        results = [item for entry in entries if (item := normalize_soundcloud_entry(entry, section, label, kind))]
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(key, "soundcloud-artist", artist_url, {"section": section}, {"results": results})
        return results


def load_soundcloud_artist_section(artist_url: str, section: str, *, runner: Callable[[str], list[dict[str, Any]]] = run_flat_entries) -> list[dict[str, Any]]:
    return SoundCloudDirectoryService(runner).load_section(artist_url, section)
