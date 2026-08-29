import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import debripod.runtime_routes as routes


async def _client(monkeypatch):
    monkeypatch.setattr(routes, "ytdlp_list_formats", lambda url: [{"file_id":"1","name":"Audio","source_label":"SoundCloud" if "soundcloud" in url else "YouTube"}])

    async def flat_entries(url):
        return [{"id": "v1", "url": url, "title": "Entry"}]

    monkeypatch.setattr(routes, "run_flat_entries_async", flat_entries)
    app = web.Application()
    app.router.add_get("/api/ytdlp/files", routes.api_ytdlp_files)
    app.router.add_get("/api/youtube/files", routes.api_ytdlp_files)
    app.router.add_get("/api/ytdlp/directory", routes.api_ytdlp_directory)
    app.router.add_post("/api/link/inspect", routes.api_link_inspect)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def test_generic_files_and_legacy_youtube_alias_match(monkeypatch):
    async def scenario():
        client = await _client(monkeypatch)
        try:
            generic = await (await client.get("/api/ytdlp/files?url=https://youtube.test/watch?v=1")).json()
            legacy = await (await client.get("/api/youtube/files?url=https://youtube.test/watch?v=1")).json()
            assert generic == legacy and generic["files"][0]["source_label"] == "YouTube"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_generic_ytdlp_directory_route(monkeypatch):
    async def scenario():
        client = await _client(monkeypatch)
        try:
            payload = await (await client.get("/api/ytdlp/directory?url=https://youtube.test/playlist")).json()
            assert payload["entries"][0]["id"] == "v1"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_pasted_soundcloud_url_still_uses_generic_ytdlp_inspection(monkeypatch):
    async def scenario():
        client = await _client(monkeypatch)
        try:
            expected={"result_id":"ytdlp:generic:1","source":"youtube","source_label":"yt-dlp","title":"Track","files":[]}
            monkeypatch.setattr(routes, "ytdlp_inspect", lambda url: dict(expected, url=url))
            response = await client.post("/api/link/inspect", json={"value":"https://soundcloud.com/artist/track"})
            assert response.status == 200
            payload = await response.json()
            assert payload["detail_kind"] == "ytdlp_formats"
            assert payload["result"]["url"] == "https://soundcloud.com/artist/track"
        finally:
            await client.close()

    asyncio.run(scenario())
