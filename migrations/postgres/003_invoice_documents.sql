-- Business objective: retain complete invoice evidence per client/partner while keeping product canonicalization focused on line descriptions.
-- Technical description: normalizes document headers, parties/addresses, exact NUMERIC commercial totals, raw line items, and canonical outcomes with tenant RLS and composite integrity.

CREATE TABLE invoice_documents (
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    invoice_number TEXT,
    invoice_date DATE,
    due_date DATE,
    payment_terms TEXT,
    currency TEXT,
    subtotal NUMERIC(20, 4),
    discount_total NUMERIC(20, 4),
    subtotal_after_discount NUMERIC(20, 4),
    tax_rate_percent NUMERIC(10, 4),
    tax_total NUMERIC(20, 4),
    shipping_total NUMERIC(20, 4),
    amount_due NUMERIC(20, 4),
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    extraction_quality JSONB,
    financial_quality JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, document_id)
);

CREATE INDEX idx_invoice_documents_number
    ON invoice_documents(tenant_id, partner_id, invoice_number);
CREATE INDEX idx_invoice_documents_date
    ON invoice_documents(tenant_id, partner_id, invoice_date DESC);

CREATE TABLE invoice_parties (
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('seller', 'bill_to', 'ship_to')),
    name TEXT NOT NULL,
    contact_name TEXT,
    address_lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    phone TEXT,
    email TEXT,
    website TEXT,
    external_id TEXT,
    PRIMARY KEY (tenant_id, document_id, role),
    CONSTRAINT fk_invoice_party_document
        FOREIGN KEY (tenant_id, document_id)
        REFERENCES invoice_documents(tenant_id, document_id) ON DELETE CASCADE
);

CREATE INDEX idx_invoice_party_lookup
    ON invoice_parties(tenant_id, role, name);

CREATE TABLE invoice_lines (
    tenant_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_line_id TEXT NOT NULL,
    partner_id TEXT NOT NULL,
    description TEXT NOT NULL,
    quantity NUMERIC(20, 6),
    unit_price NUMERIC(20, 4),
    line_total NUMERIC(20, 4),
    currency TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision_id TEXT,
    canonical_product_id TEXT,
    canonical_description TEXT,
    decision_kind TEXT,
    requires_human_review BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, document_id, source_line_id),
    CONSTRAINT fk_invoice_line_document
        FOREIGN KEY (tenant_id, document_id)
        REFERENCES invoice_documents(tenant_id, document_id) ON DELETE CASCADE,
    CONSTRAINT fk_invoice_line_product_scope
        FOREIGN KEY (canonical_product_id, tenant_id, partner_id)
        REFERENCES canonical_products(product_id, tenant_id, partner_id)
);

CREATE INDEX idx_invoice_line_scope
    ON invoice_lines(tenant_id, partner_id, document_id);
CREATE INDEX idx_invoice_line_product
    ON invoice_lines(tenant_id, partner_id, canonical_product_id)
    WHERE canonical_product_id IS NOT NULL;

ALTER TABLE invoice_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_documents FORCE ROW LEVEL SECURITY;
ALTER TABLE invoice_parties ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_parties FORCE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines FORCE ROW LEVEL SECURITY;

CREATE POLICY invoice_document_tenant_policy ON invoice_documents
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY invoice_party_tenant_policy ON invoice_parties
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE POLICY invoice_line_tenant_policy ON invoice_lines
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
