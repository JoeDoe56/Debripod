from __future__ import annotations

import hashlib
import hmac
import secrets


SCRYPT_N = 32768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
PBKDF2_MAX_ITERATIONS = 10_000_000
MIN_DIGEST_BYTES = 16
MAX_DIGEST_BYTES = 128


def generate_password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        str(password).encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}${salt}${digest.hex()}"


def _decode_hash(encoded: str) -> tuple[str, str, bytes]:
    method, salt, digest = str(encoded or "").split("$", 2)
    expected = bytes.fromhex(digest)
    if not salt or not expected:
        raise ValueError("invalid password hash")
    return method, salt, expected


def password_hash_supported(encoded: str) -> bool:
    """Return whether *encoded* is a bounded password hash we can verify."""
    try:
        method, salt, expected = _decode_hash(encoded)
        if len(salt) > 1024 or not (MIN_DIGEST_BYTES <= len(expected) <= MAX_DIGEST_BYTES):
            return False
        parts = method.split(":")
        if parts[0] == "scrypt" and len(parts) == 4:
            n, r, p = (int(value) for value in parts[1:])
            return bool(
                2 <= n <= 1_048_576
                and not n & (n - 1)
                and 1 <= r <= 64
                and 1 <= p <= 16
            )
        if parts[:2] == ["pbkdf2", "sha256"] and len(parts) == 3:
            iterations = int(parts[2])
            return 1 <= iterations <= PBKDF2_MAX_ITERATIONS
    except (ValueError, TypeError, OverflowError):
        pass
    return False


def verify_password_hash(encoded: str, password: str) -> tuple[bool, bool]:
    """Return ``(valid, needs_upgrade)`` for current and legacy local hashes."""
    if not password_hash_supported(encoded):
        return False, False
    try:
        method, salt, expected = _decode_hash(encoded)
        parts = method.split(":")
        if parts[0] == "scrypt" and len(parts) == 4:
            n, r, p = (int(value) for value in parts[1:])
            actual = hashlib.scrypt(
                str(password).encode("utf-8"),
                salt=salt.encode("utf-8"),
                n=n,
                r=r,
                p=p,
                dklen=len(expected),
                maxmem=max(64 * 1024 * 1024, 256 * n * r),
            )
            valid = hmac.compare_digest(actual, expected)
            canonical = (n, r, p, len(expected)) == (SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
            return valid, bool(valid and not canonical)
        if parts[:2] == ["pbkdf2", "sha256"] and len(parts) == 3:
            iterations = int(parts[2])
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                str(password).encode("utf-8"),
                salt.encode("utf-8"),
                iterations,
                dklen=len(expected),
            )
            valid = hmac.compare_digest(actual, expected)
            return valid, valid
    except (ValueError, TypeError, OverflowError):
        pass
    return False, False


def check_password_hash(encoded: str, password: str) -> bool:
    return verify_password_hash(encoded, password)[0]
