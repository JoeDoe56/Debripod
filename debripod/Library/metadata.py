from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional, Tuple

from ..paths import art_cache_dir
from ..playback.probe import ffprobe_json, run_cmd
from ..utils import is_audio, sha1_text

_ffmpeg_path = "ffmpeg"


def configure_metadata(*, ffmpeg_path_provider) -> None:
    global _ffmpeg_path
    _ffmpeg_path = ffmpeg_path_provider


def _ffmpeg_path_value() -> str:
    return _ffmpeg_path() if callable(_ffmpeg_path) else str(_ffmpeg_path or "ffmpeg")

# Metadata and artwork cache
# =========================
META_CACHE: Dict[str, Tuple[float, dict]] = {}
META_LOCK = threading.Lock()



def file_meta_cached(abs_path: str) -> dict:
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        return {}

    with META_LOCK:
        hit = META_CACHE.get(abs_path)
        if hit and hit[0] == mtime:
            return hit[1]

    meta: dict = {}
    try:
        js = ffprobe_json(abs_path) or {}
        fmt = js.get("format") or {}
        tags = (fmt.get("tags") or {}) if isinstance(fmt, dict) else {}

        streams = js.get("streams") or []
        audio_stream = None
        if isinstance(streams, list):
            for s in streams:
                if not isinstance(s, dict):
                    continue
                if (s.get("codec_type") or "").lower() != "audio":
                    continue
                if audio_stream is None:
                    audio_stream = s
                stags = s.get("tags")
                if isinstance(stags, dict):
                    for k, v in stags.items():
                        if k not in tags:
                            tags[k] = v

        duration = None
        try:
            duration = float(fmt.get("duration")) if fmt.get("duration") is not None else None
        except Exception:
            duration = None

        def pick(keys: List[str]) -> str:
            for k in keys:
                v = tags.get(k)
                if v:
                    return str(v).strip()
            return ""

        title = pick(["title", "TITLE"]) or os.path.splitext(os.path.basename(abs_path))[0]
        album_artist = pick(["album_artist", "ALBUM_ARTIST", "albumartist", "ALBUMARTIST", "AlbumArtist", "album artist", "ALBUM ARTIST"])
        track_artist = pick(["artist", "ARTIST"])
        artist = track_artist or album_artist
        album = pick(["album", "ALBUM"])
        genre = pick(["genre", "GENRE"])
        track = pick(["track", "TRACK"])

        # Technical display for audio (codec, bit depth, sample rate, bitrate)
        codec = ""
        bits = None
        sample_rate = None
        bit_rate = None
        if isinstance(audio_stream, dict):
            codec = str(audio_stream.get("codec_name") or "").strip()
            for k in ["bits_per_raw_sample", "bits_per_sample"]:
                v = audio_stream.get(k)
                try:
                    iv = int(str(v))
                    if iv > 0:
                        bits = iv
                        break
                except Exception:
                    pass
            try:
                sr = audio_stream.get("sample_rate")
                if sr is not None:
                    sample_rate = int(float(str(sr)))
            except Exception:
                sample_rate = None
            try:
                br = audio_stream.get("bit_rate")
                if br is not None:
                    bit_rate = int(float(str(br)))
            except Exception:
                bit_rate = None

        if bit_rate is None:
            try:
                br = fmt.get("bit_rate") if isinstance(fmt, dict) else None
                if br is not None:
                    bit_rate = int(float(str(br)))
            except Exception:
                bit_rate = None

        tech = ""
        if codec:
            tech = codec.upper()

        if bits and sample_rate:
            khz = sample_rate / 1000.0
            if abs(khz - round(khz)) < 0.05:
                khz_s = str(int(round(khz)))
            else:
                khz_s = f"{khz:.1f}".rstrip("0").rstrip(".")
            tech = (tech + " " if tech else "") + f"{bits}/{khz_s}khz"

        if bit_rate and bit_rate > 0:
            kbps = bit_rate / 1000.0
            if abs(kbps - round(kbps)) < 0.05:
                kbps_s = str(int(round(kbps)))
            else:
                kbps_s = f"{kbps:.1f}".rstrip("0").rstrip(".")
            tech = (tech + " " if tech else "") + f"{kbps_s}kbps"

        meta = {
            "title": title,
            "artist": artist,
            "album_artist": album_artist,
            "album": album,
            "genre": genre,
            "track": track,
            "duration": duration,
            "tech": tech,
        }
    except Exception:
        meta = {
            "title": os.path.splitext(os.path.basename(abs_path))[0],
            "artist": "",
            "album_artist": "",
            "album": "",
            "genre": "",
            "track": "",
            "duration": None,
            "tech": "",
        }

    with META_LOCK:
        META_CACHE[abs_path] = (mtime, meta)
    return meta


