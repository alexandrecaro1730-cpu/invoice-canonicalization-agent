"""Business objective: support CSV/TXT invoices with explicit header/party/financial metadata plus product rows.

Technical description: parses delimited key/value and line-item rows with csv.Sniffer, derives InvoiceContext, and validates Decimal line and document totals.
"""

from __future__ import annotations

import csv
from pathlib import Path

from invoice_canonicalizer.domain.errors import DocumentExtractionError
from invoice_canonicalizer.domain.models import ParsedDocument
from invoice_canonicalizer.infrastructure.documents.common import rows_to_invoice_lines
from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_extraction_quality, validate_financial_quality
from invoice_canonicalizer.infrastructure.documents.invoice_context import context_from_rows
from invoice_canonicalizer.utils.hashing import sha256_file


class DelimitedInvoiceParser:
    extensions = (".csv", ".txt")
    name = "delimited-text"

    def parse(self, path: Path, tenant_id: str, partner_id: str) -> ParsedDocument:
        text = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(text.splitlines(), dialect))
        context = context_from_rows(rows)
        lines = rows_to_invoice_lines(rows, tenant_id, partner_id, "text", context.financials.currency)
        if not lines:
            raise DocumentExtractionError("delimited file contains no supported invoice rows")
        quality = validate_extraction_quality(lines, context.financials.subtotal)
        return ParsedDocument(
            document_id=sha256_file(path), source_name=path.name, parser_name=self.name, lines=lines,
            context=context, quality=quality, financial_quality=validate_financial_quality(context.financials),
        )
