from yt_dlp.extractor.soundcloud import SoundcloudIE, SoundcloudSetIE, SoundcloudUserIE

from yt_dlp_plugins.extractor.debripod_soundcloud_search import (
    DebriPodSoundcloudAlbumSearchIE,
    DebriPodSoundcloudArtistSearchIE,
    DebriPodSoundcloudPlaylistSearchIE,
    DebriPodSoundcloudTrackSearchIE,
)


def test_plugin_prefix_endpoint_and_extractor_mapping():
    expected = [
        (DebriPodSoundcloudTrackSearchIE, "sctracksearch:test", "search/tracks", SoundcloudIE),
        (DebriPodSoundcloudArtistSearchIE, "scartistsearch:test", "search/users", SoundcloudUserIE),
        (DebriPodSoundcloudAlbumSearchIE, "scalbumsearch:test", "search/albums", SoundcloudSetIE),
        (DebriPodSoundcloudPlaylistSearchIE, "scplaylistsearch:test", "search/playlists_without_albums", SoundcloudSetIE),
    ]
    for extractor, url, endpoint, result_ie in expected:
        assert extractor.suitable(url)
        assert extractor.suitable(url.replace("search:", "search20:"))
        assert extractor._ENDPOINT == endpoint
        assert extractor._RESULT_IE is result_ie


def test_unbounded_prefix_has_no_implicit_count():
    match = DebriPodSoundcloudTrackSearchIE._match_valid_url("sctracksearch:alice")
    assert match.group("count") == ""
    assert DebriPodSoundcloudTrackSearchIE._match_valid_url("sctracksearch20:alice").group("count") == "20"
