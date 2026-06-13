from __future__ import annotations

import threading
import time
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Task:
    id: str
    title: str
    magnet: str
    task_dir: str
    owner: str = ""
    source: str = "rd"  # "rd", "soulseek", or "youtube"

    # Pause control (set pause_event to pause; clear to resume)
    paused: bool = False
    pause_event: threading.Event = field(default_factory=threading.Event)
    pre_pause_state: str = ""
    pre_pause_message: str = ""

    # Per-file control flags (file_id -> {"paused":bool, "canceled":bool})
    file_controls: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    overall_done: int = 0
    overall_total: Optional[int] = None

    # Soulseek task fields
    slsk_user: str = ""
    slsk_directory: str = ""
    slsk_files: List[Dict[str, Any]] = field(default_factory=list)

    # Real-Debrid per-file statuses
    rd_files: List[Dict[str, Any]] = field(default_factory=list)

    created: float = field(default_factory=time.time)
    state: str = "queued"
    message: str = ""
    torrent_id: Optional[str] = None
    rd_selected_file_ids: List[int] = field(default_factory=list)
    downloaded_files: List[str] = field(default_factory=list)
    current_file: str = ""
    current_done: int = 0
    current_total: Optional[int] = None

    # Video auto transcode (download time) status
    video_post_total: int = 0
    video_post_done: int = 0
    video_post_state: str = ""
    video_post_message: str = ""
    video_post_current_file: str = ""
    video_post_current_done: int = 0
    video_post_current_total: Optional[int] = None

    downloads_complete: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)


TASKS: Dict[str, Task] = {}
TASKS_LOCK = threading.Lock()
_soulseek_service_provider: Callable[[], Any] = lambda: None
_retry_worker_provider: Callable[[str], Optional[Callable[[str], None]]] = lambda source: None


def configure_task_manager(
    *,
    soulseek_service_provider: Optional[Callable[[], Any]] = None,
    retry_worker_provider: Optional[Callable[[str], Optional[Callable[[str], None]]]] = None,
) -> None:
    global _soulseek_service_provider, _retry_worker_provider
    if soulseek_service_provider is not None:
        _soulseek_service_provider = soulseek_service_provider
    if retry_worker_provider is not None:
        _retry_worker_provider = retry_worker_provider


def set_task(task_id: str, **kwargs: Any) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        for k, v in kwargs.items():
            setattr(t, k, v)


def get_task(task_id: str) -> Optional[Task]:
    with TASKS_LOCK:
        return TASKS.get(task_id)


def list_tasks() -> List[Task]:
    with TASKS_LOCK:
        return sorted(TASKS.values(), key=lambda x: x.created, reverse=True)


def list_tasks_for_owner(owner: str) -> List[Task]:
    clean_owner = str(owner or "").strip()
    with TASKS_LOCK:
        return sorted(
            [t for t in TASKS.values() if str(getattr(t, "owner", "") or "").strip() == clean_owner],
            key=lambda x: x.created,
            reverse=True,
        )


def task_belongs_to_owner(task_id: str, owner: str) -> bool:
    clean_owner = str(owner or "").strip()
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        return bool(t and str(getattr(t, "owner", "") or "").strip() == clean_owner)


def cancel_task(task_id: str) -> bool:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        if t.state in {"done", "error", "canceled"}:
            return True
        t.cancel_event.set()
        t.state = "canceling"
        t.message = "Cancel requested"
        src = (t.source or "rd").lower()

    if src == "soulseek":
        svc = _soulseek_service_provider()
        if svc:
            try:
                svc.abort_task(task_id)
            except Exception:
                pass
    return True


def pause_task(task_id: str) -> bool:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        if t.state in {"done", "canceled"}:
            return True
        if not t.paused:
            t.paused = True
            t.pause_event.set()
            t.pre_pause_state = t.state or ""
            t.pre_pause_message = t.message or ""
            t.state = "paused"
            t.message = "Paused"
        src = (t.source or "rd").lower()

    if src == "soulseek":
        svc = _soulseek_service_provider()
        if svc:
            try:
                svc.pause_task(task_id)
            except Exception:
                pass
    return True


