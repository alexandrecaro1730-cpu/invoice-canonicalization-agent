"""Business objective: support a scalable weekly human-review workflow without blocking routine invoice processing.

Technical description: exports pending clustered candidates to CSV, applies human-edited actions transactionally, archives outcomes, and rewrites the active queue with only unresolved rows.
"""

from __future__ import annotations

from pathlib import Path

from invoice_canonicalizer.application.reviews import ReviewService
from invoice_canonicalizer.domain.models import ReviewAction
from invoice_canonicalizer.infrastructure.review_queue.csv_queue import CsvReviewQueueStore


class ReviewQueueService:
    def __init__(self, reviews: ReviewService, store: CsvReviewQueueStore | None = None) -> None:
        self.reviews = reviews
        self.store = store or CsvReviewQueueStore()

    def export(self, tenant_id: str, path: Path, limit: int = 10_000) -> int:
        pending = self.reviews.list_pending(tenant_id, limit=limit)
        return self.store.export_pending(path, pending)

    def process(self, path: Path, archive_path: Path) -> dict[str, object]:
        rows = self.store.read_rows(path)
        processed = 0
        deferred = 0
        errors: list[dict[str, str]] = []
        touched_tenants: set[str] = set()

        for queue_row in rows:
            tenant_id = queue_row["tenant_id"].strip()
            review_id = queue_row["review_id"].strip()
            touched_tenants.add(tenant_id)
            raw_status = (queue_row.get("status") or ReviewAction.WAITING.value).strip().lower()
            try:
                action = ReviewAction(raw_status)
            except ValueError:
                errors.append({"review_id": review_id, "error": f"invalid status/action: {raw_status}"})
                continue
            if action is ReviewAction.WAITING:
                continue
            if action is ReviewAction.DEFER:
                try:
                    outcome = self.reviews.apply_action(
                        tenant_id=tenant_id,
                        review_id=review_id,
                        action=action,
                        reviewer_notes=queue_row.get("reviewer_notes", ""),
                    )
                    self.store.append_archive(archive_path, queue_row, outcome)
                    deferred += 1
                except Exception as exc:  # preserve row for manual correction
                    errors.append({"review_id": review_id, "error": str(exc)})
                continue
            try:
                outcome = self.reviews.apply_action(
                    tenant_id=tenant_id,
                    review_id=review_id,
                    action=action,
                    approved_description=(queue_row.get("approved_description_override") or "").strip() or None,
                    target_product_id=(queue_row.get("target_product_id_override") or "").strip() or None,
                    approved_category=(queue_row.get("category_override") or "").strip() or None,
                    reviewer_notes=queue_row.get("reviewer_notes", ""),
                )
                self.store.append_archive(archive_path, queue_row, outcome)
                processed += 1
            except Exception as exc:  # queue processing must never silently drop failed human actions
                errors.append({"review_id": review_id, "error": str(exc)})

        # Rewrite from authoritative pending state. Successfully processed rows disappear.
        # Deferred/failed rows stay pending, but their action is reset to waiting so processing is idempotent.
        refreshed = []
        for tenant_id in sorted(touched_tenants):
            refreshed.extend(self.reviews.list_pending(tenant_id, limit=10_000))
        original_by_id = {row["review_id"]: row for row in rows}
        error_by_id = {item["review_id"]: item["error"] for item in errors}
        output_rows: list[dict[str, object]] = []
        for review in refreshed:
            output_row = self.store.review_to_row(review)
            original = original_by_id.get(review.review_id, {})
            for field in ("approved_description_override", "target_product_id_override", "category_override", "reviewer_notes"):
                output_row[field] = original.get(field, "")
            if review.review_id in error_by_id:
                prefix = str(output_row.get("reviewer_notes", "")).strip()
                output_row["reviewer_notes"] = (prefix + " | " if prefix else "") + "PROCESSING_ERROR: " + error_by_id[review.review_id]
            output_row["status"] = ReviewAction.WAITING.value
            output_rows.append(output_row)
        self.store.write_rows(path, output_rows)
        return {
            "processed": processed,
            "deferred": deferred,
            "remaining": len(refreshed),
            "errors": errors,
            "queue_path": str(path),
            "archive_path": str(archive_path),
        }
