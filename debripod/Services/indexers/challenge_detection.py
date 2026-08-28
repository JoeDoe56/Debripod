from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChallengeDetection:
    detected: bool
    confidence: float = 0.0
    signatures: list[str] = field(default_factory=list)


def detect_challenge(response: Any, configured_marker: str = "") -> ChallengeDetection:
    status = int(getattr(response, "status_code", 0) or 0)
    headers = {str(key).casefold(): str(value).casefold() for key, value in dict(getattr(response, "headers", {}) or {}).items()}
    text = str(getattr(response, "text", "") or "")
    lower = text.casefold()
    signatures: list[str] = []
    if status not in {403, 503}:
        return ChallengeDetection(False)
    server = headers.get("server", "")
    if "cloudflare" in server:
        signatures.append("server:cloudflare")
    if "ddos-guard" in server:
        signatures.append("server:ddos-guard")
    for title in ("just a moment", "attention required", "access denied", "ddos-guard"):
        if re.search(r"<title[^>]*>[^<]*" + re.escape(title), lower):
            signatures.append("title:" + title)
    markers = {
        "cloudflare:1020": "error code 1020",
        "turnstile": "challenges.cloudflare.com/turnstile",
        "managed_challenge": "managed challenge",
        "challenge_platform": "/cdn-cgi/challenge-platform/",
        "javascript_form": "challenge-form",
    }
    for name, marker in markers.items():
        if marker in lower:
            signatures.append(name)
    if configured_marker and configured_marker.casefold() in lower:
        signatures.append("definition_marker")
    confidence = min(1.0, 0.45 + 0.2 * len(signatures)) if signatures else 0.0
    return ChallengeDetection(bool(signatures), confidence, signatures)
