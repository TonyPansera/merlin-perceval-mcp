"""Read a Sphinx ``objects.inv`` inventory and search it by symbol name.

The inventory is the authoritative list of everything the project documents: every
class, function, method, module and cross-reference label, each with the exact URL
of its rendered documentation. It is one small zlib-compressed download.
"""

from __future__ import annotations

import re
import zlib

from ..config import LibrarySource, get_settings
from ..errors import UpstreamError
from ..http import fetch_bytes
from ..models import Symbol

# Record layout of inventory format v2, as written by Sphinx.
_RECORD = re.compile(r"(?x)(.+?)\s+(\S+)\s+(-?\d+)\s+?(\S*)\s+(.*)")

_HEADER_LINES = 4

# Relative weight of how a query matched a symbol name. Named for the same reason
# the search-index weights are: ranking behaviour should be readable, not decoded.
_EXACT_NAME = 100.0
_EXACT_TAIL = 90.0
_TAIL_PREFIX = 70.0
_NAME_PREFIX = 60.0
_TAIL_CONTAINS = 45.0
_NAME_CONTAINS = 30.0
_PYTHON_BONUS = 5.0
_TOP_LEVEL_BONUS = 3.0
_LENGTH_PENALTY_CAP = 2.0


def _decompress(payload: bytes, cap: int) -> str:
    """Inflate the inventory body, refusing to expand past ``cap`` bytes."""
    decompressor = zlib.decompressobj()
    try:
        body = decompressor.decompress(payload, cap + 1)
    except zlib.error as exc:
        raise UpstreamError(f"could not decompress objects.inv: {exc}") from exc
    if len(body) > cap or decompressor.unconsumed_tail:
        raise UpstreamError(f"objects.inv expanded beyond the {cap} byte limit")
    return body.decode("utf-8", errors="replace")


def parse_inventory(raw: bytes, max_bytes: int | None = None) -> list[Symbol]:
    """Decode the bytes of an ``objects.inv`` file into :class:`Symbol` records."""
    if not raw.startswith(b"# Sphinx inventory version 2"):
        raise UpstreamError("unsupported objects.inv format (expected inventory version 2)")

    offset = 0
    for _ in range(_HEADER_LINES):
        newline = raw.find(b"\n", offset)
        if newline == -1:
            raise UpstreamError("truncated objects.inv header")
        offset = newline + 1

    cap = get_settings().max_response_bytes if max_bytes is None else max_bytes
    body = _decompress(raw[offset:], cap)

    symbols: list[Symbol] = []
    for line in body.splitlines():
        match = _RECORD.match(line.rstrip())
        if not match:
            continue
        name, role, _priority, uri, display = match.groups()
        if uri.endswith("$"):
            uri = uri[:-1] + name
        symbols.append(
            Symbol(
                name=name,
                role=role,
                uri=uri,
                display_name=name if display.strip() == "-" else display.strip(),
            )
        )
    return symbols


async def load_inventory(library: LibrarySource, version: str) -> list[Symbol]:
    """Fetch and parse the inventory of one documentation version."""
    url = f"{library.version_base(version)}/objects.inv"
    return parse_inventory(await fetch_bytes(url, ttl=get_settings().index_ttl))


def _score(symbol: Symbol, query: str) -> float:
    """Rank one symbol against a lowercase query string."""
    name = symbol.name.lower()
    tail = name.rsplit(".", 1)[-1]
    if name == query:
        score = _EXACT_NAME
    elif tail == query:
        score = _EXACT_TAIL
    elif tail.startswith(query):
        score = _TAIL_PREFIX
    elif name.startswith(query):
        score = _NAME_PREFIX
    elif query in tail:
        score = _TAIL_CONTAINS
    elif query in name:
        score = _NAME_CONTAINS
    else:
        return 0.0

    if symbol.is_python:
        score += _PYTHON_BONUS
    if symbol.kind in {"class", "function", "module"}:
        score += _TOP_LEVEL_BONUS
    # Prefer the shortest qualified name among otherwise equal matches.
    return score - min(len(name) / 100.0, _LENGTH_PENALTY_CAP)


def search_symbols(
    symbols: list[Symbol],
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[Symbol]:
    """Return the best matches for ``query``, optionally filtered by symbol kind."""
    needle = query.strip().lower()
    if not needle:
        return []
    wanted = kind.strip().lower() if kind else None

    scored: list[tuple[float, Symbol]] = []
    for symbol in symbols:
        if wanted and symbol.kind != wanted:
            continue
        score = _score(symbol, needle)
        if score > 0:
            scored.append((score, symbol))

    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [symbol for _, symbol in scored[:limit]]


def find_symbol(symbols: list[Symbol], name: str) -> Symbol | None:
    """Resolve an exact dotted name, or an unambiguous trailing segment such as ``QuantumLayer``."""
    needle = name.strip()
    if not needle:
        return None
    lowered = needle.lower()

    # Python-domain entries win over cross-reference labels, which frequently share a
    # name with the class they document (a notebook section titled "QuantumLayer" is
    # not the QuantumLayer class).
    python_symbols = [symbol for symbol in symbols if symbol.is_python]
    priority = {"class": 0, "function": 1, "module": 2, "method": 3, "property": 4}

    for group in (python_symbols, symbols):
        for symbol in group:
            if symbol.name == needle:
                return symbol
        for symbol in group:
            if symbol.name.lower() == lowered:
                return symbol
        tail_matches = [
            symbol for symbol in group if symbol.name.rsplit(".", 1)[-1].lower() == lowered
        ]
        if tail_matches:
            tail_matches.sort(key=lambda s: (priority.get(s.kind, 9), len(s.name)))
            return tail_matches[0]

    candidates = search_symbols(symbols, needle, limit=1)
    return candidates[0] if candidates else None
