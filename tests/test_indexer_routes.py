from types import SimpleNamespace

import debripod.auth as auth
import debripod.runtime_routes as routes
from debripod.Services.indexers.cardigann.schema import CardigannDefinition, SettingField


def _definition(identifier, *, setup=False):
    fields = [SettingField("token", type="password", label="Token", default="", required=True)] if setup else []
    return CardigannDefinition(identifier, identifier.title(), "public", ["https://example.test"], fields, {}, {}, {}, {"paths": []}, {}, [], {}, [], origin="official")


class Store:
    def __init__(self): self.rows = [_definition("public"), _definition("private", setup=True)]
    def list_active_definitions(self): return self.rows
    def load_definition(self, identifier): return next((row for row in self.rows if row.id == identifier), None)


def _client(monkeypatch):
    store = Store(); status = SimpleNamespace(get=lambda _id: SimpleNamespace(disabled_until=None,last_error_category=""), record_success=lambda *_a, **_k: None)
    service = SimpleNamespace(status_store=status, _search_one=lambda definition, query: ([{"title":query}], {"status":"ok","indexer_id":definition.id}), resolve_release=lambda identifier, release: {"magnet":"magnet:?xt=urn:btih:" + "a" * 40,"infohash":"a" * 40})
    runtime = SimpleNamespace(definition_store=store, indexer_service=service)
    settings = {"INDEXER_ENABLED_IDS":["public"]}
    monkeypatch.setattr(auth, "_find_user", lambda username: {"username":username,"password_hash":"test"})
    monkeypatch.setattr(routes, "_active_search_runtime", lambda: runtime)
    monkeypatch.setattr(routes, "ensure_app_settings", lambda **_kwargs: dict(settings))
    def save(values, **_kwargs): settings.update(values); return dict(settings)
    monkeypatch.setattr(routes, "save_app_settings", save)
    monkeypatch.setattr(routes, "_configure_unified_search_runtime", lambda *_a, **_k: runtime)
    app=routes.create_app(); app.config.update(TESTING=True,SECRET_KEY="test"); client=app.test_client()
    with client.session_transaction() as session: session.update(username="tester",csrf_token="test-token")
    return client


def test_indexer_list_toggle_and_test(monkeypatch):
    client=_client(monkeypatch)
    rows=client.get("/api/indexers").get_json()["indexers"]
    assert {row["id"] for row in rows} == {"public","private"}
    headers={"X-CSRF-Token":"test-token"}
    assert client.post("/api/indexers/toggle",json={"id":"public","enabled":False},headers=headers).get_json()["enabled"] is False
    assert client.post("/api/indexers/test",json={"id":"public"},headers=headers).get_json()["result_count"] == 1


def test_requires_setup_cannot_be_enabled(monkeypatch):
    response=_client(monkeypatch).post("/api/indexers/toggle",json={"id":"private","enabled":True},headers={"X-CSRF-Token":"test-token"})
    assert response.status_code == 400
    assert "requires setup" in response.get_json()["error"]


def test_lazy_indexer_download_resolution(monkeypatch):
    response = _client(monkeypatch).post("/api/indexers/resolve", json={"id":"public","canonical_url":"https://example.test/details/1","title":"Matrix"}, headers={"X-CSRF-Token":"test-token"})
    assert response.status_code == 200 and response.get_json()["magnet"].startswith("magnet:?")
