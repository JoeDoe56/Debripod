"""Exercise target selectors with the pinned yt-dlp parser, without network access."""
import pytest
from yt_dlp import YoutubeDL
from debripod.Services.youtube import _yt_stream_format_selector, _yt_dlp_base_args, ytdlp_format_selectors


def choose(target, formats):
    options = {"quiet": True, "no_warnings": True, "simulate": True,
               "format": _yt_stream_format_selector({"quality_target": target})}
    arguments = _yt_dlp_base_args()
    for flag in ("-S", "--format-sort"):
        if flag in arguments:
            options["format_sort"] = arguments[arguments.index(flag) + 1].split(",")
    with YoutubeDL(options) as ydl:
        return ydl.process_ie_result({"id": "fixture", "title": "Fixture", "formats": formats}, download=False)


def fmt(identifier, **values):
    return {"format_id": identifier, "url": "https://media.invalid/" + identifier, **values}


def test_requested_resolution_is_not_reduced_for_avc_compatibility():
    result = choose("2160p", [
        fmt("aac", ext="m4a", vcodec="none", acodec="mp4a.40.2", abr=128),
        fmt("avc-low", ext="mp4", vcodec="avc1", acodec="none", height=360),
        fmt("vp9-high", ext="webm", vcodec="vp9", acodec="none", height=2160),
    ])
    assert [f["format_id"] for f in result["requested_formats"]] == ["vp9-high", "aac"]


def test_target_caps_resolution_and_falls_back_to_available_audio_codec():
    result = choose("720p", [
        fmt("audio-opus", ext="webm", vcodec="none", acodec="opus", abr=160),
        fmt("video-720", ext="webm", vcodec="vp9", acodec="none", height=720),
        fmt("video-1080", ext="webm", vcodec="vp9", acodec="none", height=1080),
    ])
    assert [f["format_id"] for f in result["requested_formats"]] == ["video-720", "audio-opus"]


@pytest.mark.parametrize("target", ["720p", "audio"])
def test_progressive_only_extractor_is_selectable(target):
    result = choose(target, [fmt("combined", ext="mp4", vcodec="avc1", acodec="mp4a.40.2", height=720)])
    assert result["format_id"] == "combined"


def test_equal_resolution_prefers_browser_compatible_video_without_transcoding():
    result = choose("720p", [
        fmt("aac", ext="m4a", vcodec="none", acodec="mp4a.40.2", abr=128),
        fmt("avc", ext="mp4", vcodec="avc1.64001f", acodec="none", height=720),
        fmt("av1", ext="mp4", vcodec="av01.0.08M.08", acodec="none", height=720),
    ])
    assert result["requested_formats"][0]["vcodec"].startswith("avc1")


def test_retry_uses_progressive_media_or_an_alternate_audio_codec():
    selectors = ytdlp_format_selectors({"quality_target": "720p", "media": "video"})
    assert len(selectors) == 2
    formats = [
        fmt("aac", ext="m4a", vcodec="none", acodec="mp4a.40.2", abr=128),
        fmt("alternate", ext="webm", vcodec="none", acodec="opus", abr=160),
        fmt("video", ext="mp4", vcodec="avc1", acodec="none", height=720),
    ]
    with YoutubeDL({"quiet": True, "no_warnings": True, "simulate": True, "format": selectors[1]}) as ydl:
        result = ydl.process_ie_result({"id": "retry", "title": "Retry", "formats": formats}, download=False)
        assert result["requested_formats"][1]["format_id"] == "alternate"
        formats.append(fmt("progressive", ext="mp4", vcodec="avc1", acodec="mp4a.40.2", height=720))
        result = ydl.process_ie_result({"id": "retry", "title": "Retry", "formats": formats}, download=False)
        assert result["format_id"] == "progressive"
