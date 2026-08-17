"""Parsing and searching the Sphinx symbol inventory."""

from __future__ import annotations

import zlib

import pytest
from conftest import make_inventory

from merlin_mcp.errors import UpstreamError
from merlin_mcp.models import Symbol
from merlin_mcp.sources.inventory import find_symbol, parse_inventory, search_symbols

ENTRIES = [
    ("merlin.algorithms.layer", "py:module", "api/merlin.algorithms.layer.html#module-$", "-"),
    (
        "merlin.algorithms.layer.QuantumLayer",
        "py:class",
        "api/merlin.algorithms.layer.html#$",
        "-",
    ),
    (
        "merlin.algorithms.layer.QuantumLayer.forward",
        "py:method",
        "api/merlin.algorithms.layer.html#$",
        "-",
    ),
    ("merlin.core.circuit.CircuitConverter", "py:class", "api/merlin.core.circuit.html#$", "-"),
    ("quantumlayer", "std:label", "notebooks/binary_classification.html#QuantumLayer", "Layers"),
]


def parsed() -> list[Symbol]:
    return parse_inventory(make_inventory(ENTRIES))


def test_expands_the_dollar_placeholder() -> None:
    symbols = {symbol.name: symbol for symbol in parsed()}
    assert symbols["merlin.algorithms.layer.QuantumLayer"].uri.endswith(
        "#merlin.algorithms.layer.QuantumLayer"
    )


def test_dash_display_name_means_same_as_name() -> None:
    symbols = {symbol.name: symbol for symbol in parsed()}
    assert (
        symbols["merlin.core.circuit.CircuitConverter"].display_name
        == "merlin.core.circuit.CircuitConverter"
    )
    assert symbols["quantumlayer"].display_name == "Layers"


def test_kind_strips_the_domain_prefix() -> None:
    symbols = {symbol.name: symbol for symbol in parsed()}
    assert symbols["merlin.algorithms.layer.QuantumLayer"].kind == "class"
    assert symbols["quantumlayer"].is_python is False


def test_rejects_an_unknown_inventory_format() -> None:
    with pytest.raises(UpstreamError):
        parse_inventory(b"# Sphinx inventory version 1\n")


def test_rejects_a_truncated_header() -> None:
    with pytest.raises(UpstreamError, match="truncated"):
        parse_inventory(b"# Sphinx inventory version 2\n# Project: x\n")


def test_rejects_a_corrupt_compressed_body() -> None:
    header = b"# Sphinx inventory version 2\n# Project: x\n# Version: 1\n# zlib.\n"
    with pytest.raises(UpstreamError, match="decompress"):
        parse_inventory(header + b"not-really-zlib")


def test_refuses_a_decompression_bomb() -> None:
    # A small download that inflates without bound would otherwise be read entirely
    # into memory; the cap is what stops that.
    header = b"# Sphinx inventory version 2\n# Project: x\n# Version: 1\n# zlib.\n"
    payload = zlib.compress(b"a" * 100_000)
    with pytest.raises(UpstreamError, match="expanded beyond"):
        parse_inventory(header + payload, max_bytes=1024)


def test_search_ranks_an_exact_tail_match_first() -> None:
    results = search_symbols(parsed(), "CircuitConverter")
    assert results[0].name == "merlin.core.circuit.CircuitConverter"


def test_search_filters_by_kind() -> None:
    results = search_symbols(parsed(), "layer", kind="module")
    assert [symbol.name for symbol in results] == ["merlin.algorithms.layer"]


def test_search_returns_nothing_for_an_empty_query() -> None:
    assert search_symbols(parsed(), "   ") == []


def test_find_symbol_prefers_the_class_over_a_section_label() -> None:
    # A notebook heading is also indexed as "quantumlayer"; the class must win.
    found = find_symbol(parsed(), "QuantumLayer")
    assert found is not None
    assert found.name == "merlin.algorithms.layer.QuantumLayer"
    assert found.kind == "class"


def test_find_symbol_accepts_a_fully_qualified_name() -> None:
    found = find_symbol(parsed(), "merlin.algorithms.layer.QuantumLayer.forward")
    assert found is not None
    assert found.kind == "method"


def test_find_symbol_returns_none_for_nonsense() -> None:
    assert find_symbol(parsed(), "") is None
