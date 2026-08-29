from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    timeout: float = 15.0
    maximum_pages: int = 1
    minimum_duplicate_interval: float = 0.0
    cache_ttl: float = 60.0


@dataclass(slots=True)
class TorrentHit:
    source_id: str
    source_label: str
    title: str
    infohash: str = ""
    magnet: str = ""
    size: int = 0
    seeders: int = 0
    leechers: int = 0
    verified: bool = False
    category: str = ""
    published_at: str = ""
    detail_url: str = ""
    torrent_url: str = ""
    source_record_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class TorrentSourceAdapter(Protocol):
    source_id: str
    source_label: str
    policy: SourcePolicy

    async def search(self, query: str, context: Any = None) -> list[TorrentHit]: ...


class SourceUnavailable(RuntimeError):
    def __init__(self, source_id: str, message: str, *, code: str = "unavailable"):
        self.source_id = source_id
        self.code = code
        super().__init__(message)
