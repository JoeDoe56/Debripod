from debripod.Services.search.dedup import deduplicate_torrents, deduplicate_youtube


def _row(result_id, source, kind, label, provider_data, **extra):
    return {
        "result_id": result_id, "provider_group": "ytdlp" if source == "youtube" else "torrents",
        "source": source, "source_label": "YouTube" if source == "youtube" else "Torrent",
        "kind": kind, "kind_label": label, "title": extra.pop("title", result_id),
        "provider_data": provider_data, **extra,
    }


def test_youtube_music_wins_and_fills_only_missing_metadata():
    ordinary = _row("ordinary", "youtube", "video", "Videos", {"video_id": "same", "youtube_music": False, "search_category": "videos"}, thumbnail="thumb", artist="ordinary")
    music = _row("music", "youtube", "song", "Songs", {"video_id": "same", "youtube_music": True, "search_category": "songs"}, thumbnail="", artist="music")
    rows = deduplicate_youtube([ordinary, music])
    assert len(rows) == 1
    assert rows[0]["result_id"] == "music"
    assert rows[0]["kind_label"] == "Songs"
    assert rows[0]["provider_data"]["youtube_music"] is True
    assert rows[0]["thumbnail"] == "thumb"
    assert rows[0]["artist"] == "music"


def test_soundcloud_is_never_youtube_deduplicated():
    youtube = _row("yt", "youtube", "video", "Videos", {"video_id": "1", "youtube_music": False})
    soundcloud = _row("sc", "soundcloud", "song", "Songs", {"soundcloud_id": "1"})
    assert len(deduplicate_youtube([youtube, soundcloud])) == 2


def test_torrents_merge_by_hash_and_retain_all_indexers():
    first = _row("torrent:abc", "torrent", "torrent", "Torrent", {"infohash": "ABC", "magnet": "", "indexer_ids": ["a"], "indexer_labels": ["Alpha"], "source_urls": ["https://a"], "seeders": 2, "leechers": 8, "verified": False})
    second = _row("torrent:abc", "torrent", "torrent", "Torrent", {"infohash": "abc", "magnet": "magnet:?xt=urn:btih:abc", "indexer_ids": ["b"], "indexer_labels": ["Beta"], "source_urls": ["https://b"], "seeders": 10, "leechers": 3, "verified": True})
    rows = deduplicate_torrents([first, second])
    assert len(rows) == 1
    data = rows[0]["provider_data"]
    assert data["indexer_ids"] == ["a", "b"]
    assert data["indexer_labels"] == ["Alpha", "Beta"]
    assert data["source_urls"] == ["https://a", "https://b"]
    assert (data["seeders"], data["leechers"], data["verified"]) == (10, 8, True)
    assert "abc" in data["magnet"]


def test_hashless_torrents_only_merge_on_exact_magnet():
    one = _row("one", "torrent", "torrent", "Torrent", {"infohash": "", "magnet": "magnet:?dn=One", "indexer_ids": [], "indexer_labels": [], "source_urls": []})
    two = _row("two", "torrent", "torrent", "Torrent", {"infohash": "", "magnet": "magnet:?dn=one", "indexer_ids": [], "indexer_labels": [], "source_urls": []})
    three = _row("three", "torrent", "torrent", "Torrent", {"infohash": "", "magnet": "magnet:?dn=One", "indexer_ids": [], "indexer_labels": [], "source_urls": []})
    assert len(deduplicate_torrents([one, two, three])) == 2
