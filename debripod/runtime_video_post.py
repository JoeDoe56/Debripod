from __future__ import annotations

from .runtime_state import *

# =========================
# Video auto transcode queue
# =========================

_VIDEO_POST_QUEUE: "queue.Queue[Tuple[str, str]]" = queue.Queue()
_VIDEO_POST_THREAD: Optional[threading.Thread] = None
_VIDEO_POST_GUARD = threading.Lock()


def _ensure_video_post_worker() -> None:
    global _VIDEO_POST_THREAD
    with _VIDEO_POST_GUARD:
        if _VIDEO_POST_THREAD is not None and _VIDEO_POST_THREAD.is_alive():
            return
        _VIDEO_POST_THREAD = threading.Thread(target=_video_post_worker, name="video_post_worker", daemon=True)
        _VIDEO_POST_THREAD.start()


def enqueue_video_postprocess(task_id: str, src_path: str) -> None:
    if not AUTO_TRANSCODE_FOR_BROWSER_COMPATIBILITY:
        return
    if not is_video(src_path):
        return
    try:
        if not os.path.exists(src_path) or not os.path.isfile(src_path):
            return
    except OSError:
        return

    _ensure_video_post_worker()

    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if t:
            t.video_post_total += 1
            t.video_post_state = "queued"
            t.video_post_message = "Queued for browser compatibility"

    _VIDEO_POST_QUEUE.put((task_id, src_path))


def _probe_duration_seconds(path: str) -> float:
    try:
        j = ffprobe_json(path)
        dur = (j.get("format") or {}).get("duration")
        if dur is not None:
            return float(dur)
    except Exception:
        return 0.0
    return 0.0


def _inject_progress_args(args: List[str]) -> List[str]:
    # Insert "-progress pipe:1 -nostats" so we can parse out_time_ms
    out = list(args)
    try:
        i = out.index("-loglevel")
        if i + 1 < len(out):
            insert_at = i + 2
        else:
            insert_at = len(out)
    except ValueError:
        insert_at = 1 if out else 0
    out[insert_at:insert_at] = ["-progress", "pipe:1", "-nostats"]
    return out


def _run_ffmpeg_to_tmp_with_progress(
    args: List[str],
    tmp_path: str,
    *,
    stage: str,
    src_path: str,
    task_id: str,
    cancel_event: threading.Event,
    total_duration_s: float,
) -> Tuple[bool, str]:
    args2 = _inject_progress_args(args)

    total_us = int(max(0.0, float(total_duration_s)) * 1000000.0) if total_duration_s else 0
    set_task(
        task_id,
        video_post_state=stage,
        video_post_message="Running ffmpeg",
        video_post_current_file=os.path.basename(src_path),
        video_post_current_done=0,
        video_post_current_total=(total_us if total_us > 0 else None),
    )

    stderr_lines: List[str] = []
    try:
        p = subprocess.Popen(
            args2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )
    except FileNotFoundError:
        _safe_remove(tmp_path)
        return False, f"Command not found: {args2[0]}"
    except Exception as e:
        _safe_remove(tmp_path)
        return False, str(e)

    def _drain_stderr():
        try:
            if p.stderr:
                for line in p.stderr:
                    stderr_lines.append(line.rstrip("\n"))
        except Exception:
            pass

    th = threading.Thread(target=_drain_stderr, daemon=True)
    th.start()

    out_time_us = 0
    try:
        if p.stdout:
            for line in p.stdout:
                if cancel_event.is_set():
                    try:
                        p.terminate()
                    except Exception:
                        pass
                    break
                line = (line or "").strip()
                if not line or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "out_time_ms":
                    try:
                        # ffmpeg reports microseconds here
                        out_time_us = int(float(v))
                    except Exception:
                        out_time_us = out_time_us
                    if total_us > 0:
                        done_us = min(max(0, out_time_us), total_us)
                        set_task(task_id, video_post_current_done=done_us)
                elif k == "progress" and v == "end":
                    if total_us > 0:
                        set_task(task_id, video_post_current_done=total_us)
    except Exception:
        pass

    try:
        code = p.wait()
    except Exception:
        code = 1

    try:
        th.join(timeout=0.5)
    except Exception:
        pass

    err = "\n".join(stderr_lines).strip()
    out = ""  # progress output not kept

    if cancel_event.is_set():
        _safe_remove(tmp_path)
        try:
            _record_ffmpeg_failure(stage, args2, code, out, err, src_path, tmp_path)
        except Exception:
            pass
        return False, "Canceled"

    if code == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
        return True, ""

    _safe_remove(tmp_path)
    log_path = _record_ffmpeg_failure(stage, args2, code, out, err, src_path, tmp_path)
    msg = err.strip() or "ffmpeg failed"
    if log_path:
        msg = msg + f"\nLog saved to: {log_path}"
    msg = msg + f"\nCache dir: {transcode_cache_dir()}"
    return False, msg


