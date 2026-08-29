from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from .local_torrent_index.metadata import QUALITY_LABELS
from .local_torrent_index.schema import LOCAL_SOURCE_DMM, LOCAL_SOURCE_TORRENTS_CSV
from .local_torrent_index.service import DEFAULT_DB_PATH, LocalTorrentIndex
from .search.identity import torrent_result_id
from .search.models import ProviderSearchResponse
from .search.relevance import assess_match


class LocalIndexSearchProvider:
    provider_group = "local_index"
    source = "local_index"
    source_label = "Local Index"

    def __init__(self, index: LocalTorrentIndex | None = None, *, path: str | Path = DEFAULT_DB_PATH):
        self.index = index or LocalTorrentIndex(path)

    @staticmethod
    def _result(row: dict[str, Any], query: str) -> dict[str, Any]:
        infohash = bytes(row["infohash"]).hex()
        source_mask = int(row.get("source_mask") or 0)
        indexer_ids: list[str] = []
        indexer_labels: list[str] = []
        if source_mask & LOCAL_SOURCE_DMM:
            indexer_ids.append("dmm")
            indexer_labels.append("DMM")
        if source_mask & LOCAL_SOURCE_TORRENTS_CSV:
            indexer_ids.append("torrents_csv")
            indexer_labels.append("Torrents CSV")
        title = str(row.get("name") or infohash)
        match = assess_match(query, {"title": title, "subtitle": row.get("parsed_title") or ""})
        magnet = f"magnet:?xt=urn:btih:{infohash}"
        return {
            "result_id": torrent_result_id(infohash, magnet),
            "provider_group": "local_index",
            "source": "local_index",
            "source_label": "Local Index",
            "kind": "torrent",
            "kind_label": "Torrent",
            "title": title,
            "subtitle": str(row.get("parsed_title") or ""),
            "artist": "",
            "album": "",
            "year": str(row.get("year") or ""),
            "duration": 0,
            "thumbnail": "",
            "canonical_url": magnet,
            "stable_source_id": infohash,
            "search_blob": "",
            "filter_values": {
                "sources": ["Local Index"],
                "types": ["Torrent"],
                "indexers": indexer_labels,
                "media": [],
            },
            "match_confidence": float(match.confidence),
            "rank_score": 0.0,
            "browse_available": True,
            "stream_available": False,
            "download_available": True,
            "files_loaded": False,
            "file_count": 0,
            "size": int(row.get("size_bytes") or 0),
            "files": [],
            "provider_data": {
                "infohash": infohash,
                "magnet": magnet,
                "indexer_ids": indexer_ids,
                "indexer_labels": indexer_labels,
                "local_source_mask": source_mask,
                "size": int(row.get("size_bytes") or 0),
                "seeders": int(row.get("csv_seeders") or 0),
                "leechers": int(row.get("csv_leechers") or 0),
                "completed": int(row.get("csv_completed") or 0),
                "scraped_unix": int(row.get("csv_scraped_unix") or 0),
                "parsed_title": str(row.get("parsed_title") or ""),
                "year": row.get("year"),
                "resolution": row.get("resolution"),
                "quality": row.get("quality"),
                "quality_label": QUALITY_LABELS.get(row.get("quality"), ""),
            },
        }

    async def search(self, query: str, context: Any = None) -> ProviderSearchResponse:
        started = time.monotonic()
        results: list[dict[str, Any]] = []
        rows = await asyncio.to_thread(self.index.search, query)
        for index, row in enumerate(rows):
            if index and index % 256 == 0:
                await asyncio.sleep(0)
            result = self._result(row, query)
            if not assess_match(query, result).unrelated:
                results.append(result)
        return ProviderSearchResponse(
            provider_group=self.provider_group,
            source_status={
                "source_id": self.source,
                "source_label": self.source_label,
                "status": "ok" if results else "empty",
                "ok": True,
                "count": len(results),
            },
            results=results,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def search_stream(self, query: str, context: Any = None):
        yield await self.search(query, context)
