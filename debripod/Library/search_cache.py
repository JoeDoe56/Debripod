from __future__ import annotations

import json
import threading
from typing import Callable, Optional

from ..utils import sha1_text
from .library_db import (
    clear_search_cache,
    load_search_cache,
    load_search_history,
    record_search_history_row,
    save_search_cache,
)

_SEARCH_DISK_LOCK = threading.Lock()
_cache_dir_provider: Callable[[], str] = lambda: ""
_history_max_items_provider: Callable[[], int] = lambda: 0
_disk_cache_ttl_seconds_provider: Callable[[], int] = lambda: 0
SEARCH_CACHE_SCHEMA = 3


def configure_search_cache(
    cache_dir_provider: Callable[[], str],
    *,
    history_max_items_provider: Callable[[], int],
    disk_cache_ttl_seconds_provider: Callable[[], int],
) -> None:
    global _cache_dir_provider, _history_max_items_provider, _disk_cache_ttl_seconds_provider
    _cache_dir_provider = cache_dir_provider
    _history_max_items_provider = history_max_items_provider
    _disk_cache_ttl_seconds_provider = disk_cache_ttl_seconds_provider


def _make_search_cache_key(engine: str, q: str, extra: Optional[dict] = None) -> str:
    eng = (engine or "").strip().lower()
    qq = (q or "").strip()
    extra2 = extra if isinstance(extra, dict) else {}
    payload = {"schema": SEARCH_CACHE_SCHEMA, "engine": eng, "q": qq, "extra": extra2}
    return sha1_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _disk_cache_get(key: str) -> Optional[dict]:
    return load_search_cache(key)


def _disk_cache_set(key: str, engine: str, q: str, extra: Optional[dict], payload: dict) -> None:
    save_search_cache(
        key,
        engine,
        q,
        extra,
        payload,
        ttl_seconds=int(_disk_cache_ttl_seconds_provider() or 0),
    )


def record_search_history(q: str, engine: str, cache_key: str) -> None:
    eng = (engine or "").strip().lower()
    if eng not in ("soulseek", "ytdlp", "torrents", "combined"):
        return
    record_search_history_row(q, eng, cache_key, max_items=int(_history_max_items_provider() or 0))


def search_history() -> list[dict]:
    allowed = {"soulseek", "ytdlp", "torrents", "combined"}
    out = []
    for item in load_search_history(int(_history_max_items_provider() or 0)):
        q = str(item.get("q") or "").strip()
        eng = str(item.get("engine") or "").strip().lower()
        key = str(item.get("cache_key") or "").strip()
        if q and key and eng in allowed:
            out.append({"q": q, "engine": eng, "cache_key": key, "ts": float(item.get("ts") or 0.0)})
    return out


def _load_search_history() -> list[dict]:
    return search_history()


def clear_search_history_and_cache() -> None:
    clear_search_cache()