def resume_task(task_id: str) -> bool:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        if not t.paused:
            return True
        t.paused = False
        t.pause_event.clear()
        prev_state = (t.pre_pause_state or "").strip()
        prev_msg = (t.pre_pause_message or "").strip()
        if t.state == "paused":
            t.state = prev_state if prev_state and prev_state != "paused" else "downloading"
            t.message = prev_msg if prev_msg else "Resumed"
        src = (t.source or "rd").lower()

    if src == "soulseek":
        svc = _soulseek_service_provider()
        if svc:
            try:
                svc.resume_task(task_id)
            except Exception:
                pass
    return True


def _get_file_control(task_id: str, file_id: str) -> Dict[str, Any]:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return {}
        ctl = t.file_controls.get(file_id) if isinstance(t.file_controls, dict) else None
        return dict(ctl or {})


def _set_file_control(task_id: str, file_id: str, **kwargs: Any) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        if not isinstance(t.file_controls, dict):
            t.file_controls = {}
        cur = t.file_controls.get(file_id) or {}
        if not isinstance(cur, dict):
            cur = {}
        cur.update(kwargs)
        t.file_controls[file_id] = cur


def _update_task_file_entry(task_id: str, which: str, file_id: str, **kwargs: Any) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        lst = getattr(t, which, None)
        if not isinstance(lst, list):
            return
        for f in lst:
            try:
                if str(f.get("file_id") or "") == str(file_id):
                    f.update(kwargs)
                    break
            except Exception:
                continue


def task_file_action(task_id: str, file_id: str, action: str) -> bool:
    action = (action or "").strip().lower()
    if not task_id or not file_id or action not in {"pause", "resume", "cancel", "retry"}:
        return False

    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        src = (t.source or "rd").lower()

    if src == "soulseek":
        if action == "pause":
            _set_file_control(task_id, file_id, paused=True, canceled=False)
            _update_task_file_entry(task_id, "slsk_files", file_id, paused=True, state="paused")
        elif action == "resume":
            _set_file_control(task_id, file_id, paused=False)
            _update_task_file_entry(task_id, "slsk_files", file_id, paused=False)
        elif action == "cancel":
            _set_file_control(task_id, file_id, canceled=True)
            _update_task_file_entry(task_id, "slsk_files", file_id, canceled=True, state="canceled")
        elif action == "retry":
            _set_file_control(task_id, file_id, paused=False, canceled=False)
            _update_task_file_entry(task_id, "slsk_files", file_id, paused=False, canceled=False, done=0, speed=0.0, error="", state="queued")

        svc = _soulseek_service_provider()
        if svc:
            try:
                if action == "pause":
                    svc.pause_file(task_id, file_id)
                elif action == "resume":
                    svc.resume_file(task_id, file_id)
                elif action == "cancel":
                    svc.cancel_file(task_id, file_id)
                elif action == "retry":
                    svc.retry_file(task_id, file_id)
            except Exception:
                pass
        return True

    if action == "pause":
        _set_file_control(task_id, file_id, paused=True, canceled=False)
        _update_task_file_entry(task_id, "rd_files", file_id, paused=True, state="paused")
        return True
    if action == "resume":
        _set_file_control(task_id, file_id, paused=False)
        _update_task_file_entry(task_id, "rd_files", file_id, paused=False)
        return True
    if action == "cancel":
        _set_file_control(task_id, file_id, canceled=True)
        _update_task_file_entry(task_id, "rd_files", file_id, canceled=True, state="canceled")
        return True
    if action == "retry":
        _set_file_control(task_id, file_id, paused=False, canceled=False)
        _update_task_file_entry(task_id, "rd_files", file_id, paused=False, canceled=False, done=0, speed=0.0, error="", state="queued")
        with TASKS_LOCK:
            t = TASKS.get(task_id)
            st = (t.state or "").lower() if t else ""
            src2 = (t.source or "rd").lower() if t else "rd"
        if st in {"done", "error", "canceled"}:
            target = _retry_worker_provider(src2)
            if target:
                th = threading.Thread(target=target, args=(task_id,), daemon=True)
                th.start()
        return True

    return False


