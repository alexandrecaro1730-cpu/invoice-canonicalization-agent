"""Business objective: demonstrate the three-tier canonicalization story and declining model-call curve in under five minutes.

Technical description: runs an upstream document-quality smoke test, deterministic lookup, scoped taxonomy collision,
retrieval, bounded generation, pending-candidate deduplication, human approval, and learned exact-alias replay in an
isolated temporary SQLite database. The evidence intentionally separates document-ingestion guardrails from product
canonicalization routing.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from invoice_canonicalizer.application.factory import build_container
from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.domain.models import DecisionKind, InvoiceLine
from invoice_canonicalizer.infrastructure.llm.fixture_provider import FixtureModelProvider

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "interview_demo.json"


def _provider_calls(container) -> int:
    provider = container.canonicalizer.provider
    return provider.canonicalization_call_count if isinstance(provider, FixtureModelProvider) else -1


def _rate_per_1000(occurrences: int) -> float:
    """Return normalized model calls / 1,000 occurrences for one unique unknown.

    One unique unresolved concept needs at most one proposal while pending; after approval its future occurrences
    resolve by exact alias. This is a normalized architecture metric, not a provider-dollar claim.
    """
    return round(1000.0 / occurrences, 6)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ica-interview-demo-") as temp_dir:
        settings = replace(load_settings(ROOT), database_path=Path(temp_dir) / "catalog.db")
        container = build_container(settings)

        # Upstream ingestion guardrail smoke test. This proves clean extraction before product routing.
        challenge = container.ingestion.process(
            ROOT / "data/examples/input/challenge_invoice.pdf",
            "testinger",
            "default-partner",
        )
        challenge_llm_calls = _provider_calls(container)
        exact_count = sum(item.decision_kind is DecisionKind.EXACT_ALIAS for item in challenge.decisions)

        # Explicit taxonomy collision: same supplier wording is valid for two tenants but maps differently.
        collision_a = container.canonicalizer.canonicalize(InvoiceLine(
            tenant_id="testinger",
            partner_id="default-partner",
            description="Steel Accessories",
            source_line_id="demo-collision-a",
        ))
        collision_b = container.canonicalizer.canonicalize(InvoiceLine(
            tenant_id="other-tenant",
            partner_id="default-partner",
            description="Steel Accessories",
            source_line_id="demo-collision-b",
        ))

        # Tier 2: high-confidence bounded retrieval can keep the transaction flowing without a model call.
        auto = container.canonicalizer.canonicalize(InvoiceLine(
            tenant_id="testinger",
            partner_id="default-partner",
            description="Athletic crew socks",
            source_line_id="demo-auto",
        ))
        calls_after_auto = _provider_calls(container)

        # Tier 2 uncertain tail: one bounded generation creates staged knowledge, not approved knowledge.
        novel_line = InvoiceLine(
            tenant_id="testinger",
            partner_id="default-partner",
            description="Black Leather Jacket Midnight",
            source_line_id="demo-novel-1",
        )
        novel = container.canonicalizer.canonicalize(novel_line)
        calls_after_novel = _provider_calls(container)
        for index in range(2, 27):
            container.canonicalizer.canonicalize(replace(
                novel_line,
                source_line_id=f"demo-novel-{index}",
                description="BLACK LEATHER JACKET MIDNIGHT!!!" if index % 2 == 0 else novel_line.description,
            ))
        calls_after_repeats = _provider_calls(container)
        pending = container.repository.get_review("testinger", novel.review_id or "")
        if pending is None:
            raise RuntimeError("novel product review was not staged")

        # Tier 3: human approval promotes knowledge. The next occurrence is Tier 1 exact lookup.
        approved = container.reviews.approve(
            "testinger",
            pending.review_id,
            approved_description="Black Leather Jacket",
            approved_category="jacket",
        )
        learned = container.canonicalizer.canonicalize(replace(novel_line, source_line_id="demo-after-approval"))
        calls_after_learning = _provider_calls(container)

        recurrence_points = [1, 10, 100, 1_000, 10_000]
        cost_curve = [
            {
                "occurrences_of_same_unique_unknown": n,
                "maximum_model_proposals_while_pending": 1,
                "normalized_model_calls_per_1000_occurrences": _rate_per_1000(n),
            }
            for n in recurrence_points
        ]

        smoke_test = {
            "label": "integration_smoke_test_not_model_accuracy",
            "parser": challenge.parser_name,
            "invoice": challenge.context.to_dict(),
            "extraction_quality": challenge.quality.to_dict() if challenge.quality else None,
            "financial_reconciliation": challenge.financial_quality.to_dict() if challenge.financial_quality else None,
            "rows": len(challenge.decisions),
            "exact_aliases": exact_count,
            "llm_calls": challenge_llm_calls,
            "canonical_descriptions": [item.canonical_description for item in challenge.decisions],
        }

        evidence = {
            "narrative": {
                "core_tiers": [
                    "Tier 1 - deterministic approved lookup ($0 model cost)",
                    "Tier 2 - bounded retrieval / AI fallback for uncertainty",
                    "Tier 3 - governed human learning that promotes trusted knowledge",
                ],
                "delivery_primitives": ["REST", "MCP", "Docker", "CI/CD", "PostgreSQL migration"],
            },
            "document_ingestion_guardrail": smoke_test,
            # Backward-compatible alias retained for existing assessor artifacts.
            "challenge": smoke_test,
            "tenant_taxonomy_collision": {
                "raw_description": "Steel Accessories",
                "tenant_a": {
                    "tenant_id": "testinger",
                    "canonical_description": collision_a.canonical_description,
                    "decision_kind": collision_a.decision_kind.value,
                },
                "tenant_b": {
                    "tenant_id": "other-tenant",
                    "canonical_description": collision_b.canonical_description,
                    "decision_kind": collision_b.decision_kind.value,
                },
                "same_raw_text_different_products": collision_a.canonical_product_id != collision_b.canonical_product_id,
            },
            "tier_2_high_confidence_retrieval": {
                "input": auto.input_description,
                "decision_kind": auto.decision_kind.value,
                "canonical_description": auto.canonical_description,
                "transaction_blocked": auto.requires_human_review,
                "knowledge_review_staged": bool(auto.review_id),
                "additional_llm_calls": calls_after_auto - challenge_llm_calls,
            },
            # Backward-compatible key retained for existing references.
            "high_confidence_retrieval": {
                "input": auto.input_description,
                "decision_kind": auto.decision_kind.value,
                "canonical_description": auto.canonical_description,
                "transaction_blocked": auto.requires_human_review,
                "knowledge_review_staged": bool(auto.review_id),
                "additional_llm_calls": calls_after_auto - challenge_llm_calls,
            },
            "tier_2_novel_product": {
                "decision_kind": novel.decision_kind.value,
                "proposal": novel.canonical_description,
                "transaction_blocked": novel.requires_human_review,
                "llm_calls_for_first_occurrence": calls_after_novel - calls_after_auto,
                "deduplicated_occurrences": pending.occurrence_count,
                "additional_llm_calls_for_repeats": calls_after_repeats - calls_after_novel,
            },
            "novel_product": {
                "decision_kind": novel.decision_kind.value,
                "proposal": novel.canonical_description,
                "transaction_blocked": novel.requires_human_review,
                "llm_calls_for_first_occurrence": calls_after_novel - calls_after_auto,
                "deduplicated_occurrences": pending.occurrence_count,
                "additional_llm_calls_for_repeats": calls_after_repeats - calls_after_novel,
            },
            "tier_3_human_learning": {
                "approved_product_id": approved.product_id,
                "approved_description": approved.canonical_description,
                "next_decision_kind": learned.decision_kind.value,
                "next_canonical_description": learned.canonical_description,
                "additional_llm_calls_after_approval": calls_after_learning - calls_after_repeats,
            },
            "human_learning": {
                "approved_product_id": approved.product_id,
                "approved_description": approved.canonical_description,
                "next_decision_kind": learned.decision_kind.value,
                "next_canonical_description": learned.canonical_description,
                "additional_llm_calls_after_approval": calls_after_learning - calls_after_repeats,
            },
            "declining_cost_curve": {
                "interpretation": "Model spend scales with unique unresolved concepts, not repeated invoice volume. After human approval, future occurrences use the exact-alias path.",
                "metric": "normalized model calls per 1,000 repeated occurrences of one unique unknown",
                "points": cost_curve,
                "provider_dollar_cost_claimed": False,
            },
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    print("=" * 74)
    print("INVOICE CANONICALIZATION - THREE-TIER INTERVIEW DEMO")
    print("=" * 74)
    print("UPSTREAM DOCUMENT GUARDRAIL")
    print(f"  Integration smoke test: {exact_count}/{len(challenge.decisions)} seeded aliases replayed; LLM calls={challenge_llm_calls}")
    quality = challenge.quality.status.value if challenge.quality else "UNKNOWN"
    print(f"  Extraction arithmetic quality: {quality} (garbage rows stop before canonicalization)")
    financial_quality = challenge.financial_quality.status.value if challenge.financial_quality else "UNKNOWN"
    print(f"  Full invoice retained: #{challenge.context.invoice_number}; seller/bill-to/ship-to + discount/tax/shipping; financial reconciliation={financial_quality}")
    print("  These fields are persisted for audit/reconciliation but excluded from product naming prompts.")
    print("TIER 1 - DETERMINISTIC APPROVED LOOKUP")
    print(f"  Tenant collision: 'Steel Accessories' -> {collision_a.canonical_description} / {collision_b.canonical_description}")
    print("TIER 2 - BOUNDED RETRIEVAL / AI FALLBACK")
    print(f"  {auto.input_description!r} -> {auto.canonical_description}; extra LLM calls={calls_after_auto - challenge_llm_calls}")
    print(f"  {novel.input_description!r} -> {novel.canonical_description}; first LLM calls={calls_after_novel - calls_after_auto}")
    print(f"  Same unknown observed {pending.occurrence_count} times -> extra LLM calls={calls_after_repeats - calls_after_novel}")
    print("TIER 3 - GOVERNED HUMAN LEARNING")
    print(f"  Human approval -> {approved.canonical_description}")
    print(f"  Next occurrence -> {learned.decision_kind.value}; extra LLM calls={calls_after_learning - calls_after_repeats}")
    print("ECONOMICS")
    print("  Model-call rate declines with repeated volume because calls are per unique unknown, then approvals become exact aliases.")
    print("=" * 74)
    print("Evidence: reports/interview_demo.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