def _unique_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    if not os.path.exists(path):
        return path
    n = 1
    while True:
        cand = f"{base} ({n}){ext}"
        if not os.path.exists(cand):
            return cand
        n += 1


def _video_output_paths(src_path: str) -> Tuple[str, str]:
    base, ext = os.path.splitext(src_path)
    ext_l = (ext or "").lower()
    target_ext = "." + VIDEO_BROWSER_TARGET_EXT
    desired = base + target_ext

    if REPLACE_ORIGINAL:
        # In replace mode, prefer base.mp4 even if src was already mp4 (we will do an atomic replace at the end).
        final_path = desired
    else:
        # Keep original; avoid overwriting existing outputs.
        final_path = desired
        if os.path.abspath(final_path) == os.path.abspath(src_path):
            final_path = base + ".browser" + target_ext
        final_path = _unique_path(final_path)

    tmp_key = sha1_text(os.path.abspath(src_path) + "|browser|" + final_path)
    tmp_path = os.path.join(transcode_cache_dir(), f"{tmp_key}.tmp{target_ext}")
    _safe_remove(tmp_path)
    return final_path, tmp_path


def _finalize_video_output(src_path: str, out_final: str, tmp_path: str) -> str:
    if REPLACE_ORIGINAL:
        # Delete original only after we have a valid tmp output.
        if os.path.abspath(out_final) == os.path.abspath(src_path):
            # Replace in-place.
            try:
                os.replace(tmp_path, src_path)
            except Exception:
                # Fall back to explicit remove then replace
                try:
                    _safe_remove(src_path)
                except Exception:
                    pass
                os.replace(tmp_path, src_path)
            return src_path

        # Replace into base.mp4 and then delete original.
        os.replace(tmp_path, out_final)
        _safe_remove(src_path)
        return out_final

    os.replace(tmp_path, out_final)
    return out_final


def _mark_video_job_done(task_id: str, *, msg: str, state: str, src_path: str, out_path: str) -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return
        t.video_post_done += 1
        t.video_post_state = state
        t.video_post_message = msg
        t.video_post_current_file = ""
        t.video_post_current_done = 0
        t.video_post_current_total = None

        if out_path and src_path and os.path.abspath(out_path) != os.path.abspath(src_path):
            try:
                t.downloaded_files = [out_path if os.path.abspath(p) == os.path.abspath(src_path) else p for p in t.downloaded_files]
            except Exception:
                pass

        # If downloads are finished and all post jobs are done, mark task finished.
        if t.downloads_complete and t.video_post_done >= t.video_post_total and t.state not in ("done", "error", "canceled"):
            t.state = "done"
            t.message = "Finished"


