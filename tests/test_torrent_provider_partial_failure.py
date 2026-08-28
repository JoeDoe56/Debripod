from types import SimpleNamespace

from debripod.Services.indexers.service import IndexerService
from tests.test_torrent_provider_merge import Client, Definition, Engine, Status


class Store:
    def list_active_definitions(self): return [Definition("good", "Good"), Definition("bad", "Bad")]


class SometimesEngine(Engine):
    def generate_search_requests(self, query):
        if self.definition.id == "bad": raise RuntimeError("definition failed")
        return super().generate_search_requests(query)


def test_one_failed_indexer_does_not_fail_provider_group():
    response = IndexerService(Store(), enabled_ids=["good", "bad"], status_store=Status(), engine_factory=SometimesEngine, client_factory=lambda ident: Client()).search("Alice in Chains")
    assert len(response.results) == 1 and response.error == ""
    assert any(item["indexer_id"] == "bad" and item["status"] == "error" for item in response.source_status)


def test_requires_setup_and_blocked_are_skipped():
    setup = Definition("setup", "Setup"); setup.requires_setup = True; setup.eligible = False
    class SetupStore:
        def list_active_definitions(self): return [setup]
    response = IndexerService(SetupStore(), enabled_ids=["setup"], status_store=Status(), engine_factory=SometimesEngine, client_factory=lambda ident: Client()).search("query")
    assert not response.results and response.source_status[0]["status"] == "requires_setup"


def test_search_mirror_fallback_is_bounded_and_skips_failed_paths():
    calls = []
    class MirrorEngine(Engine):
        def generate_search_requests(self, query):
            return [SimpleNamespace(method="GET", url=f"https://m{mirror}.test/p{path}", headers={}, data=None, base_url=f"https://m{mirror}.test/", preflight=False, follow_redirects=True, delay_seconds=0) for mirror in range(5) for path in range(2)]
        def parse(self, response):
            return SimpleNamespace(error_classification="http_error", no_results=False, diagnostic_summary="HTTP 403", releases=[])
    class MirrorClient:
        def request(self, _method, url, **_kwargs): calls.append(url); return object()
    rows, status = IndexerService(Store(), enabled_ids=["good"], status_store=Status(), engine_factory=MirrorEngine, client_factory=lambda _ident: MirrorClient())._search_one(Definition("good", "Good"), "query")
    assert not rows and status["status"] == "error"
    assert calls == ["https://m0.test/p0", "https://m1.test/p0", "https://m2.test/p0"]


def test_unresolved_challenge_stops_all_mirror_fallback():
    calls = []
    class ChallengeEngine(Engine):
        def generate_search_requests(self, query):
            return [SimpleNamespace(method="GET", url=f"https://m{mirror}.test/search", headers={}, data=None, base_url=f"https://m{mirror}.test/", preflight=False, follow_redirects=True, delay_seconds=0) for mirror in range(3)]
    class ChallengeClient:
        def request(self, _method, url, **_kwargs):
            calls.append(url)
            return SimpleNamespace(_debripod_challenge_failed=True, _debripod_challenge_error="challenge timeout")
    rows, status = IndexerService(Store(), enabled_ids=["good"], status_store=Status(), engine_factory=ChallengeEngine, client_factory=lambda _ident: ChallengeClient())._search_one(Definition("good", "Good"), "query")
    assert not rows and calls == ["https://m0.test/search"]
    assert "challenge timeout" in status["error"]
