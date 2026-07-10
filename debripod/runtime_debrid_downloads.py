from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from .Library.download_manifest import write_task_manifest
from .Services.debrid import DebridFile, DebridProviderError, get_provider
from .runtime_state import *
from .runtime_video_post import enqueue_video_postprocess
from .settings import ensure_app_settings


DEBRID_API_SEMAPHORE = threading.BoundedSemaphore(4)
DEBRID_DOWNLOAD_SEMAPHORE = threading.BoundedSemaphore(2)


class DownloadHTTPError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = int(status_code or 0)


def _debrid_settings(task: Task) -> dict[str, Any]:
    # Background workers cannot rely on module globals: those contain the
    # process defaults, while a queued task belongs to a specific user.
    owner = str(getattr(task, "owner", "") or "").strip()
    saved = ensure_app_settings(username=owner or None)
    keys = (
        "DEBRID_PROVIDER", "REAL_DEBRID_API_KEY", "RD_BASE",
        "ALLDEBRID_API_KEY", "ALLDEBRID_BASE", "PREMIUMIZE_API_KEY", "PREMIUMIZE_BASE",
        "TORBOX_API_KEY", "TORBOX_BASE", "SEARCH_STREAM_SESSION_TTL_SECONDS", "REQUEST_TIMEOUT_SECONDS",
    )
    return {key: saved.get(key) for key in keys}


def _provider_for_task(task: Task):
    provider_id = str(task.debrid_provider or "").strip().lower()
    if not provider_id:
        raise DebridProviderError("No debrid provider is configured.")
    settings = _debrid_settings(task)
    return get_provider(provider_id, settings, int(settings.get("REQUEST_TIMEOUT_SECONDS") or REQUEST_TIMEOUT_SECONDS or 25))


def download_stream(url: str, out_path: str, task: Task, file_id: Optional[str] = None) -> None:
    with DEBRID_DOWNLOAD_SEMAPHORE:
        _download_stream_inner(url, out_path, task, file_id=file_id)


