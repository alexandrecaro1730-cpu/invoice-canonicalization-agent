-- Business objective: provide the production migration path for tenant/partner-isolated canonical product knowledge.
-- Technical description: PostgreSQL uses JSONB, composite integrity, pgvector-ready embeddings, FORCE RLS, and USING/WITH CHECK policies so writes cannot cross tenant scope.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE canonical_products (
    product_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    canonical_description TEXT NOT NULL,
    category TEXT NOT NULL,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536),
    style_version TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, tenant_id, partner_id)
);

CREATE TABLE product_aliases (
    alias_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    alias_text TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    approved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_alias_product_scope
        FOREIGN KEY (product_id, tenant_id, partner_id)
        REFERENCES canonical_products(product_id, tenant_id, partner_id),
    UNIQUE (tenant_id, partner_id, normalized_alias, language)
);

CREATE INDEX idx_product_scope ON canonical_products(tenant_id, partner_id, category) WHERE active;
CREATE INDEX idx_alias_scope ON product_aliases(tenant_id, partner_id, normalized_alias) WHERE approved;
CREATE INDEX idx_product_attributes ON canonical_products USING GIN(attributes);

ALTER TABLE canonical_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE canonical_products FORCE ROW LEVEL SECURITY;
ALTER TABLE product_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_aliases FORCE ROW LEVEL SECURITY;

CREATE POLICY product_tenant_policy ON canonical_products
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY alias_tenant_policy ON product_aliases
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
