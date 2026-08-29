from __future__ import annotations

import ctypes
import ctypes.util
import os
import threading

from .base import FilesystemChange, NativeWatcher
from .bsd import KqueueWatcher


FSEVENT_MUST_SCAN = 0x00000001 | 0x00000002 | 0x00000004
FSEVENT_ITEM_CREATED = 0x00000100
FSEVENT_ITEM_REMOVED = 0x00000200
FSEVENT_ITEM_RENAMED = 0x00000800
FSEVENT_ITEM_MODIFIED = 0x00001000 | 0x00002000 | 0x00004000 | 0x00008000
FSEVENT_ITEM_IS_DIR = 0x00020000
FSEVENT_CREATE_FLAGS = 0x00000002 | 0x00000008 | 0x00000010


class _FSEventStreamContext(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_long),
        ("info", ctypes.c_void_p),
        ("retain", ctypes.c_void_p),
        ("release", ctypes.c_void_p),
        ("copy_description", ctypes.c_void_p),
    ]


class FSEventsWatcher(NativeWatcher):
    def __init__(self, root, callback):
        super().__init__(root, callback)
        self._run_loop = None
        self._core_foundation = None
        self._loop_lock = threading.Lock()
        self._callback_ref = None

    def _wake(self) -> None:
        with self._loop_lock:
            run_loop = self._run_loop
            core = self._core_foundation
        if run_loop and core:
            core.CFRunLoopStop(run_loop)

    def _run(self) -> None:
        if os.sys.platform != "darwin":
            raise RuntimeError("FSEvents is available only on macOS")
        core = ctypes.CDLL(ctypes.util.find_library("CoreFoundation") or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        services = ctypes.CDLL(ctypes.util.find_library("CoreServices") or "/System/Library/Frameworks/CoreServices.framework/CoreServices")
        self._core_foundation = core
        callback_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint64))

        def receive(_stream, _info, count, paths, flags, _ids):
            for index in range(int(count)):
                path = os.fsdecode(paths[index])
                flag = int(flags[index])
                if flag & FSEVENT_MUST_SCAN:
                    self.emit(FilesystemChange(path=self.root, kind="overflow", is_directory=True))
                    continue
                if flag & FSEVENT_ITEM_CREATED:
                    kind = "created"
                elif flag & FSEVENT_ITEM_REMOVED:
                    kind = "deleted"
                elif flag & FSEVENT_ITEM_RENAMED:
                    kind = "moved"
                else:
                    kind = "modified"
                self.emit(FilesystemChange(path=path, kind=kind, is_directory=bool(flag & FSEVENT_ITEM_IS_DIR)))

        self._callback_ref = callback_type(receive)
        core.CFStringCreateWithCString.restype = ctypes.c_void_p
        core.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        core.CFArrayCreate.restype = ctypes.c_void_p
        core.CFArrayCreate.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_long, ctypes.c_void_p]
        core.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        core.CFRunLoopGetCurrent.argtypes = []
        core.CFRunLoopRun.restype = None
        core.CFRunLoopRun.argtypes = []
        core.CFRunLoopStop.restype = None
        core.CFRunLoopStop.argtypes = [ctypes.c_void_p]
        core.CFRelease.restype = None
        core.CFRelease.argtypes = [ctypes.c_void_p]
        services.FSEventStreamCreate.restype = ctypes.c_void_p
        services.FSEventStreamCreate.argtypes = [
            ctypes.c_void_p,
            callback_type,
            ctypes.POINTER(_FSEventStreamContext),
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_double,
            ctypes.c_uint32,
        ]
        services.FSEventStreamScheduleWithRunLoop.restype = None
        services.FSEventStreamScheduleWithRunLoop.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        services.FSEventStreamStart.restype = ctypes.c_bool
        services.FSEventStreamStart.argtypes = [ctypes.c_void_p]
        services.FSEventStreamStop.restype = None
        services.FSEventStreamStop.argtypes = [ctypes.c_void_p]
        services.FSEventStreamInvalidate.restype = None
        services.FSEventStreamInvalidate.argtypes = [ctypes.c_void_p]
        services.FSEventStreamRelease.restype = None
        services.FSEventStreamRelease.argtypes = [ctypes.c_void_p]
        root_string = core.CFStringCreateWithCString(None, os.fsencode(self.root), 0x08000100)
        values = (ctypes.c_void_p * 1)(root_string)
        paths = core.CFArrayCreate(None, values, 1, None)
        context = _FSEventStreamContext(0, None, None, None, None)
        stream = services.FSEventStreamCreate(None, self._callback_ref, ctypes.byref(context), paths, ctypes.c_uint64(-1).value, 0.25, FSEVENT_CREATE_FLAGS)
        if not stream:
            raise RuntimeError("FSEventStreamCreate failed")
        run_loop = core.CFRunLoopGetCurrent()
        with self._loop_lock:
            self._run_loop = run_loop
        default_mode = ctypes.c_void_p.in_dll(core, "kCFRunLoopDefaultMode").value
        started = False
        try:
            services.FSEventStreamScheduleWithRunLoop(stream, run_loop, default_mode)
            started = bool(services.FSEventStreamStart(stream))
            if not started:
                raise RuntimeError("FSEventStreamStart failed")
            self._mark_ready()
            core.CFRunLoopRun()
        finally:
            if started:
                services.FSEventStreamStop(stream)
            services.FSEventStreamInvalidate(stream)
            services.FSEventStreamRelease(stream)
            core.CFRelease(paths)
            core.CFRelease(root_string)
            with self._loop_lock:
                self._run_loop = None


class DarwinWatcher(NativeWatcher):
    """Use FSEvents first and fall back to recursive kqueue if setup fails."""

    def __init__(self, root, callback):
        super().__init__(root, callback)
        self._delegate: NativeWatcher | None = None

    @property
    def running(self) -> bool:
        return bool(self._delegate and self._delegate.running)

    def start(self) -> None:
        primary = FSEventsWatcher(self.root, self.callback)
        try:
            primary.start()
            self._delegate = primary
        except Exception:
            fallback = KqueueWatcher(self.root, self.callback)
            fallback.start()
            self._delegate = fallback

    def stop(self) -> None:
        if self._delegate:
            self._delegate.stop()
        self._delegate = None

    def _run(self) -> None:
        raise NotImplementedError
