from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .pipeline import SearchPipeline


@dataclass(slots=True)
class SearchRuntime:
    pipeline: SearchPipeline
    library_provider: Any
    local_index_provider: Any
    soulseek_provider: Any
    torrent_provider: Any
    ytdlp_provider: Any
    torrent_accumulator_factory: Any
    local_index: Any
    local_index_updater: Any
    torrent_adapters: dict[str, Any]


_LOCK = threading.RLock()
_RUNTIME: SearchRuntime | None = None


def configure_search_runtime(
    *,
    pipeline: SearchPipeline,
    library_provider: Any,
    local_index_provider: Any,
    soulseek_provider: Any,
    torrent_provider: Any,
    ytdlp_provider: Any,
    local_index: Any,
    local_index_updater: Any,
    torrent_adapters: dict[str, Any],
) -> SearchRuntime:
    global _RUNTIME
    with _LOCK:
        _RUNTIME = SearchRuntime(
            pipeline,
            library_provider,
            local_index_provider,
            soulseek_provider,
            torrent_provider,
            ytdlp_provider,
            pipeline.torrent_accumulator_factory,
            local_index,
            local_index_updater,
            dict(torrent_adapters),
        )
        return _RUNTIME


def get_search_runtime() -> SearchRuntime:
    with _LOCK:
        if _RUNTIME is None:
            raise RuntimeError("Unified search runtime is not configured")
        return _RUNTIME


def reset_search_runtime() -> None:
    global _RUNTIME
    with _LOCK:
        _RUNTIME = None
