from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod import auth, runtime_routes
from debripod.factory import session_middleware
from debripod.user_runtime import USER_RUNTIME_KEY


class _Request(dict):
    def __init__(self, payload):
        super().__init__()
        self._payload = payload

    async def json(self):
        return self._payload


def test_normal_user_cannot_change_server_endpoint_or_startup_settings(monkeypatch):
    normal_user = auth.UserContext("user-bob", "bob", "user")
    monkeypatch.setattr(runtime_routes, "current_user", lambda _request: normal_user)

    async def scenario():
        endpoint_request = _Request({"settings": {"RD_BASE": "https://example.test"}})
        endpoint_request[USER_RUNTIME_KEY] = SimpleNamespace(user_id="user-bob")
        endpoint_response = await runtime_routes.api_settings_save(endpoint_request)
        assert endpoint_response.status == 403

        device_request = _Request({"settings": {"UI_GLASS_RENDER_SCALE": 2}})
        device_request[USER_RUNTIME_KEY] = SimpleNamespace(user_id="user-bob")
        device_response = await runtime_routes.api_settings_save(device_request)
        assert device_response.status == 400

        startup_request = _Request({"startup": {"ENABLE_MCP": True}})
        startup_request[USER_RUNTIME_KEY] = SimpleNamespace(user_id="user-bob")
        startup_response = await runtime_routes.api_settings_save(startup_request)
        assert startup_response.status == 403

        token_request = _Request({})
        token_request[USER_RUNTIME_KEY] = SimpleNamespace(user_id="user-bob")
        token_response = await runtime_routes.api_settings_mcp_reset_token(token_request)
        assert token_response.status == 403

    asyncio.run(scenario())


def test_mcp_requires_its_bearer_token_even_for_a_logged_in_owner(monkeypatch):
    owner = auth.UserContext("owner-id", "owner", "owner")
    monkeypatch.setattr(auth, "current_user", lambda _request: owner)
    monkeypatch.setattr(auth, "_security_config", lambda: {"ENABLE_MCP": True, "MCP_TOKEN": "test-token"})
    monkeypatch.setattr(auth.user_repository, "list_users", lambda: [{"user_id": "owner-id", "role": "owner"}])

    async def scenario():
        async def mcp_probe(_request):
            return web.json_response({"ok": True})

        app = web.Application(middlewares=[session_middleware, auth.auth_middleware])
        app.router.add_get("/mcp", mcp_probe)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            denied = await client.get("/mcp")
            assert denied.status == 401
            allowed = await client.get("/mcp", headers={"Authorization": "Bearer test-token"})
            assert allowed.status == 200
        finally:
            await client.close()

    asyncio.run(scenario())
