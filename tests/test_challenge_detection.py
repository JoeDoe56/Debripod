from pathlib import Path
from types import SimpleNamespace

from debripod.Services.indexers.challenge_detection import detect_challenge


FIXTURES = Path(__file__).parent / "fixtures" / "cardigann"


def _response(status, text, headers=None):
    return SimpleNamespace(status_code=status, text=text, headers=headers or {})


def test_positive_cloudflare_and_ddos_signatures():
    html = (FIXTURES / "challenge_cloudflare.html").read_text(encoding="utf-8")
    detected = detect_challenge(_response(503, html, {"Server": "cloudflare"}))
    assert detected.detected and detected.confidence > .5
    assert "server:cloudflare" in detected.signatures


def test_ordinary_failures_are_not_challenges():
    login = (FIXTURES / "login_page.html").read_text(encoding="utf-8")
    for response in [_response(200, ""), _response(404, "Access denied"), _response(503, "Maintenance"), _response(401, login)]:
        assert not detect_challenge(response).detected
