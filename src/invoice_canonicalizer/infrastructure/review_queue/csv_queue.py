"""Business objective: let a reviewer manage pending knowledge decisions in Excel or any CSV editor.

Technical description: serializes deduplicated review records to a stable CSV schema whose final column is the human-editable status/action.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from invoice_canonicalizer.domain.models import ReviewAction, ReviewRecord

CSV_FIELDS = (
    "review_id",
    "tenant_id",
    "partner_id",
    "candidate_key",
    "occurrence_count",
    "affected_value",
    "affected_values_json",
    "currency",
    "first_seen_at",
    "last_seen_at",
    "source_description",
    "source_variants_json",
    "source_line_ids_json",
    "proposed_description",
    "proposed_category",
    "proposed_attributes_json",
    "target_product_id",
    "decision_score",
    "retrieval_score",
    "retrieval_margin",
    "priority_score",
    "llm_used",
    "provider",
    "model",
    "prompt_version",
    "risk_flags_json",
    "evidence_json",
    "blocks_transaction",
    "approved_description_override",
    "target_product_id_override",
    "category_override",
    "reviewer_notes",
    "status",
)

EDITABLE_FIELDS = (
    "approved_description_override",
    "target_product_id_override",
    "category_override",
    "reviewer_notes",
    "status",
)




def _spreadsheet_safe(value: str) -> str:
    """Prevent untrusted text from being interpreted as a spreadsheet formula when CSV is opened."""
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class CsvReviewQueueStore:
    def read_rows(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(CSV_FIELDS):
                raise ValueError("review queue CSV header does not match the versioned schema")
            return [dict(row) for row in reader]

    def write_rows(self, path: Path, rows: Iterable[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                normalized = {field: row.get(field, "") for field in CSV_FIELDS}
                writer.writerow(normalized)

    def export_pending(self, path: Path, reviews: Iterable[ReviewRecord]) -> int:
        existing = {row["review_id"]: row for row in self.read_rows(path)} if path.exists() else {}
        rows: list[dict[str, object]] = []
        for review in reviews:
            row = self.review_to_row(review)
            prior = existing.get(review.review_id)
            if prior:
                for field in EDITABLE_FIELDS:
                    row[field] = prior.get(field, row[field])
            rows.append(row)
        self.write_rows(path, rows)
        return len(rows)

    def append_archive(self, path: Path, row: dict[str, str], outcome: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "processed_at": datetime.now(UTC).isoformat(),
            "queue_row": row,
            "outcome": outcome,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    @staticmethod
    def review_to_row(review: ReviewRecord) -> dict[str, object]:
        return {
            "review_id": review.review_id,
            "tenant_id": review.tenant_id,
            "partner_id": review.partner_id,
            "candidate_key": review.candidate_key,
            "occurrence_count": review.occurrence_count,
            "affected_value": format(review.affected_value, "f"),
            "affected_values_json": json.dumps({key: format(value, "f") for key, value in sorted(review.affected_values_by_currency.items())}, sort_keys=True),
            "currency": review.currency or "",
            "first_seen_at": review.first_seen_at or "",
            "last_seen_at": review.last_seen_at or "",
            "source_description": _spreadsheet_safe(review.source_description),
            "source_variants_json": json.dumps(list(review.source_variants), ensure_ascii=False),
            "source_line_ids_json": json.dumps(list(review.source_line_ids), ensure_ascii=False),
            "proposed_description": _spreadsheet_safe(review.proposed_description),
            "proposed_category": _spreadsheet_safe(review.proposed_category),
            "proposed_attributes_json": json.dumps(review.attributes, sort_keys=True),
            "target_product_id": review.target_product_id or "",
            "decision_score": review.decision_score,
            "retrieval_score": review.retrieval_score,
            "retrieval_margin": review.retrieval_margin,
            "priority_score": review.priority_score,
            "llm_used": str(review.llm_used).lower(),
            "provider": review.provider or "",
            "model": review.model or "",
            "prompt_version": review.prompt_version or "",
            "risk_flags_json": json.dumps(list(review.risk_flags)),
            "evidence_json": json.dumps(list(review.evidence), sort_keys=True),
            "blocks_transaction": str(review.blocks_transaction).lower(),
            "approved_description_override": "",
            "target_product_id_override": "",
            "category_override": "",
            "reviewer_notes": "",
            "status": ReviewAction.WAITING.value,
        }
