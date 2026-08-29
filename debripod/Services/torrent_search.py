from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Iterable

from .http import HttpStatusError
from .search.identity import torrent_result_id
from .search.models import ProviderSearchResponse
from .torrent_sources import ADAPTER_TYPES, SourceUnavailable, TorrentHit


class TorrentSearchProvider:
    provider_group = "torrents"

    def __init__(
        self,
        adapters: Iterable[Any],
        *,
        enabled_sources: Iterable[str] | Callable[[], Iterable[str]] | None = None,
        max_concurrent: int = 7,
    ):
        self.adapters = list(adapters)
        self.enabled_sources = enabled_sources
        self.max_concurrent = max(1, min(7, int(max_concurrent or 7)))

    def _enabled(self) -> set[str]:
        if self.enabled_sources is None:
            return {str(adapter.source_id) for adapter in self.adapters}
        values = self.enabled_sources() if callable(self.enabled_sources) else self.enabled_sources
        return {str(value).strip().lower() for value in values or []}

    @classmethod
    def from_http(cls, http, *, enabled_sources=None, max_concurrent: int = 7):
        adapters = [adapter_type(http) for adapter_type in ADAPTER_TYPES]
        return cls(adapters, enabled_sources=enabled_sources, max_concurrent=max_concurrent)

    @staticmethod
    def _result(hit: TorrentHit) -> dict[str, Any]:
        canonical = hit.detail_url or hit.torrent_url or hit.magnet
        result_id = torrent_result_id(hit.infohash, canonical)
        indexer_labels = [hit.source_label]
        upstream = str(hit.extra.get("torapi_provider") or "")
        if upstream:
            indexer_labels.append(upstream)
        return {
            "result_id": result_id,
            "provider_group": "torrents",
            "source": "torrent",
            "source_label": "Torrents",
            "kind": "torrent",
            "kind_label": "Torrent",
            "title": hit.title,
            "subtitle": hit.category,
            "artist": "",
            "album": "",
            "year": "",
            "duration": 0,
            "thumbnail": "",
            "canonical_url": canonical,
            "stable_source_id": hit.infohash or hit.source_record_id or canonical,
            "search_blob": "",
            "filter_values": {"sources": ["Torrents"], "types": ["Torrent"], "indexers": indexer_labels, "media": []},
            "match_confidence": 0.0,
            "rank_score": 0.0,
            "browse_available": bool(hit.infohash or hit.magnet or hit.detail_url or hit.torrent_url),
            "stream_available": False,
            "download_available": bool(hit.infohash or hit.magnet or hit.torrent_url),
            "files_loaded": False,
            "file_count": 0,
            "size": int(hit.size or 0),
            "files": [],
            "provider_data": {
                "infohash": hit.infohash,
                "magnet": hit.magnet,
                "indexer_ids": [hit.source_id],
                "indexer_labels": indexer_labels,
                "source_urls": [value for value in (hit.detail_url, hit.torrent_url) if value],
                "source_record_id": hit.source_record_id,
                "seeders": int(hit.seeders or 0),
                "leechers": int(hit.leechers or 0),
                "verified": bool(hit.verified),
                "category": hit.category,
                "published_at": hit.published_at,
                "torrent_url": hit.torrent_url,
                "extra": dict(hit.extra),
            },
        }

    @staticmethod
    def _error_status(adapter: Any, exc: BaseException, elapsed_ms: int) -> dict[str, Any]:
        if isinstance(exc, SourceUnavailable):
            state = exc.code
        elif isinstance(exc, HttpStatusError) and exc.status == 429:
            state = "rate_limited"
        elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            state = "timeout"
        elif isinstance(exc, asyncio.CancelledError):
            state = "cancelled"
        else:
            state = "error"
        return {
            "source_id": adapter.source_id,
            "source_label": adapter.source_label,
            "status": state,
            "error": str(exc),
            "duration_ms": elapsed_ms,
            "result_count": 0,
        }

    async def search_stream(self, query: str, context: Any):
        enabled = self._enabled()
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_adapter(adapter):
            started = time.monotonic()
            try:
                async with semaphore:
                    hits = await adapter.search(query, context)
                return adapter, hits, int((time.monotonic() - started) * 1000), None
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                return adapter, [], int((time.monotonic() - started) * 1000), exc

        active = [adapter for adapter in self.adapters if adapter.source_id in enabled]
        tasks = [asyncio.create_task(run_adapter(adapter), name=f"torrent:{adapter.source_id}") for adapter in active]
        try:
            for completed in asyncio.as_completed(tasks):
                try:
                    adapter, hits, elapsed_ms, error = await completed
                    if error is not None:
                        status = self._error_status(adapter, error, elapsed_ms)
                        yield ProviderSearchResponse("torrents", status, [], error=str(error), duration_ms=elapsed_ms)
                        continue
                    results = [self._result(hit) for hit in hits]
                    status = {
                        "source_id": adapter.source_id,
                        "source_label": adapter.source_label,
                        "status": "ok" if results else "empty",
                        "error": "",
                        "duration_ms": elapsed_ms,
                        "result_count": len(results),
                    }
                    yield ProviderSearchResponse("torrents", status, results, duration_ms=elapsed_ms)
                except asyncio.CancelledError:
                    raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def search(self, query: str, context: Any) -> ProviderSearchResponse:
        rows: list[dict[str, Any]] = []
        statuses: list[Any] = []
        started = time.monotonic()
        async for response in self.search_stream(query, context):
            rows.extend(response.results)
            statuses.append(response.source_status)
        return ProviderSearchResponse("torrents", statuses, rows, duration_ms=int((time.monotonic() - started) * 1000))
