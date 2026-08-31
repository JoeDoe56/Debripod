from __future__ import annotations

from .runtime_state import *
from .runtime_downloads import *
from .Services.debrid import get_active_provider
from .user_runtime import SearchStreamStore, UserRuntime

_LEGACY_STREAM_STORE = SearchStreamStore()
SEARCH_STREAMS = _LEGACY_STREAM_STORE.sessions
SEARCH_STREAMS_LOCK = _LEGACY_STREAM_STORE.lock

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


def _stream_parts(runtime: UserRuntime | None = None) -> tuple[Dict[str, Dict[str, Any]], threading.RLock]:
    store = runtime.streams if runtime is not None else _LEGACY_STREAM_STORE
    return store.sessions, store.lock


def _search_stream_cleanup_locked(now_ts: Optional[float] = None, runtime: UserRuntime | None = None) -> None:
    streams, _ = _stream_parts(runtime)
    if now_ts is None:
        now_ts = time.time()
    stale = []
    for sid, sess in streams.items():
        try:
            ts = float(sess.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        if (now_ts - ts) > SEARCH_STREAM_SESSION_TTL_SECONDS:
            stale.append(sid)
    for sid in stale:
        streams.pop(sid, None)


def _search_stream_get(rel: str, runtime: UserRuntime | None = None) -> Optional[Dict[str, Any]]:
    raw = str(rel or "").strip().strip("/")
    if not raw or "/" not in raw:
        return None
    session_id, item_id = raw.split("/", 1)
    if not session_id or not item_id:
        return None
    streams, lock = _stream_parts(runtime)
    with lock:
        _search_stream_cleanup_locked(runtime=runtime)
        sess = streams.get(session_id)
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


def _playback_stream_item_for_rel(rel: str, runtime: UserRuntime | None = None) -> Optional[Dict[str, Any]]:
    raw = str(rel or "").strip().strip("/")
    if not raw:
        return None
    playback = runtime.playback if runtime is not None else None
    state = playback.state if playback is not None else PLAYBACK_STATE
    lock = playback.lock if playback is not None else PLAYBACK_STATE_LOCK
    with lock:
        candidates = []
        now = state.get("now")
        if isinstance(now, dict):
            candidates.append(now)
        recent = state.get("recent") or []
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


def _search_stream_get_or_restore(rel: str, runtime: UserRuntime | None = None) -> Optional[Dict[str, Any]]:
    it = _search_stream_get(rel, runtime)
    if it:
        return it
    restored = _playback_stream_item_for_rel(rel, runtime)
    if not restored:
        return None
    try:
        raw = str(rel or "").strip().strip("/")
        session_id, item_id = raw.split("/", 1)
    except Exception:
        return restored
    streams, lock = _stream_parts(runtime)
    with lock:
        _search_stream_cleanup_locked(runtime=runtime)
        sess = streams.get(session_id)
        if not isinstance(sess, dict):
            sess = {"ts": time.time(), "title": str(restored.get("session_title") or restored.get("title") or restored.get("album") or "Search stream"), "source": str(restored.get("source") or ""), "items": []}
            streams[session_id] = sess
        sess["ts"] = time.time()
        items = list(sess.get("items") or [])
        if not any(isinstance(x, dict) and str(x.get("item_id") or "") == item_id for x in items):
            add = dict(restored)
            add["item_id"] = item_id
            items.append(add)
            sess["items"] = items
    return _search_stream_get(rel, runtime) or restored


def _active_debrid_provider(http, runtime: UserRuntime | None = None):
    if runtime is not None:
        settings = dict(runtime.settings)
        return get_active_provider(settings, int(settings.get("REQUEST_TIMEOUT_SECONDS") or 25), http)
    keys = (
        "DEBRID_PROVIDER", "REAL_DEBRID_API_KEY", "RD_BASE",
        "ALLDEBRID_API_KEY", "ALLDEBRID_BASE", "PREMIUMIZE_API_KEY", "PREMIUMIZE_BASE",
        "TORBOX_API_KEY", "TORBOX_BASE", "SEARCH_STREAM_SESSION_TTL_SECONDS",
    )
    return get_active_provider({key: globals().get(key) for key in keys}, int(REQUEST_TIMEOUT_SECONDS or 25), http)


def _ytdlp_source_url(value: dict) -> str:
    """Return a durable inspected-page URL, never a transient format URL."""
    if not isinstance(value, dict):
        return ""
    for key in ("source_url", "original_url", "canonical_url", "youtube_url", "url"):
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


async def _engine_prepare_stream_session(payload: dict, http, runtime: UserRuntime | None = None) -> dict:
    src = str(payload.get("source") or "").strip().lower()
    if src == "youtube":
        url = _ytdlp_source_url(payload)
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
            item_url = _ytdlp_source_url(it)
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
        streams, lock = _stream_parts(runtime)
        with lock:
            _search_stream_cleanup_locked(runtime=runtime)
            streams[session_id] = {'ts': time.time(), 'title': title, 'source': src, 'items': items}
        out_items = []
        for it in items:
            rel = _search_stream_rel(session_id, str(it.get('item_id') or ''))
            out_items.append({'root_id': SEARCH_STREAM_ROOT_ID, 'rel': rel, 'media': it.get('media') or '', 'label': it.get('name') or '', 'title': it.get('title') or '', 'artist': it.get('artist') or '', 'album': it.get('album') or '', 'art': it.get('art') or '', 'streamed': True, 'source': it.get('source') or src, 'ext': it.get('ext') or '', 'quality': it.get('quality') or '', 'size': int(it.get('size') or 0)})
        return {'session_id': session_id, 'title': title, 'items': out_items}
    if src != "torrent":
        raise RuntimeError("Streaming is not available for this source")
    provider_task_id = str(payload.get("debrid_task_id") or "").strip()
    selected = payload.get("selected") or []
    title = str(payload.get("title") or payload.get("directory_title") or payload.get("directory") or "Search stream").strip() or "Search stream"
    if not provider_task_id:
        raise RuntimeError("Missing debrid task id")
    clean_ids = []
    selected_by_id = {}
    for it in selected:
        if not isinstance(it, dict):
            continue
        fid = str(it.get("file_id") or "").strip()
        if not fid:
            continue
        clean_ids.append(fid)
        selected_by_id[fid] = it
    if not clean_ids:
        raise RuntimeError("No files selected")
    provider = _active_debrid_provider(http, runtime)
    requested_provider = str(payload.get("provider") or "").strip().lower()
    if requested_provider and requested_provider != provider.id:
        raise RuntimeError("The preview provider is no longer active. Preview the result again.")
    prepared = await provider.prepare_selected_files(
        magnet=str(payload.get("magnet") or ""),
        provider_task_id=provider_task_id,
        selected_file_ids=clean_ids,
        timeout_seconds=int(MAX_TORRENT_WAIT_SECONDS or 1800),
        poll_interval_seconds=int(POLL_INTERVAL_SECONDS or 4),
    )
    prepared_by_id = {str(item.file_id): item for item in prepared}
    items = []
    for fid in clean_ids:
        meta = selected_by_id.get(fid) or {}
        name = str(meta.get("name") or meta.get("title") or f"File {fid}")
        media = _guess_media_from_name(name)
        if media not in ("audio", "video"):
            continue
        file = prepared_by_id.get(fid)
        if not file:
            continue
        resolved = await provider.resolve_file_url(file)
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
            "size": int(resolved.size or file.bytes or meta.get("size") or 0),
            "source": src,
            "provider": provider.id,
            "provider_label": provider.label,
            "streamed": True,
            "ext": str(meta.get("ext") or os.path.splitext(name)[1].lstrip('.')).lower(),
            "quality": str(meta.get("quality") or meta.get("bitrate") or ""),
            "url": resolved.url,
            "mime": resolved.mime,
            "trusted_provider_stream": True,
        })
    if not items:
        raise RuntimeError("No selected files were streamable")
    session_id = uuid.uuid4().hex
    streams, lock = _stream_parts(runtime)
    with lock:
        _search_stream_cleanup_locked(runtime=runtime)
        streams[session_id] = {"ts": time.time(), "title": title, "source": src, "items": items}
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



def build_task_dir(task_id: str, title: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = sanitize_folder_name(title)
    folder = f"{stamp}_{base}_{task_id[:6]}"
    folder = sanitize_folder_name(folder)
    return os.path.join(DOWNLOAD_DIR, folder)



__all__ = [name for name in globals() if not name.startswith("__")]
