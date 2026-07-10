from __future__ import annotations

import json
import os
import threading
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from ..Library.search_cache import _SEARCH_DISK_LOCK, _disk_cache_get, _disk_cache_set, _make_search_cache_key
from ..paths import cache_dir
from ..playback.probe import run_cmd
from ..utils import human_bytes, sha1_text

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


def _extract_json_object_from_html(html: str, anchor: str) -> Optional[dict]:
    idx = html.find(anchor)
    if idx < 0:
        return None
    start = html.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except Exception:
                    return None
    return None


def _iter_nested_values(obj: Any, key: str):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _iter_nested_values(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_nested_values(v, key)


def _youtube_text_runs(node: Any) -> str:
    if isinstance(node, dict):
        if isinstance(node.get("simpleText"), str):
            return node.get("simpleText") or ""
        runs = node.get("runs")
        if isinstance(runs, list):
            return "".join(str(r.get("text") or "") for r in runs if isinstance(r, dict))
    if isinstance(node, list):
        return "".join(_youtube_text_runs(x) for x in node)
    return str(node or "")


def _youtube_parse_video_renderer(vr: dict) -> Optional[dict]:
    if not isinstance(vr, dict):
        return None
    video_id = str(vr.get("videoId") or "").strip()
    if not video_id:
        return None
    title = _youtube_text_runs(vr.get("title")) or "YouTube video"
    owner = _youtube_text_runs(vr.get("ownerText") or vr.get("longBylineText") or vr.get("shortBylineText"))
    length = _youtube_text_runs(vr.get("lengthText"))
    published = _youtube_text_runs(vr.get("publishedTimeText"))
    view_count = _youtube_text_runs(vr.get("viewCountText"))
    owner_runs = None
    for k in ("ownerText", "longBylineText", "shortBylineText"):
        cur = vr.get(k)
        if isinstance(cur, dict) and isinstance(cur.get("runs"), list) and cur.get("runs"):
            owner_runs = cur.get("runs")
            break
    channel_id = ""
    browse_url = ""
    handle = ""
    if owner_runs:
        run0 = owner_runs[0] if isinstance(owner_runs[0], dict) else {}
        nav = run0.get("navigationEndpoint") or {}
        browse = nav.get("browseEndpoint") or {}
        channel_id = str(browse.get("browseId") or "").strip()
        browse_url = str(browse.get("canonicalBaseUrl") or "").strip()
        if browse_url.startswith("/@"):
            handle = browse_url[2:]
    thumb = ""
    thumbs = (vr.get("thumbnail") or {}).get("thumbnails") or []
    if isinstance(thumbs, list) and thumbs:
        thumb = str((thumbs[-1] or {}).get("url") or "")
    return {
        "video_id": video_id,
        "url": _youtube_watch_url(video_id),
        "title": title,
        "channel": owner,
        "channel_id": channel_id,
        "channel_url": _youtube_channel_url(channel_id, handle, browse_url),
        "browse_url": browse_url,
        "handle": handle,
        "length": length,
        "published": published,
        "view_count": view_count,
        "thumbnail": thumb,
    }


def youtube_search(query: str, limit: Optional[int] = None) -> List[dict]:
    q = str(query or "").strip()
    if not q:
        return []
    max_results = int(limit or _search_limit_provider() or 24)
    url = _youtube_web_base() + "/results?search_query=" + quote(q)
    resp = requests.get(url, headers=_request_headers_provider(), timeout=_timeout_provider())
    resp.raise_for_status()
    data = _extract_json_object_from_html(resp.text, "var ytInitialData =") or _extract_json_object_from_html(resp.text, "ytInitialData =")
    if not isinstance(data, dict):
        return []
    out: List[dict] = []
    seen = set()
    for vr in _iter_nested_values(data, "videoRenderer"):
        item = _youtube_parse_video_renderer(vr)
        if not item:
            continue
        vid = item.get("video_id") or ""
        if vid in seen:
            continue
        seen.add(vid)
        out.append(item)
        if len(out) >= max_results:
            break
    return out


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


def _youtube_channel_entries_from_feed(channel_id: str, limit: Optional[int] = None) -> List[dict]:
    cid = str(channel_id or "").strip()
    if not cid:
        return []
    resp = requests.get(_youtube_channel_feed_url(cid), headers=_request_headers_provider(), timeout=_timeout_provider())
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
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


def youtube_channel_videos(channel_id: str, limit: Optional[int] = None) -> List[dict]:
    try:
        items = _youtube_channel_entries_from_ytdlp(channel_id, limit)
        if items:
            return items
    except Exception:
        pass
    return _youtube_channel_entries_from_feed(channel_id, limit)


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
    try:
        base = cache_dir()
    except Exception:
        base = _youtube_download_root()
    sub = str(_stream_cache_subdir_provider() or "youtube_streams").strip() or "youtube_streams"
    out = os.path.join(base, sub)
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
    fid = str(fmt.get("format_id") or fmt.get("itag") or fmt.get("file_id") or "").strip()
    media = str(fmt.get("media") or "").strip().lower()
    if not fid:
        return "best"
    if media == "audio":
        return fid
    return f"{fid}+bestaudio/best"


_YOUTUBE_STREAM_BUILD_LOCKS: Dict[str, threading.Lock] = {}
_YOUTUBE_STREAM_BUILD_LOCKS_GUARD = threading.Lock()


def _youtube_stream_build_lock(key: str) -> threading.Lock:
    with _YOUTUBE_STREAM_BUILD_LOCKS_GUARD:
        lk = _YOUTUBE_STREAM_BUILD_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _YOUTUBE_STREAM_BUILD_LOCKS[key] = lk
        return lk


def _find_existing_output(base_no_ext: str) -> str:
    folder = os.path.dirname(base_no_ext) or "."
    stem = os.path.basename(base_no_ext)
    try:
        for name in sorted(os.listdir(folder)):
            if name == stem or name.startswith(stem + "."):
                cand = os.path.join(folder, name)
                if os.path.isfile(cand):
                    return cand
    except Exception:
        return ""
    return ""


def _prepare_youtube_stream_file(url: str, fmt: dict) -> str:
    src_url = str(url or "").strip()
    if not src_url:
        raise RuntimeError("Missing YouTube URL")
    fmt2 = dict(fmt or {})
    fmt_id = str(fmt2.get("format_id") or fmt2.get("itag") or fmt2.get("file_id") or "").strip()
    media = str(fmt2.get("media") or "").strip().lower()
    out_ext = _yt_selected_output_ext(fmt2)
    key = sha1_text(src_url + "|" + fmt_id + "|" + media + "|" + out_ext)
    folder = _youtube_stream_cache_dir()
    base_no_ext = os.path.join(folder, key)
    existing = _find_existing_output(base_no_ext)
    if existing:
        return existing
    lock = _youtube_stream_build_lock(key)
    with lock:
        existing = _find_existing_output(base_no_ext)
        if existing:
            return existing
        selector = _yt_stream_format_selector(fmt2)
        args = _yt_dlp_base_args() + ["--no-part", "--force-overwrites", "--newline", "-f", selector]
        if media != "audio":
            args += ["--merge-output-format", out_ext]
        args += ["-o", base_no_ext + ".%(ext)s", src_url]
        code, out, err = _run_ytdlp(args)
        if code != 0:
            raise RuntimeError((err or out or "yt-dlp failed").strip())
        built = _find_existing_output(base_no_ext)
        if not built:
            raise RuntimeError("yt-dlp did not produce a streamable file")
        return built


def _yt_dlp_base_args() -> List[str]:
    args = ["--no-playlist", "--no-warnings", "--ignore-config"]
    ff_loc = _ytdlp_ffmpeg_location()
    if ff_loc:
        args += ["--ffmpeg-location", ff_loc]
    return args


def _yt_dlp_extract_info(url: str) -> dict:
    u = str(url or "").strip()
    if not u:
        return {}
    code, out, err = _run_ytdlp(_yt_dlp_base_args() + ["-J", "--skip-download", u])
    if code != 0:
        raise RuntimeError((err or out or "yt-dlp failed").strip())
    try:
        data = json.loads(out or "{}")
    except Exception as e:
        raise RuntimeError(f"yt-dlp returned invalid json: {e}")
    if not isinstance(data, dict):
        raise RuntimeError("yt-dlp returned invalid info")
    return data


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
    return str(format_info.get("format_id") or "Format").strip()


def _yt_direct_url_for_format(url: str, format_id: str) -> str:
    info = _yt_dlp_extract_info(url)
    fid = str(format_id or "").strip()
    if not fid:
        return str(info.get("url") or "").strip()
    for fmt in list(info.get("formats") or []):
        if not isinstance(fmt, dict):
            continue
        if str(fmt.get("format_id") or "").strip() == fid:
            return str(fmt.get("url") or "").strip()
    return ""


def ytdlp_list_formats(url: str) -> List[dict]:
    info = _yt_dlp_extract_info(url)
    items: List[dict] = []
    seen = set()
    for fmt in list(info.get("formats") or []):
        if not isinstance(fmt, dict):
            continue
        fid = str(fmt.get("format_id") or "").strip()
        if not fid:
            continue
        ext = str(fmt.get("ext") or "").strip().lower()
        if ext in ("mhtml", "jpg", "jpeg", "png", "webp"):
            continue
        acodec = str(fmt.get("acodec") or "").strip().lower()
        vcodec = str(fmt.get("vcodec") or "").strip().lower()
        if acodec in ("", "none") and vcodec in ("", "none"):
            continue
        direct_url = str(fmt.get("url") or "").strip()
        quality = _yt_quality_text(fmt)
        name = quality or ("Format " + fid)
        size = 0
        for key in ("filesize", "filesize_approx"):
            try:
                val = fmt.get(key)
                if val is not None and int(val) > 0:
                    size = int(val)
                    break
            except Exception:
                pass
        media = _yt_guess_media(fmt)
        bitrate = _yt_audio_bitrate_k(fmt) if media == "audio" else ""
        key = (fid, ext, quality, size)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "file_id": fid,
            "itag": fid,
            "format_id": fid,
            "name": name,
            "title": name,
            "ext": ext,
            "quality": quality,
            "bitrate": bitrate,
            "size": size,
            "size_text": human_bytes(size) if size > 0 else "",
            "source": "youtube",
            "selectable": True,
            "media": media,
            "direct_url": direct_url,
            "fps": int(fmt.get("fps") or 0) if str(fmt.get("fps") or "").strip() else 0,
            "height": int(fmt.get("height") or 0) if str(fmt.get("height") or "").strip() else 0,
            "width": int(fmt.get("width") or 0) if str(fmt.get("width") or "").strip() else 0,
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


def _search_youtube_cached(q: str) -> Tuple[List[dict], str, str]:
    extra: Dict[str, Any] = {}
    cache_key = _make_search_cache_key("youtube", q, extra)
    cached_payload = None
    with _SEARCH_DISK_LOCK:
        d = _disk_cache_get(cache_key)
        if d and isinstance(d.get("payload"), dict):
            cached_payload = d.get("payload")
    if cached_payload is not None:
        return list(cached_payload.get("results") or []), str(cached_payload.get("error") or ""), cache_key
    try:
        results = youtube_search(q)
        err = ""
    except Exception as e:
        results = []
        err = "YouTube search failed: " + str(e)
    with _SEARCH_DISK_LOCK:
        _disk_cache_set(cache_key, "youtube", q, extra, {"results": results, "error": err})
    return results, err, cache_key


def _standardize_youtube_results(raw_results: List[dict]) -> List[dict]:
    out: List[dict] = []
    for r in raw_results or []:
        if not isinstance(r, dict):
            continue
        video_id = str(r.get("video_id") or "").strip()
        title = str(r.get("title") or "").strip()
        if not video_id or not title:
            continue
        published = str(r.get("published") or "").strip()
        view_count = str(r.get("view_count") or "").strip()
        length = str(r.get("length") or "").strip()
        channel = str(r.get("channel") or "").strip()
        channel_id = str(r.get("channel_id") or "").strip()
        out.append({
            "result_id": "youtube:" + video_id,
            "source": "youtube",
            "source_label": "YouTube",
            "user": channel,
            "title": title,
            "directory": str(r.get("url") or ""),
            "directory_title": published or length or view_count,
            "file_count": 0,
            "size": 0,
            "speed": 0,
            "seeders": 0,
            "leechers": 0,
            "browse_available": bool(channel_id),
            "stream_available": True,
            "download_available": True,
            "files_loaded": False,
            "files": [],
            "video_id": video_id,
            "url": str(r.get("url") or _youtube_watch_url(video_id)),
            "channel": channel,
            "channel_id": channel_id,
            "channel_url": str(r.get("channel_url") or ""),
            "published": published,
            "view_count": view_count,
            "length": length,
            "thumbnail": str(r.get("thumbnail") or ""),
            "description": str(r.get("description") or ""),
        })
    return out


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


def youtube_channel_browse(channel_id: str) -> List[dict]:
    return _standardize_youtube_results(youtube_channel_videos(channel_id))
