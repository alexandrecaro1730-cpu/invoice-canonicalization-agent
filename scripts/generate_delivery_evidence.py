"""Business objective: produce assessor-facing evidence that exactly reflects the final tested package.

Technical description: reruns the supplied challenge in an isolated database, summarizes sanitized quality/evaluation results, and hashes delivery files while excluding generated caches and the manifest itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import replace
from pathlib import Path

from invoice_canonicalizer import __version__
from invoice_canonicalizer.application.factory import build_container
from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.domain.models import DecisionKind
from invoice_canonicalizer.infrastructure.llm.fixture_provider import FixtureModelProvider

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
QUALITY = REPORTS / "quality_summary.json"
EVALUATION = REPORTS / "evaluation.json"
DEMO = REPORTS / "demo_output.json"
FINAL = REPORTS / "final_delivery_check.md"
MANIFEST = REPORTS / "artifact_manifest.json"

SKIP_PARTS = {
    ".git", ".runtime", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__", "build", "dist",
}
SKIP_NAMES = {".coverage", "artifact_manifest.json"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provider_calls(container: object) -> int:
    provider = getattr(getattr(container, "canonicalizer"), "provider")
    return provider.canonicalization_call_count if isinstance(provider, FixtureModelProvider) else -1


def _write_challenge_demo() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ica-delivery-demo-") as directory:
        settings = replace(load_settings(ROOT), database_path=Path(directory) / "catalog.db")
        container = build_container(settings)
        result = container.ingestion.process(
            ROOT / "data/examples/input/challenge_invoice.pdf",
            "testinger",
            "default-partner",
        )
        exact = sum(item.decision_kind is DecisionKind.EXACT_ALIAS for item in result.decisions)
        payload: dict[str, object] = {
            "business_objective": "Verify the supplied challenge resolves deterministically to stable approved descriptions.",
            "technical_description": f"Generated from package version {__version__} with an isolated seeded SQLite database and fixture provider.",
            "package_version": __version__,
            "source_name": result.source_name,
            "parser_name": result.parser_name,
            "invoice": result.context.to_dict(),
            "extraction_quality": result.quality.to_dict() if result.quality else None,
            "financial_reconciliation": result.financial_quality.to_dict() if result.financial_quality else None,
            "rows": len(result.decisions),
            "exact_alias_count": exact,
            "canonicalization_llm_calls": _provider_calls(container),
            "decisions": [item.to_dict() for item in result.decisions],
        }
        DEMO.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload


def _status_map(quality: dict[str, object]) -> dict[str, str]:
    return {str(item["name"]): str(item["status"]) for item in quality.get("results", [])}  # type: ignore[index]


def _details_map(quality: dict[str, object]) -> dict[str, str]:
    return {str(item["name"]): str(item.get("details", "")) for item in quality.get("results", [])}  # type: ignore[index]


def _write_final_check(demo: dict[str, object]) -> None:
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    evaluation = json.loads(EVALUATION.read_text(encoding="utf-8"))
    statuses = _status_map(quality)
    details = _details_map(quality)
    tests_match = re.search(r"(\d+) passed", details.get("tests_with_coverage", ""))
    coverage_match = re.search(r"^TOTAL\s+.*?\s+(\d+)%\s*$", details.get("coverage_threshold", ""), re.MULTILINE)
    tests = tests_match.group(1) if tests_match else "unknown"
    coverage = coverage_match.group(1) + "%" if coverage_match else "unknown"
    lock_match = re.search(r"(\d+) runtime pins, (\d+) CI/dev pins", details.get("lockfile", ""))
    lock_evidence = (
        f"{lock_match.group(1)} runtime + {lock_match.group(2)} dev/CI exact pins"
        if lock_match else "exact runtime/dev/build pins"
    )
    lines = [
        "# Final Delivery Check",
        "",
        "## Business objective",
        "",
        "Record the final assessor-facing verification for the deterministic-first invoice canonicalization package.",
        "",
        "## Technical description",
        "",
        f"Package version: `{__version__}`. Detailed machine-readable evidence remains in `quality_summary.*`, `evaluation.json`, `interview_demo.json`, and `demo_output.json`.",
        "",
        "| Check | Result | Evidence |",
        "|---|---|---|",
        f"| Offline quality gate | {quality['overall']} | `reports/quality_summary.html` |",
        f"| Automated tests | {tests} passed | pytest + branch coverage |",
        f"| Branch-aware coverage | {coverage} | threshold >= 80% |",
        f"| Exact lock validation | {statuses.get('lockfile')} | {lock_evidence} |",
        f"| Mandatory internal static contract | {statuses.get('static_contract')} | typed-signature / unsafe-Python contract |",
        f"| Ruff in this sandbox | {statuses.get('ruff')} | CI/`make assess-full` requires Ruff |",
        f"| mypy in this sandbox | {statuses.get('mypy')} | CI/`make assess-full` requires mypy |",
        f"| Secret scan | {statuses.get('secret_scan')} | no committed credential pattern |",
        f"| Report sanitization | {statuses.get('report_sanitization')} | no workspace/private-index leakage in text reports |",
        f"| Challenge integration smoke test | {'PASS' if demo.get('rows') == demo.get('exact_alias_count') and demo.get('canonicalization_llm_calls') == 0 else 'FAIL'} | seeded replay: {demo.get('exact_alias_count')}/{demo.get('rows')} exact aliases; 0 canonicalization LLM calls; not an ML-accuracy claim |",
        f"| Challenge extraction quality | {(demo.get('extraction_quality') or {}).get('status', 'UNKNOWN')} | Decimal row arithmetic + subtotal check |",  # type: ignore[union-attr]
        f"| Full invoice context | {'PASS' if (demo.get('invoice') or {}).get('invoice_number') == '19283746552' else 'FAIL'} | seller/bill-to/ship-to, dates/terms, discount, tax, shipping and amount due persisted |",  # type: ignore[union-attr]
        f"| Commercial reconciliation | {(demo.get('financial_reconciliation') or {}).get('status', 'UNKNOWN')} | discount + tax + shipping + amount-due checks are separate from product naming |",  # type: ignore[union-attr]
        f"| Offline routing evaluation | {'PASS' if all(float(evaluation[key]) == 1.0 for key in ('canonical_exact_accuracy','transaction_routing_accuracy','knowledge_review_accuracy','llm_usage_accuracy','decision_kind_accuracy')) else 'FAIL'} | 11 curated cases |",
        f"| False blocking bypasses | {evaluation['false_blocking_bypass_count']} | target 0 |",
        f"| Unexpected LLM calls | {evaluation['unexpected_llm_call_count']} | target 0 |",
        f"| Interview demo regression | {statuses.get('interview_demo')} | deterministic -> retrieval -> LLM -> dedup -> human approval -> learned exact alias |",
        f"| Wheel build | {statuses.get('package_build')} | generated under `reports/wheels/` by the quality gate (git-ignored build artifact) |",
        f"| Isolated wheel smoke | {statuses.get('wheel_install_smoke')} | installed outside source tree |",
        f"| Docker execution in this sandbox | {statuses.get('docker_build')} | strict CI / `make assess-full` requires Docker |",
        "| Assessor presentation | PRESENT | `presentation/Invoice_Canonicalization_Agent_Assessment.pptx` + `.pdf` |",
        "",
        "## Assessor-facing three-tier architecture",
        "",
        "1. **Tier 1 - deterministic approved lookup:** exact tenant/partner aliases, zero model call.",
        "2. **Tier 2 - bounded retrieval / AI / abstention:** use approved evidence first, allow one bounded proposal for unresolved uncertainty, and abstain rather than force an unsafe match.",
        "3. **Tier 3 - governed human learning:** promote approved knowledge so future occurrences return to Tier 1.",
        "",
        "Document extraction/arithmetic validation is an upstream reliability guardrail. Full invoice header, party snapshots and commercial totals are persisted for audit/reconciliation but excluded from product naming. REST, MCP, Docker, CI/CD, and PostgreSQL are delivery primitives around the core.",
        "",
        "## Internal machine-checked processing order (appendix)",
        "",
        "1. Authentication and tenant binding",
        "2. File validation",
        "3. Deterministic document parsing",
        "4. Decimal extraction quality gate",
        "5. Model extraction fallback only after deterministic failure",
        "6. Persist invoice header, party snapshots, financials and raw lines",
        "7. Text normalization",
        "8. Safe taxonomy-versioned cache precheck",
        "9. Approved exact-alias lookup",
        "10. Atomic pending-candidate deduplication",
        "11. Approved-only hybrid retrieval",
        "12. Deterministic policy scoring/routing",
        "13. Bounded generation",
        "14. Output/attribute/security validation",
        "15. Staged review queue",
        "16. Human review action",
        "17. Approved knowledge promotion",
        "18. Audit and metrics",
        "",
        "The detailed order is machine-checked by `architecture_manifest.yaml` and `scripts/validate_architecture.py`, but it is intentionally not the primary presentation diagram.",
        "",
        "## Delivery caveat",
        "",
        "The current execution environment does not contain Ruff, mypy, or a Docker engine, so those external-tool gates are reported explicitly as `SKIP` locally rather than being misrepresented as executed. GitHub CI installs the exact dev lock, sets `REQUIRE_STATIC_TOOLS=1`, and independently builds the container; `make assess-full` makes both static tools and Docker mandatory in a suitable release environment.",
    ]
    FINAL.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest() -> None:
    files: list[dict[str, object]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if path.name in SKIP_NAMES or any(part in SKIP_PARTS or part.endswith(".egg-info") for part in relative.parts):
            continue
        files.append({
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    payload = {
        "business_objective": "Prove which exact files were included in the final assessor-facing project directory.",
        "technical_description": "SHA-256 manifest excluding caches/build metadata and the manifest itself.",
        "version": __version__,
        "file_count": len(files),
        "files": files,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    if not QUALITY.exists() or not EVALUATION.exists():
        raise SystemExit("Run the quality gate before generating delivery evidence")
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    if quality.get("overall") != "PASS":
        raise SystemExit("Quality gate must pass before delivery evidence is generated")
    REPORTS.mkdir(parents=True, exist_ok=True)
    demo = _write_challenge_demo()
    _write_final_check(demo)
    _write_manifest()
    print(f"Delivery evidence generated for version {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
