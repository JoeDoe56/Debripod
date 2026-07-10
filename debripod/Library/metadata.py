from __future__ import annotations

import os
import math
import struct
import threading
import zlib
import hashlib
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from ..paths import art_cache_dir
from ..playback.probe import ffprobe_json, run_cmd
from ..utils import is_audio, is_video, sha1_text
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
PALETTE_ALGORITHM_VERSION = 3
PALETTE_COLOR_COUNT = 16
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
ANALYSIS_SAMPLE_RATE_HZ = 8820
ANALYSIS_BANDS = [60, 120, 250, 500, 1000, 2000, 3600]
DECODER_SETTINGS_HASH = sha1_text(f"pcm_s16le_mono_{ANALYSIS_SAMPLE_RATE_HZ}_goertzel_video_exact_stride_v3_palette16")



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


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(v))):02x}" for v in rgb)


def _linear_channel(v: int) -> float:
    x = max(0.0, min(1.0, float(v) / 255.0))
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    return _linear_channel(rgb[0]) * 0.2126 + _linear_channel(rgb[1]) * 0.7152 + _linear_channel(rgb[2]) * 0.0722


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la = _luminance(a)
    lb = _luminance(b)
    hi = max(la, lb)
    lo = min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mix(rgb: tuple[int, int, int], target: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    p = max(0.0, min(1.0, float(amount)))
    return tuple(int(round(rgb[i] + (target[i] - rgb[i]) * p)) for i in range(3))


def _best_contrast(bg: tuple[int, int, int], palette: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], float]:
    candidates: list[tuple[int, int, int]] = []
    for color in palette:
        candidates.extend([color, _mix(color, (255, 255, 255), 0.42), _mix(color, (255, 255, 255), 0.72), _mix(color, (0, 0, 0), 0.44), _mix(color, (0, 0, 0), 0.72)])
    candidates.extend([(255, 255, 255), (0, 0, 0)])
    best = candidates[0]
    best_score = -1.0
    for color in candidates:
        score = _contrast(bg, color)
        if score > best_score:
            best = color
            best_score = score
    return best, best_score


def _palette_has_color(palette: list[tuple[int, int, int]], color: tuple[int, int, int]) -> bool:
    return any(_palette_distance(existing, color) < 1.5 for existing in palette)


def _best_palette_contrast(bg: tuple[int, int, int], palette: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], float, bool]:
    best: tuple[int, int, int] | None = None
    best_ratio = -1.0
    for color in palette:
        if _palette_distance(bg, color) < 1.5:
            continue
        ratio = _contrast(bg, color)
        if ratio > best_ratio:
            best = color
            best_ratio = ratio
    if best is not None and best_ratio >= 3.0:
        return best, best_ratio, False
    fallback_best = best or (255, 255, 255)
    fallback_ratio = max(0.0, best_ratio)
    for color in ((255, 255, 255), (0, 0, 0)):
        ratio = _contrast(bg, color)
        in_palette = _palette_has_color(palette, color)
        if in_palette and ratio > fallback_ratio:
            fallback_best = color
            fallback_ratio = ratio
            best = color
        elif best_ratio < 3.0 and not in_palette and ratio > fallback_ratio:
            fallback_best = color
            fallback_ratio = ratio
    return fallback_best, fallback_ratio, not _palette_has_color(palette, fallback_best)


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
    contrast_pairs = []
    contrast_map = {}
    fallback_used = False
    for color in palette:
        contrast_rgb, ratio, fallback = _best_palette_contrast(color, palette)
        pair = {"color": _hex(color), "contrast": _hex(contrast_rgb), "contrastRatio": ratio, "fallback": bool(fallback)}
        contrast_pairs.append(pair)
        contrast_map[pair["color"]] = pair
        fallback_used = fallback_used or bool(fallback)
    role_names = ["low", "lowHigh", "lowMid", "mid", "upperMid", "highLow", "high"]
    roles = {}
    for idx, name in enumerate(role_names):
        bg = palette[idx % len(palette)]
        pair = contrast_pairs[idx % len(contrast_pairs)]
        roles[name] = {"color": _hex(bg), "contrast": pair["contrast"], "contrastRatio": pair["contrastRatio"]}
    dark_text, _ = _best_contrast((18, 18, 22), palette)
    light_text, _ = _best_contrast((236, 238, 242), palette)
    selected, _, _ = _best_palette_contrast(palette[0], palette)
    return {
        "version": PALETTE_ALGORITHM_VERSION,
        "colors": [_hex(c) for c in palette],
        "contrastPairs": contrast_pairs,
        "contrastMap": contrast_map,
        "metadata": {
            "paletteColorCount": len(palette),
            "contrastSource": "palette",
            "contrastFallbackUsed": bool(fallback_used),
        },
        "roles": roles,
        "ui": {
            "darkText": _hex(dark_text),
            "lightText": _hex(light_text),
            "clearEngraveA": roles["low"]["contrast"],
            "clearEngraveB": roles["high"]["contrast"],
            "selectedFallbackText": _hex(selected),
            "selectedFallbackPillText": _hex(selected),
            "selectedPillEdge": roles["mid"]["contrast"],
            "wheelText": _hex(selected),
        },
    }


