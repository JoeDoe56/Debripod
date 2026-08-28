from types import SimpleNamespace

import pytest

from debripod.Services.indexers.cardigann.engine import CardigannEngine
from debripod.Services.indexers.cardigann.schema import CardigannDefinition


def _engine():
    return CardigannEngine(CardigannDefinition.from_dict({"id": "d", "name": "D", "type": "public", "links": ["https://x/"], "search": {"paths": []}}))


def test_infohash_magnet_and_redirect_to_magnet():
    assert "abcdef" in _engine().resolve_download({"infohash": "ABCDEF", "title": "A B"}, lambda spec: None)["magnet"]
    response = SimpleNamespace(status_code=302, headers={"Location": "magnet:?xt=urn:btih:abc"}, content=b"")
    assert _engine().resolve_download({"download": "/get"}, lambda spec: response)["magnet"].startswith("magnet:")


def test_validates_torrent_and_bounds_redirects():
    torrent = SimpleNamespace(status_code=200, headers={}, content=b"d6:pieces1:xe")
    assert _engine().resolve_download({"download": "/get"}, lambda spec: torrent)["torrent"].startswith(b"d")
    redirect = SimpleNamespace(status_code=302, headers={"Location": "/again"}, content=b"")
    with pytest.raises(ValueError, match="redirects"):
        _engine().resolve_download({"download": "/get"}, lambda spec: redirect)


def test_download_page_selector_resolves_magnet():
    definition = CardigannDefinition.from_dict({
        "id": "d", "name": "D", "type": "public", "links": ["https://x/"], "search": {"paths": []},
        "download": {"selectors": [{"selector": 'a[href^="magnet:"]', "attribute": "href"}]},
    })
    infohash = "a" * 40
    response = SimpleNamespace(status_code=200, headers={}, text=f'<a href="magnet:?xt=urn:btih:{infohash}">Magnet</a>', content=b"")
    resolved = CardigannEngine(definition).resolve_download({"download": "/details"}, lambda spec: response)
    assert resolved["infohash"] == infohash and resolved["magnet"].startswith("magnet:?")
