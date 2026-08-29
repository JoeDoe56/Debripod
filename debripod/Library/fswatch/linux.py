from __future__ import annotations

import ctypes
import os
import select
import struct
import threading
from collections.abc import Iterator

from .base import FilesystemChange, NativeWatcher


IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000
WATCH_MASK = IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF


def parse_events(payload: bytes) -> Iterator[tuple[int, int, int, str]]:
    offset = 0
    while offset + 16 <= len(payload):
        wd, mask, cookie, name_length = struct.unpack_from("iIII", payload, offset)
        offset += 16
        raw_name = payload[offset : offset + name_length]
        offset += name_length
        name = raw_name.split(b"\0", 1)[0].decode("utf-8", errors="surrogateescape")
        yield wd, mask, cookie, name


class InotifyWatcher(NativeWatcher):
    def __init__(self, root, callback):
        super().__init__(root, callback)
        self._fd = -1
        self._fd_lock = threading.Lock()
        self._wd_paths: dict[int, str] = {}
        self._path_wds: dict[str, int] = {}

    def _wake(self) -> None:
        with self._fd_lock:
            fd, self._fd = self._fd, -1
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass

    def _register_tree(self, libc, root: str) -> None:
        for directory, _dirs, _files in os.walk(root):
            path = os.path.abspath(directory)
            if path in self._path_wds:
                continue
            wd = int(libc.inotify_add_watch(self._fd, os.fsencode(path), WATCH_MASK))
            if wd < 0:
                continue
            self._wd_paths[wd] = path
            self._path_wds[path] = wd

    def _forget_watch(self, wd: int) -> None:
        path = self._wd_paths.pop(wd, "")
        if path:
            self._path_wds.pop(path, None)

    def _run(self) -> None:
        if not os.sys.platform.startswith("linux"):
            raise RuntimeError("inotify is available only on Linux")
        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_init1.restype = ctypes.c_int
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        libc.inotify_add_watch.restype = ctypes.c_int
        fd = int(libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC))
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        with self._fd_lock:
            self._fd = fd
        self._register_tree(libc, self.root)
        self._mark_ready()
        try:
            while not self._stop_event.is_set():
                try:
                    ready, _writable, _errors = select.select([fd], [], [], 0.5)
                except (OSError, ValueError):
                    if self._stop_event.is_set():
                        break
                    raise
                if not ready:
                    continue
                try:
                    payload = os.read(fd, 256 * 1024)
                except BlockingIOError:
                    continue
                moves: dict[int, tuple[str, bool]] = {}
                for wd, mask, cookie, name in parse_events(payload):
                    if mask & IN_Q_OVERFLOW:
                        self.emit(FilesystemChange(path=self.root, kind="overflow", is_directory=True))
                        self._wd_paths.clear()
                        self._path_wds.clear()
                        self._register_tree(libc, self.root)
                        continue
                    base = self._wd_paths.get(wd, self.root)
                    path = os.path.abspath(os.path.join(base, name)) if name else base
                    is_directory = bool(mask & IN_ISDIR)
                    if mask & IN_IGNORED:
                        self._forget_watch(wd)
                        continue
                    if mask & IN_MOVED_FROM:
                        moves[cookie] = (path, is_directory)
                        continue
                    if mask & IN_MOVED_TO:
                        old_path, old_is_directory = moves.pop(cookie, ("", False))
                        directory = is_directory or old_is_directory
                        if directory and os.path.isdir(path):
                            self._register_tree(libc, path)
                        self.emit(FilesystemChange(path=path, old_path=old_path, kind="moved", is_directory=directory))
                        continue
                    if mask & IN_CREATE:
                        if is_directory and os.path.isdir(path):
                            self._register_tree(libc, path)
                        self.emit(FilesystemChange(path=path, kind="created", is_directory=is_directory))
                    elif mask & (IN_DELETE | IN_DELETE_SELF):
                        self.emit(FilesystemChange(path=path, kind="deleted", is_directory=is_directory or bool(mask & IN_DELETE_SELF)))
                    elif mask & IN_MOVE_SELF:
                        self.emit(FilesystemChange(path=path, kind="moved", is_directory=True))
                    elif mask & (IN_CLOSE_WRITE | IN_ATTRIB | IN_MODIFY):
                        self.emit(FilesystemChange(path=path, kind="modified", is_directory=is_directory))
                for old_path, is_directory in moves.values():
                    self.emit(FilesystemChange(path=old_path, kind="deleted", is_directory=is_directory))
        finally:
            self._wake()
