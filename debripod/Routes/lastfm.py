from __future__ import annotations

import logging

from aiohttp import web

from ..factory import json_response
from ..user_runtime import user_runtime_for


def register_lastfm_routes(app) -> None:
    def _client(request: web.Request):
        return user_runtime_for(request).lastfm

    async def api_lastfm_nowplaying(request: web.Request):
        client = _client(request)
        if not client or not client.enabled():
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

        client.spawn(client.update_now_playing, artist, title, album, duration_i)
        return json_response({"ok": True})

    async def api_lastfm_scrobble(request: web.Request):
        client = _client(request)
        if not client or not client.enabled():
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

        client.spawn(client.scrobble, artist, title, album, duration_i, start_i)
        return json_response({"ok": True})

    async def api_lastfm_status(request: web.Request):
        client = _client(request)
        return json_response({"ok": True, "enabled": bool(client and client.enabled()), "username": str(getattr(client, "session_username", "") or "")})

    async def api_lastfm_auth_start(request: web.Request):
        client = _client(request)
        if not client or not client.has_api_credentials():
            return json_response({"ok": False, "error": "Last.fm API key/secret not configured"}, status=400)
        try:
            out = await client.auth_start()
            return json_response({"ok": True, "auth_url": out.get("auth_url"), "token": out.get("token")})
        except Exception:
            return json_response({"ok": False, "error": "Last.fm auth failed"}, status=400)

    async def api_lastfm_auth_finish(request: web.Request):
        client = _client(request)
        if not client or not client.has_api_credentials():
            return json_response({"ok": False, "error": "Last.fm API key/secret not configured"}, status=400)
        js = await request.json()
        token = str(js.get("token") or "").strip()
        if not token:
            return json_response({"ok": False, "error": "missing token"}, status=400)
        try:
            out = await client.auth_finish(token)
            return json_response({"ok": True, "username": out.get("username")})
        except Exception:
            return json_response({"ok": False, "error": "Last.fm auth failed"}, status=400)

    async def api_lastfm_loved(request: web.Request):
        artist = str(request.query.get("artist") or "").strip()
        title = str(request.query.get("title") or "").strip()
        album = str(request.query.get("album") or "").strip()
        if not artist or not title:
            return json_response({"ok": False, "error": "missing artist or title"}, status=400)

        client = _client(request)
        local = bool(client and client.is_loved(artist, title, album))
        if local:
            return json_response({"ok": True, "loved": True})

        if client and client.enabled():
            remote = await client.remote_is_loved(artist, title)
            if remote is True:
                client.set_loved_local(artist, title, album, True)
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

        client = _client(request)
        if client is None:
            return json_response({"ok": False, "error": "Last.fm is unavailable"}, status=503)
        cur = bool(client.is_loved(artist, title, album))
        loved = not cur
        client.set_loved_local(artist, title, album, loved)

        if client.enabled():
            try:
                if loved:
                    await client.love_track(artist, title)
                else:
                    await client.unlove_track(artist, title)
            except Exception:
                logging.exception("Last.fm love/unlove failed")
                client.set_loved_local(artist, title, album, cur)
                return json_response({"ok": False, "error": "Last.fm update failed", "loved": bool(cur)}, status=500)

        return json_response({"ok": True, "loved": bool(loved)})

    app.router.add_post("/api/lastfm/nowplaying", api_lastfm_nowplaying)
    app.router.add_post("/api/lastfm/scrobble", api_lastfm_scrobble)
    app.router.add_get("/api/lastfm/status", api_lastfm_status)
    app.router.add_get("/api/lastfm/auth/start", api_lastfm_auth_start)
    app.router.add_post("/api/lastfm/auth/finish", api_lastfm_auth_finish)
    app.router.add_get("/api/lastfm/loved", api_lastfm_loved)
    app.router.add_post("/api/lastfm/toggle_loved", api_lastfm_toggle_loved)
