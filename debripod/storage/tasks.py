from __future__ import annotations

import json
import os
import time
from typing import Any

from .codec import decode, encode
from .database import database
from ..Services.debrid.identifiers import first_identifier, normalize_identifier, normalize_identifier_list


def save_task_metadata(task: Any, *, original_result_title: str = "", remote_files: list[dict[str, Any]] | None = None,
                       selected_file_ids: list[Any] | None = None, version: str = "") -> None:
    selected = set(normalize_identifier_list(selected_file_ids))
    source_data = {"magnet": str(getattr(task, "magnet", "") or ""), "selected_file_ids": sorted(selected)}
    blob, codec_name, raw_len = encode(json.dumps(source_data, separators=(",", ":"), ensure_ascii=False).encode())
    now = time.time()
    task_id = normalize_identifier(getattr(task, "id", None)) or ""
    state = {key: value for key, value in vars(task).items() if key not in {"pause_event", "cancel_event"}}
    state_payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False, default=str)
    with database() as conn:
        conn.execute("""INSERT INTO tasks(task_id,owner,source,title,original_result_title,task_dir,provider,remote_task_id,
          source_blob,source_codec,source_uncompressed_bytes,state_json,created_at,updated_at,version,origin_client_id)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET owner=excluded.owner,source=excluded.source,
          title=excluded.title,original_result_title=excluded.original_result_title,task_dir=excluded.task_dir,provider=excluded.provider,
          remote_task_id=excluded.remote_task_id,source_blob=excluded.source_blob,source_codec=excluded.source_codec,
          source_uncompressed_bytes=excluded.source_uncompressed_bytes,updated_at=excluded.updated_at,version=excluded.version,
          origin_client_id=excluded.origin_client_id""",
          (task_id, str(getattr(task, "owner", "") or ""), str(getattr(task, "source", "debrid") or "debrid"),
           str(getattr(task, "title", "") or ""), str(original_result_title or ""), str(getattr(task, "task_dir", "") or ""),
           str(getattr(task, "debrid_provider", "") or ""), normalize_identifier(getattr(task, "debrid_task_id", None)) or "", blob, codec_name,
           raw_len, state_payload, float(getattr(task, "created", now) or now), now, str(version or ""),
           str(getattr(task, "origin_client_id", "") or "")))
        conn.execute("DELETE FROM task_files WHERE task_id=?", (task_id,))
        for index, item in enumerate(remote_files or []):
            file_id = first_identifier(item, "file_id", "id")
            if file_id is None:
                file_id = str(index)
            remote_name = str(item.get("name") or item.get("path") or item.get("filename") or "")
            local_path = os.path.join(str(getattr(task, "task_dir", "") or ""), os.path.basename(remote_name)) if remote_name else ""
            conn.execute("INSERT INTO task_files(task_id,file_id,remote_name,local_path,selected,state_json,updated_at) VALUES(?,?,?,?,?,?,?)",
                (task_id, file_id, remote_name, local_path, int(file_id in selected), "{}", now))


def update_task_state(task: Any) -> None:
    state = {key: value for key, value in vars(task).items() if key not in {"pause_event", "cancel_event"}}
    payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False, default=str)
    with database() as conn:
        conn.execute("UPDATE tasks SET state_json=?,updated_at=? WHERE task_id=?", (payload, time.time(), str(getattr(task, "id", ""))))


def metadata_for_path(file_path: str, source_root: str = "") -> dict[str, Any]:
    path = os.path.normcase(os.path.abspath(file_path))
    with database(write=False) as conn:
        row = conn.execute("""SELECT t.* FROM task_files f JOIN tasks t ON t.task_id=f.task_id
          WHERE lower(f.local_path)=lower(?) ORDER BY t.updated_at DESC LIMIT 1""", (path,)).fetchone()
        if not row:
            rows = conn.execute("SELECT * FROM tasks WHERE task_dir<>'' ORDER BY length(task_dir) DESC,updated_at DESC").fetchall()
            row = next((r for r in rows if path == os.path.normcase(os.path.abspath(r["task_dir"])) or
                        path.startswith(os.path.normcase(os.path.abspath(r["task_dir"])) + os.sep)), None)
    if not row:
        return {}
    try:
        state_payload = json.loads(row["state_json"] or "{}")
    except Exception:
        state_payload = {}
    return {"source": row["source"], "source_url": str(state_payload.get("source_url") or ""),
            "task_id": row["task_id"], "task_title": row["title"],
            "original_result_title": row["original_result_title"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "version": row["version"]}
