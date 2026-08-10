"""Business objective: ensure every executable module and prompt explains its purpose to reviewers.

Technical description: scans Python, SQL, YAML, TOML, Docker, and prompt files for required documentation markers.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIRS = (ROOT / "src", ROOT / "tests", ROOT / "scripts")
TEXT_PATTERNS = {
    ".py": ("Business objective:", "Technical description:"),
    ".sql": ("Business objective:", "Technical description:"),
    ".yaml": ("Business objective:", "Technical description:"),
    ".yml": ("Business objective:", "Technical description:"),
    ".txt": ("Business objective:", "Technical description:"),
    ".toml": ("Business objective:", "Technical description:"),
}
EXCLUDED = {ROOT / ".gitignore", ROOT / ".dockerignore"}


def main() -> int:
    failures: list[str] = []
    candidates: list[Path] = []
    for directory in PYTHON_DIRS:
        candidates.extend(directory.rglob("*.py"))
    candidates.extend((ROOT / "prompts").rglob("*.txt"))
    candidates.extend((ROOT / "migrations").rglob("*.sql"))
    candidates.extend((ROOT / "config").rglob("*.yaml"))
    candidates.extend((ROOT / ".github" / "workflows").rglob("*.yml"))
    candidates.extend([ROOT / "pyproject.toml", ROOT / "architecture_manifest.yaml"])
    for path in sorted(set(candidates)):
        if path in EXCLUDED:
            continue
        markers = TEXT_PATTERNS.get(path.suffix)
        if not markers:
            continue
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            failures.append(f"{path.relative_to(ROOT)} missing {missing}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Documentation gate passed for {len(set(candidates))} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
