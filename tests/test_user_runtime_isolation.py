from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod import runtime_routes
from debripod.factory import AppServices, SERVICES_KEY
from debripod.playback.state import playback_snapshot_public, playback_update_from_client
from debripod.user_runtime import USER_RUNTIME_KEY, UserRuntime, UserRuntimeRegistry


def test_interleaved_user_runtime_requests_do_not_cross_contaminate(monkeypatch):
    users = {
        "alice": SimpleNamespace(user_id="user-alice", username="alice", role="owner"),
        "bob": SimpleNamespace(user_id="user-bob", username="bob", role="user"),
    }

    async def create_runtime(user):
        # Yield once to make concurrent registry creation exercise the lock.
        await asyncio.sleep(0)
        settings = {
            "LIBRARY_FOLDERS": [{"path": f"C:/media/{user.user_id}", "mode": "metadata"}],
            "DEBRID_PROVIDER": "realdebrid" if user.user_id == "user-alice" else "torbox",
            "REAL_DEBRID_API_KEY": "alice-token" if user.user_id == "user-alice" else "",
            "TORBOX_API_KEY": "" if user.user_id == "user-alice" else "bob-token",
            "SOULSEEK_USERNAME": f"{user.username}-slsk",
        }
        runtime = UserRuntime(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            settings_scope=user.username,
            settings=settings,
            settings_signature=(1, 1),
            search_runtime=SimpleNamespace(provider_token=settings["DEBRID_PROVIDER"]),
            soulseek_service=SimpleNamespace(service_token=settings["SOULSEEK_USERNAME"]),
        )
        return runtime

    registry = UserRuntimeRegistry(create_runtime)
    monkeypatch.setattr(runtime_routes, "current_user", lambda request: users.get(request.headers.get("X-Test-User", "")))

    async def handler(request):
        runtime = request[USER_RUNTIME_KEY]
        query = str(request.query.get("q") or "")
        runtime_routes._record_user_search_history(runtime, query, "combined", "cache:" + query)
        playback_update_from_client(
            {
                "media": "audio",
                "root_id": "root-" + runtime.user_id,
                "rel": query + ".m4a",
                "event": "start",
                "playing": True,
                "title": query,
            },
            runtime.playback,
        )
        return web.json_response(
            {
                "user_id": runtime.user_id,
                "roots": runtime.settings["LIBRARY_FOLDERS"],
                "provider": runtime.settings["DEBRID_PROVIDER"],
                "token": runtime.search_runtime.provider_token,
                "service_token": runtime.soulseek_service.service_token,
                "history": list(runtime.search_history),
                "playback": playback_snapshot_public(runtime.playback),
            }
        )

    async def scenario():
        app = web.Application(middlewares=[runtime_routes.runtime_middleware])
        app[SERVICES_KEY] = AppServices(user_runtimes=registry)
        app.router.add_get("/runtime", handler)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            alice_response, bob_response = await asyncio.gather(
                client.get("/runtime?q=alice-query", headers={"X-Test-User": "alice"}),
                client.get("/runtime?q=bob-query", headers={"X-Test-User": "bob"}),
            )
            alice = await alice_response.json()
            bob = await bob_response.json()
        finally:
            await client.close()

        assert alice["user_id"] == "user-alice" and bob["user_id"] == "user-bob"
        assert alice["roots"][0]["path"].endswith("user-alice")
        assert bob["roots"][0]["path"].endswith("user-bob")
        assert (alice["provider"], alice["token"], alice["service_token"]) == ("realdebrid", "realdebrid", "alice-slsk")
        assert (bob["provider"], bob["token"], bob["service_token"]) == ("torbox", "torbox", "bob-slsk")
        assert [item["q"] for item in alice["history"]] == ["alice-query"]
        assert [item["q"] for item in bob["history"]] == ["bob-query"]
        assert alice["playback"]["now"]["rel"] == "alice-query.m4a"
        assert bob["playback"]["now"]["rel"] == "bob-query.m4a"

    asyncio.run(scenario())
