from __future__ import annotations

import secrets
import time
import json
import logging
import traceback
from typing import Any
from urllib.parse import quote, urlparse

from aiohttp import web

from .config import ensure_startup_security_config, save_config
from .factory import json_response, session_for
from .passwords import generate_password_hash, password_hash_supported, verify_password_hash
from .settings import ensure_app_settings
from .Library.library_db import (
    passkey_by_credential_id,
    passkeys_for_user,
    pop_passkey_challenge,
    rename_passkey,
    revoke_passkey,
    save_passkey_challenge,
    save_user_passkey,
    update_passkey_sign_count,
)

try:
    from webauthn import (
        base64url_to_bytes,
        generate_authentication_options,
        generate_registration_options,
        options_to_json,
        verify_authentication_response,
        verify_registration_response,
    )
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )
    from webauthn.helpers import bytes_to_base64url
except Exception:
    base64url_to_bytes = None  # type: ignore[assignment]
    bytes_to_base64url = None  # type: ignore[assignment]
    generate_authentication_options = None  # type: ignore[assignment]
    generate_registration_options = None  # type: ignore[assignment]
    options_to_json = None  # type: ignore[assignment]
    verify_authentication_response = None  # type: ignore[assignment]
    verify_registration_response = None  # type: ignore[assignment]
    AuthenticatorSelectionCriteria = None  # type: ignore[assignment]
    PublicKeyCredentialDescriptor = None  # type: ignore[assignment]
    ResidentKeyRequirement = None  # type: ignore[assignment]
    UserVerificationRequirement = None  # type: ignore[assignment]




FAILED_LOGINS: dict[str, dict[str, Any]] = {}
FAILED_LOGINS_LOCKOUT_AFTER = 5
FAILED_LOGINS_LOCKOUT_SECONDS = 120
PASSKEY_RECENT_PASSWORD_SECONDS = 300


def _now() -> float:
    return time.time()


def _csrf_token(request: web.Request) -> str:
    session = session_for(request)
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return str(token)


async def _request_csrf_token(request: web.Request) -> str:
    header = (request.headers.get("X-CSRF-Token") or "").strip()
    if header:
        return header
    if request.can_read_body and request.content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}:
        form = await request.post()
        return str(form.get("csrf_token") or "").strip()
    return ""


def _client_ip(request: web.Request) -> str:
    return (request.remote or "").strip()


def _login_key(request: web.Request, username: str) -> str:
    return f"{username.strip().lower()}|{_client_ip(request)}"


def _login_locked(request: web.Request, username: str) -> bool:
    rec = FAILED_LOGINS.get(_login_key(request, username))
    if not rec:
        return False
    return float(rec.get("locked_until") or 0.0) > _now()


def _login_failed(request: web.Request, username: str) -> None:
    key = _login_key(request, username)
    rec = FAILED_LOGINS.setdefault(key, {"count": 0, "locked_until": 0.0})
    rec["count"] = int(rec.get("count") or 0) + 1
    if rec["count"] >= FAILED_LOGINS_LOCKOUT_AFTER:
        rec["locked_until"] = _now() + FAILED_LOGINS_LOCKOUT_SECONDS


def _login_succeeded(request: web.Request, username: str) -> None:
    FAILED_LOGINS.pop(_login_key(request, username), None)


def _security_config() -> dict[str, Any]:
    return ensure_startup_security_config()


def _users() -> list[dict[str, Any]]:
    users = _security_config().get("USERS") or []
    return users if isinstance(users, list) else []


def _valid_users() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for user in _users():
        if not isinstance(user, dict):
            continue
        username = str(user.get("username") or "").strip()
        password_hash = str(user.get("password_hash") or "").strip()
        if username and password_hash_supported(password_hash):
            out.append(user)
    return out


def _setup_needed() -> bool:
    cfg = _security_config()
    return not (bool(cfg.get("SETUP_COMPLETE")) and bool(_valid_users()))


