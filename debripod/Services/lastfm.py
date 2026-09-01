from __future__ import annotations

import hashlib
import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import quote

from ..secrets import get_secret, set_secret
from ..storage.lastfm import load_loved, save_loved
from ..storage import settings as settings_repository
from .http import HttpClient

LASTFM_API_KEY = ""
LASTFM_API_SECRET = ""
LASTFM_SESSION_KEY = ""
LASTFM_CALLBACK_URL = ""
LASTFM_API_ROOT = ""
LASTFM_REQUEST_TIMEOUT_SECONDS = 0
_LASTFM_HTTP: HttpClient | None = None
_LASTFM_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


@dataclass(slots=True)
class LastfmClient:
    """Per-user Last.fm state and requests backed by one shared HTTP client."""

    user_id: str
    settings: dict[str, Any]
    http: HttpClient
    session_username: str = ""
    tracks: dict[str, int] = field(default_factory=dict)
    loved_updated: int = 0
    _background_tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.user_id = str(self.user_id or "").strip()
        self.session_username = str(self.settings.get("LASTFM_USERNAME") or "").strip()
        self.tracks, self.loved_updated = load_loved(self.user_id)

    @property
    def api_key(self) -> str:
        return str(self.settings.get("LASTFM_API_KEY") or "").strip()

    @property
    def api_secret(self) -> str:
        return str(self.settings.get("LASTFM_API_SECRET") or "").strip()

    @property
    def session_key(self) -> str:
        return str(self.settings.get("LASTFM_SESSION_KEY") or "").strip()

    @property
    def api_root(self) -> str:
        return str(self.settings.get("LASTFM_API_ROOT") or "https://ws.audioscrobbler.com/2.0/").strip()

    @property
    def timeout(self) -> int:
        try:
            return max(1, int(self.settings.get("LASTFM_REQUEST_TIMEOUT_SECONDS") or 12))
        except Exception:
            return 12

    def has_api_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def enabled(self) -> bool:
        return bool(self.has_api_credentials() and self.session_key)

    def _sign(self, params: Dict[str, Any]) -> str:
        parts = sorted(
            (str(key), _lastfm_param_str(value))
            for key, value in (params or {}).items()
            if key not in {"format", "callback"}
        )
        return _md5_hex("".join(key + value for key, value in parts) + self.api_secret)

    async def _api(self, method: str, params: Dict[str, Any] | None = None, *, auth: bool = False, verb: str = "POST") -> Dict[str, Any]:
        if not self.has_api_credentials():
            raise RuntimeError("Last.fm API key/secret not configured")
        payload: Dict[str, Any] = {"method": method, "api_key": self.api_key, "format": "json"}
        payload.update(params or {})
        if auth:
            if not self.session_key:
                raise RuntimeError("Last.fm session key not configured")
            payload["sk"] = self.session_key
        payload["api_sig"] = self._sign(payload)
        kwargs = {"data" if verb == "POST" else "params": {key: _lastfm_param_str(value) for key, value in payload.items()}, "timeout": self.timeout}
        response = await self.http.json(verb, self.api_root, **kwargs)
        if isinstance(response, dict) and response.get("error"):
            raise RuntimeError(str(response.get("message") or "Last.fm API error"))
        return response if isinstance(response, dict) else {}

    def _persist_session(self, session_key: str, username: str) -> None:
        clean_key = str(session_key or "").strip()
        self.settings["LASTFM_SESSION_KEY"] = clean_key
        self.settings["LASTFM_USERNAME"] = str(username or "").strip()
        self.settings["LASTFM_SESSION_UPDATED"] = int(time.time())
        set_secret(self.user_id, "LASTFM_SESSION_KEY", clean_key)
        stored = settings_repository.load(self.user_id)
        stored.update({
            "LASTFM_USERNAME": self.settings["LASTFM_USERNAME"],
            "LASTFM_SESSION_UPDATED": self.settings["LASTFM_SESSION_UPDATED"],
        })
        settings_repository.save(stored, self.user_id)
        self.session_username = self.settings["LASTFM_USERNAME"]

    async def auth_start(self) -> Dict[str, Any]:
        response = await self._api("auth.getToken", auth=False)
        token = str((response.get("token") or {}).get("#text") if isinstance(response.get("token"), dict) else response.get("token") or "").strip()
        if not token:
            raise RuntimeError("Could not get Last.fm token")
        url = f"https://www.last.fm/api/auth/?api_key={quote(self.api_key)}&token={quote(token)}"
        callback = str(self.settings.get("LASTFM_CALLBACK_URL") or "").strip()
        if callback:
            url += f"&cb={quote(callback, safe='')}"
        return {"token": token, "auth_url": url}

    async def auth_finish(self, token: str) -> Dict[str, Any]:
        clean_token = str(token or "").strip()
        if not clean_token:
            raise RuntimeError("Missing token")
        response = await self._api("auth.getSession", {"token": clean_token}, auth=False)
        session = response.get("session") if isinstance(response.get("session"), dict) else {}
        key = str(session.get("key") or "").strip()
        username = str(session.get("name") or "").strip()
        if not key:
            raise RuntimeError("Missing session key")
        self._persist_session(key, username)
        self.spawn(self.sync_loved_from_remote, username)
        return {"sk": key, "username": username}

    async def sync_loved_from_remote(self, username: str = "", max_pages: int = 20, limit: int = 200) -> int:
        account = str(username or self.session_username or "").strip()
        if not account:
            return 0
        seen = 0
        page = 1
        total_pages: int | None = None
        while page <= max(1, int(max_pages)) and (total_pages is None or page <= total_pages):
            response = await self._api("user.getLovedTracks", {"user": account, "limit": str(min(200, max(10, int(limit)))), "page": str(page)}, verb="GET")
            loved = response.get("lovedtracks") if isinstance(response.get("lovedtracks"), dict) else {}
            attr = loved.get("@attr") if isinstance(loved.get("@attr"), dict) else {}
            try:
                total_pages = int(attr.get("totalPages") or 0) or None
            except Exception:
                total_pages = None
            rows = loved.get("track")
            rows = rows if isinstance(rows, list) else ([rows] if isinstance(rows, dict) else [])
            if not rows:
                break
            for row in rows:
                artist_data = row.get("artist") if isinstance(row, dict) else {}
                artist = str(artist_data.get("name") or artist_data.get("#text") or "") if isinstance(artist_data, dict) else str(artist_data or "")
                title = str(row.get("name") or "") if isinstance(row, dict) else ""
                key = _lastfm_track_key(artist, title, "")
                if key.strip():
                    self.tracks[key] = 1
                    seen += 1
            page += 1
        if seen:
            self._save_loved()
        return seen

    def _save_loved(self) -> None:
        self.loved_updated = save_loved(self.tracks, self.user_id)

    def is_loved(self, artist: str, title: str, album: str = "") -> bool:
        return bool(self.tracks.get(_lastfm_track_key(artist, title, album)) or self.tracks.get(_lastfm_track_key(artist, title, "")))

    def set_loved_local(self, artist: str, title: str, album: str, loved: bool) -> bool:
        key = _lastfm_track_key(artist, title, album)
        broad = _lastfm_track_key(artist, title, "")
        if not key.strip():
            return False
        if loved:
            self.tracks[key] = 1
            self.tracks[broad] = 1
        else:
            self.tracks.pop(key, None)
            self.tracks.pop(broad, None)
        self._save_loved()
        return True

    async def remote_is_loved(self, artist: str, title: str, username: str = "") -> Optional[bool]:
        account = str(username or self.session_username or "").strip()
        if not artist or not title or not account:
            return None
        try:
            response = await self._api("track.getInfo", {"artist": artist, "track": title, "username": account, "autocorrect": "1"}, verb="GET")
            track = response.get("track") if isinstance(response.get("track"), dict) else {}
            return str(track.get("userloved")).strip() == "1" if track.get("userloved") is not None else None
        except Exception:
            return None

    async def love_track(self, artist: str, title: str) -> bool:
        await self._api("track.love", {"artist": artist, "track": title}, auth=True)
        return True

    async def unlove_track(self, artist: str, title: str) -> bool:
        await self._api("track.unlove", {"artist": artist, "track": title}, auth=True)
        return True

    async def update_now_playing(self, artist: str, title: str, album: str = "", duration: Optional[int] = None) -> bool:
        payload: Dict[str, Any] = {"artist": artist, "track": title}
        if album:
            payload["album"] = album
        if duration and int(duration) > 0:
            payload["duration"] = str(int(duration))
        await self._api("track.updateNowPlaying", payload, auth=True)
        return True

    async def scrobble(self, artist: str, title: str, album: str = "", duration: Optional[int] = None, start_ts: Optional[int] = None) -> bool:
        payload: Dict[str, Any] = {"artist[0]": artist, "track[0]": title, "timestamp[0]": str(int(start_ts) if start_ts else int(time.time()))}
        if album:
            payload["album[0]"] = album
        if duration and int(duration) > 0:
            payload["duration[0]"] = str(int(duration))
        await self._api("track.scrobble", payload, auth=True)
        return True

    def spawn(self, operation, *args: Any) -> None:
        if not self.enabled():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(operation(*args), name=f"lastfm:{self.user_id}")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

