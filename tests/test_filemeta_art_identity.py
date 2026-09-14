import asyncio
import json
from types import SimpleNamespace

from debripod import runtime_routes as routes


def test_filemeta_preserves_shared_art_identity_across_track_urls(tmp_path, monkeypatch):
    for name in ("one.flac", "two.flac"):
        (tmp_path / name).write_bytes(b"fixture")
    monkeypatch.setattr(routes, "_request_root_by_id", lambda *_: (None, None, str(tmp_path), None))
    monkeypatch.setattr(routes, "file_meta_cached", lambda *_: {"title": "Track"})
    monkeypatch.setattr(routes, "art_identity_for_media", lambda *a, **kw: {
        "art_path": str(tmp_path / "cover.jpg"), "art_identity": "art-sha1:shared:v4"
    })
    results = []
    for name in ("one.flac", "two.flac"):
        response = asyncio.run(routes.api_library_filemeta(SimpleNamespace(query={"root_id": "root", "rel": name})))
        results.append(json.loads(response.text))
    assert results[0]["art"] != results[1]["art"]
    assert results[0]["artIdentity"] == results[1]["artIdentity"] == "art-sha1:shared:v4"
