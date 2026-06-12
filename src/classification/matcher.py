from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz


def normalise(text: str) -> str:
    """Lower-case, strip diacritics, collapse whitespace, remove punctuation."""
    text = text.lower()
    # NFD decomposition → drop combining marks → strips all accents correctly
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fuzzy_match(a: str, b: str, threshold: int = 85) -> bool:
    """Return True if the two strings are similar enough (token_set_ratio ≥ threshold)."""
    return fuzz.token_set_ratio(normalise(a), normalise(b)) >= threshold


def contains_any(text: str, keywords: list[str], threshold: int = 85) -> bool:
    """Return True if *text* fuzzy-matches any keyword in *keywords*."""
    norm = normalise(text)
    for kw in keywords:
        norm_kw = normalise(kw)
        if norm_kw in norm:
            return True
        if fuzz.partial_ratio(norm_kw, norm) >= threshold:
            return True
    return False


