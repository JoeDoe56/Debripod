from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod import auth
from debripod.factory import SESSION_COOKIE, json_response, session_middleware
from debripod.passwords import generate_password_hash
from debripod.storage import sessions, users


def _session_token(user_id: str, username: str, csrf_token: str = "csrf-token") -> str:
    token = f"token-{user_id}"
    sessions.save(token, {"user_id": user_id, "username": username, "csrf_token": csrf_token}, max_age=3600)
    return token


def test_immutable_ids_roles_and_session_revocation(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "identities.sqlite3"))
    alice = users.create_user("alice", generate_password_hash("alice-password"), role="owner")
    bob = users.create_user("bob", generate_password_hash("bob-password"), role="user")
    assert alice["role"] == "owner"
    assert bob["role"] == "user"

    users.update_username(alice["user_id"], "alice-renamed")
    renamed = users.get_user_by_username("alice-renamed")
    assert renamed and renamed["user_id"] == alice["user_id"] and renamed["role"] == "owner"

    token = _session_token(bob["user_id"], "bob")
    assert sessions.load(token)["values"]["user_id"] == bob["user_id"]
    sessions.revoke_user(bob["user_id"])
    assert sessions.load(token) is None


def test_owner_route_rejects_normal_user_and_delete_revokes_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "owner-routes.sqlite3"))
    alice = users.create_user("alice", generate_password_hash("alice-password"), role="owner")
    bob = users.create_user("bob", generate_password_hash("bob-password"), role="user")

    async def admin_probe(request: web.Request) -> web.Response:
        owner = auth.require_owner(request)
        return json_response(ok=True, user_id=owner.user_id)

    async def scenario() -> None:
        app = web.Application(middlewares=[session_middleware, auth.auth_middleware])
        auth.register_auth_routes(app)
        app.router.add_post("/api/admin-probe", admin_probe)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            bob_token = _session_token(bob["user_id"], bob["username"])
            client.session.cookie_jar.update_cookies({SESSION_COOKIE: bob_token})
            denied = await client.post("/api/admin-probe", headers={"X-CSRF-Token": "csrf-token"})
            assert denied.status == 403

            deleted = await client.post("/api/auth/users/delete_current", json={"password": "bob-password"}, headers={"X-CSRF-Token": "csrf-token"})
            assert deleted.status == 200
            assert (await deleted.json())["ok"] is True
            assert sessions.load(bob_token) is None

            alice_token = _session_token(alice["user_id"], alice["username"])
            client.session.cookie_jar.update_cookies({SESSION_COOKIE: alice_token})
            allowed = await client.post("/api/admin-probe", headers={"X-CSRF-Token": "csrf-token"})
            assert allowed.status == 200
            assert (await allowed.json())["user_id"] == alice["user_id"]
        finally:
            await client.close()

    asyncio.run(scenario())
