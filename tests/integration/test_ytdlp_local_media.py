"""Actual generic extraction, audio demux, validation and cache reuse over loopback."""
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest
from debripod.Services import youtube
from debripod import runtime_youtube_downloads as downloads


def test_generic_media_quality_audio_extraction_and_cache(tmp_path, monkeypatch):
    ffmpeg = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe")
    executable = Path(sys.executable).with_name("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if not ffmpeg or not ffprobe or not executable.exists():
        pytest.skip("local media integration requires ffmpeg, ffprobe and installed yt-dlp")
    media = tmp_path / "fixture.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264",
                    "-c:a", "aac", "-y", str(media)], check=True)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(youtube, "_ytdlp_cmd_provider", lambda: str(executable))
    monkeypatch.setattr(youtube, "_ffmpeg_path_provider", lambda: ffmpeg)
    monkeypatch.setattr(youtube, "_youtube_stream_cache_dir", lambda: str(cache))

    def probe(path):
        return json.loads(subprocess.check_output([ffprobe, "-v", "error", "-of", "json", "-show_format", "-show_streams", path]))

    monkeypatch.setattr(youtube, "ffprobe_json", probe)
    try:
        url = f"http://127.0.0.1:{server.server_port}/fixture.mp4"
        rows = youtube.ytdlp_list_formats(url)
        assert len(rows) == 2
        assert {row["media"] for row in rows} == {"audio", "video"}
        for row in rows:
            assert not {"itag", "format_id", "direct_url", "format_selector"}.intersection(row)
            output = Path(youtube._prepare_youtube_stream_file(url, row))
            kinds = {stream["codec_type"] for stream in probe(str(output))["streams"]}
            assert kinds == ({"audio"} if row["media"] == "audio" else {"audio", "video"})
            stamp = output.stat().st_mtime_ns
            assert youtube._prepare_youtube_stream_file(url, row) == str(output)
            assert output.stat().st_mtime_ns == stamp, "cache reuse must not redownload media"
        # A collection may contain repeated titles and a quality target above
        # the source resolution. Each item must finish independently.
        monkeypatch.setattr(downloads, 'YTDLP_CMD', str(executable))
        entries = [{'file_id':str(i), 'title':'Repeated title', 'name':'Repeated title',
                    'quality_target':'720p', 'media':'video', 'source_url':url, 'state':'queued'} for i in range(2)]
        task = downloads.Task(id='local-collection', title='Collection', magnet='', task_dir=str(cache), source='youtube', youtube_files=entries)
        monkeypatch.setitem(downloads.TASKS, task.id, task)
        outputs = [downloads._youtube_run_download(task.id, entry, i+1, len(entries)) for i, entry in enumerate(entries)]
        assert len(set(outputs)) == 2
        for output in outputs:
            streams = probe(output)['streams']
            assert {stream['codec_type'] for stream in streams} == {'audio','video'}
            assert next(stream['height'] for stream in streams if stream['codec_type']=='video') == 180
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