def _extract_palette_from_image(path: str) -> Optional[dict]:
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
            counts: Counter[tuple[int, int, int]] = Counter()
            for r, g, b, a in img.getdata():
                if a < 24:
                    continue
                counts[(int(r), int(g), int(b))] += 1
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


def _analysis_key(abs_path: str) -> str:
    size, mtime_ns = file_identity(abs_path)
    return sha1_text(f"analysis:{os.path.abspath(abs_path)}:{size}:{mtime_ns}:{ANALYSIS_RATE_HZ}:{DECODER_SETTINGS_HASH}:v1")


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
            rms = math.sqrt(sum(s * s for s in floats) / len(floats))
            energy = max(0.0, min(1.0, rms * 3.2))
            energy_avg = energy if not energy_avg else (energy_avg * 0.965 + energy * 0.035)
            beat = max(0.0, min(1.0, (energy - max(0.06, energy_avg * 1.28)) * 3.0))
            frame_values = []
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
            blob.extend(max(0, min(255, v)) for v in frame_values)
            blob.append(int(round(energy * 255)))
            blob.append(int(round(beat * 255)))
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


def _compress_analysis_blob(raw_blob: bytes) -> tuple[bytes, str]:
    stored_blob = raw_blob
    compression = "none"
    try:
        compressed = zlib.compress(raw_blob, level=3)
        if len(compressed) < len(raw_blob) * 0.96:
            stored_blob = compressed
            compression = "zlib"
    except Exception:
        stored_blob = raw_blob
        compression = "none"
    return stored_blob, compression


def _compute_audio_analysis(abs_path: str, key: str, *, root_id: str, rel: str, media_id: str, duration: Optional[float]) -> Optional[dict]:
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
        return None
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(frame_bytes)
            if not chunk:
                break
            if len(chunk) < frame_bytes:
                break
            samples = struct.unpack("<" + "h" * frame_samples, chunk)
            floats = [s / 32768.0 for s in samples]
            rms = math.sqrt(sum(s * s for s in floats) / len(floats))
            energy = max(0.0, min(1.0, rms * 3.2))
            energy_avg = energy if not energy_avg else (energy_avg * 0.965 + energy * 0.035)
            beat = max(0.0, min(1.0, (energy - max(0.06, energy_avg * 1.28)) * 3.0))
            frame_values = []
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
            blob.extend(max(0, min(255, v)) for v in frame_values)
            blob.append(int(round(energy * 255)))
            blob.append(int(round(beat * 255)))
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
    if frame_count <= 0:
        return None
    raw_blob = bytes(blob)
    stored_blob = raw_blob
    compression = "none"
    try:
        compressed = zlib.compress(raw_blob, level=3)
        if len(compressed) < len(raw_blob) * 0.96:
            stored_blob = compressed
            compression = "zlib"
    except Exception:
        stored_blob = raw_blob
        compression = "none"

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
        metadata={"frame_stride": len(ANALYSIS_BANDS) + 2, "raw_bytes": len(raw_blob), "stored_bytes": len(stored_blob), "fields": ["band0", "band1", "band2", "band3", "band4", "band5", "band6", "energy", "beat"]},
    )
    return load_visualizer_analysis(key)


