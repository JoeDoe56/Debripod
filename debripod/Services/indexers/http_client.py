from __future__ import annotations

import email.utils
import random
import threading
import time
from collections import defaultdict
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .challenge_detection import detect_challenge
from .status import IndexerStatusStore


RETRY_STATUSES = {408, 500, 502, 503, 504}
_HOST_LOCKS: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_HOST_LAST: dict[str, float] = {}


class IndexerHttpClient:
    def __init__(self, indexer_id: str, *, status_store: IndexerStatusStore | None = None, session: requests.Session | None = None, timeout: float = 25, retries: int = 2, rate_limit: float = 0.0, request_delay: float = 0.0, solver: Any = None, sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time, jitter: Callable[[float, float], float] = random.uniform):
        self.indexer_id = indexer_id
        self.status_store = status_store or IndexerStatusStore()
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.rate_limit = max(float(rate_limit), float(request_delay))
        self.solver = solver
        self.sleep, self.now, self.jitter = sleep, now, jitter
        self._load_clearance()

    def _load_clearance(self) -> None:
        status = self.status_store.get(self.indexer_id)
        if status.user_agent:
            self.session.headers["User-Agent"] = status.user_agent
        for cookie in status.cookies:
            if cookie.get("name"):
                self.session.cookies.set(cookie["name"], cookie.get("value", ""), domain=cookie.get("domain"), path=cookie.get("path", "/"))

    def _rate_wait(self, url: str) -> None:
        host = urlparse(url).netloc.casefold()
        with _HOST_LOCKS[host]:
            wait = _HOST_LAST.get(host, 0.0) + self.rate_limit - self.now()
            if wait > 0:
                self.sleep(wait)
            _HOST_LAST[host] = self.now()

    @staticmethod
    def _retry_after(response: Any) -> float | None:
        value = str(getattr(response, "headers", {}).get("Retry-After", "") or "").strip()
        if not value:
            return None
        if value.isdigit():
            return float(value)
        try:
            return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None

    def request(self, method: str, url: str, **kwargs: Any):
        last_error: Exception | None = None
        solved = False
        for attempt in range(self.retries + 1):
            self._rate_wait(url)
            started = time.monotonic()
            try:
                response = self.session.request(method, url, timeout=kwargs.pop("timeout", self.timeout), allow_redirects=kwargs.pop("allow_redirects", False), **kwargs)
                duration = (time.monotonic() - started) * 1000
                detection = detect_challenge(response)
                if attempt == 0 and detection.detected and self.solver is not None and not solved:
                    solved = True
                    clearance = self.solver.solve(self.indexer_id, url, response)
                    if clearance.get("ok"):
                        cookies = list(clearance.get("cookies") or [])
                        user_agent = str(clearance.get("user_agent") or "")
                        self.status_store.save_clearance(self.indexer_id, cookies, user_agent)
                        self._load_clearance()
                        continue
                    # Let the provider stop its whole mirror/path fallback sequence.
                    # Re-running an unresolved browser challenge against every mirror
                    # only multiplies a slow failure and cannot improve this response.
                    response._debripod_challenge_failed = True
                    response._debripod_challenge_error = str(clearance.get("error") or "challenge solver failed")
                status = int(response.status_code)
                if status == 429:
                    retry_after = self._retry_after(response)
                    self.status_store.record_failure(self.indexer_id, "rate_limited", retry_after=retry_after, duration_ms=duration)
                    if attempt < self.retries:
                        self.sleep(retry_after if retry_after is not None else self.rate_limit * (2 ** attempt) + self.jitter(0, .25))
                        continue
                elif status in RETRY_STATUSES and attempt < self.retries:
                    self.sleep(max(self.rate_limit, .1) * (2 ** attempt) + self.jitter(0, .25))
                    continue
                if 200 <= status < 400:
                    self.status_store.record_success(self.indexer_id, duration_ms=duration)
                else:
                    self.status_store.record_failure(self.indexer_id, f"http_{status}", duration_ms=duration)
                return response
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt < self.retries:
                    self.sleep(max(self.rate_limit, .1) * (2 ** attempt) + self.jitter(0, .25))
                    continue
                self.status_store.record_failure(self.indexer_id, "connection", connection_failure=True)
                raise
        if last_error:
            raise last_error
        raise RuntimeError("request failed")
