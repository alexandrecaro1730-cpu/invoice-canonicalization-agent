"""Business objective: reject unsafe or unsupported invoice uploads before parsing.

Technical description: applies extension, path, size, and magic-byte checks using an allow-list.
"""

from __future__ import annotations

from pathlib import Path

from invoice_canonicalizer.domain.errors import UnsupportedDocumentError, ValidationError

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".json", ".txt", ".csv"}
_MAGIC = {
    ".pdf": b"%PDF",
    ".docx": b"PK",
    ".xlsx": b"PK",
}


def validate_document_path(path: Path, max_file_size_bytes: int) -> None:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ValidationError(f"document does not exist: {path}")
    suffix = resolved.suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise UnsupportedDocumentError(f"unsupported extension: {suffix}")
    size = resolved.stat().st_size
    if size <= 0:
        raise ValidationError("document is empty")
    if size > max_file_size_bytes:
        raise ValidationError(f"document exceeds {max_file_size_bytes} bytes")
    expected = _MAGIC.get(suffix)
    if expected:
        with resolved.open("rb") as handle:
            actual = handle.read(len(expected))
        if actual != expected:
            raise ValidationError(f"file signature does not match extension {suffix}")
