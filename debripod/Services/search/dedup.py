from __future__ import annotations

from copy import deepcopy
from typing import Any

from .identity import torrent_dedupe_key, youtube_dedupe_key


YOUTUBE_CATEGORY_PRIORITY = [
    "Songs", "Music Videos", "Albums", "Artists", "Music Playlists",
    "Podcasts", "Episodes", "Videos", "Playlists", "Channels",
]
_CATEGORY_ORDER = {label: index for index, label in enumerate(YOUTUBE_CATEGORY_PRIORITY)}


def _dict(result: Any) -> dict[str, Any]:
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _fill_empty(winner: dict[str, Any], later: dict[str, Any]) -> None:
    protected = {"result_id", "provider_group", "source", "source_label", "kind", "kind_label"}
    for key, value in later.items():
        if key == "provider_data":
            target = winner.setdefault("provider_data", {})
            for nested_key, nested_value in (value or {}).items():
                if nested_key in {"youtube_music", "search_category"}:
                    continue
                if _empty(target.get(nested_key)) and not _empty(nested_value):
                    target[nested_key] = deepcopy(nested_value)
        elif key not in protected and _empty(winner.get(key)) and not _empty(value):
            winner[key] = deepcopy(value)


def deduplicate_youtube(results: list[Any]) -> list[dict[str, Any]]:
    rows = [_dict(item) for item in results]
    youtube = [row for row in rows if row.get("source") == "youtube"]
    other = [row for row in rows if row.get("source") != "youtube"]
    indexed = list(enumerate(youtube))
    indexed.sort(key=lambda pair: (
        0 if bool((pair[1].get("provider_data") or {}).get("youtube_music")) else 1,
        _CATEGORY_ORDER.get(str(pair[1].get("kind_label") or ""), len(_CATEGORY_ORDER)),
        pair[0],
    ))
    winners: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    for _index, row in indexed:
        key = youtube_dedupe_key(row) or "unique:" + str(row.get("result_id") or _index)
        if key not in winners:
            winner = deepcopy(row)
            winners[key] = winner
            ordered.append(winner)
        else:
            _fill_empty(winners[key], row)
    return ordered + other


def _unique_values(*values: Any) -> list[str]:
    output: list[str] = []
    for value in values:
        for item in value or []:
            text = str(item)
            if text and text not in output:
                output.append(text)
    return output


def _merge_torrent(winner: dict[str, Any], later: dict[str, Any], key: str) -> None:
    target = winner.setdefault("provider_data", {})
    incoming = later.get("provider_data") if isinstance(later.get("provider_data"), dict) else {}
    for name in ("indexer_ids", "indexer_labels", "source_urls"):
        target[name] = _unique_values(target.get(name), incoming.get(name))
    target["seeders"] = max(int(target.get("seeders") or 0), int(incoming.get("seeders") or 0))
    target["leechers"] = max(int(target.get("leechers") or 0), int(incoming.get("leechers") or 0))
    target["verified"] = bool(target.get("verified") or incoming.get("verified"))
    canonical_hash = key.removeprefix("torrent:")
    current_magnet = str(target.get("magnet") or "")
    incoming_magnet = str(incoming.get("magnet") or "")
    if incoming_magnet and canonical_hash in incoming_magnet.lower() and canonical_hash not in current_magnet.lower():
        target["magnet"] = incoming_magnet
    filters = winner.setdefault("filter_values", {})
    filters["indexers"] = _unique_values(filters.get("indexers"), target.get("indexer_labels"))
    _fill_empty(winner, later)


def deduplicate_torrents(results: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    winners: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(results):
        row = _dict(item)
        if row.get("source") != "torrent":
            output.append(row)
            continue
        key = torrent_dedupe_key(row)
        if not key:
            key = "unique:" + str(row.get("result_id") or index)
        if key not in winners:
            winner = deepcopy(row)
            winners[key] = winner
            output.append(winner)
        else:
            _merge_torrent(winners[key], row, key)
    return output


merge_youtube_duplicates = deduplicate_youtube
merge_torrent_duplicates = deduplicate_torrents
