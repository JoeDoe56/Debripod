from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..media_types import AUDIO_EXTS, VIDEO_EXTS
from ..paths import cache_dir
from ..utils import sanitize_filename, sanitize_folder_name

SOULSEEK_DOWNLOAD_DIR = ""
SOULSEEK_SEARCH_IDLE_STOP_SEC = 0.0
SOULSEEK_SEARCH_HARD_MAX_SEC = 0.0
TASKS: Dict[str, Any] = {}
TASKS_LOCK = threading.Lock()
SOULSEEK_ENQUEUE_SEMAPHORE = asyncio.Semaphore(3)
_SLSK_SESS_LOCK = threading.Lock()
_SLSK_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _missing_task(_task_id: str) -> Any:
    return None


def _noop_set_task(_task_id: str, **_updates: Any) -> None:
    return None


def _noop_set_file_control(_task_id: str, _file_id: str, **_updates: Any) -> None:
    return None


def _noop_get_file_control(_task_id: str, _file_id: str) -> Dict[str, Any]:
    return {}


get_task = _missing_task
set_task = _noop_set_task
_set_file_control = _noop_set_file_control
_get_file_control = _noop_get_file_control


def configure_soulseek_module(
    *,
    download_dir: str,
    search_idle_stop_sec: float,
    search_hard_max_sec: float,
    tasks: Dict[str, Any],
    tasks_lock: threading.Lock,
    get_task_func,
    set_task_func,
    set_file_control_func,
    get_file_control_func,
) -> None:
    global SOULSEEK_DOWNLOAD_DIR, SOULSEEK_SEARCH_IDLE_STOP_SEC, SOULSEEK_SEARCH_HARD_MAX_SEC
    global TASKS, TASKS_LOCK, get_task, set_task, _set_file_control, _get_file_control
    SOULSEEK_DOWNLOAD_DIR = download_dir
    SOULSEEK_SEARCH_IDLE_STOP_SEC = float(search_idle_stop_sec or 0.0)
    SOULSEEK_SEARCH_HARD_MAX_SEC = float(search_hard_max_sec or 0.0)
    TASKS = tasks
    TASKS_LOCK = tasks_lock
    get_task = get_task_func
    set_task = set_task_func
    _set_file_control = set_file_control_func
    _get_file_control = get_file_control_func

def _slsk_gc_sessions(max_keep: int = 20) -> None:
    with _SLSK_SESS_LOCK:
        if len(_SLSK_SESSIONS) <= max_keep:
            return
        # Drop oldest done sessions first
        items = list(_SLSK_SESSIONS.items())
        items.sort(key=lambda kv: float(kv[1].get("created") or 0.0))
        for sid, sess in items:
            if len(_SLSK_SESSIONS) <= max_keep:
                break
            if sess.get("done"):
                _SLSK_SESSIONS.pop(sid, None)

def _slsk_session_create(cache_key: str, q: str) -> str:
    sid = uuid.uuid4().hex
    with _SLSK_SESS_LOCK:
        _slsk_gc_sessions()
        _SLSK_SESSIONS[sid] = {
            "id": sid,
            "cache_key": cache_key,
            "q": q,
            "created": time.time(),
            "rev": 0,
            "done": False,
            "error": "",
            "items": {},
            "user_speed": {},
            "file_count": 0,
            "dir_count": 0,
            "last_touch": time.time(),
        }
    return sid

def _slsk_session_touch(sid: str) -> None:
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(sid)
        if s:
            s["last_touch"] = time.time()

def _slsk_session_add_items(session_id: str, items: List[Dict[str, Any]]) -> None:
    if not items:
        return
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(session_id)
        if not s or s.get("done"):
            return
        store = s.get("items")
        if not isinstance(store, dict):
            store = {}
            s["items"] = store
        user_speed = s.get("user_speed")
        if not isinstance(user_speed, dict):
            user_speed = {}
            s["user_speed"] = user_speed

        new_any = False
        for it in items:
            user = (it.get("user") or "").strip()
            rp = str(it.get("remote_path") or "")
            if not user or not rp:
                continue
            rp_norm = _slsk_norm_remote_path(rp)
            parts = rp_norm.split("\\")
            fname = parts[-1] if parts else rp_norm
            directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
            key = user + "|" + rp_norm
            if key in store:
                continue
            kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)
            try:
                size = int(it.get("size") or 0)
            except Exception:
                size = 0
            try:
                speed = int(it.get("speed") or 0)
            except Exception:
                speed = 0

            store[key] = {
                "user": user,
                "directory": directory,
                "name": fname,
                "remote_path": rp_norm,
                "size": size,
                "ext": ext,
                "kind": kind,
                "bitrate": br,
                "bit_depth": bd,
                "sample_rate": sr,
                "duration": dur,
                "vbr": vbr,
                "codec": codec,
                "speed": speed,
            }
            if speed and (user_speed.get(user, 0) < speed):
                user_speed[user] = speed
            new_any = True

        if new_any:
            # Recompute counts
            file_count = len(store)
            dirs = set()
            for v in store.values():
                dirs.add((v.get("user") or "", v.get("directory") or ""))
            s["file_count"] = int(file_count)
            s["dir_count"] = int(len(dirs))
            s["rev"] = int(s.get("rev") or 0) + 1
            s["last_touch"] = time.time()

def _slsk_session_mark_done(session_id: str, error: str = "") -> None:
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(session_id)
        if not s:
            return
        if s.get("done"):
            return
        s["done"] = True
        s["error"] = str(error or "")
        s["rev"] = int(s.get("rev") or 0) + 1
        s["last_touch"] = time.time()

def _slsk_session_snapshot(session_id: str) -> Optional[Dict[str, Any]]:
    with _SLSK_SESS_LOCK:
        s = _SLSK_SESSIONS.get(session_id)
        if not s:
            return None
        # Lightweight copy
        return {
            "id": s.get("id") or "",
            "cache_key": s.get("cache_key") or "",
            "q": s.get("q") or "",
            "created": float(s.get("created") or 0.0),
            "rev": int(s.get("rev") or 0),
            "done": bool(s.get("done")),
            "error": s.get("error") or "",
            "file_count": int(s.get("file_count") or 0),
            "dir_count": int(s.get("dir_count") or 0),
            "items": dict(s.get("items") or {}),
            "user_speed": dict(s.get("user_speed") or {}),
        }

def _slsk_download_state_priority(state: str) -> int:
    s = _slsk_clean_state_token(state)
    if s == "complete":
        return 100
    if s in {"downloading", "uploading", "initializing", "queued", "paused"}:
        return 80
    if s in {"incomplete", "failed", "aborted"}:
        return 60
    return 0


def _slsk_lookup_download_state(user: str, remote_path: str) -> Dict[str, Any]:
    user_s = str(user or "").strip()
    rp_norm = _slsk_norm_remote_path(remote_path or "")
    if not user_s or not rp_norm:
        return {}

    best: Dict[str, Any] = {}
    best_rank = -1
    with TASKS_LOCK:
        tasks = sorted(TASKS.values(), key=lambda t: float(getattr(t, "created", 0.0) or 0.0), reverse=True)

    for t in tasks:
        if (getattr(t, "source", "") or "").lower() != "soulseek":
            continue
        for f in list(getattr(t, "slsk_files", []) or []):
            try:
                fu = str(f.get("user") or getattr(t, "slsk_user", "") or "").strip()
                frp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            except Exception:
                continue
            if fu != user_s or frp.lower() != rp_norm.lower():
                continue
            st = _slsk_normalize_state(
                str(f.get("state") or f.get("state_raw") or ""),
                bool(f.get("paused")),
                bool(f.get("canceled")),
                _slsk_int_from_any(f.get("done") or 0),
                _slsk_int_from_any(f.get("total") or f.get("size") or 0),
                bool(f.get("error")),
            )
            rank = _slsk_download_state_priority(st)
            if rank > best_rank:
                best_rank = rank
                best = {
                    "download_state": st,
                    "download_task_id": str(getattr(t, "id", "") or ""),
                    "download_error": str(f.get("error") or ""),
                }
                if rank >= 100:
                    return best
    return best


def _slsk_annotate_file_with_download_state(file_obj: Dict[str, Any], user: str) -> Dict[str, Any]:
    if not isinstance(file_obj, dict):
        return file_obj
    info = _slsk_lookup_download_state(user, str(file_obj.get("remote_path") or ""))
    if info:
        file_obj.update(info)
    return file_obj


