# Security Policy

## Reporting a vulnerability

Please report security issues privately through GitHub's
[private vulnerability reporting](https://github.com/tonypansera/merlin-mcp/security/advisories/new)
rather than opening a public issue. You can expect an initial response within seven days.

## Threat model

This server is read-only and network-bound. Understanding what it does and does not do should
make assessment straightforward:

- It issues **outbound HTTPS GET requests only**, to `merlinquantum.ai`, `perceval.quandela.net`,
  `api.github.com`, `raw.githubusercontent.com` and `pypi.org`.
- Every request URL is built in `urls.py`, **normalised and then asserted to remain under its
  intended base** before it is sent. Tool arguments that reach a URL (`ref`, `version`, `page`,
  `name`, `target`) are validated first. Checking an un-normalised URL is not sufficient: HTTP
  clients collapse `..` path segments when building the request, so a naive prefix check can
  describe a different resource than the one actually fetched.
- It **never writes to disk**, so it cannot be used to plant files. This is enforced by a test.
- It **never imports or executes** MerLin, Perceval or any code it retrieves. Source code is
  parsed with `ast`, which does not evaluate it.
- Response bodies are **read with a byte cap** and the compressed inventory is inflated with an
  output cap, so a large or adversarial response cannot exhaust memory.
- It requires **no credentials**. `GITHUB_TOKEN` is read from the environment if present, is
  attached only when the *parsed* request host is `api.github.com`, and is never logged or
  returned in output.

The content the server returns is fetched from third-party sites and is **untrusted input to
your agent**. Treat documentation text and example code as you would any web content: an agent
should not execute retrieved code without review.

## Supported versions

Fixes are applied to the latest released version.
