from __future__ import annotations

import threading
import time
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..storage.tasks import update_task_state
from ..Services.debrid.identifiers import first_identifier, normalize_identifier


@dataclass
class Task:
    id: str
    title: str
    magnet: str
    task_dir: str
    owner: str = ""
    owner_user_id: str = ""
    source: str = "debrid"  # "debrid", "soulseek", or "youtube"

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

    # Provider-neutral debrid fields.
    debrid_provider: str = ""
    debrid_task_id: Optional[str] = None
    debrid_selected_file_ids: List[str] = field(default_factory=list)
    debrid_files: List[Dict[str, Any]] = field(default_factory=list)

    # YouTube format/download statuses.
    youtube_files: List[Dict[str, Any]] = field(default_factory=list)
    source_url: str = ""
    origin_client_id: str = ""

    created: float = field(default_factory=time.time)
    state: str = "queued"
    message: str = ""
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

    def __post_init__(self) -> None:
        # ``owner`` was the historic username field. Keep it mirrored while
        # old task state remains readable, but make ownership authoritative by
        # immutable ID from this point forward.
        canonical = str(self.owner_user_id or self.owner or "").strip()
        self.owner_user_id = canonical
        self.owner = canonical


TASKS: Dict[str, Task] = {}
TASKS_LOCK = threading.Lock()
_soulseek_service_provider: Callable[[str], Any] = lambda _user_id: None
_retry_worker_provider: Callable[[str], Optional[Callable[[str], None]]] = lambda source: None
_completion_notifier: Callable[[Task], None] = lambda task: None


def configure_task_manager(
    *,
    soulseek_service_provider: Optional[Callable[[str], Any]] = None,
    retry_worker_provider: Optional[Callable[[str], Optional[Callable[[str], None]]]] = None,
    completion_notifier: Optional[Callable[[Task], None]] = None,
) -> None:
    global _soulseek_service_provider, _retry_worker_provider, _completion_notifier
    if soulseek_service_provider is not None:
        _soulseek_service_provider = soulseek_service_provider
    if retry_worker_provider is not None:
        _retry_worker_provider = retry_worker_provider
    if completion_notifier is not None:
        _completion_notifier = completion_notifier


def _soulseek_service_for_task(task: Task) -> Any:
    try:
        return _soulseek_service_provider(str(getattr(task, "owner_user_id", "") or ""))
    except TypeError:
        # Compatibility for integrations that have not yet accepted user IDs.
        return _soulseek_service_provider()  # type: ignore[call-arg]


def set_task(task_id: str, **kwargs: Any) -> None:
    changed = None
    completed = False
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        previous_state = str(getattr(t, "state", "") or "")
        for k, v in kwargs.items():
            setattr(t, k, v)
        completed = previous_state != "done" and str(getattr(t, "state", "") or "") == "done"
        changed = t
    if changed is not None:
        update_task_state(changed)
        if completed:
            try:
                _completion_notifier(changed)
            except Exception:
                pass


def get_task(task_id: str) -> Optional[Task]:
    with TASKS_LOCK:
        return TASKS.get(task_id)


def list_tasks() -> List[Task]:
    with TASKS_LOCK:
        return sorted(TASKS.values(), key=lambda x: x.created, reverse=True)


def list_tasks_for_user(user_id: str) -> List[Task]:
    clean_user_id = str(user_id or "").strip()
    with TASKS_LOCK:
        return sorted(
            [t for t in TASKS.values() if str(getattr(t, "owner_user_id", "") or "").strip() == clean_user_id],
            key=lambda x: x.created,
            reverse=True,
        )


def task_belongs_to_user(task_id: str, user_id: str) -> bool:
    clean_user_id = str(user_id or "").strip()
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        return bool(t and str(getattr(t, "owner_user_id", "") or "").strip() == clean_user_id)


# Compatibility imports for third-party task workers. Application request
# routes use the explicit immutable-ID helpers above.
list_tasks_for_owner = list_tasks_for_user
task_belongs_to_owner = task_belongs_to_user


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
        src = (t.source or "debrid").lower()

    if src == "soulseek":
        svc = _soulseek_service_for_task(t)
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
        src = (t.source or "debrid").lower()

    if src == "soulseek":
        svc = _soulseek_service_for_task(t)
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
        src = (t.source or "debrid").lower()

    if src == "soulseek":
        svc = _soulseek_service_for_task(t)
        if svc:
            try:
                svc.resume_task(task_id)
            except Exception:
                pass
    return True


