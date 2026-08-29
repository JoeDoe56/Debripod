from __future__ import annotations

import mimetypes
import os
from aiohttp import web


def pick_mime(path: str) -> str:
    mt, _ = mimetypes.guess_type(path)
    if mt:
        return mt
    ext = os.path.splitext(path)[1].lower()
    if ext == ".mkv":
        return "video/x-matroska"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".m4a":
        return "audio/mp4"
    if ext == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


async def range_response(request: web.Request, file_path: str) -> web.StreamResponse:
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise web.HTTPNotFound()
    response = web.FileResponse(file_path)
    response.content_type = pick_mime(file_path)
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Cache-Control"] = "no-cache"
    return response
