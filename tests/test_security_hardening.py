from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from types import SimpleNamespace

from aiohttp import web

from debripod.factory import security_headers_middleware
from debripod.logging_setup import configure_logging, redact_text
from debripod.security import external_scheme, is_trusted_local_proxy, request_is_secure


def _request(*, remote: str, headers: dict[str, str] | None = None, secure: bool = False):
    return SimpleNamespace(remote=remote, headers=headers or {}, secure=secure)


def test_only_loopback_peers_may_influence_forwarded_https_state():
    local = _request(remote="127.0.0.1", headers={"X-Forwarded-Proto": "https"})
    public = _request(remote="203.0.113.10", headers={"X-Forwarded-Proto": "https"})
    assert is_trusted_local_proxy(local)
    assert request_is_secure(local)
    assert external_scheme(local) == "https"
    assert not is_trusted_local_proxy(public)
    assert not request_is_secure(public)
    assert external_scheme(public) == "http"


def test_security_headers_and_hsts_depend_on_trusted_https():
    async def response(_request):
        return web.Response(text="ok")

    secure_response = asyncio.run(security_headers_middleware(
        _request(remote="::1", headers={"Forwarded": "for=127.0.0.1;proto=https"}), response
    ))
    assert secure_response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in secure_response.headers["Content-Security-Policy"]
    assert secure_response.headers["Strict-Transport-Security"] == "max-age=31536000"

    plain_response = asyncio.run(security_headers_middleware(_request(remote="203.0.113.10"), response))
    assert "Strict-Transport-Security" not in plain_response.headers


def test_rotating_logs_redact_credentials_and_tokens(tmp_path):
    assert "secret-value" not in redact_text("https://alice:secret-value@example.test/path")
    assert "secret-value" not in redact_text("token=secret-value cookie=secret-value")
    assert "secret-value" not in redact_text("Authorization: Bearer secret-value")
    path = configure_logging(tmp_path)
    handlers = [handler for handler in logging.getLogger().handlers if isinstance(handler, RotatingFileHandler)]
    assert path.name == "debripod.log"
    assert handlers


def test_terminal_access_logger_is_configured(tmp_path):
    configure_logging(tmp_path)
    access_logger = logging.getLogger("debripod.access")
    assert access_logger.level == logging.INFO
    assert access_logger.handlers
    assert access_logger.propagate is False
