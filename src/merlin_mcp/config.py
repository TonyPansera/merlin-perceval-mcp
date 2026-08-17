"""Registry of documented libraries and process-wide settings.

Every library this server can answer questions about is described by a single
:class:`LibrarySource`. Both currently registered libraries are Sphinx builds that
publish the same machine-readable artifacts (``objects.inv``, ``searchindex.js``,
``_sources/*.txt``), so all fetching and parsing code is written once against this
dataclass. Supporting another such library is one more registry entry.

Every URL-building method here validates its caller-supplied arguments and confines
the result to the library's own site or repository, so no tool argument can redirect
a request elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from .errors import UnknownLibraryError
from .urls import confined, quote_path, validate_docname, validate_ref, validate_version

_GITHUB_API = "https://api.github.com"
_GITHUB_RAW = "https://raw.githubusercontent.com"


@dataclass(frozen=True)
class LibrarySource:
    """Everything needed to locate one library's docs, source and releases."""

    key: str
    """Short identifier used as the ``library`` argument of every tool."""

    title: str
    """Human-readable name used in tool output."""

    docs_base: str
    """Base URL whose direct children are version directories, without trailing slash.

    The landing page at ``{docs_base}/`` redirects to the current version, which is how
    the server discovers the version to serve without hardcoding it.
    """

    repo: str
    """GitHub ``owner/name`` of the upstream project."""

    package_dir: str
    """Top-level import package directory inside the repository."""

    pypi: str
    """Distribution name on PyPI."""

    notebook_dir: str
    """Repository path holding example notebooks."""

    gallery_dir: str | None
    """Repository path holding curated example gallery JSON, if the project has one."""

    fallback_version: str
    """Docs version used only if every discovery method fails."""

    install_name: str
    """What a user types to install the library."""

    def version_base(self, version: str) -> str:
        """Base URL of one built version of the documentation."""
        checked = validate_version(version)
        return confined(f"{self.docs_base}/{checked}", self.docs_base)

    def docs_url(self, version: str, suffix: str) -> str:
        """A URL under one documentation version, confined to that version directory."""
        base = self.version_base(version)
        return confined(f"{base}/{suffix.lstrip('/')}", base)

    def page_url(self, version: str, docname: str) -> str:
        """Rendered HTML URL of a documentation page."""
        checked = validate_docname(docname)
        return self.docs_url(version, f"{quote_path(checked)}.html")

    def source_url(self, version: str, docname: str, suffix: str = "rst") -> str:
        """URL of the Sphinx-published raw source of a documentation page."""
        checked = validate_docname(docname)
        return self.docs_url(version, f"_sources/{quote_path(checked)}.{suffix}.txt")

    def raw_url(self, ref: str, path: str) -> str:
        """URL of a file in the upstream repository, served by raw.githubusercontent.com."""
        checked_ref = validate_ref(ref)
        checked_path = validate_docname(path)
        base = f"{_GITHUB_RAW}/{self.repo}/{checked_ref}"
        return confined(f"{base}/{quote_path(checked_path)}", base)

    def api_url(self, suffix: str = "") -> str:
        """URL under this repository's GitHub API namespace."""
        base = f"{_GITHUB_API}/repos/{self.repo}"
        return confined(f"{base}/{suffix.lstrip('/')}", base) if suffix else base

    @property
    def pypi_url(self) -> str:
        """URL of this library's PyPI metadata."""
        base = "https://pypi.org/pypi"
        return confined(f"{base}/{quote_path(self.pypi)}/json", base)


MERLIN = LibrarySource(
    key="merlin",
    title="MerLin",
    docs_base="https://merlinquantum.ai",
    repo="merlinquantum/merlin",
    package_dir="merlin",
    pypi="merlinquantum",
    notebook_dir="docs/source/notebooks",
    gallery_dir="docs/source/_data/galleries",
    fallback_version="0.4",
    install_name="merlinquantum",
)

PERCEVAL = LibrarySource(
    key="perceval",
    title="Perceval",
    docs_base="https://perceval.quandela.net/docs",
    repo="Quandela/Perceval",
    package_dir="perceval",
    pypi="perceval-quandela",
    notebook_dir="docs/source/notebooks",
    gallery_dir=None,
    fallback_version="v1.2",
    install_name="perceval-quandela",
)

LIBRARIES: dict[str, LibrarySource] = {MERLIN.key: MERLIN, PERCEVAL.key: PERCEVAL}


def get_library(key: str | None) -> LibrarySource:
    """Look up a registered library, defaulting to MerLin.

    Raises:
        UnknownLibraryError: if ``key`` is not registered.
    """
    if not key:
        return MERLIN
    try:
        return LIBRARIES[key.strip().lower()]
    except KeyError:
        known = ", ".join(sorted(LIBRARIES))
        raise UnknownLibraryError(f"unknown library {key!r}; known libraries: {known}") from None


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime settings, all overridable by environment variable."""

    timeout: float
    index_ttl: float
    page_ttl: float

    not_found_ttl: float
    """How long a 404 is remembered. Deliberately short: a page missing during a docs
    redeploy should not be reported as absent for the whole index lifetime."""

    max_response_bytes: int
    """Hard cap on any single response body, to bound memory use."""

    github_token: str | None
    user_agent: str
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        from . import __version__

        ttl = _float_env("MERLIN_MCP_CACHE_TTL", 3600.0)
        return cls(
            timeout=_float_env("MERLIN_MCP_TIMEOUT", 30.0),
            index_ttl=ttl,
            page_ttl=_float_env("MERLIN_MCP_PAGE_CACHE_TTL", min(ttl, 900.0)),
            not_found_ttl=_float_env("MERLIN_MCP_NOT_FOUND_TTL", 60.0),
            max_response_bytes=int(_float_env("MERLIN_MCP_MAX_RESPONSE_BYTES", 32 * 1024 * 1024)),
            github_token=os.environ.get("MERLIN_MCP_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN"),
            user_agent=os.environ.get(
                "MERLIN_MCP_USER_AGENT",
                f"merlin-mcp/{__version__} (+https://github.com/tonypansera/merlin-mcp)",
            ),
            log_level=os.environ.get("MERLIN_MCP_LOG_LEVEL", "WARNING").upper(),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read from the environment once.

    Call this rather than importing a module-level instance: a value bound at import
    time in several modules cannot be replaced, which makes the settings untestable
    and the environment effectively read-only after the first import. Tests call
    ``get_settings.cache_clear()``.
    """
    return Settings.from_env()


def pinned_version(library: LibrarySource) -> str | None:
    """Docs version pinned for a library via environment, if any."""
    return os.environ.get(f"MERLIN_MCP_{library.key.upper()}_VERSION") or None
