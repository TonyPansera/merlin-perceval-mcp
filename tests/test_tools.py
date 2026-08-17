"""End-to-end tool behaviour with every upstream request mocked."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import respx
from conftest import (
    LANDING_PAGE,
    SAMPLE_MODULE,
    VERSION_BASE,
    make_inventory,
    make_notebook,
    make_search_index,
    make_tree,
)

from merlin_mcp import server

REPO_API = "https://api.github.com/repos/merlinquantum/merlin"
RAW = "https://raw.githubusercontent.com/merlinquantum/merlin/main"

PATHS = [
    "merlin/__init__.py",
    "merlin/algorithms/layer.py",
    "docs/source/notebooks/Kernels.ipynb",
    "docs/source/_data/galleries/examples/getting_started.json",
]

INVENTORY = make_inventory(
    [
        (
            "merlin.algorithms.layer.QuantumLayer",
            "py:class",
            "api_reference/api/merlin.algorithms.layer.html#$",
            "-",
        ),
        (
            "merlin.algorithms.layer",
            "py:module",
            "api_reference/api/merlin.algorithms.layer.html#module-$",
            "-",
        ),
    ]
)

SEARCH_INDEX = make_search_index(
    docnames=["user_guide/layer"],
    titles=["QuantumLayer Essentials"],
    terms={"quantumlay": [0], "essenti": [0]},
    titleterms={"quantumlay": 0},
    alltitles={"Overview": [[0, "overview"]]},
)

GALLERY = [
    {
        "title": "Kernel Methods",
        "summary": "Build photonic fidelity kernels.",
        "doc": "notebooks/Kernels.ipynb",
        "tags": ["Tutorial", "Kernels"],
    }
]

NOTEBOOK = make_notebook(
    [
        {"cell_type": "markdown", "source": "# Kernels"},
        {"cell_type": "code", "source": "import merlin as ML", "outputs": []},
    ]
)

RELEASES = [
    {
        "tag_name": "0.4.0",
        "name": "Merlin v0.4: Grimoire",
        "published_at": "2026-06-18T16:20:09Z",
        "html_url": f"{REPO_API}/releases/tag/0.4.0",
        "body": "Breaking change: renamed things.",
    }
]


@contextmanager
def upstream() -> Iterator[respx.MockRouter]:
    """Serve a complete, self-consistent snapshot of both upstream services."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://merlinquantum.ai/").mock(
            return_value=httpx.Response(200, text=LANDING_PAGE)
        )
        mock.get(f"{VERSION_BASE}/searchindex.js").mock(
            return_value=httpx.Response(200, text=SEARCH_INDEX)
        )
        mock.get(f"{VERSION_BASE}/objects.inv").mock(
            return_value=httpx.Response(200, content=INVENTORY)
        )
        mock.get(f"{VERSION_BASE}/_sources/user_guide/layer.rst.txt").mock(
            return_value=httpx.Response(200, text="QuantumLayer Essentials\n=======\n\nBody.")
        )
        mock.get(f"{VERSION_BASE}/_sources/notebooks/Kernels.ipynb.txt").mock(
            return_value=httpx.Response(200, text=json.dumps(NOTEBOOK))
        )
        mock.get(REPO_API).mock(return_value=httpx.Response(200, json={"default_branch": "main"}))
        mock.get(f"{REPO_API}/git/trees/main?recursive=1").mock(
            return_value=httpx.Response(200, json=make_tree(PATHS))
        )
        mock.get(f"{REPO_API}/releases?per_page=1").mock(
            return_value=httpx.Response(200, json=RELEASES)
        )
        mock.get(f"{RAW}/merlin/algorithms/layer.py").mock(
            return_value=httpx.Response(200, text=SAMPLE_MODULE)
        )
        mock.get(f"{RAW}/docs/source/_data/galleries/examples/getting_started.json").mock(
            return_value=httpx.Response(200, json=GALLERY)
        )
        mock.route(host="merlinquantum.ai").mock(return_value=httpx.Response(404))
        yield mock


async def test_search_docs_reports_pages_with_urls() -> None:
    with upstream():
        result = await server.search_docs("QuantumLayer")

    assert "QuantumLayer Essentials" in result
    assert "user_guide/layer" in result
    assert "https://merlinquantum.ai/0.4/user_guide/layer.html" in result


async def test_search_docs_points_at_matching_sections() -> None:
    with upstream():
        result = await server.search_docs("quantumlayer overview")

    assert "sections: Overview" in result


async def test_search_docs_explains_an_empty_result() -> None:
    with upstream():
        result = await server.search_docs("zzzzqqqq")

    assert "no results" in result
    assert "search_api" in result


async def test_get_doc_page_returns_the_source_and_paginates() -> None:
    with upstream():
        result = await server.get_doc_page("user_guide/layer", limit=10)

    assert "layer.rst.txt" in result
    assert "truncated" in result


async def test_search_api_lists_symbols() -> None:
    with upstream():
        result = await server.search_api("QuantumLayer", kind="class")

    assert "merlin.algorithms.layer.QuantumLayer" in result
    assert "(class)" in result


async def test_get_api_doc_returns_a_real_signature() -> None:
    with upstream():
        result = await server.get_api_doc("QuantumLayer")

    assert "class QuantumLayer(MerlinModule)" in result
    assert "Quantum neural network layer." in result
    assert "def forward" in result
    assert "merlin/algorithms/layer.py" in result


async def test_get_source_narrows_a_bare_name_to_its_class() -> None:
    with upstream():
        result = await server.get_source("QuantumLayer")

    assert "```python\nclass QuantumLayer" in result
    assert "def simple" not in result


async def test_list_examples_uses_the_curated_gallery() -> None:
    with upstream():
        result = await server.list_examples(topic="kernel")

    assert "Kernel Methods" in result
    assert "Build photonic fidelity kernels." in result
    assert "notebooks/Kernels" in result


async def test_get_example_renders_code_cells() -> None:
    with upstream():
        result = await server.get_example("Kernels")

    assert "```python\nimport merlin as ML" in result


async def test_get_release_notes_includes_the_body() -> None:
    with upstream():
        result = await server.get_release_notes(limit=1)

    assert "Merlin v0.4: Grimoire" in result
    assert "Breaking change" in result


async def test_docs_index_resource_lists_pages() -> None:
    with upstream():
        result = await server.docs_index("merlin")

    assert "user_guide/layer" in result


async def test_unknown_library_is_reported_not_raised() -> None:
    result = await server.search_docs("anything", library="numpy")
    assert result.startswith("Error:")
    assert "unknown library" in result


def test_prompt_names_the_tools_to_use() -> None:
    text = server.merlin_quickstart("classify Iris")
    assert "search_docs" in text
    assert "get_api_doc" in text
    assert "pip install merlinquantum" in text
