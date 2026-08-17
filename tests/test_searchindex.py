"""Full-text search over the Sphinx search index."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import VERSION, make_search_index

from merlin_mcp.config import MERLIN
from merlin_mcp.errors import UpstreamError
from merlin_mcp.sources.searchindex import parse_search_index, search, toc_entries

DOCNAMES = ["user_guide/layer", "notebooks/big_tutorial", "user_guide/noisy"]
TITLES = ["QuantumLayer Essentials", "A Very Long Tutorial", "Noisy Simulations"]
# The big tutorial mentions the topic in many inflected forms; the guide is about it.
TERMS = {
    "quantumlay": [0, 1],
    "quantumlayer": [1],
    "quantumlayers": [1],
    "train": [1],
    "trainer": [1],
    "essenti": [0],
    "noisi": [2],
    "simul": [2],
}
TITLETERMS = {"quantumlay": 0, "essenti": 0, "noisi": 2, "simul": 2}
ALLTITLES = {"Overview": [[0, "overview"]], "Batching": [[0, "batching"]]}


def index() -> dict[str, Any]:
    return parse_search_index(make_search_index(DOCNAMES, TITLES, TERMS, TITLETERMS, ALLTITLES))


def test_parse_strips_the_javascript_wrapper() -> None:
    assert index()["docnames"] == DOCNAMES


def test_parse_rejects_unexpected_content() -> None:
    with pytest.raises(UpstreamError):
        parse_search_index('Search.setIndex({"nope": 1})')


def test_parse_rejects_malformed_javascript() -> None:
    with pytest.raises(UpstreamError, match="could not parse"):
        parse_search_index('Search.setIndex({"docnames": [tru')


def test_query_token_matches_a_shorter_stem() -> None:
    # "quantumlayer" must reach the indexed stem "quantumlay".
    hits = search(index(), MERLIN, VERSION, "QuantumLayer")
    assert hits
    assert hits[0].docname == "user_guide/layer"


def test_long_page_does_not_win_on_repeated_inflections() -> None:
    ranked = [hit.docname for hit in search(index(), MERLIN, VERSION, "quantumlayer")]
    assert ranked.index("user_guide/layer") < ranked.index("notebooks/big_tutorial")


def test_multi_token_query_prefers_full_coverage() -> None:
    hits = search(index(), MERLIN, VERSION, "noisy simulation")
    assert hits[0].docname == "user_guide/noisy"


def test_hits_carry_a_usable_url_and_sections() -> None:
    hit = search(index(), MERLIN, VERSION, "overview quantumlayer")[0]
    assert hit.url == "https://merlinquantum.ai/0.4/user_guide/layer.html"
    assert "Overview" in hit.sections


def test_unmatched_query_returns_nothing() -> None:
    assert search(index(), MERLIN, VERSION, "zzzzqqqq") == []


def test_empty_query_returns_nothing() -> None:
    assert search(index(), MERLIN, VERSION, "   ") == []


def test_toc_entries_pairs_docnames_with_titles() -> None:
    assert toc_entries(index())[0] == ("user_guide/layer", "QuantumLayer Essentials")
