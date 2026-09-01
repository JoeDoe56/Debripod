from __future__ import annotations

import math

from debripod.Library import metadata
from debripod.Library.library_db import load_visualizer_analysis, save_visualizer_analysis
from debripod.storage import database


def _tone_frame(center_hz: int) -> bytes:
    samples = int(metadata.ANALYSIS_SAMPLE_RATE_HZ / metadata.ANALYSIS_RATE_HZ)
    waveform = [
        0.7 * math.sin(2 * math.pi * center_hz * index / metadata.ANALYSIS_SAMPLE_RATE_HZ)
        for index in range(samples)
    ]
    frame, _energy = metadata._audio_feature_frame(waveform, 0.0)
    return frame


def test_nine_representative_tones_favor_their_matching_bands():
    assert metadata.ANALYSIS_SAMPLE_RATE_HZ == 16000
    assert metadata.ANALYSIS_BANDS == [60, 110, 190, 330, 600, 1050, 1900, 3400, 6200]
    for expected_index, center in enumerate(metadata.ANALYSIS_BANDS):
        frame = _tone_frame(center)
        assert len(frame) == 11
        assert max(range(9), key=lambda index: frame[index]) == expected_index


def test_delta_and_zlib_analysis_storage_round_trip():
    raw = b"".join(_tone_frame(center) for center in metadata.ANALYSIS_BANDS)
    stored, encoding = metadata._compress_analysis_blob(raw)
    assert encoding == metadata.ANALYSIS_DELTA_ENCODING
    assert metadata._decompress_analysis_blob(stored, encoding) == raw
    activity = metadata._analysis_activity_metadata(raw)
    assert activity["band_centers_hz"] == metadata.ANALYSIS_BANDS
    assert activity["lowest_active_band"] == 0
    assert activity["highest_active_band"] == 8


def test_db_returns_raw_frames_and_rejects_old_versions_or_decoder_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "analysis.sqlite3"))
    database.initialize_database()
    media_path = tmp_path / "tone.wav"
    media_path.write_bytes(b"fixture")
    raw = _tone_frame(600) + _tone_frame(1900)
    stored, encoding = metadata._compress_analysis_blob(raw)
    key = "nine-band"
    save_visualizer_analysis(
        key,
        media_id="media",
        root_id="root",
        rel="tone.wav",
        abs_path=str(media_path),
        duration=0.1,
        analysis_rate_hz=30,
        band_count=9,
        frame_count=2,
        feature_blob=stored,
        compression=encoding,
        decoder_settings_hash=metadata.DECODER_SETTINGS_HASH,
        metadata=metadata._analysis_metadata(raw, stored),
    )
    loaded = load_visualizer_analysis(key, decoder_settings_hash=metadata.DECODER_SETTINGS_HASH)
    assert loaded is not None
    assert loaded["feature_blob"] == raw
    assert loaded["metadata"]["frame_stride"] == 11
    assert len(loaded["feature_blob"]) == loaded["frame_count"] * loaded["metadata"]["frame_stride"]
    assert load_visualizer_analysis(key, decoder_settings_hash="old-decoder") is None
    with database.database() as conn:
        conn.execute("UPDATE visualizer_analysis SET algorithm_version=2 WHERE analysis_key=?", (key,))
    assert load_visualizer_analysis(key, decoder_settings_hash=metadata.DECODER_SETTINGS_HASH) is None