def configure_lastfm(
    *,
    api_key: str,
    api_secret: str,
    session_key: str,
    callback_url: str,
    api_root: str = "",
    request_timeout_seconds: int = 0,
) -> None:
    global LASTFM_API_KEY, LASTFM_API_SECRET, LASTFM_SESSION_KEY, LASTFM_CALLBACK_URL
    global LASTFM_API_ROOT, LASTFM_REQUEST_TIMEOUT_SECONDS
    LASTFM_API_KEY = api_key or ""
    LASTFM_API_SECRET = api_secret or ""
    LASTFM_SESSION_KEY = session_key or ""
    LASTFM_CALLBACK_URL = callback_url or ""
    if api_root:
        LASTFM_API_ROOT = api_root
    if request_timeout_seconds:
        LASTFM_REQUEST_TIMEOUT_SECONDS = int(request_timeout_seconds)


def configure_lastfm_http(http: HttpClient) -> None:
    """Attach the one application-scoped HTTP client after aiohttp startup."""
    global _LASTFM_HTTP
    _LASTFM_HTTP = http


def _lastfm_http() -> HttpClient:
    if _LASTFM_HTTP is None:
        raise RuntimeError("Last.fm HTTP transport is not initialized")
    return _LASTFM_HTTP

def initialize_lastfm_cache() -> None:
    _lastfm_load_session_cache()
    _lastfm_loved_load()