def _download_stream_inner(url: str, out_path: str, task: Task, file_id: Optional[str] = None) -> None:
    try:
        response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RuntimeError(str(exc)) from exc
    with response:
        if response.status_code >= 400:
            raise DownloadHTTPError(response.status_code, f"Download failed ({response.status_code})")
        total_raw = response.headers.get("Content-Length")
        total = int(total_raw) if total_raw and str(total_raw).isdigit() else None
        if file_id:
            _update_task_file_entry(task.id, "debrid_files", file_id, total=int(total or 0))
        set_task(task.id, current_total=total, current_done=0)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        done = 0
        last_time = time.time()
        last_done = 0
        with open(out_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                check_canceled(task)
                while task.pause_event.is_set():
                    check_canceled(task)
                    if file_id:
                        _update_task_file_entry(task.id, "debrid_files", file_id, state="paused")
                    time.sleep(0.15)
                if file_id:
                    while True:
                        check_canceled(task)
                        control = _get_file_control(task.id, file_id)
                        if control.get("canceled"):
                            raise CancelledFile("Canceled file")
                        if not control.get("paused"):
                            break
                        _update_task_file_entry(task.id, "debrid_files", file_id, state="paused")
                        time.sleep(0.15)
                if not chunk:
                    continue
                handle.write(chunk)
                done += len(chunk)
                now = time.time()
                elapsed = max(0.001, now - last_time)
                speed = max(0.0, (done - last_done) / elapsed)
                last_time, last_done = now, done
                set_task(task.id, current_done=done)
                if file_id:
                    _update_task_file_entry(task.id, "debrid_files", file_id, done=done, speed=speed, state="downloading")


def _file_from_entry(entry: dict) -> DebridFile:
    return DebridFile(
        file_id=str(entry.get("file_id") or ""),
        path=str(entry.get("path") or entry.get("name") or ""),
        name=str(entry.get("name") or os.path.basename(str(entry.get("path") or ""))),
        bytes=int(entry.get("total") or 0),
        provider_link=str(entry.get("provider_link") or ""),
        provider_task_id=str(entry.get("provider_task_id") or ""),
        provider_file_id=str(entry.get("provider_file_id") or entry.get("file_id") or ""),
        media=str(entry.get("media") or ""),
        ext=str(entry.get("ext") or ""),
        raw=dict(entry.get("raw") or {}) if isinstance(entry.get("raw"), dict) else {},
    )


def _recompute_overall(task_id: str) -> None:
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        files = list(getattr(task, "debrid_files", []) or []) if task else []
    done = sum(max(0, int(item.get("done") or 0)) for item in files)
    totals = [max(0, int(item.get("total") or 0)) for item in files]
    total = sum(totals) if any(totals) else None
    set_task(task_id, overall_done=done, overall_total=total)


def _completed_paths(task_id: str) -> list[str]:
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        files = list(getattr(task, "debrid_files", []) or []) if task else []
    seen: set[str] = set()
    out: list[str] = []
    for entry in files:
        path = str(entry.get("out_path") or "")
        if str(entry.get("state") or "").lower() == "complete" and path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _download_from_queue(task_id: str) -> list[str]:
    task = get_task(task_id)
    if not task:
        return []
    provider = _provider_for_task(task)
    while True:
        task = get_task(task_id)
        if not task:
            break
        check_canceled(task)
        while task.pause_event.is_set():
            check_canceled(task)
            time.sleep(0.2)
        with TASKS_LOCK:
            current = TASKS.get(task_id)
            entries = list(getattr(current, "debrid_files", []) or []) if current else []
        entry = next((item for item in entries if str(item.get("state") or "").lower() == "queued"), None)
        if not entry:
            break
        file_id = str(entry.get("file_id") or "")
        if _get_file_control(task_id, file_id).get("canceled"):
            _update_task_file_entry(task_id, "debrid_files", file_id, state="canceled", canceled=True, error="")
            continue
        _update_task_file_entry(task_id, "debrid_files", file_id, state="requesting", error="")
        file = _file_from_entry(entry)
        try:
            resolved = provider.resolve_file_url(file)
            filename = sanitize_filename(resolved.filename or file.name or f"file_{entry.get('seq') or 1}")
            out_path = str(entry.get("out_path") or "")
            if not out_path:
                out_path = os.path.join(task.task_dir, filename)
                stem, ext = os.path.splitext(out_path)
                suffix = 1
                while os.path.exists(out_path):
                    out_path = f"{stem} ({suffix}){ext}"
                    suffix += 1
                _update_task_file_entry(task_id, "debrid_files", file_id, out_path=out_path, name=os.path.basename(out_path))
            set_task(task_id, current_file=os.path.basename(out_path), current_done=0, current_total=None)
            try:
                download_stream(resolved.url, out_path, task, file_id=file_id)
            except DownloadHTTPError as exc:
                if not resolved.requires_refresh or exc.status_code not in {401, 403, 404}:
                    raise
                refreshed = provider.resolve_file_url(file)
                download_stream(refreshed.url, out_path, task, file_id=file_id)
            _update_task_file_entry(task_id, "debrid_files", file_id, state="complete", error="")
            enqueue_video_postprocess(task_id, out_path)
        except CancelledFile:
            try:
                if out_path and os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            _update_task_file_entry(task_id, "debrid_files", file_id, state="canceled", error="")
        except Cancelled:
            raise
        except Exception as exc:
            _update_task_file_entry(task_id, "debrid_files", file_id, state="failed", error=str(exc)[:300] or "Debrid download failed")
        _recompute_overall(task_id)
    return _completed_paths(task_id)


def debrid_download_remaining_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task or str(task.source or "").lower() != "debrid":
        return
    try:
        set_task(task_id, state="downloading", message="Retrying queued files")
        completed = _download_from_queue(task_id)
        with TASKS_LOCK:
            current = TASKS.get(task_id)
            entries = list(getattr(current, "debrid_files", []) or []) if current else []
        failed = any(str(item.get("state") or "").lower() == "failed" for item in entries)
        complete = bool(entries) and all(str(item.get("state") or "").lower() in {"complete", "canceled"} for item in entries)
        set_task(task_id, downloaded_files=completed, current_file="", current_done=0, current_total=None, downloads_complete=complete and not failed)
        if failed:
            set_task(task_id, state="error", message="Some files failed. You can retry failed files.")
        elif complete:
            set_task(task_id, state="done", message="Finished")
    except Cancelled:
        set_task(task_id, state="canceled", message="Canceled", current_file="", current_done=0, current_total=None)
    except Exception as exc:
        set_task(task_id, state="error", message=str(exc)[:300] or "Debrid download failed", current_file="", current_done=0, current_total=None)


def worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task or str(task.source or "").lower() != "debrid":
        return
    provider = None
    try:
        check_canceled(task)
        provider = _provider_for_task(task)
        provider_task_id = str(task.debrid_task_id or "")
        preview = None
        if not provider_task_id:
            if not task.magnet:
                raise DebridProviderError("Missing magnet.")
            set_task(task_id, state="adding", message="Adding magnet to debrid provider")
            with DEBRID_API_SEMAPHORE:
                preview = provider.preview_magnet(task.magnet)
            provider_task_id = preview.provider_task_id
            set_task(task_id, debrid_task_id=provider_task_id)
        selected_ids = [str(value) for value in (task.debrid_selected_file_ids or []) if str(value or "").strip()]
        if not selected_ids:
            preview = preview or provider.refresh_preview(provider_task_id)
            selected_ids = [item.file_id for item in preview.files]
        set_task(task_id, state="selecting", message="Selecting files")
        set_task(task_id, state="waiting", message="Waiting for debrid provider to cache the torrent")
        with DEBRID_API_SEMAPHORE:
            files = provider.prepare_selected_files(
                magnet=task.magnet,
                provider_task_id=provider_task_id,
                selected_file_ids=selected_ids,
                timeout_seconds=int(MAX_TORRENT_WAIT_SECONDS or 1800),
                poll_interval_seconds=int(POLL_INTERVAL_SECONDS or 4),
            )
        if not files:
            raise DebridProviderError("No downloadable links available from debrid provider.")
        files = files[: int(MAX_FILES_PER_TORRENT or len(files))]
        entries: list[dict[str, Any]] = []
        for index, file in enumerate(files, start=1):
            file_id = str(file.file_id or hashlib.sha1((file.path + file.provider_link).encode()).hexdigest()[:16])
            entries.append({
                "file_id": file_id,
                "provider": provider.id,
                "provider_task_id": file.provider_task_id or provider_task_id,
                "provider_file_id": file.provider_file_id or file_id,
                "provider_link": file.provider_link,
                "seq": index,
                "name": file.name,
                "path": file.path,
                "media": file.media,
                "ext": file.ext,
                "out_path": "",
                "total": file.bytes,
                "done": 0,
                "speed": 0.0,
                "state": "queued",
                "error": "",
                "paused": False,
                "canceled": False,
                "raw": file.raw,
            })
            _set_file_control(task_id, file_id, paused=False, canceled=False)
        set_task(task_id, debrid_files=entries, overall_done=0, overall_total=None, state="downloading", message=f"Downloading {len(entries)} file(s)")
        write_task_manifest(task, original_result_title=task.title, remote_files=entries, selected_file_ids=selected_ids, version=str(VERSION))
        completed = _download_from_queue(task_id)
        with TASKS_LOCK:
            current = TASKS.get(task_id)
            entries = list(getattr(current, "debrid_files", []) or []) if current else []
        failed = any(str(item.get("state") or "").lower() == "failed" for item in entries)
        all_ok = bool(entries) and all(str(item.get("state") or "").lower() in {"complete", "canceled"} for item in entries)
        set_task(task_id, downloaded_files=completed, current_file="", current_done=0, current_total=None, downloads_complete=all_ok and not failed)
        current = get_task(task_id)
        if current and current.video_post_total > current.video_post_done and current.state not in {"error", "canceled"}:
            set_task(task_id, state="postprocessing", message="Downloaded. Processing videos for browser compatibility")
        elif failed:
            set_task(task_id, state="error", message="Some files failed. You can retry failed files.")
        else:
            set_task(task_id, state="done", message="Finished")
    except Cancelled:
        if provider:
            provider.delete_task_best_effort(getattr(task, "debrid_task_id", None))
        set_task(task_id, state="canceled", message="Canceled", current_file="", current_done=0, current_total=None)
    except Exception:
        set_task(task_id, state="error", message="Debrid download failed", current_file="", current_done=0, current_total=None)


__all__ = [name for name in globals() if not name.startswith("__")]
