import asyncio
import json
import os
import shutil
import subprocess

import pytest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import debripod.runtime_routes as routes
import debripod.runtime_route_state as route_state
from debripod.Services import youtube


async def _client(monkeypatch):
    monkeypatch.setattr(routes, "ytdlp_list_formats", lambda url: [{"file_id":"1","name":"Audio","source_label":"SoundCloud" if "soundcloud" in url else "YouTube"}])
    async def validate_url(_request, url):
        return url
    monkeypatch.setattr(routes, "_validated_ytdlp_url", validate_url)

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


def test_link_inspection_recognizes_generic_multi_item_sources(monkeypatch):
    calls = []
    def extract(url, **options):
        calls.append(options)
        return {'_type':'multi_video','extractor':'Generic','title':'Collection',
                'entries':[{'url':'https://media.example.test/a','title':'First'},
                           {'url':'https://media.example.test/b','title':'Second'}]}
    monkeypatch.setattr(youtube, '_yt_dlp_extract_info', extract)
    result = youtube.ytdlp_inspect('https://media.example.test/list')
    assert calls == [{'flat':True}]
    assert result['kind'] == 'playlist'
    assert len(result['entries']) == 2
    assert result['files'] == []


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


def test_format_rows_retain_the_durable_inspected_url_without_cdn_bypass(monkeypatch):
    source_url = "https://media.example.test/watch/42"
    monkeypatch.setattr(youtube, "_yt_dlp_extract_info", lambda _url: {
        "formats": [{
            "format_id": "251", "ext": "webm", "acodec": "opus",
            "vcodec": "none", "url": "https://cdn.example.test/signed-media-url",
        }],
    })
    files = youtube.ytdlp_list_formats(source_url)
    assert files[0]["source_url"] == source_url
    assert "direct_url" not in files[0]


def test_format_rows_use_resolution_targets_and_best_stream_selectors(monkeypatch):
    source_url = "https://media.example.test/watch/targeted"
    monkeypatch.setattr(youtube, "_yt_dlp_extract_info", lambda _url: {
        "formats": [
            {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "width": 1920, "tbr": 4200},
            {"format_id": "136", "ext": "mp4", "vcodec": "avc1.4d401f", "acodec": "none", "height": 720, "width": 1280, "tbr": 2200},
            {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 160, "url": "https://cdn.example.test/audio"},
        ],
    })
    files = youtube.ytdlp_list_formats(source_url)
    assert [row["quality_target"] for row in files] == ["1080p", "720p", "audio"]
    assert youtube._yt_stream_format_selector({"quality_target": files[0]["quality_target"], "media": "video"}).startswith("bestvideo[height<=1080]")
    assert youtube._yt_stream_format_selector({"quality_target": files[1]["quality_target"], "media": "video"}).startswith("bestvideo[height<=720]")
    assert files[2]["name"] == "Audio Only"
    assert youtube._yt_stream_format_selector({"quality_target": files[2]["quality_target"], "media": "audio"}) == "bestaudio/best"


def test_generic_progressive_format_gets_bounded_video_and_audio_targets(monkeypatch):
    source_url = "https://generic.example.test/media.mp4"
    monkeypatch.setattr(youtube, "_yt_dlp_extract_info", lambda _url: {
        "formats": [{"format_id": "mp4", "ext": "mp4", "url": "https://cdn.example.test/media.mp4"}],
        "duration": 3.0,
    })
    files = youtube.ytdlp_list_formats(source_url)
    assert [row["quality_target"] for row in files] == ["best", "audio"]
    assert files[1]["audio_extract"] is True
    assert "format_id" not in files[0] and "itag" not in files[0] and "direct_url" not in files[0]


def test_ytdlp_output_validation_requires_complete_media(monkeypatch, tmp_path):
    media = tmp_path / "finished.mp4"
    media.write_bytes(b"media")
    monkeypatch.setattr(youtube, "ffprobe_json", lambda _path: {
        "format": {"duration": "12.5"},
        "streams": [
            {"codec_type": "video", "start_time": "0"},
            {"codec_type": "audio", "start_time": "0.04"},
        ],
    })
    result = youtube.validate_ytdlp_output(str(media), media="video", expected_duration=12)
    assert result["duration"] == 12.5
    partial = tmp_path / "finished.f137.mp4"
    partial.write_bytes(b"partial")
    try:
        youtube.validate_ytdlp_output(str(partial), media="video")
    except RuntimeError as exc:
        assert "intermediate" in str(exc)
    else:
        raise AssertionError("format-specific intermediate was accepted")


