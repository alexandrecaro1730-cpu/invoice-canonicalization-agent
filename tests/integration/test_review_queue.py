"""Business objective: prove a reviewer can manage weekly knowledge promotion in a simple CSV without losing auditability.

Technical description: exercises export, human-edited actions, archive creation, queue clearing, deferral, redirect, and deterministic learning.
"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from invoice_canonicalizer.domain.models import DecisionKind, InvoiceLine, ReviewAction
from invoice_canonicalizer.infrastructure.review_queue.csv_queue import CSV_FIELDS


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_csv_status_is_last_and_defaults_to_waiting(container, tmp_path: Path) -> None:
    decision = container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Black Leather Jacket Midnight", source_line_id="queue-1", total=250, currency="EUR",
    ))
    assert decision.review_id
    path = tmp_path / "review_queue.csv"
    assert container.review_queue.export("testinger", path) == 1
    rows = _read(path)
    assert list(rows[0].keys())[-1] == "status"
    assert rows[0]["status"] == ReviewAction.WAITING.value
    assert rows[0]["llm_used"] == "true"
    assert rows[0]["occurrence_count"] == "1"
    assert rows[0]["proposed_description"] == "Black Leather Jacket"


def test_process_approve_new_archives_and_clears_active_queue(container, tmp_path: Path) -> None:
    line = InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Black Leather Jacket Midnight", source_line_id="queue-approve-1",
    )
    first = container.canonicalizer.canonicalize(line)
    path = tmp_path / "review_queue.csv"
    archive = tmp_path / "review_archive.jsonl"
    container.review_queue.export("testinger", path)
    rows = _read(path)
    rows[0]["approved_description_override"] = "Black Leather Jacket"
    rows[0]["category_override"] = "jacket"
    rows[0]["status"] = ReviewAction.APPROVE_NEW.value
    _write(path, rows)

    result = container.review_queue.process(path, archive)
    assert result["processed"] == 1
    assert result["remaining"] == 0
    assert result["errors"] == []
    assert _read(path) == []
    assert archive.read_text(encoding="utf-8").strip()

    repeated = container.canonicalizer.canonicalize(replace(line, source_line_id="queue-approve-2"))
    assert repeated.decision_kind is DecisionKind.EXACT_ALIAS
    assert repeated.canonical_description == "Black Leather Jacket"


def test_defer_stays_in_queue_and_action_resets_to_waiting(container, tmp_path: Path) -> None:
    container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Urban Denim Midnight", source_line_id="queue-defer-1",
    ))
    path = tmp_path / "review_queue.csv"
    archive = tmp_path / "review_archive.jsonl"
    container.review_queue.export("testinger", path)
    rows = _read(path)
    rows[0]["reviewer_notes"] = "Need merchandising input"
    rows[0]["status"] = ReviewAction.DEFER.value
    _write(path, rows)

    result = container.review_queue.process(path, archive)
    assert result["deferred"] == 1
    assert result["remaining"] == 1
    remaining = _read(path)
    assert remaining[0]["status"] == ReviewAction.WAITING.value
    assert remaining[0]["reviewer_notes"] == "Need merchandising input"


def test_redirect_maps_candidate_to_human_selected_existing_product(container, tmp_path: Path) -> None:
    line = InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Urban Denim Midnight", source_line_id="queue-redirect-1",
    )
    container.canonicalizer.canonicalize(line)
    path = tmp_path / "review_queue.csv"
    archive = tmp_path / "review_archive.jsonl"
    container.review_queue.export("testinger", path)
    rows = _read(path)
    rows[0]["target_product_id_override"] = "product-casual-shorts"
    rows[0]["status"] = ReviewAction.REDIRECT.value
    _write(path, rows)

    result = container.review_queue.process(path, archive)
    assert result["processed"] == 1
    repeated = container.canonicalizer.canonicalize(replace(line, source_line_id="queue-redirect-2"))
    assert repeated.decision_kind is DecisionKind.EXACT_ALIAS
    assert repeated.canonical_product_id == "product-casual-shorts"


def test_reject_clears_active_queue_but_does_not_promote_alias(container, tmp_path: Path) -> None:
    line = InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Urban Denim Midnight", source_line_id="queue-reject-1",
    )
    container.canonicalizer.canonicalize(line)
    path = tmp_path / "review_queue.csv"
    archive = tmp_path / "review_archive.jsonl"
    container.review_queue.export("testinger", path)
    rows = _read(path)
    rows[0]["status"] = ReviewAction.REJECT.value
    _write(path, rows)
    result = container.review_queue.process(path, archive)
    assert result["processed"] == 1
    assert _read(path) == []
    assert container.repository.find_approved_alias("testinger", "default-partner", "urban denim midnight") is None


def test_csv_neutralizes_spreadsheet_formula_injection(container, tmp_path: Path) -> None:
    container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="=HYPERLINK(\"https://evil.invalid\",\"click\")", source_line_id="queue-formula-1",
    ))
    path = tmp_path / "review_queue.csv"
    container.review_queue.export("testinger", path)
    rows = _read(path)
    assert rows[0]["source_description"].startswith("'=")
