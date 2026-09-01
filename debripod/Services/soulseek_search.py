from __future__ import annotations

import os
import time
from typing import Any, Callable

from .search.identity import soulseek_result_id
from .search.models import ProviderSearchResponse
from .soulseek import _slsk_group_items_to_dirs


class SoulseekSearchProvider:
    provider_group = "soulseek"

    def __init__(self, service_provider: Callable[[], Any]):
        self.service_provider = service_provider

    async def search(self, query: str, context: Any = None) -> ProviderSearchResponse:
        started = time.monotonic()
        service = self.service_provider()
        if service is None or not service.is_ready():
            return ProviderSearchResponse("soulseek", {"status": "unavailable"}, [], error="Soulseek service is not ready", duration_ms=int((time.monotonic() - started) * 1000))
        items = await service.search_async(query)
        by_user: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_user.setdefault(str(item.get("user") or ""), []).append(item)
        directories: list[dict[str, Any]] = []
        for username, user_items in by_user.items():
            speed = max((int(item.get("speed") or 0) for item in user_items), default=0)
            for directory in _slsk_group_items_to_dirs(username, user_items, str(getattr(service, "user_id", "") or "")):
                directory["user"] = username
                directory["speed"] = speed
                directories.append(directory)
        results: list[dict[str, Any]] = []
        for directory in directories:
            user = str(directory.get("user") or "")
            path = str(directory.get("directory") or "")
            files = []
            for raw in directory.get("files") or []:
                remote = str(raw.get("remote_path") or raw.get("name") or "")
                files.append({"file_id": remote, "name": str(raw.get("name") or os.path.basename(remote)), "title": str(raw.get("name") or os.path.basename(remote)), "path": remote, "size": int(raw.get("size") or 0), "duration": float(raw.get("duration") or 0), "media": str(raw.get("kind") or "file"), "stream_available": False, "download_available": True, "provider_data": {"remote_path": remote}})
            title = path.replace("/", "\\").rstrip("\\").split("\\")[-1] or user or "Soulseek directory"
            result_id = soulseek_result_id(user, path)
            results.append({
                "result_id": result_id, "provider_group": "soulseek", "source": "soulseek", "source_label": "Soulseek",
                "kind": "directory", "kind_label": "Directory", "title": title, "subtitle": user, "artist": "", "album": "", "year": "",
                "duration": 0, "thumbnail": "", "canonical_url": "", "stable_source_id": result_id, "search_blob": "",
                "filter_values": {"sources": [], "types": [], "indexers": [], "media": []}, "match_confidence": 0.0, "rank_score": 0.0,
                "browse_available": True, "stream_available": False, "download_available": True, "files_loaded": True,
                "file_count": len(files), "size": int(directory.get("total_size") or sum(item["size"] for item in files)), "files": files,
                "provider_data": {"user": user, "directory": path, "speed": int(directory.get("speed") or 0)},
            })
        return ProviderSearchResponse("soulseek", {"status": "ok", "file_count": len(items)}, results, duration_ms=int((time.monotonic() - started) * 1000))

    async def search_stream(self, query: str, context: Any = None):
        yield await self.search(query, context)
