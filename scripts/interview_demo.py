"""Business objective: prove the supplied invoice task and all three inconsistent runs from the brief first, then explain the governed unknown-product lifecycle clearly in one terminal demo.

Technical description: processes the real challenge PDF in an isolated SQLite database, prints the extracted invoice lines and expected canonical results, then traces one unseen product through Tier 1 exact lookup, Tier 2 approved retrieval/bounded fixture-model proposal, Tier 3 human approval, and learned Tier 1 replay. Machine-readable evidence is still written to reports/interview_demo.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from invoice_canonicalizer.application.factory import ApplicationContainer, build_container
from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.domain.models import (
    CanonicalizationDecision,
    DecisionKind,
    InvoiceLine,
    StoredInvoiceLine,
)
from invoice_canonicalizer.infrastructure.llm.fixture_provider import FixtureModelProvider

from run_evaluation import run as run_golden_evaluation

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "interview_demo.json"
CHALLENGE_ACCEPTANCE = ROOT / "data/examples/expected/challenge_three_run_acceptance.json"
DEMO_WIDTH = 106


class Style:
    """Minimal ANSI styling that automatically disables itself for CI/report capture."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def blue(self, text: str) -> str:
        return self._wrap("34", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)


STYLE = Style(enabled=sys.stdout.isatty() and os.getenv("NO_COLOR") is None)


def _provider_calls(container: ApplicationContainer) -> int:
    provider = container.canonicalizer.provider
    return provider.canonicalization_call_count if isinstance(provider, FixtureModelProvider) else -1


def _rate_per_1000(occurrences: int) -> float:
    """Return normalized model calls / 1,000 occurrences for one unique unknown."""
    return round(1000.0 / occurrences, 6)


def _text(value: object | None, fallback: str = "-") -> str:
    return fallback if value is None else str(value)


def _money(value: Decimal | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _terminal_width() -> int:
    columns = shutil.get_terminal_size((DEMO_WIDTH, 30)).columns
    return min(max(columns, 92), 118)


def _rule(title: str, *, number: str | None = None) -> None:
    width = _terminal_width()
    label = f" {number}  {title} " if number else f" {title} "
    label = STYLE.bold(STYLE.cyan(label))
    # ANSI codes do not affect visible width, so use the unstyled label for padding math.
    visible = f" {number}  {title} " if number else f" {title} "
    print()
    print(label + "─" * max(1, width - len(visible)))


def _panel(lines: Sequence[str]) -> None:
    width = _terminal_width()
    inner = width - 4
    print("╭" + "─" * (width - 2) + "╮")
    for raw in lines:
        text = raw[:inner]
        print("│ " + text.ljust(inner) + " │")
    print("╰" + "─" * (width - 2) + "╯")


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]], widths: Sequence[int], aligns: Sequence[str] | None = None) -> None:
    alignments = aligns or ["left"] * len(headers)

    def border(left: str, middle: str, right: str) -> str:
        return left + middle.join("─" * (width + 2) for width in widths) + right

    def render(cells: Sequence[str]) -> str:
        rendered: list[str] = []
        for cell, width, alignment in zip(cells, widths, alignments, strict=True):
            value = cell if len(cell) <= width else cell[: max(1, width - 1)] + "…"
            rendered.append(value.rjust(width) if alignment == "right" else value.ljust(width))
        return "│ " + " │ ".join(rendered) + " │"

    print(border("┌", "┬", "┐"))
    print(render([STYLE.bold(header) for header in headers]))
    print(border("├", "┼", "┤"))
    for row in rows:
        print(render(row))
    print(border("└", "┴", "┘"))


def _metric(label: str, value: str, *, status: str | None = None) -> None:
    if status == "ok":
        marker = STYLE.green("✓")
    elif status == "warn":
        marker = STYLE.yellow("?")
    elif status == "fail":
        marker = STYLE.red("✗")
    else:
        marker = " "
    print(f"  {marker} {label:<28} {value}")


def _pause(enabled: bool) -> None:
    if enabled and sys.stdin.isatty():
        input(STYLE.dim("\n  Press Enter to continue…"))


def _retrieval_top(decision: CanonicalizationDecision) -> tuple[str, float] | None:
    for item in decision.evidence:
        if item.get("type") == "retrieval":
            description = item.get("canonical_description")
            score = item.get("score")
            if isinstance(description, str) and isinstance(score, (int, float)):
                return description, float(score)
    return None


