from __future__ import annotations

import math
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

from ..media_types import VIDEO_EXTS


IGNORED_VIDEO_TOKENS = {
    "sample", "trailer", "trailers", "extra", "extras", "featurette", "featurettes",
    "deleted scene", "deleted scenes", "behind the scenes", "interview", "proof", "screens",
    "subs", "subtitles", "cover", "artwork", "nfo", "thumbnail", "thumbnails",
}
RELEASE_JUNK = {
    "480p", "576p", "720p", "1080p", "1440p", "2160p", "4320p", "4k", "8k",
    "bluray", "blu-ray", "bdrip", "brrip", "web", "webdl", "web-dl", "webrip", "dl", "rip", "hdtv",
    "dvdrip", "dvd", "remux", "cam", "ts", "telesync", "hdr", "hdr10", "hdr10+", "dv",
    "dolbyvision", "x264", "x265", "h264", "h265", "hevc", "av1", "vp9", "mpeg2",
    "aac", "ac3", "eac3", "ddp", "ddp5", "dts", "truehd", "atmos", "flac", "mp3", "opus",
    "10bit", "8bit", "repack", "proper", "internal", "limited", "multi", "subbed", "dubbed",
    "amzn", "amazon", "nf", "netflix", "dsnp", "hulu", "max", "atvp", "itunes", "silence", "rarbg", "eztv",
}
EDITION_PATTERNS = (
    (r"\bdirectors?[ ._-]*cut\b", "Directors Cut"),
    (r"\bextended(?:[ ._-]*edition)?\b", "Extended"),
    (r"\btheatrical(?:[ ._-]*cut)?\b", "Theatrical"),
    (r"\bunrated\b", "Unrated"),
    (r"\bcriterion\b", "Criterion"),
    (r"\bremaster(?:ed)?\b", "Remastered"),
    (r"\bspecial[ ._-]*edition\b", "Special Edition"),
)


def _ascii(value: Any) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")


