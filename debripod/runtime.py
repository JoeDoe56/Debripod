
import os
import re
import time
import uuid
import json
import threading
import hashlib
import base64
import math
import mimetypes
import subprocess
import queue
import asyncio
import concurrent.futures
import shutil
import logging
from typing import Dict, Optional, List, Tuple, Any
from urllib.parse import quote, unquote, urlparse

import requests
from flask import Flask, request, redirect, url_for, render_template, abort, Response, jsonify

from .Library.search_cache import (
    _SEARCH_DISK_LOCK,
    _atomic_write_json,
    _disk_cache_get,
    _disk_cache_set,
    _load_search_history,
    _make_search_cache_key,
    _read_json_file,
    clear_search_history_and_cache,
    configure_search_cache,
    record_search_history,
)
from .Library.playlists import (
    add_tracks_to_playlist,
    configure_playlists,
    create_root_playlist,
    create_root_smart_playlist,
    delete_root_playlist,
    is_smart_playlist_rel,
    load_smart_playlist_rules,
    playlist_tracks_for_root,
    remove_tracks_from_playlist,
    rename_root_playlist,
    save_smart_playlist_rules,
    scan_root_playlists,
    smart_playlist_tracks_for_root,
)
from .Library.metadata import (
    art_cache_path,
    art_for_media_path,
    configure_metadata,
    extract_art,
    file_meta_cached,
    pick_folder_art,
)
from .Library.index import (
    build_index_for_root,
    clear_index_cache,
    configure_library_index,
    ensure_index_async,
    get_index,
    index_building_status,
    set_index_cache,
    track_sort_key,
)
from .Library.roots import configure_library_roots, root_by_id, roots, safe_path_join
from .media_types import (
    AUDIO_EXTS,
    VIDEO_EXTS,
)
from .paths import art_cache_dir, cache_dir, configure_paths, transcode_cache_dir
from .Routes.icons import ICON_VERSION, register_icon_routes
from .Routes.lastfm import register_lastfm_routes
from .Routes.shell import register_shell_routes
from .Routes.tasks import register_task_routes
from .Services.knaben import configure_knaben, knaben_search, make_magnet
from .Services.lastfm import (
    configure_lastfm,
    initialize_lastfm_cache,
    lastfm_auth_finish,
    lastfm_auth_start,
    lastfm_enabled,
    lastfm_is_loved,
    lastfm_love_track,
    lastfm_loved_updated,
    lastfm_remote_is_loved,
    lastfm_scrobble,
    lastfm_session_key,
    lastfm_set_loved_local,
    lastfm_sync_loved_from_remote,
    lastfm_unlove_track,
    lastfm_update_now_playing,
    lastfm_username,
    _lastfm_async,
)
from .Services.real_debrid import configure_real_debrid, rd_headers, rd_request
from .Services.soulseek import (
    SoulseekService,
    _slsk_annotate_file_with_download_state,
    _slsk_expected_incoming_path,
    _slsk_group_items_to_dirs,
    _slsk_group_snapshot_to_users,
    _slsk_guess_kind_ext_attrs,
    _slsk_norm_remote_path,
    _slsk_relative_under_directory,
    _slsk_session_create,
    _slsk_session_mark_done,
    _slsk_session_snapshot,
    _slsk_session_touch,
    _slsk_task_download_dir,
    configure_aioslsk_logging,
    configure_soulseek_module,
    soulseek_incoming_dir,
)
from .Services.youtube import (
    _prepare_youtube_stream_file,
    _search_youtube_cached,
    _standardize_youtube_results,
    _yt_dlp_base_args,
    _yt_selected_output_ext,
    _yt_stream_format_selector,
    _youtube_download_root,
    configure_youtube,
    youtube_channel_browse,
    youtube_load_result_files,
    ytdlp_list_formats,
)
from .Tasks.manager import (
    TASKS,
    TASKS_LOCK,
    Task,
    _get_file_control,
    _set_file_control,
    _update_task_file_entry,
    cancel_task,
    clear_all_tasks,
    clear_task,
    configure_task_manager,
    get_task,
    list_tasks,
    pause_task,
    resume_task,
    set_task,
    task_file_action,
    task_public_dict,
)
from .utils import (
    human_bytes,
    human_rate,
    is_audio,
    is_playlist_file,
    is_video,
    sanitize_filename,
    sanitize_folder_name,
    sha1_text,
)
from .playback.streaming import pick_mime, range_response
from .playback.state import (
    PLAYBACK_STATE,
    PLAYBACK_STATE_LOCK,
    configure_playback_state,
    load_playback_state,
    playback_snapshot_public,
    playback_update_from_client,
    save_playback_state_best_effort,
)
from .playback.transcoding import (
    _browser_compatible_for_target,
    _build_smart_transcode_args,
    _build_transcode_args,
    _build_transmux_args,
    _primary_stream_info,
    configure_transcoding,
    last_ffmpeg_error,
    lock_for_key,
    transcode_if_needed,
)
from .playback.probe import configure_probe, ffprobe_json, run_cmd

# =========================
# Runtime config
# =========================
# Auto infer version from filename like debripod112.py.
_fn = os.path.basename(__file__)
_m = re.search(r"debripod(\d+)", _fn, re.IGNORECASE)
VERSION = _m.group(1) if _m else "dev"
del _fn, _m

# Defaults live in debripod.config and are overlaid by config JSON files.
try:
    from .config import CONFIG_KEYS, apply_config_to_module
    globals().update({key: None for key in CONFIG_KEYS})
    apply_config_to_module(globals())
except Exception as _config_error:
    print(f"Debripod config warning: {_config_error}")
configure_library_roots(lambda: LIBRARY_FOLDERS)
configure_playlists(
    file_meta_provider=lambda abs_path: file_meta_cached(abs_path),
    track_sort_key_provider=lambda track: track_sort_key(track),
    is_loved_provider=lambda artist, title, album: lastfm_is_loved(artist, title, album),
    get_index_provider=lambda root_id: get_index(root_id),
    build_index_provider=lambda root_abs: build_index_for_root(root_abs),
    set_index_provider=lambda root_id, data: set_index_cache(root_id, data),
)
configure_real_debrid(
    api_key_provider=lambda: REAL_DEBRID_API_KEY,
    base_url_provider=lambda: RD_BASE,
    timeout_provider=lambda: REQUEST_TIMEOUT_SECONDS,
)
configure_knaben(
    api_key_provider=lambda: KNABEN_API_KEY,
    min_interval_provider=lambda: KNABEN_MIN_SECONDS_BETWEEN_REQUESTS,
    cache_ttl_provider=lambda: KNABEN_CACHE_TTL_SECONDS,
    max_retries_provider=lambda: KNABEN_MAX_RETRIES,
    api_base_provider=lambda: KNABEN_API_BASE,
    web_base_provider=lambda: KNABEN_WEB_BASE,
    timeout_provider=lambda: REQUEST_TIMEOUT_SECONDS,
    results_per_page_provider=lambda: RESULTS_PER_PAGE,
)
configure_youtube(
    ytdlp_cmd_provider=lambda: YTDLP_CMD,
    youtube_download_dir_provider=lambda: YOUTUBE_DOWNLOAD_DIR,
    download_dir_provider=lambda: DOWNLOAD_DIR,
    stream_cache_subdir_provider=lambda: YOUTUBE_STREAM_CACHE_SUBDIR,
    web_base_provider=lambda: YOUTUBE_WEB_BASE,
    search_limit_provider=lambda: YOUTUBE_SEARCH_LIMIT,
    channel_browse_limit_provider=lambda: YOUTUBE_CHANNEL_BROWSE_LIMIT,
    request_headers_provider=lambda: YOUTUBE_REQUEST_HEADERS,
    timeout_provider=lambda: REQUEST_TIMEOUT_SECONDS,
    ffmpeg_path_provider=lambda: FFMPEG_PATH,
)
configure_soulseek_module(
    download_dir=SOULSEEK_DOWNLOAD_DIR,
    search_idle_stop_sec=SOULSEEK_SEARCH_IDLE_STOP_SEC,
    search_hard_max_sec=SOULSEEK_SEARCH_HARD_MAX_SEC,
    tasks=TASKS,
    tasks_lock=TASKS_LOCK,
    get_task_func=get_task,
    set_task_func=set_task,
    set_file_control_func=_set_file_control,
    get_file_control_func=_get_file_control,
)
configure_metadata(ffmpeg_path_provider=lambda: FFMPEG_PATH)
configure_library_index(cache_dir_name_provider=lambda: CACHE_DIR_NAME)
configure_playback_state(
    search_stream_root_id_provider=lambda: SEARCH_STREAM_ROOT_ID,
    search_stream_get_or_restore_provider=lambda rel: _search_stream_get_or_restore(rel),
)
configure_probe(ffprobe_path_provider=lambda: FFPROBE_PATH)
configure_paths(
    download_dir_provider=lambda: DOWNLOAD_DIR,
    cache_dir_name_provider=lambda: CACHE_DIR_NAME,
)
configure_transcoding(
    audio_transcode_provider=lambda: AUDIO_TRANSCODE,
    ffmpeg_path_provider=lambda: FFMPEG_PATH,
    video_browser_target_ext_provider=lambda: VIDEO_BROWSER_TARGET_EXT,
)
configure_lastfm(
    api_key=LASTFM_API_KEY,
    api_secret=LASTFM_API_SECRET,
    session_key=LASTFM_SESSION_KEY,
    callback_url=LASTFM_CALLBACK_URL,
    api_root=LASTFM_API_ROOT,
    request_timeout_seconds=LASTFM_REQUEST_TIMEOUT_SECONDS,
)

