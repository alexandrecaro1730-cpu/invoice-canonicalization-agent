"""Business objective: ingest Excel invoices including header, parties, line items, and financial totals without a spreadsheet runtime.

Technical description: parses first-sheet OOXML rows, derives InvoiceContext from explicit key/value cells, then validates Decimal line arithmetic and financial reconciliation.
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

_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class XlsxInvoiceParser:
    extensions = (".xlsx",)
    name = "xlsx-ooxml"

    def parse(self, path: Path, tenant_id: str, partner_id: str) -> ParsedDocument:
        with zipfile.ZipFile(path) as archive:
            shared_strings = self._shared_strings(archive)
            sheet_name = "xl/worksheets/sheet1.xml"
            if sheet_name not in archive.namelist():
                raise DocumentExtractionError("XLSX does not contain sheet1.xml")
            root = ET.fromstring(archive.read(sheet_name))
        rows: list[list[str]] = []
        for row in root.findall(".//a:sheetData/a:row", _NS):
            values: list[str] = []
            for cell in row.findall("a:c", _NS):
                cell_type = cell.attrib.get("t")
                if cell_type == "inlineStr":
                    value = "".join(node.text or "" for node in cell.findall(".//a:t", _NS))
                else:
                    node = cell.find("a:v", _NS)
                    raw = node.text if node is not None and node.text is not None else ""
                    value = shared_strings[int(raw)] if cell_type == "s" and raw else raw
                values.append(value)
            rows.append(values)
        context = context_from_rows(rows)
        lines = rows_to_invoice_lines(rows, tenant_id, partner_id, "xlsx", context.financials.currency)
        if not lines:
            raise DocumentExtractionError("XLSX contains no supported invoice table")
        quality = validate_extraction_quality(lines, context.financials.subtotal)
        return ParsedDocument(
            document_id=sha256_file(path), source_name=path.name, parser_name=self.name, lines=lines,
            context=context, quality=quality, financial_quality=validate_financial_quality(context.financials),
        )

    @staticmethod
    def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
        name = "xl/sharedStrings.xml"
        if name not in archive.namelist():
            return []
        root = ET.fromstring(archive.read(name))
        return ["".join(node.text or "" for node in item.findall(".//a:t", _NS)) for item in root.findall("a:si", _NS)]
