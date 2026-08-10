"""Business objective: make repeated descriptions comparable across formatting variations.

Technical description: provides Unicode normalization, tokenization, and deterministic similarity functions.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_QUOTE_TRANSLATION = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).translate(_QUOTE_TRANSLATION).lower().strip()
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def tokenize(value: str) -> tuple[str, ...]:
    normalized = normalize_text(value)
    return tuple(token for token in normalized.split(" ") if token)


def token_jaccard(left: str, right: str) -> float:
    a, b = set(tokenize(left)), set(tokenize(right))
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def sequence_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_text(left), normalize_text(right)).ratio()


def character_ngrams(value: str, n: int = 3) -> set[str]:
    normalized = f"  {normalize_text(value)}  "
    if len(normalized) < n:
        return {normalized}
    return {normalized[index:index + n] for index in range(len(normalized) - n + 1)}


def ngram_jaccard(left: str, right: str, n: int = 3) -> float:
    a, b = character_ngrams(left, n), character_ngrams(right, n)
    return len(a & b) / len(a | b) if a or b else 1.0