def _find_user(username: str) -> dict[str, Any] | None:
    wanted = username.strip().lower()
    for user in _valid_users():
        if not isinstance(user, dict):
            continue
        if str(user.get("username") or "").strip().lower() == wanted:
            return user
    return None


def _is_logged_in(request: web.Request) -> bool:
    return bool(session_for(request).get("username"))


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"username": str(user.get("username") or "").strip()}


def _current_user_password_valid(request: web.Request, password: str) -> bool:
    session = session_for(request)
    username = str(session.get("username") or "")
    user = _find_user(username)
    password_hash = str((user or {}).get("password_hash") or "")
    return bool(user and password_hash and _verify_user_password(user, password or ""))


def _verify_user_password(user: dict[str, Any] | None, password: str) -> bool:
    if not user:
        return False
    encoded = str(user.get("password_hash") or "")
    valid, needs_upgrade = verify_password_hash(encoded, password)
    if valid and needs_upgrade:
        username = str(user.get("username") or "").strip().lower()
        upgraded = []
        for item in _valid_users():
            replacement = dict(item)
            if str(item.get("username") or "").strip().lower() == username:
                replacement["password_hash"] = generate_password_hash(password)
            upgraded.append(replacement)
        _save_users(upgraded)
    return valid


def _mark_recent_password_auth(request: web.Request) -> None:
    session = session_for(request)
    session["password_authenticated_at"] = _now()


def _has_recent_password_auth(request: web.Request) -> bool:
    session = session_for(request)
    try:
        ts = float(session.get("password_authenticated_at") or 0.0)
    except Exception:
        ts = 0.0
    return ts > 0 and (_now() - ts) <= PASSKEY_RECENT_PASSWORD_SECONDS


def _save_users(users: list[dict[str, Any]]) -> None:
    cfg = _security_config()
    cfg["USERS"] = users
    cfg["SETUP_COMPLETE"] = bool(users)
    save_config(cfg)


def _create_user(username: str, password: str) -> tuple[bool, str]:
    username = (username or "").strip()
    password = password or ""
    if len(username) < 2 or len(password) < 8:
        return False, "Invalid user details"
    users = _valid_users()
    if any(str(u.get("username") or "").strip().lower() == username.lower() for u in users):
        return False, "User already exists"
    users.append({"username": username, "password_hash": generate_password_hash(password)})
    _save_users(users)
    _initialize_new_user_settings(username)
    return True, ""


def _initialize_new_user_settings(username: str) -> None:
    # ``ensure_app_settings`` restores a retired legacy settings file when one
    # exists and otherwise creates defaults for a genuinely new username.  Do
    # not overwrite an existing user's library and completed-wizard state when
    # repairing or recreating only their login credential.
    ensure_app_settings(username=username)


def _delete_current_user(request: web.Request, password: str) -> tuple[bool, str, bool]:
    session = session_for(request)
    username = str(session.get("username") or "").strip()
    if not username:
        return False, "Authentication required", _setup_needed()
    user = _find_user(username)
    password_hash = str((user or {}).get("password_hash") or "")
    if not user or not password_hash or not _verify_user_password(user, password or ""):
        return False, "Password did not match.", _setup_needed()
    remaining = [u for u in _valid_users() if str(u.get("username") or "").strip().lower() != username.lower()]
    try:
      for item in passkeys_for_user(username):
          credential_id = str(item.get("credential_id") or "")
          if credential_id:
              revoke_passkey(username, credential_id)
    except Exception:
        pass
    _save_users(remaining)
    session.clear()
    return True, "", not bool(remaining)


