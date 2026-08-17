"""URL confinement.

These are the regression tests for a real vulnerability: because httpx collapses
``..`` segments when it builds a request, a caller-supplied ``ref`` could steer a
GitHub API call — carrying the operator's token — at an arbitrary repository, while
a naive string-prefix check still said the URL was fine.
"""

from __future__ import annotations

import httpx
import pytest

from merlin_mcp.config import MERLIN, PERCEVAL
from merlin_mcp.errors import InvalidRequestError
from merlin_mcp.urls import confined, validate_docname, validate_ref, validate_version

TRAVERSAL = "../../../../../repos/torvalds/linux/git/trees/master"


@pytest.mark.parametrize("ref", ["main", "v0.3.1", "release/1.2", "a1b2c3d4"])
def test_plausible_refs_are_accepted(ref: str) -> None:
    assert validate_ref(ref) == ref


@pytest.mark.parametrize(
    "ref",
    [TRAVERSAL, "../main", "main/../../x", "/main", "main//x", "", "a" * 300, "main\nHost: evil"],
)
def test_dangerous_refs_are_rejected(ref: str) -> None:
    with pytest.raises(InvalidRequestError):
        validate_ref(ref)


@pytest.mark.parametrize("version", ["0.4", "v1.2", "0.4.post1"])
def test_plausible_versions_are_accepted(version: str) -> None:
    assert validate_version(version) == version


@pytest.mark.parametrize("version", ["..", "../0.4", "0.4/../..", "", "a/b"])
def test_dangerous_versions_are_rejected(version: str) -> None:
    with pytest.raises(InvalidRequestError):
        validate_version(version)


@pytest.mark.parametrize("docname", ["user_guide/layer", "index", "notebooks/release_0,3"])
def test_plausible_docnames_are_accepted(docname: str) -> None:
    assert validate_docname(docname) == docname


@pytest.mark.parametrize("docname", ["../etc/passwd", "a/../../b", "a/./b", "a\\b", "a\x00b"])
def test_dangerous_docnames_are_rejected(docname: str) -> None:
    with pytest.raises(InvalidRequestError):
        validate_docname(docname)


def test_confined_accepts_a_url_under_its_base() -> None:
    url = "https://merlinquantum.ai/0.4/user_guide/layer.html"
    assert confined(url, "https://merlinquantum.ai/0.4") == url


def test_confined_rejects_a_url_that_normalises_out_of_its_base() -> None:
    # This exact string passes a startswith() check but is sent somewhere else.
    escaping = "https://merlinquantum.ai/0.4/../../etc/passwd"
    assert str(httpx.URL(escaping)) == "https://merlinquantum.ai/etc/passwd"
    with pytest.raises(InvalidRequestError):
        confined(escaping, "https://merlinquantum.ai/0.4")


def test_repository_urls_cannot_be_steered_to_another_repo() -> None:
    with pytest.raises(InvalidRequestError):
        MERLIN.raw_url(TRAVERSAL, "README.md")
    with pytest.raises(InvalidRequestError):
        MERLIN.raw_url("main", "../../../torvalds/linux/master/README")


def test_api_urls_cannot_be_steered_to_another_repo() -> None:
    # The token-bearing path. Before the fix this produced a request to
    # api.github.com/repos/torvalds/linux/... with the Authorization header attached.
    with pytest.raises(InvalidRequestError):
        MERLIN.api_url(f"git/trees/{TRAVERSAL}?recursive=1")


def test_docs_urls_cannot_escape_their_version_directory() -> None:
    with pytest.raises(InvalidRequestError):
        MERLIN.source_url("0.4", "../../../etc/passwd")
    with pytest.raises(InvalidRequestError):
        MERLIN.page_url("../..", "index")


def test_query_and_fragment_characters_are_encoded_into_the_path() -> None:
    url = MERLIN.page_url("0.4", "guide/a?b#c")
    assert "%3F" in url and "%23" in url
    assert httpx.URL(url).query == b""


def test_both_libraries_build_expected_urls() -> None:
    assert (
        MERLIN.page_url("0.4", "user_guide/layer")
        == "https://merlinquantum.ai/0.4/user_guide/layer.html"
    )
    assert (
        PERCEVAL.source_url("v1.2", "reference/circuit")
        == "https://perceval.quandela.net/docs/v1.2/_sources/reference/circuit.rst.txt"
    )
    assert (
        PERCEVAL.api_url("releases?per_page=1")
        == "https://api.github.com/repos/Quandela/Perceval/releases?per_page=1"
    )