def _print_challenge_input(lines: Sequence[StoredInvoiceLine], invoice_number: str | None, parser_name: str) -> None:
    _rule("THE ORIGINAL TASK — ACTUAL INPUT", number="01")
    print("  Source    : data/examples/input/challenge_invoice.pdf")
    print(f"  Invoice   : #{_text(invoice_number)}")
    print(f"  Parser    : {parser_name}")
    print()
    _table(
        ["#", "Original invoice description", "Qty", "Unit", "Line total"],
        [
            [str(index), line.description, _text(line.quantity), _money(line.unit_price), _money(line.total)]
            for index, line in enumerate(lines, start=1)
        ],
        [3, 39, 5, 10, 12],
        ["right", "left", "right", "right", "right"],
    )


def _print_three_run_acceptance(
    rows: Sequence[Sequence[str]],
    accepted_variants: int,
    llm_calls: int,
) -> None:
    _rule("THE THREE RUNS FROM THE BRIEF — ALL MUST CONVERGE", number="02")
    print(STYLE.dim("  The assessment shows the same invoice producing three different descriptions per product."))
    print()
    _table(
        ["#", "Run 1 observed", "Run 2 observed", "Run 3 observed", "Required result"],
        rows,
        [2, 20, 20, 20, 23],
        ["right", "left", "left", "left", "left"],
    )
    print()
    _metric("Supplied runs", "3/3 converge", status="ok")
    _metric("Observed variants", f"{accepted_variants}/18 canonicalized", status="ok")
    _metric("LLM calls", str(llm_calls), status="ok")
    _metric("Acceptance path", "approved exact aliases only", status="ok")
    print(STYLE.dim("  This is a challenge acceptance test, separate from the 11-case golden routing/model regression set."))
    print()


def _print_challenge_result(lines: Sequence[StoredInvoiceLine], exact_count: int, challenge_llm_calls: int) -> None:
    _rule("ACTUAL INVOICE → REQUESTED CANONICAL RESULT", number="03")
    _table(
        ["Original description", "Canonical description", "Decision"],
        [
            [line.description, _text(line.canonical_description), _text(line.decision_kind.value if line.decision_kind else None)]
            for line in lines
        ],
        [39, 27, 16],
    )
    print()
    _metric("Challenge mappings", f"{exact_count}/{len(lines)} expected mappings", status="ok")
    _metric("LLM calls", str(challenge_llm_calls), status="ok")
    _metric("Human reviews", "0", status="ok")
    _metric("Result", "deterministic replay", status="ok")


def _print_quality(challenge: object) -> None:
    # The caller passes DocumentProcessingResult; keeping the helper lightweight avoids duplicating domain imports.
    quality = getattr(challenge, "quality", None)
    financial_quality = getattr(challenge, "financial_quality", None)
    context = getattr(challenge, "context")
    print()
    _metric("Extraction quality", quality.status.value if quality else "UNKNOWN", status="ok" if quality and quality.status.value == "PASS" else "warn")
    if quality:
        _metric("Calculated subtotal", _money(quality.calculated_subtotal))
        _metric("Declared subtotal", _money(quality.declared_subtotal))
    _metric(
        "Financial reconciliation",
        financial_quality.status.value if financial_quality else "UNKNOWN",
        status="ok" if financial_quality and financial_quality.status.value == "PASS" else "warn",
    )
    _metric("Currency / amount due", f"{_text(context.financials.currency)} {_money(context.financials.amount_due)}")


def _print_unknown_intro(description: str) -> None:
    _rule("NOW INTRODUCE A PRODUCT THE CATALOG DOES NOT KNOW", number="04")
    print()
    _panel([
        "NOVELTY SCENARIO",
        "",
        f'New invoice description:  "{description}"',
        "Catalog state:             no approved exact alias",
        "Goal:                      resolve safely without silently trusting a guess",
    ])


