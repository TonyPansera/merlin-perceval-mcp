"""Version discovery: the mechanism that keeps the server free of maintenance."""

from __future__ import annotations

import httpx
import pytest
import respx
from conftest import LANDING_PAGE, PERCEVAL_LANDING_PAGE

from merlin_mcp.config import MERLIN, PERCEVAL
from merlin_mcp.errors import InvalidRequestError
from merlin_mcp.sources.version import resolve_version, scan_landing_page


def test_scan_reads_merlin_meta_refresh() -> None:
    assert scan_landing_page(LANDING_PAGE) == "0.4"


def test_scan_reads_perceval_relative_canonical() -> None:
    assert scan_landing_page(PERCEVAL_LANDING_PAGE) == "v1.2"


def test_scan_falls_back_to_javascript_constant() -> None:
    page = '<html><script>const latest = "v9.9";</script></html>'
    assert scan_landing_page(page) == "v9.9"


def test_scan_returns_none_without_a_redirect() -> None:
    assert scan_landing_page("<html><body>hello</body></html>") is None


async def test_resolve_version_follows_the_landing_page() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://merlinquantum.ai/").mock(
            return_value=httpx.Response(200, text=LANDING_PAGE)
        )
        resolved = await resolve_version(MERLIN)

    assert resolved.version == "0.4"
    assert resolved.origin == "landing"
    assert resolved.is_fallback is False


async def test_resolve_version_prefers_an_explicit_override() -> None:
    resolved = await resolve_version(MERLIN, "0.3")
    assert (resolved.version, resolved.origin) == ("0.3", "explicit")


async def test_resolve_version_honours_the_environment_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERLIN_MCP_PERCEVAL_VERSION", "v1.1")
    resolved = await resolve_version(PERCEVAL)
    assert (resolved.version, resolved.origin) == ("v1.1", "pinned")


async def test_resolve_version_rejects_a_traversing_override() -> None:
    with pytest.raises(InvalidRequestError):
        await resolve_version(MERLIN, "../../etc")


async def test_resolve_version_marks_the_fallback_as_a_fallback() -> None:
    # The whole point: a version nobody could verify must not be presented as fact.
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://merlinquantum.ai/").mock(return_value=httpx.Response(404))
        mock.get("https://pypi.org/pypi/merlinquantum/json").mock(return_value=httpx.Response(404))
        resolved = await resolve_version(MERLIN)

    assert resolved.version == MERLIN.fallback_version
    assert resolved.origin == "fallback"
    assert resolved.is_fallback is True


async def test_resolve_version_falls_back_when_upstream_errors_rather_than_404s() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://merlinquantum.ai/").mock(return_value=httpx.Response(500))
        mock.get("https://pypi.org/pypi/merlinquantum/json").mock(return_value=httpx.Response(500))
        resolved = await resolve_version(MERLIN)

    assert resolved.is_fallback is True


async def test_resolve_version_derives_from_pypi_when_verified() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://merlinquantum.ai/").mock(return_value=httpx.Response(404))
        mock.get("https://pypi.org/pypi/merlinquantum/json").mock(
            return_value=httpx.Response(200, json={"info": {"version": "0.9.2"}})
        )
        mock.get("https://merlinquantum.ai/0.9/objects.inv").mock(
            return_value=httpx.Response(200, content=b"anything")
        )
        resolved = await resolve_version(MERLIN)

    assert (resolved.version, resolved.origin) == ("0.9", "pypi")


async def test_resolve_version_ignores_an_unpublished_pypi_version() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://merlinquantum.ai/").mock(return_value=httpx.Response(404))
        mock.get("https://pypi.org/pypi/merlinquantum/json").mock(
            return_value=httpx.Response(200, json={"info": {"version": "9.9.0"}})
        )
        mock.get("https://merlinquantum.ai/9.9/objects.inv").mock(return_value=httpx.Response(404))
        resolved = await resolve_version(MERLIN)

    assert resolved.is_fallback is True
