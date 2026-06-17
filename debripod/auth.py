from __future__ import annotations

import secrets
import time
from functools import wraps
from typing import Any, Callable

from flask import Response, abort, jsonify, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .config import ensure_startup_security_config, save_config


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
      <div class="error">{{ error }}</div>
    </form>
  </main>
</body>
</html>"""


FAILED_LOGINS: dict[str, dict[str, Any]] = {}
FAILED_LOGINS_LOCKOUT_AFTER = 5
FAILED_LOGINS_LOCKOUT_SECONDS = 120


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
        )

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
