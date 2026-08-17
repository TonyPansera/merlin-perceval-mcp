"""The command-line entry point, including the transport it hands to the server."""

from __future__ import annotations

import logging
import sys
from typing import Any

import pytest

from merlin_mcp import __version__, cli


def test_defaults_to_stdio() -> None:
    args = cli.build_parser().parse_args([])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8000


def test_accepts_streamable_http_with_a_bind_address() -> None:
    args = cli.build_parser().parse_args(
        ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9001"]
    )
    assert (args.transport, args.host, args.port) == ("streamable-http", "0.0.0.0", 9001)


def test_rejects_an_unknown_transport() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--transport", "carrier-pigeon"])


def test_version_flag_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.build_parser().parse_args(["--version"])
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out


def _capture_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from merlin_mcp import server

    recorded: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> None:
        recorded["args"] = args
        recorded["kwargs"] = kwargs

    monkeypatch.setattr(server.mcp, "run", fake_run)
    return recorded


def test_stdio_run_takes_no_transport_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _capture_run(monkeypatch)
    assert cli.main([]) == 0
    assert recorded["args"] == ()
    assert recorded["kwargs"] == {}


def test_streamable_http_run_receives_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _capture_run(monkeypatch)
    assert cli.main(["--transport", "streamable-http", "--host", "1.2.3.4", "--port", "9999"]) == 0
    assert recorded["kwargs"] == {
        "transport": "streamable-http",
        "host": "1.2.3.4",
        "port": 9999,
    }


def test_logging_goes_to_stderr_so_stdio_stays_clean() -> None:
    # stdout carries the MCP protocol on the stdio transport, so a log line written
    # there would corrupt the session.
    logging.getLogger().handlers.clear()
    cli.configure_logging("DEBUG")
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr
    assert logging.getLogger().level == logging.DEBUG


def test_log_level_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from merlin_mcp.config import get_settings

    monkeypatch.setenv("MERLIN_MCP_LOG_LEVEL", "error")
    get_settings.cache_clear()
    logging.getLogger().handlers.clear()
    cli.configure_logging()
    assert logging.getLogger().level == logging.ERROR