def _ensure_browser_compatible_video(task_id: str, src_path: str) -> str:
    # If already browser compatible (mp4/webm with compatible codecs), skip.
    ext = os.path.splitext(src_path)[1].lower().lstrip(".")
    si = _primary_stream_info(src_path)
    if ext in ("mp4", "m4v", "mov", "webm"):
        v_ok, a_ok = _browser_compatible_for_target(ext, si.get("v_codec"), si.get("v_pix_fmt"), si.get("a_codec"))
        if v_ok and a_ok:
            return src_path

    out_final, tmp_path = _video_output_paths(src_path)

    # Decide transmux vs transcode into mp4.
    v_ok_t, a_ok_t = _browser_compatible_for_target(VIDEO_BROWSER_TARGET_EXT, si.get("v_codec"), si.get("v_pix_fmt"), si.get("a_codec"))
    dur = _probe_duration_seconds(src_path)

    t = get_task(task_id)
    cancel_ev = t.cancel_event if t else threading.Event()

    if v_ok_t and a_ok_t:
        args = _build_transmux_args(src_path, VIDEO_BROWSER_TARGET_EXT, tmp_path, first_audio_only=True)
        ok, err = _run_ffmpeg_to_tmp_with_progress(
            args,
            tmp_path,
            stage="transmuxing",
            src_path=src_path,
            task_id=task_id,
            cancel_event=cancel_ev,
            total_duration_s=dur,
        )
        if not ok:
            if (err or "").strip().lower() == "canceled":
                raise Cancelled("Canceled")
            raise RuntimeError(err.strip() or "transmux failed")
    else:
        args = _build_smart_transcode_args(src_path, VIDEO_BROWSER_TARGET_EXT, tmp_path, video_ok=v_ok_t, audio_ok=a_ok_t)
        ok, err = _run_ffmpeg_to_tmp_with_progress(
            args,
            tmp_path,
            stage="transcoding",
            src_path=src_path,
            task_id=task_id,
            cancel_event=cancel_ev,
            total_duration_s=dur,
        )
        if not ok:
            if (err or "").strip().lower() == "canceled":
                raise Cancelled("Canceled")
            # Fall back to full transcode
            _safe_remove(tmp_path)
            args2 = _build_transcode_args(src_path, VIDEO_BROWSER_TARGET_EXT, tmp_path)
            ok2, err2 = _run_ffmpeg_to_tmp_with_progress(
                args2,
                tmp_path,
                stage="transcoding",
                src_path=src_path,
                task_id=task_id,
                cancel_event=cancel_ev,
                total_duration_s=dur,
            )
            if not ok2:
                if (err2 or "").strip().lower() == "canceled":
                    raise Cancelled("Canceled")
                raise RuntimeError((err2 or err or "transcode failed").strip())

    return _finalize_video_output(src_path, out_final, tmp_path)


def _video_post_worker() -> None:
    while True:
        job = _VIDEO_POST_QUEUE.get()
        try:
            task_id, src_path = job
        except Exception:
            _VIDEO_POST_QUEUE.task_done()
            continue

        try:
            t = get_task(task_id)
            if not t:
                continue
            if t.cancel_event.is_set() or t.state in ("canceled", "error"):
                if t.cancel_event.is_set() and t.state != "canceled":
                    set_task(task_id, state="canceled", message="Canceled", video_post_state="canceled", video_post_message="Canceled")
                _mark_video_job_done(task_id, msg="Canceled" if t.cancel_event.is_set() else "Skipped", state=("canceled" if t.cancel_event.is_set() else "skipped"), src_path=src_path, out_path=src_path)
                continue

            # Mark in-progress
            set_task(task_id, video_post_state="starting", video_post_message="Checking browser compatibility", video_post_current_file=os.path.basename(src_path))

            try:
                out_path = _ensure_browser_compatible_video(task_id, src_path)
                if os.path.abspath(out_path) == os.path.abspath(src_path):
                    _mark_video_job_done(task_id, msg="Already browser compatible", state="skipped", src_path=src_path, out_path=out_path)
                else:
                    _mark_video_job_done(task_id, msg="Browser compatible output created", state="done", src_path=src_path, out_path=out_path)
            except Cancelled:
                set_task(task_id, state="canceled", message="Canceled", video_post_state="canceled", video_post_message="Canceled")
                _mark_video_job_done(task_id, msg="Canceled", state="canceled", src_path=src_path, out_path=src_path)
            except Exception as e:
                # Record error but allow other tasks to continue
                set_task(task_id, state="error", message=str(e), video_post_state="error", video_post_message=str(e))
                _mark_video_job_done(task_id, msg=str(e), state="error", src_path=src_path, out_path=src_path)

        finally:
            _VIDEO_POST_QUEUE.task_done()







__all__ = [name for name in globals() if not name.startswith("__")]
