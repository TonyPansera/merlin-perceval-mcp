"""Full-text documentation search driven by Sphinx's own ``searchindex.js``.

Sphinx already ships a complete inverted index with every documentation build, so
the server searches by downloading that index rather than by crawling pages. Term
keys in the index are Porter-stemmed; instead of shipping a stemmer we match a
query token against the key set by exact, prefix and substring comparison, which
recovers the stem in practice (``quantumlayer`` finds the ``quantumlay`` key).
"""

from __future__ import annotations

import json
import math
from typing import Any

from ..config import LibrarySource, get_settings
from ..errors import UpstreamError
from ..http import fetch_text
from ..models import SearchHit
from ..util import tokenize

_PREFIX = "Search.setIndex("

# Relative weight of how a query token matched an indexed term.
_EXACT, _PREFIX_MATCH, _SUBSTRING = 1.0, 0.6, 0.35
_TITLE_BOOST = 2.5
_MAX_KEYS_PER_TOKEN = 12
_MIN_STEM = 4


def parse_search_index(text: str) -> dict[str, Any]:
    """Turn the body of ``searchindex.js`` into the underlying JSON object."""
    stripped = text.strip()
    if stripped.startswith(_PREFIX):
        stripped = stripped[len(_PREFIX) :].rstrip().rstrip(";").rstrip()
        if stripped.endswith(")"):
            stripped = stripped[:-1]
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"could not parse searchindex.js: {exc}") from exc
    if not isinstance(data, dict) or "docnames" not in data:
        raise UpstreamError("searchindex.js did not contain the expected structure")
    return data


async def load_index(library: LibrarySource, version: str) -> dict[str, Any]:
    """Fetch and parse the search index of one documentation version."""
    url = f"{library.version_base(version)}/searchindex.js"
    return parse_search_index(await fetch_text(url, ttl=get_settings().index_ttl))


def _doc_ids(value: Any) -> list[int]:
    """Normalise a term posting, which Sphinx writes as an int or a list of ints."""
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, int)]
    return []


def _matching_keys(terms: dict[str, Any], token: str) -> list[tuple[str, float]]:
    """Find indexed term keys related to one query token, with a match weight each.

    Three relationships matter, because the index stores stems rather than words:
    the key extends the token (``layer`` finds ``layers``), the token extends the key
    (``quantumlayer`` finds the stem ``quantumlay``), and plain containment.
    """
    matches: list[tuple[str, float]] = [(token, _EXACT)] if token in terms else []

    related: list[tuple[str, float]] = []
    for key in terms:
        if key == token:
            continue
        if key.startswith(token) or (len(key) >= _MIN_STEM and token.startswith(key)):
            related.append((key, _PREFIX_MATCH))
        elif len(token) >= _MIN_STEM and token in key:
            related.append((key, _SUBSTRING))

    related.sort(key=lambda pair: (-pair[1], len(pair[0])))
    return matches + related[:_MAX_KEYS_PER_TOKEN]


def _sections_for(index: dict[str, Any], doc_id: int, tokens: list[str]) -> list[str]:
    """Section headings inside one document that mention any query token."""
    all_titles = index.get("alltitles")
    if not isinstance(all_titles, dict):
        return []
    found: list[str] = []
    for title, entries in all_titles.items():
        if not isinstance(entries, list):
            continue
        lowered = title.lower()
        if not any(token in lowered for token in tokens):
            continue
        for entry in entries:
            if isinstance(entry, list) and entry and entry[0] == doc_id and title not in found:
                found.append(title)
                break
        if len(found) >= 5:
            break
    return found


def search(
    index: dict[str, Any],
    library: LibrarySource,
    version: str,
    query: str,
    limit: int = 10,
) -> list[SearchHit]:
    """Rank documentation pages against a free-text query."""
    tokens = tokenize(query)
    if not tokens:
        return []

    docnames: list[str] = index.get("docnames", [])
    titles: list[str] = index.get("titles", [])
    terms: dict[str, Any] = index.get("terms") or {}
    title_terms: dict[str, Any] = index.get("titleterms") or {}
    total_docs = max(len(docnames), 1)

    # Score per (document, query token), keeping only the best-matching stem for that
    # token. Summing every stem instead would rank long pages that mention a word in
    # many inflected forms above the page actually about it.
    per_token: dict[int, dict[str, float]] = {}
    matched: dict[int, list[str]] = {}

    def accumulate(source: dict[str, Any], boost: float) -> None:
        for token in tokens:
            for key, weight in _matching_keys(source, token):
                docs = _doc_ids(source.get(key))
                if not docs:
                    continue
                contribution = weight * boost * math.log(1.0 + total_docs / len(docs))
                for doc_id in docs:
                    bucket = per_token.setdefault(doc_id, {})
                    if contribution > bucket.get(token, 0.0):
                        bucket[token] = contribution
                    keys = matched.setdefault(doc_id, [])
                    if key not in keys:
                        keys.append(key)

    accumulate(terms, 1.0)
    accumulate(title_terms, _TITLE_BOOST)

    scores: dict[int, float] = {}
    for doc_id, contributions in per_token.items():
        # Covering more of the query matters more than matching one token strongly.
        coverage = len(contributions) / len(tokens)
        scores[doc_id] = sum(contributions.values()) * (0.5 + 0.5 * coverage) + coverage * 2.0

    # A page whose title literally contains a query token is almost always the answer.
    for doc_id, title in enumerate(titles):
        lowered = title.lower()
        if doc_id not in scores:
            continue
        hits = sum(1 for token in tokens if token in lowered)
        if hits:
            scores[doc_id] += hits * 3.0
        if all(token in lowered for token in tokens):
            scores[doc_id] += 6.0

    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], docnames[pair[0]]))
    results: list[SearchHit] = []
    for doc_id, score in ranked[:limit]:
        docname = docnames[doc_id]
        results.append(
            SearchHit(
                docname=docname,
                title=titles[doc_id] if doc_id < len(titles) else docname,
                url=library.page_url(version, docname),
                score=round(score, 3),
                matched_terms=matched.get(doc_id, [])[:6],
                sections=_sections_for(index, doc_id, tokens),
            )
        )
    return results


def toc_entries(index: dict[str, Any]) -> list[tuple[str, str]]:
    """Every documented page as ``(docname, title)`` pairs, for the index resource."""
    docnames: list[str] = index.get("docnames", [])
    titles: list[str] = index.get("titles", [])
    return [
        (docname, titles[position] if position < len(titles) else docname)
        for position, docname in enumerate(docnames)
    ]
