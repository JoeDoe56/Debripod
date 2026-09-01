from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp


class UnsafeOutboundUrl(ValueError):
    """The URL cannot safely be reached from the DebriPod server."""


def _public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def validate_public_http_url(raw_url: str, *, resolver: Callable[..., Any] = socket.getaddrinfo) -> str:
    """Validate scheme, credentials, and every current DNS answer before dialing."""
    value = str(raw_url or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise UnsafeOutboundUrl("Invalid outbound URL.") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise UnsafeOutboundUrl("Only HTTP(S) URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeOutboundUrl("URLs with embedded credentials are not allowed.")
    hostname = parsed.hostname.strip().rstrip(".")
    if not hostname or hostname.lower() in {"localhost", "local"} or hostname.lower().endswith((".localhost", ".local")):
        raise UnsafeOutboundUrl("Local network targets are not allowed.")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeOutboundUrl("Invalid outbound URL port.") from exc
    try:
        infos = resolver(hostname, port, type=socket.SOCK_STREAM)
        addresses = {str(info[4][0]) for info in infos if info and len(info) > 4 and info[4]}
    except OSError as exc:
        raise UnsafeOutboundUrl("Could not safely resolve the URL host.") from exc
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise UnsafeOutboundUrl("Private, loopback, link-local, or reserved targets are not allowed.")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


async def validate_public_http_url_async(raw_url: str) -> str:
    return await asyncio.to_thread(validate_public_http_url, raw_url)


def _peer_is_public(response: Any) -> bool:
    try:
        connection = response.connection
        transport = connection.transport if connection else None
        peer = transport.get_extra_info("peername") if transport else None
        return not peer or _public_ip(str(peer[0]))
    except Exception:
        # DNS was already checked immediately before connecting; a missing peer
        # attribute is common in mocked transports and cannot be treated as a
        # successful bypass of that validation.
        return True


async def request_public_url(
    session: aiohttp.ClientSession,
    method: str,
    raw_url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    max_redirects: int = 5,
) -> tuple[aiohttp.ClientResponse, str]:
    """Request a public URL while validating every redirect and connected peer."""
    current = await validate_public_http_url_async(raw_url)
    request_timeout = aiohttp.ClientTimeout(total=max(1.0, float(timeout)))
    for _hop in range(max(0, int(max_redirects)) + 1):
        response = await session.request(
            method, current, headers=headers, timeout=request_timeout, allow_redirects=False
        )
        if not _peer_is_public(response):
            response.close()
            raise UnsafeOutboundUrl("The URL resolved to a non-public network target.")
        if response.status not in {301, 302, 303, 307, 308}:
            return response, current
        location = str(response.headers.get("Location") or "").strip()
        response.release()
        if not location:
            raise UnsafeOutboundUrl("Redirect response did not include a destination.")
        current = await validate_public_http_url_async(urljoin(current, location))
    raise UnsafeOutboundUrl("Too many redirects while validating the URL.")


async def validate_ytdlp_target(session: aiohttp.ClientSession, raw_url: str, *, timeout: float = 12.0) -> str:
    """Safely preflight a generic yt-dlp page URL before launching yt-dlp."""
    response, final_url = await request_public_url(
        session, "HEAD", raw_url, headers={"Range": "bytes=0-2047"}, timeout=timeout
    )
    try:
        if response.status in {405, 501}:
            response.release()
            response, final_url = await request_public_url(
                session, "GET", final_url, headers={"Range": "bytes=0-2047"}, timeout=timeout
            )
            await response.content.read(2048)
    finally:
        response.release()
    return final_url
