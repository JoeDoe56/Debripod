from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Optional


DOWNLOAD_MANIFEST_NAME = ".debripod-task.json"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def write_task_manifest(
    task: Any,
    *,
    original_result_title: str = "",
    remote_files: Optional[Iterable[Any]] = None,
    selected_file_ids: Optional[Iterable[Any]] = None,
    version: str = "",
) -> str:
    raw_task_dir = str(getattr(task, "task_dir", "") or "").strip()
    if not raw_task_dir:
        return ""
    task_dir = os.path.abspath(raw_task_dir)
    files: list[str] = []
    for item in remote_files or []:
        if isinstance(item, dict):
            name = item.get("remote_path") or item.get("path") or item.get("name") or item.get("title")
        else:
            name = getattr(item, "path", "") or getattr(item, "name", "") or item
        clean = str(name or "").strip()
        if clean:
            files.append(clean)
    ids = [str(value) for value in (selected_file_ids or []) if str(value or "").strip()]
    existing: dict[str, Any] = {}
    target = Path(task_dir) / DOWNLOAD_MANIFEST_NAME
    try:
        with target.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if isinstance(raw, dict):
            existing = raw
    except Exception:
        pass
    payload = {
        "source": str(getattr(task, "source", "") or "").strip().lower(),
        "task_id": str(getattr(task, "id", "") or ""),
        "task_title": str(getattr(task, "title", "") or ""),
        "original_result_title": str(original_result_title or existing.get("original_result_title") or getattr(task, "title", "") or ""),
        "remote_file_names": files or list(existing.get("remote_file_names") or []),
        "selected_file_ids": ids or list(existing.get("selected_file_ids") or []),
        "created": float(existing.get("created") or getattr(task, "created", 0) or time.time()),
        "updated": time.time(),
        "debripod_version": str(version or existing.get("debripod_version") or ""),
    }
    _atomic_json(target, payload)
    return str(target)


def nearest_task_manifest(file_path: str, source_root: str) -> dict[str, Any]:
    if not str(file_path or "").strip() or not str(source_root or "").strip():
        return {}
    root = os.path.realpath(os.path.abspath(str(source_root or "")))
    current = os.path.realpath(os.path.abspath(os.path.dirname(str(file_path or ""))))
    if not root or not current:
        return {}
    while True:
        try:
            if os.path.commonpath([root, current]) != root:
                return {}
        except Exception:
            return {}
        candidate = os.path.join(current, DOWNLOAD_MANIFEST_NAME)
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        if current == root:
            return {}
        parent = os.path.dirname(current)
        if parent == current:
            return {}
        current = parent
