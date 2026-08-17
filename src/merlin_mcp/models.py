"""Plain data records passed between the source layer and the tool layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict


@dataclass(frozen=True)
class Symbol:
    """One entry of a Sphinx ``objects.inv`` inventory."""

    name: str
    """Fully qualified dotted name, e.g. ``merlin.algorithms.layer.QuantumLayer``."""

    role: str
    """Sphinx role such as ``py:class`` or ``std:label``."""

    uri: str
    """Documentation URI relative to the version base, including the anchor."""

    display_name: str
    """Human-readable name, or the dotted name when the inventory records ``-``."""

    @property
    def kind(self) -> str:
        """The role without its domain prefix: ``class``, ``function``, ``label``..."""
        return self.role.split(":", 1)[-1]

    @property
    def is_python(self) -> bool:
        """True for entries of the Sphinx Python domain."""
        return self.role.startswith("py:")


VersionOrigin = Literal["explicit", "pinned", "landing", "pypi", "fallback"]


@dataclass(frozen=True)
class ResolvedVersion:
    """A docs version together with how it was arrived at.

    The origin matters to the caller: a version discovered from the live site is a
    fact, while the compiled-in fallback is a guess made after every discovery route
    failed. Reporting the second as though it were the first is how a server that
    cannot reach its upstream ends up quietly answering from the wrong release.
    """

    version: str
    origin: VersionOrigin

    @property
    def is_fallback(self) -> bool:
        """True when every discovery route failed and a compiled-in guess is in use."""
        return self.origin == "fallback"

    def __str__(self) -> str:
        return self.version


class SymbolDetails(TypedDict):
    """What :func:`merlin_mcp.sources.repo.describe_symbol` extracts from source."""

    kind: Literal["module", "class", "function", "data"]
    signature: str
    docstring: str
    members: list[str]
    bases: list[str]
    init_docstring: str


@dataclass
class SearchHit:
    """One documentation page matched by a full-text search."""

    docname: str
    title: str
    url: str
    score: float
    matched_terms: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExampleRef:
    """A notebook example, optionally enriched by a curated gallery entry."""

    name: str
    """Stable identifier used by ``get_example``, e.g. ``notebooks/FirstQuantumLayers``."""

    title: str
    summary: str = ""
    tags: tuple[str, ...] = ()
    path: str = ""
    """Repository path of the notebook."""


@dataclass(frozen=True)
class Release:
    """A GitHub release of an upstream project."""

    tag: str
    name: str
    published_at: str
    """Upstream ISO-8601 timestamp, passed through verbatim."""

    url: str
    body: str
