from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from aiohttp import web

from .playback.state import PlaybackRuntime


@dataclass(slots=True)
class SearchStreamStore:
    """Transient search-stream sessions belonging to one user runtime."""

    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass(slots=True)
class UserRuntime:
    """All request-scoped mutable state for one immutable DebriPod user ID."""

    user_id: str
    username: str
    role: str
    settings_scope: str
    settings: dict[str, Any]
    settings_signature: tuple[int, int]
    search_runtime: Any = None
    soulseek_service: Any = None
    streams: SearchStreamStore = field(default_factory=SearchStreamStore)
    playback: PlaybackRuntime = field(default_factory=PlaybackRuntime)
    search_history: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def update_identity(self, user: Any) -> None:
        self.username = str(getattr(user, "username", self.username) or self.username)
        self.role = str(getattr(user, "role", self.role) or self.role)

    async def close(self) -> None:
        service = self.soulseek_service
        self.soulseek_service = None
        with self.streams.lock:
            self.streams.sessions.clear()
        if service is not None:
            stop = getattr(service, "stop", None)
            if callable(stop):
                try:
                    outcome = stop()
                    if hasattr(outcome, "__await__"):
                        await outcome
                except Exception:
                    pass


RuntimeFactory = Callable[[Any], Awaitable[UserRuntime]]


class UserRuntimeRegistry:
    """Lifecycle manager keyed solely by immutable user IDs."""

    def __init__(self, factory: RuntimeFactory):
        self._factory = factory
        self._runtimes: dict[str, UserRuntime] = {}
        self._lock = asyncio.Lock()

    async def get_user_runtime(self, user: Any) -> UserRuntime:
        user_id = str(getattr(user, "user_id", "") or "").strip()
        if not user_id:
            raise ValueError("User runtime requires an immutable user_id")
        async with self._lock:
            existing = self._runtimes.get(user_id)
            if existing is not None:
                existing.update_identity(user)
                return existing
            created = await self._factory(user)
            if created.user_id != user_id:
                raise RuntimeError("User runtime factory returned the wrong user")
            self._runtimes[user_id] = created
            return created

    async def invalidate_user_runtime(self, user_id: str) -> None:
        runtime = None
        async with self._lock:
            runtime = self._runtimes.pop(str(user_id or "").strip(), None)
        if runtime is not None:
            await runtime.close()

    async def close_user_runtime(self, user_id: str) -> None:
        await self.invalidate_user_runtime(user_id)

    async def close_all(self) -> None:
        async with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        for runtime in runtimes:
            await runtime.close()

    def snapshot(self) -> dict[str, UserRuntime]:
        return dict(self._runtimes)


USER_RUNTIME_KEY: web.RequestKey[UserRuntime] = web.RequestKey("user_runtime", UserRuntime)


def user_runtime_for(request: web.Request) -> UserRuntime:
    return request[USER_RUNTIME_KEY]
