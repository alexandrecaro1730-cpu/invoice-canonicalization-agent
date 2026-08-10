"""Business objective: persist invoice evidence, parties, exact financials, approved knowledge, decisions, clustered reviews, and audit events locally.

Technical description: implements transactional SQLite storage with tenant/partner-scoped invoice/header/party/line tables, WAL concurrency, atomic pending-candidate deduplication, Decimal-as-text persistence, and auditable review promotion.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Sequence

from invoice_canonicalizer.application.review_scoring import review_priority_score
from invoice_canonicalizer.domain.errors import ReviewConflictError, ReviewNotFoundError
from invoice_canonicalizer.domain.models import (
    AliasRecord,
    CanonicalProduct,
    CanonicalizationDecision,
    DecisionKind,
    ExtractionQualityReport,
    ExtractionQualityStatus,
    FinancialQualityReport,
    InvoiceContext,
    InvoiceFinancials,
    InvoiceLine,
    InvoiceParty,
    ParsedDocument,
    PartyRole,
    ReviewRecord,
    ReviewStatus,
    StoredInvoiceLine,
)
from invoice_canonicalizer.utils.money import ZERO, decimal_text, to_decimal
from invoice_canonicalizer.utils.text import normalize_text

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS canonical_products (
    product_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    canonical_description TEXT NOT NULL,
    category TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    style_version TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(product_id, tenant_id, partner_id)
);
CREATE INDEX IF NOT EXISTS idx_products_scope ON canonical_products(tenant_id, partner_id, active);
CREATE TABLE IF NOT EXISTS product_aliases (
    alias_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    alias_text TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    language TEXT NOT NULL,
    approved INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(product_id, tenant_id, partner_id)
        REFERENCES canonical_products(product_id, tenant_id, partner_id),
    UNIQUE(tenant_id, partner_id, normalized_alias, language)
);
CREATE INDEX IF NOT EXISTS idx_alias_scope ON product_aliases(tenant_id, partner_id, normalized_alias, approved);
CREATE TABLE IF NOT EXISTS invoice_documents (
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    invoice_number TEXT,
    invoice_date TEXT,
    due_date TEXT,
    payment_terms TEXT,
    currency TEXT,
    subtotal TEXT,
    discount_total TEXT,
    subtotal_after_discount TEXT,
    tax_rate_percent TEXT,
    tax_total TEXT,
    shipping_total TEXT,
    amount_due TEXT,
    warnings_json TEXT NOT NULL,
    extraction_quality_json TEXT,
    financial_quality_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, document_id)
);
CREATE INDEX IF NOT EXISTS idx_invoice_scope_number
    ON invoice_documents(tenant_id, partner_id, invoice_number);
CREATE TABLE IF NOT EXISTS invoice_parties (
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    contact_name TEXT,
    address_lines_json TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    website TEXT,
    external_id TEXT,
    PRIMARY KEY (tenant_id, document_id, role),
    FOREIGN KEY (tenant_id, document_id) REFERENCES invoice_documents(tenant_id, document_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_invoice_party_name
    ON invoice_parties(tenant_id, role, name);
CREATE TABLE IF NOT EXISTS invoice_lines (
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_line_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity TEXT,
    unit_price TEXT,
    line_total TEXT,
    currency TEXT,
    metadata_json TEXT NOT NULL,
    decision_id TEXT,
    canonical_product_id TEXT,
    canonical_description TEXT,
    decision_kind TEXT,
    requires_human_review INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, document_id, source_line_id),
    FOREIGN KEY (tenant_id, document_id) REFERENCES invoice_documents(tenant_id, document_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_scope
    ON invoice_lines(tenant_id, partner_id, document_id);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    line_hash TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, line_hash, taxonomy_version)
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    source_description TEXT NOT NULL,
    source_variants_json TEXT NOT NULL,
    source_line_ids_json TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL,
    affected_value TEXT NOT NULL,
    affected_values_json TEXT NOT NULL,
    currency TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    proposed_description TEXT NOT NULL,
    proposed_category TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    decision_score REAL NOT NULL,
    retrieval_score REAL NOT NULL,
    retrieval_margin REAL NOT NULL,
    priority_score REAL NOT NULL,
    llm_used INTEGER NOT NULL,
    blocks_transaction INTEGER NOT NULL,
    risk_flags_json TEXT NOT NULL,
    prompt_version TEXT,
    model TEXT,
    provider TEXT,
    status TEXT NOT NULL,
    target_product_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_scope ON reviews(tenant_id, status, priority_score DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_candidate
    ON reviews(tenant_id, partner_id, candidate_key) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class SQLiteCatalogRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)

    def seed_from_file(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            for entry in payload["products"]:
                connection.execute(
                    """INSERT OR IGNORE INTO canonical_products
                    (product_id, tenant_id, partner_id, canonical_description, category, attributes_json, style_version, active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                    (
                        entry["product_id"], entry["tenant_id"], entry["partner_id"],
                        entry["canonical_description"], entry["category"],
                        json.dumps(entry.get("attributes", {}), sort_keys=True),
                        entry.get("style_version", "1"), now,
                    ),
                )
                for alias in entry.get("aliases", []):
                    alias_text = alias if isinstance(alias, str) else alias["text"]
                    language = "en" if isinstance(alias, str) else alias.get("language", "en")
                    alias_id = str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{entry['tenant_id']}:{entry['partner_id']}:{normalize_text(alias_text)}:{language}",
                    ))
                    connection.execute(
                        """INSERT OR IGNORE INTO product_aliases
                        (alias_id, tenant_id, partner_id, product_id, alias_text, normalized_alias, language, approved, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                        (
                            alias_id, entry["tenant_id"], entry["partner_id"], entry["product_id"],
                            alias_text, normalize_text(alias_text), language, now,
                        ),
                    )

    def save_invoice_document(self, parsed: ParsedDocument, tenant_id: str, partner_id: str) -> None:
        """Persist invoice/header/party/line evidence before canonical decisions are made."""
        now = datetime.now(UTC).isoformat()
        financials = parsed.context.financials
        quality_json = json.dumps(parsed.quality.to_dict(), sort_keys=True) if parsed.quality else None
        financial_quality_json = json.dumps(parsed.financial_quality.to_dict(), sort_keys=True) if parsed.financial_quality else None
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO invoice_documents(
                    tenant_id, document_id, partner_id, source_name, parser_name,
                    invoice_number, invoice_date, due_date, payment_terms, currency,
                    subtotal, discount_total, subtotal_after_discount, tax_rate_percent,
                    tax_total, shipping_total, amount_due, warnings_json,
                    extraction_quality_json, financial_quality_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, document_id) DO UPDATE SET
                    partner_id=excluded.partner_id, source_name=excluded.source_name,
                    parser_name=excluded.parser_name, invoice_number=excluded.invoice_number,
                    invoice_date=excluded.invoice_date, due_date=excluded.due_date,
                    payment_terms=excluded.payment_terms, currency=excluded.currency,
                    subtotal=excluded.subtotal, discount_total=excluded.discount_total,
                    subtotal_after_discount=excluded.subtotal_after_discount,
                    tax_rate_percent=excluded.tax_rate_percent, tax_total=excluded.tax_total,
                    shipping_total=excluded.shipping_total, amount_due=excluded.amount_due,
                    warnings_json=excluded.warnings_json,
                    extraction_quality_json=excluded.extraction_quality_json,
                    financial_quality_json=excluded.financial_quality_json,
                    updated_at=excluded.updated_at""",
                (
                    tenant_id, parsed.document_id, partner_id, parsed.source_name, parsed.parser_name,
                    parsed.context.invoice_number, parsed.context.invoice_date, parsed.context.due_date,
                    parsed.context.payment_terms, financials.currency,
                    decimal_text(financials.subtotal), decimal_text(financials.discount_total),
                    decimal_text(financials.subtotal_after_discount), decimal_text(financials.tax_rate_percent),
                    decimal_text(financials.tax_total), decimal_text(financials.shipping_total),
                    decimal_text(financials.amount_due), json.dumps(list(parsed.warnings)),
                    quality_json, financial_quality_json, now, now,
                ),
            )
            connection.execute(
                "DELETE FROM invoice_parties WHERE tenant_id = ? AND document_id = ?",
                (tenant_id, parsed.document_id),
            )
            for party in parsed.context.parties:
                connection.execute(
                    """INSERT INTO invoice_parties(
                        tenant_id, document_id, role, name, contact_name, address_lines_json,
                        phone, email, website, external_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tenant_id, parsed.document_id, party.role.value, party.name, party.contact_name,
                        json.dumps(list(party.address_lines), ensure_ascii=False), party.phone,
                        party.email, party.website, party.external_id,
                    ),
                )
            connection.execute(
                "DELETE FROM invoice_lines WHERE tenant_id = ? AND document_id = ?",
                (tenant_id, parsed.document_id),
            )
            for line in parsed.lines:
                connection.execute(
                    """INSERT INTO invoice_lines(
                        tenant_id, document_id, source_line_id, partner_id, description,
                        quantity, unit_price, line_total, currency, metadata_json, decision_id, canonical_product_id, canonical_description, decision_kind, requires_human_review, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?)""",
                    (
                        tenant_id, parsed.document_id, line.source_line_id, partner_id, line.description,
                        decimal_text(line.quantity), decimal_text(line.unit_price), decimal_text(line.total),
                        line.currency, json.dumps(line.metadata, sort_keys=True), now,
                    ),
                )

    def link_invoice_decision(
        self, tenant_id: str, document_id: str, source_line_id: str, decision: CanonicalizationDecision
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """UPDATE invoice_lines
                   SET decision_id = ?, canonical_product_id = ?, canonical_description = ?,
                       decision_kind = ?, requires_human_review = ?
                   WHERE tenant_id = ? AND document_id = ? AND source_line_id = ?""",
                (
                    decision.decision_id, decision.canonical_product_id, decision.canonical_description,
                    decision.decision_kind.value, int(decision.requires_human_review),
                    tenant_id, document_id, source_line_id,
                ),
            )

    def get_invoice_document(self, tenant_id: str, document_id: str) -> ParsedDocument | None:
        with self._connection() as connection:
            document = connection.execute(
                "SELECT * FROM invoice_documents WHERE tenant_id = ? AND document_id = ?",
                (tenant_id, document_id),
            ).fetchone()
            if document is None:
                return None
            party_rows = connection.execute(
                """SELECT * FROM invoice_parties WHERE tenant_id = ? AND document_id = ?
                   ORDER BY CASE role WHEN 'seller' THEN 1 WHEN 'bill_to' THEN 2 ELSE 3 END""",
                (tenant_id, document_id),
            ).fetchall()
            line_rows = connection.execute(
                """SELECT * FROM invoice_lines WHERE tenant_id = ? AND document_id = ?
                   ORDER BY rowid""",
                (tenant_id, document_id),
            ).fetchall()
        parties = tuple(InvoiceParty(
            role=PartyRole(row["role"]), name=row["name"], contact_name=row["contact_name"],
            address_lines=tuple(json.loads(row["address_lines_json"])), phone=row["phone"],
            email=row["email"], website=row["website"], external_id=row["external_id"],
        ) for row in party_rows)
        context = InvoiceContext(
            invoice_number=document["invoice_number"], invoice_date=document["invoice_date"],
            due_date=document["due_date"], payment_terms=document["payment_terms"], parties=parties,
            financials=InvoiceFinancials(
                currency=document["currency"], subtotal=to_decimal(document["subtotal"]),
                discount_total=to_decimal(document["discount_total"]),
                subtotal_after_discount=to_decimal(document["subtotal_after_discount"]),
                tax_rate_percent=to_decimal(document["tax_rate_percent"]),
                tax_total=to_decimal(document["tax_total"]), shipping_total=to_decimal(document["shipping_total"]),
                amount_due=to_decimal(document["amount_due"]),
            ),
        )
        lines = tuple(InvoiceLine(
            tenant_id=tenant_id, partner_id=row["partner_id"], description=row["description"],
            source_line_id=row["source_line_id"], quantity=to_decimal(row["quantity"]),
            unit_price=to_decimal(row["unit_price"]), total=to_decimal(row["line_total"]),
            currency=row["currency"], metadata=json.loads(row["metadata_json"]),
        ) for row in line_rows)
        quality = self._quality_from_json(document["extraction_quality_json"])
        financial_quality = self._financial_quality_from_json(document["financial_quality_json"])
        return ParsedDocument(
            document_id=document_id, source_name=document["source_name"], parser_name=document["parser_name"],
            lines=lines, context=context, warnings=tuple(json.loads(document["warnings_json"])),
            quality=quality, financial_quality=financial_quality,
        )

    def get_invoice_line_records(self, tenant_id: str, document_id: str) -> tuple[StoredInvoiceLine, ...]:
        """Return persisted source lines together with the canonical outcomes linked after processing."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT source_line_id, description, quantity, unit_price, line_total, currency,
                          canonical_product_id, canonical_description, decision_kind, requires_human_review
                   FROM invoice_lines WHERE tenant_id = ? AND document_id = ? ORDER BY rowid""",
                (tenant_id, document_id),
            ).fetchall()
        return tuple(StoredInvoiceLine(
            source_line_id=row["source_line_id"],
            description=row["description"],
            quantity=to_decimal(row["quantity"]),
            unit_price=to_decimal(row["unit_price"]),
            total=to_decimal(row["line_total"]),
            currency=row["currency"],
            canonical_product_id=row["canonical_product_id"],
            canonical_description=row["canonical_description"],
            decision_kind=DecisionKind(row["decision_kind"]) if row["decision_kind"] else None,
            requires_human_review=bool(row["requires_human_review"]) if row["requires_human_review"] is not None else None,
        ) for row in rows)

    @staticmethod
    def _quality_from_json(raw: str | None) -> ExtractionQualityReport | None:
        if not raw:
            return None
        payload = json.loads(raw)
        return ExtractionQualityReport(
            status=ExtractionQualityStatus(payload["status"]),
            rows_extracted=int(payload["rows_extracted"]),
            rows_with_complete_arithmetic=int(payload["rows_with_complete_arithmetic"]),
            rows_arithmetic_valid=int(payload["rows_arithmetic_valid"]),
            rows_arithmetic_invalid=int(payload["rows_arithmetic_invalid"]),
            calculated_subtotal=to_decimal(payload.get("calculated_subtotal")),
            declared_subtotal=to_decimal(payload.get("declared_subtotal")),
            subtotal_matches=payload.get("subtotal_matches"),
            checks=tuple(payload.get("checks", [])),
        )

    @staticmethod
    def _financial_quality_from_json(raw: str | None) -> FinancialQualityReport | None:
        if not raw:
            return None
        payload = json.loads(raw)
        return FinancialQualityReport(
            status=ExtractionQualityStatus(payload["status"]),
            discount_reconciles=payload.get("discount_reconciles"),
            tax_reconciles=payload.get("tax_reconciles"),
            amount_due_reconciles=payload.get("amount_due_reconciles"),
            checks=tuple(payload.get("checks", [])),
        )

    def find_approved_alias(self, tenant_id: str, partner_id: str, normalized_alias: str) -> AliasRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT * FROM product_aliases
                WHERE tenant_id = ? AND partner_id = ? AND normalized_alias = ? AND approved = 1""",
                (tenant_id, partner_id, normalized_alias),
            ).fetchone()
        return self._alias_from_row(row) if row else None

    def list_aliases(self, tenant_id: str, partner_id: str) -> Sequence[tuple[AliasRecord, CanonicalProduct]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT a.*, p.canonical_description, p.category, p.attributes_json,
                          p.style_version, p.tenant_id AS p_tenant_id, p.partner_id AS p_partner_id
                   FROM product_aliases a
                   JOIN canonical_products p
                     ON p.product_id = a.product_id
                    AND p.tenant_id = a.tenant_id
                    AND p.partner_id = a.partner_id
                   WHERE a.tenant_id = ? AND a.partner_id = ? AND a.approved = 1 AND p.active = 1""",
                (tenant_id, partner_id),
            ).fetchall()
        results: list[tuple[AliasRecord, CanonicalProduct]] = []
        for row in rows:
            alias = self._alias_from_row(row)
            product = CanonicalProduct(
                product_id=row["product_id"], tenant_id=row["p_tenant_id"], partner_id=row["p_partner_id"],
                canonical_description=row["canonical_description"], category=row["category"],
                attributes=json.loads(row["attributes_json"]), style_version=row["style_version"],
            )
            results.append((alias, product))
        return results

    def get_product(self, tenant_id: str, product_id: str) -> CanonicalProduct | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM canonical_products WHERE tenant_id = ? AND product_id = ? AND active = 1",
                (tenant_id, product_id),
            ).fetchone()
        return self._product_from_row(row) if row else None

    def get_cached_decision(self, tenant_id: str, line_hash: str, taxonomy_version: str) -> CanonicalizationDecision | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM decisions WHERE tenant_id = ? AND line_hash = ? AND taxonomy_version = ?",
                (tenant_id, line_hash, taxonomy_version),
            ).fetchone()
        return CanonicalizationDecision.from_dict(json.loads(row["result_json"])) if row else None

    def save_decision(self, decision: CanonicalizationDecision, line_hash: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO decisions(decision_id, tenant_id, line_hash, taxonomy_version, result_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, line_hash, taxonomy_version)
                   DO UPDATE SET result_json = excluded.result_json, created_at = excluded.created_at""",
                (
                    decision.decision_id, decision.tenant_id, line_hash, decision.taxonomy_version,
                    json.dumps(decision.to_dict(), sort_keys=True), datetime.now(UTC).isoformat(),
                ),
            )

    def create_or_update_review(self, review: ReviewRecord) -> ReviewRecord:
        now = datetime.now(UTC).isoformat()
        first_seen = review.first_seen_at or now
        last_seen = review.last_seen_at or now
        variants = tuple(dict.fromkeys(review.source_variants or (review.source_description,)))
        line_ids = tuple(dict.fromkeys(review.source_line_ids))
        occurrence_count = max(1, review.occurrence_count)
        breakdown = self._initial_currency_breakdown(review)
        display_value, display_currency = self._display_value_currency(breakdown)
        priority = review_priority_score(
            occurrence_count,
            display_value,
            review.decision_score,
            currency=display_currency,
        )
        try:
            with self._connection() as connection:
                connection.execute(
                    """INSERT INTO reviews
                    (review_id, tenant_id, partner_id, candidate_key, source_description, source_variants_json,
                     source_line_ids_json, occurrence_count, affected_value, affected_values_json, currency,
                     first_seen_at, last_seen_at, proposed_description, proposed_category, attributes_json,
                     evidence_json, decision_score, retrieval_score, retrieval_margin, priority_score, llm_used,
                     blocks_transaction, risk_flags_json, prompt_version, model, provider, status,
                     target_product_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        review.review_id, review.tenant_id, review.partner_id, review.candidate_key,
                        review.source_description, json.dumps(variants), json.dumps(line_ids), occurrence_count,
                        decimal_text(display_value), self._breakdown_json(breakdown), display_currency,
                        first_seen, last_seen, review.proposed_description, review.proposed_category,
                        json.dumps(review.attributes, sort_keys=True), json.dumps(review.evidence, sort_keys=True),
                        review.decision_score, review.retrieval_score, review.retrieval_margin, priority,
                        int(review.llm_used), int(review.blocks_transaction), json.dumps(review.risk_flags),
                        review.prompt_version, review.model, review.provider, review.status.value,
                        review.target_product_id, now, now,
                    ),
                )
        except sqlite3.IntegrityError:
            # The partial unique index makes concurrent discovery atomic: only one pending candidate
            # wins; losers attach their occurrence instead of producing duplicate reviews/model work.
            existing = self.find_pending_review_by_candidate_key(
                review.tenant_id, review.partner_id, review.candidate_key
            )
            if existing is None:
                raise
            return self.record_review_occurrence(
                review.tenant_id,
                existing.review_id,
                review.source_description,
                review.source_line_ids[0] if review.source_line_ids else "unknown",
                review.affected_value,
                review.currency,
            )
        created = self.get_review(review.tenant_id, review.review_id)
        assert created is not None
        return created

    def update_pending_review(self, review: ReviewRecord) -> ReviewRecord:
        """Update machine proposal fields without changing occurrence accounting or review identity."""
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM reviews WHERE tenant_id = ? AND review_id = ? AND status = ?",
                (review.tenant_id, review.review_id, ReviewStatus.PENDING.value),
            ).fetchone()
            if not row:
                raise ReviewNotFoundError(review.review_id)
            if row["partner_id"] != review.partner_id or row["candidate_key"] != review.candidate_key:
                raise ReviewConflictError("pending review identity/scope cannot be changed")
            display_value = to_decimal(row["affected_value"], default=ZERO) or ZERO
            priority = review_priority_score(
                int(row["occurrence_count"]),
                display_value,
                review.decision_score,
                currency=row["currency"],
            )
            connection.execute(
                """UPDATE reviews SET proposed_description = ?, proposed_category = ?, attributes_json = ?,
                   evidence_json = ?, decision_score = ?, retrieval_score = ?, retrieval_margin = ?,
                   priority_score = ?, llm_used = ?, blocks_transaction = ?, risk_flags_json = ?,
                   prompt_version = ?, model = ?, provider = ?, target_product_id = ?, updated_at = ?
                   WHERE review_id = ? AND tenant_id = ? AND status = ?""",
                (
                    review.proposed_description, review.proposed_category,
                    json.dumps(review.attributes, sort_keys=True), json.dumps(review.evidence, sort_keys=True),
                    review.decision_score, review.retrieval_score, review.retrieval_margin, priority,
                    int(review.llm_used), int(review.blocks_transaction), json.dumps(review.risk_flags),
                    review.prompt_version, review.model, review.provider, review.target_product_id, now,
                    review.review_id, review.tenant_id, ReviewStatus.PENDING.value,
                ),
            )
        updated = self.get_review(review.tenant_id, review.review_id)
        assert updated is not None
        return updated

    def find_pending_review_by_candidate_key(self, tenant_id: str, partner_id: str, candidate_key: str) -> ReviewRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT * FROM reviews
                   WHERE tenant_id = ? AND partner_id = ? AND candidate_key = ? AND status = ?""",
                (tenant_id, partner_id, candidate_key, ReviewStatus.PENDING.value),
            ).fetchone()
        return self._review_from_row(row) if row else None

    def record_review_occurrence(
        self,
        tenant_id: str,
        review_id: str,
        source_description: str,
        source_line_id: str,
        affected_value: Decimal,
        currency: str | None,
    ) -> ReviewRecord:
        now = datetime.now(UTC).isoformat()
        amount = to_decimal(affected_value, default=ZERO) or ZERO
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM reviews WHERE tenant_id = ? AND review_id = ? AND status = ?",
                (tenant_id, review_id, ReviewStatus.PENDING.value),
            ).fetchone()
            if not row:
                raise ReviewNotFoundError(review_id)
            variants = list(json.loads(row["source_variants_json"]))
            if source_description not in variants and len(variants) < 25:
                variants.append(source_description)
            line_ids = list(json.loads(row["source_line_ids_json"]))
            if source_line_id not in line_ids and len(line_ids) < 50:
                line_ids.append(source_line_id)
            count = int(row["occurrence_count"]) + 1
            breakdown = self._breakdown_from_json(row["affected_values_json"])
            key = currency or "UNSPECIFIED"
            breakdown[key] = breakdown.get(key, ZERO) + abs(amount)
            display_value, display_currency = self._display_value_currency(breakdown)
            priority = review_priority_score(
                count,
                display_value,
                float(row["decision_score"]),
                currency=display_currency,
            )
            connection.execute(
                """UPDATE reviews SET source_variants_json = ?, source_line_ids_json = ?, occurrence_count = ?,
                   affected_value = ?, affected_values_json = ?, currency = ?, last_seen_at = ?,
                   priority_score = ?, updated_at = ? WHERE review_id = ?""",
                (
                    json.dumps(variants), json.dumps(line_ids), count, decimal_text(display_value),
                    self._breakdown_json(breakdown), display_currency, now, priority, now, review_id,
                ),
            )
        updated = self.get_review(tenant_id, review_id)
        assert updated is not None
        return updated

    def list_reviews(
        self,
        tenant_id: str,
        status: ReviewStatus | None = ReviewStatus.PENDING,
        limit: int = 100,
        sort_by_priority: bool = True,
    ) -> Sequence[ReviewRecord]:
        limit = max(1, min(10_000, int(limit)))
        where = "tenant_id = ?"
        params: list[object] = [tenant_id]
        if status is not None:
            where += " AND status = ?"
            params.append(status.value)
        order = "priority_score DESC, occurrence_count DESC, last_seen_at ASC" if sort_by_priority else "last_seen_at ASC"
        params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM reviews WHERE {where} ORDER BY {order} LIMIT ?", params
            ).fetchall()
        return [self._review_from_row(row) for row in rows]

    def get_review(self, tenant_id: str, review_id: str) -> ReviewRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE tenant_id = ? AND review_id = ?",
                (tenant_id, review_id),
            ).fetchone()
        return self._review_from_row(row) if row else None

    def approve_review(
        self,
        tenant_id: str,
        review_id: str,
        approved_description: str,
        target_product_id: str | None,
        approved_category: str | None = None,
    ) -> CanonicalProduct:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM reviews WHERE tenant_id = ? AND review_id = ?",
                (tenant_id, review_id),
            ).fetchone()
            if not row:
                raise ReviewNotFoundError(review_id)
            if row["status"] != ReviewStatus.PENDING.value:
                raise ReviewConflictError(f"review {review_id} is already {row['status']}")
            if target_product_id:
                product_row = connection.execute(
                    """SELECT * FROM canonical_products
                       WHERE tenant_id = ? AND partner_id = ? AND product_id = ? AND active = 1""",
                    (tenant_id, row["partner_id"], target_product_id),
                ).fetchone()
                if not product_row:
                    raise ReviewConflictError("target product does not exist in tenant/partner scope")
                product_id = target_product_id
                final_description = product_row["canonical_description"]
            else:
                product_id = f"product-{uuid.uuid4()}"
                final_description = approved_description
                category = approved_category or row["proposed_category"]
                connection.execute(
                    """INSERT INTO canonical_products
                    (product_id, tenant_id, partner_id, canonical_description, category, attributes_json, style_version, active, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, '1', 1, ?)""",
                    (product_id, tenant_id, row["partner_id"], final_description, category, row["attributes_json"], now),
                )
            variants = list(json.loads(row["source_variants_json"])) or [row["source_description"]]
            if row["source_description"] not in variants:
                variants.append(row["source_description"])
            for alias_text in variants:
                normalized = normalize_text(alias_text)
                alias_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{tenant_id}:{row['partner_id']}:{normalized}:en",
                ))
                connection.execute(
                    """INSERT INTO product_aliases
                    (alias_id, tenant_id, partner_id, product_id, alias_text, normalized_alias, language, approved, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'en', 1, ?)
                    ON CONFLICT(tenant_id, partner_id, normalized_alias, language)
                    DO UPDATE SET product_id = excluded.product_id, alias_text = excluded.alias_text, approved = 1""",
                    (alias_id, tenant_id, row["partner_id"], product_id, alias_text, normalized, now),
                )
            connection.execute(
                "UPDATE reviews SET status = ?, target_product_id = ?, proposed_description = ?, updated_at = ? WHERE review_id = ?",
                (ReviewStatus.APPROVED.value, product_id, final_description, now, review_id),
            )
            product_row = connection.execute(
                "SELECT * FROM canonical_products WHERE tenant_id = ? AND product_id = ?",
                (tenant_id, product_id),
            ).fetchone()
        assert product_row is not None
        return self._product_from_row(product_row)

    def reject_review(self, tenant_id: str, review_id: str) -> ReviewRecord:
        now = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM reviews WHERE tenant_id = ? AND review_id = ?",
                (tenant_id, review_id),
            ).fetchone()
            if not row:
                raise ReviewNotFoundError(review_id)
            if row["status"] != ReviewStatus.PENDING.value:
                raise ReviewConflictError(f"review {review_id} is already {row['status']}")
            connection.execute(
                "UPDATE reviews SET status = ?, updated_at = ? WHERE review_id = ?",
                (ReviewStatus.REJECTED.value, now, review_id),
            )
        updated = self.get_review(tenant_id, review_id)
        assert updated is not None
        return updated

    def record_audit(self, tenant_id: str, event_type: str, payload: dict[str, object]) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO audit_events(event_id, tenant_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()), tenant_id, event_type,
                    json.dumps(payload, sort_keys=True, default=str), datetime.now(UTC).isoformat(),
                ),
            )

    @staticmethod
    def _initial_currency_breakdown(review: ReviewRecord) -> dict[str, Decimal]:
        if review.affected_values_by_currency:
            return {
                str(key): to_decimal(value, default=ZERO) or ZERO
                for key, value in review.affected_values_by_currency.items()
            }
        return {review.currency or "UNSPECIFIED": abs(review.affected_value)}

    @staticmethod
    def _display_value_currency(breakdown: dict[str, Decimal]) -> tuple[Decimal, str | None]:
        nonzero = {key: value for key, value in breakdown.items() if value != ZERO}
        if not nonzero:
            return ZERO, None
        if len(nonzero) == 1:
            key, value = next(iter(nonzero.items()))
            return value, None if key == "UNSPECIFIED" else key
        # Never add incomparable currencies into a fake monetary total. The exact per-currency
        # breakdown remains available while review priority falls back to frequency/uncertainty.
        return ZERO, "MIXED"

    @staticmethod
    def _breakdown_json(breakdown: dict[str, Decimal]) -> str:
        return json.dumps({key: decimal_text(value) for key, value in sorted(breakdown.items())}, sort_keys=True)

    @staticmethod
    def _breakdown_from_json(raw: str) -> dict[str, Decimal]:
        payload = json.loads(raw or "{}")
        return {str(key): to_decimal(value, default=ZERO) or ZERO for key, value in payload.items()}

    @staticmethod
    def _product_from_row(row: sqlite3.Row) -> CanonicalProduct:
        return CanonicalProduct(
            product_id=row["product_id"], tenant_id=row["tenant_id"], partner_id=row["partner_id"],
            canonical_description=row["canonical_description"], category=row["category"],
            attributes=json.loads(row["attributes_json"]), style_version=row["style_version"],
        )

    @staticmethod
    def _alias_from_row(row: sqlite3.Row) -> AliasRecord:
        return AliasRecord(
            alias_id=row["alias_id"], tenant_id=row["tenant_id"], partner_id=row["partner_id"],
            product_id=row["product_id"], alias_text=row["alias_text"], normalized_alias=row["normalized_alias"],
            language=row["language"], approved=bool(row["approved"]),
        )

    @classmethod
    def _review_from_row(cls, row: sqlite3.Row) -> ReviewRecord:
        return ReviewRecord(
            review_id=row["review_id"], tenant_id=row["tenant_id"], partner_id=row["partner_id"],
            candidate_key=row["candidate_key"], source_description=row["source_description"],
            source_variants=tuple(json.loads(row["source_variants_json"])),
            source_line_ids=tuple(json.loads(row["source_line_ids_json"])),
            occurrence_count=int(row["occurrence_count"]),
            affected_value=to_decimal(row["affected_value"], default=ZERO) or ZERO,
            affected_values_by_currency=cls._breakdown_from_json(row["affected_values_json"]),
            currency=row["currency"], first_seen_at=row["first_seen_at"], last_seen_at=row["last_seen_at"],
            proposed_description=row["proposed_description"], proposed_category=row["proposed_category"],
            attributes=json.loads(row["attributes_json"]), evidence=tuple(json.loads(row["evidence_json"])),
            decision_score=float(row["decision_score"]), retrieval_score=float(row["retrieval_score"]),
            retrieval_margin=float(row["retrieval_margin"]), priority_score=float(row["priority_score"]),
            llm_used=bool(row["llm_used"]), blocks_transaction=bool(row["blocks_transaction"]),
            risk_flags=tuple(json.loads(row["risk_flags_json"])), prompt_version=row["prompt_version"],
            model=row["model"], provider=row["provider"], status=ReviewStatus(row["status"]),
            target_product_id=row["target_product_id"],
        )
