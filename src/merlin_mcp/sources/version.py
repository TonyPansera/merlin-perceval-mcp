"""Discover which documentation version a library currently publishes.

This is what keeps the server maintenance-free. Both documentation sites serve a
landing page at the docs root whose only job is to redirect to the current version
directory, and all three of the redirect mechanisms they use are parsed here. When
upstream ships a new release the server follows it on the next cache expiry, with
no code change and nothing to re-index.

Every result records how it was obtained, so a fallback can be reported as a
fallback instead of being presented as the live version.
"""

from __future__ import annotations

import logging
import re

from ..config import LibrarySource, get_settings, pinned_version
from ..errors import MerlinMcpError
from ..http import fetch_json, fetch_text
from ..models import ResolvedVersion
from ..urls import validate_version

logger = logging.getLogger(__name__)

_CANONICAL = re.compile(r"""rel=["']canonical["']\s+href=["']([^"']+)["']""", re.I)
_META_REFRESH = re.compile(
    r"""http-equiv=["']refresh["'][^>]*content=["'][^"']*url=([^"';]+)["']""", re.I
)
_JS_LATEST = re.compile(r"""const\s+latest\s*=\s*["']([^"']+)["']""")


def _version_from_href(href: str) -> str | None:
    """Extract the version directory from a redirect target such as ``./v1.2/index.html``."""
    cleaned = href.strip().removeprefix("./").lstrip("/")
    if not cleaned:
        return None
    first = cleaned.split("/", 1)[0]
    if not first or first.endswith(".html"):
        return None
    return first


def scan_landing_page(html: str) -> str | None:
    """Find the current version directory named by a docs landing page."""
    for pattern in (_CANONICAL, _META_REFRESH):
        match = pattern.search(html)
        if match:
            version = _version_from_href(match.group(1))
            if version:
                return version
    match = _JS_LATEST.search(html)
    if match:
        return match.group(1).strip("/")
    return None


def _version_from_release(library: LibrarySource, release: str) -> str:
    """Map a PyPI release such as ``0.4.0`` onto a docs directory such as ``0.4``."""
    parts = release.split(".")
    short = ".".join(parts[:2]) if len(parts) >= 2 else release
    return f"v{short}" if library.fallback_version.startswith("v") else short


async def _safe_json(url: str) -> object | None:
    try:
        return await fetch_json(url, ttl=get_settings().index_ttl, optional=True)
    except MerlinMcpError as exc:
        logger.warning("version probe failed for %s: %s", url, exc)
        return None


async def _safe_text(url: str) -> str | None:
    try:
        return await fetch_text(url, ttl=get_settings().index_ttl, optional=True)
    except MerlinMcpError as exc:
        logger.warning("version probe failed for %s: %s", url, exc)
        return None


async def _version_from_pypi(library: LibrarySource) -> str | None:
    data = await _safe_json(library.pypi_url)
    if not isinstance(data, dict):
        return None
    release = (data.get("info") or {}).get("version")
    if not isinstance(release, str) or not release:
        return None
    candidate = _version_from_release(library, release)
    try:
        probe = await _safe_text(f"{library.version_base(candidate)}/objects.inv")
    except MerlinMcpError as exc:
        logger.warning("rejecting PyPI-derived version %r: %s", candidate, exc)
        return None
    return candidate if probe is not None else None


async def resolve_version(library: LibrarySource, override: str | None = None) -> ResolvedVersion:
    """Return the docs version to use for ``library``, and where it came from.

    Resolution order: explicit argument, ``MERLIN_MCP_<LIB>_VERSION`` environment
    pin, the landing-page redirect, the latest PyPI release (verified against the
    docs site), and finally the last-known version compiled into the registry.
    """
    if override:
        return ResolvedVersion(validate_version(override), "explicit")

    pinned = pinned_version(library)
    if pinned:
        return ResolvedVersion(validate_version(pinned), "pinned")

    landing = await _safe_text(f"{library.docs_base}/")
    if landing:
        discovered = scan_landing_page(landing)
        if discovered:
            return ResolvedVersion(validate_version(discovered), "landing")
        logger.warning("%s landing page named no version", library.docs_base)

    from_pypi = await _version_from_pypi(library)
    if from_pypi:
        logger.info("%s docs version came from PyPI, not the docs site", library.key)
        return ResolvedVersion(from_pypi, "pypi")

    logger.warning(
        "could not discover a %s docs version; falling back to %s",
        library.key,
        library.fallback_version,
    )
    return ResolvedVersion(library.fallback_version, "fallback")
