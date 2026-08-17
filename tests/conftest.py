"""Shared fixtures.

Every offline test builds its upstream payloads in memory here, so the suite has no
recorded fixture files to keep in sync and runs with the network unplugged.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from merlin_mcp.cache import cache
from merlin_mcp.config import get_settings

MERLIN_BASE = "https://merlinquantum.ai"
VERSION = "0.4"
VERSION_BASE = f"{MERLIN_BASE}/{VERSION}"

LANDING_PAGE = (
    '<!doctype html>\n<meta charset="utf-8">\n'
    '<meta http-equiv="refresh" content="0; url=0.4/index.html">\n'
    '<link rel="canonical" href="0.4/index.html">\n'
)

PERCEVAL_LANDING_PAGE = (
    "<!DOCTYPE html>\n<html><head>\n"
    '<link rel="canonical" href="./v1.2/index.html">\n'
    '</head><body><script>const latest = "v1.2";</script></body></html>'
)


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    """Keep cached responses and cached settings from leaking between tests."""
    cache.clear()
    get_settings.cache_clear()
    yield
    cache.clear()
    get_settings.cache_clear()


def make_inventory(entries: Sequence[tuple[str, str, str, str]]) -> bytes:
    """Build an ``objects.inv`` body from ``(name, role, uri, display)`` tuples."""
    header = (
        b"# Sphinx inventory version 2\n"
        b"# Project: merlinquantum\n"
        b"# Version: 0.4\n"
        b"# The remainder of this file is compressed using zlib.\n"
    )
    lines = "\n".join(f"{name} {role} 1 {uri} {display}" for name, role, uri, display in entries)
    return header + zlib.compress(lines.encode("utf-8"))


def make_search_index(
    docnames: Sequence[str],
    titles: Sequence[str],
    terms: dict[str, Any],
    titleterms: dict[str, Any] | None = None,
    alltitles: dict[str, Any] | None = None,
) -> str:
    """Build the body of a ``searchindex.js`` file."""
    payload = {
        "docnames": list(docnames),
        "filenames": [f"{name}.rst" for name in docnames],
        "titles": list(titles),
        "terms": terms,
        "titleterms": titleterms or {},
        "alltitles": alltitles or {},
        "objects": {},
        "objtypes": {},
        "objnames": {},
        "indexentries": {},
        "envversion": {},
    }
    return f"Search.setIndex({json.dumps(payload)})"


def make_notebook(cells: Sequence[dict[str, Any]], language: str = "python") -> dict[str, Any]:
    """Build notebook JSON with the given cells."""
    return {
        "cells": list(cells),
        "metadata": {"kernelspec": {"language": language}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def make_tree(paths: Sequence[str], truncated: bool = False) -> dict[str, Any]:
    """Build a GitHub git-tree response listing ``paths`` as blobs."""
    return {
        "sha": "deadbeef",
        "truncated": truncated,
        "tree": [{"path": path, "type": "blob", "mode": "100644"} for path in paths],
    }


SAMPLE_MODULE = '''
"""Module docstring."""

import torch


class QuantumLayer(MerlinModule):
    """Quantum neural network layer."""

    def __init__(self, input_size: int, output_size: int = 2) -> None:
        """Build the layer."""
        self.input_size = input_size

    def forward(self, x: "torch.Tensor") -> "torch.Tensor":
        """Run the layer."""
        return x

    def _private(self) -> None:
        pass


def simple(input_size: int) -> QuantumLayer:
    """Factory helper."""
    return QuantumLayer(input_size)


CONSTANT = 3
'''
