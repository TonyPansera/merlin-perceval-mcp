"""Read the upstream GitHub repository: file tree, raw sources, releases.

Rendered API documentation loses information that the source retains, so API
signatures come from parsing the real module with :mod:`ast` rather than from
scraping autodoc HTML. File contents are read through ``raw.githubusercontent.com``,
which is not subject to the GitHub API rate limit; only the tree listing and the
release list use the API, once per repository per cache lifetime.

Parse failures are reported as parse failures. Returning "not found" when a module
could not be read or parsed would answer a caller's question with a confident and
plausible untruth, which is worse than an error.
"""

from __future__ import annotations

import ast
import logging
from typing import Any, TypeAlias

from ..config import LibrarySource, get_settings
from ..errors import NotFoundError, ParseError, UpstreamError
from ..http import fetch_json, fetch_text
from ..models import Release, SymbolDetails
from ..urls import validate_ref

logger = logging.getLogger(__name__)

_Definition: TypeAlias = ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


async def resolve_ref(library: LibrarySource, ref: str | None = None) -> str:
    """Return the git ref to read, defaulting to the repository's default branch."""
    if ref:
        return validate_ref(ref)
    data = await fetch_json(library.api_url(), ttl=get_settings().index_ttl, optional=True)
    if isinstance(data, dict):
        branch = data.get("default_branch")
        if isinstance(branch, str) and branch:
            return validate_ref(branch)
    logger.info("could not read the default branch of %s; assuming main", library.repo)
    return "main"


async def list_tree(library: LibrarySource, ref: str) -> list[str]:
    """Every file path in the repository at ``ref``."""
    url = library.api_url(f"git/trees/{validate_ref(ref)}?recursive=1")
    data = await fetch_json(url, ttl=get_settings().index_ttl)
    if not isinstance(data, dict) or "tree" not in data:
        message = data.get("message") if isinstance(data, dict) else None
        raise UpstreamError(
            f"could not list {library.repo}@{ref}: {message or 'unexpected response'}"
        )
    if data.get("truncated"):
        logger.warning("%s@%s file listing was truncated by GitHub", library.repo, ref)
    return [
        entry["path"]
        for entry in data["tree"]
        if isinstance(entry, dict) and entry.get("type") == "blob" and "path" in entry
    ]


async def read_file(library: LibrarySource, ref: str, path: str) -> str:
    """Read one file from the repository."""
    text = await fetch_text(library.raw_url(ref, path), optional=True)
    if text is None:
        raise NotFoundError(f"{path} does not exist in {library.repo}@{ref}")
    return text


async def _try_read(library: LibrarySource, ref: str, path: str) -> str | None:
    """Read a candidate module, distinguishing "absent" from "could not be reached"."""
    try:
        return await read_file(library, ref, path)
    except NotFoundError:
        return None
    except UpstreamError as exc:
        # Returning None here would let an outage look like a missing file, and the
        # caller would go on to report a symbol as non-existent.
        logger.warning("could not read %s@%s:%s: %s", library.repo, ref, path, exc)
        raise


async def find_module_path(
    library: LibrarySource, ref: str, dotted: str, _hops: int = 1
) -> tuple[str, list[str]] | None:
    """Split a dotted name into the module file defining it and the remaining path.

    ``merlin.algorithms.layer.QuantumLayer`` resolves to
    ``("merlin/algorithms/layer.py", ["QuantumLayer"])``. A name re-exported by a
    package — ``merlin.QuantumLayer`` — is followed to the module that defines it.
    """
    parts = [part for part in dotted.replace("/", ".").split(".") if part]
    if not parts:
        return None
    if parts[0] != library.package_dir:
        parts = [library.package_dir, *parts]
    if parts[-1] == "py":
        parts = parts[:-1]

    paths = set(await list_tree(library, ref))
    for cut in range(len(parts), 0, -1):
        stem = "/".join(parts[:cut])
        remainder = parts[cut:]
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if candidate not in paths:
                continue
            if not remainder:
                return candidate, remainder

            source = await _try_read(library, ref, candidate)
            if source is None:
                continue
            # A shorter module path only counts if it really provides the next name;
            # otherwise "merlin.nope.missing" would resolve to merlin/__init__.py.
            if _defines(source, remainder[0], candidate):
                return candidate, remainder
            if _hops > 0:
                target = _reexport_target(source, remainder[0], candidate)
                if target:
                    followed = await find_module_path(
                        library, ref, ".".join([target, *remainder]), _hops - 1
                    )
                    if followed is not None:
                        return followed
    return None


def _node_span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", 1)
    for decorator in getattr(node, "decorator_list", None) or []:
        start = min(start, getattr(decorator, "lineno", start))
    end = getattr(node, "end_lineno", start) or start
    return start, end


