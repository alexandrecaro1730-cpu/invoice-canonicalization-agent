"""Business objective: prove formatting variation cannot change deterministic synonym comparison.

Technical description: tests Unicode normalization, idempotence, token similarity, and trigram behavior.
"""

from __future__ import annotations

import random
import string

from invoice_canonicalizer.utils.text import ngram_jaccard, normalize_text, sequence_similarity, token_jaccard


def test_unicode_quotes_and_punctuation_normalize_equally() -> None:
    assert normalize_text('Sneaker “Unstoppable”') == normalize_text('sneaker "unstoppable"')
    assert normalize_text("Socks, black") == "socks black"


def test_normalization_is_idempotent_for_random_inputs() -> None:
    random.seed(42)
    alphabet = string.ascii_letters + string.digits + " ,.-_“”\t\n"
    for _ in range(200):
        value = "".join(random.choice(alphabet) for _ in range(80))
        assert normalize_text(normalize_text(value)) == normalize_text(value)


def test_similarity_functions_have_expected_bounds() -> None:
    for function in (ngram_jaccard, sequence_similarity, token_jaccard):
        assert function("White Tee", "White Tee") == 1.0
        assert 0.0 <= function("White Tee", "Steel Fittings") <= 1.0