def _mcp_bearer_token_valid(request: web.Request) -> bool:
    cfg = _security_config()
    token = str(cfg.get("MCP_TOKEN") or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    if not token or not auth.lower().startswith("bearer "):
        return False
    return secrets.compare_digest(auth[7:].strip(), token)


def _mcp_enabled() -> bool:
    return bool(_security_config().get("ENABLE_MCP"))


def _is_static_or_public_path(request: web.Request) -> bool:
    path = request.path or "/"
    if path.startswith("/static/"):
        return True
    if path.startswith("/icons/"):
        return True
    if path in {"/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/site.webmanifest", "/debripod-sw.js"}:
        return True
    if path in {"/login", "/logout", "/setup", "/api/auth/bootstrap"}:
        return True
    if path in {"/api/auth/passkey/login/options", "/api/auth/passkey/login/verify"}:
        return True
    return False


def _wants_json(request: web.Request) -> bool:
    if request.path.startswith("/api/") or request.path == "/mcp":
        return True
    return "application/json" in (request.headers.get("Accept") or "")


def _forbidden(request: web.Request, message: str = "Forbidden") -> web.Response:
    if _wants_json(request):
        return json_response(ok=False, error=message, status=403)
    return web.Response(text=message, status=403, content_type="text/plain")


def _auth_required_response(request: web.Request) -> web.Response:
    if _wants_json(request):
        return json_response(ok=False, error="Authentication required", status=401)
    next_url = request.path_qs if request.query_string else request.path
    raise web.HTTPFound(location="/login?next=" + next_url)


def _safe_next_url(request: web.Request, default: str = "/") -> str:
    next_url = (request.query.get("next") or default).strip() or default
    if not next_url.startswith("/") or next_url.startswith("//"):
        return default
    return next_url


def _webauthn_available() -> bool:
    return bool(
        generate_registration_options
        and generate_authentication_options
        and verify_registration_response
        and verify_authentication_response
        and options_to_json
        and base64url_to_bytes
        and bytes_to_base64url
    )


def _passkey_login_available() -> bool:
    if not _webauthn_available():
        return False
    return any(passkeys_for_user(str(user.get("username") or "")) for user in _valid_users())


def _webauthn_rp_id(request: web.Request) -> str:
    host = (request.host or "localhost").split(":", 1)[0].strip().lower()
    return host or "localhost"


def _external_scheme(request: web.Request) -> str:
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
    if forwarded_proto in {"http", "https"}:
        return forwarded_proto
    forwarded = request.headers.get("Forwarded") or ""
    for part in forwarded.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.lower() == "proto":
            proto = value.strip('"').lower()
            if proto in {"http", "https"}:
                return proto
    return "https" if request.secure else "http"


def _webauthn_origin(request: web.Request) -> str:
    return f"{_external_scheme(request)}://{request.host}"


def _same_host_origin_from_header(request: web.Request) -> str:
    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return ""
    try:
        parsed_origin = urlparse(origin)
        parsed_host = (parsed_origin.netloc or "").lower()
        request_host = (request.host or "").lower()
        if parsed_origin.scheme in {"http", "https"} and parsed_host == request_host:
            return f"{parsed_origin.scheme}://{parsed_origin.netloc}"
    except Exception:
        return ""
    return ""


def _webauthn_expected_origins(request: web.Request) -> list[str]:
    origin = _webauthn_origin(request)
    host = (request.host or "").strip()
    out = [origin]
    header_origin = _same_host_origin_from_header(request)
    if header_origin and header_origin not in out:
        out.append(header_origin)
    if ":" in host:
        _name, port = host.rsplit(":", 1)
        if port:
            for loopback in ("localhost", "127.0.0.1"):
                candidate = f"{_external_scheme(request)}://{loopback}:{port}"
                if candidate not in out:
                    out.append(candidate)
    return out


def _public_passkey(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "credential_id": str(item.get("credential_id") or ""),
        "device_label": str(item.get("device_label") or "This device"),
        "created_at": item.get("created_at"),
        "last_used_at": item.get("last_used_at"),
        "transports": item.get("transports") or "[]",
    }


def _passkey_error(status: int = 501) -> web.Response:
    return json_response({
        "ok": False,
        "error": "Passkey support requires the optional WebAuthn server package. Password login remains available.",
        "available": False,
    }, status=status)


def _auth_page() -> web.FileResponse:
    from pathlib import Path

    return web.FileResponse(Path(__file__).resolve().parent / "static" / "auth.html")


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.method == "POST" and request.path in {"/login", "/setup"} and _is_logged_in(request):
        raise web.HTTPFound(location=_safe_next_url(request, "/"))

    if request.path == "/mcp":
        if not _mcp_enabled():
            raise web.HTTPNotFound()
        if not (_is_logged_in(request) or _mcp_bearer_token_valid(request)):
            return _auth_required_response(request)
    elif _setup_needed():
        if not _is_static_or_public_path(request):
            raise web.HTTPFound(location="/setup")
    elif not (_is_static_or_public_path(request) or _is_logged_in(request)):
        return _auth_required_response(request)

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.path == "/mcp" and _mcp_bearer_token_valid(request):
            return await handler(request)
        if request.path in {"/api/auth/passkey/login/options", "/api/auth/passkey/login/verify"}:
            return await handler(request)
        expected = session_for(request).get("csrf_token")
        supplied = await _request_csrf_token(request)
        if not expected or not secrets.compare_digest(str(expected), supplied):
            return _forbidden(request, "Invalid CSRF token")
    return await handler(request)


def register_auth_routes(app: web.Application) -> None:
    async def api_auth_bootstrap(request: web.Request) -> web.Response:
        mode = str(request.query.get("mode") or "login").strip().lower()
        if _setup_needed():
            mode = "setup"
        elif mode == "setup":
            mode = "login"
        if mode not in {"login", "setup", "create"}:
            mode = "login"
        next_url = _safe_next_url(request, "/")
        descriptions = {
            "login": ("Log In", "Use your local DebriPod account.", "Log In", "/login"),
            "setup": ("Set Up DebriPod", "Create the first local admin account.", "Create Account", "/setup"),
            "create": ("Create Account", "Create another local DebriPod user.", "Create Account", "/account/create"),
        }
        title, subtitle, button, action = descriptions[mode]
        if mode == "login" and next_url != "/":
            action += "?next=" + quote(next_url, safe="/")
        return json_response(
            ok=True,
            title=title,
            subtitle=subtitle,
            button=button,
            action=action,
            setup=mode in {"setup", "create"},
            passkey=mode == "login" and _passkey_login_available(),
            next_url=next_url,
            csrf_token=_csrf_token(request),
            error="Invalid username or password." if request.query.get("error") else "",
        )

    async def setup(request: web.Request) -> web.Response:
        if not _setup_needed():
            raise web.HTTPFound(location="/login")
        session = session_for(request)
        if request.method == "POST":
            form = await request.post()
            username = str(form.get("username") or "").strip()
            password = str(form.get("password") or "")
            confirm = str(form.get("confirm_password") or "")
            if len(username) < 2 or len(password) < 8 or password != confirm:
                raise web.HTTPFound(location="/setup?error=1")
            else:
                _save_users([{"username": username, "password_hash": generate_password_hash(password)}])
                _initialize_new_user_settings(username)
                session.clear()
                session["username"] = username
                _mark_recent_password_auth(request)
                _csrf_token(request)
                raise web.HTTPFound(location="/")
        return _auth_page()

    async def login(request: web.Request) -> web.Response:
        if _setup_needed():
            raise web.HTTPFound(location="/setup")
        session = session_for(request)
        if request.method == "POST":
            form = await request.post()
            username = str(form.get("username") or "").strip()
            password = str(form.get("password") or "")
            user = None if _login_locked(request, username) else _find_user(username)
            password_hash = str((user or {}).get("password_hash") or "")
            if user and password_hash and _verify_user_password(user, password):
                _login_succeeded(request, username)
                session.clear()
                session["username"] = str(user.get("username") or username)
                _mark_recent_password_auth(request)
                _csrf_token(request)
                raise web.HTTPFound(location=_safe_next_url(request, "/"))
            _login_failed(request, username)
            next_url = _safe_next_url(request, "/")
            location = "/login?error=1"
            if next_url != "/":
                location += "&next=" + quote(next_url, safe="/")
            raise web.HTTPFound(location=location)
        return _auth_page()

    async def logout(request: web.Request) -> web.Response:
        session_for(request).clear()
        raise web.HTTPFound(location="/login")

    async def account_create(request: web.Request) -> web.Response:
        if _setup_needed():
            raise web.HTTPFound(location="/setup")
        session = session_for(request)
        if request.method == "POST":
            form = await request.post()
            username = str(form.get("username") or "").strip()
            password = str(form.get("password") or "")
            confirm = str(form.get("confirm_password") or "")
            if password != confirm:
                raise web.HTTPFound(location="/account/create?error=1")
            else:
                ok, _err = _create_user(username, password)
                if ok:
                    session.clear()
                    session["username"] = username
                    _mark_recent_password_auth(request)
                    _csrf_token(request)
                    raise web.HTTPFound(location="/?setup=1")
                raise web.HTTPFound(location="/account/create?error=1")
        return _auth_page()

    async def api_auth_passkeys(request: web.Request) -> web.Response:
        if not _is_logged_in(request):
            return json_response(ok=False, error="Authentication required", status=401)
        username = str(session_for(request).get("username") or "")
        return json_response(ok=True, passkeys=[_public_passkey(p) for p in passkeys_for_user(username)])

    async def api_auth_passkey_revoke(request: web.Request) -> web.Response:
        if not _is_logged_in(request):
            return json_response(ok=False, error="Authentication required", status=401)
        data = await request.json()
        credential_id = str(data.get("credential_id") or "").strip()
        if not credential_id:
            return json_response(ok=False, error="Missing credential id", status=400)
        revoke_passkey(str(session_for(request).get("username") or ""), credential_id)
        return json_response(ok=True)

    async def api_auth_passkey_rename(request: web.Request) -> web.Response:
        if not _is_logged_in(request):
            return json_response(ok=False, error="Authentication required", status=401)
        data = await request.json()
        credential_id = str(data.get("credential_id") or "").strip()
        device_label = str(data.get("device_label") or "").strip()
        if not credential_id:
            return json_response(ok=False, error="Missing credential id", status=400)
        if not device_label:
            return json_response(ok=False, error="Missing passkey label", status=400)
        rename_passkey(str(session_for(request).get("username") or ""), credential_id, device_label)
        return json_response(ok=True)

    async def api_auth_passkey_register_options(request: web.Request) -> web.Response:
        if not _is_logged_in(request):
            return json_response(ok=False, error="Authentication required", status=401)
        if not _webauthn_available():
            return _passkey_error()
        data = await request.json()
        if not _has_recent_password_auth(request) and not _current_user_password_valid(request, str(data.get("password") or "")):
            return json_response(ok=False, error="Enter your DebriPod password before adding a passkey.", status=403)
        username = str(session_for(request).get("username") or "")
        existing = []
        for item in passkeys_for_user(username):
            try:
                existing.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(str(item.get("credential_id") or ""))))  # type: ignore[misc]
            except Exception:
                pass
        options = generate_registration_options(  # type: ignore[misc]
            rp_id=_webauthn_rp_id(request),
            rp_name="DebriPod",
            user_name=username,
            user_display_name=username,
            authenticator_selection=AuthenticatorSelectionCriteria(  # type: ignore[misc]
                resident_key=ResidentKeyRequirement.PREFERRED,  # type: ignore[union-attr]
                user_verification=UserVerificationRequirement.PREFERRED,  # type: ignore[union-attr]
            ),
            exclude_credentials=existing,
        )
        public_key = json.loads(options_to_json(options))  # type: ignore[misc]
        challenge_id = secrets.token_urlsafe(24)
        save_passkey_challenge(challenge_id, username=username, action="register", challenge=public_key)
        return json_response(ok=True, available=True, challenge_id=challenge_id, publicKey=public_key)

    async def api_auth_passkey_register_verify(request: web.Request) -> web.Response:
        if not _is_logged_in(request):
            return json_response(ok=False, error="Authentication required", status=401)
        if not _webauthn_available():
            return _passkey_error()
        data = await request.json()
        pending = pop_passkey_challenge(str(data.get("challenge_id") or ""), action="register")
        if not pending:
            return json_response(ok=False, error="Passkey setup expired. Try again.", status=400)
        username = str(session_for(request).get("username") or "")
        if str(pending.get("username") or "") != username:
            return json_response(ok=False, error="Passkey setup user changed. Try again.", status=400)
        public_key = pending.get("challenge") if isinstance(pending.get("challenge"), dict) else {}
        credential = data.get("credential")
        try:
            verified = verify_registration_response(  # type: ignore[misc]
                credential=credential,
                expected_challenge=base64url_to_bytes(str(public_key.get("challenge") or "")),  # type: ignore[misc]
                expected_rp_id=_webauthn_rp_id(request),
                expected_origin=_webauthn_expected_origins(request),
                require_user_verification=False,
            )
            credential_id = bytes_to_base64url(verified.credential_id)  # type: ignore[misc]
            public_key_b64 = bytes_to_base64url(verified.credential_public_key)  # type: ignore[misc]
            transports = list((credential or {}).get("response", {}).get("transports") or [])
            save_user_passkey(
                username=username,
                credential_id=credential_id,
                public_key=public_key_b64,
                sign_count=int(getattr(verified, "sign_count", 0) or 0),
                transports=[str(value) for value in transports],
                aaguid=str(getattr(verified, "aaguid", "") or ""),
                device_label=str(data.get("device_label") or "This device"),
            )
            saved = passkeys_for_user(username)
            logging.info("Passkey registered for user %s; active passkeys: %s", username, len(saved))
            return json_response(ok=True, message="Passkey enabled for this device.", passkey_count=len(saved))
        except Exception as exc:
            logging.warning("Passkey registration verification failed: %s\n%s", exc, traceback.format_exc())
            return json_response(ok=False, error="Passkey setup failed. Use your password and try again.", status=400)

    async def api_auth_passkey_login_options(request: web.Request) -> web.Response:
        if _setup_needed():
            return json_response(ok=False, available=False, error="Set up DebriPod before adding passkeys.", status=400)
        if not _webauthn_available():
            return _passkey_error()
        allow = []
        for user in _valid_users():
            username = str(user.get("username") or "")
            user_passkeys = passkeys_for_user(username)
            for item in user_passkeys:
                try:
                    allow.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(str(item.get("credential_id") or ""))))  # type: ignore[misc]
                except Exception:
                    pass
        if not allow:
            return json_response(ok=True, available=False, error="No passkeys are registered. Use your password.")
        options = generate_authentication_options(  # type: ignore[misc]
            rp_id=_webauthn_rp_id(request),
            allow_credentials=allow,
            user_verification=UserVerificationRequirement.PREFERRED,  # type: ignore[union-attr]
        )
        public_key = json.loads(options_to_json(options))  # type: ignore[misc]
        challenge_id = secrets.token_urlsafe(24)
        save_passkey_challenge(challenge_id, username="", action="login", challenge=public_key)
        return json_response(ok=True, available=True, challenge_id=challenge_id, publicKey=public_key)

    async def api_auth_passkey_login_verify(request: web.Request) -> web.Response:
        if not _webauthn_available():
            return _passkey_error()
        data = await request.json()
        pending = pop_passkey_challenge(str(data.get("challenge_id") or ""), action="login")
        if not pending:
            return json_response(ok=False, error="Passkey sign in expired. Try again.", status=400)
        credential = data.get("credential") or {}
        credential_id = str(credential.get("id") or credential.get("rawId") or "")
        item = passkey_by_credential_id(credential_id)
        if not item:
            return json_response(ok=False, error="Passkey is not registered for this DebriPod server.", status=400)
        public_key = pending.get("challenge") if isinstance(pending.get("challenge"), dict) else {}
        try:
            verified = verify_authentication_response(  # type: ignore[misc]
                credential=credential,
                expected_challenge=base64url_to_bytes(str(public_key.get("challenge") or "")),  # type: ignore[misc]
                expected_rp_id=_webauthn_rp_id(request),
                expected_origin=_webauthn_expected_origins(request),
                credential_public_key=base64url_to_bytes(str(item.get("public_key") or "")),  # type: ignore[misc]
                credential_current_sign_count=int(item.get("sign_count") or 0),
                require_user_verification=False,
            )
            update_passkey_sign_count(credential_id, int(getattr(verified, "new_sign_count", 0) or 0))
            session = session_for(request)
            session.clear()
            session["username"] = str(item.get("username") or "")
            _csrf_token(request)
            return json_response(ok=True, username=str(item.get("username") or ""))
        except Exception as exc:
            logging.warning("Passkey login verification failed: %s\n%s", exc, traceback.format_exc())
            return json_response(ok=False, error="Passkey sign in failed. Use your password.", status=400)

    async def api_auth_status(request: web.Request) -> web.Response:
        return json_response(
            ok=True,
            setup_required=_setup_needed(),
            logged_in=_is_logged_in(request),
            username=str(session_for(request).get("username") or ""),
            users=[_public_user(user) for user in _valid_users()],
        )

    async def api_auth_create_user(request: web.Request) -> web.Response:
        data = await request.json()
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        confirm = str(data.get("confirm_password") or "")
        if password != confirm:
            return json_response(ok=False, error="Could not create user", status=400)
        ok, _err = _create_user(username, password)
        if not ok:
            return json_response(ok=False, error="Could not create user", status=400)
        return json_response(ok=True, users=[_public_user(user) for user in _valid_users()], setup_required=True)

    async def api_auth_delete_current_user(request: web.Request) -> web.Response:
        if not _is_logged_in(request):
            return json_response(ok=False, error="Authentication required", status=401)
        data = await request.json()
        ok, error, setup_required = _delete_current_user(request, str(data.get("password") or ""))
        if not ok:
            return json_response(ok=False, error=error or "Could not delete user", status=400)
        return json_response(ok=True, setup_required=bool(setup_required))

    app.router.add_get("/api/auth/bootstrap", api_auth_bootstrap)
    app.router.add_route("*", "/setup", setup)
    app.router.add_route("*", "/login", login)
    app.router.add_route("*", "/logout", logout)
    app.router.add_route("*", "/account/create", account_create)
    app.router.add_get("/api/auth/passkeys", api_auth_passkeys)
    app.router.add_post("/api/auth/passkeys/revoke", api_auth_passkey_revoke)
    app.router.add_post("/api/auth/passkeys/rename", api_auth_passkey_rename)
    app.router.add_post("/api/auth/passkey/register/options", api_auth_passkey_register_options)
    app.router.add_post("/api/auth/passkey/register/verify", api_auth_passkey_register_verify)
    app.router.add_post("/api/auth/passkey/login/options", api_auth_passkey_login_options)
    app.router.add_post("/api/auth/passkey/login/verify", api_auth_passkey_login_verify)
    app.router.add_get("/api/auth/status", api_auth_status)
    app.router.add_post("/api/auth/users", api_auth_create_user)
    app.router.add_post("/api/auth/users/delete_current", api_auth_delete_current_user)


__all__ = ["auth_middleware", "register_auth_routes"]
