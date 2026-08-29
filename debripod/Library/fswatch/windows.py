from __future__ import annotations

import ctypes
import os
import struct
import threading
from collections.abc import Iterator

from .base import FilesystemChange, NativeWatcher


FILE_ACTION_ADDED = 1
FILE_ACTION_REMOVED = 2
FILE_ACTION_MODIFIED = 3
FILE_ACTION_RENAMED_OLD_NAME = 4
FILE_ACTION_RENAMED_NEW_NAME = 5


def parse_notifications(payload: bytes) -> Iterator[tuple[int, str]]:
    offset = 0
    length = len(payload)
    while offset + 12 <= length:
        next_offset, action, name_bytes = struct.unpack_from("<III", payload, offset)
        start = offset + 12
        end = min(length, start + name_bytes)
        name = payload[start:end].decode("utf-16-le", errors="replace")
        if name:
            yield action, name
        if not next_offset:
            break
        offset += next_offset


class WindowsWatcher(NativeWatcher):
    def __init__(self, root, callback):
        super().__init__(root, callback)
        self._handle = None
        self._handle_lock = threading.Lock()
        self._known_dirs: set[str] = set()

    def _wake(self) -> None:
        handle = None
        with self._handle_lock:
            handle, self._handle = self._handle, None
        if handle not in (None, 0, ctypes.c_void_p(-1).value):
            ctypes.windll.kernel32.CloseHandle(handle)

    def _remove_known_tree(self, path: str) -> None:
        prefix = path.rstrip("\\/") + os.sep
        self._known_dirs = {item for item in self._known_dirs if item != path and not item.startswith(prefix)}

    def _run(self) -> None:
        if os.name != "nt":
            raise RuntimeError("ReadDirectoryChangesW is available only on Windows")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        create_file.restype = ctypes.c_void_p
        read_changes = kernel32.ReadDirectoryChangesW
        read_changes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_void_p]
        read_changes.restype = ctypes.c_int

        handle = create_file(
            self.root,
            0x0001,
            0x00000001 | 0x00000002 | 0x00000004,
            None,
            3,
            0x02000000 | 0x40000000,
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        with self._handle_lock:
            self._handle = handle
        self._known_dirs = {os.path.abspath(path) for path, _dirs, _files in os.walk(self.root)}
        self._mark_ready()
        notify_filter = 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008 | 0x00000010 | 0x00000040
        buffer = ctypes.create_string_buffer(64 * 1024)
        pending_old: tuple[str, bool] | None = None
        try:
            while not self._stop_event.is_set():
                returned = ctypes.c_uint32()
                ok = read_changes(handle, buffer, len(buffer), True, notify_filter, ctypes.byref(returned), None, None)
                if not ok:
                    if self._stop_event.is_set():
                        break
                    raise ctypes.WinError(ctypes.get_last_error())
                for action, relative in parse_notifications(buffer.raw[: returned.value]):
                    path = os.path.abspath(os.path.join(self.root, relative))
                    was_directory = path in self._known_dirs
                    if pending_old and action not in {FILE_ACTION_RENAMED_OLD_NAME, FILE_ACTION_RENAMED_NEW_NAME}:
                        old_path, old_was_directory = pending_old
                        if old_was_directory:
                            self._remove_known_tree(old_path)
                        self.emit(FilesystemChange(path=old_path, kind="deleted", is_directory=old_was_directory))
                        pending_old = None
                    if action == FILE_ACTION_RENAMED_OLD_NAME:
                        if pending_old:
                            old_path, old_was_directory = pending_old
                            if old_was_directory:
                                self._remove_known_tree(old_path)
                            self.emit(FilesystemChange(path=old_path, kind="deleted", is_directory=old_was_directory))
                        pending_old = (path, was_directory)
                        continue
                    if action == FILE_ACTION_RENAMED_NEW_NAME:
                        old_path, old_was_directory = pending_old or ("", False)
                        is_directory = old_was_directory or os.path.isdir(path)
                        if old_path:
                            self._remove_known_tree(old_path)
                        if is_directory:
                            self._known_dirs.update(os.path.abspath(item) for item, _dirs, _files in os.walk(path))
                        self.emit(FilesystemChange(path=path, old_path=old_path, kind="moved", is_directory=is_directory))
                        pending_old = None
                        continue
                    is_directory = was_directory or os.path.isdir(path)
                    if action == FILE_ACTION_ADDED:
                        kind = "created"
                        if is_directory:
                            self._known_dirs.add(path)
                    elif action == FILE_ACTION_REMOVED:
                        kind = "deleted"
                        if was_directory:
                            self._remove_known_tree(path)
                    else:
                        kind = "modified"
                    self.emit(FilesystemChange(path=path, kind=kind, is_directory=is_directory))
        finally:
            self._wake()
