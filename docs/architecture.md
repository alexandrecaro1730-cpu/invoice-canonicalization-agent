# Architecture

## Business objective

Return the same approved product identity for repeated invoice lines while keeping routine processing cheap, preventing unreviewed AI output from becoming trusted knowledge, and allowing humans to approve **knowledge changes** in batches rather than approving individual invoices.

## Technical description

The assessor-facing architecture is intentionally framed as **three product-canonicalization tiers**, with document ingestion treated as an upstream reliability boundary and REST/MCP/Docker/CI treated as delivery primitives around the core. Internally, the same implementation still has a machine-checked detailed sequence for quality assurance.

## The architecture in one sentence

**Use approved deterministic knowledge first, spend retrieval/AI only on uncertainty, then convert successful human decisions into exact knowledge so future processing becomes cheaper and more reproducible.**

## Upstream reliability boundary: document ingestion

Document parsing is a separate problem from product canonicalization.

```text
PDF / XLSX / DOCX / CSV / JSON / TXT

Primary reviewer-visible PDF input: `data/examples/input/challenge_invoice.pdf`; full source assessment: `data/reference/Challenge_Data_Scientist.pdf`.
                |
                v
      deterministic extraction
                |
                v
      Decimal arithmetic gate
      qty * price ~= line total
      sum(lines) ~= subtotal
          |             |
        PASS           FAIL
          |             |
          |       OCR / bounded structured
          |       extraction fallback
          |             |
          +-------------+
                |
                v
       clean InvoiceLine records
```

The arithmetic gate exists to prevent corrupted OCR/parser rows from becoming "garbage in" for normalization, retrieval, or generation. A model extraction fallback is not trusted merely because it returns valid JSON: it must pass the same deterministic financial checks.

This upstream gate is deliberately **not part of the product-routing tiers**. It protects the quality of their input.

## Core canonicalization: three tiers

### Tier 1 - Deterministic approved lookup (no LLM)

The cheapest and most trusted path.

```text
normalized description
        |
        +--> version-safe cache
        |
        +--> tenant + partner approved alias
                    |
                    v
              exact product ID
```

Characteristics:

- no model call;
- stable canonical product ID;
- tenant/partner scoped;
- approved evidence only;
- effectively zero model cost and very low latency.

### Tier 2 - Bounded retrieval / AI fallback / abstention

Used only when Tier 1 cannot resolve the line.

```text
unknown description
      |
      v
pending-candidate deduplication
      |
      v
approved-only hybrid retrieval
      |
      +--> very strong existing match --> process transaction, stage alias, LLM = 0
      |
      +--> uncertain / novel ---------> one bounded LLM proposal per unique unknown
                                          |
                                          v
                                 validation
                                      |
                                      +--> valid proposal -> staged review
                                      |
                                      +--> insufficient confidence / unsafe -> ABSTAIN
```

The current assessment retriever uses lexical, token, trigram, category, and protected-attribute evidence. A semantic extension point is available but is deliberately disabled until labelled benchmarks justify it.

### Tier 3 - Governed human learning

Machine proposals stay in staging. Humans approve **knowledge**, not individual invoices.

```text
unique pending concept
       |
       v
weekly review queue
       |
       +--> approve existing
       +--> redirect
       +--> create new
       +--> edit + approve
       +--> reject
       +--> defer
       |
       v
approved product / alias
       |
       v
future Tier 1 exact lookup
```

This creates the long-term cost curve: model spend is driven by **unique unresolved concepts**, not repeated invoice volume. Once a mapping is approved, future occurrences return to Tier 1.

## Tenant taxonomy overrides and collisions

The catalog key is not a global raw description. Approved aliases are scoped by:

```text
tenant_id + partner_id + normalized_alias + language
```

Therefore the same supplier wording may intentionally mean different things for different clients.

Example covered by the automated security test:

```text
Raw text: "Steel Accessories"

Tenant "testinger"    -> Highlife Components
Tenant "other-tenant" -> Maintenance Hardware Kit
```

