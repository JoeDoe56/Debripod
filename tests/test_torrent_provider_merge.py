from types import SimpleNamespace

from debripod.Services.indexers.service import IndexerService


class Definition:
    def __init__(self, ident, name):
        self.id, self.name, self.requires_setup, self.eligible, self.parse_error = ident, name, False, True, ""


class Store:
    def list_active_definitions(self): return [Definition("a", "Alpha"), Definition("b", "Beta")]


class Status:
    def is_blocked(self, ident): return False


class Engine:
    def __init__(self, definition): self.definition = definition
    def generate_search_requests(self, query): return [SimpleNamespace(method="GET", url="https://x", headers={}, data=None)]
    def parse(self, response):
        return SimpleNamespace(error_classification="", no_results=False, diagnostic_summary="", releases=[{"title": "Alice in Chains Dirt", "infohash": "ABC", "magnet": "magnet:?xt=urn:btih:abc", "seeders": 2 if self.definition.id == "a" else 20, "details": "https://" + self.definition.id}])


class Client:
    def request(self, *args, **kwargs): return object()


def test_concurrent_indexer_hash_merge_retains_sources():
    service = IndexerService(Store(), enabled_ids=["a", "b"], status_store=Status(), engine_factory=Engine, client_factory=lambda ident: Client())
    response = service.search("Alice in Chains")
    assert len(response.results) == 1
    data = response.results[0]["provider_data"]
    assert data["indexer_ids"] == ["a", "b"] or data["indexer_ids"] == ["b", "a"]
    assert set(data["indexer_labels"]) == {"Alpha", "Beta"}
    assert data["seeders"] == 20 and set(data["source_urls"]) == {"https://a", "https://b"}
