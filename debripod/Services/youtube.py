from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from ..Library.search_cache import _SEARCH_DISK_LOCK, _disk_cache_get, _disk_cache_set, _make_search_cache_key
from ..paths import cache_dir
from ..playback.probe import ffprobe_json, run_cmd
from ..utils import human_bytes, sha1_text
from .http import HttpClient

_ytdlp_cmd_provider: Callable[[], str] = lambda: ""
_youtube_download_dir_provider: Callable[[], str] = lambda: ""
_download_dir_provider: Callable[[], str] = lambda: ""
_stream_cache_subdir_provider: Callable[[], str] = lambda: ""
_web_base_provider: Callable[[], str] = lambda: ""
_search_limit_provider: Callable[[], int] = lambda: 0
_channel_browse_limit_provider: Callable[[], int] = lambda: 0
_request_headers_provider: Callable[[], dict] = lambda: {}
_timeout_provider: Callable[[], int] = lambda: 0
_ffmpeg_path_provider: Callable[[], str] = lambda: ""
_YOUTUBE_HTTP: HttpClient | None = None


def configure_youtube(
    *,
    ytdlp_cmd_provider: Callable[[], str],
    youtube_download_dir_provider: Callable[[], str],
    download_dir_provider: Callable[[], str],
    stream_cache_subdir_provider: Callable[[], str],
    web_base_provider: Callable[[], str],
    search_limit_provider: Callable[[], int],
    channel_browse_limit_provider: Callable[[], int],
    request_headers_provider: Callable[[], dict],
    timeout_provider: Callable[[], int],
    ffmpeg_path_provider: Callable[[], str],
) -> None:
    global _ytdlp_cmd_provider, _youtube_download_dir_provider, _download_dir_provider
    global _stream_cache_subdir_provider, _web_base_provider, _search_limit_provider
    global _channel_browse_limit_provider, _request_headers_provider, _timeout_provider
    global _ffmpeg_path_provider
    _ytdlp_cmd_provider = ytdlp_cmd_provider
    _youtube_download_dir_provider = youtube_download_dir_provider
    _download_dir_provider = download_dir_provider
    _stream_cache_subdir_provider = stream_cache_subdir_provider
    _web_base_provider = web_base_provider
    _search_limit_provider = search_limit_provider
    _channel_browse_limit_provider = channel_browse_limit_provider
    _request_headers_provider = request_headers_provider
    _timeout_provider = timeout_provider
    _ffmpeg_path_provider = ffmpeg_path_provider


def configure_youtube_http(http: HttpClient) -> None:
    global _YOUTUBE_HTTP
    _YOUTUBE_HTTP = http


def _youtube_http() -> HttpClient:
    if _YOUTUBE_HTTP is None:
        raise RuntimeError("YouTube HTTP transport is not initialized")
    return _YOUTUBE_HTTP


def _youtube_web_base() -> str:
    return (_web_base_provider() or "").rstrip("/")


def _youtube_watch_url(video_id: str) -> str:
    vid = str(video_id or "").strip()
    return f"{_youtube_web_base()}/watch?v={vid}" if vid else ""


def _youtube_channel_url(channel_id: str = "", handle: str = "", browse_url: str = "") -> str:
    base = _youtube_web_base()
    if browse_url:
        if browse_url.startswith("http://") or browse_url.startswith("https://"):
            return browse_url
        return base + browse_url
    h = str(handle or "").strip()
    cid = str(channel_id or "").strip()
    if h:
        return base + ("/" + h.lstrip("@") if h.startswith("/") else ("/" + h if h.startswith("@") else "/@" + h))
    if cid:
        return f"{base}/channel/{cid}"
    return base












def _youtube_channel_feed_url(channel_id: str) -> str:
    return f'{_youtube_web_base()}/feeds/videos.xml?channel_id={quote(str(channel_id or "").strip())}'


