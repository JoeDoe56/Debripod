from __future__ import annotations

import asyncio
import gc
import inspect
import warnings
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from debripod import auth
from debripod import runtime_routes
from debripod.Services import lastfm as lastfm_service
from debripod.factory import SERVICES_KEY


class _LocalIndex:
    def diagnostics(self):
        return {"ready": True, "count": 0, "meta": {"local_index_generation": "0"}}


def test_full_aiohttp_app_routes_and_shared_session_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "app-lifecycle.sqlite3"))
    runtime = SimpleNamespace(local_index=_LocalIndex(), local_index_updater=None)
    monkeypatch.setattr(
        runtime_routes,
        "ensure_startup_security_config",
        lambda: {},
    )
    monkeypatch.setattr(
        auth,
        "ensure_startup_security_config",
        lambda: {"AUTH_USERS": []},
    )
    monkeypatch.setattr(runtime_routes, "_configure_unified_search_runtime", lambda **_kwargs: runtime)

    async def scenario():
        app = await runtime_routes.create_app()
        routes = list(app.router.routes())
        assert len(routes) >= 100
        assert all(inspect.iscoroutinefunction(route.handler) for route in routes)

        client = TestClient(TestServer(app))
        await client.start_server()
        session = app[SERVICES_KEY].http.session
        try:
            setup = await client.get("/setup", allow_redirects=False)
            assert setup.status in {200, 302}
            favicon = await client.get("/favicon.ico", allow_redirects=False)
            assert favicon.status == 200
            assert not session.closed
        finally:
            await client.close()
        assert session.closed

    asyncio.run(scenario())


def test_lastfm_background_helper_without_running_loop_does_not_leak_coroutine(monkeypatch):
    monkeypatch.setattr(lastfm_service, "lastfm_enabled", lambda: True)

    async def request():
        return None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        lastfm_service._lastfm_async(request)
        gc.collect()
    assert not [warning for warning in caught if "was never awaited" in str(warning.message)]
