"""Business objective: provide a benchmark-driven extension point for semantic retrieval without forcing embeddings into the deterministic assessment path.

Technical description: defines a batch semantic-score protocol and a disabled production-safe implementation; a pgvector/embedding adapter can plug in without changing canonicalization policy.
"""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from invoice_canonicalizer.domain.models import CanonicalProduct


class SemanticScoreProvider(Protocol):
    @property
    def enabled(self) -> bool: ...

    def score_products(self, query: str, products: Sequence[CanonicalProduct]) -> Mapping[str, float]: ...


class DisabledSemanticScoreProvider:
    """Make lexical/attribute retrieval explicit when semantic retrieval is not benchmark-justified."""

    enabled = False

    def score_products(self, query: str, products: Sequence[CanonicalProduct]) -> Mapping[str, float]:
        del query, products
        return {}
