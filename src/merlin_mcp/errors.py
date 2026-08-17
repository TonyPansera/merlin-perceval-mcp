"""Exception types shared across the package."""

from __future__ import annotations


class MerlinMcpError(Exception):
    """Base class for every error raised by this server."""


class UnknownLibraryError(MerlinMcpError):
    """Raised when a tool is called with a library key that is not registered."""


class InvalidRequestError(MerlinMcpError):
    """Raised when a caller-supplied argument would escape the configured sources.

    Tool arguments such as ``ref``, ``version`` and ``page`` end up in request URLs.
    Anything that could redirect a request outside the library's own documentation
    site or repository is rejected here rather than sent.
    """


class UpstreamError(MerlinMcpError):
    """Raised when an upstream site is unreachable or returns an unusable response."""


class NotFoundError(MerlinMcpError):
    """Raised when a requested page, symbol or example does not exist upstream."""


class ParseError(MerlinMcpError):
    """Raised when upstream content exists but could not be parsed.

    Kept distinct from :class:`NotFoundError` on purpose: telling a caller that a
    symbol does not exist when the truth is that its module failed to parse is a
    confident wrong answer, which is worse than an error.
    """
