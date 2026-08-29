from __future__ import annotations

import asyncio
import email.utils
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping

import aiohttp


@dataclass(frozen=True, slots=True)
class HttpTimeouts:
    metadata: float = 15.0
    download: float = 60.0 * 60.0
    polling: float = 30.0


class HttpStatusError(RuntimeError):
    def __init__(self, status: int, url: str, *, retry_after: float | None = None, body: str = ""):
        self.status = int(status)
        self.url = url
        self.retry_after = retry_after
        self.body = body
        super().__init__(f"HTTP {status} from {url}")


def create_client_session(version: str = "dev", *, connector: aiohttp.BaseConnector | None = None) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=connector or aiohttp.TCPConnector(limit=64, limit_per_host=12, ttl_dns_cache=300, keepalive_timeout=30),
        timeout=aiohttp.ClientTimeout(total=HttpTimeouts().metadata),
        auto_decompress=True,
        headers={"User-Agent": f"DebriPod/{version}"},
        raise_for_status=False,
    )


def _retry_after(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
            return max(0.0, parsed.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


class HttpClient:
    """Shared application-scoped transport with bounded retries and a short response cache."""

    def __init__(self, session: aiohttp.ClientSession, *, timeouts: HttpTimeouts | None = None):
        self.session = session
        self.timeouts = timeouts or HttpTimeouts()
        self._cache: dict[str, tuple[float, bytes, Mapping[str, str], int]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _cache_key(method: str, url: str, params: Mapping[str, Any] | None, data: Any, json_body: Any) -> str:
        return json.dumps(
            [method.upper(), url, sorted((str(k), str(v)) for k, v in (params or {}).items()), data, json_body],
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )

    async def bytes(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Any = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        attempts: int = 2,
        cache_ttl: float = 0.0,
    ) -> tuple[bytes, Mapping[str, str], int]:
        key = self._cache_key(method, url, params, data, json_body)
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1], cached[2], cached[3]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1], cached[2], cached[3]
            last_error: BaseException | None = None
            for attempt in range(max(1, attempts)):
                try:
                    request_timeout = aiohttp.ClientTimeout(total=float(timeout or self.timeouts.metadata))
                    async with self.session.request(
                        method,
                        url,
                        params=params,
                        data=data,
                        json=json_body,
                        headers=headers,
                        timeout=request_timeout,
                    ) as response:
                        body = await response.read()
                        retry_after = _retry_after(response.headers.get("Retry-After", ""))
                        retryable_status = response.status in {502, 503, 504} or (
                            response.status == 429 and retry_after is not None and retry_after <= 2.0
                        )
                        if retryable_status and attempt + 1 < attempts:
                            await asyncio.sleep(retry_after if response.status == 429 else min(0.25 * (2**attempt), 1.0))
                            continue
                        if response.status >= 400:
                            raise HttpStatusError(
                                response.status,
                                str(response.url),
                                retry_after=retry_after,
                                body=body[:500].decode("utf-8", "replace"),
                            )
                        result = (body, dict(response.headers), response.status)
                        if cache_ttl > 0:
                            self._cache[key] = (time.monotonic() + cache_ttl, *result)
                        return result
                except (aiohttp.ClientConnectionError, ConnectionResetError, asyncio.TimeoutError) as exc:
                    last_error = exc
                    if attempt + 1 >= attempts:
                        raise
                    await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
            assert last_error is not None
            raise last_error

    async def json(self, method: str, url: str, **kwargs) -> Any:
        body, _headers, _status = await self.bytes(method, url, **kwargs)
        return json.loads(body.decode("utf-8"))

    async def text(self, method: str, url: str, **kwargs) -> str:
        body, _headers, _status = await self.bytes(method, url, **kwargs)
        return body.decode("utf-8", "replace")

    async def download(
        self,
        method: str,
        url: str,
        destination: Any,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        attempts: int = 2,
        chunk_size: int = 1024 * 1024,
    ) -> int:
        """Stream a large response into a file without buffering it in memory."""
        last_error: BaseException | None = None
        for attempt in range(max(1, attempts)):
            try:
                request_timeout = aiohttp.ClientTimeout(total=float(timeout or self.timeouts.download))
                async with self.session.request(method, url, headers=headers, timeout=request_timeout) as response:
                    retry_after = _retry_after(response.headers.get("Retry-After", ""))
                    retryable_status = response.status in {502, 503, 504} or (
                        response.status == 429 and retry_after is not None and retry_after <= 2.0
                    )
                    if retryable_status and attempt + 1 < attempts:
                        response.release()
                        await asyncio.sleep(retry_after if response.status == 429 else min(0.25 * (2**attempt), 1.0))
                        continue
                    if response.status >= 400:
                        body = await response.content.read(500)
                        raise HttpStatusError(
                            response.status,
                            str(response.url),
                            retry_after=retry_after,
                            body=body.decode("utf-8", "replace"),
                        )
                    written = 0
                    with open(destination, "wb") as output:
                        async for chunk in response.content.iter_chunked(max(64 * 1024, int(chunk_size))):
                            output.write(chunk)
                            written += len(chunk)
                    return written
            except (aiohttp.ClientConnectionError, ConnectionResetError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        assert last_error is not None
        raise last_error
