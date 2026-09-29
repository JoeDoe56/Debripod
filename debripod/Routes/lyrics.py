"""Read-only LRCLIB lookup through the application's shared HTTP transport."""
from __future__ import annotations

import asyncio
import math

from aiohttp import ClientError, web

from ..factory import SERVICES_KEY, json_response
from ..Services.http import HttpStatusError


async def lyrics(request: web.Request) -> web.Response:
    params = {key: request.query.get(key, "").strip()[:300]
              for key in ("track_name", "artist_name", "album_name")}
    if not params["track_name"] or not params["artist_name"]:
        return json_response(ok=True, result="missing", lyrics=None)
    try:
        duration = float(request.query.get("duration", "0"))
        if not math.isfinite(duration) or duration < 0 or duration > 86400:
            raise ValueError
    except ValueError:
        return json_response({"ok": False, "error": "Invalid duration"}, status=400)
    http = request.app[SERVICES_KEY].http
    if http is None:
        return json_response({"ok": False, "error": "Lyrics temporarily unavailable"}, status=503)
    try:
        # An exact lookup includes the recording length; missing metadata uses
        # search with conservative matching to avoid showing another recording.
        if params["album_name"] and duration > 0:
            data = await http.json("GET", "https://lrclib.net/api/get",
                                   params={**params, "duration": round(duration)},
                                   attempts=1, timeout=12, cache_ttl=3600)
        else:
            results = await http.json("GET", "https://lrclib.net/api/search",
                                      params={k: v for k, v in params.items() if v},
                                      attempts=1, timeout=12, cache_ttl=3600)
            def matches(row):
                return (isinstance(row, dict)
                        and str(row.get("trackName", "")).casefold() == params["track_name"].casefold()
                        and str(row.get("artistName", "")).casefold() == params["artist_name"].casefold()
                        and (duration <= 0 or abs(float(row.get("duration") or 0) - duration) <= 2))
            candidates = [r for r in results if matches(r)] if isinstance(results, list) else []
            candidates.sort(key=lambda r: not bool(r.get("syncedLyrics")))
            data = candidates[0] if candidates else None
        if not isinstance(data, dict):
            return json_response(ok=True, lyrics=None, result="missing")
        payload = {key: data.get(key) for key in ("instrumental", "plainLyrics", "syncedLyrics")}
        return json_response(ok=True, lyrics=payload)
    except HttpStatusError as exc:
        if exc.status == 404:
            return json_response(ok=True, lyrics=None, result="missing")
        return json_response({"ok": False, "error": "Lyrics temporarily unavailable"}, status=502)
    except (ClientError, asyncio.TimeoutError, ValueError, TypeError):
        return json_response({"ok": False, "error": "Lyrics temporarily unavailable"}, status=502)


def register_lyrics_routes(app: web.Application) -> None:
    app.router.add_get("/api/lyrics", lyrics)
