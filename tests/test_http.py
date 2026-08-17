"""The HTTP layer: retries, size limits, and where credentials are allowed to go."""

from __future__ import annotations

import httpx
import pytest
import respx

from merlin_mcp import http
from merlin_mcp.config import get_settings
from merlin_mcp.errors import NotFoundError, UpstreamError

URL = "https://merlinquantum.ai/0.4/thing.txt"
API_URL = "https://api.github.com/repos/merlinquantum/merlin"


@pytest.fixture(autouse=True)
def no_backoff_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the retry loop without actually waiting for the backoff."""

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(http.asyncio, "sleep", instant)


async def test_retries_a_transient_server_error_then_succeeds() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL)
        route.side_effect = [httpx.Response(503), httpx.Response(200, text="ok")]
        assert await http.fetch_text(URL) == "ok"
        assert route.call_count == 2


async def test_gives_up_after_the_attempt_budget() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL).mock(return_value=httpx.Response(503))
        with pytest.raises(UpstreamError, match="after 3 attempts"):
            await http.fetch_text(URL)
        assert route.call_count == 3


async def test_retries_a_transport_failure() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL)
        route.side_effect = [httpx.ConnectTimeout("boom"), httpx.Response(200, text="ok")]
        assert await http.fetch_text(URL) == "ok"


async def test_transport_failure_becomes_an_upstream_error() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL).mock(side_effect=httpx.ConnectError("no route"))
        with pytest.raises(UpstreamError):
            await http.fetch_text(URL)


async def test_a_missing_resource_raises_unless_it_is_optional() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL).mock(return_value=httpx.Response(404))
        with pytest.raises(NotFoundError):
            await http.fetch_text(URL)
        assert await http.fetch_text(URL, optional=True) is None


async def test_a_not_found_is_remembered_only_briefly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 404 during a docs redeploy must not be believed for the whole index TTL."""
    monkeypatch.setenv("MERLIN_MCP_NOT_FOUND_TTL", "0")
    get_settings.cache_clear()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL)
        route.side_effect = [httpx.Response(404), httpx.Response(200, text="back")]
        assert await http.fetch_text(URL, ttl=3600, optional=True) is None
        assert await http.fetch_text(URL, ttl=3600, optional=True) == "back"


async def test_a_successful_body_is_cached() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL).mock(return_value=httpx.Response(200, text="ok"))
        await http.fetch_text(URL)
        await http.fetch_text(URL)
        assert route.call_count == 1


async def test_an_oversized_response_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERLIN_MCP_MAX_RESPONSE_BYTES", "16")
    get_settings.cache_clear()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL).mock(return_value=httpx.Response(200, text="x" * 1024))
        with pytest.raises(UpstreamError, match="response limit"):
            await http.fetch_text(URL)


async def test_invalid_json_is_reported_as_such() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL).mock(return_value=httpx.Response(200, text="{not json"))
        with pytest.raises(UpstreamError, match="valid JSON"):
            await http.fetch_json(URL)


async def test_the_token_is_sent_to_the_github_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    get_settings.cache_clear()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(API_URL).mock(return_value=httpx.Response(200, json={}))
        await http.fetch_json(API_URL)

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


async def test_the_token_is_never_sent_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    get_settings.cache_clear()

    raw = "https://raw.githubusercontent.com/merlinquantum/merlin/main/README.md"
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(raw).mock(return_value=httpx.Response(200, text="hi"))
        await http.fetch_text(raw)

    assert "Authorization" not in route.calls.last.request.headers


async def test_the_auth_check_uses_the_normalised_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A URL that only looks like the GitHub API must not attract the token.

    httpx collapses ``..`` when building the request, so the decision has to be made
    on the parsed URL rather than on the string the caller handed in.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    get_settings.cache_clear()

    disguised = "https://api.github.com.evil.test/repos/x"
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(disguised).mock(return_value=httpx.Response(200, text="hi"))
        await http.fetch_text(disguised)

    assert "Authorization" not in route.calls.last.request.headers


async def test_error_messages_do_not_leak_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    get_settings.cache_clear()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(API_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(UpstreamError) as caught:
            await http.fetch_json(API_URL)

    assert "secret-token" not in str(caught.value)


async def test_the_client_is_reused_and_closable() -> None:
    first = await http.get_client()
    assert await http.get_client() is first
    await http.aclose()
    assert first.is_closed
    assert await http.get_client() is not first
    await http.aclose()
