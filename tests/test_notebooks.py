"""Notebook rendering and gallery parsing."""

from __future__ import annotations

import httpx
import pytest
import respx
from conftest import make_notebook

from merlin_mcp.config import MERLIN, PERCEVAL
from merlin_mcp.errors import UpstreamError
from merlin_mcp.sources.notebooks import fetch_notebook, load_gallery, render_notebook

CELLS = [
    {"cell_type": "markdown", "source": ["# Kernels\n", "\n", "Intro text."]},
    {
        "cell_type": "code",
        "source": "import merlin as ML\nlayer = ML.QuantumLayer.simple(3, 2)",
        "outputs": [{"output_type": "stream", "text": ["tensor([0.1])"]}],
    },
    {"cell_type": "code", "source": "", "outputs": []},
    {"cell_type": "raw", "source": "ignored"},
]


def test_render_keeps_prose_and_fences_code() -> None:
    rendered = render_notebook(make_notebook(CELLS))
    assert "# Kernels" in rendered
    assert "```python\nimport merlin as ML" in rendered
    assert "ignored" not in rendered


def test_render_omits_outputs_by_default() -> None:
    assert "tensor([0.1])" not in render_notebook(make_notebook(CELLS))


def test_render_can_include_outputs() -> None:
    assert "tensor([0.1])" in render_notebook(make_notebook(CELLS), include_outputs=True)


def test_render_rejects_a_non_notebook() -> None:
    with pytest.raises(UpstreamError):
        render_notebook({"not": "a notebook"})


def test_render_includes_execute_result_output() -> None:
    cells = [
        {
            "cell_type": "code",
            "source": "layer(x)",
            "outputs": [
                {"output_type": "execute_result", "data": {"text/plain": ["tensor([0.9])"]}}
            ],
        }
    ]
    assert "tensor([0.9])" in render_notebook(make_notebook(cells), include_outputs=True)


def test_render_notes_an_omitted_image() -> None:
    cells = [
        {
            "cell_type": "code",
            "source": "plot()",
            "outputs": [{"output_type": "display_data", "data": {"image/png": "base64..."}}],
        }
    ]
    assert "image output omitted" in render_notebook(make_notebook(cells), include_outputs=True)


def test_render_truncates_a_very_long_output() -> None:
    cells = [
        {
            "cell_type": "code",
            "source": "noisy()",
            "outputs": [{"output_type": "stream", "text": "x" * 5000}],
        }
    ]
    assert "output truncated" in render_notebook(make_notebook(cells), include_outputs=True)


async def test_fetch_notebook_rejects_invalid_json() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/nb.ipynb").mock(
            return_value=httpx.Response(200, text="{not json")
        )
        with pytest.raises(UpstreamError, match="valid notebook JSON"):
            await fetch_notebook("https://example.test/nb.ipynb")


async def test_fetch_notebook_rejects_a_non_object() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/nb.ipynb").mock(return_value=httpx.Response(200, json=[1]))
        with pytest.raises(UpstreamError, match="not a notebook object"):
            await fetch_notebook("https://example.test/nb.ipynb")


async def test_fetch_notebook_reports_a_missing_file() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://example.test/nb.ipynb").mock(return_value=httpx.Response(404))
        with pytest.raises(UpstreamError):
            await fetch_notebook("https://example.test/nb.ipynb")


async def test_load_gallery_reads_titles_summaries_and_tags() -> None:
    entries = [
        {
            "title": "Kernel Methods",
            "summary": "Build photonic fidelity kernels.",
            "doc": "notebooks/Kernels.ipynb",
            "tags": ["Tutorial", "Kernels"],
        },
        {"title": "Not a notebook", "doc": "user_guide/layer.rst"},
    ]
    path = "docs/source/_data/galleries/examples/getting_started.json"
    with respx.mock(assert_all_called=False) as mock:
        mock.get(MERLIN.raw_url("main", path)).mock(return_value=httpx.Response(200, json=entries))
        examples = await load_gallery(MERLIN, "main", [path])

    assert len(examples) == 1
    example = examples[0]
    assert example.name == "notebooks/Kernels"
    assert example.title == "Kernel Methods"
    assert example.tags == ("Tutorial", "Kernels")
    assert example.path == "docs/source/notebooks/Kernels.ipynb"


async def test_load_gallery_is_empty_for_a_project_without_one() -> None:
    assert await load_gallery(PERCEVAL, "main", ["anything.json"]) == []
