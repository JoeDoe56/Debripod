from __future__ import annotations

from typing import Any

from .base import SourcePolicy
from .torznab import parse_torznab


class TorLockAdapter:
    source_id = "torlock"
    source_label = "TorLock"
    endpoint = "https://www.torlock.com/torznab/api"
    policy = SourcePolicy(timeout=20, maximum_pages=1, minimum_duplicate_interval=60, cache_ttl=60)

    def __init__(self, http):
        self.http = http

    async def search(self, query: str, context: Any = None):
        payload = await self.http.text(
            "GET", self.endpoint,
            params={"t": "search", "q": query, "limit": 100, "offset": 0},
            timeout=self.policy.timeout, cache_ttl=self.policy.cache_ttl,
        )
        return parse_torznab(payload, source_id=self.source_id, source_label=self.source_label)
