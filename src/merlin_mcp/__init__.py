"""MCP server exposing live MerLin and Perceval documentation to AI agents.

Nothing in this package is vendored or persisted: every answer is fetched from the
public documentation sites, GitHub and PyPI at call time and held only in an
in-memory TTL cache.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
