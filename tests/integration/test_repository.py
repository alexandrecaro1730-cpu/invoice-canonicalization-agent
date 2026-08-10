"""Business objective: verify approved knowledge and clustered reviews remain tenant-isolated and transactional.

Technical description: exercises seed, alias lookup, review deduplication, occurrence tracking, approval, rejection conflicts, and product persistence.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from invoice_canonicalizer.domain.errors import ReviewConflictError
from invoice_canonicalizer.domain.models import PartyRole, ReviewRecord
from invoice_canonicalizer.utils.hashing import sha256_text
from invoice_canonicalizer.utils.text import normalize_text


def _review(description: str, *, review_id: str | None = None) -> ReviewRecord:
    return ReviewRecord(
        review_id=review_id or str(uuid.uuid4()), tenant_id="testinger", partner_id="default-partner",
        candidate_key=sha256_text("candidate|testinger|default-partner|" + normalize_text(description)),
        source_description=description, source_variants=(description,), source_line_ids=("repo-1",),
        proposed_description="Cotton Cap" if "Cap" in description else "Needs Product Review",
        proposed_category="headwear" if "Cap" in description else "unknown",
        attributes={"material": "cotton"} if "Cap" in description else {}, evidence=(),
        decision_score=0.5, retrieval_score=0.2, retrieval_margin=0.1, priority_score=0.0,
        llm_used=True, blocks_transaction=True,
    )


def test_alias_lookup_is_tenant_isolated(container) -> None:
    first = container.repository.find_approved_alias("testinger", "default-partner", normalize_text("White Tee"))
    second = container.repository.find_approved_alias("other-tenant", "default-partner", normalize_text("White Tee"))
    assert first and second
    assert first.product_id != second.product_id


def test_review_approval_creates_new_product_alias(container) -> None:
    review = container.repository.create_or_update_review(_review("Cotton Cap Sunrise"))
    product = container.reviews.approve("testinger", review.review_id, "Cotton Cap")
    alias = container.repository.find_approved_alias("testinger", "default-partner", normalize_text("Cotton Cap Sunrise"))
    assert alias and alias.product_id == product.product_id
    with pytest.raises(ReviewConflictError):
        container.reviews.approve("testinger", review.review_id, "Cotton Cap")


def test_review_can_be_rejected_once(container) -> None:
    review = container.repository.create_or_update_review(_review("Unknown"))
    rejected = container.reviews.reject("testinger", review.review_id)
    assert rejected.status.value == "rejected"
    with pytest.raises(ReviewConflictError):
        container.reviews.reject("testinger", review.review_id)


def test_pending_candidate_is_deduplicated_and_occurrences_accumulate(container) -> None:
    first = container.repository.create_or_update_review(_review("Cotton Cap Sunrise"))
    second = container.repository.create_or_update_review(_review("Cotton Cap Sunrise"))
    assert second.review_id == first.review_id
    assert second.occurrence_count == 2
    assert len(container.reviews.list_pending("testinger")) == 1


def test_mixed_currency_review_keeps_exact_breakdown_without_fake_total(container) -> None:
    review = _review("Cotton Cap Cross Currency")
    created = container.repository.create_or_update_review(review)
    first = container.repository.record_review_occurrence(
        "testinger", created.review_id, "Cotton Cap Cross Currency", "eur-line", 100, "EUR"
    )
    mixed = container.repository.record_review_occurrence(
        "testinger", first.review_id, "Cotton Cap Cross Currency", "usd-line", 200, "USD"
    )
    assert mixed.currency == "MIXED"
    assert mixed.affected_value == 0
    assert mixed.affected_values_by_currency["EUR"] == 100
    assert mixed.affected_values_by_currency["USD"] == 200


def test_concurrent_pending_candidate_creation_collapses_to_one_review(container) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def create(index: int):
        return container.repository.create_or_update_review(
            _review("Concurrent Cotton Cap", review_id=f"review-{index}")
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(create, range(24)))

    ids = {record.review_id for record in records}
    assert len(ids) == 1
    pending = container.reviews.list_pending("testinger")
    matching = [item for item in pending if item.source_description == "Concurrent Cotton Cap"]
    assert len(matching) == 1
    assert matching[0].occurrence_count == 24


def test_processed_invoice_persists_header_parties_financials_and_canonical_outcomes(container) -> None:
    import sqlite3
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = container.ingestion.process(
        root / "data/examples/input/challenge_invoice.pdf", "testinger", "default-partner"
    )
    stored = container.repository.get_invoice_document("testinger", result.document_id)
    assert stored is not None
    assert stored.context.invoice_number == "19283746552"
    assert stored.context.invoice_date == "2025-07-01"
    assert stored.context.due_date == "2025-07-16"
    assert stored.context.party(PartyRole.SELLER).name == "Testinger GmbH"
    assert stored.context.financials.discount_total == 13
    assert stored.context.financials.tax_total == Decimal("53.40")
    assert stored.context.financials.shipping_total == 12
    assert stored.context.financials.amount_due == Decimal("332.40")

    connection = sqlite3.connect(container.repository.database_path)
    try:
        rows = connection.execute(
            """SELECT canonical_description, decision_kind, requires_human_review
               FROM invoice_lines WHERE tenant_id = ? AND document_id = ? ORDER BY rowid""",
            ("testinger", result.document_id),
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == 6
    assert rows[0] == ("Highlife Components", "exact_alias", 0)
    assert rows[-1] == ("Crew Socks", "exact_alias", 0)


def test_persisted_invoice_is_tenant_isolated(container) -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = container.ingestion.process(
        root / "data/examples/input/challenge_invoice.pdf", "testinger", "default-partner"
    )
    assert container.repository.get_invoice_document("testinger", result.document_id) is not None
    assert container.repository.get_invoice_document("other-tenant", result.document_id) is None
