"""Business objective: provide the smallest useful plaintext representation for the optional model extraction fallback.

Technical description: extracts local text from supported formats, redacts obvious PII, narrows around invoice-item regions, and caps prompt size before any external provider call.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from invoice_canonicalizer.infrastructure.documents.pdf_parser import tesseract_pdf_ocr
from invoice_canonicalizer.security.pii import redact_pii

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_X = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def extract_raw_text(path: Path, *, enable_ocr: bool = False) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        if len(text.strip()) < 40 and enable_ocr:
            text = tesseract_pdf_ocr(path)
        return text
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        return "\n".join(node.text or "" for node in root.iter(f"{_W}t"))
    if suffix == ".xlsx":
        with zipfile.ZipFile(path) as archive:
            shared = _xlsx_shared_strings(archive)
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        values: list[str] = []
        for cell in root.findall(".//a:c", _X):
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                values.append("".join(node.text or "" for node in cell.findall(".//a:t", _X)))
            else:
                node = cell.find("a:v", _X)
                raw = node.text if node is not None and node.text is not None else ""
                values.append(shared[int(raw)] if cell_type == "s" and raw else raw)
        return "\n".join(values)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return path.read_text(encoding="utf-8-sig", errors="replace")


def minimize_invoice_text(text: str, max_chars: int) -> str:
    """Prefer the line-item region and remove common PII before bounded model use."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lower = [line.lower() for line in lines]
    start = 0
    for index, line in enumerate(lower):
        if "description" in line or "purchased item" in line or "line item" in line:
            start = max(0, index - 2)
            break
    end = len(lines)
    for index in range(start, len(lines)):
        if lower[index].startswith("subtotal") or lower[index].startswith("balance due"):
            end = min(len(lines), index + 2)
            break
    segment = "\n".join(lines[start:end])
    if not segment:
        segment = text
    return redact_pii(segment)[:max_chars]


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    name = "xl/sharedStrings.xml"
    if name not in archive.namelist():
        return []
    root = ET.fromstring(archive.read(name))
    return ["".join(node.text or "" for node in item.findall(".//a:t", _X)) for item in root.findall("a:si", _X)]
