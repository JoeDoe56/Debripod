from __future__ import annotations

import asyncio

from debripod.Services.soulseek_search import SoulseekSearchProvider


class _ReadyService:
    user_id = ""

    def is_ready(self):
        return True

    def start_error(self):
        return ""

    async def search_async(self, query):
        return [
            {"user": "alice", "remote_path": "@@music\\Artist\\Album\\01 Song.flac", "name": "01 Song.flac", "size": 1000},
            {"user": "alice", "remote_path": "@@music\\Artist\\Album\\02 Song.flac", "name": "02 Song.flac", "size": 2000},
        ]


def test_soulseek_search_files_carry_remote_path_for_enqueue():
    # The Download button sends each file's remote_path to /api/soulseek/enqueue;
    # without it the request has no files and the server answers 400.
    response = asyncio.run(SoulseekSearchProvider(lambda: _ReadyService()).search("song"))
    assert len(response.results) == 1
    result = response.results[0]
    assert result["provider_data"]["user"] == "alice"
    paths = sorted(f["remote_path"] for f in result["files"])
    assert paths == ["@@music\\Artist\\Album\\01 Song.flac", "@@music\\Artist\\Album\\02 Song.flac"]
