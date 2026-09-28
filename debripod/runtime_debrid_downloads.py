from __future__ import annotations

import hashlib
import os
import threading
import time
import asyncio
import aiohttp
from typing import Any, Dict, List, Optional

from .storage.tasks import save_task_metadata
from .Services.debrid import DebridFile, DebridProviderError, get_provider
from .Services.http import HttpClient
from .Services.debrid.identifiers import first_identifier, normalize_identifier, normalize_identifier_list
from .runtime_state import *
from .runtime_video_post import enqueue_video_postprocess
from .settings import ensure_app_settings


DEBRID_API_SEMAPHORE = asyncio.Semaphore(4)
DEBRID_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
_HTTP: HttpClient | None = None
_APP_LOOP: asyncio.AbstractEventLoop | None = None


def configure_debrid_downloads(http: HttpClient, loop: asyncio.AbstractEventLoop) -> None:
    global _HTTP, _APP_LOOP
    _HTTP = http
    _APP_LOOP = loop


class DownloadHTTPError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = int(status_code or 0)


def _debrid_settings(task: Task) -> dict[str, Any]:
    # Background workers cannot rely on module globals: those contain the
    # process defaults, while a queued task belongs to a specific user.
    user_id = str(getattr(task, "owner_user_id", "") or getattr(task, "owner", "") or "").strip()
    saved = ensure_app_settings(user_id=user_id or None)
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
    if _HTTP is None:
        raise DebridProviderError("Debrid HTTP service is unavailable.")
    return get_provider(provider_id, settings, int(settings.get("REQUEST_TIMEOUT_SECONDS") or REQUEST_TIMEOUT_SECONDS or 25), _HTTP)


async def download_stream(url: str, out_path: str, task: Task, file_id: Optional[str] = None) -> None:
    async with DEBRID_DOWNLOAD_SEMAPHORE:
        await _download_stream_inner(url, out_path, task, file_id=file_id)


async def _download_stream_inner(url: str, out_path: str, task: Task, file_id: Optional[str] = None) -> None:
    if _HTTP is None:
        raise RuntimeError("Download HTTP service is unavailable")
    try:
        response = await _HTTP.session.get(url, timeout=_HTTP.timeouts.download)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise
    try:
        if response.status >= 400:
            raise DownloadHTTPError(response.status, f"Download failed ({response.status})")
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
            async for chunk in response.content.iter_chunked(256 * 1024):
                check_canceled(task)
                while task.pause_event.is_set():
                    check_canceled(task)
                    if file_id:
                        _update_task_file_entry(task.id, "debrid_files", file_id, state="paused")
                    await asyncio.sleep(0.15)
                if file_id:
                    while True:
                        check_canceled(task)
                        control = _get_file_control(task.id, file_id)
                        if control.get("canceled"):
                            raise CancelledFile("Canceled file")
                        if not control.get("paused"):
                            break
                        _update_task_file_entry(task.id, "debrid_files", file_id, state="paused")
                        await asyncio.sleep(0.15)
                if not chunk:
                    continue
                await asyncio.to_thread(handle.write, chunk)
                done += len(chunk)
                now = time.time()
                elapsed = max(0.001, now - last_time)
                speed = max(0.0, (done - last_done) / elapsed)
                last_time, last_done = now, done
                set_task(task.id, current_done=done)
                if file_id:
                    _update_task_file_entry(task.id, "debrid_files", file_id, done=done, speed=speed, state="downloading")
        if total is not None and done != total:
            raise aiohttp.ClientPayloadError("The download ended before all bytes arrived.")
        if done == 0:
            raise RuntimeError("The provider returned an empty download.")
    finally:
        response.close()


