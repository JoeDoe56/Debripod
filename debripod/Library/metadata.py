from __future__ import annotations

import os
import math
import json
import subprocess
import struct
import threading
import zlib
import hashlib
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from ..paths import art_cache_dir, visualizer_art_cache_dir
from ..playback.probe import ffprobe_json, run_cmd
from ..utils import is_audio, sha1_text
from .library_db import load_metadata, load_palette, load_visualizer_analysis, save_metadata, save_palette, save_visualizer_analysis, file_identity

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
ANALYSIS_LOCK = threading.BoundedSemaphore(1)
PALETTE_ALGORITHM_VERSION = 4
PALETTE_COLOR_COUNT = 16
VISUALIZER_ART_ALGORITHM_VERSION = 4
# The field is sampled across the whole viewport after rotation.  A 512px
# field is under-resolved on tall phones and desktop screens, where one source
# texel can cover multiple visible pixels.  Keep the blur in the same visual
# CSS scale while giving the renderer enough source detail.
VISUALIZER_ART_SIZE = 1024
VISUALIZER_ART_BLUR_SIGMA = 40
VISUALIZER_BAND_LUMA_MIN = 0.06
VISUALIZER_BAND_LUMA_MAX = 0.94
VISUALIZER_MIN_LUMA_SPAN = 0.08
DEFAULT_VISUALIZER_PALETTE: list[tuple[int, int, int]] = [
    (10, 132, 255),
    (94, 92, 230),
    (255, 69, 58),
    (48, 209, 88),
    (255, 159, 10),
    (191, 90, 242),
    (0, 199, 190),
    (255, 55, 95),
    (100, 210, 255),
    (255, 214, 10),
    (50, 173, 230),
    (175, 82, 222),
    (52, 199, 89),
    (255, 149, 0),
    (125, 122, 255),
    (90, 200, 250),
]
ANALYSIS_RATE_HZ = 30
ANALYSIS_SAMPLE_RATE_HZ = 16000
ANALYSIS_BANDS = [60, 110, 190, 330, 600, 1050, 1900, 3400, 6200]
ANALYSIS_FRAME_STRIDE = len(ANALYSIS_BANDS) + 2
ANALYSIS_DELTA_ENCODING = "delta-zlib-v1"
DECODER_SETTINGS_HASH = sha1_text(f"pcm_s16le_mono_{ANALYSIS_SAMPLE_RATE_HZ}_goertzel_9band_delta_v4_palette16")



def file_meta_cached(abs_path: str) -> dict:
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        return {}

    with META_LOCK:
        hit = META_CACHE.get(abs_path)
        if hit and hit[0] == mtime:
            return hit[1]

    db_meta = load_metadata(abs_path)
    if db_meta is not None:
        with META_LOCK:
            META_CACHE[abs_path] = (mtime, db_meta)
        return db_meta

    meta: dict = {}
    try:
        js = ffprobe_json(abs_path) or {}
        fmt = js.get("format") or {}
        tags = (fmt.get("tags") or {}) if isinstance(fmt, dict) else {}

        streams = js.get("streams") or []
        audio_stream = None
        video_stream = None
        if isinstance(streams, list):
            for s in streams:
                if not isinstance(s, dict):
                    continue
                if (s.get("codec_type") or "").lower() == "video" and video_stream is None:
                    video_stream = s
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
            "codec": codec,
            "bit_depth": bits,
            "sample_rate": sample_rate,
            "bitrate": bit_rate,
            "container": str(fmt.get("format_name") or "").split(",", 1)[0] if isinstance(fmt, dict) else "",
            "video_codec": str((video_stream or {}).get("codec_name") or ""),
            "audio_codec": str((audio_stream or {}).get("codec_name") or ""),
            "width": int((video_stream or {}).get("width") or 0),
            "height": int((video_stream or {}).get("height") or 0),
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
            "codec": "",
            "bit_depth": None,
            "sample_rate": None,
            "bitrate": None,
            "container": "",
            "video_codec": "",
            "audio_codec": "",
            "width": 0,
            "height": 0,
        }

    with META_LOCK:
        META_CACHE[abs_path] = (mtime, meta)
    try:
        save_metadata(abs_path, meta)
    except Exception:
        pass
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


