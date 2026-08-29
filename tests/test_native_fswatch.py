from __future__ import annotations

import os
import struct
import sys
import threading
import time

import pytest

from debripod.Library import index as library_index
from debripod.Library.fswatch import FilesystemChange, create_watcher
from debripod.Library.fswatch.base import NativeWatcher
from debripod.Library.fswatch.bsd import KqueueWatcher
from debripod.Library.fswatch.darwin import DarwinWatcher
from debripod.Library.fswatch.linux import IN_CREATE, IN_ISDIR, IN_Q_OVERFLOW, InotifyWatcher, parse_events
from debripod.Library.fswatch.windows import FILE_ACTION_ADDED, FILE_ACTION_RENAMED_NEW_NAME, WindowsWatcher, parse_notifications


def _windows_record(action: int, name: str, next_offset: int = 0) -> bytes:
    encoded = name.encode("utf-16-le")
    return struct.pack("<III", next_offset, action, len(encoded)) + encoded


def test_windows_notification_parser_handles_multiple_records():
    first = _windows_record(FILE_ACTION_ADDED, "nested")
    padding = (-len(first)) % 4
    first = _windows_record(FILE_ACTION_ADDED, "nested", len(first) + padding) + (b"\0" * padding)
    payload = first + _windows_record(FILE_ACTION_RENAMED_NEW_NAME, "nested\\track.mp3")
    assert list(parse_notifications(payload)) == [
        (FILE_ACTION_ADDED, "nested"),
        (FILE_ACTION_RENAMED_NEW_NAME, "nested\\track.mp3"),
    ]


def test_inotify_parser_preserves_directory_and_overflow_flags():
    name = b"album\0" + (b"\0" * 2)
    payload = struct.pack("iIII", 4, IN_CREATE | IN_ISDIR, 8, len(name)) + name
    payload += struct.pack("iIII", -1, IN_Q_OVERFLOW, 0, 0)
    assert list(parse_events(payload)) == [
        (4, IN_CREATE | IN_ISDIR, 8, "album"),
        (-1, IN_Q_OVERFLOW, 0, ""),
    ]


def test_platform_factory_selects_native_backends(tmp_path):
    callback = lambda _change: None
    assert isinstance(create_watcher(str(tmp_path), callback, platform_name="win32"), WindowsWatcher)
    assert isinstance(create_watcher(str(tmp_path), callback, platform_name="linux"), InotifyWatcher)
    assert isinstance(create_watcher(str(tmp_path), callback, platform_name="darwin"), DarwinWatcher)
    assert isinstance(create_watcher(str(tmp_path), callback, platform_name="freebsd13"), KqueueWatcher)


def test_change_schema_rejects_unknown_kinds():
    assert FilesystemChange(path="x", old_path="y", kind="moved").old_path == "y"
    with pytest.raises(ValueError):
        FilesystemChange(path="x", kind="polled")


def test_watcher_start_fails_if_backend_never_becomes_ready(tmp_path):
    class StalledWatcher(NativeWatcher):
        STARTUP_TIMEOUT_SECONDS = 0.01

        def _run(self):
            self._stop_event.wait()

    watcher = StalledWatcher(str(tmp_path), lambda _change: None)
    with pytest.raises(TimeoutError, match="did not become ready"):
        watcher.start()
    assert not watcher.running


def test_shutdown_cancels_and_joins_inflight_reconciliation(monkeypatch, tmp_path):
    started = threading.Event()
    exited = threading.Event()

    def slow_build(_root, *, cancel_event=None, **_kwargs):
        started.set()
        try:
            assert cancel_event is not None
            cancel_event.wait(5)
            return {"tracks": [], "videos": [], "video_records": []}
        finally:
            exited.set()

    monkeypatch.setattr(library_index, "build_index_for_root", slow_build)
    root_id = "shutdown-regression"
    library_index.ensure_index_async(root_id, str(tmp_path), force=True)
    assert started.wait(1)
    library_index.stop_all_index_watchers()
    assert exited.wait(1)
    assert library_index.index_building_status()[1].get(root_id) is False


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows native watcher integration")
def test_windows_subtree_watcher_reports_create_modify_move_delete(tmp_path):
    changes: list[FilesystemChange] = []
    changed = threading.Event()

    def callback(change: FilesystemChange):
        changes.append(change)
        changed.set()

    watcher = create_watcher(str(tmp_path), callback)
    watcher.start()
    try:
        nested = tmp_path / "nested"
        nested.mkdir()
        source = nested / "track.mp3"
        source.write_bytes(b"one")
        source.write_bytes(b"two")
        moved = nested / "renamed.mp3"
        source.rename(moved)
        moved.unlink()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            kinds = {item.kind for item in changes}
            paths = {os.path.basename(item.path) for item in changes}
            if {"created", "modified", "moved", "deleted"}.issubset(kinds) and "renamed.mp3" in paths:
                break
            changed.wait(0.1)
            changed.clear()
        kinds = {item.kind for item in changes}
        assert {"created", "modified", "moved", "deleted"}.issubset(kinds)
        assert any(item.is_directory and os.path.basename(item.path) == "nested" for item in changes)
    finally:
        watcher.stop()
