from __future__ import annotations

from .runtime_state import *
from .runtime_video_post import *

YTDLP_PROCESS_SEMAPHORE = threading.BoundedSemaphore(2)
YTDLP_DOWNLOAD_TIMEOUT_SECONDS = 6 * 3600


def _youtube_recompute_overall(task_id: str) -> None:
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        files = list(getattr(task, "youtube_files", []) or []) if task else []
    done = sum(max(0, int(item.get("done") or 0)) for item in files)
    totals = [max(0, int(item.get("total") or 0)) for item in files]
    set_task(task_id, overall_done=done, overall_total=(sum(totals) if any(totals) else None))

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
        entries = list(getattr(tcur, 'youtube_files', []) or []) if tcur else []
    for e in entries:
        file_id = str(e.get('file_id') or '')
        st = str(e.get('state') or '').lower()
        ctl = _get_file_control(task_id, file_id) if file_id else {}
        if ctl.get('canceled'):
            _update_task_file_entry(task_id, 'youtube_files', file_id, state='canceled', canceled=True, error='')
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
        _update_task_file_entry(task_id, 'youtube_files', file_id, state='canceled', canceled=True, error='')
        return None
    if ctl.get('paused'):
        _update_task_file_entry(task_id, 'youtube_files', file_id, state='paused', paused=True, error='')
        return None

    title = sanitize_filename(str(entry.get('name') or entry.get('title') or 'youtube'))
    ext = str(entry.get('ext') or '').strip().lower() or 'mp4'
    format_id = str(entry.get('format_id') or entry.get('itag') or entry.get('file_id') or '').strip()
    media = str(entry.get('media') or '').strip().lower()
    source_url = str(entry.get('source_url') or entry.get('url') or task.source_url or task.magnet or '').strip()
    if not source_url:
        raise RuntimeError('No URL found for the selected format')
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
        source_url,
    ]

    initial_total = int(entry.get('total') or 0)
    _update_task_file_entry(task_id, 'youtube_files', file_id, state='downloading', paused=False, canceled=False, error='', out_path=preferred_out, name=os.path.basename(preferred_out), done=0, speed=0.0, total=initial_total)
    set_task(task_id, current_file=os.path.basename(preferred_out), current_done=0, current_total=(initial_total or None), state='downloading', message=f'Downloading {seq} of {total_count}')
    _youtube_recompute_overall(task_id)

    YTDLP_PROCESS_SEMAPHORE.acquire()
    try:
        proc = subprocess.Popen([YTDLP_CMD] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', bufsize=1)
    except Exception:
        try:
            YTDLP_PROCESS_SEMAPHORE.release()
        except Exception:
            pass
        raise
    actual_path = ''
    last_error = ''
    pause_requested = False
    cancel_requested = False
    started_at = time.time()
    timed_out = False
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
            elif (time.time() - started_at) > YTDLP_DOWNLOAD_TIMEOUT_SECONDS:
                timed_out = True
            if pause_requested or cancel_requested:
                try:
                    proc.terminate()
                except Exception:
                    pass
            if timed_out:
                try:
                    proc.kill()
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
                        _update_task_file_entry(task_id, 'youtube_files', file_id, state='downloading', done=done, total=total, speed=speed, error='')
                        set_task(task_id, current_done=done, current_total=(total or None), message=f'Downloading {seq} of {total_count}')
                        _youtube_recompute_overall(task_id)
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
        try:
            YTDLP_PROCESS_SEMAPHORE.release()
        except Exception:
            pass

    if cancel_requested:
        _update_task_file_entry(task_id, 'youtube_files', file_id, state='canceled', canceled=True, error='')
        _youtube_recompute_overall(task_id)
        return None
    if pause_requested:
        _update_task_file_entry(task_id, 'youtube_files', file_id, state='paused', paused=True, error='')
        _youtube_recompute_overall(task_id)
        return None
    if rc != 0:
        if timed_out:
            raise RuntimeError('yt-dlp timed out')
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
    _update_task_file_entry(task_id, 'youtube_files', file_id, state='complete', done=sz, total=sz, speed=0.0, out_path=actual or preferred_out, name=final_name, ext=(final_ext or ext), error='', paused=False, canceled=False)
    _youtube_recompute_overall(task_id)
    return actual or preferred_out


def _youtube_finalize_task_state(task_id: str, default_message: str = 'Finished') -> None:
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        entries = list(getattr(t, 'youtube_files', []) or []) if t else []
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
            entries = list(getattr(tcur, 'youtube_files', []) or []) if tcur else []
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
        except Exception:
            _update_task_file_entry(task_id, 'youtube_files', fid, state='failed', error='YouTube download failed', paused=False)
            _youtube_recompute_overall(task_id)
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
    except Exception:
        set_task(task_id, state='error', message='YouTube download failed', current_file='', current_done=0, current_total=None)


def youtube_worker(task_id: str) -> None:
    task = get_task(task_id)
    if not task:
        return
    try:
        entries = list(getattr(task, 'youtube_files', []) or [])
        if not entries:
            raise RuntimeError('No YouTube formats selected')
        set_task(task_id, state='downloading', message=f'Downloading {len(entries)} YouTube file(s)', overall_done=0, overall_total=None)
        _youtube_download_from_queue(task_id)
    except Cancelled:
        set_task(task_id, state='canceled', message='Canceled', current_file='', current_done=0, current_total=None)
    except Exception:
        set_task(task_id, state='error', message='YouTube download failed', current_file='', current_done=0, current_total=None)






__all__ = [name for name in globals() if not name.startswith("__")]
