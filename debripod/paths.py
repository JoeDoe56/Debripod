from __future__ import annotations

import os
from typing import Callable

_download_dir_provider: Callable[[], str] = lambda: "./data/debrid"
_cache_dir_name_provider: Callable[[], str] = lambda: "_debripod_cache"


def configure_paths(
    *,
    download_dir_provider: Callable[[], str],
    cache_dir_name_provider: Callable[[], str],
) -> None:
    global _download_dir_provider, _cache_dir_name_provider
    _download_dir_provider = download_dir_provider
    _cache_dir_name_provider = cache_dir_name_provider


def cache_dir() -> str:
    return os.path.join(_download_dir_provider(), _cache_dir_name_provider())


def transcode_cache_dir() -> str:
    return os.path.join(cache_dir(), "transcoded")


def art_cache_dir() -> str:
    return os.path.join(cache_dir(), "art")
