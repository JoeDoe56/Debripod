from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

from .base import TorrentHit
from .normalize import infohash, integer, magnet_for_hash


def parse_rss(payload: str | bytes, *, source_id: str, source_label: str) -> list[TorrentHit]:
    root = ET.fromstring(payload)
    output: list[TorrentHit] = []
    for item in root.findall(".//item"):
        values = {child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip() for child in item}
        links = [str(node.get("url") or "") for node in item.findall("enclosure")]
        description = html.unescape(values.get("description", ""))
        magnet = next((value for value in [values.get("magnet", ""), values.get("link", ""), *links] if value.startswith("magnet:")), "")
        hash_value = infohash(magnet or values.get("infohash") or values.get("hash"))
        if not magnet and hash_value:
            magnet = magnet_for_hash(hash_value)
        size_match = re.search(r"(?:size|length)\s*[:=]\s*([0-9.,]+\s*[kmgtpe]?i?b)", description, re.I)
        title = values.get("title", "")
        if not title:
            continue
        output.append(
            TorrentHit(
                source_id=source_id,
                source_label=source_label,
                title=title,
                infohash=hash_value,
                magnet=magnet,
                size=integer(size_match.group(1)) if size_match else 0,
                published_at=values.get("pubdate", ""),
                detail_url=values.get("guid", "") or (values.get("link", "") if not values.get("link", "").startswith("magnet:") else ""),
                extra={"description": re.sub(r"<[^>]+>", " ", description).strip()},
            )
        )
    return output
