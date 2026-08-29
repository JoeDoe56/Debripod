import json
import asyncio
import time

from debripod.Services.search.models import ProviderSearchResponse
from debripod.Services.search.pipeline import SearchPipeline
from debripod.Services.search.providers import SearchContext


def _row(index, group, source, *, related=True):
    labels = {"library": "Library", "soulseek": "Soulseek", "torrent": "Torrent", "youtube": "YouTube", "local_index": "Local Index"}
    kind = "torrent" if source == "torrent" else "song"
    provider_data = {"infohash": f"{index:040x}", "indexer_labels": ["Synthetic"], "indexer_ids": ["synthetic"], "source_urls": [], "seeders": index % 50, "leechers": 0, "verified": False, "magnet": "", "category": "Audio"} if source == "torrent" else {}
    return {
        "result_id": f"{source}:{index}", "provider_group": group, "source": source, "source_label": labels[source],
        "kind": kind, "kind_label": "Torrent" if kind == "torrent" else "Songs",
        "title": f"Alice in Chains synthetic result {index}" if related else f"Unrelated cookbook volume {index}",
        "subtitle": "", "artist": "Alice in Chains" if related else "", "album": "", "year": "", "duration": 0,
        "thumbnail": "", "canonical_url": "", "stable_source_id": str(index), "search_blob": "",
        "filter_values": {"sources": [], "types": [], "indexers": [], "media": []}, "match_confidence": 0,
        "rank_score": 0, "browse_available": False, "stream_available": False, "download_available": False,
        "files_loaded": False, "file_count": 0, "size": 0, "files": [], "provider_data": provider_data,
    }


class SyntheticProvider:
    def __init__(self, group, rows):
        self.provider_group, self.rows = group, rows

    async def search(self, query, context):
        return ProviderSearchResponse(self.provider_group, {"status": "ok"}, self.rows)


def test_pipeline_handles_30000_without_cap_or_quadratic_behavior():
    specs = [("library", "library"), ("soulseek", "soulseek"), ("torrents", "torrent"), ("ytdlp", "youtube")]
    providers = []
    related_count = 0
    cursor = 0
    for group, source in specs:
        rows = []
        for local in range(7500):
            related = local >= 25
            rows.append(_row(cursor, group, source, related=related))
            related_count += int(related)
            cursor += 1
        providers.append(SyntheticProvider(group, rows))
    context = SearchContext("test", "Alice in Chains", "alice in chains", {}, {}, "perf-30000")
    started = time.perf_counter()
    first = asyncio.run(SearchPipeline(providers).search_once(context.query, context))
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0
    assert len(first["results"]) == related_count
    assert all("Unrelated cookbook" not in row["title"] for row in first["results"])
    ids = [row["result_id"] for row in first["results"]]
    second_context = SearchContext("test", "Alice in Chains", "alice in chains", {}, {}, "perf-30000-b")
    second = asyncio.run(SearchPipeline(providers).search_once(second_context.query, second_context))
    assert ids == [row["result_id"] for row in second["results"]]
    restored = json.loads(json.dumps({"results": first["results"]}))
    assert [row["result_id"] for row in restored["results"]] == ids
    assert [row["filter_values"] for row in restored["results"]] == [row["filter_values"] for row in first["results"]]
