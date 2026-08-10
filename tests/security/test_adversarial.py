"""Business objective: prove malicious descriptions cannot leak tenant data or bypass approval.

Technical description: exercises prompt injection, cross-tenant aliases, and PII-minimized provider prompts.
"""

from __future__ import annotations

from invoice_canonicalizer.domain.models import InvoiceLine


def test_cross_tenant_alias_never_leaks_product(container) -> None:
    decision = container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="White Tee", source_line_id="tenant-1",
    ))
    assert decision.canonical_product_id == "product-white-tee"
    assert decision.canonical_product_id != "product-other-tenant-white-shirt"


def test_identical_raw_alias_can_resolve_differently_by_tenant(container) -> None:
    """Business objective: prove client-specific taxonomies can safely reuse the same raw wording.

    Technical description: the same normalized alias is looked up inside tenant + partner scope,
    allowing independent clients to map identical supplier text to different internal products.
    """
    tenant_a = container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Steel Accessories", source_line_id="collision-a",
    ))
    tenant_b = container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="other-tenant", partner_id="default-partner",
        description="Steel Accessories", source_line_id="collision-b",
    ))

    assert tenant_a.canonical_description == "Highlife Components"
    assert tenant_b.canonical_description == "Maintenance Hardware Kit"
    assert tenant_a.canonical_product_id != tenant_b.canonical_product_id
    assert tenant_a.provider is None and tenant_b.provider is None


def test_pii_is_not_present_in_model_prompt(container) -> None:
    provider = container.canonicalizer.provider
    description = "Cotton Cap Sunrise person@example.com +49 123 456 7890"
    decision = container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description=description, source_line_id="pii-1",
    ))
    assert decision.requires_human_review
    assert provider.last_user_prompt is not None
    assert "person@example.com" not in provider.last_user_prompt
    assert "+49 123 456 7890" not in provider.last_user_prompt
    assert "[REDACTED_" in provider.last_user_prompt


def test_party_pii_is_stored_but_not_sent_to_canonicalization_model(container, tmp_path) -> None:
    import json

    path = tmp_path / "pii_invoice.json"
    path.write_text(json.dumps({
        "invoice": {
            "invoice_number": "PII-1",
            "currency": "USD",
            "parties": [
                {
                    "role": "seller",
                    "name": "Sensitive Supplier GmbH",
                    "address_lines": ["Secret Street 99", "12345 Hamburg"],
                    "email": "private@example.com",
                    "phone": "+49 123 456789"
                }
            ],
            "financials": {
                "currency": "USD", "subtotal": "100.00", "discount_total": "5.00",
                "subtotal_after_discount": "95.00", "tax_rate_percent": "20.00",
                "tax_total": "19.00", "shipping_total": "7.00", "amount_due": "121.00"
            }
        },
        "lines": [{
            "description": "Black Leather Jacket Midnight",
            "quantity": "2", "unit_price": "50.00", "total": "100.00"
        }]
    }), encoding="utf-8")
    provider = container.canonicalizer.provider
    result = container.ingestion.process(path, "testinger", "default-partner")
    assert result.decisions[0].requires_human_review
    assert provider.canonicalization_call_count == 1
    prompt = provider.last_user_prompt or ""
    assert "private@example.com" not in prompt
    assert "Secret Street 99" not in prompt
    assert "+49 123 456789" not in prompt
    assert "PII-1" not in prompt
    assert "121.00" not in prompt
    assert "19.00" not in prompt
    assert "7.00" not in prompt
    stored = container.repository.get_invoice_document("testinger", result.document_id)
    assert stored is not None
    assert stored.context.parties[0].email == "private@example.com"
