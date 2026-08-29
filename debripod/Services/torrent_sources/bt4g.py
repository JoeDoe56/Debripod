from __future__ import annotations

from typing import Any

from .base import SourcePolicy
from .rss import parse_rss


class BT4GAdapter:
    source_id = "bt4g"
    source_label = "BT4G"
    endpoint = "https://bt4gprx.com/search"
    policy = SourcePolicy(timeout=20, maximum_pages=1, cache_ttl=60)

    def __init__(self, http):
        self.http = http

    async def search(self, query: str, context: Any = None):
        payload = await self.http.text(
            "GET", self.endpoint,
            params={"q": query, "orderby": "relevance", "category": "all", "p": 1, "page": "rss"},
            timeout=self.policy.timeout, cache_ttl=self.policy.cache_ttl,
        )
        return parse_rss(payload, source_id=self.source_id, source_label=self.source_label)