def ensure_dirs() -> None:
    if not os.path.isabs(DOWNLOAD_DIR):
        raise ValueError("DOWNLOAD_DIR must be an absolute path")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(SOULSEEK_DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(soulseek_incoming_dir(), exist_ok=True)
    os.makedirs(cache_dir(), exist_ok=True)
    os.makedirs(transcode_cache_dir(), exist_ok=True)
    os.makedirs(art_cache_dir(), exist_ok=True)

    configure_lastfm(
        api_key=LASTFM_API_KEY,
        api_secret=LASTFM_API_SECRET,
        session_key=LASTFM_SESSION_KEY,
        callback_url=LASTFM_CALLBACK_URL,
        api_root=LASTFM_API_ROOT,
        request_timeout_seconds=LASTFM_REQUEST_TIMEOUT_SECONDS,
        session_cache_path=os.path.join(cache_dir(), "lastfm_session.json"),
        loved_db_path=os.path.join(cache_dir(), "lastfm_loved.json"),
    )
    initialize_lastfm_cache()
    # Best-effort: refresh loved cache occasionally so the UI shows existing likes
    try:
        last_upd = int(lastfm_loved_updated() or 0)
        if lastfm_enabled() and (time.time() - float(last_upd or 0)) > 6 * 3600:
            _lastfm_async(lastfm_sync_loved_from_remote, lastfm_username())
    except Exception:
        pass


configure_search_cache(
    cache_dir,
    history_max_items_provider=lambda: SEARCH_HISTORY_MAX_ITEMS,
    disk_cache_ttl_seconds_provider=lambda: SEARCH_DISK_CACHE_TTL_SECONDS,
)


# =========================
# Real Debrid task tracking
# =========================
class Cancelled(Exception):
    pass


class CancelledFile(Exception):
    pass


def check_canceled(t: Task) -> None:
    if t.cancel_event.is_set():
        raise Cancelled("Canceled")



# =========================
# Soulseek (aioslsk) service
# =========================
SOULSEEK_SERVICE = None  # initialized in main()
configure_task_manager(
    soulseek_service_provider=lambda: SOULSEEK_SERVICE,
    retry_worker_provider=lambda source: youtube_download_remaining_worker if source == "youtube" else rd_download_remaining_worker,
)

# =========================
# Soulseek streaming search sessions
# =========================
_SLSK_SESS_LOCK = threading.Lock()
_SLSK_SESSIONS: Dict[str, Dict[str, Any]] = {}

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


def _youtube_ytdlp_parse_int(raw: Any) -> int:
    try:
        s = str(raw or '').strip()
        if not s or s.lower() in {'none', 'na', 'n/a'}:
            return 0
        return int(float(s))
    except Exception:
        return 0


def _youtube_ytdlp_parse_speed(raw: Any) -> float:
    try:
        s = str(raw or '').strip()
        if not s or s.lower() in {'none', 'na', 'n/a'}:
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def _youtube_find_downloaded_path(task_dir: str, base_title: str, preferred_ext: str = '') -> str:
    folder = str(task_dir or '').strip() or '.'
    stem = sanitize_filename(str(base_title or 'youtube'))
    pref = str(preferred_ext or '').strip().lower().lstrip('.')
    try:
        names = sorted(os.listdir(folder), key=lambda x: os.path.getmtime(os.path.join(folder, x)), reverse=True)
    except Exception:
        return ''
    preferred = []
    fallback = []
    for name in names:
        if not name.startswith(stem):
            continue
        cand = os.path.join(folder, name)
        if not os.path.isfile(cand):
            continue
        ext = os.path.splitext(name)[1].lstrip('.').lower()
        if pref and ext == pref:
            preferred.append(cand)
        else:
            fallback.append(cand)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return ''


def _youtube_pick_next_entry(task_id: str) -> Optional[Dict[str, Any]]:
    with TASKS_LOCK:
        tcur = TASKS.get(task_id)
        entries = list(getattr(tcur, 'rd_files', []) or []) if tcur else []
    for e in entries:
        file_id = str(e.get('file_id') or '')
        st = str(e.get('state') or '').lower()
        ctl = _get_file_control(task_id, file_id) if file_id else {}
        if ctl.get('canceled'):
            _update_task_file_entry(task_id, 'rd_files', file_id, state='canceled', canceled=True, error='')
            continue
        if st == 'queued':
            return e
        if st == 'paused' and not ctl.get('paused'):
            return e
    return None


def _youtube_run_download(task_id: str, entry: Dict[str, Any], seq: int, total_count: int) -> Optional[str]:
    task = get_task(task_id)
    if not task:
        return None
    file_id = str(entry.get('file_id') or '')
    if not file_id:
        raise RuntimeError('Missing file id')
    ctl = _get_file_control(task_id, file_id)
    if ctl.get('canceled'):
        _update_task_file_entry(task_id, 'rd_files', file_id, state='canceled', canceled=True, error='')
        return None
    if ctl.get('paused'):
        _update_task_file_entry(task_id, 'rd_files', file_id, state='paused', paused=True, error='')
        return None

    title = sanitize_filename(str(entry.get('name') or entry.get('title') or 'youtube'))
    ext = str(entry.get('ext') or '').strip().lower() or 'mp4'
    format_id = str(entry.get('format_id') or entry.get('itag') or entry.get('file_id') or '').strip()
    media = str(entry.get('media') or '').strip().lower()
    out_tpl = os.path.join(task.task_dir, title + '.%(ext)s')
    preferred_out = os.path.join(task.task_dir, title + '.' + ext)

    args = _yt_dlp_base_args()
    selector = _yt_stream_format_selector({'format_id': format_id, 'itag': format_id, 'file_id': format_id, 'media': media, 'ext': ext})
    if selector:
        args += ['-f', selector]
    if media != 'audio':
        args += ['--merge-output-format', _yt_selected_output_ext({'media': media, 'ext': ext})]
    args += [
        '--newline',
        '--progress-template', 'download:dp:%(progress.downloaded_bytes)s:%(progress.total_bytes)s:%(progress.speed)s',
        '--print', 'after_move:dp:filepath:%(filepath)s',
        '-o', out_tpl,
        str(entry.get('url') or task.magnet or ''),
    ]

    initial_total = int(entry.get('total') or 0)
    _update_task_file_entry(task_id, 'rd_files', file_id, state='downloading', paused=False, canceled=False, error='', out_path=preferred_out, name=os.path.basename(preferred_out), done=0, speed=0.0, total=initial_total)
    set_task(task_id, current_file=os.path.basename(preferred_out), current_done=0, current_total=(initial_total or None), state='downloading', message=f'Downloading {seq} of {total_count}')
    _rd_recompute_overall_from_files(task_id)

    proc = subprocess.Popen([YTDLP_CMD] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', bufsize=1)
    actual_path = ''
    last_error = ''
    pause_requested = False
    cancel_requested = False
    try:
        while True:
            task = get_task(task_id)
            if not task:
                cancel_requested = True
                break
            ctl = _get_file_control(task_id, file_id)
            if task.cancel_event.is_set():
                cancel_requested = True
            elif ctl.get('canceled'):
                cancel_requested = True
            elif task.pause_event.is_set() or ctl.get('paused'):
                pause_requested = True
            if pause_requested or cancel_requested:
                try:
                    proc.terminate()
                except Exception:
                    pass
            line = proc.stdout.readline() if proc.stdout else ''
            if line:
                s = line.strip()
                if s.startswith('download:dp:'):
                    parts = s.split(':', 4)
                    if len(parts) >= 5:
                        done = _youtube_ytdlp_parse_int(parts[2])
                        total = _youtube_ytdlp_parse_int(parts[3]) or int(entry.get('total') or 0)
                        speed = _youtube_ytdlp_parse_speed(parts[4])
                        _update_task_file_entry(task_id, 'rd_files', file_id, state='downloading', done=done, total=total, speed=speed, error='')
                        set_task(task_id, current_done=done, current_total=(total or None), message=f'Downloading {seq} of {total_count}')
                        _rd_recompute_overall_from_files(task_id)
                elif s.startswith('dp:filepath:'):
                    actual_path = s.split(':', 2)[2].strip()
                elif 'ERROR:' in s:
                    last_error = s.split('ERROR:', 1)[1].strip() or s
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.05)
        rc = proc.wait()
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass

    if cancel_requested:
        _update_task_file_entry(task_id, 'rd_files', file_id, state='canceled', canceled=True, error='')
        _rd_recompute_overall_from_files(task_id)
        return None
    if pause_requested:
        _update_task_file_entry(task_id, 'rd_files', file_id, state='paused', paused=True, error='')
        _rd_recompute_overall_from_files(task_id)
        return None
    if rc != 0:
        raise RuntimeError(last_error or 'yt-dlp failed')

    actual = str(actual_path or '').strip()
    if not actual or not os.path.exists(actual):
        actual = preferred_out if os.path.exists(preferred_out) else _youtube_find_downloaded_path(task.task_dir, title, ext)
    try:
        sz = os.path.getsize(actual) if actual and os.path.exists(actual) else int(entry.get('total') or 0)
    except Exception:
        sz = int(entry.get('total') or 0)
    final_name = os.path.basename(actual) if actual else os.path.basename(preferred_out)
    final_ext = os.path.splitext(final_name)[1].lstrip('.').lower()
    _update_task_file_entry(task_id, 'rd_files', file_id, state='complete', done=sz, total=sz, speed=0.0, out_path=actual or preferred_out, name=final_name, ext=(final_ext or ext), error='', paused=False, canceled=False)
    _rd_recompute_overall_from_files(task_id)
    return actual or preferred_out


def _youtube_finalize_task_state(task_id: str, default_message: str = 'Finished') -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        entries = list(getattr(t, 'rd_files', []) or []) if t else []
    if not entries:
        set_task(task_id, state='error', message='No YouTube formats selected', current_file='', current_done=0, current_total=None)
        return
    any_failed = any(str(e.get('state') or '').lower() == 'failed' for e in entries)
    any_active = any(str(e.get('state') or '').lower() in {'queued', 'requesting', 'downloading'} for e in entries)
    any_paused = any(str(e.get('state') or '').lower() == 'paused' for e in entries)
    all_terminal = all(str(e.get('state') or '').lower() in {'complete', 'canceled', 'failed', 'paused'} for e in entries)
    completed = []
    for e in entries:
        if str(e.get('state') or '').lower() == 'complete':
            p = str(e.get('out_path') or '').strip()
            if p:
                completed.append(p)
    seen = set()
    uniq = []
    for p in completed:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    set_task(task_id, downloaded_files=uniq, current_file='', current_done=0, current_total=None, downloads_complete=bool(all_terminal and not any_failed and not any_active and not any_paused))
    if any_active:
        set_task(task_id, state='downloading', message='Downloading')
    elif any_paused:
        set_task(task_id, state='paused', message='Paused')
    elif any_failed and uniq:
        set_task(task_id, state='error', message='Some YouTube files failed. You can retry failed files.')
    elif any_failed:
        set_task(task_id, state='error', message='YouTube download failed')
    elif uniq or all(str(e.get('state') or '').lower() in {'complete', 'canceled'} for e in entries):
        set_task(task_id, state='done', message=default_message)
    else:
        set_task(task_id, state='error', message='YouTube download failed')


def _youtube_download_from_queue(task_id: str) -> List[str]:
    completed_paths: List[str] = []
    while True:
        task = get_task(task_id)
        if not task:
            break
        check_canceled(task)
        while task.pause_event.is_set():
            set_task(task_id, state='paused', message='Paused')
            time.sleep(0.2)
            task = get_task(task_id)
            if not task:
                return completed_paths
            check_canceled(task)
        nxt = _youtube_pick_next_entry(task_id)
        if not nxt:
            break
        with TASKS_LOCK:
            tcur = TASKS.get(task_id)
            entries = list(getattr(tcur, 'rd_files', []) or []) if tcur else []
        total_count = len(entries)
        seq = 1
        fid = str(nxt.get('file_id') or '')
        for idx, cur in enumerate(entries, start=1):
            if str(cur.get('file_id') or '') == fid:
                seq = idx
                break
        try:
            out_path = _youtube_run_download(task_id, nxt, seq, total_count)
            if out_path:
                completed_paths.append(out_path)
        except Cancelled:
            raise
        except Exception as e:
            _update_task_file_entry(task_id, 'rd_files', fid, state='failed', error=str(e), paused=False)
            _rd_recompute_overall_from_files(task_id)
    _youtube_finalize_task_state(task_id)
    return completed_paths


def youtube_download_remaining_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return
    if (task.source or '').lower() != 'youtube':
        return
    try:
        set_task(task_id, state='downloading', message='Retrying queued YouTube files')
        _youtube_download_from_queue(task_id)
    except Cancelled:
        set_task(task_id, state='canceled', message='Canceled', current_file='', current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state='error', message=str(e), current_file='', current_done=0, current_total=None)


def youtube_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return
    try:
        entries = list(getattr(task, 'rd_files', []) or [])
        if not entries:
            raise RuntimeError('No YouTube formats selected')
        set_task(task_id, state='downloading', message=f'Downloading {len(entries)} YouTube file(s)', overall_done=0, overall_total=None)
        _youtube_download_from_queue(task_id)
    except Cancelled:
        set_task(task_id, state='canceled', message='Canceled', current_file='', current_done=0, current_total=None)
    except Exception as e:
        set_task(task_id, state='error', message=str(e), current_file='', current_done=0, current_total=None)


# =========================
# Flask app and templates
# =========================
app = Flask(__name__)


class _DropStaticAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            return " /static/" not in msg
        except Exception:
            return True


logging.getLogger("werkzeug").addFilter(_DropStaticAccessLogFilter())

SEARCH_STREAMS: Dict[str, Dict[str, Any]] = {}
SEARCH_STREAMS_LOCK = threading.Lock()

MCP_SESSIONS: Dict[str, Dict[str, Any]] = {}
MCP_SESSIONS_LOCK = threading.Lock()


def _guess_media_from_name(name: str) -> str:
    ext = os.path.splitext(str(name or "").strip().lower())[1]
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    mime, _ = mimetypes.guess_type(str(name or ""))
    if mime:
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"
    return ""


def _search_stream_rel(session_id: str, item_id: str) -> str:
    return f"{session_id}/{item_id}"


def _search_stream_cleanup_locked(now_ts: Optional[float] = None) -> None:
    if now_ts is None:
        now_ts = time.time()
    stale = []
    for sid, sess in SEARCH_STREAMS.items():
        try:
            ts = float(sess.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        if (now_ts - ts) > SEARCH_STREAM_SESSION_TTL_SECONDS:
            stale.append(sid)
    for sid in stale:
        SEARCH_STREAMS.pop(sid, None)


def _search_stream_get(rel: str) -> Optional[Dict[str, Any]]:
    raw = str(rel or "").strip().strip("/")
    if not raw or "/" not in raw:
        return None
    session_id, item_id = raw.split("/", 1)
    if not session_id or not item_id:
        return None
    with SEARCH_STREAMS_LOCK:
        _search_stream_cleanup_locked()
        sess = SEARCH_STREAMS.get(session_id)
        if not isinstance(sess, dict):
            return None
        sess["ts"] = time.time()
        for it in (sess.get("items") or []):
            if isinstance(it, dict) and str(it.get("item_id") or "") == item_id:
                out = dict(it)
                out["session_id"] = session_id
                out["queue_index"] = int(it.get("queue_index") or 0)
                out["queue_count"] = len(sess.get("items") or [])
                out["session_title"] = str(sess.get("title") or "")
                return out
    return None


def _playback_stream_item_for_rel(rel: str) -> Optional[Dict[str, Any]]:
    raw = str(rel or "").strip().strip("/")
    if not raw:
        return None
    with PLAYBACK_STATE_LOCK:
        candidates = []
        now = PLAYBACK_STATE.get("now")
        if isinstance(now, dict):
            candidates.append(now)
        recent = PLAYBACK_STATE.get("recent") or []
        if isinstance(recent, list):
            candidates.extend([it for it in recent if isinstance(it, dict)])
    for entry in candidates:
        try:
            if str(entry.get("root_id") or "").strip() != SEARCH_STREAM_ROOT_ID:
                continue
            if str(entry.get("rel") or "").strip().strip("/") != raw:
                continue
            stream_item = entry.get("_stream_item")
            if isinstance(stream_item, dict):
                out = dict(stream_item)
                sess_id, item_id = raw.split("/", 1)
                out["session_id"] = sess_id
                out["item_id"] = str(out.get("item_id") or item_id)
                out["queue_index"] = int(out.get("queue_index") or 0)
                out["queue_count"] = int(out.get("queue_count") or 1)
                return out
        except Exception:
            continue
    return None


def _search_stream_get_or_restore(rel: str) -> Optional[Dict[str, Any]]:
    it = _search_stream_get(rel)
    if it:
        return it
    restored = _playback_stream_item_for_rel(rel)
    if not restored:
        return None
    try:
        raw = str(rel or "").strip().strip("/")
        session_id, item_id = raw.split("/", 1)
    except Exception:
        return restored
    with SEARCH_STREAMS_LOCK:
        _search_stream_cleanup_locked()
        sess = SEARCH_STREAMS.get(session_id)
        if not isinstance(sess, dict):
            sess = {"ts": time.time(), "title": str(restored.get("session_title") or restored.get("title") or restored.get("album") or "Search stream"), "source": str(restored.get("source") or ""), "items": []}
            SEARCH_STREAMS[session_id] = sess
        sess["ts"] = time.time()
        items = list(sess.get("items") or [])
        if not any(isinstance(x, dict) and str(x.get("item_id") or "") == item_id for x in items):
            add = dict(restored)
            add["item_id"] = item_id
            items.append(add)
            sess["items"] = items
    return _search_stream_get(rel) or restored


def _rd_wait_for_selected_links(torrent_id: str, selected_ids: List[int], timeout_seconds: int = MAX_TORRENT_WAIT_SECONDS) -> Tuple[dict, List[str]]:
    wanted = [int(x) for x in (selected_ids or []) if str(x).strip()]
    end_time = time.time() + max(30, int(timeout_seconds or 0))
    while time.time() < end_time:
        info = rd_torrent_info(torrent_id)
        links = info.get("links") or []
        if info.get("status") == "downloaded" and isinstance(links, list) and links:
            if wanted and len(links) == len(wanted):
                return info, [str(x) for x in links]
            if not wanted:
                return info, [str(x) for x in links]
        status = str(info.get("status") or "")
        if status in {"error", "virus", "dead"}:
            raise RuntimeError(f"Real Debrid reported status: {status}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError("Timed out waiting for Real Debrid stream links")


def _engine_prepare_stream_session(payload: dict) -> dict:
    src = str(payload.get("source") or "").strip().lower()
    if src == "youtube":
        url = str(payload.get('url') or '').strip()
        selected = payload.get('selected') or []
        title = str(payload.get('title') or payload.get('directory_title') or 'YouTube').strip() or 'YouTube'
        selected_fallback_url = ''
        items = []
        for it in selected:
            if not isinstance(it, dict):
                continue
            format_id = str(it.get('format_id') or it.get('itag') or it.get('file_id') or '').strip()
            if not format_id:
                continue
            name = str(it.get('name') or it.get('title') or ('Format ' + format_id)).strip() or 'Format'
            media = str(it.get('media') or '').strip().lower() or ('audio' if str(it.get('ext') or '').lower() in ('mp3','m4a','aac','ogg','opus','wav','flac') else 'video')
            item_url = str(it.get('url') or '').strip()
            if not selected_fallback_url and item_url:
                selected_fallback_url = item_url
            stream_source_url = url or item_url
            if not stream_source_url:
                continue
            item_id = uuid.uuid4().hex[:12]
            items.append({
                'item_id': item_id,
                'queue_index': len(items),
                'media': media,
                'name': name,
                'title': title,
                'artist': str(payload.get('channel') or payload.get('user') or ''),
                'album': title,
                'art': str(payload.get('thumbnail') or ''),
                'size': int(it.get('size') or 0) if str(it.get('size') or '').strip() else 0,
                'source': src,
                'streamed': True,
                'ext': str(it.get('ext') or '').lower(),
                'quality': str(it.get('quality') or it.get('bitrate') or ''),
                'url': stream_source_url,
                'youtube_url': stream_source_url,
                'format_id': format_id,
                'itag': format_id,
                'mime': '',
                'requires_local_mux': bool(media != 'audio'),
            })
        if not items and selected_fallback_url:
            url = selected_fallback_url
        if not items:
            raise RuntimeError('No selected YouTube formats were streamable')
        session_id = uuid.uuid4().hex
        with SEARCH_STREAMS_LOCK:
            _search_stream_cleanup_locked()
            SEARCH_STREAMS[session_id] = {'ts': time.time(), 'title': title, 'source': src, 'items': items}
        out_items = []
        for it in items:
            rel = _search_stream_rel(session_id, str(it.get('item_id') or ''))
            out_items.append({'root_id': SEARCH_STREAM_ROOT_ID, 'rel': rel, 'media': it.get('media') or '', 'label': it.get('name') or '', 'title': it.get('title') or '', 'artist': it.get('artist') or '', 'album': it.get('album') or '', 'art': it.get('art') or '', 'streamed': True, 'source': it.get('source') or src, 'ext': it.get('ext') or '', 'quality': it.get('quality') or '', 'size': int(it.get('size') or 0)})
        return {'session_id': session_id, 'title': title, 'items': out_items}
    if src != "knaben":
        raise RuntimeError("Streaming is not available for this source")
    torrent_id = str(payload.get("torrent_id") or "").strip()
    selected = payload.get("selected") or []
    title = str(payload.get("title") or payload.get("directory_title") or payload.get("directory") or "Search stream").strip() or "Search stream"
    if not torrent_id:
        raise RuntimeError("Missing torrent id")
    clean_ids = []
    selected_by_id = {}
    for it in selected:
        if not isinstance(it, dict):
            continue
        try:
            fid = int(it.get("file_id"))
        except Exception:
            continue
        clean_ids.append(fid)
        selected_by_id[fid] = it
    if not clean_ids:
        raise RuntimeError("No files selected")
    rd_select_files(torrent_id, clean_ids)
    _info, links = _rd_wait_for_selected_links(torrent_id, clean_ids)
    items = []
    for idx, fid in enumerate(clean_ids):
        meta = selected_by_id.get(fid) or {}
        name = str(meta.get("name") or meta.get("title") or f"File {fid}")
        media = _guess_media_from_name(name)
        if media not in ("audio", "video"):
            continue
        un = rd_unrestrict(str(links[idx]))
        item_id = uuid.uuid4().hex[:12]
        items.append({
            "item_id": item_id,
            "queue_index": len(items),
            "media": media,
            "name": name,
            "title": name,
            "artist": "",
            "album": title,
            "art": "",
            "size": int(meta.get("size") or 0),
            "source": src,
            "streamed": True,
            "ext": str(meta.get("ext") or os.path.splitext(name)[1].lstrip('.')).lower(),
            "quality": str(meta.get("quality") or meta.get("bitrate") or ""),
            "url": str(un.get("download") or ""),
            "mime": str(un.get("mimeType") or un.get("mime_type") or ""),
        })
    if not items:
        raise RuntimeError("No selected files were streamable")
    session_id = uuid.uuid4().hex
    with SEARCH_STREAMS_LOCK:
        _search_stream_cleanup_locked()
        SEARCH_STREAMS[session_id] = {"ts": time.time(), "title": title, "source": src, "items": items}
    out_items = []
    for it in items:
        rel = _search_stream_rel(session_id, str(it.get("item_id") or ""))
        out_items.append({
            "root_id": SEARCH_STREAM_ROOT_ID,
            "rel": rel,
            "media": it.get("media") or "",
            "label": it.get("name") or "",
            "title": it.get("title") or "",
            "artist": it.get("artist") or "",
            "album": it.get("album") or "",
            "art": it.get("art") or "",
            "streamed": True,
            "source": it.get("source") or src,
            "ext": it.get("ext") or "",
            "quality": it.get("quality") or "",
            "size": int(it.get("size") or 0),
        })
    return {"session_id": session_id, "title": title, "items": out_items}


def _mcp_allowed_origins() -> List[str]:
    allowed = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
    try:
        allowed.add((request.host_url or '').rstrip('/'))
    except Exception:
        pass
    return sorted(x for x in allowed if x)


def _mcp_is_loopback_host(host: str) -> bool:
    h = str(host or '').strip().lower().strip('[]')
    if not h:
        return False
    return h in {'localhost', '127.0.0.1', '::1'}


def _mcp_validate_origin() -> Optional[Response]:
    origin = (request.headers.get('Origin') or '').strip()
    if not origin:
        return None
    if origin.lower() == 'null':
        return None
    try:
        parsed = urlparse(origin)
        norm = f"{parsed.scheme}://{parsed.netloc}"
        host = (parsed.hostname or '').strip().lower()
    except Exception:
        norm = origin
        host = ''
    if norm in _mcp_allowed_origins():
        return None
    if _mcp_is_loopback_host(host):
        return None
    try:
        req_host = (request.host or '').split(':', 1)[0].strip().lower()
    except Exception:
        req_host = ''
    if req_host and host and host == req_host:
        return None
    return Response('Forbidden', status=403, mimetype='text/plain')


def _mcp_prune_sessions() -> None:
    now = time.time()
    with MCP_SESSIONS_LOCK:
        stale = []
        for sid, sess in list(MCP_SESSIONS.items()):
            if not isinstance(sess, dict):
                stale.append(sid)
                continue
            try:
                updated = float(sess.get('updated') or sess.get('created') or 0.0)
            except Exception:
                updated = 0.0
            if updated <= 0 or (now - updated) > MCP_SESSION_TTL_SECONDS:
                stale.append(sid)
        for sid in stale:
            MCP_SESSIONS.pop(sid, None)


def _mcp_new_session(client_info: Optional[dict] = None) -> str:
    _mcp_prune_sessions()
    sid = uuid.uuid4().hex
    with MCP_SESSIONS_LOCK:
        MCP_SESSIONS[sid] = {
            'created': time.time(),
            'updated': time.time(),
            'initialized': False,
            'client_info': dict(client_info or {}),
        }
    return sid


def _mcp_touch_session(session_id: str) -> None:
    if not session_id:
        return
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        if isinstance(sess, dict):
            sess['updated'] = time.time()


def _mcp_get_session(session_id: str) -> Optional[dict]:
    if not session_id:
        return None
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        return dict(sess) if isinstance(sess, dict) else None


def _mcp_ensure_session(session_id: str = '', client_info: Optional[dict] = None) -> str:
    sid = str(session_id or '').strip()
    if sid and _mcp_get_session(sid) is not None:
        _mcp_touch_session(sid)
        return sid
    return _mcp_new_session(client_info)


def _mcp_set_initialized(session_id: str, initialized: bool = True) -> None:
    if not session_id:
        return
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        if isinstance(sess, dict):
            sess['initialized'] = bool(initialized)
            sess['updated'] = time.time()


def _mcp_json_response(payload: Any, status: int = 200, session_id: str = '') -> Response:
    resp = jsonify(payload)
    resp.status_code = status
    if session_id:
        resp.headers['Mcp-Session-Id'] = session_id
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


def _mcp_result(msg_id: Any, result: dict, session_id: str = '') -> Response:
    return _mcp_json_response({'jsonrpc': '2.0', 'id': msg_id, 'result': result}, 200, session_id=session_id)


def _mcp_error(msg_id: Any, code: int, message: str, *, data: Any = None, status: int = 400, session_id: str = '') -> Response:
    err = {'code': int(code), 'message': str(message)}
    if data is not None:
        err['data'] = data
    return _mcp_json_response({'jsonrpc': '2.0', 'id': msg_id, 'error': err}, status, session_id=session_id)


def _mcp_sse_response(session_id: str) -> Response:
    sid = _mcp_ensure_session(session_id)

    def gen():
        first = {
            'jsonrpc': '2.0',
            'method': 'notifications/message',
            'params': {
                'level': 'info',
                'data': {
                    'server': 'debripod',
                    'version': str(VERSION),
                    'endpoint': '/mcp',
                    'sessionId': sid,
                },
            },
        }
        yield ': connected\n\n'
        yield 'event: endpoint\n'
        yield 'data: ' + json.dumps({'path': '/mcp', 'sessionId': sid}, ensure_ascii=False) + '\n\n'
        yield 'event: message\n'
        yield 'data: ' + json.dumps(first, ensure_ascii=False) + '\n\n'
        while True:
            time.sleep(MCP_SSE_KEEPALIVE_SECONDS)
            _mcp_touch_session(sid)
            yield ': keepalive\n\n'

    resp = Response(gen(), status=200, mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Connection'] = 'keep-alive'
    resp.headers['X-Accel-Buffering'] = 'no'
    resp.headers['Mcp-Session-Id'] = sid
    return resp


def _mcp_tool_result(structured: dict, text: str, *, is_error: bool = False) -> dict:
    out = {
        'content': [{'type': 'text', 'text': str(text)}],
        'structuredContent': structured if isinstance(structured, dict) else {},
    }
    if is_error:
        out['isError'] = True
    return out


def _mcp_get_limit(args: dict) -> int:
    raw = MCP_SEARCH_RESULT_LIMIT
    if isinstance(args, dict) and args.get('limit') is not None:
        raw = args.get('limit')
    try:
        val = int(raw)
    except Exception:
        val = int(MCP_SEARCH_RESULT_LIMIT)
    return max(1, min(val, max(1, SOULSEEK_SEARCH_MAX_RESULTS)))


def _mcp_identifier_encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _mcp_identifier_decode(token: str) -> dict:
    s = str(token or '').strip()
    if not s:
        raise ValueError('Missing identifier')
    pad = '=' * ((4 - (len(s) % 4)) % 4)
    raw = base64.urlsafe_b64decode((s + pad).encode('ascii'))
    js = json.loads(raw.decode('utf-8'))
    if not isinstance(js, dict):
        raise ValueError('Invalid identifier')
    return js


def _mcp_group_soulseek_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    users: Dict[str, Dict[str, Any]] = {}
    for it in items or []:
        user = str(it.get('user') or '').strip()
        rp = _slsk_norm_remote_path(str(it.get('remote_path') or ''))
        if not user or not rp:
            continue
        try:
            size = int(it.get('size') or 0)
        except Exception:
            size = 0
        try:
            speed = int(it.get('speed') or 0)
        except Exception:
            speed = 0
        parts = rp.split('\\')
        fname = parts[-1] if parts else rp
        directory = '\\'.join(parts[:-1]) if len(parts) > 1 else ''
        kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)
        u = users.get(user)
        if not u:
            u = {'user': user, 'speed': speed, 'dirs': {}, 'total_size': 0, 'total_files': 0}
            users[user] = u
        u['speed'] = max(int(u.get('speed') or 0), speed)
        dirs = u.get('dirs') or {}
        d = dirs.get(directory)
        if not d:
            d = {'directory': directory, 'files': [], 'total_size': 0, 'total_files': 0}
            dirs[directory] = d
            u['dirs'] = dirs
        d['files'].append({
            'name': fname,
            'remote_path': rp,
            'size': size,
            'kind': kind,
            'ext': ext,
            'bitrate': br,
            'bit_depth': bd,
            'sample_rate': sr,
            'duration': dur,
            'vbr': vbr,
            'codec': codec,
        })
        d['total_size'] += size
        d['total_files'] += 1
        u['total_size'] = int(u.get('total_size') or 0) + size
        u['total_files'] = int(u.get('total_files') or 0) + 1
    out: List[Dict[str, Any]] = []
    for u in users.values():
        dirs_list = list((u.get('dirs') or {}).values())
        dirs_list.sort(key=lambda d: (int(d.get('total_size') or 0), int(d.get('total_files') or 0)), reverse=True)
        out.append({
            'user': u.get('user') or '',
            'speed': int(u.get('speed') or 0),
            'dirs': dirs_list,
            'total_size': int(u.get('total_size') or 0),
            'total_files': int(u.get('total_files') or 0),
        })
    out.sort(key=lambda u: (int(u.get('speed') or 0), int(u.get('total_size') or 0), str(u.get('user') or '').lower()), reverse=True)
    return out


def _mcp_search_knaben(query: str, limit: int) -> dict:
    results, err, remaining, reset = knaben_search(query, 1)
    trimmed = list(results or [])[:limit]
    items = []
    for it in trimmed:
        ident = _mcp_identifier_encode({
            'kind': 'knaben_item',
            'title': str(it.get('title') or 'Knaben item'),
            'magnet': str(it.get('magnet') or ''),
            'infohash': str(it.get('infohash') or ''),
        })
        items.append({
            'identifier': ident,
            'title': str(it.get('title') or ''),
            'size': it.get('size'),
            'seeders': it.get('seeders'),
            'leechers': it.get('leechers'),
            'category': str(it.get('category') or ''),
            'infohash': str(it.get('infohash') or ''),
            'href': str(it.get('href') or ''),
        })
    return {
        'engine': 'knaben',
        'query': query,
        'limit': limit,
        'error': str(err or ''),
        'rate_remaining': remaining,
        'rate_reset': reset,
        'results': items,
        'result_count': len(items),
    }


def _mcp_search_soulseek(query: str, limit: int) -> dict:
    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return {'engine': 'soulseek', 'query': query, 'limit': limit, 'results': [], 'result_count': 0, 'error': 'Soulseek service is not ready'}
    items = svc.search(query)
    grouped = _mcp_group_soulseek_items(items)
    out = []
    for u in grouped:
        user = str(u.get('user') or '')
        speed = int(u.get('speed') or 0)
        for d in (u.get('dirs') or []):
            files = list(d.get('files') or [])
            directory = str(d.get('directory') or '')
            ident = _mcp_identifier_encode({
                'kind': 'slsk_dir',
                'user': user,
                'directory': directory,
                'files': [{'remote_path': str(f.get('remote_path') or ''), 'size': int(f.get('size') or 0)} for f in files if str(f.get('remote_path') or '').strip()],
            })
            out.append({
                'identifier': ident,
                'user': user,
                'directory': directory,
                'speed': speed,
                'file_count': int(d.get('total_files') or 0),
                'total_size': int(d.get('total_size') or 0),
                'sample_files': [str(f.get('name') or '') for f in files[:5]],
            })
    out.sort(key=lambda x: (int(x.get('speed') or 0), int(x.get('total_size') or 0), str(x.get('user') or '').lower()), reverse=True)
    out = out[:limit]
    return {'engine': 'soulseek', 'query': query, 'limit': limit, 'results': out, 'result_count': len(out), 'error': ''}


def _mcp_start_rd_download(title: str, magnet: str) -> dict:
    if not magnet.startswith('magnet:?'):
        raise RuntimeError('Invalid magnet')
    torrent_id = rd_add_magnet(magnet)
    info = rd_torrent_info(torrent_id)
    files = info.get('files') or []
    file_ids: List[int] = []
    if isinstance(files, list):
        for f in files:
            if not isinstance(f, dict):
                continue
            fid = f.get('id')
            if fid is None:
                continue
            try:
                file_ids.append(int(fid))
            except Exception:
                continue
    if not file_ids:
        raise RuntimeError('No files found in torrent')
    task_id = uuid.uuid4().hex
    task_dir = build_task_dir(task_id, title)
    os.makedirs(task_dir, exist_ok=True)
    t = Task(
        id=task_id,
        title=title or 'Knaben item',
        magnet=magnet,
        task_dir=task_dir,
        state='queued',
        message='Queued',
        torrent_id=torrent_id,
        rd_selected_file_ids=file_ids,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    threading.Thread(target=worker, args=(task_id,), daemon=True).start()
    return {'task_id': task_id, 'task_dir': task_dir, 'torrent_id': torrent_id, 'selected_file_count': len(file_ids)}


def _mcp_start_slsk_download(user: str, directory: str, files_in: List[Dict[str, Any]], title: str = '') -> dict:
    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        raise RuntimeError('Soulseek is not configured or failed to start')
    task_download_dir = _slsk_task_download_dir(directory)
    try:
        os.makedirs(task_download_dir, exist_ok=True)
    except Exception:
        task_download_dir = SOULSEEK_DOWNLOAD_DIR
    files: List[Dict[str, Any]] = []
    remote_paths: List[str] = []
    for it in files_in or []:
        rp = _slsk_norm_remote_path(str((it or {}).get('remote_path') or '').strip())
        if not rp:
            continue
        try:
            sz = int((it or {}).get('size') or 0)
        except Exception:
            sz = 0
        remote_paths.append(rp)
        rel = _slsk_relative_under_directory(directory, rp)
        rel_parts = [x for x in _slsk_norm_remote_path(rel).split('\\') if x]
        local_path = os.path.join(task_download_dir, *rel_parts) if rel_parts else task_download_dir
        incoming_path = _slsk_expected_incoming_path(rp)
        files.append({
            'user': user,
            'directory': directory,
            'remote_path': rp,
            'file_id': hashlib.sha1((user + '|' + rp).encode('utf-8', 'ignore')).hexdigest()[:16],
            'name': _slsk_norm_remote_path(rp).split('\\')[-1],
            'total': sz,
            'done': 0,
            'state': 'queued',
            'state_raw': 'queued',
            'error': '',
            'paused': False,
            'canceled': False,
            'local_path': local_path,
            'incoming_path': incoming_path,
            'speed': 0.0,
        })
    if not user or not remote_paths:
        raise RuntimeError('Missing user or selected files')
    if not title:
        base = directory.split('\\')[-1] if directory else ''
        title = f"Soulseek: {user} {base}".strip()
    task_id = uuid.uuid4().hex
    t = Task(
        id=task_id,
        title=title,
        magnet='',
        task_dir=task_download_dir,
        source='soulseek',
        state='queued',
        message='Queued',
        torrent_id=None,
        slsk_user=user,
        slsk_directory=directory,
        slsk_files=files,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    svc.enqueue_downloads(task_id, user, remote_paths)
    return {'task_id': task_id, 'task_dir': task_download_dir, 'file_count': len(remote_paths), 'user': user, 'directory': directory}


def _mcp_build_library_tree() -> dict:
    roots_out = []
    for rid, name, root_abs, mode in roots():
        tree = {'name': name, 'root_id': rid, 'path': root_abs, 'mode': mode, 'folders': []}
        index: Dict[str, dict] = {'': tree}
        for base, dirs, _files in os.walk(root_abs):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != CACHE_DIR_NAME]
            rel_base = os.path.relpath(base, root_abs).replace('\\', '/')
            if rel_base == '.':
                rel_base = ''
            parent = index.get(rel_base)
            if parent is None:
                continue
            for d in sorted(dirs, key=lambda x: x.lower()):
                rel = f"{rel_base}/{d}".strip('/')
                node = {'name': d, 'path': rel, 'folders': []}
                parent['folders'].append(node)
                index[rel] = node
        roots_out.append(tree)
    return {'roots': roots_out}


def _mcp_handle_tool_call(name: str, args: dict) -> dict:
    name = str(name or '').strip()
    args = args if isinstance(args, dict) else {}
    if name == 'debripod_knaben_search':
        query = str(args.get('query') or '').strip()
        if not query:
            return _mcp_tool_result({'ok': False, 'error': 'Missing query'}, 'Error: Missing query', is_error=True)
        limit = _mcp_get_limit(args)
        data = _mcp_search_knaben(query, limit)
        ok = not data.get('error')
        text = json.dumps(data, ensure_ascii=False, indent=2)
        data['ok'] = ok
        return _mcp_tool_result(data, text, is_error=not ok)

    if name == 'debripod_soulseek_search':
        query = str(args.get('query') or '').strip()
        if not query:
            return _mcp_tool_result({'ok': False, 'error': 'Missing query'}, 'Error: Missing query', is_error=True)
        limit = _mcp_get_limit(args)
        data = _mcp_search_soulseek(query, limit)
        ok = not data.get('error')
        text = json.dumps(data, ensure_ascii=False, indent=2)
        data['ok'] = ok
        return _mcp_tool_result(data, text, is_error=not ok)

    if name == 'debripod_download':
        ident = str(args.get('identifier') or '').strip()
        if not ident:
            return _mcp_tool_result({'ok': False, 'error': 'Missing identifier'}, 'Error: Missing identifier', is_error=True)
        try:
            payload = _mcp_identifier_decode(ident)
        except Exception as e:
            return _mcp_tool_result({'ok': False, 'error': 'Invalid identifier: ' + str(e)}, 'Error: Invalid identifier: ' + str(e), is_error=True)
        kind = str(payload.get('kind') or '').strip().lower()
        try:
            if kind == 'slsk_dir':
                out = _mcp_start_slsk_download(
                    str(payload.get('user') or '').strip(),
                    _slsk_norm_remote_path(str(payload.get('directory') or '').strip()),
                    payload.get('files') if isinstance(payload.get('files'), list) else [],
                    str(payload.get('title') or '').strip(),
                )
                data = {'ok': True, 'source': 'soulseek', 'status': 'started', **out}
                text = f"Soulseek download started. Files are downloading to {out.get('task_dir')}."
                return _mcp_tool_result(data, text)
            if kind == 'knaben_item':
                out = _mcp_start_rd_download(str(payload.get('title') or 'Knaben item').strip() or 'Knaben item', str(payload.get('magnet') or '').strip())
                data = {'ok': True, 'source': 'knaben', 'status': 'started', **out}
                text = f"Knaben download started. Files are downloading to {out.get('task_dir')}."
                return _mcp_tool_result(data, text)
            return _mcp_tool_result({'ok': False, 'error': 'Unsupported identifier type'}, 'Error: Unsupported identifier type', is_error=True)
        except Exception as e:
            return _mcp_tool_result({'ok': False, 'error': str(e)}, 'Error: ' + str(e), is_error=True)

    if name == 'debripod_get_tasks':
        tasks = []
        for t in list_tasks():
            try:
                tasks.append(task_public_dict(t))
            except Exception:
                continue
        data = {'ok': True, 'tasks': tasks}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    if name == 'debripod_get_library':
        data = {'ok': True, **_mcp_build_library_tree()}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    if name == 'debripod_get_recents':
        try:
            limit = int(args.get('limit') or 20)
        except Exception:
            limit = 20
        limit = max(1, min(limit, 100))
        snap = playback_snapshot_public()
        recent = list((snap.get('recent') or [])[:limit])
        data = {'ok': True, 'recent': recent, 'count': len(recent)}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    return _mcp_tool_result({'ok': False, 'error': 'Unknown tool: ' + name}, 'Error: Unknown tool: ' + name, is_error=True)


def _mcp_tools_list() -> List[dict]:
    return [
        {
            'name': 'debripod_knaben_search',
            'title': 'Debripod Knaben Search',
            'description': 'Search Knaben torrent results. Returns Debripod download identifiers.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'limit': {'type': 'integer', 'minimum': 1},
                },
                'required': ['query'],
            },
        },
        {
            'name': 'debripod_soulseek_search',
            'title': 'Debripod Soulseek Search',
            'description': 'Search Soulseek directory results. Returns Debripod download identifiers.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'limit': {'type': 'integer', 'minimum': 1},
                },
                'required': ['query'],
            },
        },
        {
            'name': 'debripod_download',
            'title': 'Debripod Download',
            'description': 'Start a Debripod download from a search result identifier. Soulseek downloads use whole directories. Knaben downloads queue the whole torrent selection.',
            'inputSchema': {
                'type': 'object',
                'properties': {'identifier': {'type': 'string'}},
                'required': ['identifier'],
            },
        },
        {
            'name': 'debripod_get_tasks',
            'title': 'Debripod Get Tasks',
            'description': 'List current Debripod tasks and their status.',
            'inputSchema': {'type': 'object', 'properties': {}},
        },
        {
            'name': 'debripod_get_library',
            'title': 'Debripod Get Library',
            'description': 'Return a folder tree for every configured library root. Files are omitted.',
            'inputSchema': {'type': 'object', 'properties': {}},
        },
        {
            'name': 'debripod_get_recents',
            'title': 'Debripod Get Recents',
            'description': 'Return recently watched and recently listened items.',
            'inputSchema': {
                'type': 'object',
                'properties': {'limit': {'type': 'integer', 'minimum': 1}},
            },
        },
    ]


