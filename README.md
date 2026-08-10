# Invoice Canonicalization Agent

A production-oriented reference implementation for turning inconsistent invoice product descriptions into **stable, tenant-scoped canonical product identities**.

> **Do not ask an LLM a question the organization has already answered.**

Known descriptions resolve through approved deterministic knowledge with **no LLM call**. Unknown descriptions enter a bounded uncertainty path, and human approval converts successful decisions into trusted aliases for future exact lookup.

## At a glance

- **Known product:** exact approved alias → canonical product ID → no LLM call
- **Unknown product:** approved retrieval → bounded AI only if needed → human review / abstain
- **After approval:** future occurrences return to deterministic lookup
- **Document inputs:** PDF, DOCX, XLSX, JSON, CSV, TXT
- **Invoice evidence retained:** parties, addresses, dates, quantities, prices, discount, tax, shipping, amount due
- **Tenant-safe taxonomy:** the same raw description can map differently for different clients / partners
- **Quality gate:** extraction arithmetic is validated before canonicalization
- **Demo:** `make interview-demo`
- **Offline test suite:** 107 tests passing, branch-aware coverage above the configured 80% threshold

## The problem

The assessment describes invoice line items whose descriptions may be rewritten differently on repeated LLM runs. The business requirement is not more creative text generation; it is **reproducibility across invoices, clients, and business partners**.

This project separates the problem into two boundaries:

```text
DOCUMENT RELIABILITY
PDF / DOCX / XLSX / JSON / CSV / TXT
        |
        v
deterministic extraction
        |
        v
arithmetic + reconciliation checks
        |
        v
clean invoice evidence

PRODUCT CANONICALIZATION
        |
        +--> Tier 1: approved exact lookup ----------> canonical product ID
        |
        +--> Tier 2: approved retrieval / bounded AI / abstain
        |                     |
        |                     v
        +--> Tier 3: governed human approval
                              |
                              v
                        trusted future alias
```

The goal is **not to make the LLM more consistent**. The goal is to **need the LLM less often**.

## Run it locally

Recommended: Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
```

Run the supplied invoice:

```bash
make demo
```

Run the interview walkthrough:

```bash
make interview-demo
```

Run the automated tests:

```bash
make test
```

Run the full offline quality gate:

```bash
./run_assessment.sh
```

For the strict release gate with Ruff, mypy, and Docker required:

```bash
make assess-full
```

## Three-tier canonicalization

### Tier 1 — deterministic approved lookup

Approved aliases are scoped by tenant, business partner, language, and taxonomy version. A known description returns the same canonical product ID every time without calling a model.

Example:

```text
Socks, black
    ↓ exact approved alias
Crew Socks
    ↓
0 LLM calls
```

### Tier 2 — bounded uncertainty handling

If no exact approved alias exists, the system:

1. atomically deduplicates the unresolved concept;
2. retrieves evidence from **approved knowledge only**;
3. applies deterministic routing rules;
4. may use one constrained model proposal when evidence remains insufficient;
5. can **abstain** rather than silently trust an uncertain answer.

Unreviewed model output never enters the approved catalog.

### Tier 3 — governed human learning

Reviewers approve knowledge changes rather than individual invoices. An approved mapping is promoted to the tenant-scoped catalog so future occurrences return to Tier 1.

For recurring unknown concepts, model spend therefore follows **novelty**, not repeated line-item volume.

## Wild → tamed example

A novel description such as:

```text
Black Leather Jacket Midnight
```

enters the uncertainty path. The bounded fixture provider proposes:

```text
Black Leather Jacket
```

While that concept is pending, repeated equivalent occurrences reuse the same candidate rather than repeatedly calling a model.

After human approval:

```text
Black Leather Jacket Midnight
    ↓ approved alias
Black Leather Jacket
    ↓