def reset_lastfm_runtime_state() -> None:
    with _LASTFM_SESSION_LOCK:
        _LASTFM_SESSION["sk"] = ""
        _LASTFM_SESSION["username"] = ""
        _LASTFM_SESSION["ts"] = 0
    with _LASTFM_LOVED_LOCK:
        _LASTFM_LOVED["version"] = 1
        _LASTFM_LOVED["updated"] = 0
        _LASTFM_LOVED["tracks"] = {}


def lastfm_loved_updated() -> int:
    with _LASTFM_LOVED_LOCK:
        return int(_LASTFM_LOVED.get("updated") or 0)

_LASTFM_SESSION_LOCK = threading.Lock()
_LASTFM_SESSION = {
    "sk": "",
    "username": "",
    "ts": 0,
}

_LASTFM_LOVED = {
    "version": 1,
    "updated": 0,
    "tracks": {},  # key -> 1
}
_LASTFM_LOVED_LOCK = threading.Lock()


def lastfm_enabled() -> bool:
    # Enabled when we have API credentials and a session key.
    return bool((LASTFM_API_KEY or "").strip() and (LASTFM_API_SECRET or "").strip() and (lastfm_session_key() or "").strip())


def _md5_hex(s: str) -> str:
    return hashlib.md5((s or "").encode("utf-8", "ignore")).hexdigest()


def _lastfm_param_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def lastfm_session_key() -> str:
    # Prefer explicit config override, otherwise use cached session.
    sk = (LASTFM_SESSION_KEY or "").strip()
    if sk:
        return sk
    with _LASTFM_SESSION_LOCK:
        return str(_LASTFM_SESSION.get("sk") or "").strip()


def lastfm_username() -> str:
    with _LASTFM_SESSION_LOCK:
        return str(_LASTFM_SESSION.get("username") or "").strip()


