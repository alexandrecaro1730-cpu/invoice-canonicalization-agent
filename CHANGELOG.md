# Changelog

## 1.0.0 - 2026-08-07

Final assessment delivery.

### Product-canonicalization design

- Reframed the assessor-facing architecture around three tiers: deterministic approved lookup, bounded uncertainty handling, and governed human learning.
- Made abstention explicit: uncertain model output can be rejected instead of silently becoming trusted knowledge.
- Preserved tenant/partner-scoped taxonomy behavior so identical supplier text may intentionally map differently for different clients.
- Kept unapproved staging data out of approved retrieval to prevent self-reinforcing model mistakes.

### Invoice ingestion and persistence

- Added complete invoice-envelope persistence: header, seller, bill-to, ship-to, address/contact evidence, commercial totals, and original line data.
- Kept document extraction fallback separate from product canonicalization fallback.
- Added deterministic Decimal line arithmetic and document reconciliation gates before canonicalization.
- Added cross-format full-invoice examples for PDF, DOCX, XLSX, JSON, CSV, and TXT.

### Governance, security, and cost controls

- Deduplicated unresolved concepts before model generation.
- Added human-review promotion, archive/audit behavior, tenant-bound authorization, prompt-data minimization, and output/security validation.
- Kept model calls opt-in and budgeted, with deterministic fixture mode for CI.

### Delivery and presentation

- Finalized GitHub CI, Docker packaging, release workflow, production PostgreSQL/RLS migration direction, and MCP/REST delivery boundaries.
- Rebuilt the assessor presentation around a short visual "wild -> tamed" story, with technical depth moved to the appendix.
- Tightened claims from "$0 processing" to the technically defensible "no LLM call / zero model cost" language.
- Added final verification and production-validation documentation.
