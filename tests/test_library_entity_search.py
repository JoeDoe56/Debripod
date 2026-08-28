from debripod.Services.library_search import LibrarySearchProvider


def _snapshot():
    return {
        "tracks": [{"rel": "Music/Alice/Dirt/Would.mp3", "title": "Would", "artist": "Alice in Chains", "album": "Dirt", "size": 10}],
        "playlists": [{"id": "liked", "name": "Alice favorites"}],
        "movies": [{"rel": "Movies/Alice Film.mkv", "title": "Alice Film", "year": 2020}],
        "shows": [{"id": "alice-show", "title": "Alice Show", "episodes": [{"rel": "TV/Alice Show/S01E02.mkv", "title": "Alice Episode", "season": 1, "episode": 2}]}],
        "videos": [{"rel": "Videos/Alice Interview.mp4", "title": "Alice Interview"}],
        "folders": [{"rel": "Alice Folder"}],
    }


def test_returns_all_distinct_library_entity_kinds_and_navigation():
    provider = LibrarySearchProvider(lambda: [{"id": "root"}], lambda root: _snapshot(), lambda: {"root": 1})
    rows = provider.search("Alice").results
    kinds = {row["kind"] for row in rows}
    assert {"artist", "album", "song", "music_playlist", "movie", "show", "season", "episode", "video", "directory"} <= kinds
    assert all(set(row["provider_data"]) == {"root_id", "rel", "entity_key", "navigation"} for row in rows)


def test_exact_artist_does_not_expand_every_song_and_index_caches_by_version():
    calls = []
    versions = [{"root": 1}]
    provider = LibrarySearchProvider(lambda: [{"id": "root"}], lambda root: calls.append(root) or _snapshot(), lambda: versions[0])
    first = provider.search("Alice in Chains").results
    assert any(row["kind"] == "artist" for row in first)
    assert not any(row["kind"] == "song" and row["title"] == "Would" for row in first)
    provider.search("Alice")
    assert calls == ["root"]
    versions[0] = {"root": 2}
    provider.search("Alice")
    assert calls == ["root", "root"]