def _lastfm_sign(params: Dict[str, Any]) -> str:
    # Per Last.fm auth spec: sort params by name, concat <name><value>, exclude format/callback, append secret, md5.
    items = []
    for k, v in (params or {}).items():
        if k in ("format", "callback"):
            continue
        items.append((str(k), _lastfm_param_str(v)))
    items.sort(key=lambda kv: kv[0])
    s = "".join([k + v for k, v in items]) + (LASTFM_API_SECRET or "")
    return _md5_hex(s)


async def _lastfm_api_post(method: str, params: Dict[str, Any], require_auth: bool = True) -> Dict[str, Any]:
    if not (LASTFM_API_KEY or "").strip() or not (LASTFM_API_SECRET or "").strip():
        raise RuntimeError("Last.fm API key/secret not configured")

    base: Dict[str, Any] = {"method": method, "api_key": (LASTFM_API_KEY or "").strip(), "format": "json"}
    if params:
        base.update(params)

    if require_auth:
        sk = lastfm_session_key()
        if not sk:
            raise RuntimeError("Last.fm session key not configured")
        base["sk"] = sk

    base["api_sig"] = _lastfm_sign(base)

    js = await _lastfm_http().json(
        "POST",
        LASTFM_API_ROOT,
        data={k: _lastfm_param_str(v) for k, v in base.items()},
        timeout=LASTFM_REQUEST_TIMEOUT_SECONDS,
    )
    if isinstance(js, dict) and js.get("error"):
        raise RuntimeError(str(js.get("message") or "Last.fm API error"))
    return js if isinstance(js, dict) else {}



async def _lastfm_api_get(method: str, params: Optional[Dict[str, Any]] = None, require_auth: bool = False) -> Dict[str, Any]:
    # Some Last.fm methods are typically called via GET. This helper mirrors _lastfm_api_post.
    if not (LASTFM_API_KEY or "").strip() or not (LASTFM_API_SECRET or "").strip():
        raise RuntimeError("Last.fm API key/secret not configured")

    base: Dict[str, Any] = {"method": method, "api_key": (LASTFM_API_KEY or "").strip(), "format": "json"}
    if params:
        base.update(params)

    if require_auth:
        sk = lastfm_session_key()
        if not sk:
            raise RuntimeError("Last.fm session key not configured")
        base["sk"] = sk

    # Only sign if we have a secret; keep consistent with authspec rules.
    base["api_sig"] = _lastfm_sign(base)

    js = await _lastfm_http().json(
        "GET",
        LASTFM_API_ROOT,
        params={k: _lastfm_param_str(v) for k, v in base.items()},
        timeout=LASTFM_REQUEST_TIMEOUT_SECONDS,
    )
    if isinstance(js, dict) and js.get("error"):
        raise RuntimeError(str(js.get("message") or "Last.fm API error"))
    return js if isinstance(js, dict) else {}


def _lastfm_load_session_cache() -> None:
    stored = settings_repository.load("")
    with _LASTFM_SESSION_LOCK:
        _LASTFM_SESSION["sk"] = (LASTFM_SESSION_KEY or get_secret("global", "LASTFM_SESSION_KEY")).strip()
        _LASTFM_SESSION["username"] = str(stored.get("LASTFM_USERNAME") or "").strip()
        _LASTFM_SESSION["ts"] = int(stored.get("LASTFM_SESSION_UPDATED") or 0)


def _lastfm_save_session_cache(sk: str, username: str = "") -> None:
    js = {"sk": (sk or "").strip(), "username": (username or "").strip(), "ts": int(time.time())}
    set_secret("global", "LASTFM_SESSION_KEY", js["sk"])
    stored = settings_repository.load("")
    stored.update({"LASTFM_USERNAME": js["username"], "LASTFM_SESSION_UPDATED": js["ts"]})
    settings_repository.save(stored, "")
    with _LASTFM_SESSION_LOCK:
        _LASTFM_SESSION.update(js)


