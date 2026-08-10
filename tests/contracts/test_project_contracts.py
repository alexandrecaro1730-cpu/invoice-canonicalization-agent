"""Business objective: ensure all promised production artifacts exist and are actually wired into execution.

Technical description: validates manifest order, prompt use, review-queue contract, fixture coverage, Docker hardening, and one-command entry points.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from invoice_canonicalizer.domain.models import ReviewAction
from invoice_canonicalizer.infrastructure.review_queue.csv_queue import CSV_FIELDS

ROOT = Path(__file__).resolve().parents[2]


def test_architecture_manifest_order_and_paths() -> None:
    manifest = yaml.safe_load((ROOT / "architecture_manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["workflow_order"][0] == "authentication_and_tenant_binding"
    assert manifest["workflow_order"].index("file_validation") < manifest["workflow_order"].index("deterministic_document_parsing")
    assert manifest["workflow_order"].index("deterministic_document_parsing") < manifest["workflow_order"].index("extraction_quality_gate")
    assert manifest["workflow_order"].index("extraction_quality_gate") < manifest["workflow_order"].index("model_extraction_fallback")
    assert manifest["workflow_order"][-1] == "audit_and_metrics"
    assert "pending_candidate_deduplication" in manifest["workflow_order"]
    assert "staged_review_queue" in manifest["workflow_order"]
    assert manifest["workflow_order"].index("approved_alias_lookup") < manifest["workflow_order"].index("bounded_generation")
    assert manifest["workflow_order"].index("staged_review_queue") < manifest["workflow_order"].index("approved_knowledge_promotion")
    for group in ("components", "entrypoints", "quality_evidence"):
        for path in manifest[group].values():
            assert (ROOT / path).exists(), path


def test_prompts_are_used_by_application_code() -> None:
    code = (ROOT / "src/invoice_canonicalizer/application/canonicalization.py").read_text(encoding="utf-8")
    extraction = (ROOT / "src/invoice_canonicalizer/infrastructure/documents/model_extractor.py").read_text(encoding="utf-8")
    assert 'prompts.load("canonicalize/system.txt")' in code
    assert 'prompts.load("canonicalize/user.txt")' in code
    assert 'prompts.load("extract/system.txt")' in extraction
    assert 'prompts.load("extract/user.txt")' in extraction
    assert "find_pending_review_by_candidate_key" in code
    assert "llm_calls_avoided_total" in code


def test_review_queue_contract_is_human_editable_and_status_is_last() -> None:
    assert CSV_FIELDS[-1] == "status"
    assert ReviewAction.WAITING.value == "waiting_for_approval"
    assert {item.value for item in ReviewAction} >= {
        "approve_existing", "approve_new", "edit_and_approve", "redirect", "reject", "defer",
    }
    assert (ROOT / "data/review_queue/review_queue.template.csv").exists()


def test_dockerfile_runs_non_root_and_has_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "ICA_PROJECT_ROOT=/app" in dockerfile
    assert "requirements-runtime.lock" in dockerfile
    assert "--no-index" in dockerfile
    assert "OPENAI_API_KEY" not in dockerfile


def test_makefile_has_one_command_quality_gate_and_review_workflow() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "assess:" in makefile
    assert "python scripts/quality_gate.py" in makefile
    assert "review-demo:" in makefile
    assert "review-export:" in makefile
    assert "review-process:" in makefile
    assert "lint:" in makefile
    assert "typecheck:" in makefile
    assert "interview-demo:" in makefile
    assert "delivery-evidence:" in makefile


def test_example_inputs_and_expected_contract_are_visible_under_data() -> None:
    assert (ROOT / "data/examples/input/challenge_invoice.pdf").exists()
    assert (ROOT / "data/reference/Challenge_Data_Scientist.pdf").exists()
    assert (ROOT / "data/examples/expected/challenge_expected.json").exists()
    for suffix in ("pdf", "docx", "xlsx", "json", "csv", "txt"):
        assert (ROOT / f"data/examples/input/equivalent_invoice.{suffix}").exists()


def test_production_review_migration_exists() -> None:
    migration = (ROOT / "migrations/postgres/002_review_queue.sql").read_text(encoding="utf-8")
    assert "review_candidates" in migration
    assert "review_occurrences" in migration
    assert "WHERE status = 'pending'" in migration
    assert "ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "WITH CHECK" in migration


def test_package_version_matches_pyproject() -> None:
    import re

    package_init = (ROOT / "src/invoice_canonicalizer/__init__.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    package_version = re.search(r'__version__\s*=\s*"([^"]+)"', package_init)
    project_version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    assert package_version and project_version
    assert package_version.group(1) == project_version.group(1)


def test_exact_lockfiles_and_static_quality_contract_are_wired() -> None:
    runtime_lock = (ROOT / "requirements-runtime.lock").read_text(encoding="utf-8")
    dev_lock = (ROOT / "requirements-dev.lock").read_text(encoding="utf-8")
    assert "fastapi==" in runtime_lock
    assert "ruff==" in dev_lock
    assert "mypy==" in dev_lock
    quality = (ROOT / "scripts/quality_gate.py").read_text(encoding="utf-8")
    assert '"static_contract"' in quality
    assert '"report_sanitization"' in quality


def test_quality_gate_runs_interview_demo_before_packaging() -> None:
    quality = (ROOT / "scripts/quality_gate.py").read_text(encoding="utf-8")
    assert 'run_gate("interview_demo"' in quality
    assert quality.index('run_gate("offline_evaluation"') < quality.index('run_gate("interview_demo"')
    assert quality.index('run_gate("interview_demo"') < quality.index('run_gate("package_build"')
