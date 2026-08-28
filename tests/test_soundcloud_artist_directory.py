from debripod.Services import soundcloud_directory


def test_artist_sections_are_lazy_and_playlists_exclude_album_ids(monkeypatch):
    calls = []
    cache = {}

    def runner(url):
        calls.append(url)
        if url.endswith("/albums"):
            return [{"id": "1", "title": "Album", "permalink_url": "https://soundcloud.com/a/sets/album"}]
        if url.endswith("/sets"):
            return [
                {"id": "1", "title": "Album duplicate", "permalink_url": "https://soundcloud.com/a/sets/album"},
                {"id": "2", "title": "Playlist", "permalink_url": "https://soundcloud.com/a/sets/list"},
            ]
        return [{"id": "3", "title": "Track", "permalink_url": "https://soundcloud.com/a/track"}]

    monkeypatch.setattr(soundcloud_directory, "_disk_cache_get", lambda key: cache.get(key))
    monkeypatch.setattr(soundcloud_directory, "_disk_cache_set", lambda key, engine, q, extra, payload: cache.__setitem__(key, {"payload": payload}))
    service = soundcloud_directory.SoundCloudDirectoryService(runner)
    tracks = service.load_section("https://soundcloud.com/a", "tracks")
    assert [row["title"] for row in tracks] == ["Track"]
    assert calls == ["https://soundcloud.com/a/tracks"]
    playlists = service.load_section("https://soundcloud.com/a", "playlists")
    assert [row["title"] for row in playlists] == ["Playlist"]
    assert calls[-2:] == ["https://soundcloud.com/a/albums", "https://soundcloud.com/a/sets"]
    service.load_section("https://soundcloud.com/a", "playlists")
    assert calls.count("https://soundcloud.com/a/sets") == 1
