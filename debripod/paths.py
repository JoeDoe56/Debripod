from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

_download_dir_provider: Callable[[], str] = lambda: ""
_cache_dir_name_provider: Callable[[], str] = lambda: ""


def configure_paths(
    *,
    download_dir_provider: Callable[[], str],
    cache_dir_name_provider: Callable[[], str],
) -> None:
    global _download_dir_provider, _cache_dir_name_provider
    _download_dir_provider = download_dir_provider
    _cache_dir_name_provider = cache_dir_name_provider


def cache_dir() -> str:
    download_root = str(_download_dir_provider() or "").strip()
    if download_root:
        return os.path.join(download_root, _cache_dir_name_provider())
    package_root = Path(__file__).resolve().parent.parent
    return str(package_root / "data" / "runtime_cache")


def transcode_cache_dir() -> str:
    return os.path.join(cache_dir(), "transcoded")


def art_cache_dir() -> str:
    return os.path.join(cache_dir(), "art")