def _words(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", _ascii(value).lower())


def _display_title(value: Any) -> str:
    text = re.sub(r"[._]+", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" -_.")
    if not text:
        return ""
    return " ".join(word.upper() if word.lower() in {"tv", "uk", "us", "ii", "iii", "iv"} else word[:1].upper() + word[1:] for word in text.split())


def duration_text(duration: Any) -> str:
    try:
        seconds = max(0, int(float(duration or 0)))
    except Exception:
        return ""
    if not seconds:
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, _seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def completion_percent(progress: dict | None, duration: Any = None) -> int:
    progress = progress if isinstance(progress, dict) else {}
    try:
        dur = max(0.0, float(progress.get("duration") or duration or 0))
        pos = max(0.0, float(progress.get("position") or 0))
    except Exception:
        return 0
    if dur <= 0:
        return 0
    if bool(progress.get("ended")) or pos >= max(0.0, dur - 30.0):
        return 100
    return max(0, min(100, math.floor((pos / dur) * 100)))


def is_canonical_video(path: str, *, size: int = 0, duration: Any = None) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTS:
        return False
    normalized_path = " ".join(_words(path))
    if any(re.search(r"(?:^| )" + re.escape(token) + r"(?: |$)", normalized_path) for token in IGNORED_VIDEO_TOKENS):
        return False
    if any(part.lower() in {"_debripod_cache", ".debripod-cache", "cache", "transcodes"} for part in re.split(r"[\\/]", path)):
        return False
    try:
        if int(size or 0) and int(size) < 8 * 1024 * 1024 and float(duration or 0) < 180:
            return False
    except Exception:
        pass
    return True


def browser_friendly_video(path: str, metadata: dict | None = None) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    ext = os.path.splitext(path)[1].lower()
    video_codec = str(meta.get("video_codec") or meta.get("codec") or "").lower()
    audio_codec = str(meta.get("audio_codec") or "").lower()
    # This is a property of the original file, never a signal that a derived
    # browser/transcoded copy exists.  Chromium on the supported Windows
    # installation can natively play the common MP4 HEVC/AC-3 combinations as
    # well as AVC/AAC, so keep the decision tied to the probed streams.
    if ext in {".mp4", ".m4v"}:
        return video_codec in {"h264", "avc", "avc1", "hevc", "h265"} and audio_codec in {"aac", "mp3", "ac3", "eac3", ""}
    if ext == ".webm":
        return video_codec in {"vp9", "av1", "vp8"} and audio_codec in {"opus", "vorbis", ""}
    return False


def extract_quality(value: str, metadata: dict | None = None, source: str = "") -> str:
    text = str(value or "")
    match = re.search(r"(?<!\d)(4320|2160|1440|1080|720|576|480)[pi](?!\d)", text, re.I)
    if match:
        return match.group(1) + "p"
    meta = metadata if isinstance(metadata, dict) else {}
    try:
        height = int(meta.get("height") or 0)
    except Exception:
        height = 0
    for threshold, label in ((4000, "4320p"), (1900, "2160p"), (1300, "1440p"), (900, "1080p"), (650, "720p"), (430, "480p")):
        if height >= threshold:
            return label
    lower = text.lower()
    for pattern, label in ((r"blu[ ._-]?ray|bdrip|brrip", "BluRay"), (r"web[ ._-]?(?:dl|rip)?", "WEB"), (r"hdtv", "HDTV"), (r"dvd", "DVD"), (r"remux", "Remux"), (r"\bcam\b|telesync", "Cam")):
        if re.search(pattern, lower):
            return label
    return "YouTube" if source == "youtube" else ""


def _source_tag(value: str, source: str) -> str:
    lower = value.lower()
    for pattern, label in ((r"blu[ ._-]?ray|bdrip|brrip", "BluRay"), (r"web[ ._-]?(?:dl|rip)?", "WEB"), (r"hdtv", "HDTV"), (r"dvd", "DVD"), (r"remux", "Remux"), (r"\bcam\b|telesync", "Cam")):
        if re.search(pattern, lower):
            return label
    return "YouTube" if source == "youtube" else ""


def _codec_tag(value: str, metadata: dict | None = None) -> str:
    lower = value.lower()
    for pattern, label in ((r"\b(?:h[ ._-]?265|x265|hevc)\b", "H265"), (r"\b(?:h[ ._-]?264|x264|avc)\b", "H264"), (r"\bav1\b", "AV1"), (r"\bvp9\b", "VP9"), (r"\bmpeg[ ._-]?2\b", "MPEG2")):
        if re.search(pattern, lower):
            return label
    codec = str((metadata or {}).get("video_codec") or "").lower()
    return {"hevc": "H265", "h265": "H265", "h264": "H264", "av1": "AV1", "vp9": "VP9", "mpeg2video": "MPEG2"}.get(codec, codec.upper())


def _strip_release_junk(stem: str) -> str:
    value = re.sub(r"\[[^\]]*(?:torrent|tracker|www\.|\.com|\.org)[^\]]*\]", " ", stem, flags=re.I)
    # Bracketed filename suffixes are release/tracker tags in the media names
    # accepted here; remove the complete tag before token cleanup.
    value = re.sub(r"\[[^\]]*\]", " ", value)
    value = re.sub(r"\bS\d{1,2}E\d{1,4}(?:E\d{1,4})?\b|\b\d{1,2}x\d{1,3}\b", " ", value, flags=re.I)
    value = re.sub(r"\bSeason[ ._-]*\d+\b|\bEpisode[ ._-]*\d+\b", " ", value, flags=re.I)
    value = re.sub(r"\b(?:19|20)\d{2}\b", " ", value)
    value = re.sub(r"\b(?:part|pt|cd|disc|disk)[ ._-]*\d{1,2}\b", " ", value, flags=re.I)
    value = re.sub(r"(?i)(?:ddp|eac3|ac3|dts)?[ ._-]*[2-9][._-][01]\b", " ", value)
    value = re.sub(r"(?i)\b(?:\d+(?:\.\d+)?ch|[2-9]\.[01]|reenc|rerip|proper|web[ ._-]?dl|web[ ._-]?rip)\b", " ", value)
    tokens = re.split(r"([ ._\-]+)", value)
    kept = [token for token in tokens if token.strip(" ._-()[]{}").lower() not in RELEASE_JUNK]
    value = "".join(kept)
    return re.sub(r"[ ._-]+", " ", value).strip(" ()[]{}-_.")


def parse_video_filename(path: str, *, folder_title: str = "", source: str = "", metadata: dict | None = None) -> dict[str, Any]:
    filename = os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower()
    stem = os.path.splitext(filename)[0]
    group_match = re.search(r"-([A-Za-z0-9][A-Za-z0-9._-]{1,30})$", stem)
    release_signal = r"(?i)(?:\b(?:19|20)\d{2}\b|\b(?:480p|576p|720p|1080p|1440p|2160p|4320p|4k|8k|x26[45]|h26[45]|hevc|av1|vp9|bluray|bdrip|brrip|hdtv|remux)\b|web[ ._-]?(?:dl|rip))"
    if group_match and not re.search(release_signal, stem[: group_match.start()]):
        group_match = None
    if not group_match:
        group_match = re.search(
            r"(?i)(?:x26[45]|h26[45]|hevc|av1|vp9|bluray|bdrip|brrip|web[ ._-]?(?:dl|rip)?|hdtv|remux)[ ._-]+([A-Za-z0-9][A-Za-z0-9_-]{1,30})$",
            stem,
        )
    if group_match and group_match.group(1).lower() in RELEASE_JUNK:
        group_match = None
    release_group = group_match.group(1) if group_match else ""
    parse_stem = stem[: group_match.start()].rstrip(" ._-") if group_match else stem
    # Parenthetical tails are frequently the release description, not part of
    # the episode title (for example: "Title (1080p AMZN WEB-DL x265 Group)").
    parse_stem = re.sub(r"(?i)\s*\((?=[^)]*(?:\b\d{3,4}p\b|\b(?:web|bluray|hdtv|x26[45]|h26[45]|hevc|av1)\b)).*$", "", parse_stem)
    season = episode = episode_end = part = None
    episode_title = ""
    show_title = ""
    episode_match = re.search(r"(?i)\bS(\d{1,2})E(\d{1,4})(?:E(\d{1,4}))?\b", parse_stem)
    if not episode_match:
        episode_match = re.search(r"(?i)\b(\d{1,2})x(\d{1,3})(?:[-x](\d{1,3}))?\b", parse_stem)
    if not episode_match:
        episode_match = re.search(r"(?i)\bSeason[ ._-]*(\d{1,2})[ ._-]+Episode[ ._-]*(\d{1,4})(?:[ ._-]*(?:to|-)[ ._-]*(\d{1,4}))?\b", parse_stem)
    if episode_match:
        season = int(episode_match.group(1))
        episode = int(episode_match.group(2))
        episode_end = int(episode_match.group(3)) if episode_match.lastindex and episode_match.lastindex >= 3 and episode_match.group(3) else None
        show_title = _strip_release_junk(parse_stem[: episode_match.start()]) or folder_title
        tail = parse_stem[episode_match.end() :]
        episode_title = _strip_release_junk(tail)
    elif folder_title:
        numeric = re.match(r"^\s*(\d{1,2})[ ._-]+(\d{1,3})(?:[ ._-]+(.+))?$", parse_stem)
        if numeric:
            season, episode = int(numeric.group(1)), int(numeric.group(2))
            episode_title = _strip_release_junk(numeric.group(3) or "")
            show_title = folder_title
        else:
            absolute = re.match(r"^\s*(\d{1,4})(?:[ ._-]+(.+))?$", parse_stem)
            if absolute and int(absolute.group(1)) <= 999 and str(absolute.group(2) or "").strip():
                season, episode = 1, int(absolute.group(1))
                episode_title = _strip_release_junk(absolute.group(2) or "")
                show_title = folder_title
    parent_name = os.path.basename(os.path.dirname(str(path or ""))).strip().lower()
    if parent_name == "specials" and season is None:
        special_number = re.search(r"(?i)(?:^|[ ._-])(?:special|episode|e)?[ ._-]*0*(\d{1,3})(?:[ ._-]|$)", parse_stem)
        season = 0
        episode = int(special_number.group(1)) if special_number else 1
        show_title = folder_title or show_title
        episode_title = episode_title or _strip_release_junk(parse_stem)
    year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", parse_stem)
    year = int(year_match.group(1)) if year_match else None
    part_match = re.search(r"(?i)\b(?:part|pt|cd|disc|disk)[ ._-]*(\d{1,2})\b", parse_stem)
    if part_match:
        part = int(part_match.group(1))
    edition = next((label for pattern, label in EDITION_PATTERNS if re.search(pattern, stem, re.I)), "")
    raw_title_guess = parse_stem[: year_match.start()] if year_match else (parse_stem[: episode_match.start()] if episode_match else parse_stem)
    clean_title = _strip_release_junk(raw_title_guess)
    if not clean_title:
        clean_title = show_title or folder_title or stem
    audio_match = re.search(r"(?i)\b(?:AAC|AC3|EAC3|DDP(?:5\.1)?|DTS(?:HD)?|TrueHD|Atmos|FLAC|MP3|Opus)\b", stem)
    return {
        "title": _display_title(clean_title),
        "raw_title": stem,
        "raw_title_guess": _display_title(raw_title_guess),
        "show_title": _display_title(show_title or folder_title) if episode is not None else "",
        "year": year,
        "season": season,
        "episode": episode,
        "episode_end": episode_end,
        "episode_title": _display_title(episode_title),
        "airdate": "",
        "part": part,
        "quality": extract_quality(stem, metadata, source),
        "source_tag": _source_tag(stem, source),
        "codec": _codec_tag(stem, metadata),
        "audio_tag": audio_match.group(0) if audio_match else "",
        "edition": edition,
        "release_group": release_group,
        "ext": ext.lstrip("."),
        "browser_friendly": browser_friendly_video(path, metadata),
    }


def normalize_show_key(value: str, year: Any = None) -> str:
    words = _words(_strip_release_junk(value))
    if words and words[0] in {"a", "an", "the"}:
        words = words[1:]
    words = ["and" if word == "amp" else word for word in words]
    key = " ".join(words)
    if year:
        key += f"|{year}"
    return key.strip("|")


def show_keys_close(left: str, right: str) -> bool:
    a, b = normalize_show_key(left), normalize_show_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    at, bt = set(a.split()), set(b.split())
    if at == bt:
        return True
    overlap = len(at & bt) / max(1, len(at | bt))
    return overlap >= 0.75 and SequenceMatcher(None, a, b).ratio() >= 0.82


def _group_rel(record: dict) -> str:
    manifest = record.get("manifest") if isinstance(record.get("manifest"), dict) else {}
    task_id = str(manifest.get("task_id") or "")
    if task_id:
        return "task:" + task_id
    rel = str(record.get("rel") or "").replace("\\", "/")
    parent = os.path.dirname(rel).replace("\\", "/")
    parent_name = os.path.basename(parent)
    if re.match(r"(?i)^(?:season[ ._-]*\d+|s\d{1,2}|specials)$", parent_name):
        parent = os.path.dirname(parent)
    if record.get("source") in {"debrid", "soulseek"} and "/" in rel:
        return "download:" + rel.split("/", 1)[0].lower()
    return "folder:" + parent.lower() if parent else "file:" + rel.lower()


def _media_identity(record: dict) -> str:
    """Identity for alternate copies of the same movie or episode."""
    parsed = record.get("parse") if isinstance(record.get("parse"), dict) else {}
    season = parsed.get("season")
    episode = parsed.get("episode")
    if season is not None and episode is not None:
        return "episode:" + "|".join((
            normalize_show_key(parsed.get("show_title") or parsed.get("title")),
            str(int(season)), str(int(episode)), str(int(parsed.get("episode_end") or 0)),
        ))
    title = normalize_show_key(parsed.get("title"))
    year = str(parsed.get("year") or "")
    return "movie:" + title + "|" + year if title else "file:" + str(record.get("rel") or "").lower()


def _prefer_browser_friendly_copies(records: Iterable[dict]) -> list[dict]:
    """Keep one canonical copy per media identity, favouring native playback."""
    chosen: dict[str, dict] = {}
    for record in records:
        key = _media_identity(record)
        current = chosen.get(key)
        if current is None:
            chosen[key] = record
            continue
        candidate_rank = (int(bool(record.get("browser_friendly"))), int(record.get("size") or 0), str(record.get("rel") or "").lower())
        current_rank = (int(bool(current.get("browser_friendly"))), int(current.get("size") or 0), str(current.get("rel") or "").lower())
        if candidate_rank > current_rank:
            chosen[key] = record
    return list(chosen.values())


def classify_video_records(records: Iterable[dict], *, aliases: dict[str, str] | None = None) -> tuple[list[dict], list[dict], list[dict], dict[str, str]]:
    alias_map = dict(aliases or {})
    canonical = [dict(record) for record in records if bool(record.get("canonical", True))]
    # Suppress generated browser-compatible copies when their original exists.
    originals = {re.sub(r"(?i)(?:[ ._-](?:browser|transcoded|compatible))+$", "", os.path.splitext(str(item.get("rel") or ""))[0]) for item in canonical if not item.get("generated_copy")}
    canonical = [item for item in canonical if not item.get("generated_copy") or re.sub(r"(?i)(?:[ ._-](?:browser|transcoded|compatible))+$", "", os.path.splitext(str(item.get("rel") or ""))[0]) not in originals]
    canonical = _prefer_browser_friendly_copies(canonical)
    groups: dict[str, list[dict]] = {}
    for record in canonical:
        groups.setdefault(_group_rel(record), []).append(record)
    movies: list[dict] = []
    loose_videos: list[dict] = []
    show_buckets: dict[str, dict[str, Any]] = {}
    for _group, items in groups.items():
        source = str(items[0].get("source") or "unknown")
        if source == "youtube":
            loose_videos.extend(items)
            continue
        is_show = len(items) >= 2
        if len(items) == 1:
            parsed = items[0].get("parse") or {}
            if source in {"debrid", "soulseek"}:
                movies.extend(items)
                continue
            if parsed.get("episode") is not None:
                is_show = True
            elif parsed.get("year") or len(_words(parsed.get("title"))) >= 2:
                movies.extend(items)
                continue
            else:
                loose_videos.extend(items)
                continue
        if not is_show:
            loose_videos.extend(items)
            continue
        folder_title = os.path.basename(os.path.dirname(str(items[0].get("rel") or "")))
        if re.match(r"(?i)^(?:season[ ._-]*\d+|s\d{1,2}|specials)$", folder_title):
            folder_title = os.path.basename(os.path.dirname(os.path.dirname(str(items[0].get("rel") or ""))))
        label = next((str((item.get("parse") or {}).get("show_title") or "") for item in items if (item.get("parse") or {}).get("show_title")), "") or _display_title(folder_title)
        raw_key = normalize_show_key(label)
        key = alias_map.get(raw_key, raw_key)
        for existing_key, bucket in show_buckets.items():
            if show_keys_close(label, str(bucket.get("label") or "")):
                key = existing_key
                alias_map[raw_key] = existing_key
                break
        bucket = show_buckets.setdefault(key, {"show_key": key, "label": label or "Needs review", "episodes": []})
        bucket["episodes"].extend(items)
    shows = list(show_buckets.values())
    for show in shows:
        show["episodes"].sort(key=lambda item: (
            int((item.get("parse") or {}).get("season") or 0),
            int((item.get("parse") or {}).get("episode") or 0),
            str(item.get("rel") or "").lower(),
        ))
    movies.sort(key=lambda item: (str((item.get("parse") or {}).get("title") or "").lower(), int((item.get("parse") or {}).get("year") or 0), str(item.get("rel") or "").lower()))
    shows.sort(key=lambda item: str(item.get("label") or "").lower())
    loose_videos.sort(key=lambda item: str((item.get("parse") or {}).get("title") or item.get("name") or "").lower())
    return movies, shows, loose_videos, alias_map
