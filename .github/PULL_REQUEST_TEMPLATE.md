## What and why

<!-- What changes, and what problem it solves. The diff says what; explain why. -->

## Checklist

- [ ] `pytest` passes with no network access
- [ ] `ruff check .`, `ruff format --check .` and `mypy` pass
- [ ] New upstream requests are mocked in the offline tests
- [ ] Nothing new is written to disk, and no docs version is hardcoded
- [ ] `CHANGELOG.md` updated under `## Unreleased` if this is user-visible