def _youtube_format_upload_date(raw: Any) -> str:
    s = str(raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _run_ytdlp(args: List[str]) -> Tuple[int, str, str]:
    return run_cmd([_ytdlp_cmd_provider()] + list(args or []))


def _youtube_channel_entries_from_ytdlp(channel_id: str, limit: Optional[int] = None) -> List[dict]:
    cid = str(channel_id or "").strip()
    if not cid:
        return []
    args = ["-J", "--flat-playlist", "--playlist-items", "1:2147483647", _youtube_channel_url(cid) + "/videos"]
    code, out, err = _run_ytdlp(args)
    if code != 0:
        raise RuntimeError((err or out or "yt-dlp channel browse failed").strip())
    try:
        data = json.loads(out or "{}")
    except Exception:
        raise RuntimeError("yt-dlp channel browse returned invalid json")
    entries = data.get("entries")
    if not isinstance(entries, list):
        return []
    channel_name = str(data.get("channel") or data.get("uploader") or data.get("title") or "").strip()
    channel_url = str(data.get("channel_url") or _youtube_channel_url(cid)).strip()
    out_items: List[dict] = []
    max_items = int(limit if limit is not None else _channel_browse_limit_provider() or 0)
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        vid = str(ent.get("id") or ent.get("video_id") or "").strip()
        if not vid:
            url = str(ent.get("url") or "").strip()
            if "watch?v=" in url:
                vid = url.split("watch?v=", 1)[1].split("&", 1)[0].strip()
        if not vid:
            continue
        title = str(ent.get("title") or "").strip() or "YouTube video"
        published = _youtube_format_upload_date(ent.get("upload_date") or ent.get("release_date") or ent.get("timestamp") or "")
        duration = ent.get("duration")
        length = ""
        try:
            if duration is not None:
                secs = int(float(duration))
                h = secs // 3600
                m = (secs % 3600) // 60
                s = secs % 60
                length = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        except Exception:
            length = str(ent.get("duration_string") or "").strip()
        if not length:
            length = str(ent.get("duration_string") or "").strip()
        view_count = ""
        try:
            vc = ent.get("view_count")
            if vc is not None and str(vc).strip() != "":
                view_count = f"{int(vc):,} views"
        except Exception:
            view_count = str(ent.get("view_count") or "").strip()
        thumb = ""
        thumbs = ent.get("thumbnails")
        if isinstance(thumbs, list) and thumbs:
            last = thumbs[-1] or {}
            if isinstance(last, dict):
                thumb = str(last.get("url") or "").strip()
        if not thumb:
            thumb = str(ent.get("thumbnail") or "").strip()
        chan = str(ent.get("channel") or ent.get("uploader") or channel_name).strip()
        chan_id = str(ent.get("channel_id") or cid).strip() or cid
        out_items.append({
            "video_id": vid,
            "url": _youtube_watch_url(vid),
            "title": title,
            "channel": chan,
            "channel_id": chan_id,
            "channel_url": str(ent.get("channel_url") or channel_url or _youtube_channel_url(chan_id)).strip(),
            "browse_url": "",
            "handle": "",
            "length": length,
            "published": published,
            "view_count": view_count,
            "thumbnail": thumb,
            "description": str(ent.get("description") or "").strip(),
        })
        if max_items > 0 and len(out_items) >= max_items:
            break
    return out_items


async def _youtube_channel_entries_from_feed(channel_id: str, limit: Optional[int] = None) -> List[dict]:
    cid = str(channel_id or "").strip()
    if not cid:
        return []
    body = await _youtube_http().text(
        "GET",
        _youtube_channel_feed_url(cid),
        headers=_request_headers_provider(),
        timeout=_timeout_provider(),
    )
    root = ET.fromstring(body)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    out: List[dict] = []
    max_items = int(limit if limit is not None else _channel_browse_limit_provider() or 0)
    for entry in root.findall("atom:entry", ns):
        vid = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        author = (entry.findtext("atom:author/atom:name", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        media_group = entry.find("media:group", ns)
        desc = ""
        thumb = ""
        if media_group is not None:
            desc = (media_group.findtext("media:description", default="", namespaces=ns) or "").strip()
            thumb_el = media_group.find("media:thumbnail", ns)
            if thumb_el is not None:
                thumb = str(thumb_el.attrib.get("url") or "").strip()
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "url": _youtube_watch_url(vid),
            "title": title or "YouTube video",
            "channel": author,
            "channel_id": cid,
            "channel_url": _youtube_channel_url(cid),
            "browse_url": "",
            "handle": "",
            "length": "",
            "published": published.replace("T", " ").replace("Z", " UTC"),
            "view_count": "",
            "thumbnail": thumb,
            "description": desc,
        })
        if max_items > 0 and len(out) >= max_items:
            break
    return out


async def youtube_channel_videos(channel_id: str, limit: Optional[int] = None) -> List[dict]:
    try:
        items = await asyncio.to_thread(_youtube_channel_entries_from_ytdlp, channel_id, limit)
        if items:
            return items
    except Exception:
        pass
    return await _youtube_channel_entries_from_feed(channel_id, limit)


def _ytdlp_ffmpeg_location() -> str:
    raw = str(_ffmpeg_path_provider() or "").strip()
    if not raw:
        return ""
    try:
        if os.path.isdir(raw):
            return raw
        parent = os.path.dirname(raw)
        return parent or raw
    except Exception:
        return raw


def _youtube_download_root() -> str:
    root = str(_youtube_download_dir_provider() or "").strip()
    if root:
        return root
    return str(_download_dir_provider() or "").strip()


def _youtube_stream_cache_dir() -> str:
    out = os.path.join(cache_dir(), "ytdlp")
    os.makedirs(out, exist_ok=True)
    return out


def _yt_selected_output_ext(fmt: dict) -> str:
    media = str(fmt.get("media") or "").strip().lower()
    ext = str(fmt.get("ext") or "").strip().lower()
    if media == "audio":
        if ext in ("m4a", "mp3", "aac", "ogg", "opus", "wav", "flac", "webm"):
            return ext
        return "m4a"
    if ext == "webm":
        return "webm"
    return "mp4"


def _yt_stream_format_selector(fmt: dict) -> str:
    target = str(fmt.get("quality_target") or "").strip().lower()
    if target in {"audio", "audio_only", "audio only"}:
        return "bestaudio/best"
    try:
        target_height = int(target.rstrip("p"))
    except Exception:
        target_height = 0
    if target_height > 0:
        # Resolution is selected before codec so a higher requested target is
        # never silently downgraded merely because another codec is present.
        # AAC is preferred where available for browser compatibility.
        return (f"bestvideo[height<={target_height}]+bestaudio[acodec^=mp4a]/"
                f"bestvideo[height<={target_height}]+bestaudio/"
                f"best[height<={target_height}]/best[height<=?{target_height}]")
    media = str(fmt.get("media") or "").strip().lower()
    if media == "audio":
        return "bestaudio/best"
    return "bestvideo+bestaudio/best"


def ytdlp_format_selectors(fmt: dict) -> List[str]:
    """Retry a different stream combination after download or mux failure."""
    primary = _yt_stream_format_selector(fmt)
    target = str(fmt.get("quality_target") or "").lower()
    if target == "audio" or fmt.get("media") == "audio":
        fallback = "best/bestaudio"
    else:
        try:
            height = int(target.rstrip("p"))
        except (TypeError, ValueError):
            height = 0
        cap = f"[height<={height}]" if height > 0 else ""
        # A progressive stream avoids the failed merge. If unavailable, try
        # alternate audio before repeating the preferred codec combination.
        fallback = f"best{cap}/bestvideo{cap}+bestaudio[acodec!^=mp4a]/bestvideo{cap}+bestaudio"
        if height > 0:
            fallback += f"/best[height<=?{height}]"
    return list(dict.fromkeys([primary, fallback]))


YTDLP_QUALITY_TARGETS = (2160, 1440, 1080, 720, 480, 360)


def _yt_number(raw: Any, default: float = 0.0) -> float:
    """Parse the nullable/nonnumeric values emitted by different extractors."""
    try:
        value = float(raw)
        return value if value == value else default
    except (TypeError, ValueError):
        return default


def _yt_quality_target_rows(info: dict, source_url: str) -> List[dict]:
    """Collapse yt-dlp's unstable format IDs into six user quality targets."""
    formats = [f for f in list(info.get("formats") or []) if isinstance(f, dict)]
    usable = [f for f in formats if str(f.get("ext") or "").lower() not in {"mhtml", "jpg", "jpeg", "png", "webp"}]
    videos = []
    unknown_progressive = []
    audios = []
    for fmt in usable:
        vcodec = str(fmt.get("vcodec") or "").lower()
        acodec = str(fmt.get("acodec") or "").lower()
        if vcodec not in {"", "none"} and _yt_number(fmt.get("height")) > 0:
            videos.append(fmt)
        elif vcodec in {"", "none"} and acodec in {"", "none"} and str(fmt.get("ext") or "").lower() in {"mp4", "webm", "mkv", "mov"}:
            unknown_progressive.append(fmt)
        # Keep combined progressive formats as an Audio Only fallback for
        # extractors that do not expose a separate audio stream.
        if acodec not in {"", "none"}:
            audios.append(fmt)
    rows: List[dict] = []
    used_heights = set()
    for target in YTDLP_QUALITY_TARGETS:
        candidates = [f for f in videos if int(_yt_number(f.get("height"))) == target]
        if not candidates:
            continue
        # Highest resolution at or below target; then prefer AVC and larger
        # bitrate, which keeps the selector stable across extractor changes.
        candidates.sort(key=lambda f: (
            _yt_number(f.get("height")),
            str(f.get("vcodec") or "").lower().startswith(("avc", "h264")),
            _yt_number(f.get("tbr")),
        ), reverse=True)
        chosen = candidates[0]
        height = int(_yt_number(chosen.get("height")))
        if height in used_heights:
            continue
        used_heights.add(height)
        row = _yt_format_row(chosen, source_url, quality_target=f"{target}p")
        # The displayed row is the selected available height. Once a source
        # lacks (for example) 2160p, asking yt-dlp for <=2160 would make the
        # same stream look like a higher target and would duplicate it.
        row["name"] = f"{height}p"
        row["title"] = row["name"]
        row["quality"] = row["name"]
        row["file_id"] = f"quality-{target}p"
        row["duration"] = _yt_number(chosen.get("duration")) or _yt_number(info.get("duration"))
        rows.append(row)
    if not rows and videos:
        # Generic extractors sometimes expose a non-standard height. Keep a
        # bounded Best choice rather than returning an API row the client
        # cannot enqueue as one of the six targets.
        chosen = max(videos, key=lambda f: (_yt_number(f.get("height")), _yt_number(f.get("tbr"))))
        row = _yt_format_row(chosen, source_url, quality_target="best")
        height = int(_yt_number(chosen.get("height")))
        row["name"] = f"{height}p" if height else "Best"
        row["title"] = row["name"]
        row["quality"] = row["name"]
        row["file_id"] = "quality-best"
        row["duration"] = _yt_number(chosen.get("duration")) or _yt_number(info.get("duration"))
        rows.append(row)
    if not videos and unknown_progressive:
        chosen = max(unknown_progressive, key=lambda f: _yt_number(f.get("tbr")))
        row = _yt_format_row(chosen, source_url, quality_target="best")
        row["name"] = "Best"; row["title"] = "Best"; row["quality"] = "Best"; row["file_id"] = "quality-best"
        row["duration"] = _yt_number(chosen.get("duration")) or _yt_number(info.get("duration"))
        rows.append(row)
        audio_row = _yt_format_row(chosen, source_url, quality_target="audio")
        audio_row["media"] = "audio"; audio_row["name"] = "Audio Only"; audio_row["title"] = "Audio Only"; audio_row["quality"] = "Audio Only"; audio_row["file_id"] = "quality-audio"; audio_row["audio_extract"] = True
        audio_row["duration"] = row["duration"]
        rows.append(audio_row)
    if not formats and str(info.get("url") or "").strip():
        chosen = {"ext": str(info.get("ext") or "mp4"), "url": str(info.get("url") or ""), "vcodec": "", "acodec": ""}
        row = _yt_format_row(chosen, source_url, quality_target="best")
        row["name"] = "Best"; row["title"] = "Best"; row["quality"] = "Best"; row["file_id"] = "quality-best"
        row["duration"] = _yt_number(info.get("duration"))
        rows.append(row)
        audio_row = _yt_format_row(chosen, source_url, quality_target="audio")
        audio_row["media"] = "audio"; audio_row["name"] = "Audio Only"; audio_row["title"] = "Audio Only"; audio_row["quality"] = "Audio Only"; audio_row["file_id"] = "quality-audio"; audio_row["audio_extract"] = True
        audio_row["duration"] = _yt_number(info.get("duration"))
        rows.append(audio_row)
    if audios:
        audios.sort(key=lambda f: (
            str(f.get("vcodec") or "").lower() in {"", "none"},
            _yt_number(f.get("abr")),
            _yt_number(f.get("tbr")),
        ), reverse=True)
        row = _yt_format_row(audios[0], source_url, quality_target="audio")
        row["name"] = "Audio Only"; row["title"] = "Audio Only"; row["quality"] = "Audio Only"
        row["file_id"] = "quality-audio"
        row["audio_extract"] = str(audios[0].get("vcodec") or "").lower() not in {"", "none"}
        row["duration"] = _yt_number(audios[0].get("duration")) or _yt_number(info.get("duration"))
        rows.append(row)
    return rows


def _yt_format_row(fmt: dict, source_url: str, *, quality_target: str) -> dict:
    ext = str(fmt.get("ext") or "").strip().lower()
    media = _yt_guess_media(fmt)
    size = 0
    for key in ("filesize", "filesize_approx"):
        try:
            if int(fmt.get(key) or 0) > 0: size = int(fmt[key]); break
        except Exception: pass
    return {
        "file_id": "quality-" + (quality_target or "best").lower().replace(" ", "-"),
        "name": _yt_quality_text(fmt), "title": _yt_quality_text(fmt), "ext": ext,
        "quality": _yt_quality_text(fmt), "quality_target": quality_target,
        "duration": _yt_number(fmt.get("duration")),
        "bitrate": _yt_audio_bitrate_k(fmt),
        "size": size, "size_text": human_bytes(size) if size > 0 else "",
        "source": "youtube", "selectable": True, "media": media,
        "source_url": source_url,
        "fps": int(_yt_number(fmt.get("fps"))), "height": int(_yt_number(fmt.get("height"))),
        "width": int(_yt_number(fmt.get("width"))), "acodec": str(fmt.get("acodec") or "").lower(),
        "vcodec": str(fmt.get("vcodec") or "").lower(), "protocol": str(fmt.get("protocol") or "").strip(),
    }


_YOUTUBE_STREAM_BUILD_LOCKS: Dict[str, threading.Lock] = {}
_YOUTUBE_STREAM_BUILD_LOCKS_GUARD = threading.Lock()


def _youtube_stream_build_lock(key: str) -> threading.Lock:
    with _YOUTUBE_STREAM_BUILD_LOCKS_GUARD:
        lk = _YOUTUBE_STREAM_BUILD_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _YOUTUBE_STREAM_BUILD_LOCKS[key] = lk
        return lk


def validate_ytdlp_output(path: str, media: str = "", expected_duration: float = 0.0) -> dict:
    """Return ffprobe metadata only for a complete, final media artifact."""
    candidate = str(path or "").strip()
    name = os.path.basename(candidate).lower()
    if not candidate or not os.path.isfile(candidate):
        raise RuntimeError("yt-dlp output is missing")
    if any(token in name for token in (".part", ".ytdl", ".tmp", ".temp")):
        raise RuntimeError("yt-dlp output is an intermediate file")
    # yt-dlp's format-specific temporary names look like title.f137.mp4.
    if any(re.fullmatch(r"f[0-9a-z]+", part) for part in name.split(".")[1:-1]):
        raise RuntimeError("yt-dlp output is an intermediate format file")
    try:
        if os.path.getsize(candidate) <= 0:
            raise RuntimeError("yt-dlp output is empty")
    except OSError as exc:
        raise RuntimeError("yt-dlp output cannot be read") from exc
    probe = ffprobe_json(candidate)
    streams = [s for s in list(probe.get("streams") or []) if isinstance(s, dict)]
    if not streams:
        raise RuntimeError("yt-dlp output has no media streams")
    kinds = {str(s.get("codec_type") or "").lower() for s in streams}
    wanted = str(media or "").strip().lower()
    if wanted == "audio" and "audio" not in kinds:
        raise RuntimeError("yt-dlp output has no audio stream")
    if wanted == "audio" and "video" in kinds:
        raise RuntimeError("yt-dlp Audio Only output still contains video")
    if wanted == "video" and not {"video", "audio"}.issubset(kinds):
        raise RuntimeError("yt-dlp video output is missing audio or video")
    if wanted not in {"audio", "video"} and not (kinds & {"audio", "video"}):
        raise RuntimeError("yt-dlp output has no playable stream")
    durations = []
    for value in [probe.get("format", {}).get("duration") if isinstance(probe.get("format"), dict) else 0] + [s.get("duration") for s in streams]:
        number = _yt_number(value)
        if number > 0:
            durations.append(number)
    duration = max(durations, default=0.0)
    if duration <= 0:
        raise RuntimeError("yt-dlp output has no duration")
    expected = _yt_number(expected_duration)
    if expected > 0 and duration + 0.75 < expected:
        raise RuntimeError("yt-dlp output is shorter than the requested media")
    # A merged file with wildly divergent track starts/durations is incomplete
    # even if ffprobe can parse it. Small encoder padding differences are fine.
    if "video" in kinds and "audio" in kinds:
        av = [s for s in streams if str(s.get("codec_type") or "").lower() in {"audio", "video"}]
        starts = [_yt_number(s.get("start_time")) for s in av]
        if starts and max(starts) - min(starts) > 1.0:
            raise RuntimeError("yt-dlp output audio/video streams are out of sync")
        track_durations = [_yt_number(s.get("duration")) for s in av if _yt_number(s.get("duration")) > 0]
        if len(track_durations) >= 2 and max(track_durations) - min(track_durations) > 2.0:
            raise RuntimeError("yt-dlp output audio/video streams are incomplete")
    return {"probe": probe, "duration": duration, "streams": streams}


def _find_existing_output(base_no_ext: str, expected_ext: str = "", media: str = "", expected_duration: float = 0.0) -> str:
    folder = os.path.dirname(base_no_ext) or "."
    stem = os.path.basename(base_no_ext)
    try:
        ext = str(expected_ext or "").strip().lower().lstrip(".")
        for name in sorted(os.listdir(folder)):
            if not name.startswith(stem + "."):
                continue
            if name.count(".") != stem.count(".") + 1:
                continue
            if ext and os.path.splitext(name)[1].lstrip(".").lower() != ext:
                continue
            cand = os.path.join(folder, name)
            try:
                validate_ytdlp_output(cand, media=media, expected_duration=expected_duration)
                return cand
            except Exception:
                continue
    except Exception:
        return ""
    return ""


def _prepare_youtube_stream_file(url: str, fmt: dict) -> str:
    src_url = str(url or "").strip()
    if not src_url:
        raise RuntimeError("Missing YouTube URL")
    fmt2 = dict(fmt or {})
    media = str(fmt2.get("media") or "").strip().lower()
    quality_target = str(fmt2.get("quality_target") or "").strip().lower()
    expected_duration = _yt_number(fmt2.get("duration"))
    out_ext = _yt_selected_output_ext(fmt2)
    audio_extract = media == "audio"
    if audio_extract:
        # Let yt-dlp retain the source container when it can remux it. The
        # final path printed after_move is authoritative and is validated.
        out_ext = ""
    key = sha1_text(src_url + "|" + quality_target + "|" + media + "|" + out_ext)
    folder = _youtube_stream_cache_dir()
    base_no_ext = os.path.join(folder, key)
    existing = _find_existing_output(base_no_ext, out_ext, media, expected_duration)
    if existing:
        return existing
    lock = _youtube_stream_build_lock(key)
    with lock:
        existing = _find_existing_output(base_no_ext, out_ext, media, expected_duration)
        if existing:
            return existing
        # Resolve the selector from the normalized target on the server. A
        # client supplied format ID or selector is never trusted for a fetch.
        selectors = ytdlp_format_selectors({"quality_target": quality_target, "media": media, "ext": out_ext})
        last_error = ""
        for selector in selectors:
            args = _yt_dlp_base_args() + ["--no-part", "--force-overwrites", "--newline", "-f", selector]
            if media != "audio":
                args += ["--merge-output-format", out_ext]
            elif audio_extract:
                args += ["--extract-audio", "--audio-format", "best"]
            args += ["--print", "after_move:dp:filepath:%(filepath)s", "-o", base_no_ext + ".%(ext)s", src_url]
            code, out, err = _run_ytdlp(args)
            if code != 0:
                last_error = (err or out or "yt-dlp failed").strip()
                continue
            printed = ""
            for line in (out or "").splitlines():
                if line.strip().startswith("dp:filepath:"):
                    printed = line.strip().split(":", 2)[2].strip()
            built = printed if printed and os.path.isfile(printed) else ""
            if not built:
                last_error = "yt-dlp produced an invalid or incomplete stream"
                continue
            try:
                validate_ytdlp_output(built, media=media, expected_duration=expected_duration)
                return built
            except Exception as exc:
                last_error = str(exc)
        raise RuntimeError(last_error or "yt-dlp did not produce a streamable file")


def _yt_dlp_base_args() -> List[str]:
    # Sort by requested resolution first, then prefer broadly playable H.264
    # and AAC only among equal-resolution candidates.
    args = ["--no-playlist", "--no-warnings", "--ignore-config", "-S", "res,vcodec:h264,acodec:aac"]
    ff_loc = _ytdlp_ffmpeg_location()
    if ff_loc:
        args += ["--ffmpeg-location", ff_loc]
    return args


def _yt_dlp_extract_info(url: str, *, flat: bool = False) -> dict:
    u = str(url or "").strip()
    if not u:
        return {}
    args = _yt_dlp_base_args()
    if flat:
        args = [arg for arg in args if arg != "--no-playlist"] + ["--yes-playlist", "--flat-playlist"]
    code, out, err = _run_ytdlp(args + ["-J", "--skip-download", u])
    if code != 0:
        raise RuntimeError((err or out or "yt-dlp failed").strip())
    try:
        data = json.loads(out or "{}")
    except Exception as e:
        raise RuntimeError(f"yt-dlp returned invalid json: {e}")
    if not isinstance(data, dict):
        raise RuntimeError("yt-dlp returned invalid info")
    return data


def ytdlp_comments(url: str, limit: int = 100) -> List[dict]:
    """Extract a bounded normalized comment list without downloading media."""
    u = str(url or "").strip()
    if not u:
        return []
    code, out, err = _run_ytdlp(_yt_dlp_base_args() + ["--get-comments", "-J", "--skip-download", u])
    if code != 0:
        raise RuntimeError((err or out or "yt-dlp failed").strip())
    try:
        info = json.loads(out or "{}")
    except Exception as exc:
        raise RuntimeError(f"yt-dlp returned invalid json: {exc}") from exc
    comments = info.get("comments") if isinstance(info, dict) else []
    result: List[dict] = []
    for raw in comments if isinstance(comments, list) else []:
        if not isinstance(raw, dict):
            continue
        text_value = str(raw.get("text") or "").strip()
        if not text_value:
            continue
        row = {
            "author": str(raw.get("author") or raw.get("author_id") or "").strip(),
            "text": text_value,
        }
        if raw.get("timestamp") is not None:
            row["timestamp"] = raw.get("timestamp")
        if raw.get("like_count") is not None:
            row["like_count"] = raw.get("like_count")
        if raw.get("reply_count") is not None:
            row["reply_count"] = raw.get("reply_count")
        result.append(row)
        if len(result) >= max(1, min(100, int(limit or 100))):
            break
    return result


def _yt_guess_media(format_info: dict) -> str:
    vcodec = str(format_info.get("vcodec") or "").strip().lower()
    acodec = str(format_info.get("acodec") or "").strip().lower()
    if vcodec in ("none", "") and acodec not in ("", "none"):
        return "audio"
    return "video"


def _yt_audio_bitrate_k(format_info: dict) -> str:
    abr = format_info.get("abr")
    try:
        if abr is not None and float(abr) > 0:
            return str(int(round(float(abr)))) + "k"
    except Exception:
        pass
    tbr = format_info.get("tbr")
    try:
        if tbr is not None and float(tbr) > 0 and _yt_guess_media(format_info) == "audio":
            return str(int(round(float(tbr)))) + "k"
    except Exception:
        pass
    return ""


def _yt_quality_text(format_info: dict) -> str:
    q = str(format_info.get("format") or "").strip()
    if q:
        return q
    note = str(format_info.get("format_note") or "").strip()
    if note:
        ext = str(format_info.get("ext") or "").strip().lower()
        return (note + ((" " + ext) if ext else "")).strip()
    height = format_info.get("height")
    width = format_info.get("width")
    try:
        if height:
            fps = format_info.get("fps")
            base = f"{int(height)}p"
            try:
                if fps and float(fps) >= 1:
                    base += str(int(round(float(fps))))
            except Exception:
                pass
            ext = str(format_info.get("ext") or "").strip().lower()
            return (base + ((" " + ext) if ext else "")).strip()
    except Exception:
        pass
    abr = _yt_audio_bitrate_k(format_info)
    if abr:
        ext = str(format_info.get("ext") or "").strip().lower()
        return (abr + ((" " + ext) if ext else "")).strip()
    if width:
        ext = str(format_info.get("ext") or "").strip().lower()
        return (str(width) + "w" + ((" " + ext) if ext else "")).strip()
    return "Format"


def ytdlp_list_formats(url: str) -> List[dict]:
    # Keep the inspected page URL with each format. ``fmt['url']`` is a
    # transient CDN URL and must never be the only value retained by the UI:
    # yt-dlp needs the original page URL to re-resolve a format later.
    source_url = str(url or "").strip()
    info = _yt_dlp_extract_info(source_url)
    # The extractor's format IDs change over time and are not useful quality
    # choices. Return one row per available target with a stable target ID.
    items = _yt_quality_target_rows(info, source_url)
    if items:
        return items

    # A few extractors expose only a progressive format without dimensions.
    # Keep that media usable by returning a single normalized fallback row.
    items: List[dict] = []
    seen = set()
    for fmt in list(info.get("formats") or []):
        if not isinstance(fmt, dict):
            continue
        ext = str(fmt.get("ext") or "").strip().lower()
        if ext in ("mhtml", "jpg", "jpeg", "png", "webp"):
            continue
        acodec = str(fmt.get("acodec") or "").strip().lower()
        vcodec = str(fmt.get("vcodec") or "").strip().lower()
        if acodec in ("", "none") and vcodec in ("", "none"):
            continue
        media = _yt_guess_media(fmt)
        quality = _yt_quality_text(fmt)
        name = quality or ("Audio Only" if media == "audio" else "Best")
        size = 0
        for key in ("filesize", "filesize_approx"):
            try:
                val = fmt.get(key)
                if val is not None and int(val) > 0:
                    size = int(val)
                    break
            except Exception:
                pass
        bitrate = _yt_audio_bitrate_k(fmt) if media == "audio" else ""
        quality_target = "audio" if media == "audio" else "best"
        key = (quality_target, ext, quality, size)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "file_id": "quality-" + quality_target,
            "name": name,
            "title": name,
            "ext": ext,
            "quality": quality,
            "quality_target": quality_target,
            "bitrate": bitrate,
            "size": size,
            "size_text": human_bytes(size) if size > 0 else "",
            "source": "youtube",
            "selectable": True,
            "media": media,
            "source_url": source_url,
            "fps": int(_yt_number(fmt.get("fps"))),
            "height": int(_yt_number(fmt.get("height"))),
            "width": int(_yt_number(fmt.get("width"))),
            "acodec": acodec,
            "vcodec": vcodec,
            "protocol": str(fmt.get("protocol") or "").strip(),
        })

    def _sort_key(it: dict):
        media_rank = 0 if str(it.get("media") or "") == "video" else 1
        try:
            h = int(it.get("height") or 0)
        except Exception:
            h = 0
        try:
            sz = int(it.get("size") or 0)
        except Exception:
            sz = 0
        return (media_rank, -h, -sz, str(it.get("name") or "").lower())

    items.sort(key=_sort_key)
    return items


