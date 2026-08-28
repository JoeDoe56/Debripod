import hashlib
import io
import json
import zipfile
from pathlib import Path

from debripod.Services.indexers.definition_store import DefinitionStore
from debripod.settings import DEFAULT_APP_SETTINGS


def _setup(root: Path):
    (root / "indexer-definitions" / "official").mkdir(parents=True)
    (root / "indexer-definitions" / "custom").mkdir()
    manifest = {"schema_version": 11, "active_revision": "old", "package_sha256": "old", "updated_at": "", "default_enabled_public_indexers": []}
    (root / "indexer-definitions" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def test_custom_overrides_official_and_parse_errors_are_nonfatal(tmp_path):
    _setup(tmp_path)
    official = tmp_path / "indexer-definitions" / "official"
    custom = tmp_path / "indexer-definitions" / "custom"
    official.joinpath("same.yml").write_text("id: same\nname: Official\ntype: public\nlinks: [https://a]\nsearch: {paths: []}\n", encoding="utf-8")
    custom.joinpath("same.yml").write_text("id: same\nname: Custom\ntype: public\nlinks: [https://b]\nsearch: {paths: []}\n", encoding="utf-8")
    official.joinpath("broken.yml").write_text("id: [", encoding="utf-8")
    rows = DefinitionStore(tmp_path).list_active_definitions()
    assert next(row for row in rows if row.id == "same").origin == "custom"
    assert any(row.parse_error for row in rows)


def test_stage_validate_activate_and_rollback_preserve_hashes(tmp_path):
    _setup(tmp_path)
    old = tmp_path / "indexer-definitions" / "official" / "old.yml"
    old.write_text("id: old\nname: Old\ntype: public\nlinks: [https://old]\nsearch: {paths: []}\n", encoding="utf-8")
    custom = tmp_path / "indexer-definitions" / "custom" / "mine.yml"
    custom.write_text("id: mine\nname: Mine\n", encoding="utf-8")
    old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
    custom_hash = hashlib.sha256(custom.read_bytes()).hexdigest()
    payload = _zip({"definitions/v11/new.yml": "id: new\nname: New\ntype: public\nlinks: [https://new]\nsearch: {paths: []}\n"})
    store = DefinitionStore(tmp_path)
    staged = store.stage_upstream_package(payload, revision="rev-new")
    assert staged["package_sha256"] == hashlib.sha256(payload).hexdigest()
    assert old.is_file()
    assert store.validate_staging()["valid"]
    store.activate_staging()
    assert not old.exists() and (store.official_dir / "new.yml").is_file()
    assert hashlib.sha256(custom.read_bytes()).hexdigest() == custom_hash
    store.rollback_last_activation()
    assert hashlib.sha256(old.read_bytes()).hexdigest() == old_hash


def test_zip_traversal_is_rejected(tmp_path):
    _setup(tmp_path)
    payload = _zip({"../escape.yml": "id: bad"})
    import pytest
    with pytest.raises(ValueError, match="unsafe"):
        DefinitionStore(tmp_path).stage_upstream_package(payload)


def test_movie_tv_defaults_match_manifest_and_limit_anime_sources():
    expected = [
        "1337x", "thepiratebay", "yts", "internetarchive", "torrentproject2", "showrss-yml",
        "torrentsome", "magnetdownload", "torrent9", "world-torrent", "elitetorrent-wf", "nyaasi", "nekobt",
    ]
    manifest = DefinitionStore().load_manifest()
    assert DEFAULT_APP_SETTINGS["INDEXER_ENABLED_IDS"] == expected
    assert manifest["default_enabled_public_indexers"] == expected
    assert [item for item in expected if item in {"nyaasi", "nekobt"}] == ["nyaasi", "nekobt"]


def test_definition_activation_does_not_touch_persisted_user_indexer_choices(tmp_path):
    _setup(tmp_path)
    selected = tmp_path / "data" / "users" / "demo" / "settings.json"
    selected.parent.mkdir(parents=True)
    selected.write_text(json.dumps({"INDEXER_ENABLED_IDS": ["thepiratebay", "yts"]}), encoding="utf-8")
    before = selected.read_bytes()
    store = DefinitionStore(tmp_path)
    store.stage_upstream_package(_zip({"definitions/v11/new.yml": "id: new\nname: New\ntype: public\nlinks: [https://new]\nsearch: {paths: []}\n"}), revision="new")
    store.activate_staging()
    assert selected.read_bytes() == before
