"""Repository reads and ast-based symbol extraction."""

from __future__ import annotations

import httpx
import pytest
import respx
from conftest import SAMPLE_MODULE, make_tree

from merlin_mcp.config import MERLIN
from merlin_mcp.errors import InvalidRequestError, ParseError, UpstreamError
from merlin_mcp.sources.repo import (
    describe_symbol,
    find_module_path,
    get_releases,
    list_tree,
    resolve_ref,
    slice_symbol,
)

TREE_URL = "https://api.github.com/repos/merlinquantum/merlin/git/trees/main?recursive=1"
RAW = "https://raw.githubusercontent.com/merlinquantum/merlin/main"
PATHS = ["merlin/__init__.py", "merlin/algorithms/layer.py", "docs/source/notebooks/Kernels.ipynb"]
PACKAGE_INIT = "from .algorithms.layer import QuantumLayer\n\n__all__ = ['QuantumLayer']\n"


def mock_repo(mock: respx.MockRouter) -> None:
    """Serve the tree plus the two module files it lists."""
    mock.get(TREE_URL).mock(return_value=httpx.Response(200, json=make_tree(PATHS)))
    mock.get(f"{RAW}/merlin/__init__.py").mock(return_value=httpx.Response(200, text=PACKAGE_INIT))
    mock.get(f"{RAW}/merlin/algorithms/layer.py").mock(
        return_value=httpx.Response(200, text=SAMPLE_MODULE)
    )


async def test_resolve_ref_uses_the_repository_default_branch() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.github.com/repos/merlinquantum/merlin").mock(
            return_value=httpx.Response(200, json={"default_branch": "trunk"})
        )
        assert await resolve_ref(MERLIN) == "trunk"


async def test_resolve_ref_prefers_an_explicit_ref() -> None:
    assert await resolve_ref(MERLIN, "v0.3") == "v0.3"


async def test_find_module_path_splits_module_from_symbol() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_repo(mock)
        located = await find_module_path(MERLIN, "main", "merlin.algorithms.layer.QuantumLayer")

    assert located == ("merlin/algorithms/layer.py", ["QuantumLayer"])


async def test_find_module_path_prepends_the_package_name() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_repo(mock)
        located = await find_module_path(MERLIN, "main", "algorithms.layer")

    assert located == ("merlin/algorithms/layer.py", [])


async def test_find_module_path_follows_a_package_re_export() -> None:
    # merlin/__init__.py only imports QuantumLayer; the answer is where it is defined.
    with respx.mock(assert_all_called=False) as mock:
        mock_repo(mock)
        located = await find_module_path(MERLIN, "main", "merlin.QuantumLayer")

    assert located == ("merlin/algorithms/layer.py", ["QuantumLayer"])


async def test_find_module_path_returns_none_for_an_unknown_module() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_repo(mock)
        assert await find_module_path(MERLIN, "main", "merlin.nope.missing") is None


def test_slice_symbol_narrows_to_one_class() -> None:
    sliced = slice_symbol(SAMPLE_MODULE, ["QuantumLayer"])
    assert sliced is not None
    assert sliced.startswith("class QuantumLayer")
    assert "def simple" not in sliced


def test_slice_symbol_reaches_a_method() -> None:
    sliced = slice_symbol(SAMPLE_MODULE, ["QuantumLayer", "forward"])
    assert sliced is not None
    assert sliced.strip().startswith("def forward")


def test_slice_symbol_returns_the_module_when_no_path_given() -> None:
    assert slice_symbol(SAMPLE_MODULE, []) == SAMPLE_MODULE


def test_slice_symbol_returns_none_for_an_unknown_name() -> None:
    assert slice_symbol(SAMPLE_MODULE, ["Nope"]) is None


def test_describe_class_reports_signature_docstring_and_methods() -> None:
    details = describe_symbol(SAMPLE_MODULE, ["QuantumLayer"])
    assert details is not None
    assert details["kind"] == "class"
    assert details["signature"] == "class QuantumLayer(MerlinModule)"
    assert details["docstring"] == "Quantum neural network layer."
    assert details["init_docstring"] == "Build the layer."
    assert any("def forward" in member for member in details["members"])
    assert not any("_private" in member for member in details["members"])


def test_describe_function_includes_annotations() -> None:
    details = describe_symbol(SAMPLE_MODULE, ["simple"])
    assert details is not None
    assert details["signature"] == "def simple(input_size: int) -> QuantumLayer"


def test_describe_module_lists_public_members() -> None:
    details = describe_symbol(SAMPLE_MODULE, [])
    assert details is not None
    assert details["kind"] == "module"
    assert set(details["members"]) == {"QuantumLayer", "simple"}


def test_describe_reports_a_parse_failure_rather_than_absence() -> None:
    # Saying "not found" here would answer the caller with a confident untruth: the
    # symbol may well exist, we just could not read the file.
    with pytest.raises(ParseError, match="could not parse"):
        describe_symbol("def (:", ["x"], "merlin/broken.py")


def test_slice_reports_a_parse_failure_rather_than_absence() -> None:
    with pytest.raises(ParseError):
        slice_symbol("def (:", ["x"], "merlin/broken.py")


def test_describe_returns_none_when_the_name_is_genuinely_absent() -> None:
    assert describe_symbol(SAMPLE_MODULE, ["NoSuchClass"]) is None


def test_describe_handles_a_module_level_constant() -> None:
    details = describe_symbol(SAMPLE_MODULE, ["CONSTANT"])
    assert details is not None
    assert details["kind"] == "data"


async def test_list_tree_surfaces_a_github_error_payload() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(TREE_URL).mock(
            return_value=httpx.Response(403, json={"message": "API rate limit exceeded"})
        )
        with pytest.raises(UpstreamError, match="rate limit"):
            await list_tree(MERLIN, "main")


async def test_reading_a_module_propagates_an_outage_instead_of_reporting_absence() -> None:
    # A GitHub blip must not be reported to the caller as "no such symbol".
    with respx.mock(assert_all_called=False) as mock:
        mock.get(TREE_URL).mock(return_value=httpx.Response(200, json=make_tree(PATHS)))
        mock.get(f"{RAW}/merlin/__init__.py").mock(return_value=httpx.Response(503))
        with pytest.raises(UpstreamError):
            await find_module_path(MERLIN, "main", "merlin.QuantumLayer")


def test_invalid_refs_are_rejected_before_a_request_is_made() -> None:
    with pytest.raises(InvalidRequestError):
        MERLIN.raw_url("../../../other/repo/main", "README.md")


async def test_get_releases_maps_the_github_payload() -> None:
    payload = [
        {
            "tag_name": "0.4.0",
            "name": "Merlin v0.4: Grimoire",
            "published_at": "2026-06-18T16:20:09Z",
            "html_url": "https://github.com/merlinquantum/merlin/releases/tag/0.4.0",
            "body": "Notes here",
        }
    ]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.github.com/repos/merlinquantum/merlin/releases?per_page=1").mock(
            return_value=httpx.Response(200, json=payload)
        )
        releases = await get_releases(MERLIN, limit=1)

    assert releases[0].tag == "0.4.0"
    assert releases[0].published_at == "2026-06-18T16:20:09Z"
