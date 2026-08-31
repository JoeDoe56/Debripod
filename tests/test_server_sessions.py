from __future__ import annotations

import asyncio
import sqlite3
from http.cookies import SimpleCookie
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod import auth
from debripod.factory import SESSION_COOKIE, _secure_cookie_request, session_for, session_middleware
from debripod.passwords import generate_password_hash
from debripod.settings import ensure_app_settings, save_app_settings
from debripod.storage import sessions


def _cookie_value(header: str) -> str:
    parsed = SimpleCookie()
    parsed.load(header)
    return parsed[SESSION_COOKIE].value


def test_server_side_session_rotation_revocation_and_opaque_cookie(monkeypatch, tmp_path):
    database_path = tmp_path / "sessions.sqlite3"
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(database_path))

    async def scenario():
        app = web.Application(middlewares=[session_middleware])

        async def establish(request):
            current = session_for(request)
            current["username"] = "alice"
            current["csrf_token"] = "csrf-one"
            return web.json_response({"ok": True})

        async def rotate(request):
            current = session_for(request)
            current.clear()
            current["username"] = "alice"
            current["csrf_token"] = "csrf-two"
            return web.json_response({"ok": True})

        async def who(request):
            return web.json_response(dict(session_for(request)))

        async def empty(_request):
            return web.json_response({"ok": True})

        async def logout(request):
            session_for(request).clear()
            return web.json_response({"ok": True})

        app.router.add_get("/establish", establish)
        app.router.add_get("/empty", empty)
        app.router.add_get("/rotate", rotate)
        app.router.add_get("/who", who)
        app.router.add_get("/logout", logout)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            empty_response = await client.get("/empty")
            assert "Set-Cookie" not in empty_response.headers
            response = await client.get("/establish")
            first = _cookie_value(response.headers.getall("Set-Cookie")[0])
            assert "alice" not in first and "{" not in first and len(first) >= 40
            who_response = await client.get("/who")
            assert await who_response.json() == {"username": "alice", "csrf_token": "csrf-one"}
            assert "Set-Cookie" not in who_response.headers

            rotated_response = await client.get("/rotate")
            second = _cookie_value(rotated_response.headers.getall("Set-Cookie")[0])
            assert second != first
            assert sessions.load(first) is None
            assert (sessions.load(second) or {})["values"]["csrf_token"] == "csrf-two"

            await client.get("/logout")
            assert sessions.load(second) is None
        finally:
            await client.close()

        with sqlite3.connect(database_path) as conn:
            rows = conn.execute("SELECT token_hash FROM auth_sessions").fetchall()
        assert all(isinstance(row[0], bytes) and len(row[0]) == 32 for row in rows)

    asyncio.run(scenario())


def test_forwarded_https_marks_session_cookie_secure():
    assert _secure_cookie_request(SimpleNamespace(secure=False, headers={"X-Forwarded-Proto": "https"}))
    assert _secure_cookie_request(SimpleNamespace(secure=False, headers={"Forwarded": "for=127.0.0.1;proto=https"}))
    assert not _secure_cookie_request(SimpleNamespace(secure=False, headers={}))


def test_expired_sessions_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "expiry.sqlite3"))
    sessions.save("raw-token", {"username": "alice", "csrf_token": "csrf"}, max_age=1, now=10)
    assert sessions.load("raw-token", now=10) is not None
    assert sessions.load("raw-token", now=12) is None


def test_session_middleware_preserves_http_redirects_and_original_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "middleware-errors.sqlite3"))

    async def scenario():
        app = web.Application(middlewares=[session_middleware])

        async def redirect(_request):
            raise web.HTTPFound(location="/login")

        app.router.add_get("/redirect", redirect)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/redirect", allow_redirects=False)
            assert response.status == 302
            assert response.headers["Location"] == "/login"
        finally:
            await client.close()

        class FakeRequest(dict):
            cookies = {}

        async def fail(_request):
            raise RuntimeError("original handler failure")

        with pytest.raises(RuntimeError, match="original handler failure"):
            await session_middleware(FakeRequest(), fail)

    asyncio.run(scenario())


def test_static_login_csrf_cookie_and_rotated_session_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "login-csrf.sqlite3"))
    user = {"username": "alice", "password_hash": generate_password_hash("correct-password")}
    monkeypatch.setattr(auth, "_setup_needed", lambda: False)
    monkeypatch.setattr(auth, "_valid_users", lambda: [user])

    async def scenario():
        app = web.Application(middlewares=[session_middleware, auth.auth_middleware])
        auth.register_auth_routes(app)

        async def protected(request):
            return web.json_response({"ok": True, "csrf": auth._csrf_token(request)})

        app.router.add_post("/api/protected", protected)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            page = await client.get("/login")
            assert page.status == 200
            bootstrap_response = await client.get("/api/auth/bootstrap?mode=login")
            bootstrap = await bootstrap_response.json()
            assert bootstrap_response.status == 200
            assert bootstrap["csrf_token"]

            login = await client.post(
                "/login",
                data={
                    "username": "alice",
                    "password": "correct-password",
                    "csrf_token": bootstrap["csrf_token"],
                },
                allow_redirects=False,
            )
            assert login.status == 302
            assert login.headers["Location"] == "/"

            app_bootstrap = await client.get("/api/auth/status")
            status = await app_bootstrap.json()
            assert status["logged_in"] is True
            token_response = await client.get("/api/auth/bootstrap?mode=login")
            token = (await token_response.json())["csrf_token"]
            assert token != bootstrap["csrf_token"]
            protected_response = await client.post("/api/protected", headers={"X-CSRF-Token": token})
            assert protected_response.status == 200
        finally:
            await client.close()

    asyncio.run(scenario())


