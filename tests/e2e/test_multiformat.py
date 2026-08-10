"""Business objective: prove file-format changes do not alter invoice facts or canonical business results.

Technical description: runs every generated format and the supplied PDF through parsing, persistence, financial reconciliation, retrieval, and decisioning.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = json.loads((ROOT / "data/examples/expected/challenge_expected.json").read_text(encoding="utf-8"))["invoice"]


@pytest.mark.e2e
@pytest.mark.parametrize(
    "relative_path",
    [
        "data/examples/input/equivalent_invoice.pdf",
        "data/examples/input/equivalent_invoice.docx",
        "data/examples/input/equivalent_invoice.xlsx",
        "data/examples/input/equivalent_invoice.json",
        "data/examples/input/equivalent_invoice.csv",
        "data/examples/input/equivalent_invoice.txt",
        "data/examples/input/challenge_invoice.pdf",
    ],
)
def test_all_formats_produce_identical_invoice_and_canonical_results(container, expected_descriptions, relative_path: str) -> None:
    result = container.ingestion.process(ROOT / relative_path, "testinger", "default-partner")
    assert [decision.canonical_description for decision in result.decisions] == expected_descriptions
    assert all(not decision.requires_human_review for decision in result.decisions)
    assert sum((decision.estimated_cost_usd for decision in result.decisions), Decimal("0")) == Decimal("0")
    assert result.quality is not None and result.quality.status.value == "PASS"
    assert result.financial_quality is not None and result.financial_quality.status.value == "PASS"
    assert result.context.invoice_number == EXPECTED["invoice_number"]
    assert result.context.invoice_date == EXPECTED["invoice_date"]
    assert result.context.financials.amount_due == Decimal(EXPECTED["financials"]["amount_due"])
    assert {party.role.value: party.name for party in result.context.parties} == {
        item["role"]: item["name"] for item in EXPECTED["parties"]
    }
    persisted = container.repository.get_invoice_document("testinger", result.document_id)
    assert persisted is not None
    assert persisted.context.invoice_number == EXPECTED["invoice_number"]
    assert persisted.context.financials.amount_due == Decimal("332.40")
    assert len(persisted.lines) == 6


def test_document_financial_mismatch_is_persisted_but_does_not_change_product_naming(container, tmp_path) -> None:
    """Business objective: keep accounting anomalies visible without letting tax/shipping math change a product identity.

    Technical description: uses a structurally valid JSON invoice whose amount due is intentionally wrong; line
    extraction passes, financial reconciliation fails, and canonicalization still returns the approved exact alias.
    """
    import json
    from invoice_canonicalizer.domain.models import ExtractionQualityStatus

    path = tmp_path / "financial_mismatch.json"
    path.write_text(json.dumps({
        "invoice": {
            "invoice_number": "FIN-MISMATCH-1",
            "invoice_date": "2025-07-01",
            "payment_terms": "Due in 15 days",
            "currency": "USD",
            "parties": [
                {"role": "seller", "name": "Testinger GmbH"},
                {"role": "bill_to", "name": "Recipient Corp."},
            ],
            "financials": {
                "currency": "USD",
                "subtotal": "90.00",
                "discount_total": "0.00",
                "subtotal_after_discount": "90.00",
                "tax_rate_percent": "20.00",
                "tax_total": "18.00",
                "shipping_total": "12.00",
                "amount_due": "999.00"
            }
        },
        "lines": [{
            "description": "Socks, black",
            "quantity": "6", "unit_price": "15.00", "total": "90.00"
        }]
    }), encoding="utf-8")

    result = container.ingestion.process(path, "testinger", "default-partner")

    assert result.quality is not None and result.quality.status is ExtractionQualityStatus.PASS
    assert result.financial_quality is not None
    assert result.financial_quality.status is ExtractionQualityStatus.FAIL
    assert result.financial_quality.amount_due_reconciles is False
    assert result.decisions[0].canonical_description == "Crew Socks"
    assert result.decisions[0].decision_kind.value == "exact_alias"

    stored = container.repository.get_invoice_document("testinger", result.document_id)
    assert stored is not None
    assert stored.context.financials.amount_due == 999
    assert stored.financial_quality is not None
    assert stored.financial_quality.status is ExtractionQualityStatus.FAIL
