"""Business objective: turn human decisions into reusable approved knowledge safely.

Technical description: validates flexible review actions, promotes only approved knowledge, and records an immutable audit trail.
"""

from __future__ import annotations

from decimal import Decimal

from invoice_canonicalizer.application.ports import CatalogRepository
from invoice_canonicalizer.domain.errors import ReviewConflictError
from invoice_canonicalizer.domain.models import CanonicalProduct, ReviewAction, ReviewRecord, ReviewStatus


class ReviewService:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def list_pending(self, tenant_id: str, limit: int = 100) -> list[ReviewRecord]:
        return list(self.repository.list_reviews(tenant_id, ReviewStatus.PENDING, limit=limit, sort_by_priority=True))

    def summary(self, tenant_id: str, limit: int = 10_000) -> dict[str, object]:
        pending = self.list_pending(tenant_id, limit=limit)
        affected_lines = sum(item.occurrence_count for item in pending)
        totals: dict[str, Decimal] = {}
        for item in pending:
            for currency, amount in item.affected_values_by_currency.items():
                totals[currency] = totals.get(currency, Decimal("0")) + amount
        affected_by_currency: dict[str, object] = {key: format(value, "f") for key, value in sorted(totals.items())}
        top_ten = pending[:10]
        return {
            "pending_unique_candidates": len(pending),
            "affected_invoice_lines": affected_lines,
            "affected_values_by_currency": affected_by_currency,
            "blocking_candidates": sum(1 for item in pending if item.blocks_transaction),
            "nonblocking_alias_promotions": sum(1 for item in pending if not item.blocks_transaction),
            "llm_assisted_candidates": sum(1 for item in pending if item.llm_used),
            "top_10_affected_lines": sum(item.occurrence_count for item in top_ten),
            "top_10_review_leverage": round(
                (sum(item.occurrence_count for item in top_ten) / affected_lines) if affected_lines else 0.0,
                4,
            ),
        }

    def approve(
        self,
        tenant_id: str,
        review_id: str,
        approved_description: str,
        target_product_id: str | None = None,
        approved_category: str | None = None,
    ) -> CanonicalProduct:
        product = self.repository.approve_review(
            tenant_id=tenant_id,
            review_id=review_id,
            approved_description=approved_description,
            target_product_id=target_product_id,
            approved_category=approved_category,
        )
        self.repository.record_audit(tenant_id, "review_approved", {
            "review_id": review_id, "product_id": product.product_id,
            "target_product_id": target_product_id,
        })
        return product

    def reject(self, tenant_id: str, review_id: str, reviewer_notes: str = "") -> ReviewRecord:
        review = self.repository.reject_review(tenant_id, review_id)
        self.repository.record_audit(tenant_id, "review_rejected", {
            "review_id": review_id, "reviewer_notes": reviewer_notes,
        })
        return review

    def defer(self, tenant_id: str, review_id: str, reviewer_notes: str = "") -> ReviewRecord:
        review = self.repository.get_review(tenant_id, review_id)
        if review is None or review.status is not ReviewStatus.PENDING:
            raise ReviewConflictError(f"review {review_id} is not pending")
        self.repository.record_audit(tenant_id, "review_deferred", {
            "review_id": review_id, "reviewer_notes": reviewer_notes,
        })
        return review

    def apply_action(
        self,
        *,
        tenant_id: str,
        review_id: str,
        action: ReviewAction,
        approved_description: str | None = None,
        target_product_id: str | None = None,
        approved_category: str | None = None,
        reviewer_notes: str = "",
    ) -> dict[str, object]:
        review = self.repository.get_review(tenant_id, review_id)
        if review is None:
            raise ReviewConflictError(f"review {review_id} does not exist")
        if review.status is not ReviewStatus.PENDING:
            raise ReviewConflictError(f"review {review_id} is already {review.status.value}")

        if action is ReviewAction.REJECT:
            rejected = self.reject(tenant_id, review_id, reviewer_notes)
            return {"status": rejected.status.value, "review_id": review_id}
        if action is ReviewAction.DEFER:
            self.defer(tenant_id, review_id, reviewer_notes)
            return {"status": ReviewAction.WAITING.value, "review_id": review_id, "deferred": True}
        if action is ReviewAction.WAITING:
            return {"status": ReviewAction.WAITING.value, "review_id": review_id}

        if action is ReviewAction.REDIRECT:
            if not target_product_id:
                raise ReviewConflictError("redirect requires target_product_id_override")
            product = self.approve(
                tenant_id, review_id, approved_description or review.proposed_description,
                target_product_id=target_product_id, approved_category=approved_category,
            )
        elif action is ReviewAction.APPROVE_EXISTING:
            target = target_product_id or review.target_product_id
            if not target:
                raise ReviewConflictError("approve_existing requires an existing target product")
            product = self.approve(
                tenant_id, review_id, approved_description or review.proposed_description,
                target_product_id=target, approved_category=approved_category,
            )
        elif action in {ReviewAction.APPROVE_NEW, ReviewAction.EDIT_AND_APPROVE}:
            target = target_product_id if action is ReviewAction.EDIT_AND_APPROVE else None
            product = self.approve(
                tenant_id, review_id, approved_description or review.proposed_description,
                target_product_id=target, approved_category=approved_category,
            )
        else:
            raise ReviewConflictError(f"unsupported review action: {action.value}")

        self.repository.record_audit(tenant_id, "review_action_applied", {
            "review_id": review_id,
            "action": action.value,
            "product_id": product.product_id,
            "reviewer_notes": reviewer_notes,
        })
        return {
            "status": "approved",
            "review_id": review_id,
            "action": action.value,
            "product_id": product.product_id,
            "canonical_description": product.canonical_description,
        }