def _mcp_handle_message(msg: dict, session_id: str = '') -> Tuple[Optional[dict], str, int]:
    if not isinstance(msg, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}, session_id, 400
    method = str(msg.get('method') or '').strip()
    msg_id = msg.get('id')
    params = msg.get('params') if isinstance(msg.get('params'), dict) else {}
    if method == 'initialize':
        client_info = params.get('clientInfo') if isinstance(params.get('clientInfo'), dict) else {}
        requested_version = str(params.get('protocolVersion') or '').strip() or MCP_PROTOCOL_VERSION
        session_id = _mcp_ensure_session(session_id, client_info)
        result = {
            'protocolVersion': MCP_PROTOCOL_VERSION if requested_version != MCP_PROTOCOL_VERSION else requested_version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'debripod', 'version': str(VERSION)},
            'instructions': 'Use the search tool to get download identifiers, then pass one identifier to the download tool.',
        }
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}, session_id, 200
    if method == 'notifications/initialized':
        session_id = _mcp_ensure_session(session_id)
        _mcp_set_initialized(session_id, True)
        return None, session_id, 202
    if method == 'ping':
        session_id = _mcp_ensure_session(session_id)
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {}}, session_id, 200
    if method == 'tools/list':
        session_id = _mcp_ensure_session(session_id)
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {'tools': _mcp_tools_list()}}, session_id, 200
    if method == 'tools/call':
        session_id = _mcp_ensure_session(session_id)
        tool_name = str(params.get('name') or '').strip()
        tool_args = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': _mcp_handle_tool_call(tool_name, tool_args)}, session_id, 200
    if msg_id is None:
        session_id = _mcp_ensure_session(session_id) if method else session_id
        return None, session_id, 202
    session_id = _mcp_ensure_session(session_id) if method else session_id
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32601, 'message': 'Method not found'}}, session_id, 404


