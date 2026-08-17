"""The server must never persist anything.

Storing nothing locally is a design requirement, not an implementation detail: it is
what makes the server free of state to maintain, migrate or invalidate. This test
makes any attempt to open a file for writing fail loudly during a full tool sweep.
"""

from __future__ import annotations

import builtins
import pathlib
from typing import Any

import pytest
from test_tools import upstream

from merlin_mcp import server
from merlin_mcp.cache import cache

_WRITE_MODES = set("wxa+")


@pytest.fixture
def no_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every file write raise for the duration of a test."""
    real_open = builtins.open

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if _WRITE_MODES & set(mode):
            raise AssertionError(f"attempted to write to {file!r} with mode {mode!r}")
        return real_open(file, mode, *args, **kwargs)

    def refuse(self: pathlib.Path, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"attempted to write to {self}")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(pathlib.Path, "write_text", refuse)
    monkeypatch.setattr(pathlib.Path, "write_bytes", refuse)


@pytest.mark.usefixtures("no_writes")
async def test_full_tool_sweep_writes_nothing() -> None:
    with upstream():
        assert "QuantumLayer" in await server.search_docs("QuantumLayer")
        assert "Body." in await server.get_doc_page("user_guide/layer")
        assert "QuantumLayer" in await server.search_api("QuantumLayer")
        assert "class QuantumLayer" in await server.get_api_doc("QuantumLayer")
        assert "class QuantumLayer" in await server.get_source("QuantumLayer")
        assert "Kernel Methods" in await server.list_examples()
        assert "import merlin" in await server.get_example("Kernels")
        assert "Grimoire" in await server.get_release_notes(limit=1)


async def test_cache_lives_only_in_memory() -> None:
    with upstream():
        await server.search_docs("QuantumLayer")
        assert len(cache) > 0
        cache.clear()
        assert len(cache) == 0
