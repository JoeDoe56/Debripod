from __future__ import annotations

from typing import Any, Iterator

from .base import SourcePolicy, TorrentHit
from .normalize import infohash, integer, magnet_for_hash, timestamp_text


_PROVIDERS = {"rutracker", "kinozal", "rutor", "nonameclub"}


def _provider_rows(payload: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            provider = str(key).replace("_", "").replace("-", "").casefold()
            if provider in _PROVIDERS:
                rows = value if isinstance(value, list) else value.get("results", []) if isinstance(value, dict) else []
                for row in rows:
                    if isinstance(row, dict):
                        yield key, row
            elif key in {"data", "results", "providers"}:
                yield from _provider_rows(value)
    elif isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                provider = str(row.get("provider") or row.get("source") or "")
                yield provider, row


class TorAPIAdapter:
    source_id = "torapi"
    source_label = "TorAPI"
    base_url = "https://torapi.vercel.app"
    policy = SourcePolicy(timeout=60, maximum_pages=1, cache_ttl=60)

    def __init__(self, http):
        self.http = http

    async def search(self, query: str, context: Any = None) -> list[TorrentHit]:
        payload = await self.http.json(
            "GET", self.base_url + "/api/search/title/all",
            params={"query": query, "page": "all"},
            timeout=self.policy.timeout, cache_ttl=self.policy.cache_ttl,
        )
        output: list[TorrentHit] = []
        for provider, row in _provider_rows(payload):
            title = str(row.get("title") or row.get("name") or "").strip()
            hash_value = infohash(row.get("hash") or row.get("infohash") or row.get("info_hash") or row.get("magnet"))
            magnet = str(row.get("magnet") or magnet_for_hash(hash_value))
            record_id = str(row.get("id") or row.get("topic_id") or row.get("torrent_id") or "")
            detail_url = str(row.get("url") or row.get("link") or row.get("details") or "")
            torrent_url = str(row.get("torrent") or row.get("torrent_url") or row.get("download") or "")
            if not title or not (hash_value or magnet or record_id or detail_url or torrent_url):
                continue
            output.append(TorrentHit(
                source_id=self.source_id, source_label=self.source_label, title=title,
                infohash=hash_value, magnet=magnet, size=integer(row.get("size") or row.get("bytes")),
                seeders=integer(row.get("seeders")), leechers=integer(row.get("leechers") or row.get("peers")),
                category=str(row.get("category") or ""), published_at=timestamp_text(row.get("date") or row.get("created")),
                detail_url=detail_url, torrent_url=torrent_url, source_record_id=record_id,
                extra={"torapi_provider": provider},
            ))
        return output

    async def resolve(self, hit: TorrentHit) -> TorrentHit:
        if hit.infohash or hit.magnet or not hit.source_record_id:
            return hit
        provider = str(hit.extra.get("torapi_provider") or "").casefold()
        payload = await self.http.json(
            "GET", self.base_url + f"/api/search/id/{provider}",
            params={"query": hit.source_record_id}, timeout=self.policy.timeout,
        )
        row = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if isinstance(row, dict):
            hash_value = infohash(row.get("hash") or row.get("infohash") or row.get("magnet"))
            hit.infohash = hash_value
            hit.magnet = str(row.get("magnet") or magnet_for_hash(hash_value))
            hit.torrent_url = str(row.get("torrent") or row.get("torrent_url") or hit.torrent_url)
        return hit
