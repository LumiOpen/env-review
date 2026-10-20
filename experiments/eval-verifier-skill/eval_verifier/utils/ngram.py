"""N-gram utilities for contamination detection."""

from __future__ import annotations

import re
from collections import defaultdict


def tokenize(text: str) -> list[str]:
    """Whitespace-tokenize, lowercased."""
    return re.sub(r"\s+", " ", text.strip().lower()).split()


def ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def build_index(texts: list[str], n: int) -> set[tuple[str, ...]]:
    """Build a single set of n-grams from all texts."""
    idx: set[tuple[str, ...]] = set()
    for text in texts:
        idx |= ngrams(tokenize(text), n)
    return idx


def overlap_fraction(text: str, index: set[tuple[str, ...]], n: int) -> float:
    """Fraction of a text's n-grams that appear in the index."""
    toks = tokenize(text)
    grams = ngrams(toks, n)
    if not grams:
        return 0.0
    return len(grams & index) / len(grams)


def has_overlap(text: str, index: set[tuple[str, ...]], n: int) -> bool:
    toks = tokenize(text)
    return bool(ngrams(toks, n) & index)
