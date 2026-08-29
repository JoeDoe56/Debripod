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
    filters["sources"] = _unique_values(filters.get("sources"), (later.get("filter_values") or {}).get("sources"))
    filters["indexers"] = _unique_values(filters.get("indexers"), target.get("indexer_labels"))
    _fill_empty(winner, later)


class TorrentAccumulator:
    """Incrementally merge Local Index and remote torrent rows by canonical identity."""

    def __init__(self):
        self.rows: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self._unique_counter = 0

    def _key(self, row: dict[str, Any]) -> str:
        key = torrent_dedupe_key(row)
        if key:
            return key
        self._unique_counter += 1
        return "unique:" + str(row.get("result_id") or self._unique_counter)

    def upsert(self, result: Any) -> tuple[dict[str, Any], bool]:
        row = _dict(result)
        key = self._key(row)
        winner = self.rows.get(key)
        if winner is None:
            winner = deepcopy(row)
            self.rows[key] = winner
            self.order.append(key)
            return winner, True
        _merge_torrent(winner, row, key)
        return winner, False

    def ingest(self, result: Any) -> dict[str, Any]:
        return self.upsert(result)[0]

    def seed(self, results: list[Any]) -> list[dict[str, Any]]:
        return [self.ingest(result) for result in results]

    def values(self) -> list[dict[str, Any]]:
        return [self.rows[key] for key in self.order]


def deduplicate_torrents(results: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    accumulator = TorrentAccumulator()
    for item in results:
        row = _dict(item)
        if row.get("source") not in {"torrent", "local_index"}:
            output.append(row)
            continue
        winner, created = accumulator.upsert(row)
        if created:
            output.append(winner)
    return output


merge_youtube_duplicates = deduplicate_youtube
merge_torrent_duplicates = deduplicate_torrents


class IncrementalDeduplicator:
    """O(1)-average incremental upserts with the same final winner rules."""

    def __init__(self, torrent_accumulator_factory=TorrentAccumulator):
        self.rows: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.torrents = torrent_accumulator_factory()
        self.youtube_ids: dict[str, str] = {}

    @staticmethod
    def _youtube_priority(row: dict[str, Any]) -> tuple[int, int]:
        provider = row.get("provider_data") if isinstance(row.get("provider_data"), dict) else {}
        return (
            0 if bool(provider.get("youtube_music")) else 1,
            _CATEGORY_ORDER.get(str(row.get("kind_label") or ""), len(_CATEGORY_ORDER)),
        )

    def _store(self, row: dict[str, Any]) -> dict[str, Any]:
        result_id = str(row.get("result_id") or "")
        if result_id not in self.rows:
            self.order.append(result_id)
        self.rows[result_id] = row
        return row

    def ingest(self, row: dict[str, Any]) -> dict[str, Any]:
        source = str(row.get("source") or "")
        if source in {"torrent", "local_index"}:
            winner, created = self.torrents.upsert(row)
            existing_id = str(winner.get("result_id") or "")
            if created:
                return self._store(winner)
            self.rows[existing_id] = winner
            return winner
        if source == "youtube":
            key = youtube_dedupe_key(row) or "unique:" + str(row.get("result_id") or len(self.order))
            existing_id = self.youtube_ids.get(key)
            if existing_id is None:
                winner = deepcopy(row)
                self.youtube_ids[key] = str(winner["result_id"])
                return self._store(winner)
            current = self.rows[existing_id]
            if self._youtube_priority(row) < self._youtube_priority(current):
                winner = deepcopy(row)
                _fill_empty(winner, current)
                winner["result_id"] = existing_id
                self.rows[existing_id] = winner
                return winner
            _fill_empty(current, row)
            return current
        result_id = str(row.get("result_id") or "")
        return self._store(deepcopy(row))

    def values(self) -> list[dict[str, Any]]:
        return [self.rows[result_id] for result_id in self.order if result_id in self.rows]
