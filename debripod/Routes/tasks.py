from __future__ import annotations

import time
import os
from typing import List

from flask import jsonify, request, session

from ..Tasks.manager import (
    cancel_task,
    clear_all_tasks,
    clear_task,
    list_tasks_for_owner,
    pause_task,
    resume_task,
    task_belongs_to_owner,
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
    def current_owner() -> str:
        return str(session.get("username") or "").strip()

    def owns_task(task_id: str) -> bool:
        return task_belongs_to_owner(task_id, current_owner())

    @app.route("/api/tasks", methods=["GET"])
    def api_tasks_list():
        out: List[dict] = []
        for t in list_tasks_for_owner(current_owner()):
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
        return jsonify({"tasks": out})

    @app.route("/api/tasks/pause", methods=["POST"])
    def api_tasks_pause():
        data = request.get_json(silent=True) or {}
        task_id = (data.get("task_id") or "").strip()
        if not owns_task(task_id):
            return jsonify({"ok": False}), 404
        ok = pause_task(task_id)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/resume", methods=["POST"])
    def api_tasks_resume():
        data = request.get_json(silent=True) or {}
        task_id = (data.get("task_id") or "").strip()
        if not owns_task(task_id):
            return jsonify({"ok": False}), 404
        ok = resume_task(task_id)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/file_action", methods=["POST"])
    def api_tasks_file_action():
        data = request.get_json(silent=True) or {}
        task_id = (data.get("task_id") or "").strip()
        file_id = (data.get("file_id") or "").strip()
        action = (data.get("action") or "").strip()
        if not owns_task(task_id):
            return jsonify({"ok": False}), 404
        ok = task_file_action(task_id, file_id, action)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/cancel", methods=["POST"])
    def api_tasks_cancel():
        data = request.get_json(silent=True) or {}
        tid = (data.get("task_id") or request.form.get("task_id") or "").strip()
        if not tid:
            return jsonify({"ok": False, "error": "missing task_id"}), 400
        if not owns_task(tid):
            return jsonify({"ok": False}), 404
        ok = bool(cancel_task(tid))
        return jsonify({"ok": ok})

    @app.route("/api/tasks/clear", methods=["POST"])
    def api_tasks_clear():
        data = request.get_json(silent=True) or {}
        tid = (data.get("task_id") or request.form.get("task_id") or "").strip()
        if not tid:
            return jsonify({"ok": False, "error": "missing task_id"}), 400
        if not owns_task(tid):
            return jsonify({"ok": False}), 404
        ok = bool(clear_task(tid))
        return jsonify({"ok": ok})

    @app.route("/api/tasks/clear_all", methods=["POST"])
    def api_tasks_clear_all():
        clear_all_tasks(current_owner())
        return jsonify({"ok": True})
