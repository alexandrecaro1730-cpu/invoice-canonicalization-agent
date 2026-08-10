# Human Review Queue

## Business objective

Let operations review **new knowledge**, not individual invoices. Large invoice volume should collapse into a small set of unique candidate aliases/products that can be reviewed weekly.

## Technical description

SQLite is the local authoritative store. The human-facing CSV is an editable projection for the assessment/demo. Production should use the same application service behind an authenticated UI/API and PostgreSQL. CSV is not the long-term source of truth.

## Lifecycle

```text
invoice line
  -> exact approved alias? return immediately
  -> atomically claim/reuse pending normalized candidate
       -> existing claim: increment occurrence/value; no model call
       -> new claim: continue
  -> approved-only retrieval + policy score
       -> very high confidence existing product: resolve invoice, stage alias, no LLM
       -> uncertain/new: one constrained LLM proposal, update same pending claim
  -> reviewer work queue
  -> approve existing / redirect / create new / edit+approve / reject / defer
  -> processed outcome archived/audited
  -> successful approval promotes trusted knowledge
  -> future matching becomes deterministic
```

The placeholder-before-generation design is important: it prevents two workers that discover the same new unknown at the same time from both calling the model.

## CSV contract

The final column is always `status`, defaulting to `waiting_for_approval`.

Important read-only evidence columns include:

```text
review_id / tenant_id / partner_id / candidate_key
occurrence_count
affected_value
affected_values_json
currency
first_seen_at / last_seen_at
source_description / bounded source variants and source line samples
proposed description/category/attributes
target_product_id
decision_score / retrieval_score / retrieval_margin / priority_score
llm_used / provider / model / prompt_version
risk_flags_json / evidence_json
blocks_transaction
```

Reviewer-editable columns are:

```text
approved_description_override
target_product_id_override
category_override
reviewer_notes
status
```

Supported `status` values:

- `waiting_for_approval` — no action; keep active.
- `approve_existing` — promote clustered aliases to the proposed or reviewer-selected existing product.
- `approve_new` — create the proposed canonical product and promote aliases.
- `edit_and_approve` — use reviewer description/category; optionally map to an existing target override, otherwise create a new product.
- `redirect` — require `target_product_id_override`; map to that existing product.
- `reject` — do not promote; archive decision and remove from active queue.
- `defer` — record deferral but keep pending; export returns status to `waiting_for_approval` for idempotent future processing.

Evidence/scores should not be manually changed; processing ignores them as authoritative mutation inputs.

## Currency handling

`affected_value` is a convenient single-currency value only when one currency is applicable. `affected_values_json` stores exact `Decimal` totals by currency. For mixed currencies, `currency=MIXED` and the single affected value is not used as a fake EUR+USD sum. A production UI can display the breakdown or apply a separately governed FX normalization policy.

## Spreadsheet safety

Invoice descriptions are untrusted. CSV export escapes leading `=`, `+`, `-`, or `@` so opening the file in spreadsheet software cannot directly interpret an invoice string as a formula.

## Weekly workflow

```bash
make review-export
# edit .runtime/review_queue.csv
make review-process
```

For a ready-made demonstration:

```bash
make review-demo
```

For a more concise interview narrative that also shows approval -> future exact matching:

```bash
make interview-demo
```

## Why completed rows disappear but history remains

`review-process` rewrites the active CSV from authoritative pending records. Successfully completed actions are appended to `.runtime/review_archive.jsonl`, and database audit/review state remains available. This gives the requested clean weekly work queue without destroying traceability.

## Scalability

Local SQLite retains bounded source/evidence samples plus aggregate occurrence/value counters. The PostgreSQL migration uses a separate `review_occurrences` table, so millions of occurrences do not create an unbounded candidate JSON record. A partial uniqueness rule ensures one active tenant/partner/candidate key, supporting atomic first-seen deduplication across workers.