@app.route('/mcp', methods=['GET'])
def mcp_get():
    bad = _mcp_validate_origin()
    if bad is not None:
        return bad
    session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    return _mcp_sse_response(session_id)


@app.route('/mcp', methods=['DELETE'])
def mcp_delete():
    bad = _mcp_validate_origin()
    if bad is not None:
        return bad
    session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    if session_id:
        with MCP_SESSIONS_LOCK:
            MCP_SESSIONS.pop(session_id, None)
    return Response(status=204)


@app.route('/mcp', methods=['POST'])
def mcp_post():
    bad = _mcp_validate_origin()
    if bad is not None:
        return bad
    try:
        body = request.get_json(force=True, silent=False)
    except Exception as e:
        return _mcp_error(None, -32700, 'Parse error', data=str(e), status=400)
    header_session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    msgs = body if isinstance(body, list) else [body]
    replies = []
    status = 200
    session_id = header_session_id
    for msg in msgs:
        reply, session_id, this_status = _mcp_handle_message(msg, session_id=session_id)
        status = max(status, this_status)
        if reply is not None:
            replies.append(reply)
    if not replies:
        session_id = _mcp_ensure_session(session_id or header_session_id) if msgs else session_id
        resp = Response(status=202)
        if session_id:
            resp.headers['Mcp-Session-Id'] = session_id
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    payload = replies if isinstance(body, list) else replies[0]
    return _mcp_json_response(payload, status=200 if status < 400 else status, session_id=session_id)

