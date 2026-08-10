"""Business objective: retain invoice parties, header fields, and financial totals needed for audit, routing, and reconciliation without polluting product canonicalization.

Technical description: extracts a conservative InvoiceContext from structured key/value rows or invoice text/layout, preserving raw address lines and parsing only fields supported by source evidence.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from invoice_canonicalizer.domain.models import InvoiceContext, InvoiceFinancials, InvoiceParty, PartyRole
from invoice_canonicalizer.infrastructure.documents.common import parse_decimal

_DATE_PATTERN = re.compile(r"\b(\d{1,2})[.\-/ ]+([A-Za-zÄÖÜäöü]+|\d{1,2})[.\-/ ]+(\d{4})\b")
_MONTHS = {
    "january": 1, "jan": 1, "januar": 1,
    "february": 2, "feb": 2, "februar": 2,
    "march": 3, "mar": 3, "märz": 3, "maerz": 3,
    "april": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "october": 10, "oct": 10, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12, "dezember": 12, "dez": 12,
}
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
_PERSON_PREFIXES = ("mr ", "mrs ", "ms ", "dr ", "herr ", "frau ")


def parse_invoice_date(value: str | None) -> str | None:
    if not value:
        return None
    match = _DATE_PATTERN.search(value.strip())
    if not match:
        # Accept already normalized ISO values.
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None
    day = int(match.group(1))
    month_token = match.group(2).lower()
    month = int(month_token) if month_token.isdigit() else _MONTHS.get(month_token)
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, day).isoformat()
    except ValueError:
        return None


def _derive_due_date(invoice_date: str | None, payment_terms: str | None) -> str | None:
    if not invoice_date or not payment_terms:
        return None
    match = re.search(r"due\s+in\s+(\d+)\s+days?", payment_terms, re.IGNORECASE)
    if not match:
        return None
    try:
        return (date.fromisoformat(invoice_date) + timedelta(days=int(match.group(1)))).isoformat()
    except ValueError:
        return None


def _clean_phone(value: str) -> str:
    return value.strip().rstrip(",")


def _party_from_items(role: PartyRole, items: Sequence[str]) -> InvoiceParty | None:
    clean = [" ".join(item.split()).strip().rstrip(",") for item in items if item and item.strip()]
    if not clean:
        return None
    contact_name: str | None = None
    if clean[0].lower().startswith(_PERSON_PREFIXES):
        contact_name = clean.pop(0)
    if not clean:
        return None
    name = clean.pop(0)
    address: list[str] = []
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    for item in clean:
        if "@" in item and email is None:
            email = item
        elif re.match(r"^[+()0-9][+()0-9 .\-/]{5,}$", item) and phone is None:
            phone = _clean_phone(item)
        elif "." in item and " " not in item and website is None:
            website = item
        else:
            address.append(item)
    return InvoiceParty(
        role=role,
        name=name,
        contact_name=contact_name,
        address_lines=tuple(address),
        phone=phone,
        email=email,
        website=website,
    )


def _value_after_label(text: str, label: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(label)}\s*[:=]\s*(.*?)\s*$", text)
    return match.group(1).strip() if match else None


def _amount_after_label(text: str, label_pattern: str) -> Decimal | None:
    match = re.search(rf"(?im){label_pattern}\s*[:=]?\s*(?:[$€£¥]\s*)?([-+]?\d[\d.,' ]*)", text)
    if not match:
        return None
    try:
        return parse_decimal(match.group(1))
    except ValueError:
        return None


def _currency_from_text(text: str, explicit: str | None = None) -> str | None:
    if explicit:
        value = explicit.strip().upper()
        return value[:8] if value else None
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    match = re.search(r"(?im)^\s*CURRENCY\s*[:=]\s*([A-Za-z]{3,8})\s*$", text)
    return match.group(1).upper() if match else None


def _financials_from_text(text: str, explicit_currency: str | None = None) -> InvoiceFinancials:
    subtotal = _amount_after_label(text, r"\bSUBTOTAL\b(?!\s+LESS)")
    discount = _amount_after_label(text, r"\bDISCOUNT\b")
    subtotal_after_discount = _amount_after_label(text, r"\bSUBTOTAL\s+(?:LESS(?:\s+DISCOUNT)?|AFTER\s+DISCOUNT)\b")
    tax_total = _amount_after_label(text, r"\bTOTAL\s+TAX\b")
    shipping = _amount_after_label(text, r"\bSHIPPING(?:/HAND(?:LING|\s*LING)?)?\b")
    amount_due = _amount_after_label(text, r"\b(?:AMOUNT\s+DUE|BALANCE(?:\s+DUE)?|DUE)\b")
    rate_match = re.search(r"(?im)\bTAX\s+RATE\b\s*[:=]?\s*([-+]?\d[\d.,' ]*)\s*%", text)
    tax_rate = None
    if rate_match:
        try:
            tax_rate = parse_decimal(rate_match.group(1))
        except ValueError:
            tax_rate = None
    return InvoiceFinancials(
        currency=_currency_from_text(text, explicit_currency),
        subtotal=subtotal,
        discount_total=discount,
        subtotal_after_discount=subtotal_after_discount,
        tax_rate_percent=tax_rate,
        tax_total=tax_total,
        shipping_total=shipping,
        amount_due=amount_due,
    )


def _extract_parties_from_key_values(mapping: dict[str, str]) -> tuple[InvoiceParty, ...]:
    parties: list[InvoiceParty] = []
    for role, prefix in (
        (PartyRole.SELLER, "seller"),
        (PartyRole.BILL_TO, "bill_to"),
        (PartyRole.SHIP_TO, "ship_to"),
    ):
        name = mapping.get(f"{prefix}_name", "").strip()
        if not name:
            continue
        raw_address = mapping.get(f"{prefix}_address", "")
        address_lines = tuple(part.strip() for part in raw_address.split("|") if part.strip())
        parties.append(InvoiceParty(
            role=role,
            name=name,
            contact_name=mapping.get(f"{prefix}_contact") or None,
            address_lines=address_lines,
            phone=mapping.get(f"{prefix}_phone") or None,
            email=mapping.get(f"{prefix}_email") or None,
            website=mapping.get(f"{prefix}_website") or None,
            external_id=mapping.get(f"{prefix}_external_id") or None,
        ))
    return tuple(parties)


def context_from_rows(rows: Iterable[Sequence[str]]) -> InvoiceContext:
    """Parse explicit key/value invoice metadata used by machine-readable CSV/XLSX/DOCX fixtures."""
    mapping: dict[str, str] = {}
    for row in rows:
        cells = [str(cell).strip() for cell in row]
        if not cells:
            continue
        key = cells[0].strip().lower().replace(" ", "_")
        if key in {"description", "subtotal", "discount", "subtotal_after_discount", "tax_rate_percent", "tax_total", "shipping_total", "amount_due"}:
            # Financial rows are accepted below, line-table header marks end of metadata header.
            pass
        if len(cells) >= 2 and key:
            value = next((cell for cell in cells[1:] if cell), "")
            if value:
                mapping[key] = value

    invoice_date = parse_invoice_date(mapping.get("invoice_date"))
    payment_terms = mapping.get("payment_terms") or None
    financials = InvoiceFinancials(
        currency=mapping.get("currency") or None,
        subtotal=parse_decimal(mapping.get("subtotal")) if mapping.get("subtotal") else None,
        discount_total=parse_decimal(mapping.get("discount")) if mapping.get("discount") else None,
        subtotal_after_discount=parse_decimal(mapping.get("subtotal_after_discount")) if mapping.get("subtotal_after_discount") else None,
        tax_rate_percent=parse_decimal(mapping.get("tax_rate_percent")) if mapping.get("tax_rate_percent") else None,
        tax_total=parse_decimal(mapping.get("tax_total")) if mapping.get("tax_total") else None,
        shipping_total=parse_decimal(mapping.get("shipping_total")) if mapping.get("shipping_total") else None,
        amount_due=parse_decimal(mapping.get("amount_due")) if mapping.get("amount_due") else None,
    )
    return InvoiceContext(
        invoice_number=mapping.get("invoice_number") or None,
        invoice_date=invoice_date,
        due_date=parse_invoice_date(mapping.get("due_date")) or _derive_due_date(invoice_date, payment_terms),
        payment_terms=payment_terms,
        parties=_extract_parties_from_key_values(mapping),
        financials=financials,
    )


def _context_from_explicit_text(text: str) -> InvoiceContext | None:
    keys = (
        "invoice_number", "invoice_date", "payment_terms", "currency",
        "seller_name", "seller_contact", "seller_address", "seller_phone", "seller_email", "seller_website",
        "bill_to_name", "bill_to_contact", "bill_to_address", "bill_to_phone", "bill_to_email", "bill_to_website",
        "ship_to_name", "ship_to_contact", "ship_to_address", "ship_to_phone", "ship_to_email", "ship_to_website",
    )
    mapping: dict[str, str] = {}
    for key in keys:
        label = key.replace("_", " ").upper()
        value = _value_after_label(text, label)
        if value:
            mapping[key] = value
    if not mapping:
        return None
    invoice_date = parse_invoice_date(mapping.get("invoice_date"))
    payment_terms = mapping.get("payment_terms") or None
    return InvoiceContext(
        invoice_number=mapping.get("invoice_number"),
        invoice_date=invoice_date,
        due_date=_derive_due_date(invoice_date, payment_terms),
        payment_terms=payment_terms,
        parties=_extract_parties_from_key_values(mapping),
        financials=_financials_from_text(text, mapping.get("currency")),
    )


def context_from_text(text: str, *, layout_text: str | None = None) -> InvoiceContext:
    """Extract conservative invoice metadata; layout_text enables three-column party recovery from PDFs."""
    explicit = _context_from_explicit_text(text)
    if explicit is not None:
        return explicit

    source = layout_text or text
    invoice_date = None
    for line in source.splitlines()[:30]:
        invoice_date = parse_invoice_date(line)
        if invoice_date:
            break
    invoice_number = None
    # Prefer a long numeric identifier near the header; avoid money and phone numbers.
    for line in source.splitlines()[:35]:
        stripped = line.strip()
        if re.fullmatch(r"\d{8,20}", stripped):
            invoice_number = stripped
            break
    terms_match = re.search(r"(?im)\bDue\s+in\s+\d+\s+days?\b", source)
    payment_terms = terms_match.group(0) if terms_match else None
    parties = _parties_from_layout(source)
    financials = _financials_from_text(source)
    return InvoiceContext(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=_derive_due_date(invoice_date, payment_terms),
        payment_terms=payment_terms,
        parties=parties,
        financials=financials,
    )


def _parties_from_layout(layout_text: str) -> tuple[InvoiceParty, ...]:
    lines = layout_text.splitlines()
    header_index = -1
    bill_pos = ship_pos = -1
    for index, line in enumerate(lines):
        if "BILL TO" in line and "SHIP TO" in line:
            header_index = index
            bill_pos = line.index("BILL TO")
            ship_pos = line.index("SHIP TO")
            break
    if header_index < 0 or bill_pos <= 0 or ship_pos <= bill_pos:
        return ()
    seller_items: list[str] = []
    bill_items: list[str] = []
    ship_items: list[str] = []
    header_seller = lines[header_index][:bill_pos].strip()
    if header_seller:
        seller_items.append(header_seller)
    for line in lines[header_index + 1:]:
        padded = line.rstrip("\n")
        seller = padded[:bill_pos].strip() if len(padded) > 0 else ""
        if "DESCRIPTION" in line and ("QTY" in line or "QUANTITY" in line):
            if seller:
                seller_items.append(seller)
            break
        bill = padded[bill_pos:ship_pos].strip() if len(padded) > bill_pos else ""
        ship = padded[ship_pos:].strip() if len(padded) > ship_pos else ""
        if seller:
            seller_items.append(seller)
        if bill:
            bill_items.append(bill)
        if ship:
            ship_items.append(ship)
    parties = [
        _party_from_items(PartyRole.SELLER, seller_items),
        _party_from_items(PartyRole.BILL_TO, bill_items),
        _party_from_items(PartyRole.SHIP_TO, ship_items),
    ]
    return tuple(party for party in parties if party is not None)


def context_from_json_payload(payload: dict[str, object]) -> InvoiceContext:
    """Parse the explicit JSON invoice contract without flattening party/address structure."""
    header = payload.get("invoice") if isinstance(payload.get("invoice"), dict) else payload
    assert isinstance(header, dict)
    invoice_date = parse_invoice_date(str(header.get("invoice_date") or ""))
    payment_terms = str(header.get("payment_terms") or "").strip() or None
    raw_parties = header.get("parties", payload.get("parties", []))
    parties: list[InvoiceParty] = []
    if isinstance(raw_parties, list):
        for raw in raw_parties:
            if not isinstance(raw, dict) or not raw.get("name") or not raw.get("role"):
                continue
            try:
                role = PartyRole(str(raw["role"]))
            except ValueError:
                continue
            address = raw.get("address_lines", [])
            if not isinstance(address, list):
                address = []
            parties.append(InvoiceParty(
                role=role,
                name=str(raw["name"]),
                contact_name=str(raw.get("contact_name") or "").strip() or None,
                address_lines=tuple(str(item) for item in address if str(item).strip()),
                phone=str(raw.get("phone") or "").strip() or None,
                email=str(raw.get("email") or "").strip() or None,
                website=str(raw.get("website") or "").strip() or None,
                external_id=str(raw.get("external_id") or "").strip() or None,
            ))
    raw_financials = header.get("financials", payload.get("financials", {}))
    if not isinstance(raw_financials, dict):
        raw_financials = {}
    # Backward compatibility with the compact v1 fixture fields.
    currency = raw_financials.get("currency") or header.get("currency") or payload.get("currency")
    subtotal = raw_financials.get("subtotal") or header.get("subtotal") or payload.get("subtotal")
    financials = InvoiceFinancials(
        currency=str(currency) if currency else None,
        subtotal=parse_decimal(str(subtotal)) if subtotal is not None else None,
        discount_total=parse_decimal(raw_financials.get("discount_total")) if raw_financials.get("discount_total") is not None else None,
        subtotal_after_discount=parse_decimal(raw_financials.get("subtotal_after_discount")) if raw_financials.get("subtotal_after_discount") is not None else None,
        tax_rate_percent=parse_decimal(raw_financials.get("tax_rate_percent")) if raw_financials.get("tax_rate_percent") is not None else None,
        tax_total=parse_decimal(raw_financials.get("tax_total")) if raw_financials.get("tax_total") is not None else None,
        shipping_total=parse_decimal(raw_financials.get("shipping_total")) if raw_financials.get("shipping_total") is not None else None,
        amount_due=parse_decimal(raw_financials.get("amount_due")) if raw_financials.get("amount_due") is not None else None,
    )
    return InvoiceContext(
        invoice_number=str(header.get("invoice_number") or payload.get("invoice_number") or "").strip() or None,
        invoice_date=invoice_date,
        due_date=parse_invoice_date(str(header.get("due_date") or "")) or _derive_due_date(invoice_date, payment_terms),
        payment_terms=payment_terms,
        parties=tuple(parties),
        financials=financials,
    )
