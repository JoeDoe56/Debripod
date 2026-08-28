import json
from pathlib import Path

from debripod.Services.ytdlp_search import SOUNDCLOUD_SEARCHES, YtdlpSearchProvider, normalize_soundcloud_entry


FIXTURES = Path(__file__).parent / "fixtures" / "ytdlp"


def test_all_soundcloud_categories_are_source_accurate():
    mapping = [
        ("soundcloud_tracks.json", "tracks", "Songs", "song"),
        ("soundcloud_artists.json", "artists", "Artists", "artist"),
        ("soundcloud_albums.json", "albums", "Albums", "album"),
        ("soundcloud_playlists.json", "playlists", "Music Playlists", "music_playlist"),
    ]
    for fixture, category, label, kind in mapping:
        entry = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))["entries"][0]
        result = normalize_soundcloud_entry(entry, category, label, kind)
        assert result["source"] == "soundcloud"
        assert result["kind"] == kind and result["kind_label"] == label
        assert result["result_id"].startswith(f"soundcloud:{kind}:")


def test_provider_uses_four_unbounded_soundcloud_prefixes_after_youtube():
    calls = []

    def runner(value):
        calls.append(value)
        return []

    response = YtdlpSearchProvider(runner).search("query", object())
    soundcloud_calls = [value for value in calls if value.startswith("sc")]
    assert sorted(soundcloud_calls) == sorted(prefix + "query" for _category, _label, prefix, _kind in SOUNDCLOUD_SEARCHES)
    assert all(not any(char.isdigit() for char in value.split(":", 1)[0]) for value in soundcloud_calls)
    assert len(response.source_status) == 14
