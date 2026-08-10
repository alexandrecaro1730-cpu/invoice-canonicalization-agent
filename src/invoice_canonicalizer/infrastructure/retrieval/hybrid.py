"""Business objective: retrieve approved product evidence before using generative AI.

Technical description: ranks tenant-scoped aliases with lexical, token, trigram, protected-attribute signals and an optional batch semantic reranker behind a stable interface.
"""

from __future__ import annotations

from typing import Sequence

from invoice_canonicalizer.application.ports import CatalogRepository
from invoice_canonicalizer.domain.attributes import conflicting_attributes, extract_attributes
from invoice_canonicalizer.domain.models import CanonicalProduct, InvoiceLine, RetrievalCandidate
from invoice_canonicalizer.infrastructure.retrieval.semantic import DisabledSemanticScoreProvider, SemanticScoreProvider
from invoice_canonicalizer.utils.text import ngram_jaccard, sequence_similarity, token_jaccard


class HybridRetriever:
    def __init__(
        self,
        repository: CatalogRepository,
        semantic_provider: SemanticScoreProvider | None = None,
        semantic_weight: float = 0.20,
    ) -> None:
        self.repository = repository
        self.semantic_provider = semantic_provider or DisabledSemanticScoreProvider()
        self.semantic_weight = min(0.50, max(0.0, semantic_weight))

    def search(self, line: InvoiceLine, top_k: int = 5) -> Sequence[RetrievalCandidate]:
        source_attrs = extract_attributes(line.description)
        aliases = list(self.repository.list_aliases(line.tenant_id, line.partner_id))
        products_by_id: dict[str, CanonicalProduct] = {}
        for _alias, product in aliases:
            products_by_id[product.product_id] = product
        semantic_scores = self.semantic_provider.score_products(
            line.description, list(products_by_id.values())
        ) if self.semantic_provider.enabled else {}

        best_by_product: dict[str, RetrievalCandidate] = {}
        for alias, product in aliases:
            lexical = sequence_similarity(line.description, alias.alias_text)
            token = token_jaccard(line.description, alias.alias_text)
            trigram = ngram_jaccard(line.description, alias.alias_text)
            conflicts = conflicting_attributes(source_attrs, product.attributes)
            attribute_score = 1.0 if not conflicts else 0.0
            category_bonus = 0.1 if source_attrs.get("category_hint") == product.category else 0.0
            base_score = min(
                1.0,
                0.40 * lexical + 0.30 * token + 0.20 * trigram + 0.10 * attribute_score + category_bonus,
            )
            semantic_score = min(1.0, max(0.0, float(semantic_scores.get(product.product_id, 0.0))))
            score = base_score
            if self.semantic_provider.enabled and product.product_id in semantic_scores:
                score = (1.0 - self.semantic_weight) * base_score + self.semantic_weight * semantic_score
            if conflicts:
                score *= 0.35
            candidate = RetrievalCandidate(
                product=product,
                score=round(score, 6),
                lexical_score=round(lexical, 6),
                token_score=round(token, 6),
                attribute_score=attribute_score,
                matched_alias=alias.alias_text,
                conflicting_attributes=conflicts,
                semantic_score=round(semantic_score, 6),
            )
            current = best_by_product.get(product.product_id)
            if current is None or candidate.score > current.score:
                best_by_product[product.product_id] = candidate
        ranked = sorted(best_by_product.values(), key=lambda candidate: (-candidate.score, candidate.product.product_id))
        return ranked[:top_k]
