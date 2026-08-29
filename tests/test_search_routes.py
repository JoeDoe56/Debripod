import asyncio
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import debripod.runtime_routes as routes


def _result():
    return {"result_id":"library:r:song:x","provider_group":"library","source":"library","source_label":"Library","kind":"song","kind_label":"Songs","title":"Alice in Chains","subtitle":"","artist":"","album":"","year":"","duration":0,"thumbnail":"","canonical_url":"","stable_source_id":"x","search_blob":"alice in chains","filter_values":{"sources":["Library"],"types":["Songs"],"indexers":[],"media":["music"]},"match_confidence":1,"rank_score":1,"browse_available":False,"stream_available":True,"download_available":False,"files_loaded":False,"file_count":0,"size":0,"files":[],"provider_data":{"root_id":"r","rel":"x","entity_key":"x","navigation":{}}}


class Pipeline:
    async def search_stream(self, query, context):
        yield {"event":"start","search_id":context.search_id,"query":query}
        yield {"event":"source","search_id":context.search_id,"provider_group":"library","source_status":{"status":"ok"},"status":"ok","error":"","duration_ms":1,"cached":False,"result_count":1,"results":[_result()]}
        yield {"event":"source","search_id":context.search_id,"provider_group":"torrents","source_status":{"status":"error"},"status":"error","error":"offline","duration_ms":1,"cached":False,"result_count":0,"results":[]}
        yield {"event":"done","search_id":context.search_id,"query":query,"results":[_result()],"provider_status":[{"provider_group":"library","error":""},{"provider_group":"torrents","error":"offline"}]}

    async def search_once(self, query, context):
        final = {}
        async for event in self.search_stream(query, context):
            if event["event"] == "done":
                final = event
        return final


async def _request(monkeypatch, path: str, generation: str = "7"):
    cache_keys = []
    runtime = SimpleNamespace(
        pipeline=Pipeline(),
        local_index=SimpleNamespace(diagnostics=lambda: {"meta": {"local_index_generation": generation}}),
    )
    monkeypatch.setattr(routes, "_current_settings_username", lambda _request: "tester")
    monkeypatch.setattr(routes, "ensure_app_settings", lambda **_kwargs: {
        "LOCAL_INDEX_ENABLED": True,
        "TORRENT_SEARCH_ENABLED_SOURCES": ["knaben"],
        "SOULSEEK_USERNAME": "",
        "SOULSEEK_PASSWORD": "",
        "SOULSEEK_SEARCH_MAX_RESULTS": 5000,
        "YOUTUBE_SEARCH_LIMIT": 24,
    })
    monkeypatch.setattr(routes, "_active_search_runtime", lambda _request=None: runtime)
    monkeypatch.setattr(routes, "_disk_cache_get", lambda key: cache_keys.append(key) or None)
    monkeypatch.setattr(routes, "library_root_versions", lambda: {})
    monkeypatch.setattr(routes, "record_search_history", lambda *_args, **_kwargs: None)
    app = web.Application()
    app.router.add_get("/api/libsearch/combined", routes.api_libsearch_combined)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.get(path)
        return response.status, await response.text(), cache_keys[0]
    finally:
        await client.close()


def test_combined_stream_orders_events_and_preserves_partial_failure(monkeypatch):
    status, body, _cache_key = asyncio.run(_request(monkeypatch, "/api/libsearch/combined?q=Alice&stream=1"))
    assert status == 200
    events = [json.loads(line) for line in body.splitlines()]
    assert [event["event"] for event in events] == ["start", "source", "source", "done"]
    assert events[-1]["provider_status"][-1]["error"] == "offline"


def test_combined_nonstream_is_canonical_without_provider_arrays(monkeypatch):
    status, body, _cache_key = asyncio.run(_request(monkeypatch, "/api/libsearch/combined?q=Alice"))
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] and len(payload["results"]) == 1
    assert set(payload["results"][0]) == set(_result())
    assert not ({"knaben_results", "slsk_users", "youtube_results"} & set(payload))


def test_combined_cache_key_normalizes_query_and_changes_with_local_index_generation(monkeypatch):
    _status, _body, first = asyncio.run(_request(monkeypatch, "/api/libsearch/combined?q=Alice", "7"))
    _status, _body, normalized = asyncio.run(_request(monkeypatch, "/api/libsearch/combined?q=ALICE", "7"))
    _status, _body, updated = asyncio.run(_request(monkeypatch, "/api/libsearch/combined?q=Alice", "8"))
    assert first == normalized
    assert updated != first
