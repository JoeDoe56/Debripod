from __future__ import annotations

import re
import threading
import time
from typing import Callable, Dict, List, Tuple
from urllib.parse import quote

import requests

_api_key_provider: Callable[[], str] = lambda: ""
_min_interval_provider: Callable[[], float] = lambda: 0.0
_cache_ttl_provider: Callable[[], float] = lambda: 0.0
_max_retries_provider: Callable[[], int] = lambda: 0
_api_base_provider: Callable[[], str] = lambda: ""
_web_base_provider: Callable[[], str] = lambda: ""
_timeout_provider: Callable[[], int] = lambda: 0
_results_per_page_provider: Callable[[], int] = lambda: 0

KNABEN_SESSION = requests.Session()
KNABEN_SESSION.headers.update(
    {
        "User-Agent": "DebriPod/1.0",
        "Accept": "application/json",
    }
)
KNABEN_LOCK = threading.Lock()
KNABEN_LAST_REQUEST_AT = 0.0
KNABEN_CACHE: Dict[Tuple[str, int], Tuple[float, List[dict], str, str, str]] = {}


def configure_knaben(
    *,
    api_key_provider: Callable[[], str],
    min_interval_provider: Callable[[], float],
    cache_ttl_provider: Callable[[], float],
    max_retries_provider: Callable[[], int],
    api_base_provider: Callable[[], str],
    web_base_provider: Callable[[], str],
    timeout_provider: Callable[[], int],
    results_per_page_provider: Callable[[], int],
) -> None:
    global _api_key_provider, _min_interval_provider, _cache_ttl_provider, _max_retries_provider
    global _api_base_provider, _web_base_provider, _timeout_provider, _results_per_page_provider
    _api_key_provider = api_key_provider
    _min_interval_provider = min_interval_provider
    _cache_ttl_provider = cache_ttl_provider
    _max_retries_provider = max_retries_provider
    _api_base_provider = api_base_provider
    _web_base_provider = web_base_provider
    _timeout_provider = timeout_provider
    _results_per_page_provider = results_per_page_provider


def _session_headers() -> dict:
    headers = dict(KNABEN_SESSION.headers)
    api_key = (_api_key_provider() or "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    else:
        headers.pop("x-api-key", None)
    return headers


def _sleep_to_respect_min_interval() -> None:
    global KNABEN_LAST_REQUEST_AT
    with KNABEN_LOCK:
        now = time.time()
        wait = (KNABEN_LAST_REQUEST_AT + float(_min_interval_provider())) - now
        if wait > 0:
            time.sleep(wait)
        KNABEN_LAST_REQUEST_AT = time.time()


def _knaben_fetch_json(body: dict) -> dict:
    last_err = ""
    for attempt in range(int(_max_retries_provider())):
        _sleep_to_respect_min_interval()
        try:
            resp = requests.post(
                _api_base_provider(),
                json=body,
                headers=_session_headers(),
                timeout=_timeout_provider(),
            )

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = int(retry_after)
                else:
                    delay = min(60, 2 ** attempt)
                time.sleep(delay)
                last_err = f"Knaben API rate limited (429). Retrying after {delay} seconds."
                continue

            if resp.status_code >= 500:
                delay = min(30, 2 ** attempt)
                time.sleep(delay)
                last_err = f"Knaben API server error ({resp.status_code}). Retrying after {delay} seconds."
                continue

            resp.raise_for_status()
            js = resp.json()
            if not isinstance(js, dict):
                raise ValueError("Knaben API returned invalid JSON")
            return js
        except requests.RequestException as e:
            last_err = str(e)
            delay = min(30, 2 ** attempt)
            time.sleep(delay)
        except ValueError as e:
            last_err = str(e) or "Knaben API returned invalid JSON"
            delay = min(30, 2 ** attempt)
            time.sleep(delay)

    raise RuntimeError(last_err or "Failed to fetch from Knaben API")


def make_magnet(infohash: str, title: str) -> str:
    ih = (infohash or "").strip()
    dn = quote((title or "").strip(), safe="")
    if dn:
        return f"magnet:?xt=urn:btih:{ih}&dn={dn}"
    return f"magnet:?xt=urn:btih:{ih}"


def knaben_search(q: str, page: int) -> Tuple[List[dict], str, str, str]:
    q_key = q.strip().lower()
    cache_key = (q_key, page)
    now = time.time()

    cached = KNABEN_CACHE.get(cache_key)
    if cached and (now - cached[0]) <= float(_cache_ttl_provider()):
        return cached[1], cached[2], cached[3], cached[4]

    results_per_page = int(_results_per_page_provider())
    offset = max(0, (page - 1) * results_per_page)

    body = {
        "search_type": "100%",
        "search_field": "title",
        "query": q,
        "order_by": "seeders",
        "order_direction": "desc",
        "from": offset,
        "size": results_per_page,
        "hide_unsafe": True,
        "hide_xxx": False,
    }

    try:
        js = _knaben_fetch_json(body)
    except Exception as e:
        results: List[dict] = []
        err = str(e)
        KNABEN_CACHE[cache_key] = (time.time(), results, err, "", "")
        return results, err, "", ""

    raw_hits = js.get("hits") or []
    results: List[dict] = []

    if isinstance(raw_hits, list):
        for h in raw_hits:
            if not isinstance(h, dict):
                continue

            title = str(h.get("title") or "").strip()
            if not title:
                continue

            magnet = str(h.get("magnetUrl") or "").strip()
            infohash = str(h.get("hash") or "").strip()

            if not magnet:
                if infohash:
                    magnet = make_magnet(infohash, title)
                else:
                    continue

            if not infohash:
                m = re.search(r"btih:([0-9A-Fa-f]{40})", magnet)
                if m:
                    infohash = m.group(1).upper()

            size = h.get("bytes")
            category = str(h.get("category") or "").strip()
            seeders = h.get("seeders")
            peers = h.get("peers")
            details = str(h.get("details") or h.get("link") or "").strip()
            tid = str(h.get("id") or "").strip()

            results.append(
                {
                    "id": tid or infohash or title,
                    "title": title,
                    "infohash": infohash,
                    "magnet": magnet,
                    "size": int(size) if isinstance(size, int) else None,
                    "category": category,
                    "seeders": int(seeders) if isinstance(seeders, int) else None,
                    "leechers": int(peers) if isinstance(peers, int) else None,
                    "verified": False,
                    "href": details or f"{_web_base_provider()}/?q={quote(title)}",
                }
            )

    err = ""
    KNABEN_CACHE[cache_key] = (time.time(), results, err, "", "")
    return results, err, "", ""
