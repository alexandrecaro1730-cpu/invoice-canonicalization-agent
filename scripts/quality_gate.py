"""Business objective: give reviewers one command that proves the solution is release-ready without leaking build-environment details.

Technical description: runs lock consistency, lint, type checks, compilation, documentation, architecture, completeness, secret/tests/coverage/evaluation, packaging, Docker checks, then sanitizes all textual reports.
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
_TEXT_REPORT_SUFFIXES = {".json", ".md", ".html", ".xml", ".txt", ".csv", ".log"}
_SENSITIVE_PATTERNS = (
    "/mnt/data/",
    "pypi.hub.",
    "packages.hub.",
    str(ROOT),
    str(Path(sys.prefix).resolve()),
)
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


@dataclass(slots=True)
class GateResult:
    name: str
    status: str
    duration_seconds: float
    command: str
    details: str


def _sanitize(text: str) -> str:
    sanitized = text.replace(str(ROOT), "<PROJECT_ROOT>")
    sanitized = sanitized.replace(str(Path(sys.prefix).resolve()), "<PYTHON_ENV>")
    sanitized = sanitized.replace("/mnt/data/", "<WORKSPACE>/")
    lines: list[str] = []
    for line in sanitized.splitlines():
        if line.lower().startswith("looking in indexes:"):
            lines.append("Looking in indexes: <REDACTED_PACKAGE_INDEX>")
            continue
        if "pypi.hub." in line or "packages.hub." in line:
            line = _URL_RE.sub("<REDACTED_URL>", line)
        lines.append(line)
    return "\n".join(lines)


def _display_command(command: list[str]) -> str:
    rendered = list(command)
    if rendered and Path(rendered[0]).resolve() == Path(sys.executable).resolve():
        rendered[0] = "python"
    return _sanitize(" ".join(rendered))


def run_gate(name: str, command: list[str], required: bool = True, env: dict[str, str] | None = None) -> GateResult:
    started = time.perf_counter()
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    duration = time.perf_counter() - started
    output = _sanitize((process.stdout + process.stderr).strip())
    status = "PASS" if process.returncode == 0 else ("FAIL" if required else "WARN")
    return GateResult(name, status, round(duration, 3), _display_command(command), output[-8000:])



def static_tool_gate(name: str, module: str, args: list[str]) -> GateResult:
    """Run Ruff/mypy when installed; CI can require them while constrained sandboxes report an explicit SKIP."""
    required = os.getenv("REQUIRE_STATIC_TOOLS") == "1"
    if importlib.util.find_spec(module) is None:
        return GateResult(
            name,
            "FAIL" if required else "SKIP",
            0.0,
            f"python -m {module} {' '.join(args)}",
            f"{module} is not installed in this execution environment; CI sets REQUIRE_STATIC_TOOLS=1",
        )
    return run_gate(name, [sys.executable, "-m", module, *args], required=required)


def docker_gate() -> GateResult:
    required = os.getenv("REQUIRE_DOCKER") == "1"
    if shutil.which("docker") is None:
        return GateResult("docker_build", "FAIL" if required else "SKIP", 0.0, "docker build", "Docker engine is not installed")
    return run_gate("docker_build", ["docker", "build", "-t", "invoice-canonicalizer:quality", "."], required=required)


def sanitize_existing_reports() -> None:
    if not REPORTS.exists():
        return
    for path in REPORTS.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_REPORT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        path.write_text(_sanitize(text), encoding="utf-8")


def report_sanitization_gate() -> GateResult:
    started = time.perf_counter()
    leaks: list[str] = []
    for path in REPORTS.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_REPORT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in _SENSITIVE_PATTERNS:
            if pattern and pattern in text:
                leaks.append(f"{path.relative_to(ROOT)} contains {pattern!r}")
    return GateResult(
        "report_sanitization",
        "PASS" if not leaks else "FAIL",
        round(time.perf_counter() - started, 3),
        "internal report leak scan",
        "No build-environment paths or private package-index hosts found" if not leaks else "\n".join(leaks),
    )


def write_reports(results: list[GateResult]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    overall = "PASS" if all(item.status in {"PASS", "SKIP", "WARN"} for item in results) else "FAIL"
    payload = {"overall": overall, "results": [asdict(item) for item in results]}
    (REPORTS / "quality_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# Quality Gate: {overall}", "", "| Gate | Status | Seconds |", "|---|---:|---:|"]
    lines.extend(f"| {item.name} | {item.status} | {item.duration_seconds:.3f} |" for item in results)
    lines.extend(["", "## Details"])
    for item in results:
        lines.extend(["", f"### {item.name} - {item.status}", "```text", item.details or "No output", "```"])
    (REPORTS / "quality_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = "".join(
        f"<tr><td>{html.escape(item.name)}</td><td>{item.status}</td><td>{item.duration_seconds:.3f}</td></tr>"
        for item in results
    )
    details = "".join(
        f"<h2>{html.escape(item.name)} - {item.status}</h2><pre>{html.escape(item.details or 'No output')}</pre>"
        for item in results
    )
    document = f"""<!doctype html><html><head><meta charset='utf-8'><title>Quality Gate</title>
<style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:8px;text-align:left}}pre{{white-space:pre-wrap;background:#f4f4f4;padding:12px}}</style></head>
<body><h1>Quality Gate: {overall}</h1><table><tr><th>Gate</th><th>Status</th><th>Seconds</th></tr>{rows}</table>{details}</body></html>"""
    (REPORTS / "quality_summary.html").write_text(document, encoding="utf-8")


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    results = [
        run_gate("lockfile", [python, "scripts/validate_lockfile.py"]),
        static_tool_gate("ruff", "ruff", ["check", "src", "tests", "scripts"]),
        static_tool_gate("mypy", "mypy", ["src/invoice_canonicalizer"]),
        run_gate("static_contract", [python, "scripts/static_contract.py"]),
        run_gate("compile", [python, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        run_gate("documentation", [python, "scripts/validate_documentation.py"]),
        run_gate("architecture", [python, "scripts/validate_architecture.py"]),
        run_gate("completeness", [python, "scripts/completeness_audit.py"]),
        run_gate("secret_scan", [python, "scripts/secret_scan.py"]),
        run_gate("tests_with_coverage", [python, "-m", "coverage", "run", "-m", "pytest", "-q"]),
        run_gate("coverage_threshold", [python, "-m", "coverage", "report", "--fail-under=80"]),
        run_gate("coverage_xml", [python, "-m", "coverage", "xml", "-o", "reports/coverage.xml"]),
        run_gate("offline_evaluation", [python, "scripts/run_evaluation.py"]),
        run_gate("interview_demo", [python, "scripts/interview_demo.py"]),
        run_gate("package_build", [python, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "--wheel-dir", "reports/wheels"]),
        run_gate("wheel_install_smoke", [python, "scripts/wheel_smoke.py"]),
        docker_gate(),
    ]
    sanitize_existing_reports()
    results.append(report_sanitization_gate())
    write_reports(results)
    overall = "PASS" if all(item.status in {"PASS", "SKIP", "WARN"} for item in results) else "FAIL"
    print("\nPRODUCTION QUALITY GATE")
    print("=" * 72)
    for item in results:
        print(f"{item.name:<28} {item.status:<5} {item.duration_seconds:>8.3f}s")
    print("=" * 72)
    print(f"OVERALL: {overall}")
    print("Reports: reports/quality_summary.html")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
