from __future__ import annotations

import math
import sqlite3

from debripod.Library import metadata
from debripod.Library.library_db import load_visualizer_analysis, save_visualizer_analysis
from debripod.storage import database, migrations


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


def test_video_ambient_migration_removes_server_video_analysis_and_timeline_table():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE visualizer_analysis(root_id TEXT, rel TEXT, metadata_json TEXT);
        CREATE TABLE media_files(root_id TEXT, rel_path TEXT, media_type TEXT);
        CREATE TABLE video_palette_timelines(analysis_key TEXT);
        INSERT INTO visualizer_analysis VALUES('root','video.mp4','{"media_kind":"video"}');
        INSERT INTO visualizer_analysis VALUES('root','song.mp3','{"media_kind":"audio"}');
        INSERT INTO media_files VALUES('root','video.mp4','video');
        """
    )
    migrations._v15(conn)
    assert conn.execute("SELECT COUNT(*) FROM visualizer_analysis").fetchone()[0] == 1
    assert conn.execute("SELECT metadata_json FROM visualizer_analysis").fetchone()[0] == '{"media_kind":"audio"}'
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='video_palette_timelines'").fetchone() is None


def test_server_no_longer_exposes_video_visualizer_enrichment():
    for name in (
        "warm_video_analysis",
        "warm_video_audio_analysis",
        "warm_video_frame_palette_analysis",
        "_compute_video_analysis",
    ):
        assert not hasattr(metadata, name)
