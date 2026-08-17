"""Allow ``python -m merlin_mcp``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
