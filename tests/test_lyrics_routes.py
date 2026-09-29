import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod.factory import AppServices, SERVICES_KEY
from debripod.Routes.lyrics import register_lyrics_routes
from debripod.Services.http import HttpStatusError


def test_lyrics_lookup_exact_search_missing_and_failure():
    async def scenario():
        class FakeHttp:
            calls = []
            result = {"syncedLyrics": "[00:01]Words", "instrumental": False, "id": 123}

            async def json(self, method, url, **kwargs):
                self.calls.append((url, kwargs))
                if isinstance(self.result, Exception):
                    raise self.result
                return self.result

        http = FakeHttp()
        app = web.Application()
        app[SERVICES_KEY] = AppServices(http=http)
        register_lyrics_routes(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/api/lyrics?track_name=Track&artist_name=Artist&album_name=Album&duration=20')
            payload = await response.json()
            assert response.status == 200
            assert payload['lyrics']['syncedLyrics'] == '[00:01]Words'
            assert 'id' not in payload['lyrics']
            assert http.calls[-1][0] == 'https://lrclib.net/api/get'
            assert http.calls[-1][1]['params']['duration'] == 20

            http.result = [{"trackName": "Wrong", "artistName": "Artist", "duration": 20, "plainLyrics": "wrong"},
                           {"trackName": "Track", "artistName": "Artist", "duration": 90, "syncedLyrics": "wrong version"},
                           {"trackName": "Track", "artistName": "Artist", "duration": 21, "plainLyrics": "matching"}]
            response = await client.get('/api/lyrics?track_name=Track&artist_name=Artist&duration=20')
            assert (await response.json())['lyrics']['plainLyrics'] == 'matching'

            http.result = HttpStatusError(404, 'https://lrclib.net/api/get')
            response = await client.get('/api/lyrics?track_name=Track&artist_name=Artist&duration=20')
            assert (await response.json())['lyrics'] is None
            http.result = HttpStatusError(500, 'https://lrclib.net/api/get')
            response = await client.get('/api/lyrics?track_name=Track&artist_name=Artist')
            assert response.status == 502
            response = await client.get('/api/lyrics?track_name=Track')
            assert response.status == 200
            response = await client.get('/api/lyrics?track_name=Track&artist_name=Artist&duration=NaN')
            assert response.status == 400
    asyncio.run(scenario())
