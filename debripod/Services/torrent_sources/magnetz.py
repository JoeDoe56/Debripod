from __future__ import annotations

import asyncio
from typing import Any

from .base import SourcePolicy, TorrentHit
from .normalize import infohash, integer, magnet_for_hash, records, timestamp_text


class MagnetzAdapter:
    source_id = "magnetz"
    source_label = "Magnetz"
    endpoint = "https://magnetz.eu/api/magnets/search"
    policy = SourcePolicy(timeout=15, maximum_pages=4, cache_ttl=60)

    def __init__(self, http):
        self.http = http

    async def _page(self, query: str, page: int):
        return await self.http.json(
            "GET", self.endpoint, params={"query": query, "page": page},
            timeout=self.policy.timeout, cache_ttl=self.policy.cache_ttl,
        )

    async def search(self, query: str, context: Any = None) -> list[TorrentHit]:
        first = await self._page(query, 1)
        meta = first.get("meta") if isinstance(first, dict) and isinstance(first.get("meta"), dict) else {}
        last_page = min(self.policy.maximum_pages, max(1, integer(meta.get("last_page") or meta.get("lastPage") or 1)))
        remaining = await asyncio.gather(*(self._page(query, page) for page in range(2, last_page + 1)))
        seen: set[str] = set()
        output: list[TorrentHit] = []
        for payload in [first, *remaining]:
            for row in records(payload, ("data", "results", "magnets", "items")):
                title = str(row.get("name") or row.get("title") or "").strip()
                hash_value = infohash(row.get("info_hash") or row.get("infoHash") or row.get("hash") or row.get("magnet_link"))
                magnet = str(row.get("magnet_link") or row.get("magnet") or magnet_for_hash(hash_value))
                identity = hash_value or magnet or str(row.get("sqid") or row.get("id") or "")
                if not title or not identity or identity in seen:
                    continue
                seen.add(identity)
                output.append(TorrentHit(
                    source_id=self.source_id, source_label=self.source_label, title=title,
                    infohash=hash_value, magnet=magnet, size=integer(row.get("size") or row.get("bytes")),
                    seeders=integer(row.get("seeders")), leechers=integer(row.get("leechers")),
                    verified=bool(row.get("verified")), detail_url=str(row.get("web_url") or row.get("url") or ""),
                    published_at=timestamp_text(row.get("created_at") or row.get("created")),
                    source_record_id=str(row.get("sqid") or row.get("id") or ""),
                    extra={
                        key: row.get(key) for key in ("largest_file", "score", "health", "sqid") if row.get(key) is not None
                    },
                ))
        return output
