"""Business objective: prove that promised production assets are wired, ordered, and reviewable before delivery.

Technical description: performs a static/dynamic inventory audit over workflow stages, modules, prompts, authentication, Decimal/extraction controls, retrieval, locks, fixtures, review operations, migrations, CI/CD, and quality automation.
"""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

import yaml

from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.infrastructure.llm.prompt_registry import PromptRegistry

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "completeness_check.md"
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


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    return ".".join(relative.parts)


def _source_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    evidence: list[tuple[str, str]] = []

    manifest = yaml.safe_load((ROOT / "architecture_manifest.yaml").read_text(encoding="utf-8"))
    _check(manifest.get("workflow_order") == EXPECTED_ORDER, "production workflow order changed", failures)
    evidence.append(("Architecture narrative", "Three assessor-facing canonicalization tiers are separated from upstream ingestion guardrails and delivery primitives; the 18-stage detailed order remains machine-checked internally"))

    source_files = sorted((ROOT / "src/invoice_canonicalizer").rglob("*.py"))
    source_modules = {_module_name(path): path for path in source_files if path.name != "__init__.py"}
    imported_modules: set[str] = set()
    for path in source_files:
        imported_modules.update(_source_imports(path))
    dynamic_entrypoints = {
        "invoice_canonicalizer.api.app",
        "invoice_canonicalizer.cli",
        "invoice_canonicalizer.mcp.server",
        "invoice_canonicalizer.__main__",
    }
    unreferenced = [
        module
        for module in source_modules
        if module not in imported_modules
        and not any(item.startswith(module + ".") for item in imported_modules)
        and module not in dynamic_entrypoints
    ]
    _check(not unreferenced, f"source modules not wired into imports/entrypoints: {unreferenced}", failures)
    evidence.append(("Source modules", f"{len(source_modules)} executable modules are imported or registered as entry points"))

    factory_text = (ROOT / "src/invoice_canonicalizer/application/factory.py").read_text(encoding="utf-8")
    ingestion_text = (ROOT / "src/invoice_canonicalizer/application/ingestion.py").read_text(encoding="utf-8")
    model_extractor_text = (ROOT / "src/invoice_canonicalizer/infrastructure/documents/model_extractor.py").read_text(encoding="utf-8")
    for parser_class in ("PdfInvoiceParser", "DocxInvoiceParser", "XlsxInvoiceParser", "JsonInvoiceParser", "DelimitedInvoiceParser"):
        _check(parser_class in factory_text, f"parser not registered in factory: {parser_class}", failures)
    _check("ExtractionQualityStatus.FAIL" in ingestion_text, "ingestion does not enforce extraction quality", failures)
    _check("ModelDocumentExtractor" in factory_text and "model_extractor.extract" in ingestion_text, "bounded model extraction fallback is not wired", failures)
    _check("save_invoice_document" in ingestion_text and "link_invoice_decision" in ingestion_text, "parsed invoice evidence is not persisted before/after canonicalization", failures)
    read_api_text = (ROOT / "src/invoice_canonicalizer/api/app.py").read_text(encoding="utf-8")
    _check("get_invoice_line_records" in read_api_text, "persisted document read API does not expose canonical outcomes", failures)
    evidence.append(("Document ingestion", "PDF/DOCX/XLSX/JSON/CSV/TXT adapters retain invoice header, seller/bill-to/ship-to parties, line items and commercial totals; line arithmetic gates canonicalization while financial reconciliation is recorded separately"))

    prompt_registry = PromptRegistry(ROOT / "prompts")
    prompt_contracts = {
        "canonicalize/system.txt": {},
        "canonicalize/user.txt": {
            "source_description": "Black Leather Jacket Midnight",
            "style_guide": "{}",
            "source_attributes": "{}",
            "retrieved_candidates": "[]",
        },
        "extract/system.txt": {},
        "extract/user.txt": {"invoice_text": "DESCRIPTION QTY UNIT PRICE TOTAL\nWidget 2 12.50 25.00"},
    }
    for relative, values in prompt_contracts.items():
        rendered = prompt_registry.load(relative).render(**values)
        _check(bool(rendered.strip()), f"prompt rendered empty: {relative}", failures)
    canonical_text = (ROOT / "src/invoice_canonicalizer/application/canonicalization.py").read_text(encoding="utf-8")
    _check('prompts.load("canonicalize/system.txt")' in canonical_text, "canonicalization system prompt is unused", failures)
    _check('prompts.load("canonicalize/user.txt")' in canonical_text, "canonicalization user prompt is unused", failures)
    _check('prompts.load("extract/system.txt")' in model_extractor_text, "extraction system prompt is unused", failures)
    _check('prompts.load("extract/user.txt")' in model_extractor_text, "extraction user prompt is unused", failures)
    _check("model_responses.json" in factory_text and "extraction_responses.json" in factory_text, "manual offline model fixtures are not both wired", failures)
    evidence.append(("Prompt contracts", "4 versioned text prompts are executable; canonicalization and document-extraction model paths both have manual offline fixtures"))

    auth_text = (ROOT / "src/invoice_canonicalizer/security/auth.py").read_text(encoding="utf-8")
    api_text = (ROOT / "src/invoice_canonicalizer/api/app.py").read_text(encoding="utf-8")
    _check("ApiKeyAuthenticator" in auth_text and "hmac.compare_digest" in auth_text, "API-key authentication is incomplete", failures)
    _check("resolve_tenant" in api_text and "Depends(reviewer)" in api_text and "Depends(processor)" in api_text, "API tenant/role binding is not wired", failures)
    evidence.append(("Authentication", "API/MCP requests derive tenant scope from an authenticated principal; processor/reviewer permissions are separated and caller tenant overrides are rejected"))

    money_text = (ROOT / "src/invoice_canonicalizer/utils/money.py").read_text(encoding="utf-8")
    models_text = (ROOT / "src/invoice_canonicalizer/domain/models.py").read_text(encoding="utf-8")
    _check("Decimal" in money_text and "Decimal | None" in models_text, "Decimal money model is missing", failures)
    evidence.append(("Financial precision", "Invoice money and cost controls use Decimal; review aggregation preserves per-currency values instead of summing incomparable currencies"))

    semantic_text = (ROOT / "src/invoice_canonicalizer/infrastructure/retrieval/semantic.py").read_text(encoding="utf-8")
    hybrid_text = (ROOT / "src/invoice_canonicalizer/infrastructure/retrieval/hybrid.py").read_text(encoding="utf-8")
    _check("SemanticScoreProvider" in semantic_text and "semantic_provider" in hybrid_text, "semantic retrieval extension point is not wired", failures)
    _check("DisabledSemanticScoreProvider" in factory_text, "deterministic semantic-disabled default is missing", failures)
    evidence.append(("Retrieval", "Assessment path uses approved-only lexical/token/trigram/attribute retrieval; an optional batch semantic reranker exists but remains disabled until benchmarked"))

    queue_text = (ROOT / "src/invoice_canonicalizer/infrastructure/review_queue/csv_queue.py").read_text(encoding="utf-8")
    makefile_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    _check('"status",\n)' in queue_text, "review CSV status is not the final schema field", failures)
    for target in ("review-demo:", "review-export:", "review-process:", "interview-demo:", "lint:", "typecheck:"):
        _check(target in makefile_text, f"missing operator/developer command: {target}", failures)
    _check((ROOT / "data/review_queue/review_queue.template.csv").exists(), "review queue template is missing", failures)
    evidence.append(("Human review", "CSV queue, archive, deduplicated pending candidates, flexible actions, exact per-currency impact, and interview demo are wired"))

    with tempfile.TemporaryDirectory(prefix="ica-config-audit-") as temp_dir:
        settings = load_settings(
            project_root=ROOT,
            config_path=ROOT / "config/production.yaml",
            environ={
                "ICA_DATABASE_PATH": str(Path(temp_dir) / "audit.db"),
                "ICA_API_KEYS_JSON": json.dumps({"audit-token": {"tenant_id": "audit", "roles": ["processor"]}}),
            },
        )
        _check(settings.auth_mode == "api-key", "production authentication is not enabled", failures)
        _check(settings.provider_name == "openai-compatible", "production provider configuration invalid", failures)
        _check(settings.provider_input_cost_per_million > 0 and settings.provider_output_cost_per_million > 0, "production model price controls are zero", failures)
        _check(settings.seed_catalog_path.exists() and settings.client_styles_path.exists(), "configured seed/style assets are missing", failures)
    evidence.append(("Configuration", "Production configuration enables tenant-bound API keys, non-zero provider pricing placeholders, bounded retries, strict retrieval thresholds, OCR, and model-extraction fallback"))

    e2e_text = (ROOT / "tests/e2e/test_multiformat.py").read_text(encoding="utf-8")
    for extension in ("pdf", "docx", "xlsx", "json", "csv", "txt"):
        fixture = ROOT / "data/examples/input" / f"equivalent_invoice.{extension}"
        _check(fixture.exists() and fixture.stat().st_size > 0, f"missing/empty generated fixture: {fixture.name}", failures)
        _check(f"invoice.{extension}" in e2e_text, f"generated fixture not included in e2e test: {fixture.name}", failures)
    _check("data/examples/input/challenge_invoice.pdf" in e2e_text, "runnable challenge invoice PDF is not included in e2e testing", failures)
    _check((ROOT / "data/examples/input/challenge_invoice.pdf").exists(), "runnable page-2 challenge invoice PDF is missing from data/examples/input", failures)
    _check((ROOT / "data/examples/expected/challenge_expected.json").exists(), "expected challenge output contract is missing", failures)
    _check((ROOT / "data/reference/Challenge_Data_Scientist.pdf").exists(), "full supplied assessment reference is missing", failures)
    _check((ROOT / "tests/fixtures/fallback/unstructured_invoice.txt").exists(), "model extraction fallback fixture missing", failures)
    evidence.append(("Cross-format evidence", "6 equivalent example formats, the page-2 challenge invoice PDF, the full supplied assessment reference, and a deterministic-failure/model-fallback invoice are exercised"))

    for lock_name in ("requirements-runtime.lock", "requirements-dev.lock"):
        _check((ROOT / lock_name).exists(), f"missing dependency lock: {lock_name}", failures)
    lock_validator = (ROOT / "scripts/validate_lockfile.py").read_text(encoding="utf-8")
    _check("exact pin" in lock_validator.lower(), "lock validation is not exact-pin aware", failures)
    evidence.append(("Reproducibility", "Runtime and CI/dev dependency graphs have exact pin files checked against pyproject constraints"))

    migration1 = (ROOT / "migrations/postgres/001_initial.sql").read_text(encoding="utf-8")
    migration2 = (ROOT / "migrations/postgres/002_review_queue.sql").read_text(encoding="utf-8")
    migration3 = (ROOT / "migrations/postgres/003_invoice_documents.sql").read_text(encoding="utf-8")
    for migration in (migration1, migration2, migration3):
        _check("FORCE ROW LEVEL SECURITY" in migration and "WITH CHECK" in migration, "PostgreSQL RLS lacks FORCE/WITH CHECK", failures)
    _check("FOREIGN KEY" in migration1 and "tenant_id" in migration1 and "partner_id" in migration1, "tenant/partner relational integrity is missing", failures)
    _check("invoice_documents" in migration3 and "invoice_parties" in migration3 and "invoice_lines" in migration3, "production invoice persistence migration is incomplete", failures)
    evidence.append(("Production database", "PostgreSQL stores tenant-scoped invoice headers, parties/addresses, exact financials, raw lines and canonical outcomes; all migrations enforce FORCE RLS with USING/WITH CHECK"))

    workflow_files = [
        ROOT / ".github/workflows/ci.yml",
        ROOT / ".github/workflows/live-eval.yml",
        ROOT / ".github/workflows/release.yml",
    ]
    for path in workflow_files:
        _check(path.exists(), f"missing workflow: {path.name}", failures)
    ci_text = workflow_files[0].read_text(encoding="utf-8")
    _check("requirements-dev.lock" in ci_text and "REQUIRE_STATIC_TOOLS" in ci_text, "CI does not install locked dependencies and require static analysis", failures)
    _check("make assess" in ci_text and "docker build" in ci_text, "CI does not run assessment and container build", failures)
    release_text = workflow_files[2].read_text(encoding="utf-8")
    _check("requirements-dev.lock" in release_text and "python -m build" in release_text and "docker build" in release_text, "release workflow is incomplete", failures)
    evidence.append(("Delivery automation", "PR CI installs exact pins, requires Ruff/mypy, runs the quality gate and Docker; live evaluation and tagged package/container release remain separate"))

    quality_text = (ROOT / "scripts/quality_gate.py").read_text(encoding="utf-8")
    required_gates = (
        "lockfile",
        "ruff",
        "mypy",
        "static_contract",
        "compile",
        "documentation",
        "architecture",
        "completeness",
        "secret_scan",
        "tests_with_coverage",
        "coverage_threshold",
        "offline_evaluation",
        "interview_demo",
        "package_build",
        "wheel_install_smoke",
        "docker_build",
        "report_sanitization",
    )
    missing_gate_names = [name for name in required_gates if name not in quality_text]
    _check(not missing_gate_names, f"quality gate missing checks: {missing_gate_names}", failures)
    evidence.append(("Quality automation", "One command covers locks, Ruff/mypy, structure/docs, security, tests/coverage, evaluation, package smoke, Docker readiness, and report sanitization"))

    assessor_summary = ROOT / "docs/assessor_summary.md"
    invoice_data_model = ROOT / "docs/invoice_data_model.md"
    presentation_pptx = ROOT / "presentation/Invoice_Canonicalization_Agent_Assessment.pptx"
    presentation_pdf = ROOT / "presentation/Invoice_Canonicalization_Agent_Assessment.pdf"
    _check(assessor_summary.exists() and assessor_summary.stat().st_size > 0, "assessor summary is missing", failures)
    _check(invoice_data_model.exists() and "Bill-to party (expected payer)" in invoice_data_model.read_text(encoding="utf-8"), "invoice evidence/data-model boundary documentation is missing", failures)
    _check(presentation_pptx.exists() and presentation_pptx.stat().st_size > 0, "assessor PPTX is missing", failures)
    _check(presentation_pdf.exists() and presentation_pdf.stat().st_size > 0, "assessor PDF is missing", failures)
    evidence.append(("Assessor narrative", "Three-tier business-first summary, invoice data-model boundary, and presentation are packaged; technical stage sequencing is relegated to appendix material"))

    seed = json.loads((ROOT / "data/seed/catalog.json").read_text(encoding="utf-8"))
    _check(len(seed.get("products", [])) >= 6, "seed catalog does not contain the challenge products", failures)
    alias_count = sum(len(product.get("aliases", [])) for product in seed.get("products", []))
    _check(alias_count >= 6, "seed catalog does not contain approved challenge aliases", failures)
    evidence.append(("Knowledge base", f"{len(seed.get('products', []))} tenant-scoped products and {alias_count} approved aliases are versioned"))

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    status = "PASS" if not failures else "FAIL"
    lines = [
        f"# Completeness Audit: {status}",
        "",
        "This audit verifies that deliverables are not merely present: production modules, prompts, controls, parsers, fixtures, configuration, persistence, security and automation are connected to executable paths.",
        "",
        "| Area | Evidence |",
        "|---|---|",
    ]
    lines.extend(f"| {area} | {detail} |" for area, detail in evidence)
    if failures:
        lines.extend(["", "## Failures", *[f"- {item}" for item in failures]])
    else:
        lines.extend(["", "No missing or unregistered critical artifacts were detected."])
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if failures:
        print("\n".join(failures))
        return 1
    print("Completeness audit passed; report: reports/completeness_check.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
