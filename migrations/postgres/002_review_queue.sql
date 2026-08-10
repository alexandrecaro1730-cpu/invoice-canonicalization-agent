-- Business objective: scale staged human review without blocking invoice throughput, faking mixed-currency value, or contaminating approved knowledge.
-- Technical description: normalizes pending candidates/occurrences, enforces composite tenant/partner references, uses exact NUMERIC money, and applies FORCE RLS with USING/WITH CHECK policies.

CREATE TABLE review_candidates (
    review_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    source_description TEXT NOT NULL,
    proposed_description TEXT NOT NULL,
    proposed_category TEXT NOT NULL,
    proposed_attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision_score DOUBLE PRECISION NOT NULL,
    retrieval_score DOUBLE PRECISION NOT NULL,
    retrieval_margin DOUBLE PRECISION NOT NULL,
    priority_score DOUBLE PRECISION NOT NULL,
    llm_used BOOLEAN NOT NULL,
    blocks_transaction BOOLEAN NOT NULL,
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_version TEXT,
    model TEXT,
    provider TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    target_product_id TEXT,
    occurrence_count BIGINT NOT NULL DEFAULT 1,
    affected_value NUMERIC(20, 4) NOT NULL DEFAULT 0,
    affected_values_by_currency JSONB NOT NULL DEFAULT '{}'::jsonb,
    currency TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (review_id, tenant_id),
    CONSTRAINT fk_review_target_product_scope
        FOREIGN KEY (target_product_id, tenant_id, partner_id)
        REFERENCES canonical_products(product_id, tenant_id, partner_id)
);

CREATE UNIQUE INDEX uq_review_pending_candidate
    ON review_candidates(tenant_id, partner_id, candidate_key)
    WHERE status = 'pending';
CREATE INDEX idx_review_priority
    ON review_candidates(tenant_id, status, priority_score DESC, last_seen_at ASC);
CREATE INDEX idx_review_target_product
    ON review_candidates(tenant_id, target_product_id) WHERE target_product_id IS NOT NULL;

CREATE TABLE review_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    source_line_id TEXT NOT NULL,
    source_description TEXT NOT NULL,
    affected_value NUMERIC(20, 4) NOT NULL DEFAULT 0,
    currency TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_review_occurrence_scope
        FOREIGN KEY (review_id, tenant_id)
        REFERENCES review_candidates(review_id, tenant_id)
);
CREATE INDEX idx_review_occurrence_review ON review_occurrences(review_id, observed_at DESC);
CREATE INDEX idx_review_occurrence_tenant ON review_occurrences(tenant_id, observed_at DESC);

CREATE TABLE review_audit_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    review_id TEXT,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_review_audit_tenant ON review_audit_events(tenant_id, created_at DESC);

ALTER TABLE review_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE review_occurrences ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_occurrences FORCE ROW LEVEL SECURITY;
ALTER TABLE review_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_audit_events FORCE ROW LEVEL SECURITY;

CREATE POLICY review_candidate_tenant_policy ON review_candidates
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY review_occurrence_tenant_policy ON review_occurrences
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY review_audit_tenant_policy ON review_audit_events
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
