from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from ...utils import sha1_text


_PLAYLIST_ID = re.compile(r"^(?:PL|OLAK5uy_|UU|LL|FL|RD|VL)?[A-Za-z0-9_-]{10,}$")


def _data(result: Mapping[str, Any] | Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    raw = dict(result or {})
    nested = raw.get("provider_data")
    return {**raw, **(nested if isinstance(nested, dict) else {})}


def _clean_infohash(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("urn:btih:"):
        text = text[9:]
    return text


def library_result_id(root_id: Any, entity_kind: Any, entity_key: Any = "", rel: Any = "") -> str:
    return f"library:{root_id}:{entity_kind}:{sha1_text(str(entity_key or rel or ''))}"


def soulseek_result_id(user: Any, directory: Any) -> str:
    normalized = re.sub(r"[\\/]+", "/", str(directory or "").strip()).casefold()
    return "soulseek:" + sha1_text(f"{user}|{normalized}")


def torrent_result_id(infohash: Any = "", canonical_url: Any = "") -> str:
    value = _clean_infohash(infohash)
    return "torrent:" + value if value else "torrent-url:" + sha1_text(str(canonical_url or ""))


def _playlist_from_browse(value: Any) -> str:
    browse = str(value or "").strip()
    candidate = browse[2:] if browse.startswith("VL") else browse
    return candidate if _PLAYLIST_ID.match(candidate) else ""


def _youtube_url_ids(url: Any) -> tuple[str, str, str]:
    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query)
    video = str((query.get("v") or [""])[0])
    playlist = str((query.get("list") or [""])[0])
    parts = [part for part in parsed.path.split("/") if part]
    channel = parts[1] if len(parts) > 1 and parts[0] in {"channel", "c", "user"} else ""
    if parsed.hostname in {"youtu.be", "www.youtu.be"} and parts:
        video = parts[0]
    return video, playlist, channel


def youtube_result_id(kind: Any, *, video_id: Any = "", playlist_id: Any = "", channel_id: Any = "", browse_id: Any = "", canonical_url: Any = "") -> str:
    kind_text = str(kind or "").strip().lower()
    url_video, url_playlist, url_channel = _youtube_url_ids(canonical_url)
    if kind_text in {"video", "song", "music_video", "episode"}:
        value = str(video_id or url_video or "").strip()
        return "youtube:video:" + value
    if kind_text in {"playlist", "music_playlist", "album", "podcast"}:
        value = str(playlist_id or url_playlist or _playlist_from_browse(browse_id) or "").strip()
        return "youtube:playlist:" + value
    value = str(channel_id or url_channel or browse_id or "").strip()
    return "youtube:channel:" + value


def soundcloud_result_id(kind: Any, numeric_id: Any = "", permalink_url: Any = "") -> str:
    ident = str(numeric_id or "").strip()
    return f"soundcloud:{kind}:{ident}" if ident.isdigit() else "soundcloud-url:" + sha1_text(str(permalink_url or ""))


def stable_result_id(result: Mapping[str, Any] | Any) -> str:
    raw = _data(result)
    source = str(raw.get("source") or "").lower()
    kind = raw.get("kind") or ""
    if source == "library":
        return library_result_id(raw.get("root_id"), kind, raw.get("entity_key"), raw.get("rel"))
    if source == "soulseek":
        return soulseek_result_id(raw.get("user"), raw.get("directory"))
    if source == "torrent":
        return torrent_result_id(raw.get("infohash"), raw.get("canonical_url"))
    if source == "youtube":
        return youtube_result_id(kind, video_id=raw.get("video_id"), playlist_id=raw.get("playlist_id"), channel_id=raw.get("channel_id"), browse_id=raw.get("browse_id"), canonical_url=raw.get("canonical_url"))
    if source == "soundcloud":
        return soundcloud_result_id(kind, raw.get("soundcloud_id"), raw.get("permalink_url") or raw.get("canonical_url"))
    raise ValueError(f"Unsupported search result source: {source}")


def youtube_dedupe_key(result: Mapping[str, Any] | Any) -> str:
    raw = _data(result)
    identity = youtube_result_id(raw.get("kind"), video_id=raw.get("video_id"), playlist_id=raw.get("playlist_id"), channel_id=raw.get("channel_id"), browse_id=raw.get("browse_id"), canonical_url=raw.get("canonical_url"))
    return identity if identity.rsplit(":", 1)[-1] else ""


def torrent_dedupe_key(result: Mapping[str, Any] | Any) -> str:
    raw = _data(result)
    infohash = _clean_infohash(raw.get("infohash"))
    if infohash:
        return "torrent:" + infohash
    magnet = str(raw.get("magnet") or "").strip()
    return "torrent-magnet:" + magnet if magnet else ""


# Short aliases are convenient for provider implementations and tests.
library_identity = library_result_id
soulseek_identity = soulseek_result_id
torrent_identity = torrent_result_id
youtube_identity = youtube_result_id
soundcloud_identity = soundcloud_result_id
