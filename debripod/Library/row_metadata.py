"""Public browsing metadata shared by fresh and cached facet responses."""
from __future__ import annotations

import json

PUBLIC_AUDIO_FIELDS = ("title", "artist", "album", "album_artist", "genre", "track", "year",
                       "duration", "codec", "bit_depth", "sample_rate", "bitrate", "source", "quality", "container", "size", "file_size")


def enrich_browsing_payload(payload: dict, data: dict, root_id: str) -> dict:
    tracks = data.get("tracks") or []
    by_file = {(str(t.get("root_id") or root_id), t.get("rel")): t for t in tracks}
    album_stats = {}
    album_roots = {}
    for track in tracks:
        key = (track.get("artist") or "", track.get("album") or "")
        count, duration = album_stats.get(key, (0, 0))
        album_stats[key] = (count + 1, duration + float(track.get("duration") or 0))
        album_roots.setdefault(key, set()).add(str(track.get("root_id") or root_id))
    result = dict(payload)
    if "items" in result:
        rows = []
        for row in result["items"]:
            item = dict(row)
            if item.get("kind") == "track":
                track = by_file.get((str(item.get("root_id") or root_id), item.get("rel")), {})
                item = {**{key: track[key] for key in PUBLIC_AUDIO_FIELDS if track.get(key) is not None}, **item, "media": "audio"}
            elif item.get("kind") == "album":
                try:
                    value = json.loads(item.get("value") or "{}")
                except (ValueError, TypeError):
                    value = {}
                if isinstance(value, dict) and value.get("album"):
                    item["album"] = value["album"]
                    item["artist"] = value.get("artist") or ""
                    item["label"] = value["album"]
                    stats = album_stats.get((item["artist"], item["album"]))
                    if stats:
                        item["track_count"], item["duration"] = stats
                        item["collection_root_ids"] = sorted(album_roots[(item["artist"], item["album"])])
            rows.append(item)
        result["items"] = rows
    if "categories" in result:
        counts = {
            "songs": len(tracks),
            "artists": len({t.get("artist") for t in tracks if t.get("artist")}),
            "albums": len({(t.get("artist"), t.get("album")) for t in tracks if t.get("album")}),
            "genres": len({t.get("genre") for t in tracks if t.get("genre")}),
        }
        for category in ("movies", "shows", "videos", "playlists"):
            if isinstance(data.get(category), (list, dict)):
                counts[category] = len(data[category])
        result["categories"] = [{**row, **({"count": counts[row["key"]]} if row["key"] in counts else {})}
                                for row in result["categories"]]
    return result
