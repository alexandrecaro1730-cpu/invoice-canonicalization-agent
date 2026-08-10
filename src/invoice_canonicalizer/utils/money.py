"""Business objective: preserve invoice and cost arithmetic exactly across parsing, storage, and validation.

Technical description: centralizes Decimal conversion, quantization, and JSON-safe formatting so financial values never depend on binary floating-point behavior.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

MONEY_QUANTUM = Decimal("0.01")
FOUR_DP_QUANTUM = Decimal("0.0001")
ZERO = Decimal("0")


def to_decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    """Convert external numeric values through text to avoid float binary artifacts."""
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def money(value: Any) -> Decimal:
    """Return a two-decimal monetary value using standard half-up business rounding."""
    parsed = to_decimal(value, default=ZERO)
    assert parsed is not None
    return parsed.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def decimal_text(value: Decimal | None) -> str | None:
    """Serialize Decimal values without exponent notation for durable JSON/CSV storage."""
    if value is None:
        return None
    return format(value, "f")
