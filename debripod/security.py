from __future__ import annotations

import ipaddress
from typing import Any


def is_trusted_local_proxy(request: Any) -> bool:
    """Only a loopback peer may supply forwarding headers to this local app."""
    peer = str(getattr(request, "remote", "") or "").strip().strip("[]")
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return peer.lower() == "localhost"


def trusted_forwarded_scheme(request: Any) -> str:
    if not is_trusted_local_proxy(request):
        return ""
    proto = str((getattr(request, "headers", {}) or {}).get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
    if proto in {"http", "https"}:
        return proto
    forwarded = str((getattr(request, "headers", {}) or {}).get("Forwarded") or "")
    for part in forwarded.split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key.lower() == "proto":
            candidate = value.strip('"').lower()
            if candidate in {"http", "https"}:
                return candidate
    return ""


def request_is_secure(request: Any) -> bool:
    return bool(getattr(request, "secure", False) or trusted_forwarded_scheme(request) == "https")


def external_scheme(request: Any) -> str:
    return trusted_forwarded_scheme(request) or ("https" if getattr(request, "secure", False) else "http")
