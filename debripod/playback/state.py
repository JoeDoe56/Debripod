from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from ..paths import cache_dir
from ..storage import playback as playback_repository
from ..storage.legacy_import import read_json as read_legacy_json, retire as retire_legacy

_search_stream_root_id_provider: Callable[[], str] = lambda: "__search_stream__"
_search_stream_get_or_restore_provider: Callable[[str], Optional[Dict[str, Any]]] = lambda _rel: None


def configure_playback_state(
    *,
    search_stream_root_id_provider: Callable[[], str],
    search_stream_get_or_restore_provider: Callable[[str], Optional[Dict[str, Any]]],
) -> None:
    global _search_stream_root_id_provider, _search_stream_get_or_restore_provider
    _search_stream_root_id_provider = search_stream_root_id_provider
    _search_stream_get_or_restore_provider = search_stream_get_or_restore_provider


def _search_stream_root_id() -> str:
    return str(_search_stream_root_id_provider() or "")


def _search_stream_get_or_restore(rel: str) -> Optional[Dict[str, Any]]:
    return _search_stream_get_or_restore_provider(rel)

# Playback state (server-side)
# =========================
# Stored in cache folder so it persists across restarts and is shared across devices.
# This keeps:
#   - now_playing (audio or video) with last known position and navigation context
#   - recently_played list (videos always resume, audio grouped into sessions)
def playback_state_path() -> str:
    return os.path.join(cache_dir(), "incoming", "playback_state.json")

def _default_playback_state() -> dict:
    return {
        "now": None,              # dict or None
        "recent": [],             # list[dict], newest first
        # session tracking is separate for audio and video so they never overwrite each other
        "audio_session": {
            "session_id": "",
            "last_activity_ts": 0.0,   # updated while playing
            "last_stop_ts": 0.0,       # updated on pause/stop/ended
        },
        "video_session": {
            "session_id": "",
            "last_activity_ts": 0.0,
            "last_stop_ts": 0.0,
        },
        "playback_session": {
            "now": None,
            "queue": [],
            "history": [],
            "queueIndex": -1,
            "nav": None,
            "sourceView": None,
            "updatedAt": 0,
            "revision": 0,
        },
        # Durable resume/completion data for every local video, keyed by
        # root_id + relative path. This is separate from Now Playing/recent.
        "media_progress": {},
        "version": 0,
        "ver": 3,
        "updated": 0.0,
    }

@dataclass(slots=True)
class PlaybackRuntime:
    """In-memory playback state for exactly one authenticated user."""

    user_id: str = ""
    state: dict = field(default_factory=_default_playback_state)
    lock: threading.RLock = field(default_factory=threading.RLock)
    search_stream_get_or_restore: Callable[[str], Optional[Dict[str, Any]]] | None = None


# Legacy aliases keep pre-runtime integrations working until they are
# migrated. New request paths use an explicit ``PlaybackRuntime``.
_LEGACY_PLAYBACK_RUNTIME = PlaybackRuntime()
PLAYBACK_STATE_LOCK = _LEGACY_PLAYBACK_RUNTIME.lock
PLAYBACK_STATE: dict = _LEGACY_PLAYBACK_RUNTIME.state


def _runtime_parts(runtime: PlaybackRuntime | None = None) -> tuple[dict, threading.RLock]:
    target = runtime or _LEGACY_PLAYBACK_RUNTIME
    return target.state, target.lock

def _normalized_playback_state(value: Any) -> dict:
    base = _default_playback_state()
    if not isinstance(value, dict) or not value:
        return base
    base.update(value)
    if not isinstance(base.get("recent"), list):
        base["recent"] = []
    if not isinstance(base.get("media_progress"), dict):
        base["media_progress"] = {}
    for name in ("audio_session", "video_session"):
        session = base.get(name)
        if not isinstance(session, dict):
            session = {}
        session.setdefault("session_id", "")
        session.setdefault("last_activity_ts", 0.0)
        session.setdefault("last_stop_ts", 0.0)
        base[name] = session
    session = base.get("playback_session")
    if not isinstance(session, dict):
        session = {}
    if not isinstance(session.get("queue"), list):
        session["queue"] = []
    if not isinstance(session.get("history"), list):
        session["history"] = []
    try:
        session["queueIndex"] = int(session.get("queueIndex") if session.get("queueIndex") is not None else -1)
    except Exception:
        session["queueIndex"] = -1
    try:
        session["revision"] = int(session.get("revision") or base.get("version") or 0)
    except Exception:
        session["revision"] = 0
    session.setdefault("now", None)
    session.setdefault("nav", None)
    session.setdefault("sourceView", None)
    session.setdefault("updatedAt", 0)
    base["playback_session"] = session
    try:
        base["version"] = int(base.get("version") or session.get("revision") or 0)
    except Exception:
        base["version"] = 0
    return base