future exact lookup
0 additional LLM calls
0 additional human review
```

Run the complete lifecycle with:

```bash
make interview-demo
```

## Why every product is checked first

Known and unknown products pass through the **same extraction-quality boundary** before canonicalization.

The line-level gate uses `Decimal` arithmetic to verify:

```text
quantity × unit_price == line_total
sum(line_totals) == subtotal
```

Commercial reconciliation separately records and checks:

- discount;
- subtotal after discount;
- tax rate and tax amount;
- shipping / handling;
- final amount due.

This prevents corrupted OCR or parser output from contaminating normalization, retrieval, or model prompts.

## Full invoice evidence is retained

Canonicalization uses only the evidence required to identify a product, but the ingestion layer does **not discard the rest of the invoice**.

The persisted invoice envelope includes:

- invoice number, invoice date, due date, and payment terms;
- seller / issuer, bill-to, and ship-to snapshots;
- addresses and contact evidence;
- original line descriptions, quantities, unit prices, and line totals;
- subtotal, discount, net subtotal, tax rate, tax amount, shipping / handling, and amount due;
- canonical product outcomes and review status for each line.

Invoice-level PII and financial fields support audit, reconciliation, and client / partner organization, but they are deliberately **excluded from product-generation prompts**.

See [`docs/invoice_data_model.md`](docs/invoice_data_model.md).

## Supplied assessment input

The runnable invoice used by the demo is:

```text
data/examples/input/challenge_invoice.pdf
```

The complete original two-page assessment is retained under:

```text
data/reference/Challenge_Data_Scientist.pdf
```

Equivalent full-invoice examples are also provided as PDF, DOCX, XLSX, JSON, CSV, and TXT so the same business result can be regression-tested across formats.

The six supplied line descriptions resolve to these approved mappings:

| Source description | Canonical description |
|---|---|
| Highlife Steel Accessories | Highlife Components |
| Sneaker “Unstoppable” | Performance Sneakers |
| T-Shirt White “Polarbear” | White Tee |
| T-Shirt Beige “Grizzly” | Beige Tee |
| Shorts “El Camino” | Casual Shorts |
| Socks, black | Crew Socks |

> **Important:** the `6/6` result is an **integration smoke test**, not an ML-accuracy claim. The aliases are intentionally pre-approved to prove deterministic replay.

## Multi-client taxonomy safety

Raw descriptions are **not global keys**.

Approved alias uniqueness is scoped by:

```text
tenant_id + partner_id + normalized_alias + language
```

The automated test suite includes the same raw description, `Steel Accessories`, intentionally resolving to different canonical products for different tenants.

Authentication binds the caller to a tenant, and the PostgreSQL migration adds forced row-level security as defense in depth.

## Quality and evaluation

The project uses deterministic offline fixtures in CI so regression tests do not spend API credits or drift with provider changes. Live-provider evaluation is intentionally opt-in.

The quality gate covers:

- compilation and documentation contracts;
- architecture and completeness validation;
- secret scanning;
- unit, integration, E2E, security, concurrency, and contract tests;
- branch coverage with a configured `>= 80%` threshold;
- curated routing regression cases;
- package build and isolated wheel installation;
- Docker when available / required;
- report sanitization.

Useful evidence files:

- [`reports/final_delivery_check.md`](reports/final_delivery_check.md)
- [`reports/evaluation.json`](reports/evaluation.json)
- [`reports/interview_demo.json`](reports/interview_demo.json)
- [`docs/verified_results.md`](docs/verified_results.md)

## Repository map

```text
data/
  examples/input/           runnable full-invoice examples
  examples/expected/        deterministic smoke-test contract
  reference/                original assessment
  seed/                     approved catalog + tenant style data
  review_queue/             editable review-queue template

src/invoice_canonicalizer/
  domain/                    framework-independent records and rules
  application/               ingestion, canonicalization, review, budgets
  infrastructure/documents/  PDF/DOCX/XLSX/JSON/CSV/TXT adapters
  infrastructure/db/         portable SQLite repository
  infrastructure/retrieval/  approved-only hybrid retrieval
  infrastructure/llm/        prompt registry + fixture/live providers
  security/                  validation, minimization, injection controls
  observability/             structured metrics/logging
  api/                       FastAPI delivery boundary
  mcp/                       stateless MCP delivery boundary

migrations/postgres/         production relational/RLS direction
prompts/                     versioned extraction/canonicalization prompts
scripts/                     quality gates, demos, scans, evaluation
tests/                       unit/integration/e2e/security/contracts
docs/                        architecture, data model, operations, testing
presentation/                editable PPTX + rendered PDF + story assets
```

## Production boundary

The assessment runtime intentionally uses SQLite and CSV so the project runs locally without external infrastructure.

The production direction is explicit but separate from the core canonicalization logic:

- PostgreSQL for relational persistence and tenant-level integrity;
- forced row-level security for tenant isolation;
- object storage for original documents;
- queues / workers for asynchronous document processing when volume justifies them;
- pgvector-ready schema, with semantic retrieval enabled only after benchmark evidence shows it improves the Recall@K / false-match trade-off.

REST, MCP, Docker, CI/CD, and PostgreSQL are **delivery primitives**, not the product-canonicalization algorithm itself.

## What this project does not claim

- The seeded challenge `6/6` result is **not** evidence of unseen-product model accuracy.
- The curated routing set is regression evidence, not a population-level benchmark.
- A pgvector seam exists, but semantic retrieval is **not** claimed to outperform the current approved lexical hybrid until benchmarked.
- Offline fixture execution does not prove real-provider cost, latency, or drift behavior.

Those limits are intentional and documented rather than hidden.

See [`docs/production_validation_plan.md`](docs/production_validation_plan.md) for the validation required before production rollout.

## Presentation

The assessor-facing presentation uses a short visual **wild → tamed** story for the opening and then maps the metaphor back to the production architecture. Detailed engineering material is kept in the appendix.

- [`presentation/Invoice_Canonicalization_Agent_Assessment.pptx`](presentation/Invoice_Canonicalization_Agent_Assessment.pptx)
- [`presentation/Invoice_Canonicalization_Agent_Assessment.pdf`](presentation/Invoice_Canonicalization_Agent_Assessment.pdf)

## API, MCP, and review workflow

Run the API:

```bash
make api
```

Run the MCP integration boundary:

```bash
make mcp
```

Run the human-review demo:

```bash
make review-demo
# edit .runtime/review_queue.csv
make review-process
```

## CI and releases

GitHub Actions includes:

- pull-request / `main` CI with static analysis and the offline quality gate;
- an independent Docker build / smoke job;
- manual live-model evaluation;
- tagged release packaging.

## Detailed documentation

Start with:

- [`docs/assessor_summary.md`](docs/assessor_summary.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/invoice_data_model.md`](docs/invoice_data_model.md)
- [`docs/testing_strategy.md`](docs/testing_strategy.md)
- [`docs/threat_model.md`](docs/threat_model.md)
- [`docs/review_queue.md`](docs/review_queue.md)
- [`docs/operating_runbook.md`](docs/operating_runbook.md)
- [`docs/scalability.md`](docs/scalability.md)
- [`docs/production_validation_plan.md`](docs/production_validation_plan.md)
- [`docs/interview_talk_track.md`](docs/interview_talk_track.md)

Every production Python module and prompt includes a **Business objective** and **Technical description**, enforced by the documentation quality gate.
