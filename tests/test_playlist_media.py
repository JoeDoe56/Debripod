from debripod.Library import playlists


def test_playlist_keeps_mixed_media_and_written_order(tmp_path):
    for name in ('song.flac', 'movie.mp4', 'notes.txt'):
        (tmp_path / name).write_bytes(b'fixture')
    ok, error, created = playlists.create_root_playlist(str(tmp_path), 'Mixed')
    assert ok, error
    ok, error, _ = playlists.add_tracks_to_playlist(str(tmp_path), created['rel'], ['movie.mp4', 'song.flac', 'notes.txt'])
    assert ok, error
    rows = playlists.playlist_tracks_for_root(str(tmp_path), created['rel'])
    assert [(row['rel'], row['media']) for row in rows] == [('movie.mp4', 'video'), ('song.flac', 'audio')]


def test_smart_playlist_can_include_video(tmp_path, monkeypatch):
    (tmp_path / 'movie.mp4').write_bytes(b'fixture')
    ok, error, created = playlists.create_root_smart_playlist(str(tmp_path), 'All media')
    assert ok, error
    monkeypatch.setattr(playlists, 'build_index_for_root', lambda _: {'tracks': [], 'videos': [{'rel': 'movie.mp4', 'title': 'Movie'}]})
    monkeypatch.setattr(playlists, '_smart_group_match', lambda *_: True)
    rows = playlists.smart_playlist_tracks_for_root(str(tmp_path), created['rel'])
    assert [(row['rel'], row['media']) for row in rows] == [('movie.mp4', 'video')]
