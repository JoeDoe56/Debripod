import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod import runtime_routes as routes
from debripod.Library.search_cache import SEARCH_CACHE_SCHEMA
from debripod.Services.search.pipeline import SearchPipeline


async def _get(monkeypatch, store, history, path):
    runtime = SimpleNamespace(user_id="u1", search_history=history, settings={})
    monkeypatch.setattr(routes, "user_runtime_for", lambda _r: runtime)
    monkeypatch.setattr(routes, "_disk_cache_get", lambda key: store.get(key))
    app = web.Application()
    app.router.add_get("/api/search_history/results", routes.api_search_history_results)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get(path)
        return resp.status, await resp.json()
    finally:
        await client.close()


def test_history_results_prefer_snapshot_and_need_history_entry(monkeypatch):
    payload = {"schema_version": SEARCH_CACHE_SCHEMA, "results": [{"result_id": "a"}], "provider_status": []}
    store = {"history:k1": {"payload": payload}}
    history = [{"q": "alice", "cache_key": "k1"}]
    status, js = asyncio.run(_get(monkeypatch, store, history, "/api/search_history/results?key=k1"))
    assert status == 200 and js["ok"] and js["cached"] and js["results"] == [{"result_id": "a"}] and js["q"] == "alice"
    status, js = asyncio.run(_get(monkeypatch, store, history, "/api/search_history/results?key=other"))
    assert status == 404
    status, js = asyncio.run(_get(monkeypatch, {}, history, "/api/search_history/results?key=k1"))
    assert status == 404


def test_pipeline_snapshots_partial_searches_but_does_not_cache_them():
    class Cache:
        def __init__(self):
            self.full, self.snap = {}, {}
        def set(self, k, p):
            self.full[k] = p
        def set_snapshot(self, k, p):
            self.snap[k] = p
    cache = Cache()
    pipe = SearchPipeline([], cache=cache)
    ctx = SimpleNamespace(search_id="s1", query="q")
    pipe._cache_set(ctx, {"results": [1], "provider_status": [{"status": "error"}]})
    assert "s1" in cache.snap and "s1" not in cache.full
    pipe._cache_set(ctx, {"results": [1], "provider_status": [{"status": "ok"}]})
    assert "s1" in cache.full
