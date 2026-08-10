"""Business objective: publish explicit and stable HTTP contracts without letting production callers choose tenant scope.

Technical description: uses Pydantic v2 schemas with Decimal invoice values; tenant_id remains optional only for auth-disabled local compatibility and is verified against authenticated principals when auth is enabled.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class CanonicalizeRequest(BaseModel):
    tenant_id: str | None = Field(default=None, min_length=1, max_length=100)
    partner_id: str = Field(min_length=1, max_length=100)
    source_line_id: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)


class DecisionResponse(BaseModel):
    decision_id: str
    decision_kind: str
    canonical_product_id: str | None
    canonical_description: str | None
    category: str | None
    confidence: float
    requires_human_review: bool
    review_id: str | None
    evidence: list[dict[str, Any]]
    flags: list[str]
    taxonomy_version: str
    prompt_version: str | None
    model: str | None
    provider: str | None
    estimated_cost_usd: Decimal
    from_cache: bool


class ReviewApprovalRequest(BaseModel):
    tenant_id: str | None = Field(default=None, min_length=1, max_length=100)
    approved_description: str = Field(min_length=1, max_length=120)
    target_product_id: str | None = None
    approved_category: str | None = Field(default=None, max_length=120)


class ReviewRejectionRequest(BaseModel):
    tenant_id: str | None = Field(default=None, min_length=1, max_length=100)
    reviewer_notes: str = Field(default="", max_length=2_000)


class ReviewActionRequest(BaseModel):
    tenant_id: str | None = Field(default=None, min_length=1, max_length=100)
    action: Literal[
        "waiting_for_approval",
        "approve_existing",
        "approve_new",
        "edit_and_approve",
        "redirect",
        "reject",
        "defer",
    ]
    approved_description: str | None = Field(default=None, max_length=120)
    target_product_id: str | None = Field(default=None, max_length=200)
    approved_category: str | None = Field(default=None, max_length=120)
    reviewer_notes: str = Field(default="", max_length=2_000)
