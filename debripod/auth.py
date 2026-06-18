from __future__ import annotations

import secrets
import time
import json
import traceback
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlparse

from flask import Response, abort, jsonify, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .config import ensure_startup_security_config, save_config
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


LOGIN_TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{{ title }} - DebriPod</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{color-scheme:dark}
    body{margin:0;min-height:100vh;display:grid;place-items:center;background:#07080a;color:#f5f5f5;font-family:system-ui,-apple-system,Segoe UI,sans-serif}
    main{width:min(360px,calc(100vw - 32px));display:grid;gap:14px}
    h1{font-size:22px;margin:0 0 2px}
    p{margin:0;color:#aaa;line-height:1.45}
    form{display:grid;gap:12px}
    label{display:grid;gap:6px;font-size:13px;color:#cfcfcf}
    input{box-sizing:border-box;width:100%;border:1px solid #2b2f36;background:#11151b;color:#fff;border-radius:8px;padding:12px;font:inherit}
    button{border:0;border-radius:8px;background:#f5f5f5;color:#111;padding:12px;font-weight:700;cursor:pointer}
    button.secondary{background:#1b222c;color:#f5f5f5;border:1px solid #303846}
    .error{color:#ff9d9d;min-height:20px}
  </style>
</head>
<body>
  <main>
    <h1>{{ title }}</h1>
    <p>{{ subtitle }}</p>
    <form method="post" action="{{ action }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>Username<input name="username" autocomplete="username" required autofocus></label>
      <label>Password<input name="password" type="password" autocomplete="{{ password_autocomplete }}" required></label>
      {% if setup %}
      <label>Confirm password<input name="confirm_password" type="password" autocomplete="new-password" required></label>
      {% endif %}
      <button type="submit">{{ button }}</button>
      {% if not setup %}
      <button class="secondary" type="button" id="passkeyBtn">Sign in with passkey</button>
      {% endif %}
      <div class="error">{{ error }}</div>
    </form>
    {% if not setup %}
    <script>
      function b64urlToBuffer(value){
        var s = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
        while(s.length % 4) s += "=";
        var raw = atob(s);
        var out = new Uint8Array(raw.length);
        for(var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
        return out.buffer;
      }
      function bufferToB64url(buffer){
        var bytes = new Uint8Array(buffer || new ArrayBuffer(0));
        var s = "";
        for(var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
        return btoa(s).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/g, "");
      }
      function publicKeyFromServer(options){
        var out = Object.assign({}, options || {});
        out.challenge = b64urlToBuffer(out.challenge);
        if(Array.isArray(out.allowCredentials)){
          out.allowCredentials = out.allowCredentials.map(function(c){
            return Object.assign({}, c, {id:b64urlToBuffer(c.id)});
          });
        }
        return out;
      }
      function credentialToJSON(cred){
        return {
          id: cred.id,
          rawId: bufferToB64url(cred.rawId),
          type: cred.type,
          response: {
            clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
            authenticatorData: bufferToB64url(cred.response.authenticatorData),
            signature: bufferToB64url(cred.response.signature),
            userHandle: cred.response.userHandle ? bufferToB64url(cred.response.userHandle) : null
          }
        };
      }
      var btn = document.getElementById("passkeyBtn");
      if(btn){
        btn.hidden = !(window.PublicKeyCredential && navigator.credentials);
        btn.addEventListener("click", async function(){
          try{
            var optRes = await fetch("/api/auth/passkey/login/options", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
            var opt = await optRes.json();
            if(!optRes.ok || !opt.ok) throw new Error(opt.error || "Passkey sign in is not available.");
            var cred = await navigator.credentials.get({publicKey: publicKeyFromServer(opt.publicKey)});
            var verifyRes = await fetch("/api/auth/passkey/login/verify", {
              method:"POST",
              headers:{"Content-Type":"application/json"},
              body:JSON.stringify({challenge_id:opt.challenge_id, credential:credentialToJSON(cred)})
            });
            var verify = await verifyRes.json();
            if(!verifyRes.ok || !verify.ok) throw new Error(verify.error || "Passkey sign in failed.");
            window.location.href = "{{ next_url }}";
          }catch(e){
            document.querySelector(".error").textContent = e && e.message ? e.message : String(e);
          }
        });
      }
    </script>
    {% endif %}
  </main>
</body>
</html>"""


FAILED_LOGINS: dict[str, dict[str, Any]] = {}
FAILED_LOGINS_LOCKOUT_AFTER = 5
FAILED_LOGINS_LOCKOUT_SECONDS = 120
PASSKEY_RECENT_PASSWORD_SECONDS = 300


def _now() -> float:
    return time.time()


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return str(token)


def _request_csrf_token() -> str:
    return (request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or "").strip()


def _client_ip() -> str:
    return (request.remote_addr or "").strip()


def _login_key(username: str) -> str:
    return f"{username.strip().lower()}|{_client_ip()}"


def _login_locked(username: str) -> bool:
    rec = FAILED_LOGINS.get(_login_key(username))
    if not rec:
        return False
    return float(rec.get("locked_until") or 0.0) > _now()


def _login_failed(username: str) -> None:
    key = _login_key(username)
    rec = FAILED_LOGINS.setdefault(key, {"count": 0, "locked_until": 0.0})
    rec["count"] = int(rec.get("count") or 0) + 1
    if rec["count"] >= FAILED_LOGINS_LOCKOUT_AFTER:
        rec["locked_until"] = _now() + FAILED_LOGINS_LOCKOUT_SECONDS


def _login_succeeded(username: str) -> None:
    FAILED_LOGINS.pop(_login_key(username), None)


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
        if username and password_hash:
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


def _is_logged_in() -> bool:
    return bool(session.get("username"))


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"username": str(user.get("username") or "").strip()}


def _current_user_password_valid(password: str) -> bool:
    username = str(session.get("username") or "")
    user = _find_user(username)
    password_hash = str((user or {}).get("password_hash") or "")
    return bool(user and password_hash and check_password_hash(password_hash, password or ""))


def _mark_recent_password_auth() -> None:
    session["password_authenticated_at"] = _now()


def _has_recent_password_auth() -> bool:
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
    return True, ""


def _mcp_bearer_token_valid() -> bool:
    cfg = _security_config()
    token = str(cfg.get("MCP_TOKEN") or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    if not token or not auth.lower().startswith("bearer "):
        return False
    return secrets.compare_digest(auth[7:].strip(), token)


def _mcp_enabled() -> bool:
    return bool(_security_config().get("ENABLE_MCP"))


def _is_static_or_public_path() -> bool:
    path = request.path or "/"
    if path.startswith("/static/"):
        return True
    if path in {"/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/site.webmanifest"}:
        return True
    if path in {"/login", "/logout", "/setup"}:
        return True
    if path in {"/api/auth/passkey/login/options", "/api/auth/passkey/login/verify"}:
        return True
    return False


def _wants_json() -> bool:
    if request.path.startswith("/api/") or request.path == "/mcp":
        return True
    return "application/json" in (request.headers.get("Accept") or "")


def login_required(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _is_logged_in():
            if _wants_json():
                return jsonify(ok=False, error="Authentication required"), 401
            return redirect(url_for("login", next=request.full_path if request.query_string else request.path))
        return fn(*args, **kwargs)

    return wrapper


def _forbidden(message: str = "Forbidden") -> Response:
    if _wants_json():
        return jsonify(ok=False, error=message), 403
    return Response(message, status=403, mimetype="text/plain")


def _auth_required_response() -> Response:
    if _wants_json():
        return jsonify(ok=False, error="Authentication required"), 401
    return redirect(url_for("login", next=request.full_path if request.query_string else request.path))


def _safe_next_url(default: str = "/") -> str:
    next_url = (request.args.get("next") or default).strip() or default
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


def _webauthn_rp_id() -> str:
    host = (request.host or "localhost").split(":", 1)[0].strip().lower()
    return host or "localhost"


def _external_scheme() -> str:
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
    return "https" if request.is_secure else "http"


def _webauthn_origin() -> str:
    return f"{_external_scheme()}://{request.host}"


def _same_host_origin_from_header() -> str:
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


def _webauthn_expected_origins() -> list[str]:
    origin = _webauthn_origin()
    host = (request.host or "").strip()
    out = [origin]
    header_origin = _same_host_origin_from_header()
    if header_origin and header_origin not in out:
        out.append(header_origin)
    if ":" in host:
        _name, port = host.rsplit(":", 1)
        if port:
            for loopback in ("localhost", "127.0.0.1"):
                candidate = f"{_external_scheme()}://{loopback}:{port}"
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


def _passkey_error(status: int = 501) -> tuple[Any, int]:
    return jsonify({
        "ok": False,
        "error": "Passkey support requires the optional WebAuthn server package. Password login remains available.",
        "available": False,
    }), status


def register_auth(app: Any) -> None:
    cfg = _security_config()
    app.secret_key = str(cfg.get("APP_SECRET_KEY") or "")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    @app.before_request
    def require_auth_and_csrf() -> Any:
        if request.method.upper() == "POST" and request.path in {"/login", "/setup"} and _is_logged_in():
            return redirect(_safe_next_url("/"))

        if request.path == "/mcp":
            if not _mcp_enabled():
                abort(404)
            if not (_is_logged_in() or _mcp_bearer_token_valid()):
                return _auth_required_response()
        elif _setup_needed():
            if not _is_static_or_public_path():
                return redirect(url_for("setup"))
        elif not (_is_static_or_public_path() or _is_logged_in()):
            return _auth_required_response()

        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.path == "/mcp" and _mcp_bearer_token_valid():
                return None
            if request.path in {"/api/auth/passkey/login/options", "/api/auth/passkey/login/verify"}:
                return None
            expected = session.get("csrf_token")
            if not expected or not secrets.compare_digest(str(expected), _request_csrf_token()):
                return _forbidden("Invalid CSRF token")
        return None

    @app.context_processor
    def inject_auth_state() -> dict[str, str]:
        return {"csrf_token": _csrf_token()}

    @app.route("/setup", methods=["GET", "POST"])
    def setup() -> Any:
        if not _setup_needed():
            return redirect(url_for("login"))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm_password") or ""
            if len(username) < 2:
                error = "Could not create account."
            elif len(password) < 8 or password != confirm:
                error = "Could not create account."
            else:
                _save_users([{"username": username, "password_hash": generate_password_hash(password)}])
                session.clear()
                session["username"] = username
                _mark_recent_password_auth()
                _csrf_token()
                return redirect("/")
        return render_template_string(
            LOGIN_TEMPLATE,
            title="Set Up DebriPod",
            subtitle="Create the first local admin account.",
            action=url_for("setup"),
            button="Create Account",
            error=error,
            setup=True,
            csrf_token=_csrf_token(),
            password_autocomplete="new-password",
        )

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if _setup_needed():
            return redirect(url_for("setup"))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = None if _login_locked(username) else _find_user(username)
            password_hash = str((user or {}).get("password_hash") or "")
            if user and password_hash and check_password_hash(password_hash, password):
                _login_succeeded(username)
                session.clear()
                session["username"] = str(user.get("username") or username)
                _mark_recent_password_auth()
                _csrf_token()
                return redirect(_safe_next_url("/"))
            _login_failed(username)
            error = "Invalid username or password."
        return render_template_string(
            LOGIN_TEMPLATE,
            title="Log In",
            subtitle="Use your local DebriPod account.",
            action=url_for("login", next=request.args.get("next") or ""),
            button="Log In",
            error=error,
            setup=False,
            csrf_token=_csrf_token(),
            password_autocomplete="current-password",
            next_url=_safe_next_url("/"),
        )

    @app.route("/logout", methods=["GET", "POST"])
    def logout() -> Any:
        session.clear()
        return redirect(url_for("login"))

    @app.route("/account/create", methods=["GET", "POST"])
    def account_create() -> Any:
        if _setup_needed():
            return redirect(url_for("setup"))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm_password") or ""
            if password != confirm:
                error = "Could not create account."
            else:
                ok, _err = _create_user(username, password)
                if ok:
                    session.clear()
                    return redirect(url_for("login"))
                error = "Could not create account."
        return render_template_string(
            LOGIN_TEMPLATE,
            title="Create Account",
            subtitle="Create another local DebriPod user.",
            action=url_for("account_create"),
            button="Create Account",
            error=error,
            setup=True,
            csrf_token=_csrf_token(),
            password_autocomplete="new-password",
            next_url="/",
        )

    @app.route("/api/auth/passkeys", methods=["GET"])
    def api_auth_passkeys() -> Any:
        if not _is_logged_in():
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        return jsonify({"ok": True, "passkeys": [_public_passkey(p) for p in passkeys_for_user(str(session.get("username") or ""))]})

    @app.route("/api/auth/passkeys/revoke", methods=["POST"])
    def api_auth_passkey_revoke() -> Any:
        if not _is_logged_in():
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        js = request.get_json(silent=True) or {}
        credential_id = str(js.get("credential_id") or "").strip()
        if not credential_id:
            return jsonify({"ok": False, "error": "Missing credential id"}), 400
        revoke_passkey(str(session.get("username") or ""), credential_id)
        return jsonify({"ok": True})

    @app.route("/api/auth/passkeys/rename", methods=["POST"])
    def api_auth_passkey_rename() -> Any:
        if not _is_logged_in():
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        js = request.get_json(silent=True) or {}
        credential_id = str(js.get("credential_id") or "").strip()
        device_label = str(js.get("device_label") or "").strip()
        if not credential_id:
            return jsonify({"ok": False, "error": "Missing credential id"}), 400
        if not device_label:
            return jsonify({"ok": False, "error": "Missing passkey label"}), 400
        rename_passkey(str(session.get("username") or ""), credential_id, device_label)
        return jsonify({"ok": True})

    @app.route("/api/auth/passkey/register/options", methods=["POST"])
    def api_auth_passkey_register_options() -> Any:
        if not _is_logged_in():
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        if not _webauthn_available():
            return _passkey_error()
        js = request.get_json(silent=True) or {}
        if not _has_recent_password_auth() and not _current_user_password_valid(str(js.get("password") or "")):
            return jsonify({"ok": False, "error": "Enter your DebriPod password before adding a passkey."}), 403
        username = str(session.get("username") or "")
        existing = []
        for item in passkeys_for_user(username):
            try:
                existing.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(str(item.get("credential_id") or ""))))  # type: ignore[misc]
            except Exception:
                pass
        opts = generate_registration_options(  # type: ignore[misc]
            rp_id=_webauthn_rp_id(),
            rp_name="DebriPod",
            user_name=username,
            user_display_name=username,
            authenticator_selection=AuthenticatorSelectionCriteria(  # type: ignore[misc]
                resident_key=ResidentKeyRequirement.PREFERRED,  # type: ignore[union-attr]
                user_verification=UserVerificationRequirement.PREFERRED,  # type: ignore[union-attr]
            ),
            exclude_credentials=existing,
        )
        public_key = json.loads(options_to_json(opts))  # type: ignore[misc]
        challenge_id = secrets.token_urlsafe(24)
        save_passkey_challenge(challenge_id, username=username, action="register", challenge=public_key)
        return jsonify({"ok": True, "available": True, "challenge_id": challenge_id, "publicKey": public_key})

    @app.route("/api/auth/passkey/register/verify", methods=["POST"])
    def api_auth_passkey_register_verify() -> Any:
        if not _is_logged_in():
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        if not _webauthn_available():
            return _passkey_error()
        js = request.get_json(silent=True) or {}
        pending = pop_passkey_challenge(str(js.get("challenge_id") or ""), action="register")
        if not pending:
            return jsonify({"ok": False, "error": "Passkey setup expired. Try again."}), 400
        username = str(session.get("username") or "")
        if str(pending.get("username") or "") != username:
            return jsonify({"ok": False, "error": "Passkey setup user changed. Try again."}), 400
        public_key = pending.get("challenge") if isinstance(pending.get("challenge"), dict) else {}
        credential = js.get("credential")
        try:
            verified = verify_registration_response(  # type: ignore[misc]
                credential=credential,
                expected_challenge=base64url_to_bytes(str(public_key.get("challenge") or "")),  # type: ignore[misc]
                expected_rp_id=_webauthn_rp_id(),
                expected_origin=_webauthn_expected_origins(),
                require_user_verification=False,
            )
            credential_id = bytes_to_base64url(verified.credential_id)  # type: ignore[misc]
            public_key_b64 = bytes_to_base64url(verified.credential_public_key)  # type: ignore[misc]
            transports = []
            try:
                transports = list((credential or {}).get("response", {}).get("transports") or [])
            except Exception:
                transports = []
            save_user_passkey(
                username=username,
                credential_id=credential_id,
                public_key=public_key_b64,
                sign_count=int(getattr(verified, "sign_count", 0) or 0),
                transports=[str(x) for x in transports],
                aaguid=str(getattr(verified, "aaguid", "") or ""),
                device_label=str(js.get("device_label") or "This device"),
            )
            saved = passkeys_for_user(username)
            app.logger.info("Passkey registered for user %s; active passkeys: %s", username, len(saved))
            return jsonify({"ok": True, "message": "Passkey enabled for this device.", "passkey_count": len(saved)})
        except Exception as exc:
            app.logger.warning("Passkey registration verification failed: %s\n%s", exc, traceback.format_exc())
            return jsonify({"ok": False, "error": "Passkey setup failed. Use your password and try again."}), 400

    @app.route("/api/auth/passkey/login/options", methods=["POST"])
    def api_auth_passkey_login_options() -> Any:
        if _setup_needed():
            return jsonify({"ok": False, "error": "Set up DebriPod before adding passkeys."}), 400
        if not _webauthn_available():
            return _passkey_error()
        allow = []
        checked_users = []
        for user in _valid_users():
            username = str(user.get("username") or "")
            user_passkeys = passkeys_for_user(username)
            checked_users.append({"username": username, "passkeys": len(user_passkeys)})
            for item in user_passkeys:
                try:
                    allow.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(str(item.get("credential_id") or ""))))  # type: ignore[misc]
                except Exception:
                    pass
        if not allow:
            app.logger.warning("Passkey login requested but no active credentials were found; checked=%s", checked_users)
            return jsonify({"ok": False, "error": "No passkeys are registered. Use your password."}), 400
        opts = generate_authentication_options(  # type: ignore[misc]
            rp_id=_webauthn_rp_id(),
            allow_credentials=allow,
            user_verification=UserVerificationRequirement.PREFERRED,  # type: ignore[union-attr]
        )
        public_key = json.loads(options_to_json(opts))  # type: ignore[misc]
        challenge_id = secrets.token_urlsafe(24)
        save_passkey_challenge(challenge_id, username="", action="login", challenge=public_key)
        return jsonify({"ok": True, "available": True, "challenge_id": challenge_id, "publicKey": public_key})

    @app.route("/api/auth/passkey/login/verify", methods=["POST"])
    def api_auth_passkey_login_verify() -> Any:
        if not _webauthn_available():
            return _passkey_error()
        js = request.get_json(silent=True) or {}
        pending = pop_passkey_challenge(str(js.get("challenge_id") or ""), action="login")
        if not pending:
            return jsonify({"ok": False, "error": "Passkey sign in expired. Try again."}), 400
        credential = js.get("credential") or {}
        credential_id = str(credential.get("id") or credential.get("rawId") or "")
        item = passkey_by_credential_id(credential_id)
        if not item:
            return jsonify({"ok": False, "error": "Passkey is not registered for this DebriPod server."}), 400
        public_key = pending.get("challenge") if isinstance(pending.get("challenge"), dict) else {}
        try:
            verified = verify_authentication_response(  # type: ignore[misc]
                credential=credential,
                expected_challenge=base64url_to_bytes(str(public_key.get("challenge") or "")),  # type: ignore[misc]
                expected_rp_id=_webauthn_rp_id(),
                expected_origin=_webauthn_expected_origins(),
                credential_public_key=base64url_to_bytes(str(item.get("public_key") or "")),  # type: ignore[misc]
                credential_current_sign_count=int(item.get("sign_count") or 0),
                require_user_verification=False,
            )
            update_passkey_sign_count(credential_id, int(getattr(verified, "new_sign_count", 0) or 0))
            session.clear()
            session["username"] = str(item.get("username") or "")
            _csrf_token()
            return jsonify({"ok": True, "username": str(item.get("username") or "")})
        except Exception as exc:
            app.logger.warning("Passkey login verification failed: %s\n%s", exc, traceback.format_exc())
            return jsonify({"ok": False, "error": "Passkey sign in failed. Use your password."}), 400

    @app.route("/api/auth/status", methods=["GET"])
    def api_auth_status() -> Any:
        return jsonify(
            {
                "ok": True,
                "setup_required": _setup_needed(),
                "logged_in": _is_logged_in(),
                "username": str(session.get("username") or ""),
                "users": [_public_user(u) for u in _valid_users()],
            }
        )

    @app.route("/api/auth/users", methods=["POST"])
    def api_auth_create_user() -> Any:
        js = request.get_json(silent=True) or {}
        username = str(js.get("username") or "").strip()
        password = str(js.get("password") or "")
        confirm = str(js.get("confirm_password") or "")
        if password != confirm:
            return jsonify({"ok": False, "error": "Could not create user"}), 400
        ok, _err = _create_user(username, password)
        if not ok:
            return jsonify({"ok": False, "error": "Could not create user"}), 400
        return jsonify({"ok": True, "users": [_public_user(u) for u in _valid_users()]})
