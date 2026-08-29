from __future__ import annotations

from typing import Any, Iterator

from .base import SourcePolicy, TorrentHit
from .normalize import infohash, integer, magnet_for_hash, timestamp_text


def _torrent_rows(value: Any, parent: dict[str, Any] | None = None) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    parent = parent or {}
    if isinstance(value, list):
        for item in value:
            yield from _torrent_rows(item, parent)
        return
    if not isinstance(value, dict):
        return
    torrent_keys = {"infoHash", "infohash", "magnet", "magnetUrl", "torrentUrl", "torrent_url"}
    if torrent_keys & set(value):
        yield value, parent
        return
    next_parent = value if any(key in value for key in ("title", "name", "type", "year")) else parent
    for key in ("torrents", "releases", "results", "data", "items", "content"):
        if key in value:
            yield from _torrent_rows(value[key], next_parent)


class TorrentClawAdapter:
    source_id = "torrentclaw"
    source_label = "TorrentClaw"
    endpoint = "https://torrentclaw.com/api/v1/search"
    policy = SourcePolicy(timeout=20, maximum_pages=1, cache_ttl=60)

    def __init__(self, http):
        self.http = http

    async def search(self, query: str, context: Any = None) -> list[TorrentHit]:
        payload = await self.http.json(
            "GET", self.endpoint,
            params={"q": query, "limit": 50, "page": 1},
            timeout=self.policy.timeout, cache_ttl=self.policy.cache_ttl,
        )
        output: list[TorrentHit] = []
        seen: set[str] = set()
        for row, parent in _torrent_rows(payload):
            hash_value = infohash(row.get("infoHash") or row.get("infohash") or row.get("hash") or row.get("magnet"))
            magnet = str(row.get("magnet") or row.get("magnetUrl") or magnet_for_hash(hash_value))
            torrent_url = str(row.get("torrentUrl") or row.get("torrent_url") or "")
            identity = hash_value or magnet or torrent_url
            title = str(row.get("title") or row.get("name") or parent.get("title") or parent.get("name") or "").strip()
            if not title or not identity or identity in seen:
                continue
            seen.add(identity)
            extra_keys = (
                "quality", "codec", "source", "sourceType", "upstreamSource", "qualityScore",
                "languages", "audio", "hdr", "releaseGroup", "season", "episode",
            )
            output.append(TorrentHit(
                source_id=self.source_id, source_label=self.source_label, title=title,
                infohash=hash_value, magnet=magnet, torrent_url=torrent_url,
                size=integer(row.get("size") or row.get("sizeBytes")), seeders=integer(row.get("seeders")),
                leechers=integer(row.get("leechers") or row.get("peers")), verified=bool(row.get("verified")),
                category=str(parent.get("type") or row.get("type") or ""),
                published_at=timestamp_text(row.get("scrapedAt") or row.get("uploadedAt") or row.get("createdAt")),
                detail_url=str(row.get("url") or parent.get("url") or ""),
                source_record_id=str(row.get("id") or ""),
                extra={key: row.get(key) for key in extra_keys if row.get(key) is not None},
            ))
        return output