def warm_video_analysis(abs_path: str, *, root_id: str = "", rel: str = "", media_id: str = "", duration: Optional[float] = None) -> Optional[dict]:
    if not is_video(abs_path):
        return None
    audio = warm_video_audio_analysis(abs_path, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
    frames = warm_video_frame_palette_analysis(abs_path, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
    return frames or audio


def warm_video_audio_analysis(abs_path: str, *, root_id: str = "", rel: str = "", media_id: str = "", duration: Optional[float] = None) -> Optional[dict]:
    if not is_video(abs_path):
        return None
    key = _analysis_key(abs_path)
    cached = load_visualizer_analysis(key)
    if cached:
        return cached
    if not ANALYSIS_LOCK.acquire(blocking=False):
        return None
    try:
        return _compute_video_audio_analysis(abs_path, key, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
    finally:
        try:
            ANALYSIS_LOCK.release()
        except Exception:
            pass


def warm_video_frame_palette_analysis(abs_path: str, *, root_id: str = "", rel: str = "", media_id: str = "", duration: Optional[float] = None) -> Optional[dict]:
    if not is_video(abs_path):
        return None
    key = _analysis_key(abs_path)
    cached = load_visualizer_analysis(key)
    cached_meta = cached.get("metadata") if isinstance(cached, dict) else {}
    if cached and isinstance(cached_meta, dict) and not cached_meta.get("video_palette_pending") and cached_meta.get("video_palette_frames"):
        return cached
    if not ANALYSIS_LOCK.acquire(blocking=False):
        return None
    try:
        return _compute_video_frame_palette_analysis(abs_path, key, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
    finally:
        try:
            ANALYSIS_LOCK.release()
        except Exception:
            pass


def _video_stream_dimensions(abs_path: str) -> tuple[int, int, Optional[float]]:
    try:
        js = ffprobe_json(abs_path) or {}
        fmt = js.get("format") if isinstance(js.get("format"), dict) else {}
        duration = None
        try:
            duration = float(fmt.get("duration")) if fmt.get("duration") is not None else None
        except Exception:
            duration = None
        for stream in js.get("streams") or []:
            if not isinstance(stream, dict) or str(stream.get("codec_type") or "").lower() != "video":
                continue
            w = int(float(stream.get("width") or 0))
            h = int(float(stream.get("height") or 0))
            if w > 0 and h > 0:
                return w, h, duration
    except Exception:
        pass
    return 0, 0, None


def _extract_video_palette_frames(abs_path: str) -> tuple[list[list[object]], int, int]:
    import subprocess

    width, height, _duration = _video_stream_dimensions(abs_path)
    if width <= 0 or height <= 0:
        return [], 0, 0
    frame_bytes = width * height * 3
    pixel_count = width * height
    stride = max(1, int(math.sqrt(max(1, pixel_count) / 96.0)))
    args = [
        _ffmpeg_path_value(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        abs_path,
        "-an",
        "-vf",
        f"fps={ANALYSIS_RATE_HZ},format=rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    frames: list[list[object]] = []
    frame_index = 0
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return [], stride, 0
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(frame_bytes)
            if not chunk or len(chunk) < frame_bytes:
                break
            counts: Counter[tuple[int, int, int]] = Counter()
            start = (frame_index % stride) * 3
            step = stride * 3
            for off in range(start, len(chunk) - 2, step):
                counts[(chunk[off], chunk[off + 1], chunk[off + 2])] += 1
            if counts:
                palette_obj = _palette_object(_palette_from_counts(counts))
                colors = list(palette_obj.get("colors") or [])
                frame_meta = {
                    "contrastPairs": palette_obj.get("contrastPairs") or [],
                    "contrastMap": palette_obj.get("contrastMap") or {},
                    "metadata": palette_obj.get("metadata") or {},
                }
                if not frames or list(frames[-1][1] or []) != colors:
                    frames.append([frame_index, colors, frame_meta])
            frame_index += 1
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        try:
            proc.stdout.close() if proc.stdout else None
        except Exception:
            pass
    return frames, stride, frame_index


def _idle_video_feature_blob(frame_count: int) -> bytes:
    count = max(1, int(frame_count or 0))
    frame = bytes([0, 0, 0, 0, 0, 0, 0, 18, 0])
    return frame * count


def _video_analysis_metadata(
    *,
    raw_bytes: int,
    stored_bytes: int,
    audio_source: str,
    palette_frames: Optional[list[list[object]]] = None,
    palette_stride: int = 0,
    palette_pending: bool = True,
) -> dict:
    metadata = {
        "media_kind": "video",
        "frame_stride": len(ANALYSIS_BANDS) + 2,
        "raw_bytes": int(raw_bytes or 0),
        "stored_bytes": int(stored_bytes or 0),
        "fields": ["band0", "band1", "band2", "band3", "band4", "band5", "band6", "energy", "beat"],
        "video_palette_frame_stride": int(palette_stride or 0),
        "video_palette_encoding": "frame-indexed-exact-hex-v1",
        "video_palette_colors_per_frame": PALETTE_COLOR_COUNT,
        "video_palette_frames": palette_frames if isinstance(palette_frames, list) else [],
        "palette_source": "server",
        "audio_source": str(audio_source or ""),
    }
    if palette_pending:
        metadata["video_palette_pending"] = True
    return metadata


def _compute_video_audio_analysis(abs_path: str, key: str, *, root_id: str, rel: str, media_id: str, duration: Optional[float]) -> Optional[dict]:
    raw_blob, audio_frames = _decode_audio_feature_blob(abs_path)
    _, _, probed_duration = _video_stream_dimensions(abs_path)
    duration_value = duration if duration is not None else probed_duration
    audio_source = "decoded"
    frame_count = audio_frames
    if frame_count <= 0 or not raw_blob:
        audio_source = "idle"
        if duration_value and duration_value > 0:
            frame_count = max(1, int(float(duration_value) * ANALYSIS_RATE_HZ))
        else:
            frame_count = 1
        raw_blob = _idle_video_feature_blob(frame_count)
    stored_blob, compression = _compress_analysis_blob(raw_blob)
    save_visualizer_analysis(
        key,
        media_id=media_id,
        root_id=root_id,
        rel=rel,
        abs_path=abs_path,
        duration=duration_value,
        analysis_rate_hz=ANALYSIS_RATE_HZ,
        band_count=len(ANALYSIS_BANDS),
        frame_count=frame_count,
        feature_blob=stored_blob,
        compression=compression,
        decoder_settings_hash=DECODER_SETTINGS_HASH,
        metadata=_video_analysis_metadata(
            raw_bytes=len(raw_blob),
            stored_bytes=len(stored_blob),
            audio_source=audio_source,
            palette_pending=True,
        ),
    )
    return load_visualizer_analysis(key)


def _compute_video_frame_palette_analysis(abs_path: str, key: str, *, root_id: str, rel: str, media_id: str, duration: Optional[float]) -> Optional[dict]:
    cached = load_visualizer_analysis(key)
    cached_meta = cached.get("metadata") if isinstance(cached, dict) else {}
    _, _, probed_duration = _video_stream_dimensions(abs_path)
    duration_value = duration if duration is not None else probed_duration
    palette_frames, palette_stride, decoded_video_frames = _extract_video_palette_frames(abs_path)
    if cached:
        stored_blob = bytes(cached.get("feature_blob") or b"")
        compression = str(cached.get("compression") or "none")
        frame_count = int(cached.get("frame_count") or 0)
        raw_bytes = int(cached_meta.get("raw_bytes") or 0) if isinstance(cached_meta, dict) else 0
        audio_source = str(cached_meta.get("audio_source") or "decoded") if isinstance(cached_meta, dict) else "decoded"
    else:
        stored_blob = b""
        compression = "none"
        frame_count = 0
        raw_bytes = 0
        audio_source = "idle"
    if frame_count <= 0:
        if decoded_video_frames > 0:
            frame_count = decoded_video_frames
        elif duration_value and duration_value > 0:
            frame_count = max(1, int(float(duration_value) * ANALYSIS_RATE_HZ))
        else:
            frame_count = 1
    if not stored_blob:
        raw_blob = _idle_video_feature_blob(frame_count)
        raw_bytes = len(raw_blob)
        stored_blob, compression = _compress_analysis_blob(raw_blob)
    if frame_count <= 0 or not stored_blob:
        return None
    save_visualizer_analysis(
        key,
        media_id=media_id,
        root_id=root_id,
        rel=rel,
        abs_path=abs_path,
        duration=duration_value,
        analysis_rate_hz=ANALYSIS_RATE_HZ,
        band_count=len(ANALYSIS_BANDS),
        frame_count=frame_count,
        feature_blob=stored_blob,
        compression=compression,
        decoder_settings_hash=DECODER_SETTINGS_HASH,
        metadata=_video_analysis_metadata(
            raw_bytes=raw_bytes,
            stored_bytes=len(stored_blob),
            audio_source=audio_source,
            palette_frames=palette_frames,
            palette_stride=palette_stride,
            palette_pending=False,
        ),
    )
    return load_visualizer_analysis(key)


def _compute_video_analysis(abs_path: str, key: str, *, root_id: str, rel: str, media_id: str, duration: Optional[float]) -> Optional[dict]:
    audio = _compute_video_audio_analysis(abs_path, key, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
    frames = _compute_video_frame_palette_analysis(abs_path, key, root_id=root_id, rel=rel, media_id=media_id, duration=duration)
    return frames or audio
