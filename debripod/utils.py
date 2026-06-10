from __future__ import annotations

import hashlib
import os
import re
from typing import Optional

from .media_types import AUDIO_EXTS, PLAYLIST_EXTS, VIDEO_EXTS


def sanitize_filename(name: str) -> str:
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return "download"
    return name[:240]


def sanitize_folder_name(name: str) -> str:
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        return "task"
    if len(name) > 80:
        name = name[:80].rstrip()
    return name


def human_bytes(n: Optional[int]) -> str:
    if n is None or n < 0:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024.0 or u == units[-1]:
            if u == "B":
                return f"{int(f)} {u}"
            return f"{f:.2f} {u}"
        f /= 1024.0
    return f"{int(n)} B"


def human_rate(bps: Optional[int]) -> str:
    if bps is None or bps <= 0:
        return "?"
    return f"{human_bytes(int(bps))}/s"


def sha1_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def is_playlist_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in PLAYLIST_EXTS
