from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple


class DeferredApp:
    """Collect Flask registrations until an app factory creates the real app."""

    def __init__(self) -> None:
        self.config: Dict[str, Any] = {}
        self._registrations: List[Tuple[str, tuple, dict, Callable[..., Any]]] = []

    def route(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._registrations.append(("route", args, kwargs, fn))
            return fn

        return decorator

    def context_processor(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self._registrations.append(("context_processor", (), {}, fn))
        return fn

    def apply_to(self, app: Any) -> Any:
        app.config.update(self.config)
        for kind, args, kwargs, fn in self._registrations:
            if kind == "route":
                app.route(*args, **kwargs)(fn)
            elif kind == "context_processor":
                app.context_processor(fn)
        return app
