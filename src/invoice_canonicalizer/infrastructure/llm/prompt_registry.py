"""Business objective: version and test every prompt used in invoice canonicalization.

Technical description: loads text templates, validates metadata and placeholders, and renders deterministic prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Formatter

from invoice_canonicalizer.domain.errors import ValidationError
from invoice_canonicalizer.utils.hashing import sha256_text

_REQUIRED_METADATA = ("# Business objective:", "# Technical description:")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    body: str
    version: str
    placeholders: tuple[str, ...]

    def render(self, **values: object) -> str:
        missing = sorted(set(self.placeholders) - set(values))
        if missing:
            raise ValidationError(f"missing prompt values for {self.name}: {missing}")
        return self.body.format(**values)


class PromptRegistry:
    def __init__(self, prompt_dir: Path) -> None:
        self.prompt_dir = prompt_dir
        self._cache: dict[str, PromptTemplate] = {}

    def load(self, relative_path: str) -> PromptTemplate:
        if relative_path in self._cache:
            return self._cache[relative_path]
        path = (self.prompt_dir / relative_path).resolve()
        if not path.is_relative_to(self.prompt_dir.resolve()):
            raise ValidationError("prompt path escapes configured prompt directory")
        text = path.read_text(encoding="utf-8")
        for marker in _REQUIRED_METADATA:
            if marker not in text:
                raise ValidationError(f"prompt {relative_path} is missing metadata marker: {marker}")
        if "\n---\n" not in text:
            raise ValidationError(f"prompt {relative_path} must separate metadata with ---")
        _, body = text.split("\n---\n", 1)
        placeholders = tuple(sorted({field for _, field, _, _ in Formatter().parse(body) if field}))
        template = PromptTemplate(
            name=relative_path,
            body=body.strip(),
            version=sha256_text(text)[:12],
            placeholders=placeholders,
        )
        self._cache[relative_path] = template
        return template
