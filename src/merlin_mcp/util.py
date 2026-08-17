"""Small helpers shared by the tool layer."""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")


def tokenize(query: str) -> list[str]:
    """Split a free-text query into lowercase word tokens.

    CamelCase identifiers are also split, so ``QuantumLayer`` yields
    ``["quantumlayer", "quantum", "layer"]`` and matches both the compound term
    Sphinx indexes and its parts.
    """
    tokens: list[str] = []
    for word in _WORD.findall(query):
        lowered = word.lower()
        if lowered not in tokens:
            tokens.append(lowered)
        parts = _CAMEL_PART.findall(word)
        if len(parts) > 1:
            for part in parts:
                lowered_part = part.lower()
                if len(lowered_part) > 1 and lowered_part not in tokens:
                    tokens.append(lowered_part)
    return tokens


def window(text: str, offset: int = 0, limit: int = 40_000) -> tuple[str, str]:
    """Return ``(content, footer)`` for a character window of ``text``.

    Long documentation pages and notebooks routinely exceed what is reasonable to
    put in one tool result, so every content tool exposes the same window and tells
    the caller how to ask for the rest. The footer is returned separately so callers
    that wrap content in a code fence can keep it outside the fence.
    """
    total = len(text)
    offset = max(offset, 0)
    if total and offset >= total:
        return "", f"[offset {offset} is past end of content ({total} characters)]"
    content = text[offset : offset + limit] if limit > 0 else text[offset:]
    end = offset + len(content)
    if end >= total:
        return content, ""
    return content, (
        f"[truncated: showing characters {offset}-{end} of {total}. "
        f"Call again with offset={end} for the next part.]"
    )


def paginate(text: str, offset: int = 0, limit: int = 40_000) -> str:
    """A character window of ``text`` with any truncation notice appended."""
    content, footer = window(text, offset, limit)
    return f"{content}\n\n{footer}".rstrip() if footer else content


def bullet_list(items: list[str], empty: str = "(none)") -> str:
    """Render ``items`` as a markdown bullet list."""
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)