Both resolve by exact deterministic lookup with no cross-tenant leakage. Authentication binds API/MCP requests to a tenant, and PostgreSQL forced row-level security provides a second data-layer boundary.

## Operational decision vs knowledge decision

Two separate decisions prevent governance from becoming a throughput bottleneck:

1. **Operational resolution** - what canonical product may be used for this invoice line now?
2. **Knowledge promotion** - should this new wording permanently become trusted organizational knowledge?

A very-high-confidence existing-product retrieval may resolve a transaction immediately while the new alias remains staged for weekly human review. Medium/low-confidence or generated cases may remain blocking.

## Declining cost curve

For a repeated unknown description, the system atomically claims one pending candidate before generation. Repeated or concurrent occurrences reuse that record instead of paying for another proposal.

For one unique unknown repeated `N` times:

```text
maximum model proposals while pending ~= 1
average model calls per occurrence    ~= 1 / N
```

After approval, future occurrences use exact aliases and add no further model calls. The exact dollar curve depends on provider pricing and traffic mix; the architectural claim is that spend scales with **novelty**, not line-item volume.

## Delivery primitives, not business logic

The following are standard production packaging around the core tiers:

- **REST API** - application boundary for processors/reviewers;
- **MCP** - controlled integration surface for AI clients; not agent memory and not direct database access;
- **Docker / Compose** - reproducible packaging and local production-like execution;
- **GitHub Actions** - PR quality gate, live-provider evaluation, tagged release;
- **PostgreSQL migrations** - scalable persistence, integrity, forced RLS, pgvector-ready extension point;
- **SQLite + CSV** - zero-infrastructure assessment/demo runtime.

These primitives should be discussed only if the interviewer wants production depth; they are not necessary to understand the business solution.

## Invoice evidence vs canonicalization features

The invoice parser now retains a complete business envelope before line canonicalization:

```text
Invoice document
  ├─ header: number, date, due date, terms
  ├─ parties: seller, bill-to, ship-to + address/contact evidence
  ├─ financials: subtotal, discount, net subtotal, tax, shipping, amount due
  └─ lines: description, quantity, unit price, total
```

Only the final line branch is a product-canonicalization feature. Header/party/financial fields are persisted because they matter for audit, entity resolution, tenant/partner organization and financial reconciliation, but they do not change the canonical product name. This prevents a logic gap where useful invoice evidence is discarded while also preventing irrelevant PII/totals from leaking into model prompts.

The line arithmetic gate is blocking because corrupted rows would contaminate canonicalization. Document-level financial reconciliation is recorded separately: a mismatch is visible for accounting/review, but it does not automatically rename or re-route a product whose line extraction is otherwise valid.

## Data boundaries

### Approved retrieval data

- canonical products;
- approved tenant/partner aliases;
- approved attributes;
- approved client/style rules;
- taxonomy version.

### Staging data

- pending alias/product candidates;
- model proposal/provenance;
- retrieval evidence and policy scores;
- occurrence/value statistics;
- risk flags;
- human-editable overrides.

Staging data is excluded from approved retrieval until a reviewer promotes it, preventing AI mistakes from becoming self-reinforcing RAG evidence.

## Internal quality sequence (appendix-level detail)

`architecture_manifest.yaml` still machine-checks the detailed implementation order:

1. authentication and tenant binding;
2. file validation;
3. deterministic document parsing;
4. Decimal extraction quality gate;
5. model extraction fallback only after deterministic failure;
6. persist invoice header/parties/financials/raw lines;
7. text normalization;
8. taxonomy-safe cache;
9. approved exact-alias lookup;
10. atomic pending-candidate deduplication;
11. approved-only hybrid retrieval;
12. deterministic policy scoring/routing;
13. bounded generation;
14. output/attribute/security validation;
15. staged review queue;
16. human review action;
17. approved knowledge promotion;
18. audit and metrics.

This detailed sequence is an internal quality contract, **not the primary assessor-facing architecture diagram**.
