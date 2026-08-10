"""Business objective: prevent untrusted invoice text from becoming model instructions or unsafe output.

Technical description: detects common prompt-injection patterns and validates generated descriptions.
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all|any|the)?\s*(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"reveal\s+.*(secret|database|api\s*key)", re.IGNORECASE),
    re.compile(r"<\s*(script|iframe)", re.IGNORECASE),
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def detect_untrusted_instruction(text: str) -> tuple[str, ...]:
    flags = [f"prompt_injection_pattern_{index + 1}" for index, pattern in enumerate(_INJECTION_PATTERNS) if pattern.search(text)]
    if _CONTROL_CHARACTERS.search(text):
        flags.append("control_characters")
    return tuple(flags)


def validate_generated_description(text: str) -> tuple[str, ...]:
    flags: list[str] = []
    if not text.strip():
        flags.append("empty_generated_description")
    if len(text) > 120:
        flags.append("generated_description_too_long")
    if "http://" in text.lower() or "https://" in text.lower():
        flags.append("generated_description_contains_url")
    if _CONTROL_CHARACTERS.search(text):
        flags.append("generated_description_control_characters")
    return tuple(flags)
