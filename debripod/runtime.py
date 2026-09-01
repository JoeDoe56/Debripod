from __future__ import annotations

from typing import Any
import argparse
from pathlib import Path

from aiohttp import web

from . import runtime_downloads as downloads
from . import runtime_route_state as route_state
from . import runtime_routes as routes
from . import runtime_state as state
from .MCP import routes as mcp_routes
from .config import CONFIG_KEYS
from .runtime_downloads import *  # noqa: F401,F403
from .runtime_state import *  # noqa: F401,F403
from .passwords import password_hash_supported
from .config import ensure_startup_security_config
from .logging_setup import configure_logging


_RUNTIME_MODULES = (state, downloads, route_state, mcp_routes, routes)


def _sync_shared_state() -> None:
    for module in (downloads, route_state, mcp_routes, routes):
        if hasattr(module, "SOULSEEK_SERVICE"):
            setattr(module, "SOULSEEK_SERVICE", state.SOULSEEK_SERVICE)


def _sync_config_overrides() -> None:
    for key in CONFIG_KEYS:
        if key in globals():
            value = globals()[key]
            for module in _RUNTIME_MODULES:
                if hasattr(module, key):
                    setattr(module, key, value)


async def create_app() -> web.Application:
    _sync_config_overrides()
    _sync_shared_state()
    return await routes.create_app()


def _print_startup_banner(_aiohttp_message: str) -> None:
    version = str(state.VERSION_INFO.get("display_version") or state.VERSION or "dev")
    local_url = f"http://127.0.0.1:{state.PORT}"
    users = ensure_startup_security_config().get("USERS") or []
    usable_users = [
        user for user in users
        if isinstance(user, dict) and password_hash_supported(str(user.get("password_hash") or ""))
    ]
    print()
    print(f"DebriPod {version} is running.")
    print(f"Local URL: {local_url}")
    print("Phone access: use the HTTPS address configured by Tailscale Serve.")
    if not usable_users:
        print(f"Account setup/recovery: {local_url}/setup")
    print("Press Ctrl+C to stop.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(prog="debripod")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    if args.port is not None:
        state.PORT = args.port
        globals()["PORT"] = args.port
    _sync_config_overrides()
    state.ensure_dirs()
    configure_logging(Path(__file__).resolve().parent.parent / "data" / "logs")
    state.load_playback_state()
    try:
        state.configure_aioslsk_logging(bool(state.AIOSLSK_LOGGING_ENABLED))
    except Exception:
        pass
    state.SOULSEEK_SERVICE = None

    _sync_shared_state()
    web.run_app(create_app(), host="127.0.0.1", port=state.PORT, print=_print_startup_banner)


def __getattr__(name: str) -> Any:
    for module in _RUNTIME_MODULES:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


for _key in CONFIG_KEYS:
    if hasattr(state, _key):
        globals()[_key] = getattr(state, _key)

del _key


if __name__ == "__main__":
    main()
