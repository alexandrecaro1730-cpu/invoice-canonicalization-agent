"""Business objective: verify every supported invoice format retains the same business context and six line items.

Technical description: exercises PDF, DOCX OOXML, XLSX OOXML, JSON, CSV, TXT, OCR fallback, party/header extraction, and financial reconciliation contracts.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_canonicalizer.domain.errors import DocumentExtractionError
from invoice_canonicalizer.domain.models import PartyRole
from invoice_canonicalizer.infrastructure.documents.delimited_parser import DelimitedInvoiceParser
from invoice_canonicalizer.infrastructure.documents.docx_parser import DocxInvoiceParser
from invoice_canonicalizer.infrastructure.documents.json_parser import JsonInvoiceParser
from invoice_canonicalizer.infrastructure.documents.pdf_parser import PdfInvoiceParser
from invoice_canonicalizer.infrastructure.documents.xlsx_parser import XlsxInvoiceParser

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "data/examples/input"
EXPECTED = json.loads((ROOT / "data/examples/expected/challenge_expected.json").read_text(encoding="utf-8"))["invoice"]


def _assert_context(parsed) -> None:
    context = parsed.context
    assert context.invoice_number == EXPECTED["invoice_number"]
    assert context.invoice_date == EXPECTED["invoice_date"]
    assert context.due_date == EXPECTED["due_date"]
    assert context.payment_terms == EXPECTED["payment_terms"]
    expected_parties = {item["role"]: item for item in EXPECTED["parties"]}
    for role in PartyRole:
        party = context.party(role)
        expected = expected_parties[role.value]
        assert party is not None
        assert party.name == expected["name"]
        assert party.contact_name == expected["contact_name"]
        assert list(party.address_lines) == expected["address_lines"]
        assert party.phone == expected["phone"]
        assert party.email == expected["email"]
        assert party.website == expected["website"]
    financials = context.financials
    for key, value in EXPECTED["financials"].items():
        if key == "currency":
            assert financials.currency == value
        else:
            assert getattr(financials, key) == Decimal(value)
    assert parsed.financial_quality is not None
    assert parsed.financial_quality.status.value == "PASS"
    assert parsed.financial_quality.discount_reconciles is True
    assert parsed.financial_quality.tax_reconciles is True
    assert parsed.financial_quality.amount_due_reconciles is True


@pytest.mark.parametrize(
    ("parser", "filename"),
    [
        (PdfInvoiceParser(), "equivalent_invoice.pdf"),
        (DocxInvoiceParser(), "equivalent_invoice.docx"),
        (XlsxInvoiceParser(), "equivalent_invoice.xlsx"),
        (JsonInvoiceParser(), "equivalent_invoice.json"),
        (DelimitedInvoiceParser(), "equivalent_invoice.csv"),
        (DelimitedInvoiceParser(), "equivalent_invoice.txt"),
    ],
)
def test_generated_formats_extract_same_full_invoice(parser, filename: str) -> None:
    parsed = parser.parse(EXAMPLES / filename, "testinger", "default-partner")
    assert len(parsed.lines) == 6
    assert parsed.lines[0].description == "Highlife Steel Accessories"
    assert parsed.lines[-1].description == "Socks, black"
    assert all(line.currency == "USD" for line in parsed.lines)
    _assert_context(parsed)


def test_supplied_challenge_invoice_pdf_extracts_full_context() -> None:
    path = ROOT / "data/examples/input/challenge_invoice.pdf"
    parsed = PdfInvoiceParser().parse(path, "testinger", "default-partner")
    assert len(parsed.lines) == 6
    assert [line.quantity for line in parsed.lines] == [1, 2, 3, 4, 5, 6]
    _assert_context(parsed)


def test_pdf_ocr_fallback_is_injected_and_auditable(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "scanned.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF")

    class EmptyPage:
        def extract_text(self, *args, **kwargs):
            del args, kwargs
            return ""

    class EmptyReader:
        pages = [EmptyPage()]

    monkeypatch.setattr("invoice_canonicalizer.infrastructure.documents.pdf_parser.PdfReader", lambda _: EmptyReader())
    text = "DESCRIPTION QTY UNIT PRICE TOTAL\nCotton Cap Sunrise 1 10 10.00\nSUBTOTAL 10.00"
    parsed = PdfInvoiceParser(enable_ocr_fallback=True, ocr_function=lambda _: text).parse(
        path, "testinger", "default-partner"
    )
    assert parsed.parser_name == "pdf-tesseract-ocr"
    assert parsed.warnings == ("ocr_fallback_used",)


def test_pdf_without_text_abstains_when_ocr_disabled(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "scanned.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF")

    class EmptyReader:
        pages = [type("Page", (), {"extract_text": lambda self, *args, **kwargs: ""})()]

    monkeypatch.setattr("invoice_canonicalizer.infrastructure.documents.pdf_parser.PdfReader", lambda _: EmptyReader())
    with pytest.raises(DocumentExtractionError):
        PdfInvoiceParser(enable_ocr_fallback=False).parse(path, "testinger", "default-partner")