app.config["SECRET_KEY"] = os.urandom(24)
register_icon_routes(app)
register_lastfm_routes(
    app,
    api_key_provider=lambda: LASTFM_API_KEY,
    api_secret_provider=lambda: LASTFM_API_SECRET,
)
register_task_routes(app)


@app.context_processor
def inject_helpers():
    return {"human_bytes": human_bytes, "human_rate": human_rate}


def render_shell(autorefresh: int = 0, **ctx) -> str:
    try:
        hostport = request.host
    except Exception:
        hostport = f"localhost:{PORT}"
    info_json = json.dumps({"version": VERSION, "host": HOST, "port": PORT, "ddir": DOWNLOAD_DIR, "sdir": SOULSEEK_DOWNLOAD_DIR})
    return render_template(
        "shell.html",
        hostport=hostport,
        port=PORT,
        ddir=DOWNLOAD_DIR,
        autorefresh=autorefresh,
        tasks_poll_ms=TASKS_POLL_MS,
        icon_v=ICON_VERSION,
        info_json=info_json,
        **ctx,
    )
register_shell_routes(app, render_shell)


def _search_knaben_cached(q: str, page: int = 1) -> Tuple[List[dict], str, str, str, str]:
    extra = {"page": int(page or 1)}
    cache_key = _make_search_cache_key("knaben", q, extra)
    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")
    if cached_payload is not None:
        results = cached_payload.get("results") or []
        err = cached_payload.get("error") or ""
        remaining = cached_payload.get("remaining") or ""
        reset = cached_payload.get("reset") or ""
    else:
        results, err, remaining, reset = knaben_search(q, int(page or 1))
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "knaben", q, extra, {"results": results, "error": err, "remaining": remaining, "reset": reset})
    return results, err, remaining, reset, cache_key


def _search_soulseek_cached(q: str) -> Tuple[List[Dict[str, Any]], int, int, str, str]:
    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key("soulseek", q, extra)
    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")
    slsk_users: List[Dict[str, Any]] = []
    slsk_total_results = 0
    dir_count = 0
    err = ""
    if cached_payload is not None:
        slsk_users = cached_payload.get("slsk_users") or []
        try:
            slsk_total_results = int(cached_payload.get("slsk_total_results") or 0)
        except Exception:
            slsk_total_results = sum(int(u.get("total_files") or 0) for u in (slsk_users or []))
        try:
            dir_count = int(cached_payload.get("dir_count") or 0)
        except Exception:
            dir_count = sum(len(u.get("dirs") or []) for u in (slsk_users or []))
    else:
        svc = SOULSEEK_SERVICE
        if not svc or not svc.is_ready():
            return [], 0, 0, cache_key, "Soulseek service is not ready"
        try:
            items = svc.search(q)
        except Exception as e:
            return [], 0, 0, cache_key, "Soulseek search failed: " + str(e)
        users: Dict[str, Dict[str, Any]] = {}
        for it in items:
            user = (it.get("user") or "").strip()
            rp = str(it.get("remote_path") or "")
            size = int(it.get("size") or 0)
            speed = int(it.get("speed") or 0)
            if not user or not rp:
                continue
            rp_norm = _slsk_norm_remote_path(rp)
            parts = rp_norm.split("\\")
            fname = parts[-1] if parts else rp_norm
            directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
            kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)
            u = users.get(user)
            if not u:
                u = {"user": user, "speed": speed, "dirs": {}, "total_size": 0, "total_files": 0}
                users[user] = u
            u["speed"] = max(int(u.get("speed") or 0), speed)
            d2 = (u.get("dirs") or {}).get(directory)
            if not d2:
                d2 = {"directory": directory, "files": [], "total_size": 0, "total_files": 0}
                (u.get("dirs") or {})[directory] = d2
                u["dirs"] = u.get("dirs") or {}
                u["dirs"][directory] = d2
            file_obj = {
                "name": fname, "remote_path": rp_norm, "size": size, "kind": kind, "ext": ext,
                "bitrate": br, "bit_depth": bd, "sample_rate": sr, "duration": dur, "vbr": vbr, "codec": codec,
            }
            file_obj = _slsk_annotate_file_with_download_state(file_obj, user)
            d2["files"].append(file_obj)
            d2["total_size"] += size
            d2["total_files"] = int(d2.get("total_files") or 0) + 1
            u["total_size"] = int(u.get("total_size") or 0) + size
            u["total_files"] = int(u.get("total_files") or 0) + 1
        for u in users.values():
            dirs_list = list((u.get("dirs") or {}).values())
            dirs_list.sort(key=lambda d: (int(d.get("total_size") or 0), len(d.get("files") or [])), reverse=True)
            slsk_users.append({"user": u.get("user") or "", "speed": int(u.get("speed") or 0), "dirs": dirs_list, "total_size": int(u.get("total_size") or 0), "total_files": int(u.get("total_files") or 0)})
        slsk_users.sort(key=lambda u: (int(u.get("speed") or 0), int(u.get("total_size") or 0), str(u.get("user") or "").lower()), reverse=True)
        slsk_total_results = sum(int(u.get("total_files") or 0) for u in slsk_users)
        dir_count = sum(len(u.get("dirs") or []) for u in (slsk_users or []))
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "soulseek", q, extra, {"slsk_users": slsk_users, "slsk_total_results": slsk_total_results, "file_count": slsk_total_results, "dir_count": dir_count})
    return slsk_users, slsk_total_results, dir_count, cache_key, err


def _quality_text_from_attrs(bit_depth: Any, sample_rate: Any, bitrate: Any) -> str:
    parts: List[str] = []
    try:
        bd = int(bit_depth or 0)
    except Exception:
        bd = 0
    try:
        sr = int(sample_rate or 0)
    except Exception:
        sr = 0
    br = bitrate
    if bd > 0:
        parts.append(f"{bd} bit")
    if sr > 0:
        parts.append(f"{round(sr / 1000.0, 1):g} kHz")
    if br:
        try:
            parts.append(f"{int(br)} kbps")
        except Exception:
            parts.append(str(br))
    return " ".join(parts)


def _standardize_knaben_results(raw_results: List[dict]) -> List[dict]:
    out: List[dict] = []
    for r in raw_results or []:
        if not isinstance(r, dict):
            continue
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        size = r.get("size")
        try:
            size = int(size) if size is not None else 0
        except Exception:
            size = 0
        seeders = r.get("seeders")
        leechers = r.get("leechers")
        out.append({
            "result_id": "knaben:" + str(r.get("id") or r.get("infohash") or sha1_text(title)),
            "source": "knaben",
            "source_label": "Knaben",
            "user": "",
            "title": title,
            "directory": "",
            "directory_title": title,
            "file_count": 0,
            "size": size,
            "speed": 0,
            "seeders": int(seeders) if isinstance(seeders, int) else 0,
            "leechers": int(leechers) if isinstance(leechers, int) else 0,
            "browse_available": False,
            "stream_available": True,
            "files_loaded": False,
            "files": [],
            "magnet": str(r.get("magnet") or ""),
            "infohash": str(r.get("infohash") or ""),
            "category": str(r.get("category") or ""),
            "verified": bool(r.get("verified")),
            "href": str(r.get("href") or ""),
            "_score": int(seeders) if isinstance(seeders, int) else 0,
        })
    return out


def _standardize_soulseek_results(slsk_users: List[Dict[str, Any]]) -> List[dict]:
    out: List[dict] = []
    for u in slsk_users or []:
        user = str(u.get("user") or "").strip()
        speed = int(u.get("speed") or 0)
        for d in (u.get("dirs") or []):
            directory = str(d.get("directory") or "").strip()
            files_std: List[dict] = []
            for f in (d.get("files") or []):
                if not isinstance(f, dict):
                    continue
                files_std.append({
                    "name": str(f.get("name") or ""),
                    "title": str(f.get("name") or ""),
                    "ext": str(f.get("ext") or "").lower(),
                    "quality": _quality_text_from_attrs(f.get("bit_depth"), f.get("sample_rate"), f.get("bitrate")),
                    "bitrate": (str(int(f.get("bitrate"))) + " kbps") if f.get("bitrate") else "",
                    "size": int(f.get("size") or 0),
                    "remote_path": str(f.get("remote_path") or ""),
                    "bit_depth": int(f.get("bit_depth") or 0) if f.get("bit_depth") else 0,
                    "sample_rate": int(f.get("sample_rate") or 0) if f.get("sample_rate") else 0,
                    "download_state": str(f.get("download_state") or ""),
                    "codec": str(f.get("codec") or ""),
                    "source": "soulseek",
                })
            base = directory.split("\\")[-1] if directory else ""
            out.append({
                "result_id": "soulseek:" + sha1_text(user + "|" + directory),
                "source": "soulseek",
                "source_label": "Soulseek",
                "user": user,
                "title": base or directory or user or "Soulseek",
                "directory": directory,
                "directory_title": base or directory,
                "file_count": len(files_std),
                "size": int(d.get("total_size") or 0),
                "speed": speed,
                "seeders": 0,
                "leechers": 0,
                "browse_available": True,
                "stream_available": False,
                "files_loaded": True,
                "files": files_std,
                "_score": speed if speed > 0 else len(files_std),
            })
    return out


@app.route("/api/libsearch/combined", methods=["GET"])
def api_libsearch_combined():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Missing query", results=[], result_count=0, cache_key="")
    combined_cache_key = _make_search_cache_key("combined", q, {})
    knaben_results, knaben_err, _, _, _ = _search_knaben_cached(q, 1)
    slsk_users, slsk_total_results, dir_count, _, slsk_err = _search_soulseek_cached(q)
    youtube_results, youtube_err, _ = _search_youtube_cached(q)
    results = _standardize_youtube_results(youtube_results) + _standardize_soulseek_results(slsk_users) + _standardize_knaben_results(knaben_results)
    results.sort(key=lambda x: (int(x.get("_score") or 0), int(x.get("size") or 0), str(x.get("title") or "").lower()), reverse=True)
    for r in results:
        r.pop("_score", None)
    try:
        record_search_history(q, "combined", combined_cache_key)
    except Exception:
        pass
    err = "; ".join([x for x in [youtube_err, slsk_err, knaben_err] if x])
    return jsonify(ok=True, q=q, cache_key=combined_cache_key, results=results, result_count=len(results), knaben_results=knaben_results, slsk_users=slsk_users, youtube_results=youtube_results, dir_count=dir_count, file_count=slsk_total_results, error=err)


def _removed_route(*args, **kwargs):
    def deco(fn):
        return fn
    return deco


@_removed_route("/api/libsearch/knaben", methods=["GET"])
def api_libsearch_knaben():
    q = (request.args.get("q") or "").strip()
    try:
        page = int(request.args.get("page") or "1")
    except ValueError:
        page = 1
    page = max(1, page)
    if not q:
        return jsonify(ok=False, error="Missing query", results=[], page=page, result_count=0, cache_key="")

    extra = {"page": page}
    cache_key = _make_search_cache_key("knaben", q, extra)

    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")

    if cached_payload is not None:
        results = cached_payload.get("results") or []
        err = cached_payload.get("error") or ""
        remaining = cached_payload.get("remaining") or ""
        reset = cached_payload.get("reset") or ""
    else:
        results, err, remaining, reset = knaben_search(q, page)
        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "knaben", q, extra, {"results": results, "error": err, "remaining": remaining, "reset": reset})

    if page == 1:
        try:
            record_search_history(q, "knaben", cache_key)
        except Exception:
            pass

    return jsonify(ok=True, q=q, page=page, cache_key=cache_key, results=results, error=err, rate_remaining=remaining, rate_reset=reset, result_count=len(results))



@_removed_route("/api/libsearch/soulseek_start", methods=["GET"])
def api_libsearch_soulseek_start():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Missing query", sid="", done=True, slsk_users=[], file_count=0, dir_count=0, cache_key="")

    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key("soulseek", q, extra)

    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")

    if cached_payload is not None:
        slsk_users = cached_payload.get("slsk_users") or []
        try:
            file_count = int(cached_payload.get("file_count") or 0)
        except Exception:
            file_count = 0
        try:
            dir_count = int(cached_payload.get("dir_count") or 0)
        except Exception:
            dir_count = 0
        if not file_count:
            try:
                file_count = sum(int(u.get("total_files") or 0) for u in (slsk_users or []))
            except Exception:
                file_count = 0
        return jsonify(ok=True, q=q, cache_key=cache_key, sid="", rev=1, done=True, slsk_users=slsk_users, file_count=file_count, dir_count=dir_count, error="", changed=True)

    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return jsonify(ok=False, error="Soulseek service is not ready", sid="", done=True, slsk_users=[], file_count=0, dir_count=0, cache_key=cache_key)

    sid = _slsk_session_create(cache_key, q)

    try:
        record_search_history(q, "soulseek", cache_key)
    except Exception:
        pass

    try:
        svc.start_search_session(sid, q)
    except Exception as e:
        _slsk_session_mark_done(sid, error=str(e))
        return jsonify(ok=False, error="Soulseek search failed: " + str(e), sid=sid, done=True, slsk_users=[], file_count=0, dir_count=0, cache_key=cache_key)

    return jsonify(ok=True, q=q, cache_key=cache_key, sid=sid, rev=0, done=False, slsk_users=[], file_count=0, dir_count=0, error="", changed=True)