def _slsk_group_snapshot_to_users(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    store = snap.get("items") or {}
    user_speed = snap.get("user_speed") or {}
    users: Dict[str, Dict[str, Any]] = {}
    for v in store.values():
        user = v.get("user") or ""
        directory = v.get("directory") or ""
        if not user:
            continue
        u = users.get(user)
        if u is None:
            u = {"user": user, "speed": int(user_speed.get(user) or 0), "dirs": [], "total_files": 0}
            users[user] = u
        # directory entry
        dir_map = u.setdefault("_dir_map", {})
        dd = dir_map.get(directory)
        if dd is None:
            dd = {"directory": directory, "files": [], "total_size": 0}
            dir_map[directory] = dd
            u["dirs"].append(dd)
        fobj = {
            "name": v.get("name") or "",
            "remote_path": v.get("remote_path") or "",
            "size": int(v.get("size") or 0),
            "ext": v.get("ext") or "",
            "kind": v.get("kind") or "file",
            "bitrate": v.get("bitrate"),
            "bit_depth": v.get("bit_depth"),
            "sample_rate": v.get("sample_rate"),
            "duration": v.get("duration"),
            "vbr": v.get("vbr"),
            "codec": v.get("codec") or "",
        }
        fobj = _slsk_annotate_file_with_download_state(fobj, user)
        dd["files"].append(fobj)
        dd["total_size"] = int(dd.get("total_size") or 0) + int(fobj.get("size") or 0)
        u["total_files"] = int(u.get("total_files") or 0) + 1

    # Clean internal maps and sort
    out: List[Dict[str, Any]] = []
    for u in users.values():
        try:
            u.pop("_dir_map", None)
        except Exception:
            pass
        # sort dirs by total_size desc
        try:
            u["dirs"].sort(key=lambda d: int(d.get("total_size") or 0), reverse=True)
        except Exception:
            pass
        out.append(u)

    # Sort users by speed desc
    out.sort(key=lambda x: int(x.get("speed") or 0), reverse=True)
    return out



def _slsk_norm_remote_path(p: str) -> str:
    s = (p or "").replace("/", "\\")
    s = s.lstrip("\\")
    return s


def _slsk_safe_remote_parts(p: str) -> List[str]:
    s = _slsk_norm_remote_path(p)
    if "\x00" in s or re.match(r"^[A-Za-z]:", s) or s.startswith("\\\\"):
        return []
    reserved = {"con", "prn", "aux", "nul", "clock$"}
    reserved.update({f"com{i}" for i in range(1, 10)})
    reserved.update({f"lpt{i}" for i in range(1, 10)})
    out: List[str] = []
    for part in s.split("\\"):
        raw = part.strip()
        clean = raw.rstrip(". ")
        if not clean or clean in {".", ".."}:
            continue
        if clean.lower() in reserved:
            continue
        out.append(sanitize_filename(clean))
    return [x for x in out if x]


def _slsk_local_path(download_dir: str, remote_path: str) -> str:
    parts = _slsk_safe_remote_parts(remote_path)
    base = os.path.realpath(os.path.abspath(download_dir))
    candidate = os.path.realpath(os.path.abspath(os.path.join(base, *parts))) if parts else base
    try:
        if os.path.commonpath([base, candidate]) != base:
            return base
    except Exception:
        return base
    return candidate


def soulseek_log_file_path() -> str:
    # Keeps Soulseek (aioslsk) logs out of the terminal; written to a dedicated file.
    return os.path.join(cache_dir(), "incoming", "soulseek_aioslsk.log")


def soulseek_incoming_dir() -> str:
    return os.path.join(cache_dir(), "incoming", "soulseek")


def _slsk_sanitized_dir_name(remote_directory: str) -> str:
    d = _slsk_norm_remote_path(remote_directory or "")
    base = d.split("\\")[-1].strip() if d else ""
    base = sanitize_filename(base) if base else ""
    return base or "soulseek"


def _slsk_task_download_dir(remote_directory: str) -> str:
    return os.path.join(SOULSEEK_DOWNLOAD_DIR, _slsk_sanitized_dir_name(remote_directory))


def _slsk_relative_under_directory(remote_directory: str, remote_path: str) -> str:
    d = _slsk_norm_remote_path(remote_directory or "").rstrip("\\")
    p = _slsk_norm_remote_path(remote_path or "")
    if d and p.lower().startswith((d + "\\").lower()):
        rel = p[len(d) + 1 :]
    else:
        rel = p.split("\\")[-1]
    parts = _slsk_safe_remote_parts(rel.lstrip("\\"))
    if parts:
        return "\\".join(parts)
    fallback_parts = _slsk_safe_remote_parts(p.split("\\")[-1] if p else "")
    return "\\".join(fallback_parts)




def _slsk_collect_browse_items(obj: Any, user: str = "", base_dir: str = "", _seen: Optional[set] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if _seen is None:
        _seen = set()
    try:
        oid = id(obj)
    except Exception:
        oid = None
    if oid is not None:
        if oid in _seen:
            return items
        _seen.add(oid)

    def _get(o: Any, key: str, default=None):
        if isinstance(o, dict):
            return o.get(key, default)
        return getattr(o, key, default)

    if obj is None:
        return items

    if isinstance(obj, (list, tuple, set)):
        for part in obj:
            items.extend(_slsk_collect_browse_items(part, user=user, base_dir=base_dir, _seen=_seen))
        return items

    rp = _get(obj, "remote_path", None)
    if rp is None:
        rp = _get(obj, "filename", None)
    if rp is None:
        rp = _get(obj, "path", None)
    rp_str = str(rp or "").strip()
    if rp_str:
        rp_norm = _slsk_norm_remote_path(rp_str)
        if "\\" not in rp_norm and base_dir:
            rp_norm = _slsk_norm_remote_path(base_dir.rstrip("\\") + "\\" + rp_norm)
        parts = rp_norm.split("\\")
        fname = parts[-1] if parts else rp_norm
        directory = "\\".join(parts[:-1]) if len(parts) > 1 else ""
        size = _get(obj, "size", None)
        if size is None:
            size = _get(obj, "filesize", 0)
        try:
            size = int(size or 0)
        except Exception:
            size = 0
        kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, obj)
        items.append({
            "user": str(user or _get(obj, "username", "") or _get(obj, "user", "") or ""),
            "directory": directory,
            "name": fname,
            "remote_path": rp_norm,
            "size": size,
            "ext": ext,
            "kind": kind,
            "bitrate": br,
            "bit_depth": bd,
            "sample_rate": sr,
            "duration": dur,
            "vbr": vbr,
            "codec": codec,
        })
        return items

    next_base = base_dir
    dir_name = _get(obj, "directory", None)
    if dir_name is None:
        dir_name = _get(obj, "name", None)
    if dir_name is None:
        dir_name = _get(obj, "path", None)
    dir_name_s = str(dir_name or "").strip()
    if dir_name_s and dir_name_s != base_dir:
        if "\\" in dir_name_s or "/" in dir_name_s:
            next_base = _slsk_norm_remote_path(dir_name_s)
        else:
            next_base = _slsk_norm_remote_path((base_dir.rstrip("\\") + "\\" + dir_name_s) if base_dir else dir_name_s)

    for key in ("files", "items", "shared_items", "children", "directories", "dirs", "subdirs", "subdirectories"):
        val = _get(obj, key, None)
        if val:
            items.extend(_slsk_collect_browse_items(val, user=user, base_dir=next_base, _seen=_seen))

    if not items and not isinstance(obj, dict):
        for key in dir(obj):
            if key.startswith("_"):
                continue
            if key in {"remote_path", "filename", "path", "size", "filesize", "name", "directory"}:
                continue
            try:
                val = getattr(obj, key)
            except Exception:
                continue
            if callable(val):
                continue
            if isinstance(val, (str, bytes, int, float, bool)):
                continue
            items.extend(_slsk_collect_browse_items(val, user=user, base_dir=next_base, _seen=_seen))
    return items


def _slsk_group_items_to_dirs(user: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    dirs: Dict[str, Dict[str, Any]] = {}
    seen: set = set()
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        rp = _slsk_norm_remote_path(str(it.get("remote_path") or ""))
        if not rp or rp in seen:
            continue
        seen.add(rp)
        directory = _slsk_norm_remote_path(str(it.get("directory") or ""))
        if not directory and "\\" in rp:
            directory = "\\".join(rp.split("\\")[:-1])
        name = str(it.get("name") or rp.split("\\")[-1] or "")
        dd = dirs.get(directory)
        if dd is None:
            dd = {"directory": directory, "files": [], "total_size": 0, "total_files": 0}
            dirs[directory] = dd
        fobj = {
            "name": name,
            "remote_path": rp,
            "size": int(it.get("size") or 0),
            "ext": it.get("ext") or "",
            "kind": it.get("kind") or "file",
            "bitrate": it.get("bitrate"),
            "bit_depth": it.get("bit_depth"),
            "sample_rate": it.get("sample_rate"),
            "duration": it.get("duration"),
            "vbr": it.get("vbr"),
            "codec": it.get("codec") or "",
        }
        fobj = _slsk_annotate_file_with_download_state(fobj, user)
        dd["files"].append(fobj)
        dd["total_size"] = int(dd.get("total_size") or 0) + int(fobj.get("size") or 0)
        dd["total_files"] = int(dd.get("total_files") or 0) + 1

    out = list(dirs.values())
    out.sort(key=lambda d: (int(d.get("total_size") or 0), int(d.get("total_files") or 0), str(d.get("directory") or "").lower()), reverse=True)
    return out


def _slsk_expected_incoming_path(remote_path: str) -> str:
    fn = _slsk_norm_remote_path(remote_path or "").split("\\")[-1]
    return os.path.join(soulseek_incoming_dir(), fn) if fn else soulseek_incoming_dir()


def _safe_move_file(src_path: str, dst_path: str) -> str:
    """Move a file to dst_path, with automatic renaming if needed. Returns the final destination path."""
    src_path = str(src_path or "")
    dst_path = str(dst_path or "")
    if not src_path or not dst_path:
        return dst_path
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    if not os.path.exists(src_path):
        return dst_path
    if not os.path.exists(dst_path):
        try:
            os.replace(src_path, dst_path)
            return dst_path
        except Exception:
            pass
    base, ext = os.path.splitext(dst_path)
    for i in range(1, 1000):
        cand = f"{base} ({i}){ext}"
        if not os.path.exists(cand):
            try:
                os.replace(src_path, cand)
                return cand
            except Exception:
                continue
    return dst_path


class _DropAioslskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return not (record and getattr(record, "name", "").startswith("aioslsk"))
        except Exception:
            return True


def configure_aioslsk_logging() -> str:
    """Route aioslsk logs to a dedicated file and prevent them from printing to the terminal."""
    log_file = soulseek_log_file_path()
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
    except Exception:
        pass

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)

    # Prevent any existing root handlers from printing aioslsk logs.
    drop = _DropAioslskFilter()
    root = logging.getLogger()
    for h in list(getattr(root, "handlers", []) or []):
        try:
            h.addFilter(drop)
        except Exception:
            pass

    # Attach our handler to aioslsk loggers and stop propagation.
    try:
        names = list(logging.root.manager.loggerDict.keys())
    except Exception:
        names = []
    if "aioslsk" not in names:
        names.append("aioslsk")
    for name in names:
        if name == "aioslsk" or str(name).startswith("aioslsk."):
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            try:
                lg.handlers.clear()
            except Exception:
                for old in list(getattr(lg, "handlers", []) or []):
                    try:
                        lg.removeHandler(old)
                    except Exception:
                        pass
            lg.addHandler(fh)
            lg.propagate = False

    return log_file


def _slsk_resolve_local_progress_path(final_path: str) -> str:
    """Return a path that is likely to exist while downloading (handles common temp extensions)."""
    p = str(final_path or "")
    if not p:
        return p
    try:
        if os.path.exists(p):
            return p
        exts = [".part", ".partial", ".incomplete", ".tmp", ".download", ".downloading"]
        for ext in exts:
            cand = p + ext
            if os.path.exists(cand):
                return cand
        d = os.path.dirname(p)
        bn = os.path.basename(p)
        if d and os.path.isdir(d) and bn:
            for fn in os.listdir(d):
                if fn != bn and fn.startswith(bn):
                    cand = os.path.join(d, fn)
                    if os.path.isfile(cand):
                        return cand
    except Exception:
        pass
    return p


def _slsk_int_from_any(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0



def _slsk_clean_state_token(v: Any) -> str:
    s = ""
    try:
        if v is None:
            return ""
        if hasattr(v, "name"):
            s = str(getattr(v, "name", "") or "")
        else:
            s = str(v or "")
    except Exception:
        s = ""
    s = s.strip()
    if not s:
        return ""
    # Common enum/string formats: "TransferState.DOWNLOADING", "DOWNLOAD))"
    if "." in s:
        s = s.split(".")[-1]
    s = s.lower()
    # Remove non-token characters
    try:
        s = re.sub(r"[^a-z_]+", "", s)
    except Exception:
        pass
    s = s.strip("_")
    return s


def _slsk_normalize_state(raw_state: str, paused: bool, canceled: bool, done: int, total: int, has_error: bool) -> str:
    s = _slsk_clean_state_token(raw_state)

    if canceled:
        return "aborted"
    if paused and s != "complete":
        return "paused"
    if total > 0 and done >= total and done > 0:
        return "complete"

    if s in {"done", "finished", "completed", "complete", "success", "succeeded"}:
        return "complete"
    if s in {"abort", "aborted", "aborting", "cancel", "canceled", "cancelled"}:
        return "aborted"
    if s in {"pause", "paused", "pausing"}:
        return "paused"
    if s in {"incomplete", "retry", "retrying", "willretry", "queued_retry", "queuedretry"}:
        return "incomplete"
    if s in {"fail", "failed", "failure", "error", "exception", "timeout", "timedout", "timed_out"}:
        return "failed"
    if s in {"queue", "queued", "enqueued", "waiting", "pending", "idle"}:
        return "queued"
    if s in {"initialize", "initializing", "init", "starting", "request", "requesting", "requested", "connect", "connecting", "handshake", "negotiating"}:
        return "initializing"
    if s in {"upload", "uploading", "sending"}:
        return "uploading"
    if s in {"download", "downloading", "transfer", "transferring", "receiving", "inprogress", "in_progress", "active"}:
        return "downloading"

    if has_error:
        if s in {"incomplete", "retry", "retrying", "willretry", "queued_retry", "queuedretry"}:
            return "incomplete"
        return "failed"

    if done > 0 and (total <= 0 or done < total):
        return "downloading"
    if total > 0 and done >= total and done > 0:
        return "complete"
    return "queued"



def _slsk_extract_transfer_progress(tr: Any) -> Tuple[int, int, float, str]:
    """Best-effort extraction of (done_bytes, total_bytes, speed_bps, state_str) from aioslsk transfer objects."""
    done = 0
    total = 0
    speed = 0.0
    state = ""
    if tr is None:
        return done, total, speed, state

    # state
    try:
        st = getattr(tr, "state", "")
        if hasattr(st, "name"):
            state = str(getattr(st, "name", "")).lower()
        else:
            s = str(st or "")
            if "." in s:
                s = s.split(".")[-1]
            state = s.lower()
    except Exception:
        state = ""

    state = _slsk_clean_state_token(state) if state else ""

    # total
    for attr in ("filesize", "file_size", "size", "total", "total_bytes", "bytes_total", "expected_size"):
        try:
            total = _slsk_int_from_any(getattr(tr, attr, 0))
        except Exception:
            total = 0
        if total > 0:
            break

    # done
    for attr in ("bytes_received", "received", "bytes_transferred", "transferred", "downloaded", "bytes_done", "position", "offset"):
        try:
            done = _slsk_int_from_any(getattr(tr, attr, 0))
        except Exception:
            done = 0
        if done > 0:
            break

    # Some aioslsk versions store progress in a nested object
    try:
        prog = getattr(tr, "progress", None)
    except Exception:
        prog = None
    if prog is not None:
        if total <= 0:
            for attr in ("total", "total_bytes", "bytes_total", "filesize", "file_size", "size", "expected_size"):
                try:
                    total = _slsk_int_from_any(getattr(prog, attr, 0))
                except Exception:
                    total = 0
                if total > 0:
                    break
        if done <= 0:
            for attr in ("done", "bytes_received", "received", "bytes_transferred", "transferred", "downloaded", "bytes_done", "position", "offset"):
                try:
                    done = _slsk_int_from_any(getattr(prog, attr, 0))
                except Exception:
                    done = 0
                if done > 0:
                    break

    # speed
    for attr in ("speed", "bps", "bytes_per_second", "download_speed", "upload_speed"):
        try:
            s = getattr(tr, attr, None)
            if s is None:
                continue
            speed = float(s)
        except Exception:
            speed = 0.0
        if speed > 0:
            break

    return done, total, speed, state


def _slsk_extract_transfer_error(tr: Any) -> str:
    if tr is None:
        return ""
    for attr in ("error", "exception", "reason", "failure_reason", "last_error", "message"):
        try:
            v = getattr(tr, attr, None)
            if v:
                return str(v)
        except Exception:
            continue
    # Some versions keep errors nested
    for parent in ("progress", "status"):
        try:
            obj = getattr(tr, parent, None)
        except Exception:
            obj = None
        if obj is None:
            continue
        for attr in ("error", "exception", "reason", "failure_reason", "last_error", "message"):
            try:
                v = getattr(obj, attr, None)
                if v:
                    return str(v)
            except Exception:
                continue
    return ""


def _slsk_transfer_is_paused(tr: Any) -> bool:
    if tr is None:
        return False
    for attr in ("paused", "is_paused"):
        try:
            v = getattr(tr, attr, None)
            if isinstance(v, bool):
                return v
        except Exception:
            continue
    # state string sometimes includes paused
    try:
        st = getattr(tr, "state", "")
        s = str(getattr(st, "name", st) or "").lower()
        if "pause" in s:
            return True
    except Exception:
        pass
    return False


def _slsk_as_mapping(x: Any) -> Optional[Dict[str, Any]]:
    if x is None:
        return None
    if isinstance(x, dict):
        return x
    if isinstance(x, (list, tuple)):
        try:
            if all(isinstance(i, (list, tuple)) and len(i) == 2 for i in x):
                return {str(k): v for k, v in x}  # type: ignore
        except Exception:
            return None
    return None


def _slsk_to_dict(x: Any) -> Optional[Dict[str, Any]]:
    if x is None:
        return None
    if isinstance(x, dict):
        return x
    for mname in ("to_dict", "dict", "as_dict"):
        try:
            if hasattr(x, mname):
                d = getattr(x, mname)()
                if isinstance(d, dict):
                    return d
        except Exception:
            continue
    return None


def _slsk_pick(obj: Any, *names: str) -> Any:
    for n in names:
        try:
            if hasattr(obj, n):
                v = getattr(obj, n)
                if v is not None and v != "":
                    return v
        except Exception:
            pass
        try:
            if isinstance(obj, dict) and n in obj:
                v = obj.get(n)
                if v is not None and v != "":
                    return v
        except Exception:
            pass

    for cname in ("attributes", "attrs", "meta", "metadata", "info", "audio", "details", "extra"):
        c = None
        try:
            c = getattr(obj, cname, None)
        except Exception:
            c = None
        if c is None and isinstance(obj, dict):
            try:
                c = obj.get(cname)
            except Exception:
                c = None

        cm = _slsk_as_mapping(c) or _slsk_to_dict(c)
        if cm is not None:
            for n in names:
                if n in cm:
                    v = cm.get(n)
                    if v is not None and v != "":
                        return v
        else:
            for n in names:
                try:
                    if c is not None and hasattr(c, n):
                        v = getattr(c, n)
                        if v is not None and v != "":
                            return v
                except Exception:
                    pass

    d0 = _slsk_to_dict(obj)
    if d0 is not None:
        for n in names:
            if n in d0:
                v = d0.get(n)
                if v is not None and v != "":
                    return v
        for _, vv in list(d0.items())[:50]:
            dv = _slsk_as_mapping(vv) or _slsk_to_dict(vv)
            if dv is None:
                continue
            for n in names:
                if n in dv:
                    v = dv.get(n)
                    if v is not None and v != "":
                        return v
    return None


def _slsk_pick_int(obj: Any, *names: str) -> Optional[int]:
    v = _slsk_pick(obj, *names)
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None


def _slsk_attr_code_map(obj: Any) -> Dict[int, int]:
    """Return Soulseek attribute code mapping for a shared file item.

    Soulseek search results include file attributes as numeric code/value pairs.
    Common codes used by popular clients:
      0: bitrate (kbps)
      1: duration (seconds)
      2: vbr flag (1)
      4: sample rate (Hz)
      5: bit depth (bits)
    """
    candidates = []
    for cname in ("attributes", "attrs", "attr", "file_attributes", "fileAttrs", "audio_attributes", "audioAttributes"):
        try:
            v = getattr(obj, cname, None)
        except Exception:
            v = None
        if v is None and isinstance(obj, dict):
            try:
                v = obj.get(cname)
            except Exception:
                v = None
        if v is not None:
            candidates.append(v)

    # Also inspect dict views when provided by library objects
    d0 = _slsk_to_dict(obj)
    if d0:
        for k in ("attributes", "attrs", "file_attributes", "fileAttributes"):
            if k in d0 and d0.get(k) is not None:
                candidates.append(d0.get(k))

    out: Dict[int, int] = {}

    def _key_to_code(k: Any) -> Optional[int]:
        """Best effort conversion of aioslsk attribute keys into Soulseek numeric codes."""
        if k is None:
            return None
        # enum like AttributeType
        try:
            kv = getattr(k, "value", None)
            if isinstance(kv, (int, float)):
                return int(kv)
        except Exception:
            pass
        try:
            kn = getattr(k, "name", None)
            if isinstance(kn, str) and kn:
                c2 = _key_to_code(kn)
                if c2 is not None:
                    return c2
        except Exception:
            pass
        if isinstance(k, (int, float)):
            return int(k)
        if isinstance(k, str):
            s = k.strip().lower()
            if not s:
                return None
            if s.isdigit():
                try:
                    return int(s)
                except Exception:
                    return None
            s2 = s.replace("_", " ").replace("-", " ").strip()
            alias = {
                "bitrate": 0,
                "br": 0,
                "kbps": 0,
                "duration": 1,
                "length": 1,
                "time": 1,
                "vbr": 2,
                "variable bitrate": 2,
                "variable_bitrate": 2,
                "samplerate": 4,
                "sample rate": 4,
                "sample_rate": 4,
                "frequency": 4,
                "hz": 4,
                "bitdepth": 5,
                "bit depth": 5,
                "bit_depth": 5,
                "depth": 5,
                "bits": 5,
                "encoder": 3,
            }
            if s2 in alias:
                return alias[s2]
            if s in alias:
                return alias[s]
        return None

    def _val_to_int(v: Any) -> Optional[int]:
        if v is None:
            return None
        try:
            vv = getattr(v, "value", None)
            if vv is not None:
                v = vv
        except Exception:
            pass
        try:
            return int(v)
        except Exception:
            try:
                return int(float(v))
            except Exception:
                return None
    for v in candidates:
        if v is None:
            continue
        if isinstance(v, dict):
            for kk, vv in v.items():
                try:
                    ik = _key_to_code(kk)
                    iv = _val_to_int(vv)
                    if ik is None or iv is None:
                        continue
                    out[int(ik)] = int(iv)
                except Exception:
                    continue
            if out:
                return out

        if isinstance(v, (list, tuple)):
            # list of pairs
            try:
                if all(isinstance(i, (list, tuple)) and len(i) == 2 for i in v):
                    for kk, vv in v:
                        ck = _key_to_code(kk)
                        cv = _val_to_int(vv)
                        if ck is None or cv is None:
                            continue
                        out[int(ck)] = int(cv)
                    if out:
                        return out
            except Exception:
                pass

            # list of objects: [{index/code, value}, ...] or FileAttribute objects
            try:
                for it in v:
                    if it is None:
                        continue
                    if isinstance(it, dict):
                        ck = it.get("index", None)
                        if ck is None:
                            ck = it.get("code", None)
                        if ck is None:
                            ck = it.get("id", None)
                        if ck is None:
                            ck = it.get("key", None)
                        if ck is None:
                            ck = it.get("type", None)
                        if ck is None:
                            ck = it.get("attribute", None)
                        if ck is None:
                            ck = it.get("attribute_type", None)
                        if ck is None:
                            ck = it.get("attr_type", None)

                        cv = it.get("value", None)
                        if cv is None:
                            cv = it.get("val", None)
                        if cv is None:
                            cv = it.get("v", None)
                        if ck is None or cv is None:
                            continue
                        ck2 = _key_to_code(ck)
                        cv2 = _val_to_int(cv)
                        if ck2 is None or cv2 is None:
                            continue
                        try:
                            out[int(ck2)] = int(cv2)
                        except Exception:
                            continue
                    else:
                        ck = None
                        for kn in ("index", "code", "id", "key", "type", "attribute", "attribute_type", "attr_type"):
                            try:
                                ck = getattr(it, kn, None)
                            except Exception:
                                ck = None
                            if ck is not None:
                                break
                        cv = None
                        for vn in ("value", "val", "v"):
                            try:
                                cv = getattr(it, vn, None)
                            except Exception:
                                cv = None
                            if cv is not None:
                                break
                        if ck is None or cv is None:
                            continue
                        ck2 = _key_to_code(ck)
                        cv2 = _val_to_int(cv)
                        if ck2 is None or cv2 is None:
                            continue
                        try:
                            out[int(ck2)] = int(cv2)
                        except Exception:
                            continue
                if out:
                    return out
            except Exception:
                pass

            # flat list [code, value, code, value, ...]
            try:
                if len(v) >= 2 and all(isinstance(i, (int, float, str)) for i in v):
                    if len(v) % 2 == 0:
                        for i in range(0, len(v), 2):
                            ck = _key_to_code(v[i])
                            cv = _val_to_int(v[i + 1])
                            if ck is None or cv is None:
                                continue
                            out[int(ck)] = int(cv)
                        if out:
                            return out
            except Exception:
                pass

        # object with to_dict etc already handled, but try mapping conversion
        m = _slsk_as_mapping(v) or _slsk_to_dict(v)
        if m:
            for kk, vv in m.items():
                try:
                    ck = _key_to_code(kk)
                    cv = _val_to_int(vv)
                    if ck is None or cv is None:
                        continue
                    out[int(ck)] = int(cv)
                except Exception:
                    continue
            if out:
                return out

    return out


def _slsk_guess_lossless_depth_and_rate_from_name(name: str) -> Tuple[Optional[int], Optional[int]]:
    """Best effort fallback when peers omit attributes.

    Returns (bit_depth, sample_rate_hz).
    """
    n = (name or "").lower()
    bit_depth = None
    sample_rate = None

    # bit depth patterns: 16bit, 24 bit, 32-bit
    m = re.search(r"\b(16|20|24|32)\s*[-_ ]?bit\b", n)
    if m:
        try:
            bit_depth = int(m.group(1))
        except Exception:
            bit_depth = None

    # sample rate patterns: 44.1k, 48khz, 96k, 192khz
    m = re.search(r"\b(\d{2,3}(?:\.\d)?)\s*[-_ ]?(?:khz|k)\b", n)
    if m:
        try:
            khz = float(m.group(1))
            sample_rate = int(round(khz * 1000.0))
        except Exception:
            sample_rate = None

    return bit_depth, sample_rate


def _slsk_extract_media_attrs(shared_item: Any, remote_path: str, size: int) -> Dict[str, Any]:
    amap = _slsk_attr_code_map(shared_item)
    bitrate = amap.get(0)
    duration = amap.get(1)
    vbr = amap.get(2)
    sample_rate = amap.get(4)
    bit_depth = amap.get(5)

    # Some library versions expose these directly instead of numeric code pairs.
    if bitrate is None:
        bitrate = _slsk_pick_int(shared_item, "bitrate", "bit_rate", "bitRate", "kbps", "bps")
    if duration is None:
        duration = _slsk_pick_int(shared_item, "duration", "length", "time", "seconds", "secs")
    if vbr is None:
        vbr = _slsk_pick_int(shared_item, "vbr", "is_vbr", "variable_bitrate", "variableBitrate")
    if sample_rate is None:
        sample_rate = _slsk_pick_int(shared_item, "sample_rate", "samplerate", "sampleRate", "rate", "frequency", "hz")
    if bit_depth is None:
        bit_depth = _slsk_pick_int(shared_item, "bit_depth", "bitdepth", "bitDepth", "depth", "bits")

    # Normalize and sanity check
    def sane_int(x, lo, hi):
        try:
            xi = int(x)
        except Exception:
            return None
        if xi < lo or xi > hi:
            return None
        return xi

    # bitrate is usually kbps, but some implementations may provide bps
    bitrate = sane_int(bitrate, 1, 20000000)
    if bitrate is not None and bitrate > 20000:
        try:
            bitrate = int(round(bitrate / 1000.0))
        except Exception:
            pass
    bitrate = sane_int(bitrate, 1, 20000)  # kbps

    duration = sane_int(duration, 0, 60 * 60 * 24 * 7)  # seconds

    # sample rate is typically Hz (44100), but occasionally kHz (44)
    sample_rate = sane_int(sample_rate, 1, 768000)
    if sample_rate is not None and sample_rate < 1000:
        if 8 <= sample_rate <= 768:
            sample_rate = sample_rate * 1000
    sample_rate = sane_int(sample_rate, 1000, 768000)  # Hz

    bit_depth = sane_int(bit_depth, 1, 128)
    vbr = sane_int(vbr, 0, 1)

    name_part = remote_path.replace("\\", "/").split("/")[-1]
    ext = os.path.splitext(name_part)[1].lower().lstrip(".")
    ext = ext or ""

    kind = "file"
    try:
        if ("." + ext) in AUDIO_EXTS:
            kind = "audio"
        elif ("." + ext) in VIDEO_EXTS:
            kind = "video"
    except Exception:
        kind = "file"

    # Fallback: infer common lossless attributes from name when missing
    if kind == "audio" and (bit_depth is None or sample_rate is None):
        bd2, sr2 = _slsk_guess_lossless_depth_and_rate_from_name(name_part)
        if bit_depth is None:
            bit_depth = bd2
        if sample_rate is None:
            sample_rate = sr2

    # Codec is often just the extension for Soulseek shares
    codec = ext.upper() if ext else ""

    return {
        "ext": ext,
        "kind": kind,
        "bitrate": bitrate,
        "bit_depth": bit_depth,
        "sample_rate": sample_rate,
        "duration": duration,
        "vbr": vbr,
        "codec": codec,
    }


def _slsk_guess_kind_ext_attrs(name: str, shared_item: Any) -> Tuple[str, str, Optional[int], Optional[int], Optional[int], Optional[int], Optional[int], str]:
    """Return (kind, ext, bitrate_kbps, bit_depth, sample_rate_hz, duration_sec, vbr_flag, codec)."""
    rp = ""
    try:
        rp = str(_slsk_pick(shared_item, "remote_path", "path", "filename", "file", "name") or "")
    except Exception:
        rp = ""
    if not rp:
        rp = str(name or "")
    size = 0
    try:
        size = int(_slsk_pick(shared_item, "size", "filesize", "file_size", "bytes", "length") or 0)
    except Exception:
        size = 0

    try:
        m = _slsk_extract_media_attrs(shared_item, rp, size)
    except Exception:
        # Fallback: minimal inference from the filename only
        base = (name or "").replace("\\", "/").split("/")[-1]
        ext = os.path.splitext(base)[1].lower().lstrip(".")
        kind = "file"
        try:
            if ("." + ext) in AUDIO_EXTS:
                kind = "audio"
            elif ("." + ext) in VIDEO_EXTS:
                kind = "video"
        except Exception:
            kind = "file"
        codec = ext.upper() if ext else ""
        return kind, ext, None, None, None, None, None, codec

    kind = str(m.get("kind") or "file")
    ext = str(m.get("ext") or "")
    br = m.get("bitrate", None)
    bd = m.get("bit_depth", None)
    sr = m.get("sample_rate", None)
    dur = m.get("duration", None)
    vbr = m.get("vbr", None)
    codec = str(m.get("codec") or "")
    return kind, ext, br, bd, sr, dur, vbr, codec


class SoulseekService:
    def __init__(
        self,
        username: str,
        password: str,
        download_dir: str,
        listening_port: int,
        obfuscated_port: int,
        search_timeout_sec: int = 8,
        search_max_results: int = 60,
    ):
        self.username = (username or "").strip()
        self.password = (password or "").strip()
        self.download_dir = os.path.abspath(download_dir)
        self.listening_port = int(listening_port)
        self.obfuscated_port = int(obfuscated_port)
        self.search_timeout_sec = max(2, int(search_timeout_sec))
        self.search_max_results = max(10, int(search_max_results))

        self._thread = None
        self._loop = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._client = None
        self._start_error = None
        self._start_warning = ""
        self._startup_status = {
            "username_set": bool(self.username),
            "download_dir": self.download_dir,
            "listening_port": self.listening_port,
            "obfuscated_port": self.obfuscated_port,
            "upnp_enabled": False,
            "peer_obfuscate": False,
            "client_start_attempted": False,
            "client_start_ok": False,
            "login_attempted": False,
            "login_ok": False,
            "ready": False,
            "error": "",
            "warning": "",
        }

        self.incoming_dir = soulseek_incoming_dir()
        os.makedirs(self.incoming_dir, exist_ok=True)

        self._thread = threading.Thread(target=self._thread_main, name="SoulseekLoop", daemon=True)
        self._thread.start()

        # Wait briefly for startup to either succeed or fail
        self._ready.wait(timeout=15)

    def is_ready(self) -> bool:
        return bool(self._ready.is_set() and self._client is not None and self._start_error is None)

    def start_error(self) -> Optional[str]:
        return self._start_error

    def startup_status(self) -> Dict[str, Any]:
        status = dict(self._startup_status)
        status["ready"] = self.is_ready()
        status["error"] = str(self._start_error or "")
        status["warning"] = str(self._start_warning or status.get("warning") or "")
        return status

    def shutdown(self) -> None:
        self._stop.set()
        loop = self._loop
        client = self._client

        async def _stop_client():
            for name in ("stop", "close", "disconnect"):
                fn = getattr(client, name, None)
                if not fn:
                    continue
                try:
                    result = fn()
                    if hasattr(result, "__await__"):
                        await result
                    break
                except Exception:
                    continue

        if loop:
            try:
                if client:
                    fut = asyncio.run_coroutine_threadsafe(_stop_client(), loop)
                    try:
                        fut.result(timeout=5)
                    except Exception:
                        pass
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
        except Exception:
            pass

    def _thread_main(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.create_task(self._async_start())
            loop.run_forever()
        except Exception as e:
            self._start_error = str(e)
            try:
                self._startup_status["error"] = self._start_error
                self._startup_status["ready"] = False
            except Exception:
                pass
        finally:
            self._ready.set()

    def _is_non_obfuscated_listen_error(self, exc: Exception) -> bool:
        text = str(exc or "").lower().replace("_", "-")
        return "non-obfuscated" in text and "listening port" in text

    async def _stop_client_obj(self, client: Any) -> None:
        if not client:
            return
        for name in ("stop", "close", "disconnect"):
            fn = getattr(client, name, None)
            if not fn:
                continue
            try:
                result = fn()
                if hasattr(result, "__await__"):
                    await result
                break
            except Exception:
                continue

    async def _async_start(self):
        from aioslsk.client import SoulSeekClient
        from aioslsk.network.network import ListeningConnectionErrorMode
        from aioslsk.settings import Settings, CredentialsSettings

        def _build_settings(listening_port: int, obfuscated_port: int, fallback: bool = False):
            settings = Settings(credentials=CredentialsSettings(username=self.username, password=self.password))
            # Reliability relevant options
            try:
                settings.network.listening.port = int(listening_port)
            except Exception:
                pass
            try:
                settings.network.listening.obfuscated_port = int(obfuscated_port)
            except Exception:
                pass
            try:
                if fallback or int(listening_port or 0) <= 0:
                    settings.network.listening.error_mode = ListeningConnectionErrorMode.ANY
                else:
                    settings.network.listening.error_mode = ListeningConnectionErrorMode.CLEAR
            except Exception:
                pass
            try:
                settings.network.upnp.enabled = False
            except Exception:
                pass
            try:
                settings.network.peer.obfuscate = False
            except Exception:
                pass
            try:
                settings.shares.download = self.incoming_dir
            except Exception:
                pass
            try:
                settings.server.reconnect.auto = True
            except Exception:
                pass
            return settings

        async def _attempt_start(settings, warning: str = ""):
            self._startup_status.update({
                "listening_port": int(getattr(settings.network.listening, "port", 0) or 0),
                "obfuscated_port": int(getattr(settings.network.listening, "obfuscated_port", 0) or 0),
                "upnp_enabled": bool(getattr(settings.network.upnp, "enabled", False)),
                "peer_obfuscate": bool(getattr(settings.network.peer, "obfuscate", False)),
                "client_start_attempted": True,
                "client_start_ok": False,
                "login_attempted": False,
                "login_ok": False,
                "ready": False,
                "warning": warning,
            })

            client = SoulSeekClient(settings)
            self._client = client

            await client.start()
            self._startup_status["client_start_ok"] = True
            self._startup_status["login_attempted"] = True
            await client.login()
            self._startup_status["login_ok"] = True

            try:
                ports = client.network.get_listening_ports()
                self._startup_status["listening_port"] = int(ports[0] or 0)
                self._startup_status["obfuscated_port"] = int(ports[1] or 0)
            except Exception:
                pass

            # Background poller to integrate transfer progress into DebriPod tasks
            asyncio.create_task(self._poll_transfers_loop())

            self._start_error = None
            self._start_warning = warning
            self._startup_status["ready"] = True
            self._ready.set()

        try:
            try:
                await _attempt_start(_build_settings(self.listening_port, self.obfuscated_port))
                return
            except Exception as first_exc:
                await self._stop_client_obj(self._client)
                self._client = None
                if not self._is_non_obfuscated_listen_error(first_exc):
                    raise
                warning = f"Configured listening port failed; Soulseek started with fallback listener settings. Original error: {first_exc}"
                try:
                    await _attempt_start(_build_settings(0, self.obfuscated_port, fallback=True), warning=warning)
                    return
                except Exception:
                    await self._stop_client_obj(self._client)
                    self._client = None
                await _attempt_start(_build_settings(0, 0, fallback=True), warning=warning)
        except Exception as e:
            self._start_error = str(e)
            self._startup_status["error"] = self._start_error
            self._startup_status["ready"] = False
            self._ready.set()

    def submit(self, coro, timeout: int = 30):
        if not self._loop:
            raise RuntimeError("Soulseek loop not initialized")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def submit_nowait(self, coro):
        if not self._loop:
            raise RuntimeError("Soulseek loop not initialized")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)


    def start_search_session(self, session_id: str, query: str) -> None:
        q = (query or "").strip()
        if not q:
            _slsk_session_mark_done(session_id, error="Missing query")
            return
        try:
            self.submit_nowait(self._search_stream_coro(q, session_id))
        except Exception as e:
            _slsk_session_mark_done(session_id, error=str(e))

    def search(self, query: str) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        return self.submit(self._search_coro(q), timeout=self.search_timeout_sec + 10)

    async def _search_coro(self, query: str) -> List[Dict[str, Any]]:
        if not self._client:
            raise RuntimeError("Soulseek client not started")
        # aioslsk search results can arrive asynchronously; wait a short window
        searcher = None
        try:
            searches = getattr(self._client, "searches", None)
            if searches is not None and hasattr(searches, "search"):
                searcher = searches.search
        except Exception:
            searcher = None
        if searcher is None:
            try:
                sm = getattr(self._client, "search_manager", None)
                if sm is not None and hasattr(sm, "search"):
                    searcher = sm.search
            except Exception:
                searcher = None
        if searcher is None:
            raise RuntimeError("Soulseek client does not expose a search manager (expected client.searches.search)")
        req = await searcher(query)
        await asyncio.sleep(min(1.0, max(0.2, self.search_timeout_sec / 10)))
        # Wait up to timeout and keep the largest snapshot (Soulseek results can trickle in)
        end = time.time() + float(self.search_timeout_sec)
        best: List[Any] = []
        while time.time() < end:
            try:
                cur = list(getattr(req, "results", []) or [])
            except Exception:
                cur = []
            if len(cur) > len(best):
                best = cur
            await asyncio.sleep(0.25)
        results = best
# Flatten into {user, remote_path, size} items, grouped by directory later
        items: List[Dict[str, Any]] = []
        for r in results[: self.search_max_results]:
            user = getattr(r, "username", "") or getattr(r, "user", "")
            speed = _slsk_extract_result_speed(r)
            try:
                shared = list(getattr(r, "shared_items", []) or [])
            except Exception:
                shared = []
            for f in shared:
                rp = getattr(f, "filename", None)
                if rp is None:
                    rp = getattr(f, "remote_path", "")
                rp = str(rp or "")
                if not rp:
                    continue
                size = getattr(f, "filesize", None)
                if size is None:
                    size = getattr(f, "size", 0)
                try:
                    size = int(size or 0)
                except Exception:
                    size = 0
                meta = _slsk_extract_media_attrs(f, rp, size)

                ext = meta.get("ext") or ""

                kind = meta.get("kind") or "file"

                bitrate = meta.get("bitrate")

                bit_depth = meta.get("bit_depth")

                sample_rate = meta.get("sample_rate")

                duration = meta.get("duration")

                vbr = meta.get("vbr")

                codec = meta.get("codec") or ""

                items.append({
                    "user": str(user or ""),
                    "speed": int(speed) if speed else 0,
                    "remote_path": rp,
                    "size": size,
                    "ext": ext,
                    "kind": kind,
                    "bitrate": bitrate,
                    "bit_depth": bit_depth,
                    "sample_rate": sample_rate,
                    "duration": duration,
                    "vbr": vbr,
                    "codec": codec,
                })
        return items

    async def _search_stream_coro(self, query: str, session_id: str) -> None:
        if not self._client:
            _slsk_session_mark_done(session_id, error="Soulseek client not started")
            return

        searcher = None
        try:
            searches = getattr(self._client, "searches", None)
            if searches is not None and hasattr(searches, "search"):
                searcher = searches.search
        except Exception:
            searcher = None
        if searcher is None:
            try:
                sm = getattr(self._client, "search_manager", None)
                if sm is not None and hasattr(sm, "search"):
                    searcher = sm.search
            except Exception:
                searcher = None
        if searcher is None:
            _slsk_session_mark_done(session_id, error="Soulseek client does not expose a search manager")
            return

        try:
            req = await searcher(query)
        except Exception as e:
            _slsk_session_mark_done(session_id, error=str(e))
            return

        idle_stop = float(SOULSEEK_SEARCH_IDLE_STOP_SEC or 2.5)
        hard_max = float(SOULSEEK_SEARCH_HARD_MAX_SEC or 60)
        start_t = time.time()
        last_growth = start_t
        seen: set = set()

        # Small initial wait to let first packets arrive
        try:
            await asyncio.sleep(0.15)
        except Exception:
            pass

        while True:
            now = time.time()
            if (now - start_t) > hard_max:
                break

            new_items: List[Dict[str, Any]] = []

            try:
                cur = list(getattr(req, "results", []) or [])
            except Exception:
                cur = []

            for r in cur:
                user = getattr(r, "username", "") or getattr(r, "user", "")
                speed = _slsk_extract_result_speed(r)
                try:
                    shared = list(getattr(r, "shared_items", []) or [])
                except Exception:
                    shared = []
                if not user or not shared:
                    continue

                for f in shared:
                    rp = getattr(f, "filename", None)
                    if rp is None:
                        rp = getattr(f, "remote_path", "")
                    rp = str(rp or "")
                    if not rp:
                        continue
                    key = str(user) + "|" + rp
                    if key in seen:
                        continue
                    seen.add(key)

                    size = getattr(f, "filesize", None)
                    if size is None:
                        size = getattr(f, "size", 0)
                    try:
                        size = int(size or 0)
                    except Exception:
                        size = 0

                    meta = _slsk_extract_media_attrs(f, rp, size)
                    ext = meta.get("ext") or ""
                    kind = meta.get("kind") or "file"
                    bitrate = meta.get("bitrate")
                    bit_depth = meta.get("bit_depth")
                    sample_rate = meta.get("sample_rate")
                    duration = meta.get("duration")
                    vbr = meta.get("vbr")
                    codec = meta.get("codec") or ""

                    new_items.append(
                        {
                            "user": str(user or ""),
                            "speed": int(speed) if speed else 0,
                            "remote_path": rp,
                            "size": size,
                            "ext": ext,
                            "kind": kind,
                            "bitrate": bitrate,
                            "bit_depth": bit_depth,
                            "sample_rate": sample_rate,
                            "duration": duration,
                            "vbr": vbr,
                            "codec": codec,
                        }
                    )

                    if len(seen) >= int(self.search_max_results):
                        break
                if len(seen) >= int(self.search_max_results):
                    break

            if new_items:
                last_growth = time.time()
                _slsk_session_add_items(session_id, new_items)

            if len(seen) >= int(self.search_max_results):
                break

            if (time.time() - last_growth) >= idle_stop:
                break

            try:
                await asyncio.sleep(0.25)
            except Exception:
                break

        _slsk_session_mark_done(session_id, error="")


    def browse_user(self, username: str) -> List[Dict[str, Any]]:
        user = (username or "").strip()
        if not user:
            return []
        timeout = max(20, int(self.search_timeout_sec) + 20)
        return self.submit(self._browse_user_coro(user), timeout=timeout)

    async def _browse_user_coro(self, username: str) -> List[Dict[str, Any]]:
        if not self._client:
            raise RuntimeError("Soulseek client not started")

        response = None
        last_error = ""

        async def _try_await(fn, *args, **kwargs):
            val = fn(*args, **kwargs)
            if asyncio.iscoroutine(val):
                return await val
            return val

        async def _run_command(cmd_obj: Any):
            exec_methods = []
            for meth_name in ("execute",):
                meth = getattr(self._client, meth_name, None)
                if callable(meth):
                    exec_methods.append(meth)
            call_dunder = getattr(self._client, "__call__", None)
            if callable(call_dunder):
                exec_methods.append(call_dunder)
            for meth in exec_methods:
                try:
                    out = meth(cmd_obj, response=True)
                    if asyncio.iscoroutine(out):
                        out = await out
                    if out is not None:
                        return out
                except TypeError:
                    try:
                        out = meth(cmd_obj)
                        if asyncio.iscoroutine(out):
                            out = await out
                        if out is not None:
                            return out
                    except Exception as e:
                        nonlocal last_error
                        last_error = str(e)
                except Exception as e:
                    last_error = str(e)
            return None

        # First try command objects from aioslsk.commands. The exact command names
        # differ between releases, so discover them dynamically instead of assuming
        # a single BrowseUserCommand symbol exists.
        try:
            import aioslsk.commands as slsk_commands  # type: ignore
            command_names = []
            for name in dir(slsk_commands):
                lname = str(name).lower()
                if "command" not in lname:
                    continue
                if ("share" in lname) or ("browse" in lname) or ("directory" in lname and "peer" in lname):
                    command_names.append(name)
            preferred = []
            deferred = []
            for name in command_names:
                lname = str(name).lower()
                if ("share" in lname or "browse" in lname) and "directory" not in lname:
                    preferred.append(name)
                else:
                    deferred.append(name)
            for name in preferred + deferred:
                cls = getattr(slsk_commands, name, None)
                if not callable(cls):
                    continue
                variants = [
                    ((username,), {}),
                    ((), {"username": username}),
                    ((username, None), {}),
                    ((username, ""), {}),
                    ((), {"user": username}),
                ]
                for args, kwargs in variants:
                    try:
                        cmd_obj = cls(*args, **kwargs)
                    except TypeError:
                        continue
                    except Exception as e:
                        last_error = str(e)
                        continue
                    try:
                        response = await _run_command(cmd_obj)
                        if response is not None:
                            break
                    except Exception as e:
                        last_error = str(e)
                if response is not None:
                    break
        except Exception:
            pass

        if response is None:
            candidates = []
            for owner_name in dir(self._client):
                if owner_name.startswith("_"):
                    continue
                owner = getattr(self._client, owner_name, None)
                if owner is None:
                    continue
                for meth_name in dir(owner):
                    if meth_name.startswith("_"):
                        continue
                    lname = str(meth_name).lower()
                    if not ("browse" in lname or "share" in lname or ("directory" in lname and "get" in lname)):
                        continue
                    meth = getattr(owner, meth_name, None)
                    if callable(meth):
                        candidates.append(meth)
            for meth in candidates:
                try:
                    response = await _try_await(meth, username)
                    if response is not None:
                        break
                except TypeError:
                    try:
                        response = await _try_await(meth, username=username)
                        if response is not None:
                            break
                    except TypeError:
                        try:
                            response = await _try_await(meth, user=username)
                            if response is not None:
                                break
                        except Exception as e:
                            last_error = str(e)
                    except Exception as e:
                        last_error = str(e)
                except Exception as e:
                    last_error = str(e)

        if response is None:
            raise RuntimeError(last_error or "Could not browse user shares with current aioslsk API")

        try:
            await asyncio.sleep(1.0)
        except Exception:
            pass

        items = _slsk_collect_browse_items(response, user=username)
        if not items:
            for attr_name in ("results", "items", "shared_items", "directories", "files", "value", "payload"):
                try:
                    extra = getattr(response, attr_name, None)
                except Exception:
                    extra = None
                if extra:
                    items = _slsk_collect_browse_items(extra, user=username)
                    if items:
                        break
                if isinstance(response, dict):
                    extra = response.get(attr_name)
                    if extra:
                        items = _slsk_collect_browse_items(extra, user=username)
                        if items:
                            break

        if not items:
            raise RuntimeError("Browse returned no readable shared files")

        dedup: Dict[str, Dict[str, Any]] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            rp = _slsk_norm_remote_path(str(it.get("remote_path") or ""))
            if not rp:
                continue
            it["user"] = username
            it["remote_path"] = rp
            it["directory"] = _slsk_norm_remote_path(str(it.get("directory") or ""))
            dedup[rp] = it
        out = list(dedup.values())
        out.sort(key=lambda x: str(x.get("remote_path") or "").lower())
        return out

    def enqueue_downloads(self, task_id: str, username: str, remote_paths: List[str]) -> None:
        self.submit(self._enqueue_coro(task_id, username, remote_paths), timeout=30)

    async def _enqueue_coro(self, task_id: str, username: str, remote_paths: List[str]) -> None:
        if not self._client:
            raise RuntimeError("Soulseek client not started")
        from aioslsk.transfer.model import TransferDirection

        user = (username or "").strip()
        paths = [p for p in (remote_paths or []) if (p or "").strip()]
        if not user or not paths:
            return

        async with SOULSEEK_ENQUEUE_SEMAPHORE:
            # Create transfers (idempotent: aioslsk returns existing transfer if already present)
            for rp in paths:
                if get_task(task_id) and get_task(task_id).cancel_event.is_set():
                    break
                tm = getattr(self._client, "transfers", None)
                if tm is not None and hasattr(tm, "download"):
                    await tm.download(user, rp)
                else:
                    tm_old = getattr(self._client, "transfer_manager", None)
                    if tm_old is None or not hasattr(tm_old, "download"):
                        raise RuntimeError("Soulseek client does not expose transfers manager")
                    await tm_old.download(user, rp, paused=False)

        set_task(task_id, state="downloading", message="Soulseek downloads queued")

    def abort_task(self, task_id: str) -> None:
        try:
            self.submit(self._abort_task_coro(task_id), timeout=20)
        except Exception:
            pass

    async def _abort_task_coro(self, task_id: str) -> None:
        if not self._client:
            return
        from aioslsk.transfer.model import TransferDirection
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        try:
            files = list(t.slsk_files or [])
        except Exception:
            files = []
        for f in files:
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = f.get("remote_path") or ""
            rp = str(rp)
            if not user or not rp:
                continue
            tr = None
            try:
                tm = getattr(self._client, "transfers", None)
                if tm is not None and hasattr(tm, "transfers"):
                    for _tr in list(getattr(tm, "transfers", []) or []):
                        try:
                            tr_rp = getattr(_tr, "filename", "") or getattr(_tr, "remote_path", "") or getattr(_tr, "path", "")
                            if getattr(_tr, "username", "") == user and _slsk_norm_remote_path(str(tr_rp)).lower() == _slsk_norm_remote_path(rp).lower():
                                d = getattr(_tr, "direction", None)
                                if d is None or getattr(d, "name", str(d)).upper() == "DOWNLOAD":
                                    tr = _tr
                                    break
                        except Exception:
                            continue
                if tr is None:
                    tm_old = getattr(self._client, "transfer_manager", None)
                    if tm_old is not None and hasattr(tm_old, "find_transfer"):
                        tr = tm_old.find_transfer(user, rp, TransferDirection.DOWNLOAD)
            except Exception:
                tr = None
            if tr is not None:
                try:
                    tm = getattr(self._client, "transfers", None)
                    if tm is not None and hasattr(tm, "abort"):
                        await tm.abort(tr)
                    else:
                        tm_old = getattr(self._client, "transfer_manager", None)
                        if tm_old is not None and hasattr(tm_old, "abort"):
                            await tm_old.abort(tr)
                except Exception:
                    pass


    def pause_task(self, task_id: str) -> None:
        try:
            self.submit(self._pause_task_coro(task_id), timeout=20)
        except Exception:
            pass

    def resume_task(self, task_id: str) -> None:
        try:
            self.submit(self._resume_task_coro(task_id), timeout=20)
        except Exception:
            pass

    def pause_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._pause_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    def resume_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._resume_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    def cancel_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._cancel_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    def retry_file(self, task_id: str, file_id: str) -> None:
        try:
            self.submit(self._retry_file_coro(task_id, file_id), timeout=20)
        except Exception:
            pass

    async def _find_transfer(self, user: str, rp_norm: str):
        if not self._client:
            return None
        try:
            from aioslsk.transfer.model import TransferDirection
        except Exception:
            TransferDirection = None  # type: ignore

        tr = None
        try:
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "transfers"):
                for _tr in list(getattr(tm, "transfers", []) or []):
                    try:
                        if getattr(_tr, "username", "") != user:
                            continue
                        tr_rp = getattr(_tr, "filename", "") or getattr(_tr, "remote_path", "") or getattr(_tr, "path", "")
                        if _slsk_norm_remote_path(str(tr_rp)).lower() != _slsk_norm_remote_path(str(rp_norm)).lower():
                            continue
                        d = getattr(_tr, "direction", None)
                        if d is not None and getattr(d, "name", str(d)).upper() != "DOWNLOAD":
                            continue
                        tr = _tr
                        break
                    except Exception:
                        continue
            if tr is None:
                tm_old = getattr(self._client, "transfer_manager", None)
                if tm_old is not None and hasattr(tm_old, "find_transfer") and TransferDirection is not None:
                    tr = tm_old.find_transfer(user, rp_norm, TransferDirection.DOWNLOAD)
        except Exception:
            tr = None
        return tr

    async def _pause_transfer(self, tr) -> bool:
        if not self._client or tr is None:
            return False
        try:
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "pause"):
                res = tm.pause(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            tm_old = getattr(self._client, "transfer_manager", None)
            if tm_old is not None and hasattr(tm_old, "pause"):
                res = tm_old.pause(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            if hasattr(tr, "paused"):
                setattr(tr, "paused", True)
                return True
        except Exception:
            pass
        return False

    async def _resume_transfer(self, tr) -> bool:
        if not self._client or tr is None:
            return False
        try:
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "resume"):
                res = tm.resume(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            tm_old = getattr(self._client, "transfer_manager", None)
            if tm_old is not None and hasattr(tm_old, "resume"):
                res = tm_old.resume(tr)
                if asyncio.iscoroutine(res):
                    await res
                return True
        except Exception:
            pass
        try:
            if hasattr(tr, "paused"):
                setattr(tr, "paused", False)
                return True
        except Exception:
            pass
        return False

    async def _pause_task_coro(self, task_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        files = list(t.slsk_files or [])
        for f in files:
            try:
                fid = str(f.get("file_id") or "")
                if fid:
                    _set_file_control(task_id, fid, paused=True)
            except Exception:
                pass
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                continue
            tr = await self._find_transfer(user, rp)
            await self._pause_transfer(tr)

    async def _resume_task_coro(self, task_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        files = list(t.slsk_files or [])
        for f in files:
            try:
                fid = str(f.get("file_id") or "")
                if fid:
                    _set_file_control(task_id, fid, paused=False)
            except Exception:
                pass
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                continue
            tr = await self._find_transfer(user, rp)
            await self._resume_transfer(tr)

    async def _pause_file_coro(self, task_id: str, file_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, paused=True)
            tr = await self._find_transfer(user, rp)
            await self._pause_transfer(tr)
            return

    async def _resume_file_coro(self, task_id: str, file_id: str) -> None:
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = _slsk_norm_remote_path(str(f.get("remote_path") or ""))
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, paused=False)
            tr = await self._find_transfer(user, rp)
            await self._resume_transfer(tr)
            return

    async def _cancel_file_coro(self, task_id: str, file_id: str) -> None:
        if not self._client:
            return
        from aioslsk.transfer.model import TransferDirection
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = str(f.get("remote_path") or "")
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, canceled=True)
            # Abort the specific transfer
            try:
                tm = getattr(self._client, "transfers", None)
                if tm is not None and hasattr(tm, "abort"):
                    tr = await self._find_transfer(user, _slsk_norm_remote_path(rp))
                    if tr is not None:
                        res = tm.abort(tr)
                        if asyncio.iscoroutine(res):
                            await res
                        return
            except Exception:
                pass
            try:
                tm_old = getattr(self._client, "transfer_manager", None)
                if tm_old is not None and hasattr(tm_old, "find_transfer") and hasattr(tm_old, "abort"):
                    tr = tm_old.find_transfer(user, rp, TransferDirection.DOWNLOAD)
                    if tr is not None:
                        res = tm_old.abort(tr)
                        if asyncio.iscoroutine(res):
                            await res
                        return
            except Exception:
                pass
            return

    async def _retry_file_coro(self, task_id: str, file_id: str) -> None:
        if not self._client:
            return
        t = get_task(task_id)
        if not t or (t.source or "").lower() != "soulseek":
            return
        for f in list(t.slsk_files or []):
            if str(f.get("file_id") or "") != str(file_id):
                continue
            user = (f.get("user") or t.slsk_user or "").strip()
            rp = str(f.get("remote_path") or "")
            if not user or not rp:
                return
            _set_file_control(task_id, file_id, paused=False, canceled=False)
            # Re-create transfer (idempotent)
            tm = getattr(self._client, "transfers", None)
            if tm is not None and hasattr(tm, "download"):
                res = tm.download(user, rp)
                if asyncio.iscoroutine(res):
                    await res
            else:
                tm_old = getattr(self._client, "transfer_manager", None)
                if tm_old is None or not hasattr(tm_old, "download"):
                    return
                res = tm_old.download(user, rp, paused=False)
                if asyncio.iscoroutine(res):
                    await res
            return


    async def _poll_transfers_loop(self):
        # No event wiring needed; poll transfer state and file sizes for progress
        try:
            from aioslsk.transfer.model import TransferDirection
        except Exception:
            return

        last_overall: Dict[str, Tuple[float, int]] = {}
        while True:
            await asyncio.sleep(1.0)
            if not self._client:
                continue

            # Snapshot Soulseek tasks
            with TASKS_LOCK:
                slsk_tasks = [t for t in TASKS.values() if (t.source or "").lower() == "soulseek" and t.state not in {"done", "error", "canceled"}]

            for t in slsk_tasks:
                if t.cancel_event.is_set():
                    # keep canceling until transfers are aborted
                    set_task(t.id, state="canceling", message="Canceling Soulseek downloads")
                files = []
                try:
                    files = list(t.slsk_files or [])
                except Exception:
                    files = []

                any_active = False
                any_failed = False
                all_complete = True
                overall_done = 0
                overall_total = 0
                current_file = ""
                current_done = 0
                current_total = None

                now = time.time()

                for f in files:
                    user = (f.get("user") or t.slsk_user or "").strip()
                    rp = str(f.get("remote_path") or "")
                    rp_norm = _slsk_norm_remote_path(rp)
                    total = int(f.get("total") or f.get("size") or 0)
                    final_lp = f.get("local_path")
                    if not final_lp:
                        rel = _slsk_relative_under_directory(t.slsk_directory, rp_norm)
                        rel_parts = [x for x in _slsk_norm_remote_path(rel).split("\\") if x]
                        base_dir = _slsk_task_download_dir(t.slsk_directory)
                        final_lp = os.path.join(base_dir, *rel_parts) if rel_parts else base_dir
                    incoming_lp = f.get("incoming_path") or _slsk_expected_incoming_path(rp)
                    f["local_path"] = final_lp
                    f["incoming_path"] = incoming_lp
                    f["total"] = int(total) if total else 0

                    # done bytes from disk if possible (aioslsk may use temp extensions while downloading)
                    done = 0
                    lp_progress = ""
                    for cand in (incoming_lp, final_lp):
                        if not cand:
                            continue
                        p = _slsk_resolve_local_progress_path(cand)
                        try:
                            if p and os.path.exists(p):
                                lp_progress = p
                                break
                        except Exception:
                            continue
                    try:
                        if os.path.exists(lp_progress):
                            done = int(os.path.getsize(lp_progress))
                    except Exception:
                        done = int(f.get("done") or 0)

                    # estimate speed
                    prev_sz = float(f.get("_prev_sz") or 0)
                    prev_t = float(f.get("_prev_t") or 0)
                    speed = 0.0
                    if prev_t > 0 and now > prev_t:
                        speed = max(0.0, (done - prev_sz) / max(0.001, (now - prev_t)))
                    f["_prev_sz"] = float(done)
                    f["_prev_t"] = float(now)
                    f["speed"] = float(speed)
                    f["done"] = int(done)

                    # transfer state from manager if available
                    tr_state = ""
                    tr = None
                    try:
                        tm = getattr(self._client, "transfers", None)
                        if tm is not None and hasattr(tm, "transfers"):
                            for _tr in list(getattr(tm, "transfers", []) or []):
                                try:
                                    if getattr(_tr, "username", "") != user:
                                        continue
                                    tr_rp = getattr(_tr, "filename", "") or getattr(_tr, "remote_path", "") or getattr(_tr, "path", "")
                                    if _slsk_norm_remote_path(str(tr_rp)).lower() != rp_norm.lower():
                                        continue
                                    d = getattr(_tr, "direction", None)
                                    if d is not None and getattr(d, "name", str(d)).upper() != "DOWNLOAD":
                                        continue
                                    tr = _tr
                                    break
                                except Exception:
                                    continue
                        if tr is None:
                            tm_old = getattr(self._client, "transfer_manager", None)
                            if tm_old is not None and hasattr(tm_old, "find_transfer"):
                                tr = tm_old.find_transfer(user, rp, TransferDirection.DOWNLOAD)
                    except Exception:
                        tr = None
                    if tr is not None:
                        try:
                            tr_state = getattr(getattr(tr, "state", ""), "name", str(getattr(tr, "state", "")))
                        except Exception:
                            tr_state = ""
                    # Prefer transfer-provided numbers when available (filesize/bytes received/speed)
                    tr_done, tr_total, tr_speed, tr_state2 = _slsk_extract_transfer_progress(tr)
                    if tr_total > 0:
                        if total <= 0 or tr_total > total:
                            total = int(tr_total)
                    if tr_done > 0 and tr_done > done:
                        done = int(tr_done)
                    if tr_speed > 0:
                        speed = float(tr_speed)
                    if tr_state2:
                        tr_state = tr_state2
                    f["total"] = int(total) if total else 0
                    f["done"] = int(done)
                    f["speed"] = float(speed)

                    # Apply per-file controls and expose raw transfer status/error
                    fid = str(f.get("file_id") or "")
                    ctl = _get_file_control(t.id, fid) if fid else {}
                    paused_ctl = bool(ctl.get("paused"))
                    canceled_ctl = bool(ctl.get("canceled"))
                    paused_tr = _slsk_transfer_is_paused(tr)
                    err = _slsk_extract_transfer_error(tr)
                    if err:
                        f["error"] = str(err)
                    if paused_ctl or paused_tr:
                        f["paused"] = True
                    if canceled_ctl:
                        f["canceled"] = True

                    state_raw = (tr_state or f.get("state") or "")
                    state_tok = _slsk_clean_state_token(state_raw)
                    f["state_raw"] = state_tok or f.get("state_raw") or ""
                    state = _slsk_normalize_state(state_tok, bool(f.get("paused")), bool(f.get("canceled")), int(done), int(total), bool(f.get("error")))
                    f["state"] = state


                    # If a file completed but total is unknown, lock total to done so overall can reach 100
                    if state == "complete" and (total <= 0) and done > 0:
                        total = int(done)
                        f["total"] = int(total)

                    # When a file completes, move it from the incoming folder into the task folder
                    if state == "complete":
                        try:
                            src = _slsk_resolve_local_progress_path(incoming_lp)
                        except Exception:
                            src = incoming_lp
                        dst = final_lp
                        try:
                            if src and dst and os.path.abspath(src) != os.path.abspath(dst) and os.path.exists(src):
                                moved_to = _safe_move_file(src, dst)
                                final_lp = moved_to or dst
                                f["local_path"] = final_lp
                        except Exception:
                            pass

                    if state in {"failed", "incomplete"}:
                        any_failed = True
                    if state not in {"complete"}:
                        all_complete = False
                    if state in {"queued", "downloading", "requesting", "initializing", "connecting"}:
                        any_active = True
                        if not current_file:
                            current_file = rp_norm.split("\\")[-1] if rp_norm else ""
                            current_done = done
                            current_total = total if total > 0 else None

                    overall_done += done
                    overall_total += total

                # Write updates back
                set_task(t.id, slsk_files=files, overall_done=overall_done, overall_total=(overall_total if overall_total > 0 else None), current_file=current_file, current_done=current_done, current_total=current_total)

                if all_complete and files:
                    # mark done
                    saved = []
                    for f in files:
                        lp = f.get("local_path") or ""
                        if lp:
                            saved.append(lp)
                    set_task(t.id, state="done", message="Soulseek download complete", downloaded_files=saved, downloads_complete=True)
                else:
                    if t.cancel_event.is_set():
                        # If canceled, consider it canceled once nothing is active
                        if not any_active:
                            set_task(t.id, state="canceled", message="Canceled", downloads_complete=False)
                    else:
                        any_paused = any(bool(ff.get("paused")) for ff in files)
                        if t.pause_event.is_set() or bool(getattr(t, "paused", False)) or (any_paused and not any_active and not all_complete):
                            set_task(t.id, state="paused", message="Paused")
                        elif any_failed and not any_active:
                            set_task(t.id, state="error", message="Soulseek download finished with errors")
                        else:
                            set_task(t.id, state="downloading", message="Soulseek downloading")


def _slsk_extract_result_speed(r: Any) -> int:
    """
    Best-effort extraction of a user's advertised connection speed from aioslsk search result objects.
    Many Soulseek clients surface a speed value, but different library versions name it differently.
    Returns an integer speed in bytes/sec when possible, else 0.
    """
    if r is None:
        return 0

    # Common attribute names seen across Soulseek client implementations / wrappers
    cand_attrs = (
        "speed",
        "upload_speed",
        "connection_speed",
        "avg_speed",
        "download_speed",
        "ul_speed",
        "dl_speed",
        "bandwidth",
        "rate",
    )
    for a in cand_attrs:
        try:
            v = getattr(r, a, None)
        except Exception:
            v = None
        if v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if not math.isfinite(f) or f <= 0:
            continue
        # Heuristic: some APIs report KB/s; if it looks too small, treat as KB/s.
        if f < 1024 and f > 0:
            f = f * 1024.0
        try:
            return int(f)
        except Exception:
            continue

    # Sometimes the info is nested under a "user" object
    try:
        u = getattr(r, "user", None)
    except Exception:
        u = None
    if u is not None:
        for a in cand_attrs:
            try:
                v = getattr(u, a, None)
            except Exception:
                v = None
            if v is None:
                continue
            try:
                f = float(v)
            except Exception:
                continue
            if not math.isfinite(f) or f <= 0:
                continue
            if f < 1024 and f > 0:
                f = f * 1024.0
            try:
                return int(f)
            except Exception:
                continue

    return 0


