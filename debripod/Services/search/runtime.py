from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .pipeline import SearchPipeline


@dataclass(slots=True)
class SearchRuntime:
    pipeline: SearchPipeline
    library_provider: Any
    soulseek_provider: Any
    torrent_provider: Any
    ytdlp_provider: Any
    definition_store: Any
    indexer_service: Any
    challenge_solver: Any


_LOCK = threading.RLock()
_RUNTIME: SearchRuntime | None = None


def configure_search_runtime(*, pipeline: SearchPipeline, library_provider: Any, soulseek_provider: Any, torrent_provider: Any, ytdlp_provider: Any, definition_store: Any, indexer_service: Any, challenge_solver: Any) -> SearchRuntime:
    global _RUNTIME
    with _LOCK:
        _RUNTIME = SearchRuntime(pipeline, library_provider, soulseek_provider, torrent_provider, ytdlp_provider, definition_store, indexer_service, challenge_solver)
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