@_removed_route("/api/libsearch/soulseek_poll", methods=["GET"])
def api_libsearch_soulseek_poll():
    sid = (request.args.get("sid") or "").strip()
    if not sid:
        return jsonify(ok=False, error="Missing sid", done=True)

    try:
        want_rev = int(request.args.get("rev") or 0)
    except Exception:
        want_rev = 0

    snap = _slsk_session_snapshot(sid)
    if not snap:
        return jsonify(ok=False, error="Unknown sid", done=True)

    _slsk_session_touch(sid)

    rev = int(snap.get("rev") or 0)
    done = bool(snap.get("done"))
    err = str(snap.get("error") or "")
    file_count = int(snap.get("file_count") or 0)
    dir_count = int(snap.get("dir_count") or 0)

    changed = (rev != want_rev) or done

    slsk_users = []
    if changed:
        slsk_users = _slsk_group_snapshot_to_users(snap)

    if done and not err:
        # Persist to disk cache for fast repeat loads
        cache_key = str(snap.get("cache_key") or "")
        q = str(snap.get("q") or "")
        extra: Dict[str, Any] = {}
        payload = {
            "slsk_users": slsk_users,
            "file_count": file_count,
            "dir_count": dir_count,
        }
        try:
            with _SEARCH_DISK_LOCK:
                _disk_cache_set(cache_key, "soulseek", q, extra, payload)
        except Exception:
            pass

    return jsonify(
        ok=True,
        sid=sid,
        cache_key=str(snap.get("cache_key") or ""),
        rev=rev,
        changed=changed,
        done=done,
        error=err,
        slsk_users=slsk_users,
        file_count=file_count,
        dir_count=dir_count,
    )

@_removed_route("/api/libsearch/soulseek", methods=["GET"])
def api_libsearch_soulseek():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(ok=False, error="Missing query", slsk_users=[], result_count=0, cache_key="")

    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key("soulseek", q, extra)

    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")

    slsk_users: List[Dict[str, Any]] = []
    slsk_total_results = 0

    if cached_payload is not None:
        slsk_users = cached_payload.get("slsk_users") or []
        try:
            slsk_total_results = int(cached_payload.get("slsk_total_results") or 0)
        except Exception:
            slsk_total_results = sum(int(u.get("total_files") or 0) for u in (slsk_users or []))
    else:
        svc = SOULSEEK_SERVICE
        if not svc or not svc.is_ready():
            return jsonify(ok=False, error="Soulseek service is not ready", slsk_users=[], result_count=0, cache_key=cache_key)

        try:
            items = svc.search(q)
        except Exception as e:
            return jsonify(ok=False, error="Soulseek search failed: " + str(e), slsk_users=[], result_count=0, cache_key=cache_key)

        users: Dict[str, Dict[str, Any]] = {}
        for it in items:
            user = (it.get("user") or "").strip()
            rp = str(it.get("remote_path") or "")
            size = int(it.get("size") or 0)
            speed = int(it.get("speed") or 0)
            if not user or not rp:
                continue
            rp_norm = _slsk_norm_remote_path(rp)
            parts = rp_norm.split("\\")
            fname = parts[-1] if parts else rp_norm
            directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
            kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)

            u = users.get(user)
            if not u:
                u = {"user": user, "speed": speed, "dirs": {}, "total_size": 0, "total_files": 0}
                users[user] = u
            u["speed"] = max(int(u.get("speed") or 0), speed)

            d = (u.get("dirs") or {}).get(directory)
            if not d:
                d = {"directory": directory, "files": [], "total_size": 0, "total_files": 0}
                (u.get("dirs") or {})[directory] = d
                u["dirs"] = u.get("dirs") or {}
                u["dirs"][directory] = d

            d["files"].append({
                "name": fname,
                "remote_path": rp_norm,
                "size": size,
                "kind": kind,
                "ext": ext,
                "bitrate": br,
                "bit_depth": bd,
                "sample_rate": sr,
                "duration": dur,
                "vbr": vbr,
                "codec": codec,
            })
            d["total_size"] += size
            u["total_size"] = int(u.get("total_size") or 0) + size
            u["total_files"] = int(u.get("total_files") or 0) + 1

        for u in users.values():
            dirs_list = list((u.get("dirs") or {}).values())
            dirs_list.sort(key=lambda d: (int(d.get("total_size") or 0), len(d.get("files") or [])), reverse=True)
            u2 = {"user": u.get("user") or "", "speed": int(u.get("speed") or 0), "dirs": dirs_list, "total_size": int(u.get("total_size") or 0), "total_files": int(u.get("total_files") or 0)}
            slsk_users.append(u2)

        slsk_users.sort(key=lambda u: (int(u.get("speed") or 0), int(u.get("total_size") or 0), str(u.get("user") or "").lower()), reverse=True)
        slsk_total_results = sum(int(u.get("total_files") or 0) for u in slsk_users)

        dir_count = 0
        try:
            dir_count = sum(len(u.get("dirs") or []) for u in (slsk_users or []))
        except Exception:
            dir_count = 0

        with _SEARCH_DISK_LOCK:
            _disk_cache_set(cache_key, "soulseek", q, extra, {"slsk_users": slsk_users, "slsk_total_results": slsk_total_results, "file_count": slsk_total_results, "dir_count": dir_count})

    try:
        record_search_history(q, "soulseek", cache_key)
    except Exception:
        pass

    return jsonify(ok=True, q=q, cache_key=cache_key, slsk_users=slsk_users, result_count=slsk_total_results)

@app.route("/api/soulseek/browse_user", methods=["GET"])
def api_soulseek_browse_user():
    user = (request.args.get("user") or "").strip()
    selected_dir = _slsk_norm_remote_path(request.args.get("selected_dir") or "")
    if not user:
        return jsonify(ok=False, error="Missing user", user="", dirs=[], selected_dir=""), 400

    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return jsonify(ok=False, error="Soulseek service is not ready", user=user, dirs=[], selected_dir=selected_dir)

    try:
        items = svc.browse_user(user)
    except Exception as e:
        return jsonify(ok=False, error="Soulseek browse failed: " + str(e), user=user, dirs=[], selected_dir=selected_dir)

    dirs = _slsk_group_items_to_dirs(user, items)
    dir_paths = {str(d.get("directory") or "") for d in dirs}
    if selected_dir and selected_dir not in dir_paths:
        selected_dir = ""

    return jsonify(ok=True, user=user, dirs=dirs, selected_dir=selected_dir, file_count=sum(int(d.get("total_files") or 0) for d in dirs), dir_count=len(dirs))


