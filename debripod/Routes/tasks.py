from __future__ import annotations

import time
from typing import List

from flask import jsonify, request

from ..Tasks.manager import (
    cancel_task,
    clear_all_tasks,
    clear_task,
    list_tasks,
    pause_task,
    resume_task,
    task_file_action,
    task_public_dict,
)


def register_task_routes(app) -> None:
    @app.route("/api/tasks", methods=["GET"])
    def api_tasks_list():
        out: List[dict] = []
        for t in list_tasks():
            try:
                out.append(task_public_dict(t))
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
                        "torrent_id": getattr(t, "torrent_id", None),
                        "source": getattr(t, "source", "rd"),
                        "overall_done": 0,
                        "overall_total": None,
                        "slsk_user": "",
                        "slsk_directory": "",
                        "slsk_files": [],
                        "rd_files": [],
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
        ok = pause_task(task_id)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/resume", methods=["POST"])
    def api_tasks_resume():
        data = request.get_json(silent=True) or {}
        task_id = (data.get("task_id") or "").strip()
        ok = resume_task(task_id)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/file_action", methods=["POST"])
    def api_tasks_file_action():
        data = request.get_json(silent=True) or {}
        task_id = (data.get("task_id") or "").strip()
        file_id = (data.get("file_id") or "").strip()
        action = (data.get("action") or "").strip()
        ok = task_file_action(task_id, file_id, action)
        return jsonify({"ok": bool(ok)})

    @app.route("/api/tasks/cancel", methods=["POST"])
    def api_tasks_cancel():
        data = request.get_json(silent=True) or {}
        tid = (data.get("task_id") or request.form.get("task_id") or "").strip()
        if not tid:
            return jsonify({"ok": False, "error": "missing task_id"}), 400
        ok = bool(cancel_task(tid))
        return jsonify({"ok": ok})

    @app.route("/api/tasks/clear", methods=["POST"])
    def api_tasks_clear():
        data = request.get_json(silent=True) or {}
        tid = (data.get("task_id") or request.form.get("task_id") or "").strip()
        if not tid:
            return jsonify({"ok": False, "error": "missing task_id"}), 400
        ok = bool(clear_task(tid))
        return jsonify({"ok": ok})

    @app.route("/api/tasks/clear_all", methods=["POST"])
    def api_tasks_clear_all():
        clear_all_tasks()
        return jsonify({"ok": True})
