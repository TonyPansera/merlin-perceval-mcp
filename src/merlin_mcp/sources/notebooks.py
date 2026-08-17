"""Render Jupyter notebooks to markdown and read curated example galleries."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import LibrarySource, get_settings
from ..errors import UpstreamError
from ..http import fetch_json, fetch_text
from ..models import ExampleRef

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 800


def _cell_source(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def _render_outputs(cell: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for output in cell.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        text = ""
        if output.get("output_type") == "stream":
            raw = output.get("text", "")
            text = "".join(raw) if isinstance(raw, list) else str(raw)
        else:
            data = output.get("data") or {}
            plain = data.get("text/plain")
            if plain is not None:
                text = "".join(plain) if isinstance(plain, list) else str(plain)
            elif "image/png" in data:
                text = "[image output omitted]"
        if not text.strip():
            continue
        if len(text) > _MAX_OUTPUT_CHARS:
            text = text[:_MAX_OUTPUT_CHARS] + "\n... [output truncated]"
        rendered.append(f"```text\n{text.rstrip()}\n```")
    return rendered


def render_notebook(notebook: dict[str, Any], include_outputs: bool = False) -> str:
    """Convert notebook JSON into markdown with fenced code cells.

    Outputs are dropped by default: an agent reading an example wants the code that
    produces a result, not the result itself.
    """
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise UpstreamError("notebook JSON has no cell list")

    metadata = notebook.get("metadata") or {}
    kernelspec = metadata.get("kernelspec") or {}
    language = kernelspec.get("language") or "python"

    blocks: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        kind = cell.get("cell_type")
        body = _cell_source(cell).rstrip()
        if not body:
            continue
        if kind == "markdown":
            blocks.append(body)
        elif kind == "code":
            blocks.append(f"```{language}\n{body}\n```")
            if include_outputs:
                blocks.extend(_render_outputs(cell))
    return "\n\n".join(blocks)


async def fetch_notebook(url: str) -> dict[str, Any]:
    """Fetch a notebook and parse it, accepting the docs ``.ipynb.txt`` mirror."""
    text = await fetch_text(url, optional=True)
    if text is None:
        raise UpstreamError(f"no notebook at {url}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"{url} is not valid notebook JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise UpstreamError(f"{url} is not a notebook object")
    return data


async def load_gallery(library: LibrarySource, ref: str, paths: list[str]) -> list[ExampleRef]:
    """Read the project's curated gallery JSON files into example references.

    MerLin ships hand-written catalog entries with a title, one-line summary and
    tags for each notebook, which is far more useful to an agent choosing an example
    than a bare list of filenames.
    """
    if not library.gallery_dir:
        return []

    examples: dict[str, ExampleRef] = {}
    for path in paths:
        url = library.raw_url(ref, path)
        data = await fetch_json(url, ttl=get_settings().index_ttl, optional=True)
        if not isinstance(data, list):
            # A gallery file that is missing or reshaped silently costs the caller
            # example entries, so say so rather than quietly listing fewer notebooks.
            logger.warning("gallery file %s was missing or not a list", url)
            continue
        for entry in data:
            if not isinstance(entry, dict):
                continue
            doc = entry.get("doc")
            if not isinstance(doc, str) or ".ipynb" not in doc:
                continue
            name = doc.removesuffix(".ipynb")
            tags = entry.get("tags")
            examples[name] = ExampleRef(
                name=name,
                title=str(entry.get("title") or name.rsplit("/", 1)[-1]),
                summary=str(entry.get("summary") or ""),
                tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                path=f"docs/source/{doc}",
            )
    return list(examples.values())
