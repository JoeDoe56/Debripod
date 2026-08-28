import json
from pathlib import Path

from debripod.Services.search.dedup import deduplicate_youtube
from debripod.Services.ytdlp_search import normalize_youtube_entry


FIXTURES = Path(__file__).parent / "fixtures" / "ytdlp"


def _entry(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["entries"][0]


def test_music_categories_parse_to_canonical_schema():
    song = normalize_youtube_entry(_entry("youtube_music_songs.json"), "songs", "Songs", youtube_music=True)
    album = normalize_youtube_entry(_entry("youtube_music_albums.json"), "albums", "Albums", youtube_music=True)
    assert song["kind"] == "song" and song["result_id"] == "youtube:video:dQw4w9WgXcQ"
    assert album["kind"] == "album" and album["result_id"] == "youtube:playlist:PLabcdefghijk"
    assert song["provider_data"]["youtube_music"] is True
    assert set(song) == {"result_id", "provider_group", "source", "source_label", "kind", "kind_label", "title", "subtitle", "artist", "album", "year", "duration", "thumbnail", "canonical_url", "stable_source_id", "search_blob", "filter_values", "match_confidence", "rank_score", "browse_available", "stream_available", "download_available", "files_loaded", "file_count", "size", "files", "provider_data"}


def test_channels_parse_and_music_wins_duplicates():
    channel = normalize_youtube_entry(_entry("youtube_channels.json"), "channels", "Channels", youtube_music=False)
    assert channel["kind"] == "channel"
    assert channel["result_id"] == "youtube:channel:UCabcdefghijk"
    ordinary = normalize_youtube_entry({"id": "same", "title": "ordinary"}, "videos", "Videos", youtube_music=False)
    music = normalize_youtube_entry({"id": "same", "title": "music"}, "songs", "Songs", youtube_music=True)
    assert deduplicate_youtube([ordinary, music])[0]["title"] == "music"