def _json_safe(v: Any, depth: int = 0) -> Any:
    if depth > 6:
        return str(v)
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple, set)):
        return [_json_safe(x, depth + 1) for x in list(v)]
    if isinstance(v, dict):
        out: Dict[str, Any] = {}
        for k, val in v.items():
            try:
                ks = str(k)
            except Exception:
                ks = "key"
            out[ks] = _json_safe(val, depth + 1)
        return out
    try:
        return str(v)
    except Exception:
        return "<?>"


_PATH_FIELD_NAMES = {"task_dir", "local_path", "incoming_path", "out_path", "path", "abs_path"}


def _display_path(value: Any) -> str:
    s = str(value or "")
    if not s:
        return ""
    return os.path.basename(s.rstrip("\\/")) or s


def _redact_paths(v: Any, depth: int = 0) -> Any:
    if depth > 6:
        return _json_safe(v, depth)
    if isinstance(v, list):
        return [_redact_paths(x, depth + 1) for x in v]
    if isinstance(v, dict):
        out: Dict[str, Any] = {}
        for k, val in v.items():
            key = str(k)
            if key in _PATH_FIELD_NAMES:
                out[key] = _display_path(val)
            else:
                out[key] = _redact_paths(val, depth + 1)
        return out
    return _json_safe(v, depth)


def task_public_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "task_dir": _display_path(t.task_dir),
        "created": t.created,
        "paused": bool(getattr(t, "paused", False)),
        "state": t.state,
        "message": t.message,
        "torrent_id": t.torrent_id,
        "source": t.source,
        "overall_done": int(t.overall_done or 0),
        "overall_total": (int(t.overall_total) if t.overall_total is not None else None),
        "slsk_user": t.slsk_user,
        "slsk_directory": t.slsk_directory,
        "slsk_files": _redact_paths(list(t.slsk_files or [])),
        "rd_files": _redact_paths(list(getattr(t, "rd_files", []) or [])),
        "downloaded_files": [_display_path(p) for p in list(t.downloaded_files or [])],
        "current_file": _display_path(t.current_file),
        "current_done": int(t.current_done or 0),
        "current_total": (int(t.current_total) if t.current_total is not None else None),
        "video_post_total": int(t.video_post_total or 0),
        "video_post_done": int(t.video_post_done or 0),
        "video_post_state": t.video_post_state,
        "video_post_message": t.video_post_message,
        "video_post_current_file": _display_path(t.video_post_current_file),
        "video_post_current_done": int(t.video_post_current_done or 0),
        "video_post_current_total": (int(t.video_post_current_total) if t.video_post_current_total is not None else None),
        "downloads_complete": bool(t.downloads_complete),
    }


def clear_task(task_id: str) -> bool:
    task_id = (task_id or "").strip()
    if not task_id:
        return False

    src = "rd"
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        src = (t.source or "rd").lower()
        if t.state not in ("done", "error", "canceled"):
            try:
                t.cancel_event.set()
            except Exception:
                pass
        TASKS.pop(task_id, None)

    if src == "soulseek":
        svc = _soulseek_service_provider()
        if svc:
            try:
                svc.abort_task(task_id)
            except Exception:
                pass

    return True


def clear_all_tasks(owner: str | None = None) -> None:
    slsk_ids: List[str] = []
    clean_owner = str(owner or "").strip()
    with TASKS_LOCK:
        for t in list(TASKS.values()):
            if owner is not None and str(getattr(t, "owner", "") or "").strip() != clean_owner:
                continue
            if t.state not in ("done", "error", "canceled"):
                try:
                    t.cancel_event.set()
                except Exception:
                    pass
            if (t.source or "").lower() == "soulseek":
                slsk_ids.append(t.id)
            TASKS.pop(t.id, None)

    if slsk_ids:
        svc = _soulseek_service_provider()
        if svc:
            for tid in slsk_ids:
                try:
                    svc.abort_task(tid)
                except Exception:
                    pass
