"""URL construction that cannot be steered outside the configured sources.

Tool arguments (``ref``, ``version``, ``page``, ``name``, ``target``) are
interpolated into request URLs. A string-prefix check on an unnormalised URL is not
enough to constrain where a request goes: ``httpx`` collapses ``..`` path segments
when it builds the request, so a check that passes before normalisation can be
describing a completely different resource than the one actually fetched. Every URL
this server requests is therefore built here, normalised first, and then asserted to
still live under its intended base.
"""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from .errors import InvalidRequestError

# Git refs may contain slashes ("release/1.2") but never "..", and never start with
# a separator. Length is bounded to keep pathological input out of request lines.
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")

# Documentation version directories: "0.4", "v1.2", "0.4.post1". No separators.
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_ref(ref: str) -> str:
    """Return ``ref`` if it is a plausible git ref, otherwise raise.

    Raises:
        InvalidRequestError: if the ref could alter the path structure of a URL.
    """
    candidate = ref.strip()
    if not _REF.match(candidate) or ".." in candidate or "//" in candidate:
        raise InvalidRequestError(f"invalid git ref {ref!r}: expected a branch, tag or commit name")
    return candidate


def validate_version(version: str) -> str:
    """Return ``version`` if it is a plausible docs version directory, otherwise raise.

    Raises:
        InvalidRequestError: if the version could alter the path structure of a URL.
    """
    candidate = version.strip().strip("/")
    if not _VERSION.match(candidate) or ".." in candidate:
        raise InvalidRequestError(
            f"invalid docs version {version!r}: expected something like '0.4' or 'v1.2'"
        )
    return candidate


def validate_docname(docname: str) -> str:
    """Return ``docname`` if it stays inside its documentation tree, otherwise raise.

    Raises:
        InvalidRequestError: if the docname is absolute or contains a parent segment.
    """
    candidate = docname.strip().strip("/")
    segments = candidate.split("/")
    if any(segment in {"..", "."} for segment in segments) or "\\" in candidate:
        raise InvalidRequestError(f"invalid page name {docname!r}: path segments may not traverse")
    if "\x00" in candidate or any("\n" in segment or "\r" in segment for segment in segments):
        raise InvalidRequestError(f"invalid page name {docname!r}")
    return candidate


def quote_path(path: str) -> str:
    """Percent-encode a repository path, keeping ``/`` as the segment separator."""
    return quote(path, safe="/")


def confined(url: str, base: str) -> str:
    """Normalise ``url`` and assert it still lives under ``base``.

    This is the single choke point that makes the host and path prefix of every
    outbound request a property of the code rather than of caller input.

    Raises:
        InvalidRequestError: if the normalised URL escapes ``base``.
    """
    prefix = base.rstrip("/") + "/"
    try:
        normalised = str(httpx.URL(url))
    except (httpx.InvalidURL, ValueError) as exc:
        raise InvalidRequestError(f"could not build a valid URL from {url!r}: {exc}") from exc
    if not normalised.startswith(prefix):
        raise InvalidRequestError(
            f"refusing to request {normalised!r}: it resolves outside {prefix!r}"
        )
    return normalised
