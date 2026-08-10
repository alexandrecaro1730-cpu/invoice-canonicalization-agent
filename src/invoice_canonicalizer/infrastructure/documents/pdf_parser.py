"""Business objective: ingest native-text PDF invoices while retaining parties/header/totals and reserving OCR for genuine fallback cases.

Technical description: uses pypdf native and layout extraction, optionally invokes local OCR, builds InvoiceContext, validates Decimal line arithmetic, and separately reconciles document financials.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from pypdf import PdfReader

from invoice_canonicalizer.domain.errors import DocumentExtractionError
from invoice_canonicalizer.domain.models import ParsedDocument
from invoice_canonicalizer.infrastructure.documents.common import extract_declared_subtotal_from_text, text_to_invoice_lines
from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_extraction_quality, validate_financial_quality
from invoice_canonicalizer.infrastructure.documents.invoice_context import context_from_text
from invoice_canonicalizer.utils.hashing import sha256_file

OcrFunction = Callable[[Path], str]


def tesseract_pdf_ocr(path: Path) -> str:
    """Run a local last-resort OCR path without transmitting document data."""
    with tempfile.TemporaryDirectory(prefix="invoice-ocr-") as directory:
        prefix = Path(directory) / "page"
        subprocess.run(
            ["pdftoppm", "-png", "-r", "150", str(path), str(prefix)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        chunks: list[str] = []
        for image in sorted(Path(directory).glob("page-*.png")):
            result = subprocess.run(
                ["tesseract", str(image), "stdout", "--psm", "6"],
                check=True, capture_output=True, text=True, timeout=60,
            )
            chunks.append(result.stdout)
        return "\n".join(chunks)


class PdfInvoiceParser:
    extensions = (".pdf",)
    name = "pdf-native-text"

    def __init__(self, enable_ocr_fallback: bool = False, ocr_function: OcrFunction | None = None) -> None:
        self.enable_ocr_fallback = enable_ocr_fallback
        self.ocr_function = ocr_function or tesseract_pdf_ocr

    def parse(self, path: Path, tenant_id: str, partner_id: str) -> ParsedDocument:
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        try:
            layout_text = "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
        except (TypeError, ValueError):
            layout_text = text
        warnings: list[str] = []
        parser_name = self.name
        if len(text.strip()) < 40:
            if not self.enable_ocr_fallback:
                raise DocumentExtractionError("PDF contains insufficient native text; OCR fallback is disabled")
            try:
                text = self.ocr_function(path)
            except (subprocess.SubprocessError, OSError) as exc:
                raise DocumentExtractionError(f"OCR fallback failed: {exc}") from exc
            layout_text = text
            warnings.append("ocr_fallback_used")
            parser_name = "pdf-tesseract-ocr"
        context = context_from_text(text, layout_text=layout_text)
        lines = text_to_invoice_lines(
            text, tenant_id, partner_id, "pdf", currency=context.financials.currency
        )
        declared_subtotal = context.financials.subtotal or extract_declared_subtotal_from_text(text)
        quality = validate_extraction_quality(lines, declared_subtotal)
        financial_quality = validate_financial_quality(context.financials)
        return ParsedDocument(
            document_id=sha256_file(path), source_name=path.name, parser_name=parser_name,
            lines=lines, context=context, warnings=tuple(warnings), quality=quality,
            financial_quality=financial_quality,
        )