def load_playback_runtime(user_id: str) -> PlaybackRuntime:
    runtime = PlaybackRuntime(user_id=str(user_id or "").strip())
    try:
        runtime.state = _normalized_playback_state(playback_repository.load(runtime.user_id))
    except Exception:
        runtime.state = _default_playback_state()
    return runtime


def load_playback_state() -> None:
    """Load the retired shared state only for legacy non-request integrations."""
    global PLAYBACK_STATE
    p = playback_state_path()
    try:
        js = playback_repository.load()
        legacy = False
        if not js and os.path.exists(p):
            js = read_legacy_json(p)
            legacy = True
        base = _normalized_playback_state(js)
        with PLAYBACK_STATE_LOCK:
            PLAYBACK_STATE.clear()
            PLAYBACK_STATE.update(base)
        if legacy:
            playback_repository.save(base)
            try:
                retire_legacy(p)
            except OSError:
                pass
    except Exception:
        with PLAYBACK_STATE_LOCK:
            PLAYBACK_STATE.clear()
            PLAYBACK_STATE.update(_default_playback_state())

def save_playback_state_best_effort(runtime: PlaybackRuntime | None = None) -> None:
    try:
        target = runtime or _LEGACY_PLAYBACK_RUNTIME
        with target.lock:
            target.state["updated"] = time.time()
            data = dict(target.state)
        playback_repository.save(data, target.user_id)
    except Exception:
        pass

def _media_key(media: str, root_id: str, rel: str) -> str:
    return f"{(media or '').strip().lower()}::{(root_id or '').strip()}::{(rel or '').strip()}"


def media_progress_key(root_id: str, rel: str) -> str:
    return f"{str(root_id or '').strip()}::{str(rel or '').replace(chr(92), '/').strip('/')}"


def completion_percent(position: Any, duration: Any, ended: bool = False) -> int:
    try:
        dur = max(0.0, float(duration or 0))
    except Exception:
        dur = 0.0
    try:
        pos = max(0.0, float(position or 0))
    except Exception:
        pos = 0.0
    if dur <= 0:
        return 0
    if ended or pos >= max(0.0, dur - 30.0):
        return 100
    return max(0, min(100, int((pos / dur) * 100.0)))


def media_progress_for(root_id: str, rel: str, runtime: PlaybackRuntime | None = None) -> dict:
    key = media_progress_key(root_id, rel)
    state, lock = _runtime_parts(runtime)
    with lock:
        raw = (state.get("media_progress") or {}).get(key)
        out = dict(raw) if isinstance(raw, dict) else {}
    out.setdefault("position", 0.0)
    out.setdefault("duration", 0.0)
    out.setdefault("updated", 0.0)
    out.setdefault("ended", False)
    out["completion_percent"] = completion_percent(out.get("position"), out.get("duration"), bool(out.get("ended")))
    return out


def media_progress_snapshot(runtime: PlaybackRuntime | None = None) -> dict[str, dict]:
    state, lock = _runtime_parts(runtime)
    with lock:
        raw = dict(state.get("media_progress") or {})
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        item = dict(value)
        item["completion_percent"] = completion_percent(item.get("position"), item.get("duration"), bool(item.get("ended")))
        out[str(key)] = item
    return out

def _trim_recent(recent: list, max_items: int = 0) -> list:
    out = recent if isinstance(recent, list) else []
    if max_items and max_items > 0:
        return out[:max_items]
    return out

