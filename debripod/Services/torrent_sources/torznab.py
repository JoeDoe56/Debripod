from __future__ import annotations

import xml.etree.ElementTree as ET

from .base import TorrentHit
from .normalize import infohash, integer, magnet_for_hash


def parse_torznab(payload: str | bytes, *, source_id: str, source_label: str) -> list[TorrentHit]:
    root = ET.fromstring(payload)
    output: list[TorrentHit] = []
    for item in root.findall(".//item"):
        values: dict[str, str] = {}
        enclosures: list[str] = []
        categories: list[str] = []
        for child in item:
            tag = child.tag.rsplit("}", 1)[-1].lower()
            if tag == "attr":
                values[str(child.get("name") or "").lower()] = str(child.get("value") or "")
            elif tag == "enclosure":
                enclosures.append(str(child.get("url") or ""))
                if child.get("length"):
                    values.setdefault("size", str(child.get("length")))
            elif tag == "category":
                categories.append((child.text or "").strip())
            else:
                values[tag] = (child.text or "").strip()
        title = values.get("title", "")
        if not title:
            continue
        candidates = [values.get("magneturl", ""), values.get("downloadvolumefactor", ""), values.get("link", ""), *enclosures]
        magnet = next((value for value in candidates if value.startswith("magnet:")), "")
        hash_value = infohash(values.get("infohash") or values.get("hash") or magnet)
        if not magnet and hash_value:
            magnet = magnet_for_hash(hash_value)
        peers = integer(values.get("peers"))
        seeders = integer(values.get("seeders"))
        output.append(
            TorrentHit(
                source_id=source_id,
                source_label=source_label,
                title=title,
                infohash=hash_value,
                magnet=magnet,
                size=integer(values.get("size")),
                seeders=seeders,
                leechers=integer(values.get("leechers")) or max(0, peers - seeders),
                category=", ".join(value for value in categories if value) or values.get("category", ""),
                published_at=values.get("pubdate", ""),
                detail_url=values.get("guid", "") or (values.get("link", "") if not values.get("link", "").startswith("magnet:") else ""),
                torrent_url=next((value for value in enclosures if value and not value.startswith("magnet:")), ""),
                extra={"peers": peers},
            )
        )
    return output