def _get_file_control(task_id: str, file_id: str) -> Dict[str, Any]:
    task_id = normalize_identifier(task_id) or ""
    file_id = normalize_identifier(file_id) or ""
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return {}
        ctl = t.file_controls.get(file_id) if isinstance(t.file_controls, dict) else None
        return dict(ctl or {})


def _set_file_control(task_id: str, file_id: str, **kwargs: Any) -> None:
    task_id = normalize_identifier(task_id) or ""
    file_id = normalize_identifier(file_id) or ""
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
    task_id = normalize_identifier(task_id) or ""
    normalized_file_id = normalize_identifier(file_id)
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        lst = getattr(t, which, None)
        if not isinstance(lst, list):
            return
        for f in lst:
            try:
                if first_identifier(f, "file_id", "id") == normalized_file_id:
                    f.update(kwargs)
                    break
            except Exception:
                continue


def task_file_action(task_id: str, file_id: str, action: str) -> bool:
    action = (action or "").strip().lower()
    task_id = normalize_identifier(task_id) or ""
    file_id = normalize_identifier(file_id) or ""
    if not task_id or not file_id or action not in {"pause", "resume", "cancel", "retry"}:
        return False

    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        src = (t.source or "debrid").lower()

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

        svc = _soulseek_service_for_task(t)
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

    file_list_name = "debrid_files" if src == "debrid" else "youtube_files"
    if action == "pause":
        _set_file_control(task_id, file_id, paused=True, canceled=False)
        _update_task_file_entry(task_id, file_list_name, file_id, paused=True, state="paused")
        return True
    if action == "resume":
        _set_file_control(task_id, file_id, paused=False)
        _update_task_file_entry(task_id, file_list_name, file_id, paused=False)
        return True
    if action == "cancel":
        _set_file_control(task_id, file_id, canceled=True)
        _update_task_file_entry(task_id, file_list_name, file_id, canceled=True, state="canceled")
        return True
    if action == "retry":
        _set_file_control(task_id, file_id, paused=False, canceled=False)
        _update_task_file_entry(task_id, file_list_name, file_id, paused=False, canceled=False, done=0, speed=0.0, error="", state="queued")
        with TASKS_LOCK:
            t = TASKS.get(task_id)
            st = (t.state or "").lower() if t else ""
            src2 = (t.source or "debrid").lower() if t else "debrid"
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
        "debrid_provider": getattr(t, "debrid_provider", ""),
        "debrid_task_id": getattr(t, "debrid_task_id", None),
        "source": t.source,
        "origin_client_id": getattr(t, "origin_client_id", ""),
        "overall_done": int(t.overall_done or 0),
        "overall_total": (int(t.overall_total) if t.overall_total is not None else None),
        "slsk_user": t.slsk_user,
        "slsk_directory": t.slsk_directory,
        "slsk_files": _redact_paths(list(t.slsk_files or [])),
        "debrid_files": _redact_paths(list(getattr(t, "debrid_files", []) or [])),
        "youtube_files": _redact_paths(list(getattr(t, "youtube_files", []) or [])),
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

    src = "debrid"
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return False
        src = (t.source or "debrid").lower()
        if t.state not in ("done", "error", "canceled"):
            try:
                t.cancel_event.set()
            except Exception:
                pass
        TASKS.pop(task_id, None)

    if src == "soulseek":
        svc = _soulseek_service_for_task(t)
        if svc:
            try:
                svc.abort_task(task_id)
            except Exception:
                pass

    return True


def clear_all_tasks(user_id: str | None = None) -> None:
    slsk_tasks: List[Task] = []
    clean_user_id = str(user_id or "").strip()
    with TASKS_LOCK:
        for t in list(TASKS.values()):
            if user_id is not None and str(getattr(t, "owner_user_id", "") or "").strip() != clean_user_id:
                continue
            if t.state not in ("done", "error", "canceled"):
                try:
                    t.cancel_event.set()
                except Exception:
                    pass
            if (t.source or "").lower() == "soulseek":
                slsk_tasks.append(t)
            TASKS.pop(t.id, None)

    if slsk_tasks:
        for task in slsk_tasks:
            svc = _soulseek_service_for_task(task)
            if svc:
                try:
                    svc.abort_task(task.id)
                except Exception:
                    pass
