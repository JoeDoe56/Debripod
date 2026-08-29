import os
import sys
import asyncio
from pathlib import Path

import pytest

from debripod.Services.ytdlp_search import YtdlpSearchProvider
from debripod.Services.ytdlp_runner import configure_ytdlp_runner


pytestmark = pytest.mark.skipif(os.environ.get("DEBRIPOD_RUN_NETWORK_TESTS") != "1", reason="network smoke tests are opt-in")


def test_live_ytdlp_search_returns_source_accurate_schema():
    executable = Path(sys.executable).with_name("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    configure_ytdlp_runner(ytdlp_cmd_provider=lambda: str(executable))
    response = asyncio.run(YtdlpSearchProvider(max_concurrent=4).search("Daft Punk", None))
    assert response.provider_group == "ytdlp"
    assert len(response.source_status) == 10
    assert any(row.get("status") == "ok" for row in response.source_status)
    for result in response.results:
        assert result["source"] == "youtube"
        assert result["canonical_url"].startswith("http")
        assert result["provider_group"] == "ytdlp"