async def lastfm_auth_start() -> Dict[str, Any]:
    # Desktop auth flow: auth.getToken + user approves in browser.
    # Docs: https://www.last.fm/api/authspec
    js = await _lastfm_api_post("auth.getToken", {}, require_auth=False)
    token = ""
    try:
        token = str(((js.get("token") or {}).get("#text") if isinstance(js.get("token"), dict) else js.get("token")) or "").strip()
    except Exception:
        token = str(js.get("token") or "").strip()
    if not token:
        raise RuntimeError("Could not get Last.fm token")
    auth_url = f"https://www.last.fm/api/auth/?api_key={quote((LASTFM_API_KEY or '').strip())}&token={quote(token)}"
    cb = (LASTFM_CALLBACK_URL or "").strip()
    if cb:
        auth_url += f"&cb={quote(cb, safe='')}"
    return {"token": token, "auth_url": auth_url}


async def lastfm_auth_finish(token: str) -> Dict[str, Any]:
    token = (token or "").strip()
    if not token:
        raise RuntimeError("Missing token")
    js = await _lastfm_api_post("auth.getSession", {"token": token}, require_auth=False)
    sess = js.get("session") if isinstance(js, dict) else None
    if not isinstance(sess, dict):
        raise RuntimeError("Invalid session response")
    sk = str(sess.get("key") or "").strip()
    name = str(sess.get("name") or "").strip()
    if not sk:
        raise RuntimeError("Missing session key")
    _lastfm_save_session_cache(sk, name)
    # Best-effort: pull loved tracks so UI can show â™¥ immediately for existing likes.
    _lastfm_async(lastfm_sync_loved_from_remote, name)
    return {"sk": sk, "username": name}



async def lastfm_sync_loved_from_remote(username: str = "", max_pages: int = 20, limit: int = 200) -> int:
    # Fetch the user's loved tracks from Last.fm and cache them locally.
    # This allows fast loved lookups without hitting Last.fm for every track.
    user = (username or "").strip() or lastfm_username()
    if not user:
        return 0

    max_pages_i = int(max(1, max_pages))
    limit_i = int(min(200, max(10, limit)))

    page = 1
    seen = 0
    total_pages = None

    while page <= max_pages_i and (total_pages is None or page <= total_pages):
        js = await _lastfm_api_get("user.getLovedTracks", {"user": user, "limit": str(limit_i), "page": str(page)}, require_auth=False)
        loved = js.get("lovedtracks") if isinstance(js, dict) else None
        if not isinstance(loved, dict):
            break

        # totalPages lives under @attr in most responses
        if total_pages is None:
            try:
                attr = loved.get("@attr") if isinstance(loved.get("@attr"), dict) else {}
                total_pages = int(attr.get("totalPages") or 0) or None
            except Exception:
                total_pages = None

        tracks_obj = loved.get("track")
        tracks_list: List[dict] = []
        if isinstance(tracks_obj, list):
            tracks_list = tracks_obj
        elif isinstance(tracks_obj, dict):
            tracks_list = [tracks_obj]
        else:
            tracks_list = []

        if not tracks_list:
            break

        with _LASTFM_LOVED_LOCK:
            db = _LASTFM_LOVED.get("tracks") or {}
            for tr in tracks_list:
                try:
                    title = str(tr.get("name") or "").strip()
                    artist_obj = tr.get("artist")
                    artist = ""
                    if isinstance(artist_obj, dict):
                        artist = str(artist_obj.get("name") or artist_obj.get("#text") or "").strip()
                    else:
                        artist = str(artist_obj or "").strip()
                    if not artist or not title:
                        continue
                    # Store album-blank key for broad matching
                    k = _lastfm_track_key(artist, title, "")
                    if k.strip():
                        db[k] = 1
                        seen += 1
                except Exception:
                    continue
            _LASTFM_LOVED["tracks"] = db

        page += 1

    if seen > 0:
        _lastfm_loved_save()
    return seen


def _lastfm_track_key(artist: str, title: str, album: str = "") -> str:
    a = (artist or "").strip().lower()
    t = (title or "").strip().lower()
    b = (album or "").strip().lower()
    return a + "\n" + t + "\n" + b


def _lastfm_loved_load() -> None:
    tracks, updated = load_loved()
    with _LASTFM_LOVED_LOCK:
        _LASTFM_LOVED["version"] = 1
        _LASTFM_LOVED["updated"] = updated
        _LASTFM_LOVED["tracks"] = tracks


