from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Task:
    id: str
    title: str
    magnet: str
    task_dir: str
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


def cancel_task(task_id: str) -> bool:
    from ..legacy import cancel_task as legacy_cancel_task

    return legacy_cancel_task(task_id)


def pause_task(task_id: str) -> bool:
    from ..legacy import pause_task as legacy_pause_task

    return legacy_pause_task(task_id)


def resume_task(task_id: str) -> bool:
    from ..legacy import resume_task as legacy_resume_task

    return legacy_resume_task(task_id)
