"""Business objective: quantify deterministic accuracy, safe routing, model-call discipline, staged review, and cost on versioned manual cases.

Technical description: runs JSONL cases against an isolated seeded database and writes machine-readable release evidence.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from invoice_canonicalizer.application.factory import build_container
from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.domain.models import InvoiceLine

ROOT = Path(__file__).resolve().parents[1]


def run() -> dict[str, object]:
    cases = [json.loads(line) for line in (ROOT / "evals/cases/canonicalization_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    with tempfile.TemporaryDirectory(prefix="invoice-eval-") as directory:
        settings = replace(load_settings(ROOT), database_path=Path(directory) / "eval.db")
        container = build_container(settings)
        rows: list[dict[str, object]] = []
        correct = 0
        routing_correct = 0
        knowledge_review_correct = 0
        llm_usage_correct = 0
        kind_correct = 0
        cost = Decimal("0")
        for index, case in enumerate(cases, start=1):
            before_calls = container.canonicalizer.provider.call_count
            decision = container.canonicalizer.canonicalize(InvoiceLine(
                tenant_id=case["tenant_id"], partner_id=case["partner_id"],
                description=case["description"], source_line_id=f"eval-{index}",
            ))
            llm_used = container.canonicalizer.provider.call_count > before_calls
            is_correct = decision.canonical_description == case["expected"]
            is_routing_correct = decision.requires_human_review is case["expected_transaction_review"]
            actual_knowledge_review = decision.review_id is not None
            is_knowledge_review_correct = actual_knowledge_review is case["expected_knowledge_review"]
            is_llm_correct = llm_used is case["expected_llm"]
            is_kind_correct = decision.decision_kind.value == case["expected_decision_kind"]
            correct += int(is_correct)
            routing_correct += int(is_routing_correct)
            knowledge_review_correct += int(is_knowledge_review_correct)
            llm_usage_correct += int(is_llm_correct)
            kind_correct += int(is_kind_correct)
            cost += decision.estimated_cost_usd
            rows.append({
                "description": case["description"],
                "expected": case["expected"],
                "actual": decision.canonical_description,
                "expected_transaction_review": case["expected_transaction_review"],
                "actual_transaction_review": decision.requires_human_review,
                "expected_knowledge_review": case["expected_knowledge_review"],
                "actual_knowledge_review": actual_knowledge_review,
                "expected_llm": case["expected_llm"],
                "actual_llm": llm_used,
                "expected_decision_kind": case["expected_decision_kind"],
                "actual_decision_kind": decision.decision_kind.value,
                "correct": is_correct,
                "routing_correct": is_routing_correct,
                "knowledge_review_correct": is_knowledge_review_correct,
                "llm_usage_correct": is_llm_correct,
                "decision_kind_correct": is_kind_correct,
            })
        total = len(cases)
        return {
            "cases": total,
            "canonical_exact_accuracy": correct / total,
            "transaction_routing_accuracy": routing_correct / total,
            "knowledge_review_accuracy": knowledge_review_correct / total,
            "llm_usage_accuracy": llm_usage_correct / total,
            "decision_kind_accuracy": kind_correct / total,
            "estimated_cost_usd": format(cost.quantize(Decimal("0.000001")), "f"),
            "false_blocking_bypass_count": sum(1 for row in rows if row["expected_transaction_review"] and not row["actual_transaction_review"]),
            "missing_knowledge_review_count": sum(1 for row in rows if row["expected_knowledge_review"] and not row["actual_knowledge_review"]),
            "unexpected_llm_call_count": sum(1 for row in rows if not row["expected_llm"] and row["actual_llm"]),
            "rows": rows,
        }


def main() -> int:
    result = run()
    output = ROOT / "reports" / "evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2, sort_keys=True))
    passed = (
        result["canonical_exact_accuracy"] == 1.0
        and result["transaction_routing_accuracy"] == 1.0
        and result["knowledge_review_accuracy"] == 1.0
        and result["llm_usage_accuracy"] == 1.0
        and result["decision_kind_accuracy"] == 1.0
        and result["false_blocking_bypass_count"] == 0
        and result["missing_knowledge_review_count"] == 0
        and result["unexpected_llm_call_count"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
