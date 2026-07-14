from __future__ import annotations

import json
import re
import struct
import time
from typing import Any

from .codec import decode as decode_envelope
from .codec import encode as encode_envelope
from .database import database

PALETTE_ENCODING_VERSION = 1
VIDEO_TIMELINE_ENCODING_VERSION = 1
VIDEO_PALETTE_SAMPLE_RATE_HZ = 2
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_STATIC_HEADER = struct.Struct(">BH")
_VIDEO_HEADER = struct.Struct(">BHI")
_SAMPLE_HEADER = struct.Struct(">IH")


def _rgb(value: Any) -> tuple[int, int, int] | None:
    if isinstance(value, str):
        match = _HEX.match(value.strip())
        if match:
            raw = match.group(1)
            return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return tuple(max(0, min(255, int(value[i]))) for i in range(3))  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def source_colors(palette: Any) -> list[tuple[int, int, int]]:
    values = palette.get("colors", []) if isinstance(palette, dict) else palette
    out: list[tuple[int, int, int]] = []
    if isinstance(values, list):
        for value in values:
            color = _rgb(value)
            if color and color not in out:
                out.append(color)
    return out


def pack_colors(colors: list[Any]) -> bytes:
    clean = [color for value in colors if (color := _rgb(value))]
    return _STATIC_HEADER.pack(PALETTE_ENCODING_VERSION, len(clean)) + bytes(channel for color in clean for channel in color)


def unpack_colors(blob: bytes) -> list[list[int]]:
    value = bytes(blob)
    if len(value) < _STATIC_HEADER.size:
        raise ValueError("Truncated palette")
    version, count = _STATIC_HEADER.unpack(value[: _STATIC_HEADER.size])
    if version != PALETTE_ENCODING_VERSION or len(value) != _STATIC_HEADER.size + count * 3:
        raise ValueError("Invalid palette encoding")
    payload = value[_STATIC_HEADER.size:]
    return [list(payload[i:i + 3]) for i in range(0, len(payload), 3)]


def save_palette(palette_key: str, palette: Any, *, root_id: str = "", rel: str = "", source_kind: str = "", source_identity: str = "") -> None:
    colors = source_colors(palette)
    raw = pack_colors(colors)
    envelope, codec_name, raw_len = encode_envelope(raw)
    with database() as conn:
        conn.execute("""INSERT INTO media_palettes(palette_key,root_id,rel,source_kind,source_identity,color_count,colors_blob,
          encoding_version,compression,uncompressed_bytes,saved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(palette_key) DO UPDATE SET root_id=excluded.root_id,rel=excluded.rel,source_kind=excluded.source_kind,
          source_identity=excluded.source_identity,color_count=excluded.color_count,colors_blob=excluded.colors_blob,
          encoding_version=excluded.encoding_version,compression=excluded.compression,uncompressed_bytes=excluded.uncompressed_bytes,saved_at=excluded.saved_at""",
          (palette_key, root_id, rel, source_kind, source_identity, len(colors), envelope, PALETTE_ENCODING_VERSION, codec_name, raw_len, time.time()))


