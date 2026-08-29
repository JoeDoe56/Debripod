from __future__ import annotations

import sys
from collections.abc import Callable

from .base import FilesystemChange, NativeWatcher


def create_watcher(
    root: str,
    callback: Callable[[FilesystemChange], None],
    *,
    platform_name: str | None = None,
) -> NativeWatcher:
    platform = str(platform_name or sys.platform).lower()
    if platform.startswith("win"):
        from .windows import WindowsWatcher

        return WindowsWatcher(root, callback)
    if platform.startswith("linux"):
        from .linux import InotifyWatcher

        return InotifyWatcher(root, callback)
    if platform == "darwin":
        from .darwin import DarwinWatcher

        return DarwinWatcher(root, callback)
    if "bsd" in platform:
        from .bsd import KqueueWatcher

        return KqueueWatcher(root, callback)
    raise RuntimeError(f"native filesystem events are not supported on {platform}")


__all__ = ["FilesystemChange", "NativeWatcher", "create_watcher"]