def _palette_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    dr = float(a[0] - b[0])
    dg = float(a[1] - b[1])
    db = float(a[2] - b[2])
    return math.sqrt(dr * dr + dg * dg + db * db)


def _palette_luma(rgb: tuple[int, int, int]) -> float:
    return (rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114) / 255.0


def _palette_saturation(rgb: tuple[int, int, int]) -> float:
    mx = max(rgb)
    mn = min(rgb)
    return ((mx - mn) / mx) if mx else 0.0


def _near_black_or_white(rgb: tuple[int, int, int]) -> bool:
    mx = max(rgb)
    mn = min(rgb)
    lum = _palette_luma(rgb)
    sat = _palette_saturation(rgb)
    return mx <= 24 or mn >= 235 or (lum <= 0.08 and sat <= 0.22) or (lum >= 0.92 and sat <= 0.18)


def _distinct_palette(colors: list[tuple[int, int, int]], limit: int = PALETTE_COLOR_COUNT) -> list[tuple[int, int, int]]:
    if not colors:
        return []
    selected: list[tuple[int, int, int]] = []
    for min_distance in (38.0, 30.0, 22.0, 14.0, 0.0):
        for color in colors:
            if color in selected:
                continue
            if all(_palette_distance(color, existing) >= min_distance for existing in selected):
                selected.append(color)
                if len(selected) >= limit:
                    return selected
    return selected[:limit]