def _parse(source: str, path: str) -> ast.Module:
    """Parse module source, naming the file in any failure."""
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise ParseError(f"could not parse {path}: {exc}") from exc


def _find_node(tree: ast.Module, path: list[str]) -> ast.AST | None:
    """Walk a dotted path of names through nested class and function definitions."""
    scope: ast.AST = tree
    node: ast.AST | None = None
    for name in path:
        body = getattr(scope, "body", None)
        if body is None:
            return None
        node = None
        for item in body:
            if isinstance(item, _Definition):
                if item.name == name:
                    node = item
                    break
            elif isinstance(item, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in item.targets
            ):
                node = item
                break
        if node is None:
            return None
        scope = node
    return node


def _defines(source: str, name: str, path: str) -> bool:
    """Whether module ``source`` defines ``name`` at its top level."""
    try:
        tree = _parse(source, path)
    except ParseError as exc:
        logger.warning("%s while looking for %r", exc, name)
        return False
    return _find_node(tree, [name]) is not None


def _reexport_target(source: str, name: str, path: str) -> str | None:
    """The absolute module a package re-exports ``name`` from, if it does.

    Public APIs are commonly surfaced from the package root (``merlin.QuantumLayer``)
    while living in a submodule, so an import statement is a legitimate answer to
    "where is this defined".
    """
    try:
        tree = _parse(source, path)
    except ParseError:
        return None

    # The package a relative import resolves against is the directory holding the file,
    # for both "pkg/__init__.py" and "pkg/module.py".
    package_parts = path.removesuffix(".py").split("/")[:-1]

    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if not any(alias.asname == name or alias.name == name for alias in node.names):
            continue
        if node.level:
            base = package_parts[: len(package_parts) - (node.level - 1)]
            return ".".join([*base, *(node.module.split(".") if node.module else [])])
        if node.module:
            return node.module
    return None


def slice_symbol(source: str, path: list[str], filename: str = "<module>") -> str | None:
    """Return only the source of the named class or function inside ``source``.

    Returns ``None`` when the name is genuinely absent.

    Raises:
        ParseError: when the module could not be parsed, so absence is unknown.
    """
    if not path:
        return source
    tree = _parse(source, filename)
    node = _find_node(tree, path)
    if node is None:
        return None
    start, end = _node_span(node)
    return "\n".join(source.splitlines()[start - 1 : end])


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"


def describe_symbol(
    source: str, path: list[str], filename: str = "<module>"
) -> SymbolDetails | None:
    """Extract signature, docstring and public members of one symbol from module source.

    Returns ``None`` when the name is genuinely absent.

    Raises:
        ParseError: when the module could not be parsed, so absence is unknown.
    """
    tree = _parse(source, filename)

    if not path:
        return SymbolDetails(
            kind="module",
            signature="",
            docstring=ast.get_docstring(tree) or "",
            members=[
                item.name
                for item in tree.body
                if isinstance(item, _Definition) and not item.name.startswith("_")
            ],
            bases=[],
            init_docstring="",
        )

    node = _find_node(tree, path)
    if node is None:
        return None

    if isinstance(node, ast.ClassDef):
        methods = [
            _signature(item)
            for item in node.body
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            and (not item.name.startswith("_") or item.name == "__init__")
        ]
        init = next(
            (
                item
                for item in node.body
                if isinstance(item, ast.FunctionDef) and item.name == "__init__"
            ),
            None,
        )
        bases = [ast.unparse(base) for base in node.bases]
        return SymbolDetails(
            kind="class",
            signature=f"class {node.name}({', '.join(bases)})",
            docstring=ast.get_docstring(node) or "",
            members=methods,
            bases=bases,
            init_docstring=(ast.get_docstring(init) or "") if init else "",
        )

    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return SymbolDetails(
            kind="function",
            signature=_signature(node),
            docstring=ast.get_docstring(node) or "",
            members=[],
            bases=[],
            init_docstring="",
        )

    return SymbolDetails(
        kind="data",
        signature=ast.unparse(node),
        docstring="",
        members=[],
        bases=[],
        init_docstring="",
    )


async def get_releases(library: LibrarySource, limit: int = 3) -> list[Release]:
    """The most recent GitHub releases of the upstream project."""
    per_page = max(1, min(limit, 30))
    data: Any = await fetch_json(
        library.api_url(f"releases?per_page={per_page}"), ttl=get_settings().index_ttl
    )
    if not isinstance(data, list):
        raise UpstreamError(f"could not list releases for {library.repo}")
    return [
        Release(
            tag=str(entry.get("tag_name") or ""),
            name=str(entry.get("name") or entry.get("tag_name") or ""),
            published_at=str(entry.get("published_at") or ""),
            url=str(entry.get("html_url") or ""),
            body=str(entry.get("body") or ""),
        )
        for entry in data[:limit]
        if isinstance(entry, dict)
    ]