def _public_entry(value: Any) -> Any:
    if isinstance(value, list):
        return [_public_entry(x) for x in value]
    if isinstance(value, dict):
        d = dict(value)
        for key in ("_key", "_sess", "_list", "_stream_item"):
            d.pop(key, None)
        return {k: _public_entry(v) for k, v in d.items()}
    return value

def _sanitize_session_item(it: Any, media_fallback: str = "audio") -> Optional[Dict[str, Any]]:
    if not isinstance(it, dict):
        return None
    root_obj = it.get("root") if isinstance(it.get("root"), dict) else {}
    root_id = str(it.get("root_id") or it.get("rootId") or root_obj.get("id") or "").strip()
    rel = str(it.get("rel") or "").strip()
    if not root_id or not rel:
        return None
    media = str(it.get("media") or media_fallback or "audio").strip().lower() or "audio"
    if media not in ("audio", "video"):
        media = media_fallback if media_fallback in ("audio", "video") else "audio"
    return {
        "kind": str(it.get("kind") or "file"),
        "media": media,
        "root": {"id": root_id},
        "root_id": root_id,
        "rel": rel,
        "label": str(it.get("label") or it.get("title") or ""),
        "streamed": bool(it.get("streamed")),
        "source": str(it.get("source") or "").strip().lower(),
        "ext": str(it.get("ext") or "").strip().lower(),
        "quality": str(it.get("quality") or ""),
    }

def _sanitize_playback_session(raw: Any, now_entry: Optional[dict], recent: list, version: int) -> dict:
    src = raw if isinstance(raw, dict) else {}
    media = str((now_entry or {}).get("media") or (src.get("now") or {}).get("media") or "audio").lower()
    queue = []
    for it in (src.get("queue") if isinstance(src.get("queue"), list) else []):
        clean = _sanitize_session_item(it, media)
        if clean:
            queue.append(clean)
        if len(queue) >= 600:
            break
    try:
        queue_index = int(src.get("queueIndex") if src.get("queueIndex") is not None else src.get("queue_index"))
    except Exception:
        queue_index = 0 if queue else -1
    if queue:
        queue_index = max(0, min(len(queue) - 1, queue_index))
    else:
        queue_index = -1
    nav = src.get("nav") if isinstance(src.get("nav"), dict) else ((now_entry or {}).get("nav") if isinstance((now_entry or {}).get("nav"), dict) else None)
    source_view = src.get("sourceView") if isinstance(src.get("sourceView"), dict) else (src.get("source_view") if isinstance(src.get("source_view"), dict) else None)
    try:
        revision = int(src.get("revision") or version or 0)
    except Exception:
        revision = int(version or 0)
    return {
        "now": _public_entry(src.get("now") if isinstance(src.get("now"), dict) else now_entry),
        "queue": queue,
        "history": _public_entry(_trim_recent(recent)),
        "queueIndex": queue_index,
        "nav": _public_entry(nav),
        "sourceView": _public_entry(source_view),
        "updatedAt": src.get("updatedAt") or int(time.time() * 1000),
        "revision": revision,
    }

def _recent_list_key(media: str, root_id: str, rel: str, nav: dict) -> str:
    """Return a stable key that represents the *list context* an item was played from.

    This is used to decide whether the newest recently-played entry should overwrite the previous entry
    (same list), or create a new entry (different list).
    """
    try:
        rid = str(root_id or "").strip()
        rrel = str(rel or "").strip()
        nav_d = nav if isinstance(nav, dict) else {}
        kind = str(nav_d.get("kind") or "").strip().lower()
        nav_rid = str(nav_d.get("root_id") or rid).strip() or rid

        # Directory fallback (for unknown nav kinds)
        dir_rel = ""
        try:
            if "/" in rrel:
                dir_rel = rrel.rsplit("/", 1)[0]
            else:
                dir_rel = ""
        except Exception:
            dir_rel = ""

        base = ""
        if kind == "folder":
            base = "folder|" + nav_rid + "|" + str(nav_d.get("rel") or "")
        elif kind == "metalist":
            base = "meta|" + nav_rid + "|" + str(nav_d.get("level") or "") + "|" + str(nav_d.get("value") or "")
        elif kind:
            base = kind + "|" + nav_rid + "|" + str(nav_d.get("label") or "")
        else:
            base = "dir|" + nav_rid + "|" + dir_rel

        m = str(media or "").strip().lower()
        if m not in ("audio", "video"):
            m = "other"
        return m + "|" + base
    except Exception:
        try:
            m = str(media or "").strip().lower()
            if m not in ("audio", "video"):
                m = "other"
            return m + "|unknown"
        except Exception:
            return "unknown"


