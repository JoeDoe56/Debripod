from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FilesystemChange:
    path: str
    old_path: str = ""
    kind: str = "modified"
    is_directory: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"created", "deleted", "modified", "moved", "overflow"}:
            raise ValueError(f"unsupported filesystem change kind: {self.kind}")


class NativeWatcher:
    STARTUP_TIMEOUT_SECONDS = 5.0

    def __init__(self, root: str, callback: Callable[[FilesystemChange], None]):
        self.root = os.path.abspath(root)
        self.callback = callback
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._startup_error: Exception | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        if not os.path.isdir(self.root):
            raise FileNotFoundError(self.root)
        self._stop_event.clear()
        self._ready_event.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._run_guarded, daemon=True, name=self.__class__.__name__)
        self._thread.start()
        ready = self._ready_event.wait(timeout=self.STARTUP_TIMEOUT_SECONDS)
        if not ready:
            self.stop()
            raise TimeoutError(
                f"{self.__class__.__name__} did not become ready within "
                f"{self.STARTUP_TIMEOUT_SECONDS:g} seconds"
            )
        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise error

    def stop(self) -> None:
        self._stop_event.set()
        self._wake()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._thread = None

    def _wake(self) -> None:
        pass

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._startup_error = exc
            if not self._stop_event.is_set():
                self.emit(FilesystemChange(path=self.root, kind="overflow", is_directory=True))
        finally:
            self._ready_event.set()

    def _mark_ready(self) -> None:
        self._ready_event.set()

    def _run(self) -> None:
        raise NotImplementedError

    def emit(self, change: FilesystemChange) -> None:
        if self._stop_event.is_set():
            return
        try:
            self.callback(change)
        except Exception:
            pass
