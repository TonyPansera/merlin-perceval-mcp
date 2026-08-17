"""Shared HTTP access layer: one client, cached responses, bounded reads."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, overload

import httpx

from .cache import cache
from .config import get_settings
from .errors import NotFoundError, UpstreamError

logger = logging.getLogger(__name__)

_RETRIABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_GITHUB_API_HOST = "api.github.com"

_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


@dataclass(frozen=True)
class _Response:
    status_code: int
    content: bytes


async def get_client() -> httpx.AsyncClient:
    """Return the process-wide async client, rebuilding it if the event loop changed.

    The previous client is closed rather than dropped: ``httpx.AsyncClient`` has no
    finaliser, so an abandoned one leaks its pooled connections.
    """
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is not None and _client_loop is loop:
        return _client

    if _client is not None:
        stale = _client
        _client, _client_loop = None, None
        try:
            await stale.aclose()
        except (httpx.HTTPError, RuntimeError) as exc:  # e.g. a client of a dead loop
            logger.debug("could not close the previous HTTP client: %s", exc)

    settings = get_settings()
    _client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=settings.timeout,
        headers={"User-Agent": settings.user_agent},
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )
    _client_loop = loop
    return _client


async def aclose() -> None:
    """Close the shared client, if one was created."""
    global _client, _client_loop
    if _client is not None:
        await _client.aclose()
        _client, _client_loop = None, None


def _headers_for(url: httpx.URL) -> dict[str, str]:
    """Headers for one request, including credentials only where they belong.

    The host is read from the parsed URL, after ``..`` segments have been collapsed.
    Checking the raw string instead would let a caller-supplied path segment change
    which resource the token is sent to while still passing the check.
    """
    if url.host != _GITHUB_API_HOST:
        return {}
    headers = {"Accept": "application/vnd.github+json"}
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _read_capped(response: httpx.Response, url: httpx.URL, cap: int) -> bytes:
    """Read a response body, refusing to buffer more than ``cap`` bytes."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > cap:
            raise UpstreamError(f"{url} exceeded the {cap} byte response limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _request(url: str) -> _Response:
    client = await get_client()
    target = httpx.URL(url)
    cap = get_settings().max_response_bytes
    last_error: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            async with client.stream("GET", target, headers=_headers_for(target)) as response:
                if response.status_code not in _RETRIABLE_STATUS:
                    body = await _read_capped(response, target, cap)
                    return _Response(response.status_code, body)
                last_error = UpstreamError(f"{target} returned HTTP {response.status_code}")
        except httpx.HTTPError as exc:  # transport-level failure
            last_error = exc

        if attempt + 1 < _MAX_ATTEMPTS:
            delay = 0.5 * (2**attempt)
            logger.warning("retrying %s in %.1fs after %s", target, delay, last_error)
            await asyncio.sleep(delay)

    raise UpstreamError(f"could not fetch {target} after {_MAX_ATTEMPTS} attempts: {last_error}")


@overload
async def fetch_bytes(
    url: str, *, ttl: float | None = ..., optional: Literal[False] = False
) -> bytes: ...


@overload
async def fetch_bytes(
    url: str, *, ttl: float | None = ..., optional: Literal[True]
) -> bytes | None: ...


async def fetch_bytes(
    url: str, *, ttl: float | None = None, optional: bool = False
) -> bytes | None:
    """GET ``url`` and return its body.

    Args:
        url: absolute URL to fetch.
        ttl: cache lifetime in seconds; defaults to the page TTL.
        optional: when true a 404 yields ``None`` instead of raising.
    """
    settings = get_settings()
    lifetime = settings.page_ttl if ttl is None else ttl

    async def load() -> bytes | None:
        response = await _request(url)
        if response.status_code == 404:
            if optional:
                logger.debug("not found (remembered briefly): %s", url)
                return None
            raise NotFoundError(f"not found: {url}")
        if response.status_code >= 400:
            # Upstream usually explains itself in the body — GitHub rate limits in
            # particular — and that explanation is what makes the error actionable.
            detail = response.content.decode("utf-8", errors="replace").strip()[:200]
            suffix = f": {detail}" if detail else ""
            raise UpstreamError(f"{url} returned HTTP {response.status_code}{suffix}")
        return response.content

    def lifetime_for(value: bytes | None) -> float:
        # A 404 during a docs redeploy should not be believed for the full TTL.
        return settings.not_found_ttl if value is None else lifetime

    return await cache.get_or_set(f"bytes:{url}", load, ttl=lifetime, ttl_for=lifetime_for)


@overload
async def fetch_text(
    url: str, *, ttl: float | None = ..., optional: Literal[False] = False
) -> str: ...


@overload
async def fetch_text(
    url: str, *, ttl: float | None = ..., optional: Literal[True]
) -> str | None: ...


async def fetch_text(url: str, *, ttl: float | None = None, optional: bool = False) -> str | None:
    """GET ``url`` and return its body decoded as UTF-8."""
    raw = (
        await fetch_bytes(url, ttl=ttl, optional=True)
        if optional
        else await fetch_bytes(url, ttl=ttl)
    )
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace")


async def fetch_json(url: str, *, ttl: float | None = None, optional: bool = False) -> Any:
    """GET ``url`` and parse the body as JSON."""
    text = (
        await fetch_text(url, ttl=ttl, optional=True)
        if optional
        else await fetch_text(url, ttl=ttl)
    )
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"{url} did not return valid JSON: {exc}") from exc