def _file_from_entry(entry: dict) -> DebridFile:
    return DebridFile(
        file_id=first_identifier(entry, "file_id", "id") or "",
        path=str(entry.get("path") or entry.get("name") or ""),
        name=str(entry.get("name") or os.path.basename(str(entry.get("path") or ""))),
        bytes=int(entry.get("total") or 0),
        provider_link=str(entry.get("provider_link") or ""),
        provider_task_id=first_identifier(entry, "provider_task_id", "task_id") or "",
        provider_file_id=first_identifier(entry, "provider_file_id", "file_id", "id") or "",
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


async def _download_from_queue(task_id: str) -> list[str]:
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
            await asyncio.sleep(0.2)
        with TASKS_LOCK:
            current = TASKS.get(task_id)
            entries = list(getattr(current, "debrid_files", []) or []) if current else []
        entry = next((item for item in entries if str(item.get("state") or "").lower() == "queued"), None)
        if not entry:
            break
        file_id = first_identifier(entry, "file_id", "id") or ""
        if _get_file_control(task_id, file_id).get("canceled"):
            _update_task_file_entry(task_id, "debrid_files", file_id, state="canceled", canceled=True, error="")
            continue
        _update_task_file_entry(task_id, "debrid_files", file_id, state="requesting", error="")
        file = _file_from_entry(entry)
        out_path = str(entry.get("out_path") or "")
        try:
            resolved = await provider.resolve_file_url(file)
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
            for attempt in range(2):
                try:
                    await download_stream(resolved.url, out_path, task, file_id=file_id)
                    break
                except (DownloadHTTPError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    retryable = not isinstance(exc, DownloadHTTPError) or exc.status_code in {401,403,404,408,429,500,502,503,504}
                    if attempt or not resolved.requires_refresh or not retryable:
                        if isinstance(exc, aiohttp.ClientConnectorCertificateError):
                            raise DebridProviderError("The provider download server has an invalid or expired TLS certificate. A refreshed link also failed; the provider must repair its certificate.") from exc
                        raise
                    resolved = await provider.resolve_file_url(file)
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


async def debrid_download_remaining_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task or str(task.source or "").lower() != "debrid":
        return
    try:
        set_task(task_id, state="downloading", message="Retrying queued files")
        completed = await _download_from_queue(task_id)
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


def schedule_debrid_download_remaining(task_id: str) -> None:
    loop = _APP_LOOP
    if loop is None or loop.is_closed():
        return

    def _start() -> None:
        loop.create_task(debrid_download_remaining_worker(task_id), name=f"debrid-retry:{task_id}")

    loop.call_soon_threadsafe(_start)


async def worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task or str(task.source or "").lower() != "debrid":
        return
    provider = None
    try:
        check_canceled(task)
        provider = _provider_for_task(task)
        provider_task_id = normalize_identifier(task.debrid_task_id) or ""
        preview = None
        if not provider_task_id:
            if not task.magnet:
                raise DebridProviderError("Missing magnet.")
            set_task(task_id, state="adding", message="Adding magnet to debrid provider")
            async with DEBRID_API_SEMAPHORE:
                preview = await provider.preview_magnet(task.magnet)
            provider_task_id = preview.provider_task_id
            set_task(task_id, debrid_task_id=provider_task_id)
        selected_ids = normalize_identifier_list(task.debrid_selected_file_ids)
        if not selected_ids:
            preview = preview or await provider.refresh_preview(provider_task_id)
            selected_ids = [item.file_id for item in preview.files]
        set_task(task_id, state="selecting", message="Selecting files")
        set_task(task_id, state="waiting", message="Waiting for debrid provider to cache the torrent")
        async with DEBRID_API_SEMAPHORE:
            files = await provider.prepare_selected_files(
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
            file_id = normalize_identifier(file.file_id) or hashlib.sha1((file.path + file.provider_link).encode()).hexdigest()[:16]
            entries.append({
                "file_id": file_id,
                "provider": provider.id,
                "provider_task_id": normalize_identifier(file.provider_task_id) or provider_task_id,
                "provider_file_id": normalize_identifier(file.provider_file_id) or file_id,
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
        save_task_metadata(task, original_result_title=task.title, remote_files=entries, selected_file_ids=selected_ids, version=str(VERSION))
        completed = await _download_from_queue(task_id)
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
            await provider.delete_task_best_effort(getattr(task, "debrid_task_id", None))
        set_task(task_id, state="canceled", message="Canceled", current_file="", current_done=0, current_total=None)
    except Exception as exc:
        set_task(task_id, state="error", message=str(exc)[:300] or "Debrid download failed", current_file="", current_done=0, current_total=None)


__all__ = [name for name in globals() if not name.startswith("__")]
