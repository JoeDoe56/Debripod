from debripod.Services.search.identity import (
    library_result_id,
    soulseek_result_id,
    stable_result_id,
    torrent_dedupe_key,
    torrent_result_id,
    youtube_dedupe_key,
    youtube_result_id,
)


def test_provider_identity_rules_are_stable():
    assert library_result_id("root", "song", "artist|title") == library_result_id("root", "song", "artist|title")
    assert soulseek_result_id("user", r"Music\Artist") == soulseek_result_id("user", "music/artist")
    assert torrent_result_id("ABCDEF") == "torrent:abcdef"


def test_youtube_browse_playlist_and_dedupe_are_stable_across_field_order():
    assert youtube_result_id("album", browse_id="VLPLabcdefghijkl") == "youtube:playlist:PLabcdefghijkl"
    first = {"source": "youtube", "kind": "video", "provider_data": {"video_id": "abc123"}}
    second = {"provider_data": {"video_id": "abc123"}, "kind": "video", "source": "youtube"}
    assert youtube_dedupe_key(first) == youtube_dedupe_key(second) == "youtube:video:abc123"


def test_torrent_identity_stable_across_field_order():
    first = {"source": "torrent", "provider_data": {"infohash": "ABC"}, "kind": "torrent"}
    second = {"kind": "torrent", "provider_data": {"infohash": "abc"}, "source": "torrent"}
    assert stable_result_id(first) == stable_result_id(second) == "torrent:abc"
    assert torrent_dedupe_key(first) == torrent_dedupe_key(second)
