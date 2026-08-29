from __future__ import annotations

from typing import Any

from .base import SourcePolicy, TorrentHit
from .normalize import infohash, integer, magnet_for_hash, records, timestamp_text


class KnabenAdapter:
    source_id = "knaben"
    source_label = "Knaben"
    endpoint = "https://api.knaben.org/v1"
    policy = SourcePolicy(timeout=20, maximum_pages=1, cache_ttl=60)

    def __init__(self, http):
        self.http = http

    async def search(self, query: str, context: Any = None) -> list[TorrentHit]:
        payload = await self.http.json(
            "POST",
            self.endpoint,
            json_body={
                "search_type": "100%", "search_field": "title", "query": query,
                "order_by": "seeders", "order_direction": "desc", "from": 0,
                "size": 300, "hide_unsafe": True,
            },
            timeout=self.policy.timeout,
            cache_ttl=self.policy.cache_ttl,
        )
        output: list[TorrentHit] = []
        for raw in records(payload):
            row = raw.get("_source") if isinstance(raw.get("_source"), dict) else raw
            title = str(row.get("title") or row.get("name") or "").strip()
            hash_value = infohash(row.get("hash") or row.get("infohash") or row.get("magnetUrl"))
            magnet = str(row.get("magnetUrl") or row.get("magnet") or magnet_for_hash(hash_value))
            if not title:
                continue
            output.append(TorrentHit(
                source_id=self.source_id, source_label=self.source_label, title=title,
                infohash=hash_value, magnet=magnet, size=integer(row.get("bytes") or row.get("size")),
                seeders=integer(row.get("seeders")), leechers=integer(row.get("leechers") or row.get("peers")),
                category=str(row.get("category") or ""), published_at=timestamp_text(row.get("date") or row.get("created")),
                detail_url=str(row.get("details") or ""),
                extra={"upstream_origin": row.get("cachedOrigin") or ""},
            ))
        return output
