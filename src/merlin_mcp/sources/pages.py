"""Fetch the text of a documentation page.

Sphinx publishes the untouched source of every page under ``_sources/``, so pages
are served as the author wrote them — reStructuredText with intact code blocks and
directives — instead of being scraped back out of rendered HTML. HTML extraction
exists only as a fallback for builds that disable ``html_copy_source``.
"""

from __future__ import annotations

import json
import logging
from html.parser import HTMLParser

from ..config import LibrarySource
from ..errors import NotFoundError, UpstreamError
from ..http import fetch_text
from ..urls import validate_docname
from .notebooks import render_notebook

logger = logging.getLogger(__name__)

_SOURCE_SUFFIXES = ("rst", "md", "txt", "ipynb")
_SKIP_TAGS = {"script", "style", "nav", "footer", "header"}
_BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "div", "section", "tr"}


class _MainTextExtractor(HTMLParser):
    """Pull readable text out of the ``role="main"`` region of a Sphinx page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._in_main = False
        self._skip = 0
        self._in_pre = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self._in_main:
            if attributes.get("role") == "main":
                self._in_main = True
                self._depth = 1
            return
        self._depth += 1
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "pre":
            self._in_pre = True
            self._chunks.append("\n```\n")
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._in_main:
            return
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "pre":
            self._in_pre = False
            self._chunks.append("\n```\n")
        self._depth -= 1
        if self._depth <= 0:
            self._in_main = False

    def handle_data(self, data: str) -> None:
        if self._in_main and not self._skip:
            self._chunks.append(data if self._in_pre else data.strip() + " ")

    @property
    def text(self) -> str:
        lines = [line.rstrip() for line in "".join(self._chunks).splitlines()]
        out: list[str] = []
        for line in lines:
            if line or (out and out[-1]):
                out.append(line)
        return "\n".join(out).strip()


def normalize_docname(page: str, library: LibrarySource) -> str:
    """Reduce a page reference to a Sphinx docname.

    Accepts a docname (``user_guide/layer``), a full documentation URL, or either
    with an ``.html`` suffix and a section anchor. The host of a supplied URL is
    discarded rather than trusted, and the result is validated so it cannot climb
    out of the documentation tree.
    """
    value = page.strip()
    if value.startswith(("http://", "https://")):
        path = value.partition("://")[2].partition("/")[2]
        base_path = library.docs_base.partition("://")[2].partition("/")[2]
        value = path[len(base_path) :] if base_path and path.startswith(base_path) else path
    value = value.split("#", 1)[0].split("?", 1)[0].strip("/")

    # Drop a leading version directory such as "0.4/" or "v1.2/".
    head, _, tail = value.partition("/")
    if tail and (head[:1].isdigit() or (head[:1] == "v" and head[1:2].isdigit())):
        value = tail

    for suffix in (".html", ".rst.txt", ".md.txt", ".ipynb.txt", ".rst", ".md", ".ipynb", ".txt"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return validate_docname(value or "index")


async def get_page(
    library: LibrarySource,
    version: str,
    page: str,
    include_outputs: bool = False,
) -> tuple[str, str, str]:
    """Return ``(text, source_url, docname)`` for one documentation page.

    Each published source format is tried in turn. A candidate that is merely absent
    moves on to the next; a candidate that could not be *reached* is remembered, so a
    transient outage on the first format never masquerades as "no such page".

    Raises:
        NotFoundError: when the page genuinely does not exist upstream.
        UpstreamError: when no candidate could be reached.
    """
    docname = normalize_docname(page, library)
    unreachable: list[str] = []

    for suffix in (*_SOURCE_SUFFIXES, "html"):
        is_html = suffix == "html"
        url = (
            library.page_url(version, docname)
            if is_html
            else library.source_url(version, docname, suffix)
        )
        try:
            text = await fetch_text(url, optional=True)
        except UpstreamError as exc:
            # Do not let one unreachable format defeat the remaining ones.
            logger.warning("could not reach %s: %s", url, exc)
            unreachable.append(f"{url} ({exc})")
            continue

        if text is None:
            continue
        if suffix == "ipynb":
            return render_notebook(json.loads(text), include_outputs), url, docname
        if is_html:
            parser = _MainTextExtractor()
            parser.feed(text)
            extracted = parser.text
            if extracted:
                return extracted, url, docname
            continue
        return text, url, docname

    if unreachable:
        raise UpstreamError(
            f"could not reach any published form of {docname!r} in {library.title} {version}: "
            + "; ".join(unreachable)
        )
    raise NotFoundError(
        f"no page {docname!r} in {library.title} {version}; "
        "use search_docs to find the right page name"
    )
