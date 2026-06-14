from __future__ import annotations

from typing import Callable

from flask import jsonify, request

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

    @app.route("/api/lastfm/nowplaying", methods=["POST"])
    def api_lastfm_nowplaying():
        if not lastfm_enabled():
            return jsonify({"ok": False, "disabled": True})
        js = request.get_json(silent=True) or {}
        artist = str(js.get("artist") or "").strip()
        title = str(js.get("title") or "").strip()
        album = str(js.get("album") or "").strip()
        duration = js.get("duration")
        try:
            duration_i = int(float(str(duration))) if duration is not None and str(duration).strip() else None
        except Exception:
            duration_i = None

        if not artist or not title:
            return jsonify({"ok": False, "error": "missing artist or title"})

        _lastfm_async(lastfm_update_now_playing, artist, title, album, duration_i)
        return jsonify({"ok": True})

    @app.route("/api/lastfm/scrobble", methods=["POST"])
    def api_lastfm_scrobble():
        if not lastfm_enabled():
            return jsonify({"ok": False, "disabled": True})
        js = request.get_json(silent=True) or {}
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
            return jsonify({"ok": False, "error": "missing artist or title"})

        _lastfm_async(lastfm_scrobble, artist, title, album, duration_i, start_i)
        return jsonify({"ok": True})

    @app.route("/api/lastfm/status", methods=["GET"])
    def api_lastfm_status():
        return jsonify({"ok": True, "enabled": bool(lastfm_enabled()), "username": lastfm_username()})

    @app.route("/api/lastfm/auth/start", methods=["GET"])
    def api_lastfm_auth_start():
        if not _has_api_credentials():
            return jsonify({"ok": False, "error": "Last.fm API key/secret not configured"}), 400
        try:
            out = lastfm_auth_start()
            return jsonify({"ok": True, "auth_url": out.get("auth_url"), "token": out.get("token")})
        except Exception:
            return jsonify({"ok": False, "error": "Last.fm auth failed"}), 400

    @app.route("/api/lastfm/auth/finish", methods=["POST"])
    def api_lastfm_auth_finish():
        if not _has_api_credentials():
            return jsonify({"ok": False, "error": "Last.fm API key/secret not configured"}), 400
        js = request.get_json(silent=True) or {}
        token = str(js.get("token") or "").strip()
        if not token:
            return jsonify({"ok": False, "error": "missing token"}), 400
        try:
            out = lastfm_auth_finish(token)
            return jsonify({"ok": True, "username": out.get("username")})
        except Exception:
            return jsonify({"ok": False, "error": "Last.fm auth failed"}), 400

    @app.route("/api/lastfm/loved", methods=["GET"])
    def api_lastfm_loved():
        artist = str(request.args.get("artist") or "").strip()
        title = str(request.args.get("title") or "").strip()
        album = str(request.args.get("album") or "").strip()
        if not artist or not title:
            return jsonify({"ok": False, "error": "missing artist or title"}), 400

        local = bool(lastfm_is_loved(artist, title, album))
        if local:
            return jsonify({"ok": True, "loved": True})

        if lastfm_enabled():
            remote = lastfm_remote_is_loved(artist, title)
            if remote is True:
                lastfm_set_loved_local(artist, title, album, True)
                return jsonify({"ok": True, "loved": True})
            if remote is False:
                return jsonify({"ok": True, "loved": False})

        return jsonify({"ok": True, "loved": False})

    @app.route("/api/lastfm/toggle_loved", methods=["POST"])
    def api_lastfm_toggle_loved():
        js = request.get_json(silent=True) or {}
        artist = str(js.get("artist") or "").strip()
        title = str(js.get("title") or "").strip()
        album = str(js.get("album") or "").strip()
        if not artist or not title:
            return jsonify({"ok": False, "error": "missing artist or title"}), 400

        cur = bool(lastfm_is_loved(artist, title, album))
        loved = not cur
        lastfm_set_loved_local(artist, title, album, loved)

        if lastfm_enabled():
            try:
                if loved:
                    lastfm_love_track(artist, title)
                else:
                    lastfm_unlove_track(artist, title)
            except Exception:
                try:
                    app.logger.exception("Last.fm love/unlove failed")
                except Exception:
                    pass
                lastfm_set_loved_local(artist, title, album, cur)
                return jsonify({"ok": False, "error": "Last.fm update failed", "loved": bool(cur)}), 500

        return jsonify({"ok": True, "loved": bool(loved)})
