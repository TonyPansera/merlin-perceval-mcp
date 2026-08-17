"""Live checks against the real upstream services.

Deselected by default (`-m "not network"`, set in pyproject.toml) and run on a
schedule by the upstream-canary workflow. Because the server owns no vendored copy of
the documentation, upstream changing its published layout is the one thing that can
break it — these tests are how that gets noticed.

Every assertion here has to fail when discovery silently degrades. A check that also
passes for the compiled-in fallback, or for an empty field, is worse than no check:
it makes a broken canary look healthy.
"""

from __future__ import annotations

import pytest

from merlin_mcp import server
from merlin_mcp.config import MERLIN, PERCEVAL, LibrarySource
from merlin_mcp.sources import inventory, searchindex
from merlin_mcp.sources.version import resolve_version

pytestmark = pytest.mark.network


@pytest.mark.parametrize("library", [MERLIN, PERCEVAL], ids=lambda source: source.key)
async def test_version_is_discovered_rather_than_assumed(library: LibrarySource) -> None:
    resolved = await resolve_version(library)
    # The fallback would satisfy any format check, so assert on the origin instead.
    assert resolved.origin in {"landing", "pypi"}, f"discovery degraded to {resolved.origin}"
    assert not resolved.is_fallback


@pytest.mark.parametrize("library", [MERLIN, PERCEVAL], ids=lambda source: source.key)
async def test_inventory_is_published_and_substantial(library: LibrarySource) -> None:
    resolved = await resolve_version(library)
    symbols = await inventory.load_inventory(library, resolved.version)
    assert len(symbols) > 1000
    assert any(symbol.kind == "class" for symbol in symbols)
    assert any(symbol.name.startswith(f"{library.package_dir}.") for symbol in symbols)


@pytest.mark.parametrize("library", [MERLIN, PERCEVAL], ids=lambda source: source.key)
async def test_search_index_is_published(library: LibrarySource) -> None:
    resolved = await resolve_version(library)
    index = await searchindex.load_index(library, resolved.version)
    assert len(index["docnames"]) > 20
    assert len(index["terms"]) > 500
    assert index["titles"]


async def test_page_sources_are_published() -> None:
    result = await server.get_doc_page("user_guide/layer", limit=4000)
    assert "QuantumLayer" in result
    assert "_sources/user_guide/layer.rst.txt" in result
    # The published source keeps reStructuredText markup; rendered HTML would not.
    assert ":class:" in result or "::" in result


async def test_search_finds_the_quantum_layer_guide() -> None:
    result = await server.search_docs("QuantumLayer", limit=3)
    assert "user_guide/layer" in result


async def test_api_doc_matches_the_current_release() -> None:
    result = await server.get_api_doc("QuantumLayer")
    assert "class QuantumLayer" in result
    assert "input_size" in result
    assert "raw.githubusercontent.com" in result


async def test_examples_are_listed_and_readable() -> None:
    listing = await server.list_examples(topic="iris")
    assert "notebooks/" in listing

    example = await server.get_example("notebooks/FirstQuantumLayers", limit=6000)
    assert "```python" in example
    assert "import" in example
    assert "merlin" in example.lower()


async def test_release_notes_carry_real_content() -> None:
    result = await server.get_release_notes(limit=1)
    # A schema rename upstream would empty these fields while leaving the call
    # nominally successful, so check the fields themselves rather than the length.
    assert "github.com/merlinquantum/merlin/releases/tag/" in result
    assert "(no notes)" not in result
    assert any(char.isdigit() for char in result.splitlines()[2])


async def test_perceval_symbols_resolve_to_real_names() -> None:
    result = await server.search_api("Circuit", library="perceval", kind="class", limit=5)
    # Asserting on the docs domain would pass for any match at all; assert the
    # symbol we asked for was actually found.
    assert "perceval.components" in result or "perceval.utils" in result
    assert "Circuit" in result


async def test_a_missing_page_is_reported_as_missing() -> None:
    result = await server.get_doc_page("no/such/page/anywhere")
    assert result.startswith("Error:")
    assert "no page" in result
