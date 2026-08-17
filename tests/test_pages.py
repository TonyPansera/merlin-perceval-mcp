"""Documentation page retrieval and page-name normalisation."""

from __future__ import annotations

import httpx
import pytest
import respx
from conftest import VERSION, VERSION_BASE

from merlin_mcp.config import MERLIN, PERCEVAL
from merlin_mcp.errors import NotFoundError
from merlin_mcp.sources.pages import get_page, normalize_docname

RST = ".. _quantum_layer:\n\nQuantumLayer Essentials\n=======================\n\nBody text.\n"

HTML = """
<html><body>
<div class="wy-nav-side">sidebar</div>
<div role="main" class="document">
  <h1>QuantumLayer Essentials</h1>
  <p>The layer wraps a circuit.</p>
  <pre>layer = ML.QuantumLayer.simple(3, 2)</pre>
  <script>ignore()</script>
</div>
</body></html>
"""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("user_guide/layer", "user_guide/layer"),
        ("user_guide/layer.html", "user_guide/layer"),
        ("/user_guide/layer/", "user_guide/layer"),
        ("https://merlinquantum.ai/0.4/user_guide/layer.html#overview", "user_guide/layer"),
        ("0.4/user_guide/layer", "user_guide/layer"),
        ("", "index"),
    ],
)
def test_normalize_docname(raw: str, expected: str) -> None:
    assert normalize_docname(raw, MERLIN) == expected


def test_normalize_docname_strips_the_perceval_docs_prefix() -> None:
    url = "https://perceval.quandela.net/docs/v1.2/reference/circuit.html"
    assert normalize_docname(url, PERCEVAL) == "reference/circuit"


async def test_get_page_returns_the_published_source() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{VERSION_BASE}/_sources/user_guide/layer.rst.txt").mock(
            return_value=httpx.Response(200, text=RST)
        )
        text, url, docname = await get_page(MERLIN, VERSION, "user_guide/layer")

    assert "QuantumLayer Essentials" in text
    assert url.endswith("layer.rst.txt")
    assert docname == "user_guide/layer"


async def test_get_page_falls_back_to_html_extraction() -> None:
    with respx.mock(assert_all_called=False) as mock:
        for suffix in ("rst", "md", "txt", "ipynb"):
            mock.get(f"{VERSION_BASE}/_sources/user_guide/layer.{suffix}.txt").mock(
                return_value=httpx.Response(404)
            )
        mock.get(f"{VERSION_BASE}/user_guide/layer.html").mock(
            return_value=httpx.Response(200, text=HTML)
        )
        text, url, _ = await get_page(MERLIN, VERSION, "user_guide/layer")

    assert "The layer wraps a circuit." in text
    assert "ML.QuantumLayer.simple(3, 2)" in text
    assert "sidebar" not in text
    assert "ignore()" not in text
    assert url.endswith(".html")


async def test_get_page_raises_when_the_page_does_not_exist() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="merlinquantum.ai").mock(return_value=httpx.Response(404))
        with pytest.raises(NotFoundError):
            await get_page(MERLIN, VERSION, "nope/missing")