def load_palette(palette_key: str = "", *, root_id: str = "", rel: str = "") -> dict[str, Any] | None:
    with database(write=False) as conn:
        if palette_key:
            row = conn.execute("SELECT * FROM media_palettes WHERE palette_key=?", (palette_key,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM media_palettes WHERE root_id=? AND rel=? ORDER BY saved_at DESC LIMIT 1", (root_id, rel)).fetchone()
    if not row:
        return None
    colors = unpack_colors(decode_envelope(row["colors_blob"]))
    return {"version": int(row["encoding_version"]), "colors": colors, "paletteKey": str(row["palette_key"])}


def pack_video_timeline(samples: list[tuple[int, list[Any]]], sample_count: int, sample_rate_hz: int = VIDEO_PALETTE_SAMPLE_RATE_HZ) -> bytes:
    changed: list[tuple[int, list[tuple[int, int, int]]]] = []
    previous: list[tuple[int, int, int]] | None = None
    for position, values in samples:
        colors = [color for value in values if (color := _rgb(value))]
        if colors == previous:
            continue
        changed.append((max(0, int(position)), colors))
        previous = colors
    out = bytearray(_VIDEO_HEADER.pack(VIDEO_TIMELINE_ENCODING_VERSION, int(sample_rate_hz), max(0, int(sample_count))))
    for position, colors in changed:
        out.extend(_SAMPLE_HEADER.pack(position, len(colors)))
        out.extend(channel for color in colors for channel in color)
    return bytes(out)


def unpack_video_timeline(raw: bytes) -> dict[str, Any]:
    value = bytes(raw)
    if len(value) < _VIDEO_HEADER.size:
        raise ValueError("Truncated video palette timeline")
    version, rate, count = _VIDEO_HEADER.unpack(value[:_VIDEO_HEADER.size])
    if version != VIDEO_TIMELINE_ENCODING_VERSION:
        raise ValueError("Unsupported video palette timeline")
    offset, samples = _VIDEO_HEADER.size, []
    while offset < len(value):
        if offset + _SAMPLE_HEADER.size > len(value):
            raise ValueError("Truncated video palette sample")
        position, color_count = _SAMPLE_HEADER.unpack(value[offset:offset + _SAMPLE_HEADER.size])
        offset += _SAMPLE_HEADER.size
        byte_count = color_count * 3
        if offset + byte_count > len(value):
            raise ValueError("Truncated video palette colors")
        colors = [list(value[i:i + 3]) for i in range(offset, offset + byte_count, 3)]
        samples.append({"position": position, "colors": colors})
        offset += byte_count
    return {"version": version, "sampleRateHz": rate, "sampleCount": count, "samples": samples}


def save_video_timeline(analysis_key: str, samples: list[tuple[int, list[Any]]], *, sample_count: int, media_id: str = "",
                        root_id: str = "", rel: str = "", abs_path: str = "", size: int = 0, mtime_ns: int = 0) -> None:
    raw = pack_video_timeline(samples, sample_count)
    envelope, codec_name, raw_len = encode_envelope(raw)
    with database() as conn:
        conn.execute("""INSERT INTO video_palette_timelines(analysis_key,media_id,root_id,rel,abs_path,size,mtime_ns,encoding_version,
          sample_rate_hz,sample_count,payload_blob,compression,uncompressed_bytes,saved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(analysis_key) DO UPDATE SET media_id=excluded.media_id,root_id=excluded.root_id,rel=excluded.rel,
          abs_path=excluded.abs_path,size=excluded.size,mtime_ns=excluded.mtime_ns,encoding_version=excluded.encoding_version,
          sample_rate_hz=excluded.sample_rate_hz,sample_count=excluded.sample_count,payload_blob=excluded.payload_blob,
          compression=excluded.compression,uncompressed_bytes=excluded.uncompressed_bytes,saved_at=excluded.saved_at""",
          (analysis_key, media_id, root_id, rel, abs_path, size, mtime_ns, VIDEO_TIMELINE_ENCODING_VERSION,
           VIDEO_PALETTE_SAMPLE_RATE_HZ, sample_count, envelope, codec_name, raw_len, time.time()))


def load_video_timeline(analysis_key: str) -> dict[str, Any] | None:
    with database(write=False) as conn:
        row = conn.execute("SELECT payload_blob FROM video_palette_timelines WHERE analysis_key=?", (analysis_key,)).fetchone()
    return unpack_video_timeline(decode_envelope(row[0])) if row else None


def migrate_legacy_palette_data(conn) -> dict[str, int]:
    counts = {"static": 0, "video": 0, "invalid_video": 0}
    marker = "__palette-v1__"
    if conn.execute("SELECT 1 FROM legacy_imports WHERE source_path=?", (marker,)).fetchone():
        return counts
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='art_palette_cache'").fetchone():
        for row in conn.execute("SELECT cache_key,root_id,rel,source_kind,source_identity,palette_json,saved_at FROM art_palette_cache").fetchall():
            try:
                palette = json.loads(row["palette_json"] or "{}")
                colors = source_colors(palette)
                raw = pack_colors(colors)
                envelope, codec_name, raw_len = encode_envelope(raw)
                conn.execute("INSERT OR REPLACE INTO media_palettes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (row["cache_key"], row["root_id"], row["rel"], row["source_kind"], row["source_identity"], len(colors),
                     envelope, PALETTE_ENCODING_VERSION, codec_name, raw_len, row["saved_at"] or time.time()))
                counts["static"] += 1
            except Exception:
                continue
        conn.execute("DELETE FROM art_palette_cache")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='visualizer_analysis'").fetchone():
        rows = conn.execute("SELECT analysis_key,media_id,root_id,rel,abs_path,size,mtime_ns,analysis_rate_hz,metadata_json,saved_at FROM visualizer_analysis").fetchall()
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
                frames = metadata.pop("video_palette_frames", None)
                metadata.pop("video_palette_frame_stride", None)
                metadata.pop("video_palette_encoding", None)
                metadata.pop("video_palette_colors_per_frame", None)
                metadata.pop("palette_source", None)
                if isinstance(frames, list) and frames:
                    old_rate = max(1, int(row["analysis_rate_hz"] or 30))
                    total = max(int(frame[0]) for frame in frames if isinstance(frame, list) and frame) + 1
                    sample_count = max(1, (total * VIDEO_PALETTE_SAMPLE_RATE_HZ + old_rate - 1) // old_rate)
                    samples = []
                    for position in range(sample_count):
                        target = position * old_rate / VIDEO_PALETTE_SAMPLE_RATE_HZ
                        nearest = min(frames, key=lambda frame: abs(float(frame[0]) - target))
                        samples.append((position, nearest[1] if len(nearest) > 1 else []))
                    raw = pack_video_timeline(samples, sample_count)
                    envelope, codec_name, raw_len = encode_envelope(raw)
                    conn.execute("INSERT OR REPLACE INTO video_palette_timelines VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (row["analysis_key"], row["media_id"], row["root_id"], row["rel"], row["abs_path"], row["size"],
                         row["mtime_ns"], VIDEO_TIMELINE_ENCODING_VERSION, VIDEO_PALETTE_SAMPLE_RATE_HZ, sample_count,
                         envelope, codec_name, raw_len, row["saved_at"] or time.time()))
                    counts["video"] += 1
                conn.execute("UPDATE visualizer_analysis SET metadata_json=? WHERE analysis_key=?",
                    (json.dumps(metadata, separators=(",", ":"), ensure_ascii=False), row["analysis_key"]))
            except Exception:
                conn.execute("DELETE FROM video_palette_timelines WHERE analysis_key=?", (row["analysis_key"],))
                counts["invalid_video"] += 1
    conn.execute("INSERT INTO legacy_imports(source_path,source_kind,imported_at,row_counts_json,backup_path) VALUES(?,?,?,?,?)",
        (marker, "palette", time.time(), json.dumps(counts, sort_keys=True), ""))
    return counts