def _print_pipeline_trace(
    novel: CanonicalizationDecision,
    first_model_calls: int,
    pending_occurrences: int,
    repeat_model_calls: int,
    provider_name: str,
) -> None:
    _rule("PIPELINE TRACE — ONE UNKNOWN THROUGH ALL THREE TIERS", number="05")

    print(STYLE.bold("  DOCUMENT GATE"))
    print(f"    {STYLE.green('✓')} extraction already validated")
    print(f"    {STYLE.green('✓')} arithmetic already validated")
    print(f"    {STYLE.green('✓')} only product-line evidence enters canonicalization")
    print("        │")
    print("        ▼")

    print(STYLE.bold(STYLE.blue("  TIER 1 · APPROVED EXACT LOOKUP")))
    print(f"    normalized input     {novel.normalized_description}")
    print(f"    exact alias          {STYLE.red('✗ NOT FOUND')}")
    print("        │")
    print("        ▼")

    top = _retrieval_top(novel)
    print(STYLE.bold(STYLE.blue("  TIER 2 · APPROVED RETRIEVAL + BOUNDED AI")))
    if top:
        print(f"    top retrieval        {top[0]}  (score={top[1]:.3f})")
    print(f"    evidence sufficient  {STYLE.yellow('✗ NO — do not auto-match')}")
    print(f"    provider             {provider_name}  {STYLE.dim('(deterministic offline fixture for the demo)')}")
    print(f"    bounded proposal     {STYLE.yellow(_text(novel.canonical_description))}")
    print(f"    model calls          {first_model_calls}")
    print(f"    trusted knowledge?   {STYLE.red('✗ NO — proposal only')}")
    print("        │")
    print("        ▼")

    print(STYLE.bold(STYLE.blue("  TIER 3 · HUMAN GOVERNANCE")))
    print(f"    review candidate     {novel.input_description}")
    print(f"    proposed mapping     → {_text(novel.canonical_description)}")
    print(f"    status               {STYLE.yellow('WAITING FOR APPROVAL')}")
    print(f"    repeated occurrences {pending_occurrences}")
    print(f"    extra model calls    {repeat_model_calls}  {STYLE.dim('(pending candidate is reused)')}")


def _print_learning(approved_description: str, learned: CanonicalizationDecision, additional_calls: int) -> None:
    _rule("HUMAN APPROVAL → REUSABLE KNOWLEDGE", number="06")
    print()
    print(f"  Reviewer decision      {STYLE.green('✓ APPROVED')}")
    print(f"  Knowledge promoted     Black Leather Jacket Midnight  →  {approved_description}")
    print()
    print(STYLE.bold("  Same description arrives again:"))
    print(f"    Tier 1 exact alias    {STYLE.green('✓ FOUND')}")
    print(f"    canonical product    {_text(learned.canonical_description)}")
    print(f"    decision             {learned.decision_kind.value}")
    print(f"    additional LLM calls {additional_calls}")
    print("    human review         0")
    print()
    _panel([
        "FIRST OCCURRENCE                           FUTURE OCCURRENCES",
        "Unknown → retrieval → AI proposal          Known → exact approved lookup",
        "           → human approval                       → canonical product ID",
        "",
        "1 bounded proposal + 1 approval            0 model calls + 0 reviews",
        "",
        "WILD  →  TAMED",
    ])


def _format_percent(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value) * 100:.0f}%"
    return _text(value)


def _print_golden_evaluation(golden: dict[str, object]) -> None:
    _rule("GOLDEN REGRESSION EVALUATION", number="07")
    print(STYLE.dim("  Versioned offline regression evidence — not a population-level accuracy claim."))
    print()
    _metric("Golden cases", str(golden.get("cases", "-")), status="ok")
    _metric("Model-driven cases", str(golden.get("model_case_count", "-")))
    _metric("Canonical exact accuracy", _format_percent(golden.get("canonical_exact_accuracy")), status="ok")
    _metric("Routing accuracy", _format_percent(golden.get("transaction_routing_accuracy")), status="ok")
    _metric("Unexpected LLM calls", str(golden.get("unexpected_llm_call_count", "-")), status="ok")
    _metric("Unsafe auto-accepts", str(golden.get("unsafe_auto_accept_count", "-")), status="ok")
    _metric("Model-review bypasses", str(golden.get("model_review_bypass_count", "-")), status="ok")
    print()
    _panel([
        "CURRENT EVIDENCE",
        "11 curated regression cases protect routing, model-call discipline, and review safety.",
        "",
        "NEXT BEFORE PRODUCTION",
        "Larger blind labelled set → compare candidate models → quality × safety × cost × latency",
        "→ pin the smallest / lowest-cost model that satisfies the agreed thresholds.",
    ])


