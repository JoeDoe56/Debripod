from __future__ import annotations

import mimetypes
import os
import re

from flask import Response, abort, request


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


def range_response(file_path: str) -> Response:
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        abort(404)

    file_size = os.path.getsize(file_path)
    mime = pick_mime(file_path)
    range_header = request.headers.get("Range", "")
    method = request.method.upper()

    if not range_header:
        headers = {"Content-Length": str(file_size), "Accept-Ranges": "bytes"}
        if method == "HEAD":
            return Response(status=200, headers=headers, mimetype=mime)

        def gen():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return Response(gen(), status=200, headers=headers, mimetype=mime)

    m = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        headers = {"Content-Length": str(file_size), "Accept-Ranges": "bytes"}
        if method == "HEAD":
            return Response(status=200, headers=headers, mimetype=mime)
        return Response(open(file_path, "rb"), status=200, headers=headers, mimetype=mime)

    start = int(m.group(1))
    end_s = m.group(2)
    end = int(end_s) if end_s and end_s.isdigit() else file_size - 1
    start = max(0, min(start, file_size - 1))
    end = max(start, min(end, file_size - 1))
    length = end - start + 1

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "no-cache",
    }

    if method == "HEAD":
        return Response(status=206, headers=headers, mimetype=mime)

    def gen():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return Response(gen(), status=206, headers=headers, mimetype=mime)
