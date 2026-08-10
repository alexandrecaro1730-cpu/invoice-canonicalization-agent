# Invoice data model and relevance boundaries

## Business objective

Retain the complete business evidence needed to organize invoices by authenticated client and business partner, audit the source document, and reconcile commercial totals without allowing unrelated invoice metadata to distort product-description canonicalization.

## Technical description

The application deliberately separates **invoice evidence** from **canonicalization features**. The database keeps the source invoice header, parties, financial totals, raw lines, and canonical outcomes. Only the minimum product-line evidence is allowed into product retrieval or model prompts.

## What is stored and why

| Source field | Persist? | Used for product canonicalization? | Reason |
|---|---|---|---|
| Authenticated `tenant_id` | Yes | Scope only | Authoritative client isolation boundary. Never inferred from invoice text. |
| Routed `partner_id` | Yes | Scope only | Keeps aliases and invoices organized by the client's business partner. |
| Invoice number | Yes | No | Audit, deduplication support, search, and ERP reconciliation. |
| Invoice date / due date / payment terms | Yes | No | Operational and accounting context. |
| Seller / issuer (expected payee) | Yes | No | Counterparty evidence and later entity resolution. |
| Bill-to party (expected payer) | Yes | No | Counterparty evidence, AP/AR organization, and audit. |
| Ship-to party | Yes | No | Logistics and location evidence; may differ from payer. |
| Party addresses / phone / email / website | Yes, tenant-scoped | No | Entity resolution and audit. Sensitive contact data is excluded from canonicalization prompts. |
| Product description | Yes | **Yes** | Primary canonicalization input. |
| Quantity / unit price / line total | Yes | Only as validation / impact evidence | Arithmetic gate detects corrupt extraction; monetary impact can prioritize review. |
| Subtotal | Yes | No | Reconcile extracted line totals to the document. |
| Discount | Yes | No | Reconcile net subtotal and preserve accounting evidence. |
| Tax rate / tax total | Yes | No | Reconciliation and downstream accounting. |
| Shipping / handling | Yes | No | Reconciliation and downstream accounting/logistics. |
| Amount due | Yes | No | Final document-level financial reconciliation. |
| Signatures / decorative logo | No | No | Not required for the canonicalization or accounting evidence in this assessment. |
| Empty remarks / payment-instructions heading | No | No | There is no source value to persist. Real populated notes could be retained as protected invoice metadata in a future schema. |

## Why payer/payee information does not choose the tenant

The system receives the authenticated client (`tenant_id`) from the security boundary and the business-partner scope (`partner_id`) from the calling workflow/integration. Extracted seller/bill-to/ship-to values are **evidence**, not authorization data. An attacker or malformed invoice therefore cannot write data into another tenant simply by printing another company name on a PDF.

For the supplied example, `Testinger GmbH` is stored as the seller/issuer and `Recipient Corp.` is stored as bill-to and ship-to evidence. The assessment runs under the authenticated `testinger` tenant and `default-partner` relationship. A production integration can later resolve those snapshots to ERP/vendor/customer master IDs through `external_id` without changing the canonicalization algorithm.

## Two quality gates with different consequences

### 1. Line extraction gate - blocking

`quantity × unit_price == line_total` and `sum(line_total) == subtotal` protect canonicalization from corrupted OCR/parser rows. A failure triggers the bounded document-extraction fallback (when enabled) or stops processing.

### 2. Commercial reconciliation - non-blocking for naming

The system separately checks:

- `subtotal - discount == subtotal_after_discount`
- `subtotal_after_discount × tax_rate == tax_total`
- `subtotal_after_discount + tax_total + shipping == amount_due`

A commercial mismatch is stored and surfaced for accounting/review, but it does **not** change what a product is called. This prevents a tax or shipping discrepancy from contaminating retrieval or causing a different canonical product description.

## Storage model

```text
invoice_documents
  tenant_id + document_id
  partner_id
  invoice_number / dates / terms
  subtotal / discount / tax / shipping / amount_due
  extraction + financial quality evidence
        |
        +-- invoice_parties
        |     role: seller | bill_to | ship_to
        |     name / contact / address / phone / email / website / external_id
        |
        +-- invoice_lines
              raw description / quantity / unit price / total / currency
              canonical product ID / canonical description / decision kind
```

The local assessment uses SQLite. `migrations/postgres/003_invoice_documents.sql` contains the equivalent production-oriented PostgreSQL schema with tenant-scoped foreign keys and row-level security.

## Privacy boundary

Full party/contact information is retained because it is useful operational evidence, but it is not inserted into the product canonicalization prompt. The model receives the product line and bounded approved examples, not the customer's addresses, emails, phone numbers, tax totals, or invoice balance.
