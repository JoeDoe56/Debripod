from __future__ import annotations

import base64
import datetime as dt
import re
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse


_HEX_HASH = re.compile(r"^[0-9a-f]{40}$", re.I)
_BASE32_HASH = re.compile(r"^[a-z2-7]{32}$", re.I)


def infohash(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("urn:btih:"):
        text = text[9:]
    if _HEX_HASH.fullmatch(text):
        return text.lower()
    if _BASE32_HASH.fullmatch(text):
        try:
            return base64.b32decode(text.upper()).hex()
        except ValueError:
            return ""
    if text.startswith("magnet:"):
        for xt in parse_qs(urlparse(text).query).get("xt") or []:
            normalized = infohash(xt)
            if normalized:
                return normalized
    return ""


def magnet_for_hash(value: Any) -> str:
    normalized = infohash(value)
    return f"magnet:?xt=urn:btih:{normalized}" if normalized else ""


def integer(value: Any) -> int:
    text = str(value or "0").replace(",", "").strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([kmgtpe]?i?b)?", text, re.I)
    if not match:
        try:
            return int(float(text))
        except ValueError:
            return 0
    unit = (match.group(2) or "").casefold()
    power = {"": 0, "b": 0, "kb": 1, "kib": 1, "mb": 2, "mib": 2, "gb": 3, "gib": 3, "tb": 4, "tib": 4, "pb": 5, "pib": 5, "eb": 6, "eib": 6}.get(unit, 0)
    return int(float(match.group(1)) * (1024**power))


def timestamp_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
        except (ValueError, OSError, OverflowError):
            pass
    return str(value)


def records(payload: Any, keys: Iterable[str] = ("results", "data", "hits", "items", "torrents")) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = records(value, keys)
            if nested:
                return nested
    return []
