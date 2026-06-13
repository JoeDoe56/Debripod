from __future__ import annotations

from typing import Callable, Dict, Tuple
import threading

import requests

_api_key_provider: Callable[[], str] = lambda: ""
_base_url_provider: Callable[[], str] = lambda: "https://api.real-debrid.com/rest/1.0"
_timeout_provider: Callable[[], int] = lambda: 25
_rd_api_semaphore = threading.BoundedSemaphore(4)


def configure_real_debrid(
    *,
    api_key_provider: Callable[[], str],
    base_url_provider: Callable[[], str],
    timeout_provider: Callable[[], int],
) -> None:
    global _api_key_provider, _base_url_provider, _timeout_provider
    _api_key_provider = api_key_provider
    _base_url_provider = base_url_provider
    _timeout_provider = timeout_provider


def rd_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key_provider()}",
        "User-Agent": "Debripod/1.0",
    }


def rd_request(method: str, path: str, params=None, data=None) -> Tuple[int, str, dict]:
    url = _base_url_provider() + path
    try:
        with _rd_api_semaphore:
            resp = requests.request(
                method=method,
                url=url,
                headers=rd_headers(),
                params=params,
                data=data,
                timeout=_timeout_provider(),
            )
        text = resp.text or ""
        js = {}
        if text.strip().startswith("{") or text.strip().startswith("["):
            try:
                js = resp.json()
            except Exception:
                js = {}
        return resp.status_code, text, js
    except requests.RequestException as e:
        return 0, str(e), {}
