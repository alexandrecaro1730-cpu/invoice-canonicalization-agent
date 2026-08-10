"""Business objective: define auditable invoice, party, financial, product, review, and decision records independent of frameworks.

Technical description: immutable dataclasses model invoice headers and parties, exact Decimal financials, line items, canonical knowledge, extraction/reconciliation evidence, clustered reviews, and deterministic/AI decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from invoice_canonicalizer.utils.money import ZERO, decimal_text, to_decimal


class DecisionKind(StrEnum):
    EXACT_ALIAS = "exact_alias"
    CACHED = "cached"
    AUTO_RETRIEVAL = "auto_retrieval"
    GENERATED_CANDIDATE = "generated_candidate"
    PENDING_REVIEW_REUSE = "pending_review_reuse"
    ABSTAINED = "abstained"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewAction(StrEnum):
    """Human-editable actions accepted by the CSV review queue."""

    WAITING = "waiting_for_approval"
    APPROVE_EXISTING = "approve_existing"
    APPROVE_NEW = "approve_new"
    EDIT_AND_APPROVE = "edit_and_approve"
    REDIRECT = "redirect"
    REJECT = "reject"
    DEFER = "defer"


class ExtractionQualityStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class PartyRole(StrEnum):
    """Invoice roles are descriptive evidence and never override authenticated tenant scope."""

    SELLER = "seller"
    BILL_TO = "bill_to"
    SHIP_TO = "ship_to"


@dataclass(frozen=True, slots=True)
class InvoiceParty:
    """One party printed on an invoice, stored as evidence for routing, audit, and entity resolution."""

    role: PartyRole
    name: str
    contact_name: str | None = None
    address_lines: tuple[str, ...] = ()
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    external_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "name": self.name,
            "contact_name": self.contact_name,
            "address_lines": list(self.address_lines),
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "external_id": self.external_id,
        }


@dataclass(frozen=True, slots=True)
class InvoiceFinancials:
    """Document-level financial fields retained for reconciliation and downstream accounting, not product naming."""

    currency: str | None = None
    subtotal: Decimal | None = None
    discount_total: Decimal | None = None
    subtotal_after_discount: Decimal | None = None
    tax_rate_percent: Decimal | None = None
    tax_total: Decimal | None = None
    shipping_total: Decimal | None = None
    amount_due: Decimal | None = None

    def __post_init__(self) -> None:
        for name in (
            "subtotal",
            "discount_total",
            "subtotal_after_discount",
            "tax_rate_percent",
            "tax_total",
            "shipping_total",
            "amount_due",
        ):
            object.__setattr__(self, name, to_decimal(getattr(self, name)))
        if self.currency:
            object.__setattr__(self, "currency", self.currency.strip().upper())

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "subtotal": decimal_text(self.subtotal),
            "discount_total": decimal_text(self.discount_total),
            "subtotal_after_discount": decimal_text(self.subtotal_after_discount),
            "tax_rate_percent": decimal_text(self.tax_rate_percent),
            "tax_total": decimal_text(self.tax_total),
            "shipping_total": decimal_text(self.shipping_total),
            "amount_due": decimal_text(self.amount_due),
        }


@dataclass(frozen=True, slots=True)
class InvoiceContext:
    """Header and counterparty context retained with the invoice but excluded from canonicalization prompts by default."""

    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    payment_terms: str | None = None
    parties: tuple[InvoiceParty, ...] = ()
    financials: InvoiceFinancials = field(default_factory=InvoiceFinancials)
    metadata: dict[str, Any] = field(default_factory=dict)

    def party(self, role: PartyRole) -> InvoiceParty | None:
        return next((party for party in self.parties if party.role is role), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "due_date": self.due_date,
            "payment_terms": self.payment_terms,
            "parties": [party.to_dict() for party in self.parties],
            "financials": self.financials.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    tenant_id: str
    partner_id: str
    description: str
    source_line_id: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.partner_id.strip():
            raise ValueError("tenant_id and partner_id are required")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if len(self.description) > 2_000:
            raise ValueError("description exceeds 2,000 characters")
        object.__setattr__(self, "quantity", to_decimal(self.quantity))
        object.__setattr__(self, "unit_price", to_decimal(self.unit_price))
        object.__setattr__(self, "total", to_decimal(self.total))
        if self.currency:
            object.__setattr__(self, "currency", self.currency.strip().upper())


@dataclass(frozen=True, slots=True)
class StoredInvoiceLine:
    """Raw invoice line plus its persisted canonical outcome for audit/read APIs."""

    source_line_id: str
    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = None
    canonical_product_id: str | None = None
    canonical_description: str | None = None
    decision_kind: DecisionKind | None = None
    requires_human_review: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", to_decimal(self.quantity))
        object.__setattr__(self, "unit_price", to_decimal(self.unit_price))
        object.__setattr__(self, "total", to_decimal(self.total))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_line_id": self.source_line_id,
            "description": self.description,
            "quantity": decimal_text(self.quantity),
            "unit_price": decimal_text(self.unit_price),
            "total": decimal_text(self.total),
            "currency": self.currency,
            "canonical_product_id": self.canonical_product_id,
            "canonical_description": self.canonical_description,
            "decision_kind": self.decision_kind.value if self.decision_kind else None,
            "requires_human_review": self.requires_human_review,
        }


@dataclass(frozen=True, slots=True)
class CanonicalProduct:
    product_id: str
    tenant_id: str
    partner_id: str
    canonical_description: str
    category: str
    attributes: dict[str, str] = field(default_factory=dict)
    style_version: str = "1"


@dataclass(frozen=True, slots=True)
class AliasRecord:
    alias_id: str
    tenant_id: str
    partner_id: str
    product_id: str
    alias_text: str
    normalized_alias: str
    language: str = "en"
    approved: bool = True


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    product: CanonicalProduct
    score: float
    lexical_score: float
    token_score: float
    attribute_score: float
    matched_alias: str
    conflicting_attributes: tuple[str, ...] = ()
    semantic_score: float = 0.0


@dataclass(frozen=True, slots=True)
class ProviderResult:
    proposed_description: str
    category: str
    attributes: dict[str, str]
    rationale: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class ExtractionProviderResult:
    """Strict model output used only when deterministic line-item extraction cannot succeed."""

    lines: tuple[dict[str, str | None], ...]
    declared_subtotal: Decimal | None
    rationale: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class CanonicalizationDecision:
    decision_id: str
    tenant_id: str
    partner_id: str
    source_line_id: str
    input_description: str
    normalized_description: str
    decision_kind: DecisionKind
    canonical_product_id: str | None
    canonical_description: str | None
    category: str | None
    confidence: float
    requires_human_review: bool
    review_id: str | None
    evidence: tuple[dict[str, Any], ...]
    taxonomy_version: str
    prompt_version: str | None
    model: str | None
    provider: str | None
    estimated_cost_usd: Decimal
    flags: tuple[str, ...] = ()
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision_kind"] = self.decision_kind.value
        payload["estimated_cost_usd"] = decimal_text(self.estimated_cost_usd)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CanonicalizationDecision":
        data = dict(payload)
        data["decision_kind"] = DecisionKind(data["decision_kind"])
        data["evidence"] = tuple(data.get("evidence", ()))
        data["flags"] = tuple(data.get("flags", ()))
        data["estimated_cost_usd"] = to_decimal(data.get("estimated_cost_usd"), default=ZERO)
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """One deduplicated unresolved knowledge candidate presented to a human reviewer."""

    review_id: str
    tenant_id: str
    partner_id: str
    candidate_key: str
    source_description: str
    proposed_description: str
    proposed_category: str
    attributes: dict[str, str]
    evidence: tuple[dict[str, Any], ...]
    decision_score: float
    retrieval_score: float
    retrieval_margin: float
    priority_score: float
    llm_used: bool
    blocks_transaction: bool
    source_variants: tuple[str, ...] = ()
    source_line_ids: tuple[str, ...] = ()
    occurrence_count: int = 1
    affected_value: Decimal = ZERO
    affected_values_by_currency: dict[str, Decimal] = field(default_factory=dict)
    currency: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    risk_flags: tuple[str, ...] = ()
    prompt_version: str | None = None
    model: str | None = None
    provider: str | None = None
    status: ReviewStatus = ReviewStatus.PENDING
    target_product_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionQualityReport:
    """Machine-checkable evidence that line-item extraction is arithmetically coherent."""

    status: ExtractionQualityStatus
    rows_extracted: int
    rows_with_complete_arithmetic: int
    rows_arithmetic_valid: int
    rows_arithmetic_invalid: int
    calculated_subtotal: Decimal | None
    declared_subtotal: Decimal | None
    subtotal_matches: bool | None
    checks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "rows_extracted": self.rows_extracted,
            "rows_with_complete_arithmetic": self.rows_with_complete_arithmetic,
            "rows_arithmetic_valid": self.rows_arithmetic_valid,
            "rows_arithmetic_invalid": self.rows_arithmetic_invalid,
            "calculated_subtotal": decimal_text(self.calculated_subtotal),
            "declared_subtotal": decimal_text(self.declared_subtotal),
            "subtotal_matches": self.subtotal_matches,
            "checks": list(self.checks),
        }


@dataclass(frozen=True, slots=True)
class FinancialQualityReport:
    """Non-blocking document-level reconciliation evidence for discount, tax, shipping, and amount due."""

    status: ExtractionQualityStatus
    discount_reconciles: bool | None = None
    tax_reconciles: bool | None = None
    amount_due_reconciles: bool | None = None
    checks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "discount_reconciles": self.discount_reconciles,
            "tax_reconciles": self.tax_reconciles,
            "amount_due_reconciles": self.amount_due_reconciles,
            "checks": list(self.checks),
        }


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    document_id: str
    source_name: str
    parser_name: str
    lines: tuple[InvoiceLine, ...]
    context: InvoiceContext = field(default_factory=InvoiceContext)
    warnings: tuple[str, ...] = ()
    quality: ExtractionQualityReport | None = None
    financial_quality: FinancialQualityReport | None = None


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    document_id: str
    source_name: str
    parser_name: str
    decisions: tuple[CanonicalizationDecision, ...]
    context: InvoiceContext = field(default_factory=InvoiceContext)
    warnings: tuple[str, ...] = ()
    quality: ExtractionQualityReport | None = None
    financial_quality: FinancialQualityReport | None = None
