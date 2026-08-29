from __future__ import annotations

import os
import select
import threading

from .base import FilesystemChange, NativeWatcher


class KqueueWatcher(NativeWatcher):
    """Recursive kqueue directory watcher; events trigger targeted reconciliation."""

    def __init__(self, root, callback):
        super().__init__(root, callback)
        self._kqueue = None
        self._lock = threading.Lock()
        self._fds: dict[int, str] = {}
        self._paths: dict[str, int] = {}

    def _wake(self) -> None:
        with self._lock:
            queue, self._kqueue = self._kqueue, None
        if queue is not None:
            try:
                queue.close()
            except OSError:
                pass

    def _sync_directories(self) -> None:
        queue = self._kqueue
        if queue is None:
            return
        current = {os.path.abspath(path) for path, _dirs, _files in os.walk(self.root)}
        for path in sorted(current - self._paths.keys()):
            fd = -1
            try:
                fd = os.open(path, os.O_RDONLY)
                event = select.kevent(
                    fd,
                    filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                    fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_ATTRIB | select.KQ_NOTE_EXTEND,
                )
                queue.control([event], 0, 0)
                self._fds[fd] = path
                self._paths[path] = fd
            except OSError:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        for path in list(self._paths):
            if path in current:
                continue
            fd = self._paths.pop(path)
            self._fds.pop(fd, None)
            try:
                os.close(fd)
            except OSError:
                pass

    def _run(self) -> None:
        if not hasattr(select, "kqueue"):
            raise RuntimeError("kqueue is unavailable")
        with self._lock:
            self._kqueue = select.kqueue()
        self._sync_directories()
        self._mark_ready()
        try:
            while not self._stop_event.is_set():
                queue = self._kqueue
                if queue is None:
                    break
                try:
                    events = queue.control(None, 128, 0.5)
                except (OSError, ValueError):
                    if self._stop_event.is_set():
                        break
                    raise
                for event in events:
                    path = self._fds.get(int(event.ident), self.root)
                    flags = int(event.fflags)
                    if flags & select.KQ_NOTE_DELETE:
                        kind = "deleted"
                    elif flags & select.KQ_NOTE_RENAME:
                        kind = "moved"
                    else:
                        kind = "modified"
                    self.emit(FilesystemChange(path=path, kind=kind, is_directory=True))
                if events:
                    self._sync_directories()
        finally:
            self._wake()
            for fd in list(self._fds):
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._fds.clear()
            self._paths.clear()
