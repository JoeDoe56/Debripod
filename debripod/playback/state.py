from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from ..paths import cache_dir

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
PLAYBACK_STATE_LOCK = threading.Lock()

def playback_state_path() -> str:
    return os.path.join(cache_dir(), "playback_state.json")

def _default_playback_state() -> dict:
    return {
        "now": None,              # dict or None
        "recent": [],             # list[dict], newest first
        # session tracking is separate for audio and video so they never overwrite each other
        "audio_session": {
            "session_id": "",
            "last_activity_ts": 0.0,   # updated while playing
            "last_stop_ts": 0.0,       # updated on pause/stop/ended
            # legacy key kept for backward compatibility
            "last_play_ts": 0.0,
        },
        "video_session": {
            "session_id": "",
            "last_activity_ts": 0.0,
            "last_stop_ts": 0.0,
        },
        # legacy unified key kept so older files still load, but it is not used anymore
        "session": {
            "session_id": "",
            "last_activity_ts": 0.0,
            "last_stop_ts": 0.0,
        },
        "ver": 3,
        "updated": 0.0,
    }

PLAYBACK_STATE: dict = _default_playback_state()

def load_playback_state() -> None:
    global PLAYBACK_STATE
    p = playback_state_path()
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                js = json.load(f)
            if isinstance(js, dict):
                base = _default_playback_state()
                base.update(js)

                # recent must be a list
                if not isinstance(base.get("recent"), list):
                    base["recent"] = []

                # normalize audio_session
                a = base.get("audio_session")
                if not isinstance(a, dict):
                    a = {}
                if "session_id" not in a:
                    a["session_id"] = ""
                # support old schema: last_play_ts used instead of last_activity_ts
                if "last_play_ts" not in a:
                    a["last_play_ts"] = 0.0
                if "last_activity_ts" not in a:
                    try:
                        a["last_activity_ts"] = float(a.get("last_play_ts") or 0.0)
                    except Exception:
                        a["last_activity_ts"] = 0.0
                if "last_stop_ts" not in a:
                    a["last_stop_ts"] = 0.0
                base["audio_session"] = a

                # normalize video_session
                v = base.get("video_session")
                if not isinstance(v, dict):
                    v = {}
                if "session_id" not in v:
                    v["session_id"] = ""
                if "last_activity_ts" not in v:
                    v["last_activity_ts"] = 0.0
                if "last_stop_ts" not in v:
                    v["last_stop_ts"] = 0.0
                base["video_session"] = v

                # keep legacy unified session if present, but do not rely on it
                sess = base.get("session")
                if not isinstance(sess, dict):
                    sess = {"session_id": "", "last_activity_ts": 0.0, "last_stop_ts": 0.0}
                if "session_id" not in sess:
                    sess["session_id"] = ""
                if "last_activity_ts" not in sess:
                    sess["last_activity_ts"] = 0.0
                if "last_stop_ts" not in sess:
                    sess["last_stop_ts"] = 0.0
                base["session"] = sess

                PLAYBACK_STATE = base
    except Exception:
        PLAYBACK_STATE = _default_playback_state()

def save_playback_state_best_effort() -> None:
    p = playback_state_path()
    tmp = p + ".tmp"
    try:
        data = None
        with PLAYBACK_STATE_LOCK:
            PLAYBACK_STATE["updated"] = time.time()
            data = json.dumps(PLAYBACK_STATE, indent=2)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, p)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def _media_key(media: str, root_id: str, rel: str) -> str:
    return f"{(media or '').strip().lower()}::{(root_id or '').strip()}::{(rel or '').strip()}"

def _trim_recent(recent: list, max_items: int = 60) -> list:
    out = recent[:max_items] if isinstance(recent, list) else []
    return out

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


def playback_snapshot_public() -> dict:
    with PLAYBACK_STATE_LOCK:
        now = PLAYBACK_STATE.get("now")
        recent = PLAYBACK_STATE.get("recent") or []
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
        return {"now": out_now, "recent": rp}

def playback_update_from_client(payload: dict) -> dict:
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
    if root_id == _search_stream_root_id() and rel:
        stream_item = _search_stream_get_or_restore(rel)
    if (not root_id or not rel) or (root_id == _search_stream_root_id() and not stream_item):
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
                clean_items.append({"root_id": rid, "rel": rrel, "media": m2, "label": lbl2})
            playlist_ctx["items"] = clean_items

    if playlist_ctx:
        now_entry["playlist"] = playlist_ctx
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
            "format_id", "itag", "mime", "requires_local_mux"
        )
        now_entry["_stream_item"] = {k: stream_item.get(k) for k in keep_keys if k in stream_item}

    
    # recently played overwrite key (list or directory context)
    now_entry["_list"] = _recent_list_key(media, root_id, rel, nav)

    with PLAYBACK_STATE_LOCK:
        # update now playing
        if playing is not None:
            now_entry["playing"] = bool(playing)
        PLAYBACK_STATE["now"] = now_entry

        # recent list
        recent = PLAYBACK_STATE.get("recent") or []
        if not isinstance(recent, list):
            recent = []

        # per-media session tracking so audio and video never overwrite each other
        sess_key = "audio_session" if media == "audio" else "video_session"
        sess = PLAYBACK_STATE.get(sess_key) or {}
        if not isinstance(sess, dict):
            sess = {}

        if "session_id" not in sess:
            sess["session_id"] = ""
        if "last_activity_ts" not in sess:
            # migrate from legacy audio_session key if present
            try:
                sess["last_activity_ts"] = float(sess.get("last_play_ts") or 0.0)
            except Exception:
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
            # legacy audio key kept up to date
            if media == "audio":
                sess["last_play_ts"] = now_ts
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
        PLAYBACK_STATE[sess_key] = sess
        PLAYBACK_STATE["recent"] = _trim_recent(recent)

    save_playback_state_best_effort()
    return {"ok": True}


# =========================