def art_cache_path(abs_path: str) -> str:
    key = sha1_text(os.path.abspath(abs_path))
    return os.path.join(art_cache_dir(), f"{key}.jpg")



IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
DIR_ART_CACHE: Dict[str, Tuple[float, Optional[str]]] = {}
DIR_ART_LOCK = threading.Lock()


def pick_folder_art(dir_path: str) -> Optional[str]:
    """Pick an image file inside dir_path to use as album art.

    Priority order is cover, folder, front, album, then any other image.
    Result is cached keyed by directory mtime.
    """
    if not dir_path or not os.path.isdir(dir_path):
        return None
    try:
        d_mtime = os.path.getmtime(dir_path)
    except OSError:
        d_mtime = 0.0

    with DIR_ART_LOCK:
        hit = DIR_ART_CACHE.get(dir_path)
        if hit and hit[0] == d_mtime:
            return hit[1]

    try:
        names = os.listdir(dir_path)
    except OSError:
        names = []

    imgs = []
    for n in names:
        if not n or n.startswith("."):
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext in IMAGE_EXTS:
            imgs.append(n)

    if not imgs:
        with DIR_ART_LOCK:
            DIR_ART_CACHE[dir_path] = (d_mtime, None)
        return None

    prio = ["cover", "folder", "front", "album"]

    def score(fn: str) -> Tuple[int, float, str]:
        base = os.path.splitext(fn)[0].lower().strip()
        # Exact matches win, then prefix matches, then alphabetical.
        for i, key in enumerate(prio):
            if base == key:
                return (i, 0.0, fn.lower())
            if base.startswith(key):
                return (i, 1.0, fn.lower())
        return (len(prio) + 1, 0.0, fn.lower())

    imgs.sort(key=score)
    chosen = os.path.join(dir_path, imgs[0])

    with DIR_ART_LOCK:
        DIR_ART_CACHE[dir_path] = (d_mtime, chosen)

    return chosen


def art_for_media_path(abs_path: str) -> Optional[str]:
    """Return a path to a cover image for an audio file or directory.

    Prefers folder image files, falls back to embedded artwork extraction.
    """
    if not abs_path:
        return None
    if os.path.isdir(abs_path):
        return pick_folder_art(abs_path)
    if os.path.isfile(abs_path):
        d = os.path.dirname(abs_path)
        p = pick_folder_art(d)
        if p:
            return p
        # Fallback to embedded art when no folder image exists.
        if is_audio(abs_path):
            return extract_art(abs_path)
    return None


def extract_art(abs_path: str) -> Optional[str]:
    outp = art_cache_path(abs_path)
    try:
        src_m = os.path.getmtime(abs_path)
    except OSError:
        return None

    if os.path.exists(outp):
        try:
            if os.path.getmtime(outp) >= src_m and os.path.getsize(outp) > 0:
                return outp
        except OSError:
            pass

    base_tmp, ext_tmp = os.path.splitext(outp)
    tmp = base_tmp + ".tmp" + ext_tmp
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass

    args = [
        _ffmpeg_path_value(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        abs_path,
        "-an",
        "-vf",
        "scale=400:-1",
        "-frames:v",
        "1",
        tmp,
    ]
    code, _, _ = run_cmd(args)
    if code != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return None

    try:
        os.replace(tmp, outp)
        return outp
    except OSError:
        return None




# =========================
