from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

ICON_VERSION = "dev"
ASSET_VERSION = "dev"
PROJECT_ICON_DIR = Path(__file__).resolve().parents[2] / "icons"
STATIC_ICON_DIR = Path(__file__).resolve().parents[1] / "static" / "icons"
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

SVG_ICON_NAMES = frozenset(
    {
        "button2_seek-mode_liked-active.svg",
        "button2_seek-mode_liked-inactive.svg",
        "button3_next-track.svg",
        "button3_seek-mode_skip-forward.svg",
        "button4_media-paused.svg",
        "button4_media-playing.svg",
        "button5_previous-track.svg",
        "button5_seek-mode_skip-back.svg",
        "debripod-app-icon.svg",
        "shuffleactivefull-fixed.svg",
        "shuffleinactivefull-fixed.svg",
    }
)
STATIC_ICON_NAMES = frozenset(
    {"favicon.ico", "icon-16.png", "icon-32.png", "icon-180.png", "icon-192.png", "icon-512.png"}
)


def configure_asset_versions(*, asset_version: str | None = None, icon_version: str | None = None) -> None:
    global ASSET_VERSION, ICON_VERSION
    if asset_version:
        ASSET_VERSION = str(asset_version)
    if icon_version:
        ICON_VERSION = str(icon_version)


def _immutable_file(directory: Path, filename: str, *, mimetype: str | None = None):
    path = directory / filename
    if not path.is_file():
        raise web.HTTPNotFound()
    response = web.FileResponse(path)
    if mimetype:
        response.content_type = mimetype
    response.headers["Cache-Control"] = IMMUTABLE_CACHE
    return response


def register_icon_routes(app) -> None:
    async def icon_asset(request: web.Request):
        filename = request.match_info["filename"]
        if filename in SVG_ICON_NAMES and (PROJECT_ICON_DIR / filename).is_file():
            return _immutable_file(PROJECT_ICON_DIR, filename, mimetype="image/svg+xml")
        if filename in STATIC_ICON_NAMES and (STATIC_ICON_DIR / filename).is_file():
            return _immutable_file(STATIC_ICON_DIR, filename)
        raise web.HTTPNotFound()

    async def favicon_ico(_request: web.Request):
        return _immutable_file(STATIC_ICON_DIR, "favicon.ico", mimetype="image/x-icon")

    async def apple_touch_icon(_request: web.Request):
        return _immutable_file(STATIC_ICON_DIR, "icon-180.png", mimetype="image/png")

    async def apple_touch_icon_precomposed(_request: web.Request):
        return _immutable_file(STATIC_ICON_DIR, "icon-180.png", mimetype="image/png")

    async def icon_192(_request: web.Request):
        return _immutable_file(STATIC_ICON_DIR, "icon-192.png", mimetype="image/png")

    async def icon_512(_request: web.Request):
        return _immutable_file(STATIC_ICON_DIR, "icon-512.png", mimetype="image/png")

    async def site_webmanifest(_request: web.Request):
        manifest = {
            "name": "DebriPod",
            "short_name": "DebriPod",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0b0b0c",
            "theme_color": "#0b0b0c",
            "icons": [
                {
                    "src": f"/icon-192.png?v={ICON_VERSION}",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": f"/icon-512.png?v={ICON_VERSION}",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        }
        return web.Response(
            text=json.dumps(manifest),
            content_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    app.router.add_get("/icons/{filename:.*}", icon_asset)
    app.router.add_get("/favicon.ico", favicon_ico)
    app.router.add_get("/apple-touch-icon.png", apple_touch_icon)
    app.router.add_get("/apple-touch-icon-precomposed.png", apple_touch_icon_precomposed)
    app.router.add_get("/icon-192.png", icon_192)
    app.router.add_get("/icon-512.png", icon_512)
    app.router.add_get("/site.webmanifest", site_webmanifest)
