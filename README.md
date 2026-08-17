# merlin-perceval-mcp

An [MCP](https://modelcontextprotocol.io) server that gives AI coding agents accurate, up-to-date knowledge of **[MerLin](https://merlinquantum.ai)**, Quandela's photonic quantum machine learning framework for PyTorch, and **[Perceval](https://perceval.quandela.net/docs/)**, the photonic SDK it is built on.

MerLin is young and moving fast, and it post-dates the training cutoff of most models. Left to itself an agent will invent plausible-looking `QuantumLayer` arguments that do not exist. This server replaces guessing with the real documentation, the real signatures and the real example notebooks.

## Nothing is stored locally

The server ships **no vendored documentation** and writes **nothing to disk**. Every answer is fetched at call time from the published documentation sites, GitHub and PyPI, and cached only in memory for the life of the process.

It also does not hardcode a version. On each call it reads the docs landing page, follows the redirect that names the current version, and serves that. When MerLin 0.5 ships, this server serves 0.5 — no update, no re-index, no maintenance.

That leaves exactly one failure mode: upstream changing how it publishes. A scheduled [canary workflow](.github/workflows/upstream-canary.yml) runs the live tests weekly and opens an issue if the published layout ever moves.

## Install

```bash
git clone https://github.com/TonyPansera/merlin-perceval-mcp.git
cd merlin-perceval mcp
python -m venv .venv && .venv/bin/pip install -e .
```

Requires Python 3.10+. The only runtime dependencies are `mcp` and `httpx`. The server never imports the libraries it documents.

## Connect the mcp

**Claude code**

```bash
claude mcp add merlin -- .venv/bin/merlin-mcp
```

## Tools

Every tool takes `library`, either `"merlin"` (the default) or `"perceval"`.

| Tool | What it does |
| --- | --- |
| `search_docs` | Full-text search across the documentation; returns pages, URLs and matching sections. |
| `get_doc_page` | The full published source of one page — reStructuredText, code blocks intact. |
| `search_api` | Find documented symbols by name across classes, functions, methods and modules. |
| `get_api_doc` | Exact signature, docstring and public methods of one symbol, parsed from real source. |
| `get_source` | The library's actual source code, narrowed to one class or function. |
| `list_examples` | The curated example gallery, with summaries and tags. |
| `get_example` | An example notebook rendered as markdown with runnable code cells. |
| `get_release_notes` | Recent upstream release notes — the best guide to what changed. |

There is also a `docs://{library}/index` resource listing every documentation page, and a `merlin_quickstart` prompt that walks an agent through grounding its code in the docs.

A typical session: `search_docs("angle encoding")` → `get_doc_page(...)` →
`get_api_doc("QuantumLayer")` → `get_example("notebooks/FirstQuantumLayers")` → write code
that actually runs.

## Configuration

All optional.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MERLIN_MCP_MERLIN_VERSION` | auto-discovered | Pin the MerLin docs version, e.g. `0.3`. |
| `MERLIN_MCP_PERCEVAL_VERSION` | auto-discovered | Pin the Perceval docs version, e.g. `v1.1`. |
| `MERLIN_MCP_CACHE_TTL` | `3600` | Seconds to cache indexes and inventories. |
| `MERLIN_MCP_PAGE_CACHE_TTL` | `900` | Seconds to cache pages and source files. |
| `MERLIN_MCP_NOT_FOUND_TTL` | `60` | Seconds to remember a 404. Kept short so a page missing during a docs redeploy is not reported as absent for the whole cache lifetime. |
| `MERLIN_MCP_MAX_RESPONSE_BYTES` | `33554432` | Hard cap on any single response body, and on inventory decompression. |
| `MERLIN_MCP_TIMEOUT` | `30` | HTTP timeout in seconds. |
| `MERLIN_MCP_LOG_LEVEL` | `WARNING` | Logging level. Logs go to stderr, leaving stdout free for the protocol. Also settable with `--log-level`. |
| `GITHUB_TOKEN` | unset | Raises the GitHub API rate limit. Rarely needed: the server makes at most a couple of API calls per repository per hour, and reads all file contents through `raw.githubusercontent.com`, which is not rate limited. |

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest              # offline: every HTTP call is mocked
.venv/bin/pytest -m network   # live: hits the real docs sites and repositories
.venv/bin/ruff check . && .venv/bin/mypy
```

The offline suite builds its upstream payloads in memory, so there are no recorded fixtures to keep in sync and it passes with the network unplugged.

## How it works

Both documentation sites are Sphinx builds, and Sphinx publishes everything needed to answer questions about a library without scraping a single rendered page:

- `objects.inv` — a compressed index of every documented symbol and its URL.
- `searchindex.js` — the complete inverted full-text index Sphinx builds for its own search box.
- `_sources/<page>.rst.txt` — the untouched source of every page.

Signatures come from parsing the real modules on GitHub with Python's `ast`, which is more faithful than rendered autodoc HTML. Adding another Sphinx-documented library is one entry in the registry in [`config.py`](src/merlin_mcp/config.py).

## License

MIT. MerLin and Perceval are projects of [Quandela](https://www.quandela.com), this server is an independent client of their public documentation.
