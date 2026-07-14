from __future__ import annotations

import struct
import zlib

MAGIC = b"DPB1"
CODEC_VERSION = 1
RAW = 0
ZLIB = 1
MIN_COMPRESS_BYTES = 1024
MIN_SAVINGS_RATIO = 0.04
_HEADER = struct.Struct(">4sBBQ")


class CodecError(ValueError):
    pass


def encode(value: bytes) -> tuple[bytes, str, int]:
    raw = bytes(value)
    method = RAW
    payload = raw
    if len(raw) > MIN_COMPRESS_BYTES:
        compressed = zlib.compress(raw, level=6)
        if len(compressed) <= int(len(raw) * (1.0 - MIN_SAVINGS_RATIO)):
            method, payload = ZLIB, compressed
    envelope = _HEADER.pack(MAGIC, CODEC_VERSION, method, len(raw)) + payload
    return envelope, "zlib" if method == ZLIB else "raw", len(raw)


def decode(envelope: bytes) -> bytes:
    value = bytes(envelope)
    if len(value) < _HEADER.size:
        raise CodecError("Truncated DebriPod BLOB envelope")
    magic, version, method, expected = _HEADER.unpack(value[: _HEADER.size])
    if magic != MAGIC or version != CODEC_VERSION:
        raise CodecError("Unsupported DebriPod BLOB envelope")
    payload = value[_HEADER.size :]
    if method == RAW:
        raw = payload
    elif method == ZLIB:
        try:
            raw = zlib.decompress(payload)
        except zlib.error as exc:
            raise CodecError("Corrupt zlib payload") from exc
    else:
        raise CodecError(f"Unsupported BLOB compression method: {method}")
    if len(raw) != expected:
        raise CodecError(f"BLOB length mismatch: expected {expected}, got {len(raw)}")
    return raw
