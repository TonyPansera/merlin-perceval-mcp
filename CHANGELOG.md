# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

Initial release.

### Added

- Eight MCP tools over live MerLin and Perceval documentation: `search_docs`, `get_doc_page`,
  `search_api`, `get_api_doc`, `get_source`, `list_examples`, `get_example` and
  `get_release_notes`.
- A `docs://{library}/index` resource listing every documentation page, and a
  `merlin_quickstart` prompt.
- Runtime version discovery from the documentation landing page, so the server follows upstream
  releases without a code change. Overridable per library by environment variable.
- Full-text search backed by Sphinx's own `searchindex.js`, with stem-aware matching so a query
  word finds the stem the index actually stores.
- API signatures parsed from real module source with `ast`, including following a name
  re-exported by a package to the module that defines it.
- stdio and streamable-HTTP transports.
- An offline test suite that passes with no network access, and a network-marked live suite run
  weekly to detect upstream layout changes.
- Logging to stderr throughout, so a swallowed upstream failure leaves a trace. Level is set by
  `MERLIN_MCP_LOG_LEVEL` or `--log-level`.
- Pooled HTTP connections are released on shutdown through the server lifespan.

### Security

- Request URLs are validated and confined to their intended base before being sent, so no tool
  argument can redirect a request to another repository, another documentation tree, or another
  path on the GitHub API. The bearer token is attached only when the parsed request host is
  `api.github.com`.
- Response bodies are read under a byte cap, and `objects.inv` is inflated under an output cap,
  removing the unbounded-memory paths.

### Notes on behaviour

- A documentation version that could not be discovered is reported as a fallback in every tool
  result rather than presented as the live version.
- A module that cannot be parsed raises a parse error instead of being reported as "symbol not
  found", which previously produced a confident wrong answer.
- A page format that cannot be reached no longer prevents the remaining formats from being
  tried, and a 404 is remembered only briefly.
