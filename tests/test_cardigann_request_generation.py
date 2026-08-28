from debripod.Services.indexers.cardigann.engine import CardigannEngine
from debripod.Services.indexers.cardigann.schema import CardigannDefinition


def test_get_post_headers_delay_encoding_and_duplicate_suppression():
    definition = CardigannDefinition.from_dict({
        "id": "demo", "name": "Demo", "type": "public", "links": ["https://tracker.test/base/"],
        "search": {"headers": {"X-Query": "{{ .Query.Query }}"}, "paths": [
            {"path": "/search", "inputs": {"q": "{{ .Query.Query }}"}, "requestDelay": 1},
            {"path": "/search", "inputs": {"q": "{{ .Query.Query }}"}},
            {"path": "/form", "method": "POST", "inputs": {"query": "{{ .Query.Query }}"}},
        ]},
    })
    requests = CardigannEngine(definition).generate_search_requests("Alice in Chains")
    assert len(requests) == 2
    assert requests[0].method == "GET" and "q=Alice+in+Chains" in requests[0].url
    assert requests[0].headers["X-Query"] == "Alice in Chains" and requests[0].delay_seconds == 1
    assert requests[1].method == "POST" and requests[1].data["query"] == "Alice in Chains"


def test_requires_setup_is_not_executed():
    definition = CardigannDefinition.from_dict({"id": "private", "name": "Private", "type": "private", "links": ["https://x"], "search": {"paths": [{}]}})
    import pytest
    with pytest.raises(PermissionError, match="requires_setup"):
        CardigannEngine(definition).generate_search_requests("x")


def test_prowlarr_defaults_top_level_variables_raw_inputs_and_method_template():
    definition = CardigannDefinition.from_dict({
        "id": "upstream", "name": "Upstream", "type": "public", "links": ["https://tracker.test/"],
        "requestDelay": 2,
        "settings": [{"name": "sort", "type": "select", "default": "seeders"}],
        "search": {"inputs": {"$raw": "category=0&", "q": "{{ .Keywords }}", "sort": "{{ .Config.sort }}"}, "paths": [
            {"path": "search", "method": "{{ if .Keywords }}post{{ else }}get{{ end }}"}
        ]},
    })
    request = CardigannEngine(definition).generate_search_requests("ubuntu")[0]
    assert request.method == "POST"
    assert request.data == "category=0&q=ubuntu&sort=seeders"
    assert request.delay_seconds == 2
