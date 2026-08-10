"""Business objective: reject corrupted line extraction before canonicalization and separately reconcile invoice-level financial fields.

Technical description: validates line arithmetic/subtotals as a blocking quality gate and discount/tax/shipping/amount-due relationships as non-blocking financial evidence using Decimal tolerances.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from invoice_canonicalizer.domain.models import (
    ExtractionQualityReport,
    ExtractionQualityStatus,
    FinancialQualityReport,
    InvoiceFinancials,
    InvoiceLine,
)
from invoice_canonicalizer.utils.money import MONEY_QUANTUM, ZERO, money


def validate_extraction_quality(
    lines: Sequence[InvoiceLine],
    declared_subtotal: Decimal | None = None,
    *,
    tolerance: Decimal = MONEY_QUANTUM,
) -> ExtractionQualityReport:
    complete = 0
    valid = 0
    invalid = 0
    totals: list[Decimal] = []
    checks: list[str] = []

    for line in lines:
        if line.total is not None:
            totals.append(line.total)
        if line.quantity is None or line.unit_price is None or line.total is None:
            continue
        complete += 1
        expected = line.quantity * line.unit_price
        if abs(expected - line.total) <= tolerance:
            valid += 1
        else:
            invalid += 1
            checks.append(
                f"row_arithmetic_mismatch:{line.source_line_id}:"
                f"{line.quantity}*{line.unit_price}!={line.total}"
            )

    calculated = money(sum(totals, ZERO)) if totals else None
    subtotal_matches: bool | None = None
    if declared_subtotal is not None and calculated is not None:
        subtotal_matches = abs(calculated - declared_subtotal) <= tolerance
        if not subtotal_matches:
            checks.append(f"subtotal_mismatch:{calculated}!={money(declared_subtotal)}")
        else:
            checks.append("subtotal_matches")

    if invalid or subtotal_matches is False or not lines:
        status = ExtractionQualityStatus.FAIL
    elif complete == 0:
        status = ExtractionQualityStatus.WARN
        checks.append("no_complete_arithmetic_rows")
    else:
        status = ExtractionQualityStatus.PASS
        checks.append("row_arithmetic_pass")

    return ExtractionQualityReport(
        status=status,
        rows_extracted=len(lines),
        rows_with_complete_arithmetic=complete,
        rows_arithmetic_valid=valid,
        rows_arithmetic_invalid=invalid,
        calculated_subtotal=calculated,
        declared_subtotal=money(declared_subtotal) if declared_subtotal is not None else None,
        subtotal_matches=subtotal_matches,
        checks=tuple(checks),
    )


def validate_financial_quality(
    financials: InvoiceFinancials,
    *,
    tolerance: Decimal = MONEY_QUANTUM,
) -> FinancialQualityReport:
    """Reconcile document totals without blocking product canonicalization when optional header fields are absent."""
    checks: list[str] = []
    discount_ok: bool | None = None
    tax_ok: bool | None = None
    due_ok: bool | None = None

    if (
        financials.subtotal is not None
        and financials.discount_total is not None
        and financials.subtotal_after_discount is not None
    ):
        discount_ok = abs(
            financials.subtotal - financials.discount_total - financials.subtotal_after_discount
        ) <= tolerance
        checks.append("discount_reconciles" if discount_ok else "discount_mismatch")

    if (
        financials.subtotal_after_discount is not None
        and financials.tax_rate_percent is not None
        and financials.tax_total is not None
    ):
        expected_tax = financials.subtotal_after_discount * financials.tax_rate_percent / Decimal("100")
        tax_ok = abs(expected_tax - financials.tax_total) <= tolerance
        checks.append("tax_reconciles" if tax_ok else "tax_mismatch")

    if financials.amount_due is not None:
        base = financials.subtotal_after_discount
        if base is None and financials.subtotal is not None:
            discount = financials.discount_total or ZERO
            base = financials.subtotal - discount
        if base is not None and financials.tax_total is not None:
            expected_due = base + financials.tax_total + (financials.shipping_total or ZERO)
            due_ok = abs(expected_due - financials.amount_due) <= tolerance
            checks.append("amount_due_reconciles" if due_ok else "amount_due_mismatch")

    observed = [value for value in (discount_ok, tax_ok, due_ok) if value is not None]
    if not observed:
        status = ExtractionQualityStatus.WARN
        checks.append("insufficient_financial_fields_for_reconciliation")
    elif all(observed):
        status = ExtractionQualityStatus.PASS
    else:
        status = ExtractionQualityStatus.FAIL
    return FinancialQualityReport(
        status=status,
        discount_reconciles=discount_ok,
        tax_reconciles=tax_ok,
        amount_due_reconciles=due_ok,
        checks=tuple(checks),
    )