def playback_snapshot_public(runtime: PlaybackRuntime | None = None) -> dict:
    state, lock = _runtime_parts(runtime)
    with lock:
        now = state.get("now")
        recent = state.get("recent") or []
        version = int(state.get("version") or 0)
        # remove internal fields from each entry if present
        rp = []
        for it in recent:
            if not isinstance(it, dict):
                continue
            d = dict(it)
            d.pop("_key", None)
            d.pop("_sess", None)
            d.pop("_list", None)
            d.pop("_stream_item", None)
            rp.append(d)
        out_now = dict(now) if isinstance(now, dict) else None
        if isinstance(out_now, dict):
            out_now.pop("_key", None)
            out_now.pop("_sess", None)
            out_now.pop("_list", None)
            out_now.pop("_stream_item", None)
        session = _sanitize_playback_session(state.get("playback_session"), out_now, rp, version)
        progress = {str(key): dict(value) for key, value in (state.get("media_progress") or {}).items() if isinstance(value, dict)}
        for value in progress.values():
            if isinstance(value, dict):
                value["completion_percent"] = completion_percent(value.get("position"), value.get("duration"), bool(value.get("ended")))
        return {"now": out_now, "recent": rp, "session": session, "media_progress": progress, "version": version}

def playback_update_from_client(payload: dict, runtime: PlaybackRuntime | None = None) -> dict:
    # payload fields (best-effort):
    #   media: "audio"|"video"
    #   root_id, rel
    #   label, title, artist, album, art
    #   position, duration
    #   playing: bool
    #   nav: dict (navigation context to restore list/album/folder)
    #   event: "start"|"time"|"pause"|"stop"|"ended"
    js = payload if isinstance(payload, dict) else {}
    media = str(js.get("media") or "").strip().lower()
    if media not in ("audio", "video"):
        return {"ok": False, "error": "bad media"}
    root_id = str(js.get("root_id") or "").strip()
    rel = str(js.get("rel") or "").strip()
    stream_item = None
    search_root_id = _search_stream_root_id()
    stream_lookup = runtime.search_stream_get_or_restore if runtime is not None else _search_stream_get_or_restore
    if root_id == search_root_id and rel:
        stream_item = stream_lookup(rel) if callable(stream_lookup) else None
    if (not root_id or not rel) or (root_id == search_root_id and not stream_item):
        return {"ok": False, "error": "missing root_id or rel"}

    label = str(js.get("label") or "").strip()
    title = str(js.get("title") or "").strip()
    artist = str(js.get("artist") or "").strip()
    album = str(js.get("album") or "").strip()
    art = str(js.get("art") or "").strip()
    nav = js.get("nav") if isinstance(js.get("nav"), dict) else {}
    ev = str(js.get("event") or "").strip().lower()

    pos = js.get("position")
    dur = js.get("duration")
    try:
        pos_f = float(pos) if pos is not None and str(pos).strip() else 0.0
    except Exception:
        pos_f = 0.0
    try:
        dur_f = float(dur) if dur is not None and str(dur).strip() else None
    except Exception:
        dur_f = None

    playing = bool(js.get("playing")) if "playing" in js else None

    k = _media_key(media, root_id, rel)
    now_entry = {
        "_key": k,
        "media": media,
        "root_id": root_id,
        "rel": rel,
        "label": label,
        "title": title,
        "artist": artist,
        "album": album,
        "art": art,
        "position": max(0.0, pos_f),
        "duration": dur_f,
        "playing": bool(playing) if playing is not None else False,
        "nav": nav,
        "ts": time.time(),
        "streamed": bool(js.get("streamed")),
        "source": str(js.get("source") or "").strip().lower(),
        "ext": str(js.get("ext") or "").strip().lower(),
        "quality": str(js.get("quality") or "").strip(),
    }


    playlist_ctx = js.get("playlist") if isinstance(js.get("playlist"), dict) else None
    if playlist_ctx:
        # best-effort sanity limits
        items = playlist_ctx.get("items")
        if not isinstance(items, list):
            playlist_ctx = None
        else:
            if len(items) > 600:
                playlist_ctx["items"] = items[:600]
            try:
                playlist_ctx["index"] = int(playlist_ctx.get("index") or 0)
            except Exception:
                playlist_ctx["index"] = 0
            # strip unexpected large fields
            clean_items = []
            for itx in playlist_ctx.get("items") or []:
                if not isinstance(itx, dict):
                    continue
                rid = str(itx.get("root_id") or "").strip()
                rrel = str(itx.get("rel") or "").strip()
                m2 = str(itx.get("media") or media).strip().lower()
                lbl2 = str(itx.get("label") or "").strip()
                if not rid or not rrel:
                    continue
                clean_items.append({
                    "root_id": rid,
                    "rel": rrel,
                    "media": m2,
                    "label": lbl2,
                    "streamed": bool(itx.get("streamed")),
                    "source": str(itx.get("source") or "").strip().lower(),
                    "ext": str(itx.get("ext") or "").strip().lower(),
                    "quality": str(itx.get("quality") or ""),
                })
            playlist_ctx["items"] = clean_items

    playlist_hash = str(js.get("playlist_hash") or "").strip()
    if playlist_ctx:
        now_entry["playlist"] = playlist_ctx
        if playlist_hash:
            now_entry["playlist_hash"] = playlist_hash
    elif playlist_hash:
        try:
            state, _ = _runtime_parts(runtime)
            prev_now = state.get("now") if isinstance(state, dict) else None
            if isinstance(prev_now, dict) and str(prev_now.get("playlist_hash") or "") == playlist_hash and isinstance(prev_now.get("playlist"), dict):
                now_entry["playlist"] = dict(prev_now.get("playlist") or {})
                now_entry["playlist_hash"] = playlist_hash
        except Exception:
            pass
    if stream_item:
        now_entry["streamed"] = True
        now_entry["source"] = str(stream_item.get("source") or now_entry.get("source") or "").strip().lower()
        stream_title = str(stream_item.get("title") or stream_item.get("name") or "").strip()
        stream_name = str(stream_item.get("name") or stream_item.get("title") or "").strip()
        if now_entry.get("source") == "youtube" and stream_title:
            now_entry["title"] = stream_title
            now_entry["label"] = stream_title
        else:
            if not now_entry.get("title"):
                now_entry["title"] = stream_title
            if not now_entry.get("label"):
                now_entry["label"] = stream_name
        if not now_entry.get("album"):
            now_entry["album"] = str(stream_item.get("album") or "")
        if not now_entry.get("artist"):
            now_entry["artist"] = str(stream_item.get("artist") or "")
        if not now_entry.get("art"):
            now_entry["art"] = str(stream_item.get("art") or "")
        if not now_entry.get("ext"):
            now_entry["ext"] = str(stream_item.get("ext") or "").strip().lower()
        if not now_entry.get("quality"):
            now_entry["quality"] = str(stream_item.get("quality") or "")
        keep_keys = (
            "item_id", "queue_index", "queue_count", "session_title",
            "media", "name", "title", "artist", "album", "art", "size",
            "source", "streamed", "ext", "quality", "url", "youtube_url",
            "format_id", "itag", "mime", "requires_local_mux", "provider", "provider_label",
            "trusted_provider_stream"
        )
        now_entry["_stream_item"] = {k: stream_item.get(k) for k in keep_keys if k in stream_item}

    
    # recently played overwrite key (list or directory context)
    now_entry["_list"] = _recent_list_key(media, root_id, rel, nav)
    source_view = js.get("source_view") if isinstance(js.get("source_view"), dict) else None
    client_session = js.get("session") if isinstance(js.get("session"), dict) else {}

    state, lock = _runtime_parts(runtime)
    with lock:
        prev_version = int(state.get("version") or 0)
        next_version = prev_version + 1
        # update now playing
        if playing is not None:
            now_entry["playing"] = bool(playing)
        state["now"] = now_entry
        if media == "video" and root_id != search_root_id:
            progress = state.get("media_progress")
            if not isinstance(progress, dict):
                progress = {}
            ended = ev == "ended"
            progress[media_progress_key(root_id, rel)] = {
                "root_id": root_id,
                "rel": rel,
                "position": max(0.0, pos_f),
                "duration": max(0.0, float(dur_f or 0.0)),
                "updated": time.time(),
                "ended": bool(ended),
            }
            state["media_progress"] = progress

        # recent list
        recent = state.get("recent") or []
        if not isinstance(recent, list):
            recent = []

        # per-media session tracking so audio and video never overwrite each other
        sess_key = "audio_session" if media == "audio" else "video_session"
        sess = state.get(sess_key) or {}
        if not isinstance(sess, dict):
            sess = {}

        if "session_id" not in sess:
            sess["session_id"] = ""
        if "last_activity_ts" not in sess:
            sess["last_activity_ts"] = 0.0
        if "last_stop_ts" not in sess:
            sess["last_stop_ts"] = 0.0

        now_ts = time.time()
        session_gap_seconds = 150.0

        sess_id = str(sess.get("session_id") or "")
        try:
            last_act = float(sess.get("last_activity_ts") or 0.0)
        except Exception:
            last_act = 0.0
        try:
            last_stop = float(sess.get("last_stop_ts") or 0.0)
        except Exception:
            last_stop = 0.0

        ev_s = (ev or "").strip().lower()
        is_playing_now = bool(now_entry.get("playing"))

        # update markers
        if is_playing_now:
            sess["last_activity_ts"] = now_ts
            last_act = now_ts
        if ev_s in ("pause", "stop", "ended"):
            sess["last_stop_ts"] = now_ts
            last_stop = now_ts

        # decide whether to start a new session based on last activity (play or stop)
        last_any = max(last_act, last_stop)
        start_new_session = False
        if not sess_id:
            start_new_session = True
        elif last_any > 0.0 and (now_ts - last_any) > session_gap_seconds:
            start_new_session = True

        # only create a new session id when playback is actually running
        if (ev_s in ("start", "time")) and is_playing_now and start_new_session:
            prefix = "a" if media == "audio" else "v"
            sess_id = prefix + str(int(now_ts)) + "_" + uuid.uuid4().hex[:8]
            sess["session_id"] = sess_id

        if sess_id:
            now_entry["_sess"] = sess_id

                # recently played: overwrite the previous entry when the list/directory context is the same;
        # otherwise add a new entry.
        found_by_key = None
        for i, it2 in enumerate(recent):
            if isinstance(it2, dict) and it2.get("_key") == k:
                found_by_key = i
                break

        if ev_s == "start":
            if recent and isinstance(recent[0], dict) and recent[0].get("_list") == now_entry.get("_list"):
                recent[0] = dict(now_entry)
            else:
                if found_by_key is not None:
                    try:
                        recent.pop(found_by_key)
                    except Exception:
                        pass
                recent.insert(0, dict(now_entry))
        else:
            # Do not reorder on time/pause/stop updates; just refresh fields if we can find a matching entry.
            if found_by_key is not None and isinstance(recent[found_by_key], dict):
                recent[found_by_key].update(dict(now_entry))
            elif recent and isinstance(recent[0], dict) and recent[0].get("_list") == now_entry.get("_list"):
                recent[0].update(dict(now_entry))
            elif not recent and (ev_s in ("time", "start")) and is_playing_now:
                recent.insert(0, dict(now_entry))
        state[sess_key] = sess
        state["recent"] = _trim_recent(recent)
        session_seed = dict(client_session) if isinstance(client_session, dict) else {}
        if source_view and not isinstance(session_seed.get("sourceView"), dict):
            session_seed["sourceView"] = source_view
        if nav and not isinstance(session_seed.get("nav"), dict):
            session_seed["nav"] = nav
        session_seed["revision"] = next_version
        state["playback_session"] = _sanitize_playback_session(session_seed, now_entry, state["recent"], next_version)
        state["version"] = next_version

    save_playback_state_best_effort(runtime)
    return {"ok": True, "version": next_version, "revision": next_version}


# =========================
