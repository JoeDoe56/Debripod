import json
from types import SimpleNamespace

import debripod.auth as auth
import debripod.runtime_routes as routes


def _result():
    return {"result_id":"library:r:song:x","provider_group":"library","source":"library","source_label":"Library","kind":"song","kind_label":"Songs","title":"Alice in Chains","subtitle":"","artist":"","album":"","year":"","duration":0,"thumbnail":"","canonical_url":"","stable_source_id":"x","search_blob":"alice in chains","filter_values":{"sources":["Library"],"types":["Songs"],"indexers":[],"media":["music"]},"match_confidence":1,"rank_score":1,"browse_available":False,"stream_available":True,"download_available":False,"files_loaded":False,"file_count":0,"size":0,"files":[],"provider_data":{"root_id":"r","rel":"x","entity_key":"x","navigation":{}}}


class Pipeline:
    def search_stream(self, query, context):
        yield {"event":"start","search_id":context.search_id,"query":query}
        yield {"event":"source","search_id":context.search_id,"provider_group":"library","source_status":{"status":"ok"},"error":"","duration_ms":1,"cached":False,"result_count":1,"results":[_result()]}
        yield {"event":"source","search_id":context.search_id,"provider_group":"torrents","source_status":{"status":"error"},"error":"offline","duration_ms":1,"cached":False,"result_count":0,"results":[]}
        yield {"event":"done","search_id":context.search_id,"query":query,"results":[_result()],"provider_status":[{"provider_group":"library","error":""},{"provider_group":"torrents","error":"offline"}]}

    def search_once(self, query, context):
        return list(self.search_stream(query, context))[-1]


def _client(monkeypatch):
    monkeypatch.setattr(auth, "_find_user", lambda username: {"username": username, "password_hash": "test"})
    monkeypatch.setattr(routes, "_apply_runtime_settings_for_user", lambda _username: {})
    monkeypatch.setattr(routes, "_active_search_runtime", lambda: SimpleNamespace(pipeline=Pipeline()))
    monkeypatch.setattr(routes, "_disk_cache_get", lambda _key: None)
    monkeypatch.setattr(routes, "library_root_versions", lambda: {})
    monkeypatch.setattr(routes, "record_search_history", lambda *_args, **_kwargs: None)
    app = routes.create_app(); app.config.update(TESTING=True, SECRET_KEY="route-test")
    client = app.test_client()
    with client.session_transaction() as session: session["username"] = "tester"
    return client


def test_combined_stream_orders_events_and_preserves_partial_failure(monkeypatch):
    response = _client(monkeypatch).get("/api/libsearch/combined?q=Alice&stream=1")
    assert response.status_code == 200
    events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
    assert [event["event"] for event in events] == ["start", "source", "source", "done"]
    assert events[-1]["provider_status"][-1]["error"] == "offline"


def test_combined_nonstream_is_canonical_without_provider_arrays(monkeypatch):
    payload = _client(monkeypatch).get("/api/libsearch/combined?q=Alice").get_json()
    assert payload["ok"] and len(payload["results"]) == 1
    assert set(payload["results"][0]) == set(_result())
    assert not ({"knaben_results", "slsk_users", "youtube_results"} & set(payload))