def build_task_dir(task_id: str, title: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = sanitize_folder_name(title)
    folder = f"{stamp}_{base}_{task_id[:6]}"
    folder = sanitize_folder_name(folder)
    return os.path.join(DOWNLOAD_DIR, folder)


@app.route("/enqueue", methods=["POST"])
def enqueue():
    title = (request.form.get("title") or "").strip() or "Knaben item"
    magnet = (request.form.get("magnet") or "").strip()
    if not magnet.startswith("magnet:?"):
        abort(400)

    task_id = uuid.uuid4().hex
    task_dir = build_task_dir(task_id, title)
    os.makedirs(task_dir, exist_ok=True)

    t = Task(id=task_id, title=title, magnet=magnet, task_dir=task_dir, state="queued", message="Queued")
    with TASKS_LOCK:
        TASKS[task_id] = t

    th = threading.Thread(target=worker, args=(task_id,), daemon=True)
    th.start()

    ref = request.headers.get("Referer") or ""
    return redirect(ref or url_for("index", tab="search"))


@app.route("/api/libsearch/youtube", methods=["GET"])
def api_libsearch_youtube():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify(ok=False, error='Missing query', results=[], result_count=0, cache_key='')
    raw_results, err, cache_key = _search_youtube_cached(q)
    try:
        record_search_history(q, 'youtube', cache_key)
    except Exception:
        pass
    results = _standardize_youtube_results(raw_results)
    return jsonify(ok=True, q=q, cache_key=cache_key, results=results, result_count=len(results), error=err)


@app.route("/api/youtube/files", methods=["GET"])
def api_youtube_files():
    url = (request.args.get('url') or '').strip()
    if not url:
        return jsonify(ok=False, error='Missing URL', files=[], file_count=0, size=0), 400
    try:
        files = ytdlp_list_formats(url)
        total_size = sum(int(f.get('size') or 0) for f in files)
        return jsonify(ok=True, files=files, file_count=len(files), size=total_size)
    except Exception as e:
        return jsonify(ok=False, error=str(e), files=[], file_count=0, size=0), 500


@app.route("/api/youtube/channel", methods=["GET"])
def api_youtube_channel():
    channel_id = (request.args.get('channel_id') or '').strip()
    if not channel_id:
        return jsonify(ok=False, error='Missing channel id', results=[], result_count=0), 400
    try:
        results = youtube_channel_browse(channel_id)
        return jsonify(ok=True, results=results, result_count=len(results))
    except Exception as e:
        return jsonify(ok=False, error=str(e), results=[], result_count=0), 500


@app.route("/api/youtube/enqueue", methods=["POST"])
def api_youtube_enqueue():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    title = str(data.get('title') or '').strip() or 'YouTube'
    url = str(data.get('url') or '').strip()
    selected = data.get('selected') or []
    if not url:
        return jsonify(ok=False, error='Missing URL'), 400
    entries: List[Dict[str, Any]] = []
    for i, it in enumerate(selected):
        if not isinstance(it, dict):
            continue
        name = str(it.get('name') or it.get('title') or f'Format {i+1}')
        ext = str(it.get('ext') or 'mp4').lower()
        file_id = str(it.get('file_id') or it.get('itag') or sha1_text(name + '|' + ext)[:12])
        entries.append({
            'file_id': file_id,
            'itag': str(it.get('itag') or it.get('format_id') or it.get('file_id') or ''),
            'format_id': str(it.get('format_id') or it.get('itag') or it.get('file_id') or ''),
            'name': name,
            'title': name,
            'ext': ext,
            'media': str(it.get('media') or '').strip().lower(),
            'direct_url': str(it.get('direct_url') or '').strip(),
            'url': url,
            'total': int(it.get('size') or 0) if str(it.get('size') or '').strip() else 0,
            'done': 0,
            'speed': 0.0,
            'state': 'queued',
            'error': '',
            'paused': False,
            'canceled': False,
            'out_path': '',
        })
    if not entries:
        return jsonify(ok=False, error='No files selected'), 400
    task_id = uuid.uuid4().hex
    youtube_root = _youtube_download_root()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = sanitize_folder_name(title)
    folder = sanitize_folder_name(f"{stamp}_{base}_{task_id[:6]}")
    task_dir = os.path.join(youtube_root, folder)
    os.makedirs(task_dir, exist_ok=True)
    t = Task(id=task_id, title=title, magnet=url, task_dir=task_dir, source='youtube', state='queued', message='Queued', rd_files=entries)
    with TASKS_LOCK:
        TASKS[task_id] = t
    th = threading.Thread(target=worker, args=(task_id,), daemon=True)
    th.start()
    return jsonify(ok=True, task_id=task_id)


@app.route("/api/search_history", methods=["GET"])
def api_search_history():
    try:
        with _SEARCH_DISK_LOCK:
            items = _load_search_history()
        # hide internal keys from the UI
        out = [{"q": it.get("q") or "", "engine": it.get("engine") or ""} for it in items]
        return jsonify({"ok": True, "items": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "items": []})


@app.route("/api/search_history/clear", methods=["POST"])
def api_search_history_clear():
    try:
        clear_search_history_and_cache()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/libsearch/stream_selected", methods=["POST"])
def api_libsearch_stream_selected():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    try:
        out = _engine_prepare_stream_session(data)
        return jsonify({"ok": True, **out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/rd/preview_files", methods=["POST"])
def api_rd_preview_files():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    magnet = str(data.get("magnet") or "").strip()
    if not magnet.startswith("magnet:?"):
        return jsonify({"ok": False, "error": "Invalid magnet"}), 400
    try:
        torrent_id = rd_add_magnet(magnet)
        info = rd_torrent_info(torrent_id)
        files = info.get("files") or []
        out: List[Dict[str, Any]] = []
        if isinstance(files, list):
            for f in files:
                if not isinstance(f, dict):
                    continue
                fid = f.get("id")
                if fid is None:
                    continue
                path = f.get("path") or f.get("file_path") or f.get("filename") or ""
                b = f.get("bytes")
                if b is None:
                    b = f.get("size") or f.get("filesize") or 0
                try:
                    out.append({"id": int(fid), "path": str(path), "bytes": int(b or 0)})
                except Exception:
                    continue
        return jsonify({"ok": True, "torrent_id": str(torrent_id), "files": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500




@app.route("/api/rd/load_files", methods=["POST"])
def api_rd_load_files():
    # Backwards compatible alias for older frontends.
    return api_rd_preview_files()

@app.route("/api/rd/enqueue_selected", methods=["POST"])
def api_rd_enqueue_selected():
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    title = str(data.get("title") or "").strip() or "Knaben item"
    magnet = str(data.get("magnet") or "").strip()
    torrent_id = str(data.get("torrent_id") or "").strip()
    file_ids = data.get("file_ids") or []

    if not torrent_id:
        return jsonify({"ok": False, "error": "Missing torrent id"}), 400

    clean_ids: List[int] = []
    if isinstance(file_ids, list):
        for x in file_ids:
            try:
                clean_ids.append(int(x))
            except Exception:
                continue

    if not clean_ids:
        return jsonify({"ok": False, "error": "No files selected"}), 400

    task_id = uuid.uuid4().hex
    task_dir = build_task_dir(task_id, title)
    os.makedirs(task_dir, exist_ok=True)

    t = Task(
        id=task_id,
        title=title,
        magnet=magnet,
        task_dir=task_dir,
        state="queued",
        message="Queued",
        torrent_id=torrent_id,
        rd_selected_file_ids=clean_ids,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t

    th = threading.Thread(target=worker, args=(task_id,), daemon=True)
    th.start()

    return jsonify({"ok": True, "task_id": task_id})


@app.route("/api/soulseek/enqueue", methods=["POST"])
def api_soulseek_enqueue():
    svc = SOULSEEK_SERVICE
    if not svc or not svc.is_ready():
        return jsonify({"ok": False, "error": "Soulseek is not configured or failed to start"}), 400

    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception:
        data = {}

    user = (data.get("user") or "").strip()
    directory = (data.get("directory") or "").strip()
    files_in = data.get("files") or []
    title = (data.get("title") or "").strip()

    task_download_dir = _slsk_task_download_dir(directory)
    try:
        os.makedirs(task_download_dir, exist_ok=True)
    except Exception:
        task_download_dir = SOULSEEK_DOWNLOAD_DIR

    files: List[Dict[str, Any]] = []
    remote_paths: List[str] = []
    for it in files_in:
        if isinstance(it, str):
            rp = it
            sz = 0
        else:
            rp = it.get("remote_path") if isinstance(it, dict) else ""
            sz = it.get("size") if isinstance(it, dict) else 0
        rp = _slsk_norm_remote_path(str(rp or "").strip())
        if not rp:
            continue
        try:
            sz = int(sz or 0)
        except Exception:
            sz = 0
        remote_paths.append(rp)
        rel = _slsk_relative_under_directory(directory, rp)
        rel_parts = [x for x in _slsk_norm_remote_path(rel).split("\\") if x]
        local_path = os.path.join(task_download_dir, *rel_parts) if rel_parts else task_download_dir
        incoming_path = _slsk_expected_incoming_path(rp)
        files.append(
            {
                "user": user,
                "directory": directory,
                "remote_path": rp,
                "file_id": hashlib.sha1((user + "|" + rp).encode("utf-8", "ignore")).hexdigest()[:16],
                "name": _slsk_norm_remote_path(rp).split("\\")[-1],
                "total": sz,
                "done": 0,
                "state": "queued",
                "state_raw": "queued",
                "error": "",
                "paused": False,
                "canceled": False,
                "local_path": local_path,
                "incoming_path": incoming_path,
                "speed": 0.0,
            }
        )

    if not user or not remote_paths:
        return jsonify({"ok": False, "error": "Missing user or selected files"}), 400

    if not title:
        base = directory.split("\\")[-1] if directory else ""
        title = f"Soulseek: {user} {base}".strip()

    task_id = uuid.uuid4().hex
    t = Task(
        id=task_id,
        title=title,
        magnet="",
        task_dir=task_download_dir,
        source="soulseek",
        state="queued",
        message="Queued",
        torrent_id=None,
        slsk_user=user,
        slsk_directory=directory,
        slsk_files=files,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t

    try:
        svc.enqueue_downloads(task_id, user, remote_paths)
    except Exception as e:
        set_task(task_id, state="error", message="Failed to queue Soulseek download: " + str(e))
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "task_id": task_id})




@app.route("/cancel", methods=["POST"])
def cancel():
    task_id = (request.form.get("task_id") or "").strip()
    if not task_id:
        abort(400)
    cancel_task(task_id)
    return redirect(url_for("tasks"))




# =========================
# Library API
# =========================

@app.route("/api/library/config", methods=["GET"])
def api_library_config():
    rts = []
    for rid, name, ap, mode in roots():
        rts.append({"id": rid, "name": name, "mode": mode})
    return jsonify(
        {
            "roots": rts,
            "preload_enabled": bool(PRELOAD_NEXT_FOR_GAPLESS),
            "preload_bytes": int(PRELOAD_NEXT_CHUNK_BYTES),
            "lastfm_enabled": bool(lastfm_enabled()),
            "wheel_rotation_max_degrees": float(WHEEL_ROTATION_MAX_DEGREES),
            "playback_streaming_mode": str(PLAYBACK_STREAMING_MODE or "http").strip().lower() or "http",
        }
    )


@app.route("/api/library/reindex", methods=["POST"])
def api_library_reindex():
    clear_index_cache()
    return jsonify({"ok": True})


@app.route("/api/library/building", methods=["GET"])
def api_library_building():
    any_building, roots_status = index_building_status()
    return jsonify({"ok": True, "any_building": any_building, "roots": roots_status})





# =========================
# Playback state API (server-side)
# =========================
@app.route("/api/playback/snapshot", methods=["GET"])
def api_playback_snapshot():
    return jsonify(playback_snapshot_public())

@app.route("/api/playback/recent", methods=["GET"])
def api_playback_recent():
    with PLAYBACK_STATE_LOCK:
        recent = PLAYBACK_STATE.get("recent") or []
        out = []
        for it in recent:
            if not isinstance(it, dict):
                continue
            d = dict(it)
            d.pop("_key", None)
            d.pop("_sess", None)
            d.pop("_stream_item", None)
            out.append(d)
    return jsonify({"recent": out})

@app.route("/api/playback/update", methods=["POST"])
def api_playback_update():
    js = request.get_json(silent=True) or {}
    out = playback_update_from_client(js)
    if not out.get("ok"):
        return jsonify(out), 400
    return jsonify(out)


@app.route("/api/library/browse", methods=["GET"])
def api_library_browse():
    root_id = (request.args.get("root_id") or "").strip()
    rel = (request.args.get("rel") or "").strip()
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    if not os.path.isdir(abs_path):
        abort(404)

    entries = []
    try:
        names = os.listdir(abs_path)
    except OSError:
        names = []

    dirs = []
    files = []
    for n in names:
        if n.startswith(".") or n == CACHE_DIR_NAME:
            continue
        p = os.path.join(abs_path, n)
        if os.path.isdir(p):
            dirs.append(n)
        elif os.path.isfile(p):
            ext = os.path.splitext(n)[1].lower()
            if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
                files.append(n)

    dirs.sort(key=lambda x: x.lower())
    files.sort(key=lambda x: x.lower())

    rel_norm = rel.replace("\\", "/").strip("/")
    for d in dirs:
        relp = f"{rel_norm}/{d}" if rel_norm else d
        entries.append({"type": "dir", "name": d, "rel": relp})
    for f in files:
        relp = f"{rel_norm}/{f}" if rel_norm else f
        p = os.path.join(abs_path, f)
        media = "video" if is_video(p) else ("audio" if is_audio(p) else "")
        entries.append({"type": "file", "name": f, "rel": relp, "media": media})
    return jsonify({"entries": entries})


@app.route("/api/library/metadata", methods=["GET"])
def api_library_metadata():
    root_id = (request.args.get("root_id") or "").strip()
    level = (request.args.get("level") or "").strip().lower()
    value = (request.args.get("value") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    if level == "playlists":
        items = scan_root_playlists(root_abs)
        if not items:
            items = [{"kind": "info", "label": "No playlists found"}]
        return jsonify({"items": items})

    if level == "playlist_tracks":
        if is_smart_playlist_rel(value):
            items = smart_playlist_tracks_for_root(root_abs, value, root_id)
        else:
            items = playlist_tracks_for_root(root_abs, value)
        if not items:
            items = [{"kind": "info", "label": "No playable tracks found in playlist"}]
        return jsonify({"items": items})

    ensure_index_async(root_id, root_abs)
    data = get_index(root_id)
    if data is None:
        if level == "top":
            cats = [
                {"key": "artists", "label": "Artists"},
                {"key": "albums", "label": "Albums"},
                {"key": "songs", "label": "Songs"},
                {"key": "liked_songs", "label": "Liked Songs"},
                {"key": "playlists", "label": "Playlists"},
                {"key": "genres", "label": "Genres"},
                {"key": "videos", "label": "Videos"},
                {"key": "folders", "label": "Folders"},
            ]
            return jsonify({"categories": cats, "building": True})
        return jsonify({"items": [{"kind": "info", "label": "Indexing media files..."}], "building": True})

    tracks = data.get("tracks") or []
    vids = data.get("videos") or []

    if level == "top":
        cats = [
            {"key": "artists", "label": "Artists"},
            {"key": "albums", "label": "Albums"},
            {"key": "songs", "label": "Songs"},
            {"key": "liked_songs", "label": "Liked Songs"},
            {"key": "playlists", "label": "Playlists"},
            {"key": "genres", "label": "Genres"},
            {"key": "videos", "label": "Videos"},
            {"key": "folders", "label": "Folders"},
        ]
        return jsonify({"categories": cats, "building": False})

    if level == "artists":
        s = sorted({(t.get("artist") or "").strip() for t in tracks if (t.get("artist") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "artist", "label": a, "value": a} for a in s] or [{"kind": "info", "label": "No artist tags found"}]
        return jsonify({"items": items})

    if level == "albums":
        artist_filter = value
        albums = []
        seen = set()
        for t in tracks:
            art = (t.get("artist") or "").strip()
            alb = (t.get("album") or "").strip()
            if not alb:
                continue
            if artist_filter and art != artist_filter:
                continue
            key = (art, alb) if not artist_filter else ("", alb)
            if key in seen:
                continue
            seen.add(key)
            label = alb if artist_filter else (alb + (f"   {art}" if art else ""))
            val = json.dumps({"artist": art, "album": alb})
            albums.append({"kind": "album", "label": label, "value": val})
        albums.sort(key=lambda x: x["label"].lower())
        if artist_filter:
            # Special entry to show every track for this artist (no album filter)
            albums.insert(0, {"kind": "album", "label": "All Songs", "value": json.dumps({"artist": artist_filter, "album": ""})})
            albums.insert(0, {"kind": "album", "label": "Liked Songs", "value": json.dumps({"artist": artist_filter, "album": "", "liked": True})})

        if not albums:
            albums = [{"kind": "info", "label": "No albums found"}]
        return jsonify({"items": albums})

    if level == "tracks":
        try:
            sel = json.loads(value) if value else {}
        except Exception:
            sel = {}
        artist = (sel.get("artist") or "").strip()
        album = (sel.get("album") or "").strip()
        genre = (sel.get("genre") or "").strip()
        liked_only = bool(sel.get("liked") or sel.get("loved") or sel.get("liked_only"))
        if liked_only and not lastfm_enabled():
            return jsonify({"items": [{"kind": "info", "label": "Last.fm not configured"}]})
        tr = []
        for t in tracks:
            if artist and (t.get("artist") or "").strip() != artist:
                continue
            if album and (t.get("album") or "").strip() != album:
                continue
            if genre and (t.get("genre") or "").strip() != genre:
                continue
            if liked_only:
                a = (t.get("artist") or "").strip()
                tt = (t.get("title") or t.get("name") or "").strip()
                b = (t.get("album") or "").strip()
                if not a or not tt or (not lastfm_is_loved(a, tt, b)):
                    continue
            label = t.get("title") or t.get("name") or "Track"
            tr.append({"kind": "track", "label": label, "rel": t.get("rel"), "badge": (t.get("track") or "")})
        tr.sort(key=lambda x: track_sort_key(x.get("badge") or "") + (x.get("label") or "",))
        if not tr:
            tr = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": tr})


    if level == "liked_songs":
        if not lastfm_enabled():
            return jsonify({"items": [{"kind": "info", "label": "Last.fm not configured"}]})
        items = []
        for t in tracks:
            a = (t.get("artist") or "").strip()
            tt = (t.get("title") or t.get("name") or "").strip()
            b = (t.get("album") or "").strip()
            if not a or not tt:
                continue
            if not lastfm_is_loved(a, tt, b):
                continue
            items.append({"kind": "track", "label": (t.get("title") or t.get("name") or "Track"), "rel": t.get("rel"), "badge": (t.get("track") or "")})
        items.sort(key=lambda x: (x.get("label") or "").lower())
        if not items:
            items = [{"kind": "info", "label": "No liked songs found"}]
        return jsonify({"items": items[:3000]})

    if level == "songs":
        s = sorted(tracks, key=lambda x: (x.get("title") or x.get("name") or "").lower())
        items = [{"kind": "track", "label": (t.get("title") or t.get("name") or "Track"), "rel": t.get("rel")} for t in s[:3000]]
        if not items:
            items = [{"kind": "info", "label": "No songs found"}]
        return jsonify({"items": items})

    if level == "genres":
        s = sorted({(t.get("genre") or "").strip() for t in tracks if (t.get("genre") or "").strip()}, key=lambda x: x.lower())
        items = [{"kind": "genre", "label": g, "value": g} for g in s] or [{"kind": "info", "label": "No genre tags found"}]

        return jsonify({"items": items})

    if level == "genre_albums":
        genre = value
        albums = []
        seen = set()
        any_match = False

        for t in tracks:
            if (t.get("genre") or "").strip() != genre:
                continue
            any_match = True
            art = (t.get("artist") or "").strip()
            alb = (t.get("album") or "").strip()
            if not alb:
                continue
            key = (art, alb)
            if key in seen:
                continue
            seen.add(key)
            label = alb + (f"   {art}" if art else "")
            val = json.dumps({"genre": genre, "artist": art, "album": alb})
            albums.append({"kind": "album", "label": label, "value": val})

        albums.sort(key=lambda x: x["label"].lower())

        # Always offer a way to play all tracks for this genre, even if albums are missing tags.
        if genre and any_match:
            albums.insert(0, {"kind": "album", "label": "All Songs", "value": json.dumps({"genre": genre, "album": ""})})
            albums.insert(0, {"kind": "album", "label": "Liked Songs", "value": json.dumps({"genre": genre, "album": "", "liked": True})})

        if not albums:
            albums = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": albums})

    if level == "genre_tracks":
        genre = value
        items = []
        for t in tracks:
            if (t.get("genre") or "").strip() != genre:
                continue
            label = t.get("title") or t.get("name") or "Track"
            items.append({"kind": "track", "label": label, "rel": t.get("rel")})
        items.sort(key=lambda x: (x.get("label") or "").lower())
        if not items:
            items = [{"kind": "info", "label": "No tracks found"}]
        return jsonify({"items": items})

    if level == "videos":
        items = []
        for v in sorted(vids, key=lambda x: (x.get("title") or x.get("name") or "").lower())[:3000]:
            items.append({"kind": "file", "label": v.get("name") or v.get("title") or "Video", "rel": v.get("rel"), "media": "video", "badge": "video"})
        if not items:
            items = [{"kind": "info", "label": "No videos found"}]
        return jsonify({"items": items})

    return jsonify({"items": [{"kind": "info", "label": "Unsupported view"}]})


@app.route("/api/library/playlist_create", methods=["POST"])
def api_library_playlist_create():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    name = str(js.get("name") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = create_root_playlist(root_abs, name)
    if not ok:
        return jsonify({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return jsonify({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@app.route("/api/library/playlist_rename", methods=["POST"])
def api_library_playlist_rename():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    name = str(js.get("name") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = rename_root_playlist(root_abs, playlist_rel, name)
    if not ok:
        return jsonify({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return jsonify({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@app.route("/api/library/playlist_add", methods=["POST"])
def api_library_playlist_add():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    tracks = js.get("tracks") if isinstance(js.get("tracks"), list) else []
    clean_tracks = [str(x or "").strip() for x in tracks if str(x or "").strip()]

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = add_tracks_to_playlist(root_abs, playlist_rel, clean_tracks)
    if not ok:
        return jsonify({"ok": False, "error": err, "added": int((info or {}).get("added") or 0)})
    return jsonify({"ok": True, "added": int((info or {}).get("added") or 0)})


@app.route("/api/library/playlist_remove", methods=["POST"])
def api_library_playlist_remove():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    tracks = js.get("tracks") if isinstance(js.get("tracks"), list) else []
    clean_tracks = [str(x or "").strip() for x in tracks if str(x or "").strip()]

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = remove_tracks_from_playlist(root_abs, playlist_rel, clean_tracks)
    if not ok:
        return jsonify({"ok": False, "error": err, "removed": int((info or {}).get("removed") or 0)})
    return jsonify({"ok": True, "removed": int((info or {}).get("removed") or 0)})




@app.route("/api/library/playlist_delete", methods=["POST"])
def api_library_playlist_delete():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = delete_root_playlist(root_abs, playlist_rel)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "smart": bool((info or {}).get("smart"))})


@app.route("/api/library/smart_playlist_create", methods=["POST"])
def api_library_smart_playlist_create():
    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    name = str(js.get("name") or "").strip()

    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r

    ok, err, info = create_root_smart_playlist(root_abs, name)
    if not ok:
        return jsonify({"ok": False, "error": err, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})
    return jsonify({"ok": True, "rel": str((info or {}).get("rel") or ""), "label": str((info or {}).get("label") or "")})


@app.route("/api/library/smart_playlist_rules", methods=["GET", "POST"])
def api_library_smart_playlist_rules():
    if request.method == "GET":
        root_id = (request.args.get("root_id") or "").strip()
        playlist_rel = (request.args.get("rel") or "").strip()
        r = root_by_id(root_id)
        if not r:
            abort(404)
        _, _, root_abs, _ = r
        ok, err, info = load_smart_playlist_rules(root_abs, playlist_rel)
        if not ok:
            return jsonify({"ok": False, "error": err}), 400
        return jsonify({"ok": True, "text": str((info or {}).get("text") or ""), "label": str((info or {}).get("label") or "")})

    js = request.get_json(silent=True) or {}
    root_id = str(js.get("root_id") or "").strip()
    playlist_rel = str(js.get("rel") or "").strip()
    text = str(js.get("text") or "")
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    ok, err, info = save_smart_playlist_rules(root_abs, playlist_rel, text)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "label": str((info or {}).get("label") or "")})


@app.route("/api/library/filemeta", methods=["GET"])
def api_library_filemeta():
    root_id = (request.args.get("root_id") or "").strip()
    rel = (request.args.get("rel") or "").strip()
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(rel)
        if not it:
            abort(404)
        return jsonify({
            "title": str(it.get("title") or it.get("name") or ""),
            "artist": str(it.get("artist") or ""),
            "album": str(it.get("album") or ""),
            "genre": "",
            "duration": None,
            "tech": str(it.get("quality") or it.get("ext") or ""),
            "art": str(it.get("art") or ""),
        })
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        abort(404)

    meta = file_meta_cached(abs_path)

    art = ""
    ver = ""
    try:
        ver = str(int(os.path.getmtime(os.path.dirname(abs_path))))
    except OSError:
        ver = ""
    ap = art_for_media_path(abs_path) if is_audio(abs_path) else None
    if ap:
        art = url_for("art", root_id=root_id, relpath=rel)
        if ver:
            art = art + "?v=" + ver

    return jsonify(
        {
            "title": meta.get("title") or os.path.splitext(os.path.basename(abs_path))[0],
            "artist": meta.get("artist") or "",
            "album": meta.get("album") or "",
            "genre": meta.get("genre") or "",
            "duration": meta.get("duration"),
            "tech": meta.get("tech") or "",
            "art": art,
        }
    )


@app.route("/art/<root_id>/<path:relpath>", methods=["GET", "HEAD"])
def art(root_id: str, relpath: str):
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    ap = art_for_media_path(abs_path)
    if not ap:
        abort(404)
    return range_response(ap)




def hls_cache_dir() -> str:
    p = os.path.join(cache_dir(), "hls")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def _hls_stream_key_for_path(src_path: str) -> str:
    ap = os.path.abspath(src_path)
    try:
        st = os.stat(ap)
        sig = f"{ap}|{int(st.st_mtime)}|{int(st.st_size)}"
    except OSError:
        sig = ap
    return sha1_text(sig)


def _hls_build_args(src_path: str, out_dir: str) -> List[str]:
    manifest_path = os.path.join(out_dir, "stream.m3u8")
    seg_pat = os.path.join(out_dir, "seg_%05d.m4s")
    init_path = os.path.join(out_dir, "init.mp4")
    return [
        FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
        "-i", src_path,
        "-map", "0:v:0?",
        "-map", "0:a:0?",
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "0",
        "-hls_playlist_type", "vod",
        "-hls_flags", "independent_segments",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", init_path,
        "-hls_segment_filename", seg_pat,
        manifest_path,
    ]


def _hls_cache_entry_for_path(src_path: str) -> Tuple[str, str]:
    key = _hls_stream_key_for_path(src_path)
    out_dir = os.path.join(hls_cache_dir(), key)
    manifest_path = os.path.join(out_dir, "stream.m3u8")
    lock = lock_for_key("hls:" + key)
    with lock:
        try:
            src_m = os.path.getmtime(src_path)
        except OSError:
            abort(404)
        ok = False
        if os.path.exists(manifest_path):
            try:
                ok = os.path.getmtime(manifest_path) >= src_m and os.path.getsize(manifest_path) > 0
            except OSError:
                ok = False
        if not ok:
            if os.path.isdir(out_dir):
                try:
                    shutil.rmtree(out_dir)
                except Exception:
                    pass
            os.makedirs(out_dir, exist_ok=True)
            args = _hls_build_args(src_path, out_dir)
            code, out, err = run_cmd(args)
            if code != 0 or not os.path.exists(manifest_path):
                raise RuntimeError((err or out or "ffmpeg HLS packaging failed").strip())
    return key, manifest_path


def _resolve_stream_source_for_hls(root_id: str, relpath: str) -> str:
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(unquote(relpath))
        if not it:
            abort(404)
        if str(it.get("source") or "").strip().lower() == 'youtube':
            try:
                return _prepare_youtube_stream_file(str(it.get('youtube_url') or it.get('url') or ''), it)
            except Exception as e:
                raise RuntimeError(str(e))
        abort(400)
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        abort(404)
    try:
        return transcode_if_needed(abs_path)
    except Exception as e:
        info = last_ffmpeg_error()
        msg = str(e)
        try:
            if isinstance(info, dict) and info.get("src") == abs_path:
                msg = msg + "\n\nLast ffmpeg error:\n" + json.dumps(info, indent=2)
        except Exception:
            pass
        raise RuntimeError(msg)


def _rewrite_hls_manifest_text(text: str, key: str) -> str:
    base = "/hls/file/" + quote(key, safe="") + "/"
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out.append(raw)
            continue
        if line.startswith("#EXT-X-MAP:"):
            line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + base + quote(os.path.basename(m.group(1)), safe="/._-") + '"', line)
            out.append(line)
            continue
        if line.startswith("#"):
            out.append(raw)
            continue
        out.append(base + quote(line, safe="/._-"))
    return "\n".join(out) + "\n"


@app.route("/hls/manifest", methods=["GET"])
def hls_manifest():
    root_id = str(request.args.get("root_id") or "")
    rel = str(request.args.get("rel") or "")
    if not root_id or not rel:
        abort(400)
    try:
        playable = _resolve_stream_source_for_hls(root_id, rel)
        key, manifest_path = _hls_cache_entry_for_path(playable)
        with open(manifest_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        return Response(_rewrite_hls_manifest_text(raw, key), mimetype="application/vnd.apple.mpegurl")
    except RuntimeError as e:
        return Response(str(e), status=500, mimetype="text/plain")


@app.route("/hls/file/<key>/<path:name>", methods=["GET", "HEAD"])
def hls_file(key: str, name: str):
    key2 = re.sub(r"[^a-fA-F0-9]", "", str(key or ""))[:64]
    if not key2:
        abort(404)
    base = os.path.join(hls_cache_dir(), key2)
    try:
        path = safe_path_join(base, unquote(name))
    except ValueError:
        abort(400)
    if not os.path.exists(path) or not os.path.isfile(path):
        abort(404)
    mime = pick_mime(path)
    if request.method.upper() == "HEAD":
        return Response(status=200, headers={"Content-Length": str(os.path.getsize(path))}, mimetype=mime)
    return range_response(path)


@app.route("/stream/<root_id>/<path:relpath>", methods=["GET", "HEAD"])
def stream(root_id: str, relpath: str):
    if root_id == SEARCH_STREAM_ROOT_ID:
        it = _search_stream_get_or_restore(unquote(relpath))
        if not it:
            abort(404)
        if str(it.get("source") or "").strip().lower() == 'youtube':
            try:
                local_path = _prepare_youtube_stream_file(str(it.get('youtube_url') or it.get('url') or ''), it)
            except Exception as e:
                return Response(str(e), status=502, mimetype="text/plain")
            return range_response(local_path)
        headers = {}
        rng = request.headers.get("Range")
        if rng:
            headers["Range"] = rng
        method = "HEAD" if request.method == "HEAD" else "GET"
        try:
            upstream = requests.request(method, str(it.get("url") or ""), headers=headers, stream=True, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        except Exception as e:
            return Response(str(e), status=502, mimetype="text/plain")
        excluded = {"content-encoding", "transfer-encoding", "connection"}
        out_headers = []
        for k2, v2 in upstream.headers.items():
            if str(k2).lower() in excluded:
                continue
            out_headers.append((k2, v2))
        if request.method == "HEAD":
            return Response(status=upstream.status_code, headers=out_headers)
        def gen():
            try:
                for chunk in upstream.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        yield chunk
            finally:
                try:
                    upstream.close()
                except Exception:
                    pass
        return Response(gen(), status=upstream.status_code, headers=out_headers)
    r = root_by_id(root_id)
    if not r:
        abort(404)
    _, _, root_abs, _ = r
    rel = unquote(relpath)
    try:
        abs_path = safe_path_join(root_abs, rel)
    except ValueError:
        abort(400)

    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        abort(404)

    try:
        playable = transcode_if_needed(abs_path)
    except Exception as e:
        info = last_ffmpeg_error()
        msg = str(e)
        try:
            if isinstance(info, dict) and info.get("src") == abs_path:
                msg = msg + "\n\nLast ffmpeg error:\n" + json.dumps(info, indent=2)
        except Exception:
            pass
        try:
            print("STREAM ERROR:", msg)
        except Exception:
            pass
        return Response(msg, status=500, mimetype="text/plain")

    return range_response(playable)


@app.route("/watch/<root_id>/<path:relpath>", methods=["GET"])
def watch(root_id: str, relpath: str):
    rel = unquote(relpath)
    # legacy endpoint kept for older links, now routed into the Library player
    return redirect("/?tab=library&vroot=" + quote(root_id) + "&vrel=" + quote(rel, safe=""))



def main():
    global SOULSEEK_SERVICE
    ensure_dirs()
    load_playback_state()
    try:
        configure_aioslsk_logging()
    except Exception:
        pass
    if not REAL_DEBRID_API_KEY:
        raise RuntimeError("Set REAL_DEBRID_API_KEY at the top of this file before running")

    # Start Soulseek once at startup and keep it connected for the whole session.
    if (SOULSEEK_USERNAME or "").strip() and (SOULSEEK_PASSWORD or "").strip():
        try:
            SOULSEEK_SERVICE = SoulseekService(
                username=SOULSEEK_USERNAME,
                password=SOULSEEK_PASSWORD,
                download_dir=SOULSEEK_DOWNLOAD_DIR,
                listening_port=SOULSEEK_LISTENING_PORT,
                obfuscated_port=SOULSEEK_OBFUSCATED_PORT,
                search_timeout_sec=SOULSEEK_SEARCH_TIMEOUT_SEC,
                search_max_results=SOULSEEK_SEARCH_MAX_RESULTS,
            )
            if not SOULSEEK_SERVICE.is_ready():
                err = SOULSEEK_SERVICE.start_error() or "Unknown start error"
                print("Soulseek failed to start:", err)
        except Exception as e:
            SOULSEEK_SERVICE = None
            print("Soulseek failed to start:", str(e))
    else:
        SOULSEEK_SERVICE = None

    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
