from __future__ import annotations

from .runtime_state import *
from .runtime_video_post import *


def download_stream(url: str, out_path: str, task: Task, file_id: Optional[str] = None) -> None:
    # Supports task-level pause and per-file pause/cancel via TASKS[file].file_controls
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as r:
        r.raise_for_status()
        total = r.headers.get("Content-Length")
        total_i = int(total) if total and str(total).isdigit() else None

        if file_id:
            _update_task_file_entry(task.id, "rd_files", file_id, total=(int(total_i) if total_i is not None else 0))

        set_task(task.id, current_total=total_i, current_done=0)

        done = 0
        last_t = time.time()
        last_done = 0

        # Ensure parent folder exists
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        except Exception:
            pass

        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                check_canceled(task)

                # Task pause
                while True:
                    check_canceled(task)
                    if not task.pause_event.is_set():
                        break
                    if file_id:
                        _update_task_file_entry(task.id, "rd_files", file_id, state="paused")
                    time.sleep(0.15)

                # Per-file control
                if file_id:
                    while True:
                        check_canceled(task)
                        ctl = _get_file_control(task.id, file_id)
                        if ctl.get("canceled"):
                            raise CancelledFile("Canceled file")
                        if ctl.get("paused"):
                            _update_task_file_entry(task.id, "rd_files", file_id, state="paused")
                            time.sleep(0.15)
                            continue
                        break

                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)

                # speed estimate
                now = time.time()
                dt = max(0.001, now - last_t)
                spd = max(0.0, (done - last_done) / dt)
                last_t = now
                last_done = done

                set_task(task.id, current_done=done)
                if file_id:
                    _update_task_file_entry(task.id, "rd_files", file_id, done=int(done), speed=float(spd), state="downloading")



def rd_add_magnet(magnet: str) -> str:
    status, text, js = rd_request("POST", "/torrents/addMagnet", data={"magnet": magnet})
    if status not in (200, 201) or not isinstance(js, dict):
        raise RuntimeError(f"addMagnet failed ({status}): {text[:300]}")
    tid = js.get("id")
    if not tid:
        raise RuntimeError("addMagnet did not return an id")
    return str(tid)


def rd_select_all_files(torrent_id: str) -> None:
    status, text, _ = rd_request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": "all"})
    if status not in (200, 204, 202):
        raise RuntimeError(f"selectFiles failed ({status}): {text[:300]}")



def rd_select_files(torrent_id: str, file_ids: List[int]) -> None:
    clean: List[str] = []
    for x in (file_ids or []):
        try:
            clean.append(str(int(x)))
        except Exception:
            continue
    if not clean:
        raise RuntimeError("No files selected")
    files_str = ",".join(clean)
    status, text, _ = rd_request("POST", f"/torrents/selectFiles/{torrent_id}", data={"files": files_str})
    if status not in (200, 204, 202):
        raise RuntimeError(f"selectFiles failed ({status}): {text[:300]}")


def rd_torrent_info(torrent_id: str) -> dict:
    status, text, js = rd_request("GET", f"/torrents/info/{torrent_id}")
    if status != 200 or not isinstance(js, dict):
        raise RuntimeError(f"torrents/info failed ({status}): {text[:300]}")
    return js


def rd_unrestrict(link: str) -> dict:
    status, text, js = rd_request("POST", "/unrestrict/link", data={"link": link})
    if status != 200 or not isinstance(js, dict):
        raise RuntimeError(f"unrestrict/link failed ({status}): {text[:300]}")
    if not js.get("download"):
        raise RuntimeError("unrestrict/link did not return a download url")
    return js


def rd_delete_torrent_best_effort(torrent_id: Optional[str]) -> None:
    if not torrent_id:
        return
    rd_request("DELETE", f"/torrents/delete/{torrent_id}")


def _rd_recompute_overall_from_files(task_id: str) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        files = list(getattr(t, "rd_files", []) or [])
    od = 0
    ot = 0
    have_total = False
    for f in files:
        try:
            d = int(f.get("done") or 0)
            tot = int(f.get("total") or 0)
        except Exception:
            d = 0
            tot = 0
        od += max(0, d)
        if tot > 0:
            ot += tot
            have_total = True
    set_task(task_id, overall_done=int(od), overall_total=(int(ot) if have_total and ot > 0 else None))