def ytdlp_inspect(url: str) -> dict:
    """Inspect any yt-dlp-supported HTTP(S) URL without downloading it."""
    original_url = str(url or "").strip()
    info = _yt_dlp_extract_info(original_url, flat=True)
    is_collection = isinstance(info.get("entries"), list) or info.get("_type") in {"playlist", "multi_video"}
    entries = [entry for entry in info.get("entries", []) if isinstance(entry, dict)] if is_collection else []
    files = [] if is_collection else _yt_quality_target_rows(info, original_url)
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").strip()
    title = str(info.get("title") or info.get("fulltitle") or original_url).strip()
    media_id = str(info.get("id") or "").strip()
    total_size = sum(int(item.get("size") or 0) for item in files)
    return {
        "result_id": "ytdlp:" + (extractor or "generic") + ":" + (media_id or original_url),
        "source": "youtube",
        "source_label": extractor or "yt-dlp",
        "title": title,
        "directory_title": title,
        "kind": "playlist" if is_collection else "video",
        "canonical_url": original_url,
        "entries": entries,
        "directory": original_url,
        "url": original_url,
        "original_url": original_url,
        "extractor": extractor,
        "extractor_id": media_id,
        "channel": str(info.get("channel") or info.get("uploader") or "").strip(),
        "channel_id": str(info.get("channel_id") or info.get("uploader_id") or "").strip(),
        "thumbnail": str(info.get("thumbnail") or "").strip(),
        "description": str(info.get("description") or "").strip(),
        "browse_available": False,
        "stream_available": True,
        "download_available": True,
        "files_loaded": True,
        "files": files,
        "file_count": len(files),
        "size": total_size,
    }






def youtube_load_result_files(raw: dict) -> dict:
    out = dict(raw or {})
    files = ytdlp_list_formats(str(out.get("url") or ""))
    total_size = 0
    for f in files:
        try:
            total_size += int(f.get("size") or 0)
        except Exception:
            pass
    out["files"] = files
    out["file_count"] = len(files)
    out["size"] = total_size
    out["files_loaded"] = True
    return out
