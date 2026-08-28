import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import debripod.auth as auth
import debripod.runtime_routes as routes
from debripod.Services.indexers.definition_store import DefinitionStore


def _package():
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w") as archive:
        archive.writestr("definitions/v11/new.yml","id: new\nname: New\ntype: public\nlinks: [https://new.test]\nsearch: {paths: []}\n")
    return output.getvalue()


class RouteStore(DefinitionStore):
    def __init__(self, root, payload): super().__init__(root); self.payload=payload
    def stage_upstream_package(self): return super().stage_upstream_package(self.payload,revision="route-revision")


def _client(monkeypatch, tmp_path):
    tracked=tmp_path/"indexer-definitions"; (tracked/"official").mkdir(parents=True); (tracked/"custom").mkdir()
    (tracked/"manifest.json").write_text(json.dumps({"schema_version":11,"active_revision":"old","package_sha256":"old","updated_at":"","default_enabled_public_indexers":[]}),encoding="utf-8")
    old=tracked/"official"/"old.yml"; old.write_text("id: old\nname: Old\ntype: public\nlinks: [https://old.test]\nsearch: {paths: []}\n",encoding="utf-8")
    store=RouteStore(tmp_path,_package())
    monkeypatch.setattr(auth,"_find_user",lambda username:{"username":username,"password_hash":"test"})
    monkeypatch.setattr(routes,"_active_search_runtime",lambda:SimpleNamespace(definition_store=store))
    monkeypatch.setattr(routes,"_configure_unified_search_runtime",lambda *_a,**_k:None)
    app=routes.create_app(); app.config.update(TESTING=True,SECRET_KEY="test"); client=app.test_client()
    with client.session_transaction() as session: session.update(username="tester",csrf_token="test-token")
    return client,store,old


def test_staging_activation_and_rollback_routes_preserve_hashes(monkeypatch,tmp_path):
    client,store,old=_client(monkeypatch,tmp_path)
    old_hash=hashlib.sha256(old.read_bytes()).hexdigest()
    headers={"X-CSRF-Token":"test-token"}
    assert client.post("/api/indexer-definitions/stage",headers=headers).get_json()["ok"]
    assert old.is_file(), "staging must not change active definitions"
    assert client.post("/api/indexer-definitions/validate",headers=headers).get_json()["validation"]["valid"]
    assert client.post("/api/indexer-definitions/activate",headers=headers).get_json()["ok"]
    assert not old.exists() and (store.official_dir/"new.yml").is_file()
    assert client.post("/api/indexer-definitions/rollback",headers=headers).get_json()["ok"]
    assert hashlib.sha256(old.read_bytes()).hexdigest() == old_hash


def test_discard_route_removes_only_staging(monkeypatch,tmp_path):
    client,store,old=_client(monkeypatch,tmp_path)
    headers={"X-CSRF-Token":"test-token"}
    client.post("/api/indexer-definitions/stage",headers=headers)
    assert store.staging_dir.exists()
    assert client.post("/api/indexer-definitions/discard",headers=headers).get_json()["ok"]
    assert not store.staging_dir.exists() and old.exists()
