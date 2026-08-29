from debripod.Services.search.dedup import TorrentAccumulator, deduplicate_torrents, deduplicate_youtube


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


def test_local_index_baseline_merges_two_remote_sources_and_keeps_remote_only_hash():
    shared_hash = "a" * 40
    remote_hash = "b" * 40
    local = _row(
        "torrent:" + shared_hash, "local_index", "torrent", "Torrent",
        {"infohash": shared_hash, "magnet": "magnet:?xt=urn:btih:" + shared_hash,
         "indexer_ids": ["dmm"], "indexer_labels": ["DMM"], "source_urls": [],
         "seeders": 0, "leechers": 0, "verified": False},
        filter_values={"sources": ["Local Index"], "types": ["Torrent"], "indexers": ["DMM"], "media": []},
    )
    local.update(provider_group="local_index", source_label="Local Index")
    knaben = _row(
        "torrent:" + shared_hash, "torrent", "torrent", "Torrent",
        {"infohash": shared_hash, "magnet": "magnet:?xt=urn:btih:" + shared_hash,
         "indexer_ids": ["knaben"], "indexer_labels": ["Knaben"], "source_urls": ["https://knaben.invalid/detail"],
         "seeders": 200, "leechers": 2, "verified": False},
        filter_values={"sources": ["Torrents"], "types": ["Torrent"], "indexers": ["Knaben"], "media": []},
    )
    magnetz = _row(
        "torrent:" + shared_hash, "torrent", "torrent", "Torrent",
        {"infohash": shared_hash, "magnet": "magnet:?xt=urn:btih:" + shared_hash,
         "indexer_ids": ["magnetz"], "indexer_labels": ["Magnetz"], "source_urls": ["https://magnetz.invalid/detail"],
         "seeders": 150, "leechers": 10, "verified": True},
        filter_values={"sources": ["Torrents"], "types": ["Torrent"], "indexers": ["Magnetz"], "media": []},
    )
    remote_only = _row(
        "torrent:" + remote_hash, "torrent", "torrent", "Torrent",
        {"infohash": remote_hash, "magnet": "magnet:?xt=urn:btih:" + remote_hash,
         "indexer_ids": ["knaben"], "indexer_labels": ["Knaben"], "source_urls": [],
         "seeders": 3, "leechers": 0, "verified": False},
        filter_values={"sources": ["Torrents"], "types": ["Torrent"], "indexers": ["Knaben"], "media": []},
    )

    accumulator = TorrentAccumulator()
    assert accumulator.ingest(local)["result_id"] == "torrent:" + shared_hash
    assert accumulator.ingest(knaben)["result_id"] == "torrent:" + shared_hash
    merged = accumulator.ingest(magnetz)
    accumulator.ingest(remote_only)
    assert len(accumulator.values()) == 2
    assert merged["source"] == "local_index"
    assert merged["filter_values"]["sources"] == ["Local Index", "Torrents"]
    assert merged["provider_data"]["indexer_labels"] == ["DMM", "Knaben", "Magnetz"]
    assert merged["provider_data"]["source_urls"] == ["https://knaben.invalid/detail", "https://magnetz.invalid/detail"]
    assert (merged["provider_data"]["seeders"], merged["provider_data"]["leechers"], merged["provider_data"]["verified"]) == (200, 10, True)

    final = deduplicate_torrents([local, knaben, magnetz, remote_only])
    assert len(final) == 2
    assert final[0]["provider_data"] == merged["provider_data"]
