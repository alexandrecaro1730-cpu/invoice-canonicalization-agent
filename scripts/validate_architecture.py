"""Business objective: detect forgotten components and accidental workflow reordering before release.

Technical description: validates the 18-stage architecture manifest, entry points, prompts, lock files, seed data, migrations, and critical production artifacts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ORDER = [
    "authentication_and_tenant_binding",
    "file_validation",
    "deterministic_document_parsing",
    "extraction_quality_gate",
    "model_extraction_fallback",
    "invoice_context_persistence",
    "text_normalization",
    "cache_precheck",
    "approved_alias_lookup",
    "pending_candidate_deduplication",
    "approved_only_hybrid_retrieval",
    "policy_scoring_and_routing",
    "bounded_generation",
    "output_validation",
    "staged_review_queue",
    "human_review_action",
    "approved_knowledge_promotion",
    "audit_and_metrics",
]


def main() -> int:
    manifest = yaml.safe_load((ROOT / "architecture_manifest.yaml").read_text(encoding="utf-8"))
    failures: list[str] = []
    if manifest.get("workflow_order") != EXPECTED_ORDER:
        failures.append("workflow_order differs from the approved production sequence")
    for section in ("components", "entrypoints", "quality_evidence"):
        for name, relative in manifest.get(section, {}).items():
            if not (ROOT / relative).exists():
                failures.append(f"{section}.{name} points to missing path: {relative}")
    required = [
        "prompts/canonicalize/system.txt",
        "prompts/canonicalize/user.txt",
        "prompts/extract/system.txt",
        "prompts/extract/user.txt",
        "prompts/fixtures/model_responses.json",
        "prompts/fixtures/extraction_responses.json",
        "data/seed/catalog.json",
        "requirements-runtime.lock",
        "requirements-dev.lock",
        "Dockerfile",
        "compose.yaml",
        "Makefile",
        ".github/workflows/ci.yml",
        "migrations/postgres/001_initial.sql",
        "migrations/postgres/002_review_queue.sql",
        "migrations/postgres/003_invoice_documents.sql",
        "data/review_queue/review_queue.template.csv",
        "scripts/interview_demo.py",
    ]
    failures.extend(f"missing required artifact: {item}" for item in required if not (ROOT / item).exists())
    if failures:
        print("\n".join(failures))
        return 1
    print("Architecture gate passed: 18 governed stages and all critical artifacts present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
