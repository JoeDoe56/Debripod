from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from typing import Any, Callable

from .search.identity import library_result_id
from .search.models import ProviderSearchResponse
from .search.relevance import assess_match, normalize_text


_LABELS = {
    "song": "Songs", "album": "Albums", "artist": "Artists", "music_playlist": "Music Playlists",
    "movie": "Movies", "show": "Shows", "season": "Seasons", "episode": "Episodes",
    "video": "Videos", "directory": "Folders",
}


class LibrarySearchProvider:
    provider_group = "library"

    def __init__(self, roots_provider: Callable[[], list[dict[str, Any]]], index_provider: Callable[[str], dict[str, Any] | None], versions_provider: Callable[[], Any]):
        self.roots_provider = roots_provider
        self.index_provider = index_provider
        self.versions_provider = versions_provider
        self._cache_key: str = ""
        self._entities: list[dict[str, Any]] = []

    @staticmethod
    def _file(record: dict[str, Any], root_id: str, media: str) -> dict[str, Any]:
        rel = str(record.get("rel") or record.get("rel_path") or "")
        return {"file_id": f"{root_id}:{rel}", "name": str(record.get("name") or os.path.basename(rel)), "title": str(record.get("title") or record.get("name") or os.path.basename(rel)), "path": rel, "size": int(record.get("size") or 0), "duration": float(record.get("duration") or 0), "media": media, "stream_available": True, "download_available": False, "provider_data": {"root_id": root_id, "rel": rel}}

    @staticmethod
    def _result(root_id: str, kind: str, title: str, *, entity_key: str, rel: str = "", subtitle: str = "", artist: str = "", album: str = "", year: Any = "", duration: Any = 0, size: Any = 0, files: list[dict[str, Any]] | None = None, navigation: dict[str, Any] | None = None) -> dict[str, Any]:
        result_id = library_result_id(root_id, kind, entity_key, rel)
        playable = kind in {"song", "movie", "episode", "video"}
        browsable = kind in {"artist", "album", "music_playlist", "show", "season", "directory"}
        file_rows = list(files or [])
        return {
            "result_id": result_id, "provider_group": "library", "source": "library", "source_label": "Library",
            "kind": kind, "kind_label": _LABELS[kind], "title": str(title), "subtitle": str(subtitle), "artist": str(artist), "album": str(album),
            "year": str(year or ""), "duration": float(duration or 0), "thumbnail": "", "canonical_url": "", "stable_source_id": entity_key,
            "search_blob": "", "filter_values": {"sources": [], "types": [], "indexers": [], "media": []}, "match_confidence": 0.0, "rank_score": 0.0,
            "browse_available": browsable, "stream_available": playable, "download_available": False, "files_loaded": bool(file_rows),
            "file_count": len(file_rows), "size": int(size or 0), "files": file_rows,
            "provider_data": {"root_id": root_id, "rel": rel, "entity_key": entity_key, "navigation": dict(navigation or {})},
        }

    def _build(self) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        for root in self.roots_provider() or []:
            root_id = str(root.get("id") or root.get("root_id") or "")
            snapshot = self.index_provider(root_id) or {}
            artists: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
            albums: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            folders: set[str] = set()
            for track in snapshot.get("tracks") or []:
                artist = str(track.get("artist") or track.get("album_artist") or "Unknown Artist")
                album = str(track.get("album") or "")
                rel = str(track.get("rel") or track.get("rel_path") or "")
                file_row = self._file(track, root_id, "audio")
                artists[artist].append(file_row)
                if album:
                    albums[(artist, album)].append(file_row)
                title = str(track.get("title") or track.get("name") or os.path.basename(rel))
                entities.append(self._result(root_id, "song", title, entity_key=rel or f"{artist}|{album}|{title}", rel=rel, subtitle=artist, artist=artist, album=album, duration=track.get("duration"), size=track.get("size"), files=[file_row]))
                parent = os.path.dirname(rel).replace("\\", "/")
                while parent:
                    folders.add(parent); parent = os.path.dirname(parent).replace("\\", "/")
            for artist, files in artists.items():
                entities.append(self._result(root_id, "artist", artist, entity_key=artist, subtitle=f"{len(files)} songs", artist=artist, navigation={"view": "artist", "root_id": root_id, "artist": artist}))
            for (artist, album), files in albums.items():
                entities.append(self._result(root_id, "album", album, entity_key=f"{artist}|{album}", subtitle=artist, artist=artist, album=album, files=files, navigation={"view": "album", "root_id": root_id, "artist": artist, "album": album}))
            for playlist in snapshot.get("playlists") or []:
                name = str(playlist.get("title") or playlist.get("name") or "Playlist")
                key = str(playlist.get("id") or playlist.get("rel") or name)
                entities.append(self._result(root_id, "music_playlist", name, entity_key=key, rel=str(playlist.get("rel") or ""), navigation={"view": "playlist", "root_id": root_id, "playlist": key}))
            videos = list(snapshot.get("videos") or [])
            for movie in snapshot.get("movies") or []:
                title = str(movie.get("title") or movie.get("name") or "Movie")
                rel = str(movie.get("rel") or movie.get("rel_path") or "")
                entities.append(self._result(root_id, "movie", title, entity_key=rel or title, rel=rel, year=movie.get("year"), duration=movie.get("duration"), size=movie.get("size"), files=[self._file(movie, root_id, "video")]))
            for show in snapshot.get("shows") or []:
                show_title = str(show.get("title") or show.get("name") or show.get("show_title") or "Show")
                show_key = str(show.get("id") or show_title)
                entities.append(self._result(root_id, "show", show_title, entity_key=show_key, navigation={"view": "show", "root_id": root_id, "show": show_key}))
                seasons: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
                for episode in show.get("episodes") or []:
                    parsed = episode.get("parse") if isinstance(episode.get("parse"), dict) else {}
                    season = int(episode.get("season") or parsed.get("season") or 0)
                    number = int(episode.get("episode") or parsed.get("episode") or 0)
                    title = str(episode.get("title") or parsed.get("episode_title") or f"Episode {number}")
                    rel = str(episode.get("rel") or episode.get("rel_path") or "")
                    seasons[season].append(episode)
                    entities.append(self._result(root_id, "episode", title, entity_key=rel or f"{show_key}|{season}|{number}", rel=rel, subtitle=f"{show_title} S{season:02d}E{number:02d}", duration=episode.get("duration"), size=episode.get("size"), files=[self._file(episode, root_id, "video")]))
                for season, episodes in seasons.items():
                    entities.append(self._result(root_id, "season", f"Season {season}", entity_key=f"{show_key}|{season}", subtitle=show_title, navigation={"view": "season", "root_id": root_id, "show": show_key, "season": season}))
            for video in videos:
                title = str(video.get("title") or video.get("name") or "Video")
                rel = str(video.get("rel") or video.get("rel_path") or "")
                entities.append(self._result(root_id, "video", title, entity_key=rel or title, rel=rel, duration=video.get("duration"), size=video.get("size"), files=[self._file(video, root_id, "video")]))
                parent = os.path.dirname(rel).replace("\\", "/")
                while parent:
                    folders.add(parent); parent = os.path.dirname(parent).replace("\\", "/")
            for folder in snapshot.get("folders") or []:
                folders.add(str(folder.get("rel") if isinstance(folder, dict) else folder).replace("\\", "/"))
            for folder in sorted(value for value in folders if value):
                entities.append(self._result(root_id, "directory", os.path.basename(folder) or folder, entity_key=folder, rel=folder, subtitle=folder, navigation={"view": "folder", "root_id": root_id, "rel": folder}))
        return entities

    def _entity_index(self) -> list[dict[str, Any]]:
        key = repr(self.versions_provider())
        if key != self._cache_key:
            self._entities = self._build()
            self._cache_key = key
        return self._entities

    def _search_rows(self, query: str) -> list[dict[str, Any]]:
        qnorm = normalize_text(query)
        results: list[dict[str, Any]] = []
        for raw in self._entity_index():
            row = dict(raw)
            # Exact artist searches surface the artist and albums, but not every
            # song merely because its artist metadata matches.
            if row["kind"] == "song" and qnorm == normalize_text(row.get("artist")):
                if assess_match(query, {"title": row["title"]}).unrelated:
                    continue
            assessment = assess_match(query, row)
            if not assessment.unrelated:
                row["match_confidence"] = assessment.confidence
                results.append(row)
        return results

    async def search(self, query: str, context: Any = None) -> ProviderSearchResponse:
        started = time.monotonic()
        results = await asyncio.to_thread(self._search_rows, query)
        return ProviderSearchResponse("library", {"status": "ok", "root_versions": self.versions_provider()}, results, duration_ms=int((time.monotonic() - started) * 1000))

    async def search_stream(self, query: str, context: Any = None):
        yield await self.search(query, context)
