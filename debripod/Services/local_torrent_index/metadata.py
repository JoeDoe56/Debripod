from __future__ import annotations

from typing import Any

from ...Library.video_parse import extract_resolution, extract_source_quality, parse_video_filename


RESOLUTION_CODES = {"480p": 480, "576p": 576, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160, "4320p": 4320}
QUALITY_CODES = {"Cam": 1, "DVD": 2, "HDTV": 3, "WEB": 4, "BluRay": 5, "Remux": 6}
QUALITY_LABELS = {value: key for key, value in QUALITY_CODES.items()}


def parse_release_name(name: str) -> dict[str, Any]:
    """Parse a torrent release name with DebriPod's existing filename parser."""
    value = str(name or "").strip()
    if not value:
        return {"parsed_title": "", "year": None, "resolution": None, "quality": None}
    try:
        parsed = parse_video_filename(value)
        resolution = RESOLUTION_CODES.get(extract_resolution(value))
        quality = QUALITY_CODES.get(extract_source_quality(value))
        return {
            "parsed_title": str(parsed.get("title") or ""),
            "year": int(parsed["year"]) if parsed.get("year") else None,
            "resolution": resolution,
            "quality": quality,
        }
    except Exception:
        return {"parsed_title": "", "year": None, "resolution": None, "quality": None}
