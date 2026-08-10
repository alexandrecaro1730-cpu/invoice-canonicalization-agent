# Scalability

## Business objective

Scale from an assessment catalog to high invoice volume while reducing model calls and human work as approved knowledge grows.

## Technical description

The main scaling strategy is **knowledge reuse**: exact approved aliases are O(index lookup) and cost no model tokens. New unknowns are deduplicated before model generation and reviewed as unique knowledge candidates rather than per invoice line.

## Scaling path

1. **Exact alias first.** Mature catalogs should drive most traffic through indexed approved aliases.
2. **Atomic unknown claim before AI.** The first worker creates a placeholder under a uniqueness constraint before generation. Concurrent/repeated unknowns attach to it and do not independently call the model.
3. **Partition retrieval.** Tenant and partner scope is mandatory; category/other metadata can further reduce candidate sets.
4. **Cache only safe final decisions.** Include taxonomy/version context so stale decisions cannot override newly approved knowledge.
5. **Keep staging separate from approved retrieval.** This prevents self-reinforcing model errors.
6. **Asynchronous document work.** Put document ingestion behind a queue for burst traffic; process independent lines concurrently while preserving candidate-claim atomicity.
7. **Object storage for raw invoices.** Keep document hashes and structured evidence in the transactional database, not large raw blobs.
8. **PostgreSQL for multi-worker production.** Use pooling, indexes/partitions where justified, normalized `review_occurrences`, and forced RLS.
9. **Optional semantic/vector retrieval only after benchmarks.** The runnable assessment uses deterministic hybrid retrieval. A semantic provider/pgvector adapter can be enabled when labelled recall/false-match/latency tests justify it.
10. **Precompute embeddings in batches if semantic retrieval is enabled.** Do not recompute approved catalog embeddings per invoice.
11. **Bounded provider usage.** One active unknown should have at most one proposal; use timeout, retry caps, call/cost budgets and model-call metrics.
12. **Separate online resolution from offline knowledge maintenance.** Promotion, taxonomy updates and vector refresh can be asynchronous.
13. **Prioritize reviewer leverage.** Sort by occurrence count, risk, age and financial impact rather than FIFO alone.

## Review scale

For a repeated unknown appearing many times:

```text
N invoice occurrences
-> 1 normalized pending candidate
-> <= 1 model proposal while pending
-> 1 human knowledge decision
-> 1 approved alias/product update
-> future occurrences become exact deterministic lookups
```

Local SQLite keeps bounded evidence samples plus aggregate counts. PostgreSQL stores occurrences in `review_occurrences`, avoiding ever-growing JSON arrays.

## Money and currency scale

Financial values use `Decimal`. Candidate impact is stored per currency. When a candidate spans currencies, the system does not sum EUR + USD into one fake amount; review/UI code uses the per-currency map and can either prioritize on frequency or apply an explicitly governed FX-normalization service later.

## Retrieval scale

Current retrieval is intentionally deterministic for the small assessment catalog. At larger scale, candidate reduction should happen before expensive similarity work. If semantic search is introduced, compare exact vector search, HNSW and IVFFlat using labelled retrieval recall, false auto-resolution rate, memory, build/update cost and p95 latency. The approximate index choice must follow measurement, not architecture fashion.

## Suggested service-level indicators

- approved exact-alias rate;
- exact-alias p50/p95 latency;
- document extraction PASS/WARN/FAIL rate by format;
- model-extraction fallback rate;
- retrieval recall@k and false-match rate;
- operational auto-resolution precision;
- blocking human-review rate;
- pending unique candidates vs affected invoice lines;
- model calls per 1,000 invoice lines;
- model calls avoided by pending-candidate reuse;
- provider cost per 1,000 lines/documents;
- review backlog age and top-N review leverage;
- approval/edit/reject rates;
- tenant authorization failures/leakage incidents (leakage target: zero).

## Invoice evidence at scale

Product aliases and invoice evidence have different scaling patterns. Canonical aliases are compact reusable knowledge; invoice headers/party snapshots/financials are immutable operational history. The production schema therefore keeps them in separate normalized tables and indexes invoices by `(tenant_id, partner_id, invoice_number)` plus party names for tenant-scoped search/entity resolution.

At larger volume, raw invoice documents can move to object storage while PostgreSQL retains hashes, extracted evidence, and canonical outcomes. Repeated party snapshots can later resolve to ERP customer/vendor master IDs through `external_id`; the snapshot remains on the invoice so historical evidence is not rewritten when a master address changes.
