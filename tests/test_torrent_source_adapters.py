from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
import pytest

from debripod.Services.http import HttpClient, HttpStatusError
from debripod.Services.torrent_sources import (
    ADAPTER_TYPES,
    BT4GAdapter,
    BitSearchAdapter,
    KnabenAdapter,
    MagnetzAdapter,
    TorAPIAdapter,
    TorLockAdapter,
    TorrentClawAdapter,
)


FIXTURES = Path(__file__).parent / "fixtures" / "torrent_sources"


class FakeHttp:
    def __init__(self):
        self.calls = []

    async def json(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if "/api/search/id/" in url:
            return {"data": {"hash": "9" * 40, "torrent_url": "https://example.invalid/resolved.torrent"}}
        if "knaben" in url:
            name = "knaben.json"
        elif "bitsearch" in url:
            name = "bitsearch.json"
        elif "magnetz" in url:
            name = f"magnetz_page{kwargs['params']['page']}.json"
        elif "torrentclaw" in url:
            name = "torrentclaw.json"
        elif "torapi" in url:
            name = "torapi.json"
        else:
            raise AssertionError(url)
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    async def text(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        name = "torlock.xml" if "torlock" in url else "bt4g.xml"
        return (FIXTURES / name).read_text(encoding="utf-8")


def run(coro):
    return asyncio.run(coro)


def test_exactly_seven_fixed_remote_adapters_exist():
    assert [value.source_id for value in ADAPTER_TYPES] == [
        "knaben", "bitsearch", "magnetz", "torlock", "bt4g", "torrentclaw", "torapi"
    ]


def test_knaben_uses_documented_maximum_and_maps_fixture():
    http = FakeHttp()
    hits = run(KnabenAdapter(http).search("fixture"))
    assert http.calls[0][2]["json_body"]["size"] == 300
    assert http.calls[0][2]["json_body"]["hide_unsafe"] is True
    assert hits[0].infohash == "1" * 40
    assert hits[0].magnet == "magnet:?xt=urn:btih:" + "1" * 40
    assert (hits[0].title, hits[0].size, hits[0].seeders, hits[0].leechers, hits[0].category) == (
        "Knaben Release", 1024, 8, 2, "video"
    )
    assert hits[0].detail_url == "https://example.invalid/k"
    assert hits[0].extra["upstream_origin"] == "fixture"


def test_bitsearch_spends_one_quota_request_at_limit_100():
    http = FakeHttp()
    hits = run(BitSearchAdapter(http).search("fixture"))
    assert len(http.calls) == 1
    assert http.calls[0][2]["params"] == {"q": "fixture", "limit": 100, "page": 1}
    assert hits[0].verified is True
    assert (hits[0].title, hits[0].infohash, hits[0].size, hits[0].seeders, hits[0].leechers) == (
        "BitSearch Release", "2" * 40, 2048, 7, 1
    )
    assert hits[0].magnet.endswith("2" * 40)


def test_magnetz_fetches_remaining_pages_concurrently_and_deduplicates():
    http = FakeHttp()
    hits = run(MagnetzAdapter(http).search("fixture"))
    assert {call[2]["params"]["page"] for call in http.calls} == {1, 2}
    assert [hit.infohash for hit in hits] == ["3" * 40, "4" * 40]
    assert [hit.title for hit in hits] == ["Magnetz One", "Magnetz Two"]
    assert hits[0].magnet.endswith("3" * 40)
    assert hits[1].extra["largest_file"] == "movie.mkv"


def test_torlock_uses_one_max_torznab_request():
    http = FakeHttp()
    hits = run(TorLockAdapter(http).search("fixture"))
    assert http.calls[0][2]["params"] == {"t": "search", "q": "fixture", "limit": 100, "offset": 0}
    assert hits[0].seeders == 4 and hits[0].leechers == 2
    assert (hits[0].title, hits[0].infohash, hits[0].size) == ("TorLock Release", "5" * 40, 4096)
    assert hits[0].magnet.startswith("magnet:?xt=urn:btih:")


def test_bt4g_consumes_only_the_complete_first_rss_page():
    http = FakeHttp()
    hits = run(BT4GAdapter(http).search("fixture"))
    assert len(http.calls) == 1 and http.calls[0][2]["params"]["p"] == 1
    assert hits[0].size == 8192
    assert hits[0].seeders == hits[0].leechers == 0
    assert (hits[0].title, hits[0].infohash) == ("BT4G Release", "6" * 40)
    assert hits[0].detail_url == "https://example.invalid/bt4g"


def test_torrentclaw_uses_anonymous_max_request_and_flattens_releases():
    http = FakeHttp()
    hits = run(TorrentClawAdapter(http).search("fixture"))
    assert http.calls[0][2]["params"] == {"q": "fixture", "limit": 50, "page": 1}
    assert len(hits) == 1 and hits[0].infohash == "7" * 40
    assert (hits[0].title, hits[0].size, hits[0].seeders, hits[0].leechers) == (
        "TorrentClaw Release", 8192, 3, 1
    )
    assert hits[0].magnet.endswith("7" * 40)
    assert hits[0].extra["codec"] == "HEVC"


def test_torapi_uses_page_all_and_keeps_url_identity_provisional():
    http = FakeHttp()
    hits = run(TorAPIAdapter(http).search("fixture"))
    assert http.calls[0][2]["params"] == {"query": "fixture", "page": "all"}
    assert len(hits) == 2
    hashed = next(hit for hit in hits if hit.source_record_id == "rt1")
    assert (hashed.infohash, hashed.size, hashed.extra["torapi_provider"]) == ("8" * 40, 16384, "RuTor")
    assert hashed.magnet.endswith("8" * 40)
    provisional = next(hit for hit in hits if hit.source_record_id == "kz2")
    assert provisional.infohash == provisional.magnet == ""
    assert provisional.extra["torapi_provider"] == "Kinozal"

    resolved = run(TorAPIAdapter(http).resolve(provisional))
    assert resolved.infohash == "9" * 40
    assert resolved.magnet.endswith("9" * 40)
    assert resolved.torrent_url == "https://example.invalid/resolved.torrent"


@pytest.mark.parametrize("adapter_type", ADAPTER_TYPES)
def test_every_adapter_handles_empty_structured_responses(adapter_type):
    class EmptyHttp:
        async def json(self, *_args, **_kwargs):
            return {}

        async def text(self, *_args, **_kwargs):
            return "<?xml version='1.0'?><rss><channel/></rss>"

    assert run(adapter_type(EmptyHttp()).search("fixture")) == []


@pytest.mark.parametrize("adapter_type", ADAPTER_TYPES)
@pytest.mark.parametrize("error", [asyncio.TimeoutError(), HttpStatusError(429, "https://example.invalid")])
def test_every_adapter_propagates_timeout_and_rate_limit_for_source_isolation(adapter_type, error):
    class FailedHttp:
        async def json(self, *_args, **_kwargs):
            raise error

        async def text(self, *_args, **_kwargs):
            raise error

    with pytest.raises(type(error)):
        run(adapter_type(FailedHttp()).search("fixture"))


@pytest.mark.parametrize("adapter_type", [TorLockAdapter, BT4GAdapter])
def test_xml_adapters_reject_malformed_payloads(adapter_type):
    class MalformedHttp:
        async def text(self, *_args, **_kwargs):
            return "<rss><channel>"

    with pytest.raises(Exception):
        run(adapter_type(MalformedHttp()).search("fixture"))


class FakeResponse:
    def __init__(self, status, body=b"{}", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}
        self.url = "https://example.invalid/api"

    async def read(self):
        return self._body


class ResponseContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        return False


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        return ResponseContext(self.responses.pop(0))


def test_shared_http_retries_only_transient_statuses_and_not_parse_errors(monkeypatch):
    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    session = FakeSession([FakeResponse(503), FakeResponse(200, b'{"ok":true}')])
    assert run(HttpClient(session).json("GET", "https://example.invalid/api")) == {"ok": True}
    assert session.calls == 2

    bad = FakeSession([FakeResponse(400)])
    with pytest.raises(HttpStatusError):
        run(HttpClient(bad).json("GET", "https://example.invalid/api"))
    assert bad.calls == 1

    malformed = FakeSession([FakeResponse(200, b"not json")])
    with pytest.raises(json.JSONDecodeError):
        run(HttpClient(malformed).json("GET", "https://example.invalid/api"))
    assert malformed.calls == 1
