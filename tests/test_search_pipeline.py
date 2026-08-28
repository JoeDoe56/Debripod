import threading
import time

from debripod.Services.search.models import ProviderSearchResponse
from debripod.Services.search.pipeline import SearchPipeline
from debripod.Services.search.providers import SearchContext


def _canonical(result_id, group, source, title):
    labels = {"library": "Library", "soulseek": "Soulseek", "torrent": "Torrent", "youtube": "YouTube", "soundcloud": "SoundCloud"}
    kind = "torrent" if source == "torrent" else "song"
    return {
        "result_id": result_id, "provider_group": group, "source": source, "source_label": labels[source],
        "kind": kind, "kind_label": "Torrent" if kind == "torrent" else "Songs", "title": title,
        "subtitle": "", "artist": "", "album": "", "year": "", "duration": 0, "thumbnail": "",
        "canonical_url": "", "stable_source_id": "", "search_blob": "",
        "filter_values": {"sources": [], "types": [], "indexers": [], "media": []},
        "match_confidence": 0, "rank_score": 0, "browse_available": False, "stream_available": False,
        "download_available": False, "files_loaded": False, "file_count": 0, "size": 0, "files": [],
        "provider_data": {},
    }


class Provider:
    def __init__(self, group, rows, delay=0, error=None):
        self.provider_group, self.rows, self.delay, self.error = group, rows, delay, error

    def search(self, query, context):
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return ProviderSearchResponse(self.provider_group, {"status": "ok"}, self.rows)


def _context():
    return SearchContext("user", "Alice in Chains", "alice in chains", {}, {}, "search-1", threading.Event())


def test_pipeline_streams_completion_order_keeps_partial_success_and_rejects_unrelated():
    providers = [
        Provider("library", [_canonical("library:1", "library", "library", "Alice in Chains")], delay=.03),
        Provider("soulseek", [_canonical("soulseek:1", "soulseek", "soulseek", "Chainsaw Repair Manual")]),
        Provider("torrents", [], error=RuntimeError("offline")),
    ]
    events = list(SearchPipeline(providers).search_stream("Alice in Chains", _context()))
    assert events[0]["event"] == "start" and events[-1]["event"] == "done"
    assert len([event for event in events if event["event"] == "source"]) == 3
    assert [row["result_id"] for row in events[-1]["results"]] == ["library:1"]
    assert any(status["error"] == "offline" for status in events[-1]["provider_status"])


def test_pipeline_has_no_total_cap():
    rows = [_canonical(f"library:{index}", "library", "library", f"Alice in Chains song {index}") for index in range(1000)]
    final = SearchPipeline([Provider("library", rows)]).search_once("Alice in Chains", _context())
    assert len(final["results"]) == 1000
