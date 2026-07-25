from __future__ import annotations

# Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818

import re
from urllib.parse import parse_qs, urlparse


_HEX_INFO_HASH = re.compile(r"^[0-9a-fA-F]{40}$")
_BASE32_INFO_HASH = re.compile(r"^[A-Z2-7]{32}$", re.IGNORECASE)


def classify_link_input(value: object) -> str:
    text = str(value or "").strip()
    if _valid_magnet(text):
        return "magnet"
    try:
        parsed = urlparse(text)
    except ValueError:
        return "query"
    if parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc):
        return "ytdlp_url"
    return "query"


def _valid_magnet(value: str) -> bool:
    if not value.lower().startswith("magnet:?"):
        return False
    try:
        values = parse_qs(urlparse(value).query).get("xt", [])
    except ValueError:
        return False
    for item in values:
        if not str(item).lower().startswith("urn:btih:"):
            continue
        info_hash = str(item).split(":")[-1]
        if _HEX_INFO_HASH.fullmatch(info_hash) or _BASE32_INFO_HASH.fullmatch(info_hash):
            return True
    return False
