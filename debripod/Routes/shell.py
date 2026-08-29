from __future__ import annotations

from typing import Awaitable, Callable

from aiohttp import web


def register_shell_routes(app: web.Application, render_shell: Callable[..., Awaitable[web.Response]]) -> None:
    async def index(request: web.Request) -> web.Response:
        return await render_shell(request, autorefresh=0)

    app.router.add_get("/", index)
