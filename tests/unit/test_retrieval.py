"""Business objective: verify retrieval prefers correct approved products and rejects attribute conflicts.

Technical description: searches seeded aliases with lexical, token, trigram, category, and protected-attribute signals.
"""

from invoice_canonicalizer.domain.models import InvoiceLine
from invoice_canonicalizer.infrastructure.retrieval.hybrid import HybridRetriever


def test_hybrid_retrieval_finds_near_synonym(container) -> None:
    retriever = HybridRetriever(container.repository)
    candidates = retriever.search(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="White cotton tee shirt", source_line_id="x",
    ))
    assert candidates
    assert candidates[0].product.canonical_description == "White Tee"


def test_color_conflict_penalizes_candidate(container) -> None:
    retriever = HybridRetriever(container.repository)
    candidates = retriever.search(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Beige logo t-shirt", source_line_id="x",
    ))
    assert candidates[0].product.canonical_description == "Beige Tee"
    white = next(item for item in candidates if item.product.canonical_description == "White Tee")
    assert "color" in white.conflicting_attributes


class _SemanticBoostProvider:
    """Business objective: test the optional semantic extension without external embeddings.

    Technical description: returns deterministic product scores so the hybrid ranking can be asserted offline.
    """

    enabled = True

    def score_products(self, query, products):
        del query
        return {
            product.product_id: (1.0 if product.canonical_description == "Crew Socks" else 0.0)
            for product in products
        }


def test_optional_semantic_provider_can_rerank_without_changing_repository_contract(container) -> None:
    retriever = HybridRetriever(container.repository, semantic_provider=_SemanticBoostProvider(), semantic_weight=0.5)
    candidates = retriever.search(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="generic apparel item", source_line_id="semantic-x",
    ))
    assert candidates
    assert candidates[0].product.canonical_description == "Crew Socks"
    assert candidates[0].semantic_score == 1.0