def _rank_palette_counts(counts: Counter[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    if not counts:
        return []
    total = float(sum(counts.values()) or 1)

    def score(item: tuple[tuple[int, int, int], int]) -> tuple[float, int]:
        rgb, freq = item
        sat = _palette_saturation(rgb)
        lum = _palette_luma(rgb)
        colorfulness = sat * (1.0 - abs(lum - 0.5) * 0.72)
        freq_score = math.log1p(freq) / math.log1p(total)
        useful_penalty = -1.8 if _near_black_or_white(rgb) else 0.0
        return (freq_score * 1.55 + colorfulness * 1.15 + useful_penalty, freq)

    return [rgb for rgb, _freq in sorted(counts.items(), key=score, reverse=True)]


def _palette_from_counts(counts: Counter[tuple[int, int, int]], limit: int = PALETTE_COLOR_COUNT) -> list[tuple[int, int, int]]:
    ranked = _rank_palette_counts(counts)
    useful = [rgb for rgb in ranked if not _near_black_or_white(rgb)]
    fallback = [rgb for rgb in ranked if _near_black_or_white(rgb)]
    selected = _distinct_palette(useful, limit)
    if len(selected) < limit:
        selected.extend([rgb for rgb in _distinct_palette(fallback, limit) if rgb not in selected][: max(0, limit - len(selected))])
    if len(selected) < limit:
        selected.extend([rgb for rgb in ranked if rgb not in selected][: max(0, limit - len(selected))])
    return selected[:limit]


def _palette_object(colors: list[tuple[int, int, int]]) -> dict:
    palette = _distinct_palette(colors, PALETTE_COLOR_COUNT) or DEFAULT_VISUALIZER_PALETTE[:PALETTE_COLOR_COUNT]
    palette = palette[:PALETTE_COLOR_COUNT]
    return {"version": PALETTE_ALGORITHM_VERSION, "colors": [list(color) for color in palette]}


def _extract_palette_from_image(path: str) -> Optional[dict]:
    try:
        proc = subprocess.run(
            [
                _ffmpeg_path_value(),
                "-v",
                "error",
                "-i",
                path,
                "-vf",
                "scale=48:48:force_original_aspect_ratio=decrease",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        raw = proc.stdout
        counts: Counter[tuple[int, int, int]] = Counter(
            (raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)
        )
        if not counts:
            return None
        return _palette_object(_palette_from_counts(counts))
    except Exception:
        return None


def _file_sha1(path: str) -> str:
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _normalized_identity_part(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def art_identity_for_media(abs_path: str, *, root_id: str = "", rel: str = "", meta: Optional[dict] = None) -> Optional[dict[str, Any]]:
    art = art_for_media_path(abs_path)
    if not art:
        return None
    art_abs = os.path.abspath(art)
    digest = _file_sha1(art_abs)
    size, mtime_ns = file_identity(art)
    source_kind = "embedded-art" if os.path.abspath(art_abs).startswith(os.path.abspath(art_cache_dir())) else "folder-art"
    if digest:
        identity = f"art-sha1:{digest}:v{PALETTE_ALGORITHM_VERSION}"
    else:
        meta_obj = meta if isinstance(meta, dict) else file_meta_cached(abs_path)
        album_artist = ""
        album = ""
        if isinstance(meta_obj, dict):
            album_artist = str(meta_obj.get("album_artist") or meta_obj.get("artist") or "")
            album = str(meta_obj.get("album") or "")
        fallback = "|".join(
            [
                str(root_id or ""),
                _normalized_identity_part(album_artist),
                _normalized_identity_part(album),
                _normalized_identity_part(os.path.relpath(art_abs, os.path.dirname(os.path.abspath(abs_path))) if os.path.isabs(art_abs) else art_abs),
                source_kind,
            ]
        )
        identity = f"art-fallback:{sha1_text(fallback)}:v{PALETTE_ALGORITHM_VERSION}"
    return {
        "art_identity": identity,
        "cache_key": identity,
        "art_path": art_abs,
        "source_kind": source_kind,
        "source_identity": digest or art_abs,
        "size": size,
        "mtime_ns": mtime_ns,
    }


def warm_art_palette(abs_path: str, *, root_id: str = "", rel: str = "", art_info: Optional[dict[str, Any]] = None, linked_count: int = 0) -> Optional[dict]:
    info = art_info if isinstance(art_info, dict) else art_identity_for_media(abs_path, root_id=root_id, rel=rel)
    if not info:
        return None
    art = str(info.get("art_path") or "")
    if not art:
        return None
    key = str(info.get("cache_key") or info.get("art_identity") or "")
    if not key:
        return None
    cached = load_palette(key)
    if cached:
        return cached
    palette = _extract_palette_from_image(art)
    if palette:
        metadata = palette.get("metadata") if isinstance(palette.get("metadata"), dict) else {}
        metadata.update(
            {
                "artIdentity": str(info.get("art_identity") or key),
                "sourceKind": str(info.get("source_kind") or "art"),
                "sourceIdentity": str(info.get("source_identity") or ""),
                "linkedTrackCount": int(linked_count or 0),
            }
        )
        palette["metadata"] = metadata
        save_palette(key, palette, source_kind=str(info.get("source_kind") or "art"), source_identity=str(info.get("source_identity") or os.path.abspath(art)), root_id=root_id, rel=rel)
    return palette


# Extreme-blur artwork fields are deliberately stored as files rather than SQLite
# records.  They are derived from album art, inexpensive to rebuild, and shared by
# every track whose artwork hash is the same.
_VISUALIZER_ART_LOCKS: Dict[str, threading.Lock] = {}
_VISUALIZER_ART_LOCKS_GUARD = threading.Lock()


def visualizer_art_cache_key(art_identity: str) -> str:
    return sha1_text(f"visualizer-art:{str(art_identity or '')}:v{VISUALIZER_ART_ALGORITHM_VERSION}")


def visualizer_art_cache_paths(art_identity: str) -> tuple[str, str]:
    key = visualizer_art_cache_key(art_identity)
    directory = visualizer_art_cache_dir()
    return os.path.join(directory, f"{key}.png"), os.path.join(directory, f"{key}.json")


def _visualizer_art_lock(key: str) -> threading.Lock:
    with _VISUALIZER_ART_LOCKS_GUARD:
        return _VISUALIZER_ART_LOCKS.setdefault(key, threading.Lock())


def _clamp_unit(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def normalize_visualizer_art_luma(value: Any, useful_low: Any, useful_high: Any) -> float:
    """Normalize a sampled luma value against cached robust percentiles."""
    low = _clamp_unit(useful_low)
    high = max(low + VISUALIZER_MIN_LUMA_SPAN, _clamp_unit(useful_high))
    return _clamp_unit((_clamp_unit(value) - low) / (high - low))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0.0, min(float(len(ordered) - 1), float(fraction) * (len(ordered) - 1)))
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _robust_visualizer_luma(raw_rgb: bytes) -> Optional[dict[str, float]]:
    raw = bytes(raw_rgb or b"")
    if len(raw) < 3:
        return None
    lumas = [
        _clamp_unit((raw[index] * 0.2126 + raw[index + 1] * 0.7152 + raw[index + 2] * 0.0722) / 255.0)
        for index in range(0, len(raw) - 2, 3)
    ]
    if not lumas:
        return None
    # Black/near-black and white/near-white pixels are framing or clipping,
    # not useful brightness ranges for assigning audio bands.  Keep them in
    # the image, but do not let them define the useful luma interval.
    useful_lumas = [
        value for value in lumas
        if VISUALIZER_BAND_LUMA_MIN < value < VISUALIZER_BAND_LUMA_MAX
    ]
    interval = useful_lumas or lumas
    low = _percentile(interval, 0.03)
    high = _percentile(interval, 0.97)
    # Favor colorful regions over neutral framing. Saturation alone would give
    # nearly black colored noise a large vote; chroma also weights its strength.
    # Analyze the blurred field once, not the changing audio-reactive output.
    colorful: list[tuple[float, float]] = []
    for index, luma in enumerate(lumas):
        channels = raw[index * 3:index * 3 + 3]
        maximum, minimum = max(channels) / 255.0, min(channels) / 255.0
        chroma = maximum - minimum
        saturation = chroma / max(maximum, 0.0001)
        if chroma > 0.04 and saturation > 0.15:
            colorful.append((luma, saturation * saturation * chroma))
    # A stray colored speck should not redefine an otherwise grayscale cover.
    if len(colorful) >= max(8, math.ceil(len(lumas) * 0.02)):
        ordered = sorted(colorful)
        total = sum(weight for _luma, weight in ordered)

        def weighted_percentile(fraction: float) -> float:
            cumulative = 0.0
            for value, weight in ordered:
                cumulative += weight
                if cumulative >= total * fraction:
                    return value
            return ordered[-1][0]

        low = weighted_percentile(0.03)
        high = weighted_percentile(0.97)
    if high < low + VISUALIZER_MIN_LUMA_SPAN:
        high = min(1.0, low + VISUALIZER_MIN_LUMA_SPAN)
        low = max(0.0, high - VISUALIZER_MIN_LUMA_SPAN)
    return {"useful_luma_low": _clamp_unit(low), "useful_luma_high": _clamp_unit(high)}


def _sample_visualizer_art_luma(path: str) -> Optional[dict[str, float]]:
    try:
        proc = subprocess.run(
            [
                _ffmpeg_path_value(), "-v", "error", "-i", path,
                "-vf", "scale=32:32", "-frames:v", "1",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return _robust_visualizer_luma(proc.stdout)
    except Exception:
        return None


def _build_visualizer_art_image(art_path: str, destination: str) -> bool:
    args = [
        _ffmpeg_path_value(), "-y", "-hide_banner", "-loglevel", "error", "-i", art_path,
        "-vf", (
            f"scale={VISUALIZER_ART_SIZE}:{VISUALIZER_ART_SIZE}:force_original_aspect_ratio=increase,"
            f"crop={VISUALIZER_ART_SIZE}:{VISUALIZER_ART_SIZE},gblur=sigma={VISUALIZER_ART_BLUR_SIGMA}:steps=2"
        ),
        # Keep the preblurred field lossless. JPEG quantization contours are
        # amplified by the luma-to-band normalization in the fragment shader.
        "-frames:v", "1", "-c:v", "png", destination,
    ]
    code, _out, _err = run_cmd(args)
    try:
        return code == 0 and os.path.isfile(destination) and os.path.getsize(destination) > 0
    except OSError:
        return False


def _visualizer_art_metadata_from_cache(art_info: dict[str, Any]) -> Optional[dict[str, Any]]:
    identity = str(art_info.get("art_identity") or art_info.get("cache_key") or "")
    if not identity:
        return None
    image_path, metadata_path = visualizer_art_cache_paths(identity)
    try:
        if not os.path.isfile(image_path) or os.path.getsize(image_path) <= 0:
            return None
        with open(metadata_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        algorithm_version = int(data.get("algorithm_version") or 0)
    except (TypeError, ValueError):
        return None
    if algorithm_version != VISUALIZER_ART_ALGORITHM_VERSION:
        return None
    if str(data.get("art_identity") or "") != identity:
        return None
    try:
        low = _clamp_unit(data.get("useful_luma_low"))
        high = _clamp_unit(data.get("useful_luma_high"))
        if high < low + VISUALIZER_MIN_LUMA_SPAN:
            return None
    except Exception:
        return None
    data["cache_key"] = visualizer_art_cache_key(identity)
    data["path"] = image_path
    return data


def load_visualizer_art(abs_path: str, *, root_id: str = "", rel: str = "", art_info: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    info = art_info if isinstance(art_info, dict) else art_identity_for_media(abs_path, root_id=root_id, rel=rel)
    return _visualizer_art_metadata_from_cache(info) if info else None


def warm_visualizer_art(abs_path: str, *, root_id: str = "", rel: str = "", art_info: Optional[dict[str, Any]] = None, linked_count: int = 0) -> Optional[dict[str, Any]]:
    info = art_info if isinstance(art_info, dict) else art_identity_for_media(abs_path, root_id=root_id, rel=rel)
    if not info:
        return None
    identity = str(info.get("art_identity") or info.get("cache_key") or "")
    art_path = str(info.get("art_path") or "")
    if not identity or not art_path:
        return None
    cached = _visualizer_art_metadata_from_cache(info)
    if cached:
        return cached
    key = visualizer_art_cache_key(identity)
    with _visualizer_art_lock(key):
        cached = _visualizer_art_metadata_from_cache(info)
        if cached:
            return cached
        image_path, metadata_path = visualizer_art_cache_paths(identity)
        directory = os.path.dirname(image_path)
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            return None
        token = f".{os.getpid()}.{threading.get_ident()}.tmp"
        temp_image = image_path + token + ".png"
        temp_metadata = metadata_path + token + ".json"
        try:
            if not _build_visualizer_art_image(art_path, temp_image):
                return None
            luma = _sample_visualizer_art_luma(temp_image)
            if not luma:
                return None
            payload: dict[str, Any] = {
                "algorithm_version": VISUALIZER_ART_ALGORITHM_VERSION,
                "art_identity": identity,
                "cache_key": key,
                "source_kind": str(info.get("source_kind") or "art"),
                "source_identity": str(info.get("source_identity") or ""),
                "linked_track_count": int(linked_count or 0),
                "width": VISUALIZER_ART_SIZE,
                "height": VISUALIZER_ART_SIZE,
                **luma,
            }
            with open(temp_metadata, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            os.replace(temp_image, image_path)
            os.replace(temp_metadata, metadata_path)
            payload["path"] = image_path
            return payload
        except (OSError, TypeError, ValueError):
            return None
        finally:
            for path in (temp_image, temp_metadata):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass


def _analysis_key(abs_path: str) -> str:
    size, mtime_ns = file_identity(abs_path)
    return sha1_text(f"analysis:{os.path.abspath(abs_path)}:{size}:{mtime_ns}:{ANALYSIS_RATE_HZ}:{DECODER_SETTINGS_HASH}:v2")


def _audio_feature_frame(floats: list[float], energy_avg: float) -> tuple[bytes, float]:
    if not floats:
        return bytes(ANALYSIS_FRAME_STRIDE), energy_avg
    rms = math.sqrt(sum(sample * sample for sample in floats) / len(floats))
    energy = max(0.0, min(1.0, rms * 3.2))
    smoothed_energy = energy if not energy_avg else (energy_avg * 0.965 + energy * 0.035)
    beat = max(0.0, min(1.0, (energy - max(0.06, smoothed_energy * 1.28)) * 3.0))
    frame_values: list[int] = []
    for freq in ANALYSIS_BANDS:
        coeff = 2.0 * math.cos(2.0 * math.pi * freq / ANALYSIS_SAMPLE_RATE_HZ)
        q0 = q1 = q2 = 0.0
        for sample in floats:
            q0 = coeff * q1 - q2 + sample
            q2 = q1
            q1 = q0
        power = q1 * q1 + q2 * q2 - coeff * q1 * q2
        value = max(0.0, min(1.0, math.sqrt(max(0.0, power)) / len(floats) * 10.0))
        frame_values.append(int(round(value * 255)))
    return bytes(frame_values + [int(round(energy * 255)), int(round(beat * 255))]), smoothed_energy


def _delta_encode_analysis_blob(raw_blob: bytes, frame_stride: int = ANALYSIS_FRAME_STRIDE) -> bytes:
    stride = max(1, int(frame_stride or 0))
    raw = bytes(raw_blob or b"")
    if not raw or len(raw) % stride:
        raise ValueError("Invalid raw analysis payload")
    encoded = bytearray(raw[:stride])
    previous = raw[:stride]
    for offset in range(stride, len(raw), stride):
        frame = raw[offset:offset + stride]
        encoded.extend((frame[index] - previous[index]) & 0xFF for index in range(stride))
        previous = frame
    return bytes(encoded)


def _delta_decode_analysis_blob(delta_blob: bytes, frame_stride: int = ANALYSIS_FRAME_STRIDE) -> bytes:
    stride = max(1, int(frame_stride or 0))
    encoded = bytes(delta_blob or b"")
    if not encoded or len(encoded) % stride:
        raise ValueError("Invalid delta analysis payload")
    decoded = bytearray(encoded[:stride])
    previous = bytearray(encoded[:stride])
    for offset in range(stride, len(encoded), stride):
        frame = encoded[offset:offset + stride]
        restored = bytearray((previous[index] + frame[index]) & 0xFF for index in range(stride))
        decoded.extend(restored)
        previous = restored
    return bytes(decoded)


def _compress_analysis_blob(raw_blob: bytes) -> tuple[bytes, str]:
    delta = _delta_encode_analysis_blob(raw_blob)
    return zlib.compress(delta, level=3), ANALYSIS_DELTA_ENCODING


def _decompress_analysis_blob(stored_blob: bytes, compression: str) -> bytes:
    if str(compression or "") == ANALYSIS_DELTA_ENCODING:
        return _delta_decode_analysis_blob(zlib.decompress(bytes(stored_blob or b"")))
    return bytes(stored_blob or b"")


def _analysis_activity_metadata(raw_blob: bytes) -> dict[str, object]:
    raw = bytes(raw_blob or b"")
    if not raw or len(raw) % ANALYSIS_FRAME_STRIDE:
        return {
            "band_centers_hz": list(ANALYSIS_BANDS),
            "band_activity_p95": [0] * len(ANALYSIS_BANDS),
            "active_bands": [True] * len(ANALYSIS_BANDS),
            "lowest_active_band": 0,
            "highest_active_band": len(ANALYSIS_BANDS) - 1,
        }
    distributions = [[] for _ in ANALYSIS_BANDS]
    for offset in range(0, len(raw), ANALYSIS_FRAME_STRIDE):
        for index in range(len(ANALYSIS_BANDS)):
            distributions[index].append(raw[offset + index])
    p95: list[int] = []
    for values in distributions:
        values.sort()
        p95.append(int(values[min(len(values) - 1, max(0, math.ceil((len(values) - 1) * 0.95)))]) if values else 0)
    strongest = max(p95) if p95 else 0
    threshold = max(12, int(round(strongest * 0.18)))
    active = [value >= threshold for value in p95]
    indices = [index for index, is_active in enumerate(active) if is_active]
    if not indices:
        active = [True] * len(ANALYSIS_BANDS)
        indices = list(range(len(ANALYSIS_BANDS)))
    return {
        "band_centers_hz": list(ANALYSIS_BANDS),
        "band_activity_p95": p95,
        "active_bands": active,
        "lowest_active_band": indices[0],
        "highest_active_band": indices[-1],
    }


def _analysis_metadata(raw_blob: bytes, stored_blob: bytes, *, media_kind: str = "audio") -> dict[str, object]:
    metadata: dict[str, object] = {
        "media_kind": str(media_kind or "audio"),
        "frame_stride": ANALYSIS_FRAME_STRIDE,
        "raw_bytes": len(raw_blob),
        "stored_bytes": len(stored_blob),
        "storage_encoding": ANALYSIS_DELTA_ENCODING,
        "fields": [*(f"band{index}" for index in range(len(ANALYSIS_BANDS))), "energy", "beat"],
    }
    metadata.update(_analysis_activity_metadata(raw_blob))
    return metadata


def warm_audio_analysis(abs_path: str, *, root_id: str = "", rel: str = "", media_id: str = "", duration: Optional[float] = None) -> Optional[dict]:
    if not is_audio(abs_path):
        return None
    key = _analysis_key(abs_path)
    cached = load_visualizer_analysis(key)
    if cached:
        return cached
    if not ANALYSIS_LOCK.acquire(blocking=False):
        return None
    try:
        return _compute_audio_analysis(abs_path, key, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
    finally:
        try:
            ANALYSIS_LOCK.release()
        except Exception:
            pass


def _decode_audio_feature_blob(abs_path: str) -> tuple[bytes, int]:
    import subprocess

    frame_samples = max(1, int(ANALYSIS_SAMPLE_RATE_HZ / ANALYSIS_RATE_HZ))
    frame_bytes = frame_samples * 2
    args = [
        _ffmpeg_path_value(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        abs_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(ANALYSIS_SAMPLE_RATE_HZ),
        "-f",
        "s16le",
        "pipe:1",
    ]
    blob = bytearray()
    energy_avg = 0.0
    frame_count = 0
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return b"", 0
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(frame_bytes)
            if not chunk or len(chunk) < frame_bytes:
                break
            samples = struct.unpack("<" + "h" * frame_samples, chunk)
            floats = [s / 32768.0 for s in samples]
            frame, energy_avg = _audio_feature_frame(floats, energy_avg)
            blob.extend(frame)
            frame_count += 1
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        try:
            proc.stdout.close() if proc.stdout else None
        except Exception:
            pass
    return bytes(blob), frame_count


def _compute_audio_analysis(abs_path: str, key: str, *, root_id: str, rel: str, media_id: str, duration: Optional[float]) -> Optional[dict]:
    raw_blob, frame_count = _decode_audio_feature_blob(abs_path)
    if frame_count <= 0:
        return None
    stored_blob, compression = _compress_analysis_blob(raw_blob)

    save_visualizer_analysis(
        key,
        media_id=media_id,
        root_id=root_id,
        rel=rel,
        abs_path=abs_path,
        duration=duration,
        analysis_rate_hz=ANALYSIS_RATE_HZ,
        band_count=len(ANALYSIS_BANDS),
        frame_count=frame_count,
        feature_blob=stored_blob,
        compression=compression,
        decoder_settings_hash=DECODER_SETTINGS_HASH,
        metadata=_analysis_metadata(raw_blob, stored_blob),
    )
    return load_visualizer_analysis(key)


