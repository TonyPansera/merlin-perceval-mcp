"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__
from .config import get_settings


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``merlin-mcp`` command."""
    parser = argparse.ArgumentParser(
        prog="merlin-mcp",
        description=(
            "MCP server exposing live MerLin and Perceval documentation, API reference, "
            "source code and examples."
        ),
    )
    parser.add_argument("--version", action="version", version=f"merlin-mcp {__version__}")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="transport to serve on (default: stdio, which is what MCP clients launch)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host for streamable-http")
    parser.add_argument("--port", type=int, default=8000, help="bind port for streamable-http")
    parser.add_argument(
        "--log-level",
        default=None,
        help="logging level (default: MERLIN_MCP_LOG_LEVEL, or WARNING)",
    )
    return parser


def configure_logging(level: str | None = None) -> None:
    """Send logs to stderr, which the stdio transport leaves free for diagnostics."""
    resolved = (level or get_settings().log_level).upper()
    logging.basicConfig(
        level=getattr(logging, resolved, logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the server on the requested transport."""
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    from .server import mcp

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    return 0
