"""Business objective: minimize personal data sent to external model providers.

Technical description: redacts emails, telephone-like strings, and long account-number sequences from text.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s()./-]{7,}\d)(?!\w)")
_LONG_NUMBER = re.compile(r"\b\d{8,}\b")


def redact_pii(text: str) -> str:
    value = _EMAIL.sub("[REDACTED_EMAIL]", text)
    value = _PHONE.sub("[REDACTED_PHONE]", value)
    return _LONG_NUMBER.sub("[REDACTED_NUMBER]", value)
