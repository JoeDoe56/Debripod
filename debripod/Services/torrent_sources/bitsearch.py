from __future__ import annotations

from typing import Any

from .base import SourcePolicy, TorrentHit
from .normalize import infohash, integer, magnet_for_hash, records, timestamp_text


class BitSearchAdapter:
    source_id = "bitsearch"
    source_label = "BitSearch"
    endpoint = "https://bitsearch.to/api/v1/search"
    policy = SourcePolicy(timeout=15, maximum_pages=1, minimum_duplicate_interval=60, cache_ttl=300)

    def __init__(self, http):
        self.http = http

    async def search(self, query: str, context: Any = None) -> list[TorrentHit]:
        payload = await self.http.json(
            "GET", self.endpoint,
            params={"q": query, "limit": 100, "page": 1},
            timeout=self.policy.timeout, cache_ttl=self.policy.cache_ttl,
        )
        output: list[TorrentHit] = []
        for row in records(payload):
            title = str(row.get("title") or row.get("name") or "").strip()
            hash_value = infohash(row.get("infohash") or row.get("info_hash") or row.get("hash") or row.get("magnet"))
            if not title:
                continue
            output.append(TorrentHit(
                source_id=self.source_id, source_label=self.source_label, title=title,
                infohash=hash_value, magnet=str(row.get("magnet") or magnet_for_hash(hash_value)),
                size=integer(row.get("size") or row.get("size_bytes")), seeders=integer(row.get("seeders")),
                leechers=integer(row.get("leechers") or row.get("peers")), verified=bool(row.get("verified")),
                category=str(row.get("category") or ""),
                published_at=timestamp_text(row.get("created_at") or row.get("created") or row.get("date")),
                detail_url=str(row.get("url") or row.get("details") or ""),
            ))
        return output
