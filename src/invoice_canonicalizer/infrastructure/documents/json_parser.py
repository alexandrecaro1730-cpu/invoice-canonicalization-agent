"""Business objective: support deterministic machine-to-machine invoice ingestion including parties, header, financials, and line items.

Technical description: validates a JSON invoice contract, retains InvoiceContext, converts money to Decimal, and attaches line and financial reconciliation evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from invoice_canonicalizer.domain.errors import DocumentExtractionError
from invoice_canonicalizer.domain.models import InvoiceLine, ParsedDocument
from invoice_canonicalizer.infrastructure.documents.common import parse_decimal
from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_extraction_quality, validate_financial_quality
from invoice_canonicalizer.infrastructure.documents.invoice_context import context_from_json_payload
from invoice_canonicalizer.utils.hashing import sha256_file


class JsonInvoiceParser:
    extensions = (".json",)
    name = "json-contract-v2"

    def parse(self, path: Path, tenant_id: str, partner_id: str) -> ParsedDocument:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            source_lines = payload["lines"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise DocumentExtractionError(f"invalid invoice JSON contract: {exc}") from exc
        context = context_from_json_payload(payload)
        lines: list[InvoiceLine] = []
        for index, row in enumerate(source_lines, start=1):
            try:
                lines.append(InvoiceLine(
                    tenant_id=tenant_id, partner_id=partner_id,
                    description=str(row["description"]), source_line_id=f"json-{index}",
                    quantity=parse_decimal(row.get("quantity")),
                    unit_price=parse_decimal(row.get("unit_price")),
                    total=parse_decimal(row.get("total")),
                    currency=context.financials.currency,
                ))
            except (KeyError, TypeError, ValueError) as exc:
                raise DocumentExtractionError(f"invalid JSON line {index}: {exc}") from exc
        if not lines:
            raise DocumentExtractionError("invoice JSON has no line items")
        quality = validate_extraction_quality(lines, context.financials.subtotal)
        return ParsedDocument(
            document_id=sha256_file(path), source_name=path.name, parser_name=self.name, lines=tuple(lines),
            context=context, quality=quality, financial_quality=validate_financial_quality(context.financials),
        )