def _lastfm_loved_save() -> None:
    with _LASTFM_LOVED_LOCK:
        tracks = dict(_LASTFM_LOVED.get("tracks") or {})
    updated = save_loved(tracks)
    with _LASTFM_LOVED_LOCK:
        _LASTFM_LOVED["updated"] = updated


def lastfm_is_loved(artist: str, title: str, album: str = "") -> bool:
    # Check exact match first, then fallback to album-blank key so remote loved tracks
    # (which often don't include album) still show as loved.
    k = _lastfm_track_key(artist, title, album)
    if not k.strip():
        return False
    k2 = _lastfm_track_key(artist, title, "")
    with _LASTFM_LOVED_LOCK:
        tracks = _LASTFM_LOVED.get("tracks") or {}
        return bool(tracks.get(k) or tracks.get(k2))


async def lastfm_remote_is_loved(artist: str, title: str, username: str = "") -> Optional[bool]:
    # Best-effort remote check for whether the user has loved this track.
    # Uses track.getInfo with username; returns True/False on success, or None on failure.
    a = (artist or "").strip()
    t = (title or "").strip()
    if not a or not t:
        return None
    user = (username or "").strip() or lastfm_username()
    if not user:
        return None
    try:
        js = await _lastfm_api_get(
            "track.getInfo",
            {"artist": a, "track": t, "username": user, "autocorrect": "1"},
            require_auth=False,
        )
        tr = js.get("track") if isinstance(js, dict) else None
        if not isinstance(tr, dict):
            return None
        val = tr.get("userloved")
        # Last.fm commonly returns "1" / "0" here.
        if val is None:
            return None
        try:
            return str(val).strip() == "1"
        except Exception:
            return None
    except Exception:
        return None


def lastfm_set_loved_local(artist: str, title: str, album: str, loved: bool) -> bool:
    # Store both album-specific and album-blank keys for better matching across sources.
    k = _lastfm_track_key(artist, title, album)
    k2 = _lastfm_track_key(artist, title, "")
    if not k.strip():
        return False
    with _LASTFM_LOVED_LOCK:
        tracks = _LASTFM_LOVED.get("tracks") or {}
        if loved:
            tracks[k] = 1
            tracks[k2] = 1
        else:
            tracks.pop(k, None)
            tracks.pop(k2, None)
        _LASTFM_LOVED["tracks"] = tracks
    _lastfm_loved_save()
    return True


async def lastfm_love_track(artist: str, title: str) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return False
    await _lastfm_api_post("track.love", {"artist": artist, "track": title}, require_auth=True)
    return True


async def lastfm_unlove_track(artist: str, title: str) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return False
    await _lastfm_api_post("track.unlove", {"artist": artist, "track": title}, require_auth=True)
    return True


async def lastfm_update_now_playing(artist: str, title: str, album: str = "", duration: Optional[int] = None) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    album = (album or "").strip()
    if not artist or not title:
        return False
    params: Dict[str, Any] = {"artist": artist, "track": title}
    if album:
        params["album"] = album
    if duration and int(duration) > 0:
        params["duration"] = str(int(duration))
    await _lastfm_api_post("track.updateNowPlaying", params, require_auth=True)
    return True


async def lastfm_scrobble(artist: str, title: str, album: str = "", duration: Optional[int] = None, start_ts: Optional[int] = None) -> bool:
    artist = (artist or "").strip()
    title = (title or "").strip()
    album = (album or "").strip()
    if not artist or not title:
        return False
    ts = int(start_ts) if start_ts else int(time.time())
    params: Dict[str, Any] = {"artist[0]": artist, "track[0]": title, "timestamp[0]": str(ts)}
    if album:
        params["album[0]"] = album
    if duration and int(duration) > 0:
        params["duration[0]"] = str(int(duration))
    await _lastfm_api_post("track.scrobble", params, require_auth=True)
    return True


def _lastfm_async(fn, *args, **kwargs) -> None:
    if not lastfm_enabled():
        return

    async def _run() -> None:
        try:
            await fn(*args, **kwargs)
        except Exception:
            pass

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_run(), name=f"lastfm:{getattr(fn, '__name__', 'request')}")
    _LASTFM_BACKGROUND_TASKS.add(task)
    task.add_done_callback(_LASTFM_BACKGROUND_TASKS.discard)