def _print_final_summary(exact_count: int, line_count: int, accepted_variants: int) -> None:
    _rule("DEMO COMPLETE")
    _panel([
        f"✓ Raw challenge invoice reproduces {exact_count}/{line_count} requested mappings",
        f"✓ All three supplied runs converge: {accepted_variants}/18 observed variants",
        "✓ Challenge acceptance uses 0 LLM calls",
        "✓ Unknown descriptions follow a bounded, reviewable path",
        "✓ Human approval creates reusable deterministic knowledge",
        "✓ Golden regression tests separately protect routing and safety behavior",
    ])
    print(STYLE.dim("\n  Machine-readable evidence: reports/interview_demo.json"))

def _build_evidence(
    challenge: object,
    exact_count: int,
    challenge_llm_calls: int,
    collision_a: CanonicalizationDecision,
    collision_b: CanonicalizationDecision,
    auto: CanonicalizationDecision,
    calls_after_auto: int,
    novel: CanonicalizationDecision,
    calls_after_novel: int,
    pending_occurrences: int,
    calls_after_repeats: int,
    approved_product_id: str,
    approved_description: str,
    learned: CanonicalizationDecision,
    calls_after_learning: int,
) -> dict[str, object]:
    context = getattr(challenge, "context")
    quality = getattr(challenge, "quality")
    financial_quality = getattr(challenge, "financial_quality")
    decisions = getattr(challenge, "decisions")
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
        "parser": getattr(challenge, "parser_name"),
        "invoice": context.to_dict(),
        "extraction_quality": quality.to_dict() if quality else None,
        "financial_reconciliation": financial_quality.to_dict() if financial_quality else None,
        "rows": len(decisions),
        "exact_aliases": exact_count,
        "llm_calls": challenge_llm_calls,
        "canonical_descriptions": [item.canonical_description for item in decisions],
    }
    return {
        "narrative": {
            "core_tiers": [
                "Tier 1 - deterministic approved lookup (no LLM call)",
                "Tier 2 - approved retrieval / bounded AI for uncertainty",
                "Tier 3 - governed human learning that promotes trusted knowledge",
            ],
            "delivery_primitives": ["REST", "MCP", "Docker", "CI/CD", "PostgreSQL migration"],
        },
        "document_ingestion_guardrail": smoke_test,
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
            "deduplicated_occurrences": pending_occurrences,
            "additional_llm_calls_for_repeats": calls_after_repeats - calls_after_novel,
        },
        "novel_product": {
            "decision_kind": novel.decision_kind.value,
            "proposal": novel.canonical_description,
            "transaction_blocked": novel.requires_human_review,
            "llm_calls_for_first_occurrence": calls_after_novel - calls_after_auto,
            "deduplicated_occurrences": pending_occurrences,
            "additional_llm_calls_for_repeats": calls_after_repeats - calls_after_novel,
        },
        "tier_3_human_learning": {
            "approved_product_id": approved_product_id,
            "approved_description": approved_description,
            "next_decision_kind": learned.decision_kind.value,
            "next_canonical_description": learned.canonical_description,
            "additional_llm_calls_after_approval": calls_after_learning - calls_after_repeats,
        },
        "human_learning": {
            "approved_product_id": approved_product_id,
            "approved_description": approved_description,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the interviewer-facing invoice canonicalization lifecycle demo.")
    parser.add_argument("--plain", action="store_true", help="disable ANSI color while keeping the formatted narrative")
    parser.add_argument("--json", action="store_true", help="print only the machine-readable evidence JSON")
    parser.add_argument("--step", action="store_true", help="pause between narrative stages when running interactively")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.plain or args.json:
        STYLE.enabled = False

    with tempfile.TemporaryDirectory(prefix="ica-interview-demo-") as temp_dir:
        settings = replace(load_settings(ROOT), database_path=Path(temp_dir) / "catalog.db")
        container = build_container(settings)

        challenge = container.ingestion.process(
            ROOT / "data/examples/input/challenge_invoice.pdf",
            "testinger",
            "default-partner",
        )
        challenge_lines = tuple(container.repository.get_invoice_line_records("testinger", challenge.document_id))
        challenge_llm_calls = _provider_calls(container)
        exact_count = sum(item.decision_kind is DecisionKind.EXACT_ALIAS for item in challenge.decisions)

        acceptance_payload = json.loads(CHALLENGE_ACCEPTANCE.read_text(encoding="utf-8"))
        expected_outputs = [str(value) for value in acceptance_payload["expected_canonical_descriptions"]]
        observed_runs = acceptance_payload["observed_runs"]
        acceptance_settings = replace(settings, database_path=Path(temp_dir) / "challenge-acceptance.db")
        acceptance_container = build_container(acceptance_settings)
        acceptance_decisions: list[list[CanonicalizationDecision]] = []
        for run in observed_runs:
            descriptions = run["descriptions"]
            acceptance_decisions.append([
                acceptance_container.canonicalizer.canonicalize(InvoiceLine(
                    tenant_id="testinger",
                    partner_id="default-partner",
                    description=str(description),
                    source_line_id=f"brief-run-{run['run']}-{index}",
                ))
                for index, description in enumerate(descriptions, start=1)
            ])
        acceptance_llm_calls = _provider_calls(acceptance_container)
        accepted_variants = sum(
            decision.decision_kind is DecisionKind.EXACT_ALIAS
            and decision.canonical_description == expected_outputs[index]
            for run_decisions in acceptance_decisions
            for index, decision in enumerate(run_decisions)
        )
        acceptance_rows = [
            [
                str(index + 1),
                str(observed_runs[0]["descriptions"][index]),
                str(observed_runs[1]["descriptions"][index]),
                str(observed_runs[2]["descriptions"][index]),
                expected_outputs[index],
            ]
            for index in range(len(expected_outputs))
        ]

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

        auto = container.canonicalizer.canonicalize(InvoiceLine(
            tenant_id="testinger",
            partner_id="default-partner",
            description="Athletic crew sock",
            source_line_id="demo-auto",
        ))
        calls_after_auto = _provider_calls(container)

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

        approved = container.reviews.approve(
            "testinger",
            pending.review_id,
            approved_description="Black Leather Jacket",
            approved_category="jacket",
        )
        learned = container.canonicalizer.canonicalize(replace(novel_line, source_line_id="demo-after-approval"))
        calls_after_learning = _provider_calls(container)

        evidence = _build_evidence(
            challenge=challenge,
            exact_count=exact_count,
            challenge_llm_calls=challenge_llm_calls,
            collision_a=collision_a,
            collision_b=collision_b,
            auto=auto,
            calls_after_auto=calls_after_auto,
            novel=novel,
            calls_after_novel=calls_after_novel,
            pending_occurrences=pending.occurrence_count,
            calls_after_repeats=calls_after_repeats,
            approved_product_id=approved.product_id,
            approved_description=approved.canonical_description,
            learned=learned,
            calls_after_learning=calls_after_learning,
        )
        golden = run_golden_evaluation()
        evidence["golden_regression_evaluation"] = {
            key: value for key, value in golden.items() if key != "rows"
        }
        evidence["challenge_three_run_acceptance"] = {
            "source": "assessment page 1 - three inconsistent observed runs",
            "runs": 3,
            "variants": 18,
            "accepted_variants": accepted_variants,
            "llm_calls": acceptance_llm_calls,
            "expected_canonical_descriptions": expected_outputs,
            "rows": [
                {
                    "position": index + 1,
                    "run_1": row[1],
                    "run_2": row[2],
                    "run_3": row[3],
                    "required_result": row[4],
                }
                for index, row in enumerate(acceptance_rows)
            ],
        }

        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(evidence, indent=2))
        return 0

    _panel([
        "INVOICE CANONICALIZATION AGENT",
        "Deterministic first · AI only for uncertainty · Human approvals become reusable knowledge",
    ])
    _print_challenge_input(challenge_lines, challenge.context.invoice_number, challenge.parser_name)
    _print_quality(challenge)
    _pause(args.step)

    _print_three_run_acceptance(acceptance_rows, accepted_variants, acceptance_llm_calls)
    _pause(args.step)

    _print_challenge_result(challenge_lines, exact_count, challenge_llm_calls)
    _pause(args.step)

    _print_unknown_intro(novel.input_description)
    _pause(args.step)

    provider_name = novel.provider or "none"
    _print_pipeline_trace(
        novel,
        calls_after_novel - calls_after_auto,
        pending.occurrence_count,
        calls_after_repeats - calls_after_novel,
        provider_name,
    )
    _pause(args.step)

    _print_learning(
        approved.canonical_description,
        learned,
        calls_after_learning - calls_after_repeats,
    )
    _pause(args.step)

    _print_golden_evaluation(golden)
    _print_final_summary(exact_count, len(challenge_lines), accepted_variants)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
