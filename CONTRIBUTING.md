# Contributing

Thanks for helping out. Issues and pull requests are welcome.

## Getting set up

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pre-commit install
```

## Before you open a pull request

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
```

CI runs exactly these on Python 3.10 through 3.13.

## Testing rules

- The default suite must pass **with no network access**. Mock every HTTP call with `respx`.
- Build upstream payloads in memory using the helpers in `tests/conftest.py`. Do not commit
  recorded fixture files — they go stale, and staleness is the thing this project exists to avoid.
- Tests that hit the real documentation sites belong in `tests/test_live.py` and must carry
  `pytestmark = pytest.mark.network`. They are deselected by default and run weekly by the
  canary workflow.

## Design constraints

Two rules define this project. Please keep them:

1. **Nothing is written to disk.** All caching goes through the in-memory `TTLCache` in
   `cache.py`. `tests/test_no_disk.py` enforces this.
2. **No version is hardcoded.** The docs version is discovered at runtime in
   `sources/version.py`. If you need a constant, it belongs in the fallback chain, not in a
   URL.

## Adding another library

Both supported libraries are described by one `LibrarySource` entry in `src/merlin_mcp/config.py`.
If a project publishes a Sphinx build with `objects.inv`, `searchindex.js` and `_sources/`, adding
it should be a new registry entry plus tests — not new fetching code. If it needs new fetching
code, say so in the issue first so we can discuss where it belongs.

## Commit and PR style

- One logical change per pull request.
- Explain *why* in the description; the diff already says what.
- Update `CHANGELOG.md` under `## Unreleased` for anything user-visible.