def test_passkey_login_uses_the_same_rotating_server_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "passkey-session.sqlite3"))
    monkeypatch.setattr(auth, "_setup_needed", lambda: False)
    monkeypatch.setattr(auth, "_webauthn_available", lambda: True)
    monkeypatch.setattr(
        auth,
        "pop_passkey_challenge",
        lambda _challenge_id, action: {"challenge": {"challenge": "AA"}} if action == "login" else None,
    )
    monkeypatch.setattr(
        auth,
        "passkey_by_credential_id",
        lambda credential_id: {
            "credential_id": credential_id,
            "username": "alice",
            "public_key": "AA",
            "sign_count": 0,
        },
    )
    monkeypatch.setattr(auth, "base64url_to_bytes", lambda _value: b"\0")
    monkeypatch.setattr(
        auth,
        "verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(new_sign_count=1),
    )
    monkeypatch.setattr(auth, "update_passkey_sign_count", lambda *_args: None)
    monkeypatch.setattr(auth, "_valid_users", lambda: [{"username": "alice", "password_hash": "unused"}])

    async def scenario():
        app = web.Application(middlewares=[session_middleware, auth.auth_middleware])
        auth.register_auth_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post(
                "/api/auth/passkey/login/verify",
                json={"challenge_id": "challenge", "credential": {"id": "credential"}},
            )
            assert response.status == 200
            token = _cookie_value(response.headers.getall("Set-Cookie")[0])
            stored = sessions.load(token)
            assert (stored or {})["values"]["username"] == "alice"
            status = await (await client.get("/api/auth/status")).json()
            assert status["logged_in"] is True
            assert status["username"] == "alice"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_malformed_only_account_enters_safe_setup_recovery(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "account-recovery.sqlite3"))
    configured = [{"username": "tester", "password_hash": "x"}]
    monkeypatch.setattr(auth, "_security_config", lambda: {"SETUP_COMPLETE": True, "USERS": configured})
    monkeypatch.setattr(auth, "_initialize_new_user_settings", lambda _username: None)

    assert auth._valid_users() == []
    assert auth._setup_needed()

    async def scenario():
        app = web.Application(middlewares=[session_middleware, auth.auth_middleware])
        auth.register_auth_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            bootstrap = await (await client.get("/api/auth/bootstrap?mode=setup")).json()
            response = await client.post(
                "/setup",
                data={
                    "username": "tester",
                    "password": "replacement-password",
                    "confirm_password": "replacement-password",
                    "csrf_token": bootstrap["csrf_token"],
                },
                allow_redirects=False,
            )
            assert response.status == 302
            assert response.headers["Location"] == "/"
            created = auth._find_user("tester")
            assert created and created["role"] == "owner"
            assert created["password_hash"] != "replacement-password"
            assert len(created["password_hash"]) > 100
        finally:
            await client.close()

    asyncio.run(scenario())


def test_bootstrap_does_not_offer_or_probe_missing_passkeys(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "no-passkeys.sqlite3"))
    user = {"username": "alice", "password_hash": generate_password_hash("correct-password")}
    monkeypatch.setattr(auth, "_setup_needed", lambda: False)
    monkeypatch.setattr(auth, "_valid_users", lambda: [user])
    monkeypatch.setattr(auth, "_webauthn_available", lambda: True)
    monkeypatch.setattr(auth, "passkeys_for_user", lambda _username: [])

    async def scenario():
        app = web.Application(middlewares=[session_middleware, auth.auth_middleware])
        auth.register_auth_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            bootstrap = await (await client.get("/api/auth/bootstrap?mode=login")).json()
            assert bootstrap["passkey"] is False
            options_response = await client.post("/api/auth/passkey/login/options", json={})
            assert options_response.status == 200
            assert await options_response.json() == {
                "ok": True,
                "available": False,
                "error": "No passkeys are registered. Use your password.",
            }
        finally:
            await client.close()

    asyncio.run(scenario())


def test_account_initialization_preserves_existing_user_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "existing-user-settings.sqlite3"))
    folders = [{"path": str(tmp_path / "music"), "mode": "meta"}]
    save_app_settings(
        {"SETUP_WIZARD_COMPLETE": True, "LIBRARY_FOLDERS": folders},
        username="returning-user",
    )

    auth._initialize_new_user_settings("returning-user")

    restored = ensure_app_settings(username="returning-user")
    assert restored["SETUP_WIZARD_COMPLETE"] is True
    assert restored["LIBRARY_FOLDERS"] == folders


def test_account_initialization_uses_first_run_defaults_for_new_username(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "new-user-settings.sqlite3"))

    auth._initialize_new_user_settings("new-user")

    created = ensure_app_settings(username="new-user")
    assert created["SETUP_WIZARD_COMPLETE"] is False
    assert created["LIBRARY_FOLDERS"] == []
