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
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_STATIC_HEADER = struct.Struct(">BH")


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


def migrate_legacy_palette_data(conn) -> dict[str, int]:
    counts = {"static": 0}
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
    conn.execute("INSERT INTO legacy_imports(source_path,source_kind,imported_at,row_counts_json,backup_path) VALUES(?,?,?,?,?)",
        (marker, "palette", time.time(), json.dumps(counts, sort_keys=True), ""))
    return counts
