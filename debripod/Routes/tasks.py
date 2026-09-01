from __future__ import annotations

import time
import os
from typing import List

from aiohttp import web

from ..auth import current_user
from ..factory import json_response

from ..Tasks.manager import (
    cancel_task,
    clear_all_tasks,
    clear_task,
    list_tasks_for_user,
    pause_task,
    resume_task,
    task_belongs_to_user,
    task_file_action,
    task_public_dict,
)
from ..Library.roots import root_objects


def _task_library_nav(task) -> dict:
    raw_task_dir = str(getattr(task, "task_dir", "") or "").strip()
    if not raw_task_dir:
        return {"root_id": "", "rel": "", "label": "Open library location", "available": False}
    task_dir = os.path.realpath(os.path.abspath(raw_task_dir))
    matches = []
    for root in root_objects():
        root_abs = os.path.realpath(os.path.abspath(str(root.get("path") or "")))
        try:
            if root_abs and os.path.commonpath([root_abs, task_dir]) == root_abs:
                matches.append((len(root_abs), root, root_abs))
        except Exception:
            continue
    if not matches:
        return {"root_id": "", "rel": "", "label": "Open library location", "available": False}
    _length, root, root_abs = max(matches, key=lambda item: item[0])
    rel = os.path.relpath(task_dir, root_abs).replace("\\", "/")
    rel = "" if rel == "." else rel.strip("/")
    return {"root_id": str(root.get("id") or ""), "rel": rel, "label": "Open library location", "available": True}


def register_task_routes(app) -> None:
    def current_user_id(request: web.Request) -> str:
        user = current_user(request)
        return str(getattr(user, "user_id", "") or "").strip()

    def owns_task(request: web.Request, task_id: str) -> bool:
        return task_belongs_to_user(task_id, current_user_id(request))

    async def api_tasks_list(request: web.Request):
        out: List[dict] = []
        for t in list_tasks_for_user(current_user_id(request)):
            try:
                payload = task_public_dict(t)
                payload["library_nav"] = _task_library_nav(t)
                out.append(payload)
            except Exception as e:
                try:
                    out.append({
                        "id": getattr(t, "id", ""),
                        "title": getattr(t, "title", "Task"),
                        "task_dir": "",
                        "created": getattr(t, "created", time.time()),
                        "paused": bool(getattr(t, "paused", False)),
                        "state": "error",
                        "message": "Task serialization error",
                        "debrid_provider": getattr(t, "debrid_provider", ""),
                        "debrid_task_id": getattr(t, "debrid_task_id", None),
                        "source": getattr(t, "source", "debrid"),
                        "overall_done": 0,
                        "overall_total": None,
                        "slsk_user": "",
                        "slsk_directory": "",
                        "slsk_files": [],
                        "debrid_files": [],
                        "youtube_files": [],
                        "downloaded_files": [],
                        "current_file": "",
                        "current_done": 0,
                        "current_total": None,
                        "video_post_total": 0,
                        "video_post_done": 0,
                        "video_post_state": "",
                        "video_post_message": "",
                        "video_post_current_file": "",
                        "video_post_current_done": 0,
                        "video_post_current_total": None,
                        "downloads_complete": False,
                    })
                except Exception:
                    continue
        return json_response({"tasks": out})

    async def api_tasks_pause(request: web.Request):
        data = await request.json()
        task_id = (data.get("task_id") or "").strip()
        if not owns_task(request, task_id):
            return json_response({"ok": False}, status=404)
        ok = pause_task(task_id)
        return json_response({"ok": bool(ok)})

    async def api_tasks_resume(request: web.Request):
        data = await request.json()
        task_id = (data.get("task_id") or "").strip()
        if not owns_task(request, task_id):
            return json_response({"ok": False}, status=404)
        ok = resume_task(task_id)
        return json_response({"ok": bool(ok)})

    async def api_tasks_file_action(request: web.Request):
        data = await request.json()
        task_id = (data.get("task_id") or "").strip()
        file_id = (data.get("file_id") or "").strip()
        action = (data.get("action") or "").strip()
        if not owns_task(request, task_id):
            return json_response({"ok": False}, status=404)
        ok = task_file_action(task_id, file_id, action)
        return json_response({"ok": bool(ok)})

    async def api_tasks_cancel(request: web.Request):
        data = await request.json()
        tid = (data.get("task_id") or "").strip()
        if not tid:
            return json_response({"ok": False, "error": "missing task_id"}, status=400)
        if not owns_task(request, tid):
            return json_response({"ok": False}, status=404)
        ok = bool(cancel_task(tid))
        return json_response({"ok": ok})

    async def api_tasks_clear(request: web.Request):
        data = await request.json()
        tid = (data.get("task_id") or "").strip()
        if not tid:
            return json_response({"ok": False, "error": "missing task_id"}, status=400)
        if not owns_task(request, tid):
            return json_response({"ok": False}, status=404)
        ok = bool(clear_task(tid))
        return json_response({"ok": ok})

    async def api_tasks_clear_all(request: web.Request):
        clear_all_tasks(current_user_id(request))
        return json_response({"ok": True})

    app.router.add_get("/api/tasks", api_tasks_list)
    app.router.add_post("/api/tasks/pause", api_tasks_pause)
    app.router.add_post("/api/tasks/resume", api_tasks_resume)
    app.router.add_post("/api/tasks/file_action", api_tasks_file_action)
    app.router.add_post("/api/tasks/cancel", api_tasks_cancel)
    app.router.add_post("/api/tasks/clear", api_tasks_clear)
    app.router.add_post("/api/tasks/clear_all", api_tasks_clear_all)
