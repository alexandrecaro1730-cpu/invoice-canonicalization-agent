"""Business objective: ingest Word invoices including business parties and totals without layout-specific Office automation.

Technical description: reads DOCX OOXML table rows, derives InvoiceContext from explicit metadata rows, and validates line/financial Decimal relationships.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from invoice_canonicalizer.domain.errors import DocumentExtractionError
from invoice_canonicalizer.domain.models import ParsedDocument
from invoice_canonicalizer.infrastructure.documents.common import rows_to_invoice_lines
from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_extraction_quality, validate_financial_quality
from invoice_canonicalizer.infrastructure.documents.invoice_context import context_from_rows
from invoice_canonicalizer.utils.hashing import sha256_file

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxInvoiceParser:
    extensions = (".docx",)
    name = "docx-ooxml"

    def parse(self, path: Path, tenant_id: str, partner_id: str) -> ParsedDocument:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        rows: list[list[str]] = []
        for table_row in root.iter(f"{_W}tr"):
            cells: list[str] = []
            for cell in table_row.findall(f"{_W}tc"):
                text = "".join(node.text or "" for node in cell.iter(f"{_W}t"))
                cells.append(text.strip())
            rows.append(cells)
        context = context_from_rows(rows)
        lines = rows_to_invoice_lines(rows, tenant_id, partner_id, "docx", context.financials.currency)
        if not lines:
            raise DocumentExtractionError("DOCX contains no supported invoice table")
        quality = validate_extraction_quality(lines, context.financials.subtotal)
        return ParsedDocument(
            document_id=sha256_file(path), source_name=path.name, parser_name=self.name, lines=lines,
            context=context, quality=quality, financial_quality=validate_financial_quality(context.financials),
        )
