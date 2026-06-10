from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Callable, List, Optional

from ..utils import sha1_text

SEARCH_HISTORY_MAX_ITEMS = 50
SEARCH_DISK_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_SEARCH_DISK_LOCK = threading.Lock()
_cache_dir_provider: Callable[[], str] = lambda: "_debripod_cache"


def configure_search_cache(cache_dir_provider: Callable[[], str]) -> None:
    global _cache_dir_provider
    _cache_dir_provider = cache_dir_provider


def _search_cache_root_dir() -> str:
    p = os.path.join(_cache_dir_provider(), "search_cache")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def _search_history_path() -> str:
    return os.path.join(_search_cache_root_dir(), "search_history.json")


def _search_cache_file_path(key: str) -> str:
    key2 = re.sub(r"[^a-fA-F0-9]", "", str(key or ""))[:64]
    if not key2:
        key2 = sha1_text(str(key or ""))
    return os.path.join(_search_cache_root_dir(), f"res_{key2}.json")


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _read_json_file(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _make_search_cache_key(engine: str, q: str, extra: Optional[dict] = None) -> str:
    eng = (engine or "").strip().lower()
    qq = (q or "").strip()
    extra2 = extra if isinstance(extra, dict) else {}
    payload = {"engine": eng, "q": qq, "extra": extra2}
    return sha1_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _disk_cache_get(key: str) -> Optional[dict]:
    p = _search_cache_file_path(key)
    d = _read_json_file(p)
    if not d:
        return None
    try:
        created = float(d.get("created") or 0.0)
    except Exception:
        created = 0.0
    if created > 0 and (time.time() - created) > SEARCH_DISK_CACHE_TTL_SECONDS:
        return None
    return d


def _disk_cache_set(key: str, engine: str, q: str, extra: Optional[dict], payload: dict) -> None:
    p = _search_cache_file_path(key)
    d = {
        "created": time.time(),
        "engine": (engine or "").strip().lower(),
        "q": (q or "").strip(),
        "extra": extra if isinstance(extra, dict) else {},
        "payload": payload if isinstance(payload, dict) else {},
    }
    _atomic_write_json(p, d)


def _load_search_history() -> List[dict]:
    p = _search_history_path()
    d = _read_json_file(p)
    items = d.get("items") if isinstance(d, dict) else None
    out: List[dict] = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            q = str(it.get("q") or "").strip()
            eng = str(it.get("engine") or "").strip().lower()
            key = str(it.get("cache_key") or "").strip()
            try:
                ts = float(it.get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if not q or eng not in ("knaben", "soulseek", "youtube", "combined") or not key:
                continue
            out.append({"q": q, "engine": eng, "cache_key": key, "ts": ts})
    out.sort(key=lambda x: float(x.get("ts") or 0.0), reverse=True)
    return out[:SEARCH_HISTORY_MAX_ITEMS]


def _save_search_history(items: List[dict]) -> None:
    p = _search_history_path()
    out = []
    for it in (items or [])[:SEARCH_HISTORY_MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        q = str(it.get("q") or "").strip()
        eng = str(it.get("engine") or "").strip().lower()
        key = str(it.get("cache_key") or "").strip()
        ts = float(it.get("ts") or 0.0) if it.get("ts") is not None else 0.0
        if not q or eng not in ("knaben", "soulseek", "youtube", "combined") or not key:
            continue
        out.append({"q": q, "engine": eng, "cache_key": key, "ts": ts})
    _atomic_write_json(p, {"items": out})


def record_search_history(q: str, engine: str, cache_key: str) -> None:
    qq = (q or "").strip()
    eng = (engine or "").strip().lower()
    key = (cache_key or "").strip()
    if not qq or eng not in ("knaben", "soulseek", "youtube", "combined") or not key:
        return
    with _SEARCH_DISK_LOCK:
        items = _load_search_history()
        items = [it for it in items if not (it.get("engine") == eng and it.get("q") == qq)]
        items.insert(0, {"q": qq, "engine": eng, "cache_key": key, "ts": time.time()})
        _save_search_history(items)


def clear_search_history_and_cache() -> None:
    with _SEARCH_DISK_LOCK:
        try:
            p = _search_history_path()
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
        try:
            root = _search_cache_root_dir()
            for fn in os.listdir(root):
                if fn.startswith("res_") and fn.endswith(".json"):
                    try:
                        os.remove(os.path.join(root, fn))
                    except Exception:
                        pass
        except Exception:
            pass
