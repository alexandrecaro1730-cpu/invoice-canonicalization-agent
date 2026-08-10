"""Business objective: extract product rows consistently from heterogeneous invoice representations.

Technical description: normalizes tabular rows and free text into Decimal-safe InvoiceLine records and extracts declared subtotal evidence for quality validation.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

from invoice_canonicalizer.domain.errors import DocumentExtractionError
from invoice_canonicalizer.domain.models import InvoiceLine

_ROW_PATTERN = re.compile(
    r"^\s*(?P<description>.+?)\s+(?P<quantity>[-+]?\d[\d.,' ]*)\s+"
    r"(?P<unit_price>[-+]?\d[\d.,' ]*)\s+(?P<total>[-+]?\d[\d.,' ]*)\s*$"
)
_STOP_WORDS = ("subtotal", "discount", "tax rate", "total tax", "balance due", "shipping")
_HEADER_WORDS = {"description", "qty", "quantity", "unit price", "total"}
_NUMBER_TOKEN = re.compile(r"[-+]?\d[\d.,' ]*")


def parse_decimal(value: str | int | float | Decimal | None) -> Decimal | None:
    """Parse common US/EU formatted numbers without ever round-tripping through float.

    When both separators occur, the right-most separator is treated as the decimal mark:
    ``1,234.56`` and ``1.234,56`` therefore both become ``1234.56``.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    cleaned = str(value).strip().replace(" ", "").replace("'", "")
    cleaned = re.sub(r"[^0-9,\.\-+]", "", cleaned)
    if not cleaned or cleaned in {"-", "+", ".", ","}:
        raise ValueError(f"invalid numeric value: {value!r}")

    comma = cleaned.rfind(",")
    dot = cleaned.rfind(".")
    if comma >= 0 and dot >= 0:
        decimal_mark = "," if comma > dot else "."
        thousands_mark = "." if decimal_mark == "," else ","
        cleaned = cleaned.replace(thousands_mark, "")
        if decimal_mark == ",":
            cleaned = cleaned.replace(",", ".")
    elif comma >= 0:
        # Multiple groups of exactly three digits are treated as thousands; a single comma is
        # interpreted as decimal because EU invoices commonly use values such as 12,50.
        groups = cleaned.split(",")
        if len(groups) > 2 and all(len(group) == 3 for group in groups[1:]):
            cleaned = "".join(groups)
        else:
            cleaned = cleaned.replace(",", ".")
    elif dot >= 0:
        groups = cleaned.split(".")
        if len(groups) > 2 and all(len(group) == 3 for group in groups[1:]):
            cleaned = "".join(groups)
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc


def extract_declared_subtotal_from_rows(rows: Iterable[Sequence[str]]) -> Decimal | None:
    """Return the first plain subtotal row, excluding discount/tax variants."""
    for row in rows:
        cells = [str(cell).strip() for cell in row]
        if not cells:
            continue
        label = cells[0].lower().strip()
        if label != "subtotal":
            continue
        for cell in reversed(cells[1:]):
            if not cell:
                continue
            try:
                return parse_decimal(cell)
            except ValueError:
                continue
    return None


def extract_declared_subtotal_from_text(text: str) -> Decimal | None:
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line.lower().startswith("subtotal"):
            continue
        # Reject variants such as "SUBTOTAL LESS DISCOUNT".
        if line.lower().startswith("subtotal less"):
            continue
        values = _NUMBER_TOKEN.findall(line[len("subtotal"):])
        for token in reversed(values):
            try:
                return parse_decimal(token)
            except ValueError:
                continue
    return None


def rows_to_invoice_lines(
    rows: Iterable[Sequence[str]],
    tenant_id: str,
    partner_id: str,
    source_prefix: str,
    currency: str | None = None,
) -> tuple[InvoiceLine, ...]:
    lines: list[InvoiceLine] = []
    for raw_index, row in enumerate(rows, start=1):
        cells = [str(cell).strip() for cell in row]
        if not any(cells):
            continue
        lowered = [cell.lower() for cell in cells]
        if any(cell in _HEADER_WORDS for cell in lowered):
            continue
        first = cells[0].lower() if cells else ""
        if any(first.startswith(word) for word in _STOP_WORDS):
            break
        if len(cells) >= 4 and cells[0]:
            try:
                quantity = parse_decimal(cells[1])
                unit_price = parse_decimal(cells[2])
                total = parse_decimal(cells[3])
            except ValueError:
                continue
            lines.append(InvoiceLine(
                tenant_id=tenant_id, partner_id=partner_id, description=cells[0],
                source_line_id=f"{source_prefix}-{raw_index}", quantity=quantity,
                unit_price=unit_price, total=total, currency=currency,
            ))
    return tuple(lines)


def text_to_invoice_lines(
    text: str,
    tenant_id: str,
    partner_id: str,
    source_prefix: str,
    currency: str | None = None,
) -> tuple[InvoiceLine, ...]:
    normalized_lines = [" ".join(line.split()) for line in text.splitlines()]
    results: list[InvoiceLine] = []
    in_table = False
    for raw_index, line in enumerate(normalized_lines, start=1):
        lower = line.lower()
        if "description" in lower and ("qty" in lower or "quantity" in lower) and "total" in lower:
            in_table = True
            trailing = re.split(r"\bdescription\b.*?\btotal\b", line, maxsplit=1, flags=re.IGNORECASE)
            if len(trailing) == 2 and trailing[1].strip():
                line = trailing[1].strip()
                lower = line.lower()
            else:
                continue
        if not in_table:
            continue
        if any(lower.startswith(word) for word in _STOP_WORDS):
            break
        match = _ROW_PATTERN.match(line)
        if not match:
            continue
        description = match.group("description").strip()
        if not description:
            continue
        results.append(InvoiceLine(
            tenant_id=tenant_id, partner_id=partner_id, description=description,
            source_line_id=f"{source_prefix}-{raw_index}",
            quantity=parse_decimal(match.group("quantity")),
            unit_price=parse_decimal(match.group("unit_price")),
            total=parse_decimal(match.group("total")), currency=currency,
        ))
    if results:
        return tuple(results)

    # Some PDF generators expose each visual table cell as a separate text line.
    compact = [line for line in normalized_lines if line]
    try:
        start = next(index for index, value in enumerate(compact) if value.lower() == "description")
    except StopIteration as exc:
        raise DocumentExtractionError("no invoice line-item table could be extracted") from exc
    header_end = start
    for index in range(start, min(start + 8, len(compact))):
        if compact[index].lower() == "total":
            header_end = index
            break
    cursor = header_end + 1
    vertical_results: list[InvoiceLine] = []
    while cursor < len(compact):
        description = compact[cursor]
        if any(description.lower().startswith(word) for word in _STOP_WORDS):
            break
        if cursor + 3 >= len(compact):
            break
        numeric = compact[cursor + 1:cursor + 4]
        try:
            quantity, unit_price, total = (parse_decimal(value) for value in numeric)
        except ValueError:
            cursor += 1
            continue
        vertical_results.append(InvoiceLine(
            tenant_id=tenant_id, partner_id=partner_id, description=description,
            source_line_id=f"{source_prefix}-vertical-{cursor}", quantity=quantity,
            unit_price=unit_price, total=total, currency=currency,
        ))
        cursor += 4
    if not vertical_results:
        raise DocumentExtractionError("no invoice line-item table could be extracted")
    return tuple(vertical_results)
