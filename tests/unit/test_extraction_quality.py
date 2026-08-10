"""Business objective: prove invoice parsing uses exact Decimal arithmetic and blocks incoherent extraction.

Technical description: validates US/EU number formats, row multiplication, and declared-subtotal reconciliation independently of any LLM.
"""

from __future__ import annotations

from decimal import Decimal

from invoice_canonicalizer.domain.models import ExtractionQualityStatus, InvoiceLine
from invoice_canonicalizer.infrastructure.documents.common import parse_decimal
from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_extraction_quality


def test_parse_decimal_supports_us_and_eu_thousands_formats() -> None:
    assert parse_decimal("1,234.56") == Decimal("1234.56")
    assert parse_decimal("1.234,56") == Decimal("1234.56")
    assert parse_decimal("12,50") == Decimal("12.50")


def test_extraction_quality_passes_exact_invoice_math() -> None:
    lines = (
        InvoiceLine("t", "p", "A", "1", quantity=Decimal("2"), unit_price=Decimal("10.25"), total=Decimal("20.50")),
        InvoiceLine("t", "p", "B", "2", quantity=Decimal("1"), unit_price=Decimal("5.00"), total=Decimal("5.00")),
    )
    quality = validate_extraction_quality(lines, Decimal("25.50"))
    assert quality.status is ExtractionQualityStatus.PASS
    assert quality.rows_arithmetic_valid == 2
    assert quality.subtotal_matches is True
    assert quality.calculated_subtotal == Decimal("25.50")


def test_extraction_quality_fails_row_or_subtotal_mismatch() -> None:
    lines = (
        InvoiceLine("t", "p", "A", "1", quantity=Decimal("2"), unit_price=Decimal("10"), total=Decimal("19")),
    )
    quality = validate_extraction_quality(lines, Decimal("20"))
    assert quality.status is ExtractionQualityStatus.FAIL
    assert quality.rows_arithmetic_invalid == 1
    assert quality.subtotal_matches is False


def test_financial_reconciliation_validates_discount_tax_shipping_and_due() -> None:
    from invoice_canonicalizer.domain.models import InvoiceFinancials
    from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_financial_quality

    financials = InvoiceFinancials(
        currency="USD",
        subtotal=Decimal("280.00"),
        discount_total=Decimal("13.00"),
        subtotal_after_discount=Decimal("267.00"),
        tax_rate_percent=Decimal("20.00"),
        tax_total=Decimal("53.40"),
        shipping_total=Decimal("12.00"),
        amount_due=Decimal("332.40"),
    )
    quality = validate_financial_quality(financials)
    assert quality.status is ExtractionQualityStatus.PASS
    assert quality.discount_reconciles is True
    assert quality.tax_reconciles is True
    assert quality.amount_due_reconciles is True


def test_financial_reconciliation_failure_is_visible_but_separate_from_line_gate() -> None:
    from invoice_canonicalizer.domain.models import InvoiceFinancials
    from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_financial_quality

    quality = validate_financial_quality(InvoiceFinancials(
        subtotal="280", discount_total="13", subtotal_after_discount="267",
        tax_rate_percent="20", tax_total="53.40", shipping_total="12", amount_due="999",
    ))
    assert quality.status is ExtractionQualityStatus.FAIL
    assert quality.amount_due_reconciles is False
