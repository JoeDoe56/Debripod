from __future__ import annotations

import asyncio
import socket

import pytest

from debripod.Services import safe_outbound


def _resolver_for(address: str):
    return lambda _host, _port, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1"])
def test_private_and_metadata_targets_are_rejected(address):
    with pytest.raises(safe_outbound.UnsafeOutboundUrl):
        safe_outbound.validate_public_http_url("https://example.test/path", resolver=_resolver_for(address))


def test_normal_public_http_url_is_accepted():
    assert safe_outbound.validate_public_http_url("https://example.test/watch?q=1#fragment", resolver=_resolver_for("8.8.8.8")) == "https://example.test/watch?q=1"


def test_urls_with_credentials_are_rejected_before_resolution():
    with pytest.raises(safe_outbound.UnsafeOutboundUrl, match="credentials"):
        safe_outbound.validate_public_http_url("https://user:password@example.test/", resolver=_resolver_for("8.8.8.8"))


def test_public_to_private_redirect_is_rejected(monkeypatch):
    class Response:
        status = 302
        headers = {"Location": "http://private.test/metadata"}
        connection = None

        def release(self):
            return None

        def close(self):
            return None

    class Session:
        async def request(self, *_args, **_kwargs):
            return Response()

    async def validate(url: str) -> str:
        if "private.test" in url:
            raise safe_outbound.UnsafeOutboundUrl("Private targets are not allowed.")
        return url

    monkeypatch.setattr(safe_outbound, "validate_public_http_url_async", validate)
    with pytest.raises(safe_outbound.UnsafeOutboundUrl, match="Private"):
        asyncio.run(safe_outbound.request_public_url(Session(), "HEAD", "https://public.test/start"))
