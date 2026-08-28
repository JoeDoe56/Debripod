import json
import os
from types import SimpleNamespace

import pytest

from debripod.Services.indexers.definition_store import DefinitionStore
from debripod.Services.indexers.browsers.solver import BrowserChallengeSolver
from debripod.Services.indexers.http_client import IndexerHttpClient
from debripod.Services.indexers.service import IndexerService


pytestmark = pytest.mark.skipif(os.environ.get("DEBRIPOD_RUN_NETWORK_TESTS") != "1", reason="network smoke tests are opt-in")


class EphemeralStatus:
    def __init__(self):
        self.rows = {}

    def is_blocked(self, _identifier):
        return False

    def get(self, identifier):
        return self.rows.setdefault(identifier, SimpleNamespace(indexer_id=identifier, cookies=[], user_agent="", cookies_expiration=None, disabled_until=None, last_error_category=""))

    def record_success(self, identifier, **_kwargs):
        return self.get(identifier)

    def record_failure(self, identifier, *_args, **_kwargs):
        return self.get(identifier)

    def save_clearance(self, identifier, *_args, **_kwargs):
        status = self.get(identifier)
        status.cookies = list(_args[0] if _args else _kwargs.get("cookies") or [])
        status.user_agent = str(_args[1] if len(_args) > 1 else _kwargs.get("user_agent") or "")
        return status


@pytest.fixture(scope="module")
def prowlarr_store(tmp_path_factory):
    root = tmp_path_factory.mktemp("live-prowlarr")
    tracked = root / "indexer-definitions"
    (tracked / "official").mkdir(parents=True)
    (tracked / "custom").mkdir()
    (tracked / "manifest.json").write_text(
        json.dumps({"schema_version": 11, "source": "Prowlarr Cardigann definitions", "active_revision": "", "package_sha256": "", "updated_at": "", "default_enabled_public_indexers": []}),
        encoding="utf-8",
    )
    store = DefinitionStore(root)
    staged = store.stage_upstream_package()
    validation = store.validate_staging()
    assert staged["package_sha256"] and validation["valid"], validation
    assert validation["definition_count"] > 100
    store.official_dir = store.staging_dir / "official"
    return store


@pytest.mark.parametrize(
    ("indexer_id", "query"),
    [
        ("thepiratebay", "ubuntu"),
        ("yts", "matrix"),
        ("internetarchive", "ubuntu"),
        ("torrentproject2", "matrix"),
        ("showrss-yml", "the"),
        ("torrentsome", "matrix"),
        ("magnetdownload", "matrix"),
        ("torrent9", "matrix"),
        ("world-torrent", "matrix"),
        ("elitetorrent-wf", "matrix"),
        ("nyaasi", "one piece"),
        ("nekobt", "one piece"),
    ],
)
def test_live_pulled_public_indexer_returns_canonical_results(prowlarr_store, indexer_id, query):
    status_store = EphemeralStatus()
    service = IndexerService(
        prowlarr_store,
        enabled_ids=[indexer_id],
        status_store=status_store,
        client_factory=lambda identifier: IndexerHttpClient(identifier, status_store=status_store, retries=1),
        max_concurrent=1,
    )
    response = service.search(query)
    if not response.results:
        print(json.dumps(response.source_status, indent=2, sort_keys=True))
    assert len(response.source_status) == 1, response.source_status
    assert response.source_status[0]["indexer_id"] == indexer_id
    assert response.source_status[0]["status"] == "ok", response.source_status
    assert response.results, response.source_status
    for result in response.results:
        assert result["source"] == "torrent"
        assert result["provider_group"] == "torrents"
        assert result["provider_data"]["indexer_labels"]
        assert result["provider_data"]["magnet"].startswith("magnet:?") or result["canonical_url"].startswith(("http://", "https://"))


def test_live_1337x_exercises_detected_challenge_browser_path(prowlarr_store):
    status_store = EphemeralStatus()
    solver = BrowserChallengeSolver(repo_root=prowlarr_store.repo_root, status_store=status_store, timeout=45)
    calls = []
    original_solve = solver.solve
    def counted_solve(*args, **kwargs):
        calls.append(args[1])
        return original_solve(*args, **kwargs)
    solver.solve = counted_solve
    service = IndexerService(
        prowlarr_store,
        enabled_ids=["1337x"],
        status_store=status_store,
        client_factory=lambda identifier: IndexerHttpClient(identifier, status_store=status_store, solver=solver, retries=0),
        max_concurrent=1,
    )
    response = service.search("matrix")
    assert len(response.source_status) == 1 and response.source_status[0]["indexer_id"] == "1337x"
    if response.results:
        assert response.source_status[0]["status"] == "ok"
    else:
        assert calls, "1337x challenge response must invoke the installed-browser solver"
        assert len(calls) == 1, "one unresolved challenge must stop mirror fallback"
        assert "challenge" in response.source_status[0]["error"].casefold()
