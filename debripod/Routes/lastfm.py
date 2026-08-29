from __future__ import annotations

import logging
from typing import Callable

from aiohttp import web

from ..factory import json_response

from ..Services.lastfm import (
    _lastfm_async,
    lastfm_auth_finish,
    lastfm_auth_start,
    lastfm_enabled,
    lastfm_is_loved,
    lastfm_love_track,
    lastfm_remote_is_loved,
    lastfm_scrobble,
    lastfm_set_loved_local,
    lastfm_unlove_track,
    lastfm_update_now_playing,
    lastfm_username,
)


def register_lastfm_routes(
    app,
    *,
    api_key_provider: Callable[[], str],
    api_secret_provider: Callable[[], str],
) -> None:
    def _has_api_credentials() -> bool:
        return bool((api_key_provider() or "").strip() and (api_secret_provider() or "").strip())

    async def api_lastfm_nowplaying(request: web.Request):
        if not lastfm_enabled():
            return json_response({"ok": False, "disabled": True})
        js = await request.json()
        artist = str(js.get("artist") or "").strip()
        title = str(js.get("title") or "").strip()
        album = str(js.get("album") or "").strip()
        duration = js.get("duration")
        try:
            duration_i = int(float(str(duration))) if duration is not None and str(duration).strip() else None
        except Exception:
            duration_i = None

        if not artist or not title:
            return json_response({"ok": False, "error": "missing artist or title"})

        _lastfm_async(lastfm_update_now_playing, artist, title, album, duration_i)
        return json_response({"ok": True})

    async def api_lastfm_scrobble(request: web.Request):
        if not lastfm_enabled():
            return json_response({"ok": False, "disabled": True})
        js = await request.json()
        artist = str(js.get("artist") or "").strip()
        title = str(js.get("title") or "").strip()
        album = str(js.get("album") or "").strip()
        duration = js.get("duration")
        start_ts = js.get("start_ts")
        try:
            duration_i = int(float(str(duration))) if duration is not None and str(duration).strip() else None
        except Exception:
            duration_i = None
        try:
            start_i = int(float(str(start_ts))) if start_ts is not None and str(start_ts).strip() else None
        except Exception:
            start_i = None

        if not artist or not title:
            return json_response({"ok": False, "error": "missing artist or title"})

        _lastfm_async(lastfm_scrobble, artist, title, album, duration_i, start_i)
        return json_response({"ok": True})

    async def api_lastfm_status(_request: web.Request):
        return json_response({"ok": True, "enabled": bool(lastfm_enabled()), "username": lastfm_username()})

    async def api_lastfm_auth_start(_request: web.Request):
        if not _has_api_credentials():
            return json_response({"ok": False, "error": "Last.fm API key/secret not configured"}, status=400)
        try:
            out = await lastfm_auth_start()
            return json_response({"ok": True, "auth_url": out.get("auth_url"), "token": out.get("token")})
        except Exception:
            return json_response({"ok": False, "error": "Last.fm auth failed"}, status=400)

    async def api_lastfm_auth_finish(request: web.Request):
        if not _has_api_credentials():
            return json_response({"ok": False, "error": "Last.fm API key/secret not configured"}, status=400)
        js = await request.json()
        token = str(js.get("token") or "").strip()
        if not token:
            return json_response({"ok": False, "error": "missing token"}, status=400)
        try:
            out = await lastfm_auth_finish(token)
            return json_response({"ok": True, "username": out.get("username")})
        except Exception:
            return json_response({"ok": False, "error": "Last.fm auth failed"}, status=400)

    async def api_lastfm_loved(request: web.Request):
        artist = str(request.query.get("artist") or "").strip()
        title = str(request.query.get("title") or "").strip()
        album = str(request.query.get("album") or "").strip()
        if not artist or not title:
            return json_response({"ok": False, "error": "missing artist or title"}, status=400)

        local = bool(lastfm_is_loved(artist, title, album))
        if local:
            return json_response({"ok": True, "loved": True})

        if lastfm_enabled():
            remote = await lastfm_remote_is_loved(artist, title)
            if remote is True:
                lastfm_set_loved_local(artist, title, album, True)
                return json_response({"ok": True, "loved": True})
            if remote is False:
                return json_response({"ok": True, "loved": False})

        return json_response({"ok": True, "loved": False})

    async def api_lastfm_toggle_loved(request: web.Request):
        js = await request.json()
        artist = str(js.get("artist") or "").strip()
        title = str(js.get("title") or "").strip()
        album = str(js.get("album") or "").strip()
        if not artist or not title:
            return json_response({"ok": False, "error": "missing artist or title"}, status=400)

        cur = bool(lastfm_is_loved(artist, title, album))
        loved = not cur
        lastfm_set_loved_local(artist, title, album, loved)

        if lastfm_enabled():
            try:
                if loved:
                    await lastfm_love_track(artist, title)
                else:
                    await lastfm_unlove_track(artist, title)
            except Exception:
                logging.exception("Last.fm love/unlove failed")
                lastfm_set_loved_local(artist, title, album, cur)
                return json_response({"ok": False, "error": "Last.fm update failed", "loved": bool(cur)}, status=500)

        return json_response({"ok": True, "loved": bool(loved)})

    app.router.add_post("/api/lastfm/nowplaying", api_lastfm_nowplaying)
    app.router.add_post("/api/lastfm/scrobble", api_lastfm_scrobble)
    app.router.add_get("/api/lastfm/status", api_lastfm_status)
    app.router.add_get("/api/lastfm/auth/start", api_lastfm_auth_start)
    app.router.add_post("/api/lastfm/auth/finish", api_lastfm_auth_finish)
    app.router.add_get("/api/lastfm/loved", api_lastfm_loved)
    app.router.add_post("/api/lastfm/toggle_loved", api_lastfm_toggle_loved)
