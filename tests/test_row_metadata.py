from debripod.Library.row_metadata import enrich_browsing_payload


def test_cached_track_facets_receive_public_metadata_without_private_paths():
    track = dict(root_id="one", rel="song.flac", title="Song", artist="Artist", album="Album",
                 track="3/12", bitrate=1411000, sample_rate=96000, bit_depth=24, duration=120,
                 abs_path="PRIVATE", manifest={"debug": "private"})
    original = {"kind": "track", "root_id": "one", "rel": "song.flac", "label": "Song"}
    result = enrich_browsing_payload({"items": [original]}, {"tracks": [track]}, "one")["items"][0]
    assert result["track"] == "3/12"
    assert result["sample_rate"] == 96000
    assert result["media"] == "audio"
    assert "abs_path" not in result and "manifest" not in result
    assert "track" not in original


def test_counts_keep_zero_and_album_aggregates_use_the_logical_collection():
    payload = {"categories": [{"key": "songs"}, {"key": "movies"}], "items": [
        {"kind": "album", "value": '{"artist":"A","album":"B"}', "label": "B A"}]}
    data = {"tracks": [{"artist": "A", "album": "B", "duration": 10}, {"artist": "A", "album": "B", "duration": 20}], "movies": []}
    result = enrich_browsing_payload(payload, data, "root")
    assert result["categories"] == [{"key": "songs", "count": 2}, {"key": "movies", "count": 0}]
    assert result["items"][0]["duration"] == 30
    assert result["items"][0]["track_count"] == 2
