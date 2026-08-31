from __future__ import annotations

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


def build_search_runtime(
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
    return SearchRuntime(
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


def configure_search_runtime(**kwargs: Any) -> SearchRuntime:
    """Compatibility constructor; search runtimes are no longer global."""
    return build_search_runtime(**kwargs)


def reset_search_runtime() -> None:
    """Compatibility no-op retained for integrations from pre-runtime builds."""
    return None


def get_search_runtime() -> SearchRuntime:
    raise RuntimeError("Search runtimes are request/user scoped; pass one explicitly")
