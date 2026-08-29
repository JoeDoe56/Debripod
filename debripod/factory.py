from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

from .Services.http import HttpClient
from .storage import sessions as session_repository


SESSION_COOKIE = "debripod_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60


class Session(dict[str, Any]):
    """Mutable server-side session attached explicitly to an aiohttp request."""

    def __init__(
        self,
        values: dict[str, Any] | None = None,
        *,
        raw_token: str = "",
        created_unix: int | None = None,
    ):
        super().__init__(values or {})
        self.invalidated = False
        self.modified = False
        self.raw_token = str(raw_token or "")
        self.created_unix = created_unix

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self or self.get(key) != value:
            self.modified = True
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self.modified = True
        super().__delitem__(key)

    def pop(self, key: str, *args: Any) -> Any:
        if key in self:
            self.modified = True
        return super().pop(key, *args)

    def popitem(self) -> tuple[str, Any]:
        self.modified = True
        return super().popitem()

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self.modified = True
        return super().setdefault(key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        incoming = dict(*args, **kwargs)
        if any(key not in self or self.get(key) != value for key, value in incoming.items()):
            self.modified = True
        super().update(incoming)

    def clear(self) -> None:
        super().clear()
        self.invalidated = True
        self.modified = True


@dataclass(slots=True)
class AppServices:
    http: HttpClient | None = None
    search_runtime: Any = None
    soulseek_service: Any = None
    task_manager: Any = None
    local_index_task: asyncio.Task[Any] | None = None
    library_reconciliation_task: asyncio.Task[Any] | None = None
    local_index_state: dict[str, Any] = field(default_factory=dict)


SERVICES_KEY: web.AppKey[AppServices] = web.AppKey("services", AppServices)
SESSION_KEY: web.RequestKey[Session] = web.RequestKey("session", Session)


def session_for(request: web.Request) -> Session:
    return request[SESSION_KEY]


def _secure_cookie_request(request: web.Request) -> bool:
    if request.secure:
        return True
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    for part in (request.headers.get("Forwarded") or "").split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.lower() == "proto":
            return value.strip('"').lower() == "https"
    return False


@web.middleware
async def session_middleware(request: web.Request, handler):
    raw = request.cookies.get(SESSION_COOKIE, "")
    loaded = await asyncio.to_thread(session_repository.load, raw) if raw else None
    values = dict((loaded or {}).get("values") or {})
    current = Session(
        values,
        raw_token=raw if loaded else "",
        created_unix=(loaded or {}).get("created_unix"),
    )
    request[SESSION_KEY] = current
    http_exception: web.HTTPException | None = None
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        # Exception targets are cleared when an ``except`` block exits, so do
        # not bind the response itself in the ``except ... as`` clause.
        response = exc
        http_exception = exc
    stale_cookie = bool(raw and not loaded)
    if current.invalidated and not current:
        if raw:
            await asyncio.to_thread(session_repository.revoke, raw)
        response.del_cookie(SESSION_COOKIE, path="/")
    elif current.modified or (not current.raw_token and bool(current)):
        if current.invalidated or not current.raw_token:
            if raw:
                await asyncio.to_thread(session_repository.revoke, raw)
            current.raw_token = secrets.token_urlsafe(32)
            current.created_unix = None
        await asyncio.to_thread(
            session_repository.save,
            current.raw_token,
            dict(current),
            max_age=SESSION_MAX_AGE,
            created_unix=current.created_unix,
        )
        response.set_cookie(
            SESSION_COOKIE,
            current.raw_token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=_secure_cookie_request(request),
            samesite="Lax",
            path="/",
        )
    elif stale_cookie:
        response.del_cookie(SESSION_COOKIE, path="/")
    if http_exception is not None:
        raise http_exception
    return response


def json_response(data: dict[str, Any] | None = None, *, status: int = 200, **fields: Any) -> web.Response:
    """Create an API response while keeping endpoint payload construction concise."""

    payload = dict(data or {})
    payload.update(fields)
    return web.json_response(payload, status=status)
