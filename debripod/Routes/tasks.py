from __future__ import annotations

import time
import os
import asyncio
import threading
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
    restart_task_attempt,
    task_belongs_to_user,
    task_file_action,
    task_public_dict,
)
from ..storage.tasks import save_task_metadata
from ..user_runtime import user_runtime_for
from ..Library.roots import root_objects


def _task_library_nav(task, user_id: str) -> dict:
    raw_task_dir = str(getattr(task, "task_dir", "") or "").strip()
    if not raw_task_dir:
        return {"root_id": "", "rel": "", "label": "Open library location", "available": False}
    task_dir = os.path.realpath(os.path.abspath(raw_task_dir))
    matches = []
    for root in root_objects(user_id):
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
                payload["library_nav"] = _task_library_nav(t, current_user_id(request))
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

    async def api_tasks_restart(request: web.Request):
        data = await request.json()
        task_id = (data.get("task_id") or "").strip()
        if not task_id:
            return json_response({"ok": False, "error": "missing task_id"}, status=400)
        if not owns_task(request, task_id):
            return json_response({"ok": False}, status=404)
        attempt = restart_task_attempt(task_id)
        if attempt is None:
            return json_response({"ok": False, "error": "Only an inactive task can be restarted."}, status=409)
        try:
            if attempt.task_dir:
                os.makedirs(attempt.task_dir, exist_ok=True)
            files = attempt.slsk_files if attempt.source == "soulseek" else (attempt.youtube_files if attempt.source == "youtube" else attempt.debrid_files)
            save_task_metadata(
                attempt, original_result_title=attempt.title, remote_files=files,
                selected_file_ids=(attempt.debrid_selected_file_ids or [item.get("file_id") for item in files if isinstance(item, dict)]),
            )
            source = str(attempt.source or "").lower()
            if source == "debrid":
                from ..runtime_debrid_downloads import worker
                asyncio.create_task(worker(attempt.id), name=f"debrid-restart:{attempt.id}")
            elif source == "youtube":
                from ..runtime_youtube_downloads import youtube_worker
                threading.Thread(target=youtube_worker, args=(attempt.id,), daemon=True).start()
            elif source == "soulseek":
                service = user_runtime_for(request).soulseek_service
                if service is None or not service.is_ready():
                    raise RuntimeError("Soulseek is not connected for this account.")
                paths = [str(item.get("remote_path") or "") for item in attempt.slsk_files if isinstance(item, dict)]
                await service.enqueue_downloads_async(attempt.id, attempt.slsk_user, paths)
            else:
                raise RuntimeError("This task source cannot be restarted.")
        except Exception as exc:
            from ..Tasks.manager import set_task
            set_task(attempt.id, state="error", message=str(exc)[:300] or "Task restart failed")
            return json_response({"ok": False, "error": "Task restart failed", "task_id": attempt.id}, status=400)
        return json_response({"ok": True, "task_id": attempt.id, "attempt": attempt.attempt})

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
    app.router.add_post("/api/tasks/restart", api_tasks_restart)
    app.router.add_post("/api/tasks/clear", api_tasks_clear)
    app.router.add_post("/api/tasks/clear_all", api_tasks_clear_all)