def test_ytdlp_output_validation_reads_real_ffmpeg_artifact(tmp_path, monkeypatch):
    bundled = r"C:\Users\bugma\AppData\Local\Medal\recorder-3.877.0\{}"
    ffmpeg = shutil.which("ffmpeg") or (bundled.format("ffmpeg.exe") if os.path.exists(bundled.format("ffmpeg.exe")) else "")
    ffprobe = shutil.which("ffprobe") or (bundled.format("ffprobe.exe") if os.path.exists(bundled.format("ffprobe.exe")) else "")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are required for the media artifact fixture")
    output = tmp_path / "fixture.m4a"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.8",
        "-c:a", "aac", "-y", str(output),
    ], check=True)
    def probe(path):
        result = subprocess.run([
            ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path,
        ], check=False, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr or "ffprobe failed")
        return json.loads(result.stdout)
    monkeypatch.setattr(youtube, "ffprobe_json", probe)
    result = youtube.validate_ytdlp_output(str(output), media="audio", expected_duration=0.5)
    assert result["duration"] >= 0.5
    assert any(stream.get("codec_type") == "audio" for stream in result["streams"])
    muxed = tmp_path / "fixture.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=0.8",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=0.8", "-shortest",
        "-c:v", "libx264", "-c:a", "aac", "-y", str(muxed),
    ], check=True)
    muxed_result = youtube.validate_ytdlp_output(str(muxed), media="video", expected_duration=0.5)
    muxed_kinds = {stream.get("codec_type") for stream in muxed_result["streams"]}
    assert {"audio", "video"}.issubset(muxed_kinds)
    with pytest.raises(RuntimeError, match="still contains video"):
        youtube.validate_ytdlp_output(str(muxed), media="audio")
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(muxed.read_bytes()[: max(32, muxed.stat().st_size // 4)])
    with pytest.raises(RuntimeError):
        youtube.validate_ytdlp_output(str(truncated), media="video")
    video_only = tmp_path / "video-only.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=0.8",
        "-c:v", "libx264", "-y", str(video_only),
    ], check=True)
    with pytest.raises(RuntimeError, match="missing audio"):
        youtube.validate_ytdlp_output(str(video_only), media="video")


def test_stream_cache_retries_and_ignores_client_selector(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(youtube, "_youtube_stream_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(youtube, "_yt_dlp_base_args", lambda: [])
    monkeypatch.setattr(youtube, "ffprobe_json", lambda _path: {
        "format": {"duration": "1.0"},
        "streams": [{"codec_type": "video", "duration": "1.0"}, {"codec_type": "audio", "duration": "1.0"}],
    })
    def run(args):
        calls.append(list(args))
        if len(calls) == 1:
            return 1, "", "provider rejected preferred selector"
        output_template = args[args.index("-o") + 1]
        output_path = output_template.replace(".%(ext)s", ".mp4")
        with open(output_path, "wb") as handle:
            handle.write(b"complete")
        return 0, "dp:filepath:" + output_path, ""
    monkeypatch.setattr(youtube, "_run_ytdlp", run)
    path = youtube._prepare_youtube_stream_file("https://media.example.test/item", {
        "media": "video", "quality_target": "720p", "format_selector": "--malicious-client-selector",
    })
    assert path.endswith(".mp4")
    assert len(calls) == 2
    first_selector = calls[0][calls[0].index("-f") + 1]
    assert "height<=720" in first_selector
    assert "malicious" not in first_selector


def test_selected_ytdlp_format_uses_source_url_for_stream_preparation():
    source_url = "https://media.example.test/watch/42"

    async def scenario():
        prepared = await route_state._engine_prepare_stream_session({
            "source": "youtube",
            "selected": [{
                "quality_target": "audio", "name": "Audio Only", "media": "audio",
                "source_url": source_url,
            }],
        }, None)
        stream_item = route_state._search_stream_get(prepared["items"][0]["rel"])
        assert stream_item and stream_item["youtube_url"] == source_url

    asyncio.run(scenario())


def test_playlist_streams_keep_each_item_url_and_title():
    async def scenario():
        prepared = await route_state._engine_prepare_stream_session({
            'source': 'youtube', 'url': 'https://media.example.test/playlist', 'title': 'Collection',
            'selected': [{'quality_target':'720p','name':name,'media':'video','source_url':f'https://media.example.test/{name}'} for name in ('First','Second')],
        }, None)
        items = [route_state._search_stream_get(row['rel']) for row in prepared['items']]
        assert [item['youtube_url'] for item in items] == ['https://media.example.test/First','https://media.example.test/Second']
        assert [item['title'] for item in items] == ['First','Second']
    asyncio.run(scenario())


def test_playlist_downloads_get_distinct_control_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_runtime_settings', lambda _: {'YOUTUBE_DOWNLOAD_DIR':str(tmp_path)})
    monkeypatch.setattr(routes, '_current_user_id', lambda _: 'test-user')
    monkeypatch.setattr(routes, 'youtube_worker', lambda _: None)
    async def validate(_, url):
        return url
    monkeypatch.setattr(routes, '_validated_ytdlp_url', validate)
    async def scenario():
        app = web.Application()
        app.router.add_post('/enqueue', routes.api_youtube_enqueue)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post('/enqueue', json={
                'url':'https://media.example.test/list','selected':[
                    {'name':'Repeated title','quality_target':'720p','media':'video','source_url':f'https://media.example.test/{index}'} for index in range(2)
                ]})
            data = await response.json()
            assert data['ok']
            task = routes.TASKS[data['task_id']]
            assert len({item['file_id'] for item in task.youtube_files}) == 2
            assert len({item['source_url'] for item in task.youtube_files}) == 2
        finally:
            await client.close()
    asyncio.run(scenario())


def test_enqueue_url_resolver_accepts_new_and_legacy_payload_shapes():
    source_url = "https://media.example.test/watch/42"
    assert routes._ytdlp_enqueue_source_url({"source_url": source_url}) == source_url
    assert routes._ytdlp_enqueue_source_url({"original_url": source_url}) == source_url
    assert routes._ytdlp_enqueue_source_url({"canonical_url": source_url}) == source_url
