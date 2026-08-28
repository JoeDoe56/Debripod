from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from yt_dlp.extractor.soundcloud import SoundcloudBaseIE, SoundcloudIE, SoundcloudSetIE, SoundcloudUserIE


class DebriPodSoundcloudSearchBase(SoundcloudBaseIE):
    _SEARCH_KIND = ""
    _ENDPOINT = ""
    _RESULT_IE = SoundcloudIE

    def _entries(self, query, maximum):
        endpoint = self._API_V2_BASE + self._ENDPOINT
        request_query = {"q": query, "limit": 200, "linked_partitioning": 1}
        yielded = 0
        next_url = endpoint
        while next_url and (maximum is None or yielded < maximum):
            parsed = urlparse(next_url)
            existing = dict(parse_qsl(parsed.query))
            page_url = urlunparse(parsed._replace(query=""))
            page_query = request_query if next_url == endpoint else existing
            page_query["client_id"] = self._CLIENT_ID
            payload = self._call_api(page_url, query, query=page_query, headers=self._HEADERS)
            collection = payload.get("collection") if isinstance(payload, dict) else []
            for item in collection if isinstance(collection, list) else []:
                if maximum is not None and yielded >= maximum:
                    break
                permalink = str(item.get("permalink_url") or "").strip()
                if not permalink:
                    continue
                result = self.url_result(permalink, ie=self._RESULT_IE.ie_key(), video_id=str(item.get("id") or ""), video_title=item.get("title") or item.get("username"))
                result.update({
                    "soundcloud_id": item.get("id"),
                    "permalink_url": permalink,
                    "thumbnail": item.get("artwork_url") or item.get("avatar_url"),
                    "uploader": item.get("username") or item.get("user", {}).get("username"),
                    "duration": (item.get("duration") or 0) / 1000 if item.get("duration") else None,
                    "track_count": item.get("track_count"),
                    "set_type": item.get("set_type"),
                })
                yielded += 1
                yield result
            next_url = str(payload.get("next_href") or "") if isinstance(payload, dict) else ""
            if next_url:
                parsed_next = urlparse(next_url)
                query_values = dict(parse_qsl(parsed_next.query))
                query_values.setdefault("client_id", self._CLIENT_ID)
                next_url = urlunparse(parsed_next._replace(query=urlencode(query_values)))
            request_query = {}

    def _real_extract(self, url):
        match = self._match_valid_url(url)
        query = match.group("query")
        maximum = int(match.group("count")) if match.group("count") else None
        return self.playlist_result(self._entries(query, maximum), playlist_title=f"SoundCloud {self._SEARCH_KIND} search: {query}")


class DebriPodSoundcloudTrackSearchIE(DebriPodSoundcloudSearchBase):
    IE_NAME = "debripod:soundcloud:track-search"
    _VALID_URL = r"sctracksearch(?P<count>\d*):(?P<query>.+)"
    _SEARCH_KIND = "track"
    _ENDPOINT = "search/tracks"
    _RESULT_IE = SoundcloudIE


class DebriPodSoundcloudArtistSearchIE(DebriPodSoundcloudSearchBase):
    IE_NAME = "debripod:soundcloud:artist-search"
    _VALID_URL = r"scartistsearch(?P<count>\d*):(?P<query>.+)"
    _SEARCH_KIND = "artist"
    _ENDPOINT = "search/users"
    _RESULT_IE = SoundcloudUserIE


class DebriPodSoundcloudAlbumSearchIE(DebriPodSoundcloudSearchBase):
    IE_NAME = "debripod:soundcloud:album-search"
    _VALID_URL = r"scalbumsearch(?P<count>\d*):(?P<query>.+)"
    _SEARCH_KIND = "album"
    _ENDPOINT = "search/albums"
    _RESULT_IE = SoundcloudSetIE


class DebriPodSoundcloudPlaylistSearchIE(DebriPodSoundcloudSearchBase):
    IE_NAME = "debripod:soundcloud:playlist-search"
    _VALID_URL = r"scplaylistsearch(?P<count>\d*):(?P<query>.+)"
    _SEARCH_KIND = "playlist"
    _ENDPOINT = "search/playlists_without_albums"
    _RESULT_IE = SoundcloudSetIE
