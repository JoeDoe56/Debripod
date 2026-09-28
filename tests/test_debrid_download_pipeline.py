import asyncio
import ssl
from types import SimpleNamespace

from aiohttp import web, ClientSession, ClientConnectorCertificateError
from aiohttp.test_utils import TestServer

from debripod import runtime_debrid_downloads as downloads
from debripod.Services.http import HttpClient
from debripod.Services.debrid.models import DebridFile, DebridResolvedLink
from debripod.Services.debrid.torbox import TorBoxProvider, _task_payload


def test_expired_link_refresh_downloads_complete_file(tmp_path, monkeypatch):
    async def scenario():
        content = b'local download fixture' * 100
        app = web.Application()
        app.router.add_get('/expired', lambda _: web.Response(status=403))
        app.router.add_get('/file', lambda _: web.Response(body=content))
        server = TestServer(app)
        await server.start_server()
        try:
            async with ClientSession() as session:
                monkeypatch.setattr(downloads, '_HTTP', HttpClient(session))
                task = downloads.Task(id='refresh-test', title='Fixture', magnet='', task_dir=str(tmp_path), debrid_provider='torbox')
                task.debrid_files = [{'file_id':'0','provider_file_id':'0','provider_task_id':'42','name':'fixture.bin','state':'queued'}]
                monkeypatch.setitem(downloads.TASKS, task.id, task)
                class Provider:
                    calls = 0
                    async def resolve_file_url(self, file):
                        assert file.provider_file_id == '0'
                        self.calls += 1
                        return DebridResolvedLink(url=str(server.make_url('/expired' if self.calls == 1 else '/file')), filename='fixture.bin', requires_refresh=True)
                provider = Provider()
                monkeypatch.setattr(downloads, '_provider_for_task', lambda _: provider)
                monkeypatch.setattr(downloads, 'enqueue_video_postprocess', lambda *_: None)
                paths = await downloads._download_from_queue(task.id)
                assert provider.calls == 2
                assert len(paths) == 1
                assert (tmp_path / 'fixture.bin').read_bytes() == content
                assert task.debrid_files[0]['state'] == 'complete'
        finally:
            await server.close()
    asyncio.run(scenario())


def test_missing_torrent_never_uses_another_torrents_files():
    assert _task_payload({'data':[{'id':99,'files':[{'id':0}]}]}, '42') == {}


def test_torbox_readiness_uses_download_presence():
    async def scenario():
        provider = TorBoxProvider('test', 'https://example.test', 10, None)
        async def request(*_, **__):
            return {'data':{'id':42,'download_state':'uploading','download_present':False,'files':[{'id':0,'name':'song.flac'}]}}
        provider._request = request
        assert not (await provider.refresh_preview('42')).ready
    asyncio.run(scenario())


def test_bad_certificate_refreshes_link_without_disabling_tls(tmp_path, monkeypatch):
    async def scenario():
        task = downloads.Task(id='tls-test', title='Fixture', magnet='', task_dir=str(tmp_path), debrid_provider='torbox')
        task.debrid_files = [{'file_id':'0','provider_file_id':'0','provider_task_id':'42','name':'fixture.bin','state':'queued'}]
        monkeypatch.setitem(downloads.TASKS, task.id, task)
        calls = []
        class Provider:
            async def resolve_file_url(self, file):
                calls.append('resolve')
                return DebridResolvedLink(url='https://example.test/file', filename='fixture.bin', requires_refresh=True)
        async def fail(*args, **kwargs):
            calls.append('download')
            raise ClientConnectorCertificateError(SimpleNamespace(host='example.test', port=443, ssl=True, is_ssl=True), ssl.SSLCertVerificationError('certificate expired'))
        monkeypatch.setattr(downloads, '_provider_for_task', lambda _: Provider())
        monkeypatch.setattr(downloads, 'download_stream', fail)
        assert await downloads._download_from_queue(task.id) == []
        assert calls == ['resolve','download','resolve','download']
        assert task.debrid_files[0]['state'] == 'failed'
        assert 'TLS certificate' in task.debrid_files[0]['error']
    asyncio.run(scenario())
