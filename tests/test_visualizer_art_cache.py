from __future__ import annotations

from debripod.Library import metadata
import os
import shutil
import subprocess
import pytest


def _fake_visualizer_art_builder(calls: list[str]):
    def build(source: str, destination: str) -> bool:
        calls.append(source)
        with open(destination, "wb") as handle:
            handle.write(b"fake-jpeg")
        return True
    return build


def test_green_artwork_retains_distinct_shades_after_blur(tmp_path, monkeypatch):
    ffmpeg = os.environ.get('FFMPEG_PATH') or shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('requires ffmpeg')
    monkeypatch.setattr(metadata, '_ffmpeg_path_value', lambda: ffmpeg)
    source = tmp_path / 'green.ppm'
    # Several dark/light green regions, like a mostly monochromatic cover.
    pixels = bytearray()
    for y in range(128):
        for x in range(128):
            pixels.extend(((22,45,10),(72,110,25),(144,182,65),(198,220,105))[(x//16+y//16)%4])
    source.write_bytes(b'P6\n128 128\n255\n'+pixels)
    output = tmp_path / 'field.png'
    assert metadata._build_visualizer_art_image(str(source), str(output))
    raw = subprocess.check_output([ffmpeg,'-v','error','-i',str(output),'-vf','scale=32:32','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
    greens = list(raw[1::3])
    greens.sort()
    assert greens[int(len(greens)*.9)] - greens[int(len(greens)*.1)] > 45
    assert len(set(greens)) > 30


def test_shared_album_art_generates_one_visualizer_field(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    album = tmp_path / "album"
    album.mkdir()
    cover = album / "cover.jpg"
    cover.write_bytes(b"one album cover")
    first = album / "01.mp3"
    second = album / "02.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(metadata, "visualizer_art_cache_dir", lambda: str(cache))
    calls: list[str] = []
    monkeypatch.setattr(metadata, "_build_visualizer_art_image", _fake_visualizer_art_builder(calls))
    monkeypatch.setattr(metadata, "_sample_visualizer_art_luma", lambda _path: {"useful_luma_low": 0.14, "useful_luma_high": 0.82})

    one = metadata.warm_visualizer_art(str(first), root_id="root", rel="01.mp3", linked_count=2)
    two = metadata.warm_visualizer_art(str(second), root_id="root", rel="02.mp3", linked_count=2)

    assert one is not None and two is not None
    assert one["art_identity"] == two["art_identity"]
    assert one["path"] == two["path"]
    assert len(calls) == 1
    assert one["linked_track_count"] == 2


def test_visualizer_art_cache_version_invalidates_previous_field(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cover = tmp_path / "cover.jpg"
    song = tmp_path / "song.mp3"
    cover.write_bytes(b"cover")
    song.write_bytes(b"song")
    monkeypatch.setattr(metadata, "visualizer_art_cache_dir", lambda: str(cache))
    monkeypatch.setattr(metadata, "art_for_media_path", lambda _path: str(cover))
    calls: list[str] = []
    monkeypatch.setattr(metadata, "_build_visualizer_art_image", _fake_visualizer_art_builder(calls))
    monkeypatch.setattr(metadata, "_sample_visualizer_art_luma", lambda _path: {"useful_luma_low": 0.1, "useful_luma_high": 0.9})

    first = metadata.warm_visualizer_art(str(song))
    monkeypatch.setattr(metadata, "VISUALIZER_ART_ALGORITHM_VERSION", metadata.VISUALIZER_ART_ALGORITHM_VERSION + 1)
    second = metadata.warm_visualizer_art(str(song))

    assert first is not None and second is not None
    assert first["cache_key"] != second["cache_key"]
    assert len(calls) == 2


def test_robust_luma_percentiles_normalize_dark_and_bright_fields():
    dark = bytes([12, 12, 12] * 96 + [50, 50, 50] * 4)
    bright = bytes([205, 205, 205] * 96 + [250, 250, 250] * 4)
    dark_luma = metadata._robust_visualizer_luma(dark)
    bright_luma = metadata._robust_visualizer_luma(bright)

    assert dark_luma is not None and bright_luma is not None
    assert dark_luma["useful_luma_high"] < bright_luma["useful_luma_low"]
    assert metadata.normalize_visualizer_art_luma(dark_luma["useful_luma_low"], dark_luma["useful_luma_low"], dark_luma["useful_luma_high"]) == 0.0
    assert metadata.normalize_visualizer_art_luma(dark_luma["useful_luma_high"], dark_luma["useful_luma_low"], dark_luma["useful_luma_high"]) == 1.0
    assert metadata.normalize_visualizer_art_luma(bright_luma["useful_luma_low"], bright_luma["useful_luma_low"], bright_luma["useful_luma_high"]) == 0.0
    assert metadata.normalize_visualizer_art_luma(bright_luma["useful_luma_high"], bright_luma["useful_luma_low"], bright_luma["useful_luma_high"]) == 1.0


def test_clipped_grayscale_extremes_do_not_define_visualizer_band_range():
    raw = (
        bytes([0, 0, 0] * 80)
        + bytes([255, 255, 255] * 80)
        + bytes([51, 51, 51] * 20)
        + bytes([204, 204, 204] * 20)
    )
    bounds = metadata._robust_visualizer_luma(raw)
    assert bounds is not None
    assert 0.18 < bounds["useful_luma_low"] < 0.23
    assert 0.77 < bounds["useful_luma_high"] < 0.82


def test_colorful_regions_define_range_despite_dominant_neutral_background():
    colors = bytes([140, 0, 0] * 50 + [0, 190, 0] * 50)
    neutral = bytes([30, 30, 30] * 400 + [230, 230, 230] * 400)
    bounds = metadata._robust_visualizer_luma(neutral + colors)
    assert bounds is not None
    assert bounds["useful_luma_low"] == pytest.approx(140 * 0.2126 / 255)
    assert bounds["useful_luma_high"] == pytest.approx(190 * 0.7152 / 255)
    # Neutral padding must not change the range assigned to these colors.
    assert bounds == metadata._robust_visualizer_luma(colors)


def test_very_dark_and_bright_colors_are_not_removed_by_fixed_cutoffs():
    dark = metadata._robust_visualizer_luma(bytes([0, 0, 80] * 50 + [0, 0, 160] * 50))
    bright = metadata._robust_visualizer_luma(bytes([255, 255, 180] * 50 + [255, 255, 220] * 50))
    assert dark is not None and bright is not None
    assert dark["useful_luma_low"] < metadata.VISUALIZER_BAND_LUMA_MIN
    assert bright["useful_luma_high"] > metadata.VISUALIZER_BAND_LUMA_MAX
    for bounds in (dark, bright):
        assert bounds["useful_luma_high"] - bounds["useful_luma_low"] >= metadata.VISUALIZER_MIN_LUMA_SPAN - 1e-9


def test_isolated_color_noise_keeps_grayscale_mapping():
    gray = bytes([51, 51, 51] * 100 + [204, 204, 204] * 100)
    assert metadata._robust_visualizer_luma(gray + bytes([255, 0, 0])) == metadata._robust_visualizer_luma(gray)
