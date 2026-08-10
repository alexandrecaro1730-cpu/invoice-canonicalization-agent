"""Business objective: prevent credentials and private keys from being packaged or committed.

Technical description: applies deterministic high-signal patterns while excluding generated and binary fixture content.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "generic_assignment": re.compile(r"(?i)(api[_-]?key|secret|password)\s*[=:]\s*['\"][^'\"]{12,}['\"]"),
}
SKIP_PARTS = {".git", ".runtime", ".venv", "reports", "__pycache__", "build", "dist"}
BINARY_SUFFIXES = {".pdf", ".docx", ".xlsx", ".png", ".zip", ".db"}
ALLOWED_PLACEHOLDERS = {"OPENAI_API_KEY=replace_only_in_secret_manager"}


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or any(part in SKIP_PARTS or part.endswith(".egg-info") for part in path.parts)
            or path.suffix.lower() in BINARY_SUFFIXES
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                if any(placeholder in match.group(0) for placeholder in ALLOWED_PLACEHOLDERS):
                    continue
                findings.append(f"{path.relative_to(ROOT)}:{name}:{match.group(0)[:40]}")
    if findings:
        print("\n".join(findings))
        return 1
    print("Secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
