from __future__ import annotations

from typing import Any

from flask import Flask

from . import runtime_downloads as downloads
from . import runtime_route_state as route_state
from . import runtime_routes as routes
from . import runtime_state as state
from .MCP import routes as mcp_routes
from .config import CONFIG_KEYS
from .runtime_downloads import *  # noqa: F401,F403
from .runtime_state import *  # noqa: F401,F403


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


def create_app() -> Flask:
    _sync_config_overrides()
    _sync_shared_state()
    return routes.create_app()


def main() -> None:
    _sync_config_overrides()
    state.ensure_dirs()
    state.load_playback_state()
    try:
        state.configure_aioslsk_logging()
    except Exception:
        pass
    state.SOULSEEK_SERVICE = None

    _sync_shared_state()
    create_app().run(host="127.0.0.1", port=state.PORT, debug=False, threaded=True)


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