def _rd_download_from_queue(task_id: str) -> List[str]:
    task = get_task(task_id)
    if not task:
        return []

    downloaded_paths: List[str] = []

    while True:
        task = get_task(task_id)
        if not task:
            break
        check_canceled(task)

        # Task pause
        while task.pause_event.is_set():
            check_canceled(task)
            time.sleep(0.2)

        # Pick next queued file
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            entries = list(getattr(tcur, "rd_files", []) or []) if tcur else []
        next_entry: Optional[Dict[str, Any]] = None
        for e in entries:
            st = str(e.get("state") or "").lower()
            if st == "queued":
                next_entry = e
                break
        if not next_entry:
            break

        file_id = str(next_entry.get("file_id") or "")
        link = str(next_entry.get("link") or "")
        seq = int(next_entry.get("seq") or 0)
        if not file_id or not link:
            _update_task_file_entry(task_id, "rd_files", file_id, state="failed", error="Missing link")
            _rd_recompute_overall_from_files(task_id)
            continue

        ctl = _get_file_control(task_id, file_id)
        if ctl.get("canceled"):
            _update_task_file_entry(task_id, "rd_files", file_id, state="canceled", error="")
            _rd_recompute_overall_from_files(task_id)
            continue

        try:
            _update_task_file_entry(task_id, "rd_files", file_id, state="requesting", error="")
            un = rd_unrestrict(link)
            dl_url = un["download"]
            filename = sanitize_filename(un.get("filename") or next_entry.get("name") or f"file_{seq or 1}")
        except Exception as e:
            _update_task_file_entry(task_id, "rd_files", file_id, state="failed", error=str(e))
            _rd_recompute_overall_from_files(task_id)
            continue

        # Determine output path (stable per file_id)
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            cur_files = list(getattr(tcur, "rd_files", []) or []) if tcur else []
            existing_out = ""
            for ff in cur_files:
                if str(ff.get("file_id") or "") == file_id:
                    existing_out = str(ff.get("out_path") or "")
                    break

        if existing_out:
            out_path = existing_out
        else:
            out_path = os.path.join(task.task_dir, filename)
            base, ext = os.path.splitext(out_path)
            n = 1
            while os.path.exists(out_path):
                out_path = f"{base} ({n}){ext}"
                n += 1
            _update_task_file_entry(task_id, "rd_files", file_id, out_path=out_path, name=os.path.basename(out_path))

        set_task(task_id, current_file=os.path.basename(out_path), current_done=0, current_total=None)

        try:
            download_stream(dl_url, out_path, task, file_id=file_id)
            downloaded_paths.append(out_path)
            _update_task_file_entry(task_id, "rd_files", file_id, state="complete", error="")
            try:
                enqueue_video_postprocess(task_id, out_path)
            except Exception:
                pass
        except CancelledFile:
            try:
                if out_path and os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            _update_task_file_entry(task_id, "rd_files", file_id, state="canceled", error="")
        except Cancelled:
            raise
        except Exception as e:
            _update_task_file_entry(task_id, "rd_files", file_id, state="failed", error=str(e))

        _rd_recompute_overall_from_files(task_id)

    # Return list of completed file paths (deduped)
    with TASKS_LOCK:
        tcur = TASKS.get(task_id)
        entries = list(getattr(tcur, "rd_files", []) or []) if tcur else []
    completed: List[str] = []
    for e in entries:
        if str(e.get("state") or "").lower() == "complete":
            op = str(e.get("out_path") or "")
            if op:
                completed.append(op)
    # Deduplicate while keeping order
    seen = set()
    uniq: List[str] = []
    for p in completed + downloaded_paths:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def rd_download_remaining_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return
    if (task.source or "").lower() != "rd":
        return
    try:
        set_task(task_id, state="downloading", message="Retrying queued files")
        completed = _rd_download_from_queue(task_id)
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            entries = list(getattr(tcur, "rd_files", []) or []) if tcur else []
        any_failed = any(str(e.get("state") or "").lower() == "failed" for e in entries)
        all_done = all(str(e.get("state") or "").lower() in {"complete", "canceled"} for e in entries) if entries else True
        set_task(task_id, downloaded_files=completed, current_file="", current_done=0, current_total=None, downloads_complete=bool(all_done and not any_failed))
        if any_failed:
            set_task(task_id, state="error", message="Some files failed. You can retry failed files.")
        elif all_done:
            set_task(task_id, state="done", message="Finished")
        else:
            set_task(task_id, state="downloading", message="Downloading")
    except Cancelled:
        set_task(task_id, state="canceled", message="Canceled", current_file="", current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state="error", message=str(e), current_file="", current_done=0, current_total=None)



def worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return

    try:
        check_canceled(task)

        if str(task.source or '').lower() == 'youtube':
            return youtube_worker(task_id)

        torrent_id = task.torrent_id
        if torrent_id:
            set_task(task_id, state="selecting", message="Selecting files")
        else:
            if not task.magnet:
                raise RuntimeError("Missing magnet")
            set_task(task_id, state="adding", message="Adding magnet to Real Debrid")
            torrent_id = rd_add_magnet(task.magnet)
            set_task(task_id, torrent_id=torrent_id)
            check_canceled(task)
            set_task(task_id, state="selecting", message="Selecting files")

        if task.rd_selected_file_ids:
            rd_select_files(torrent_id, task.rd_selected_file_ids)
        else:
            rd_select_all_files(torrent_id)
        check_canceled(task)

        set_task(task_id, state="waiting", message="Waiting for Real Debrid to cache the torrent")
        start = time.time()
        info = {}
        while True:
            check_canceled(task)
            if time.time() - start > MAX_TORRENT_WAIT_SECONDS:
                raise RuntimeError("Timed out waiting for Real Debrid to finish caching the torrent")
            info = rd_torrent_info(torrent_id)
            status = str(info.get("status", "")).lower()
            links = info.get("links") or []
            if status == "downloaded" and isinstance(links, list) and len(links) > 0:
                break
            if status in {"error", "magnet_error", "dead"}:
                raise RuntimeError(f"Real Debrid reported status: {status}")
            time.sleep(POLL_INTERVAL_SECONDS)

        links = info.get("links") or []
        if not isinstance(links, list) or not links:
            raise RuntimeError("No downloadable links available from Real Debrid")

        if len(links) > MAX_FILES_PER_TORRENT:
            links = links[:MAX_FILES_PER_TORRENT]

        set_task(task_id, state="downloading", message=f"Downloading {len(links)} file(s)")

        # Initialize per-file status entries
        rd_files: List[Dict[str, Any]] = []
        for i, lnk in enumerate(links, start=1):
            fid = hashlib.sha1(str(lnk).encode("utf-8", "ignore")).hexdigest()[:16]
            rd_files.append(
                {
                    "file_id": fid,
                    "seq": int(i),
                    "link": str(lnk),
                    "name": "",
                    "out_path": "",
                    "total": 0,
                    "done": 0,
                    "speed": 0.0,
                    "state": "queued",
                    "error": "",
                    "paused": False,
                    "canceled": False,
                }
            )
            _set_file_control(task_id, fid, paused=False, canceled=False)

        set_task(task_id, rd_files=rd_files, overall_done=0, overall_total=None)

        downloaded_paths = _rd_download_from_queue(task_id)

        set_task(
            task_id,
            downloaded_files=downloaded_paths,
            current_file="",
            current_done=0,
            current_total=None,
            downloads_complete=True,
        )
        # Determine whether any files failed so the task can report errors while still keeping completed files
        with TASKS_LOCK:
            _tcur = TASKS.get(task_id)
            _entries = list(getattr(_tcur, "rd_files", []) or []) if _tcur else []
        any_failed = any(str(e.get("state") or "").lower() == "failed" for e in _entries)
        all_ok = all(str(e.get("state") or "").lower() in {"complete", "canceled"} for e in _entries) if _entries else True
        set_task(task_id, downloads_complete=bool(all_ok and not any_failed))

        task2 = get_task(task_id)
        if task2 and task2.video_post_total > task2.video_post_done and task2.state not in ("error", "canceled"):
            set_task(task_id, state="postprocessing", message="Downloaded. Processing videos for browser compatibility")
        else:
            if any_failed:
                set_task(task_id, state="error", message="Some files failed. You can retry failed files.")
            else:
                set_task(task_id, state="done", message="Finished")

    except Cancelled:
        rd_delete_torrent_best_effort(task.torrent_id)
        set_task(task_id, state="canceled", message="Canceled", current_file="", current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state="error", message=str(e), current_file="", current_done=0, current_total=None)




__all__ = [name for name in globals() if not name.startswith("__")]
