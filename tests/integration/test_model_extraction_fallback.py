"""Business objective: verify AI is used for document extraction only after deterministic parsing fails and never bypasses arithmetic checks.

Technical description: processes an intentionally unstructured text invoice through the stored extraction prompt/fixture and then canonicalizes the recovered product with the same shared model budget.
"""

from __future__ import annotations

from pathlib import Path

from invoice_canonicalizer.domain.models import ExtractionQualityStatus

ROOT = Path(__file__).resolve().parents[2]


def test_model_extraction_fallback_is_real_and_quality_gated(container) -> None:
    provider = container.canonicalizer.provider
    path = ROOT / "tests/fixtures/fallback/unstructured_invoice.txt"
    before_extract = provider.extraction_call_count
    before_canonical = provider.canonicalization_call_count

    result = container.ingestion.process(path, "testinger", "default-partner")

    assert result.parser_name == "model-structured-fallback"
    assert result.quality is not None
    assert result.quality.status is ExtractionQualityStatus.PASS
    assert result.quality.rows_arithmetic_valid == 1
    assert result.quality.subtotal_matches is True
    assert provider.extraction_call_count == before_extract + 1
    assert provider.canonicalization_call_count == before_canonical + 1
    assert result.decisions[0].canonical_description == "Black Leather Jacket"
    assert result.decisions[0].requires_human_review
