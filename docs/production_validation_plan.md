# Production Validation Plan

## Business objective

Define the evidence required before converting the assessment reference implementation into a production auto-resolution service.

## Technical description

The current project proves deterministic replay, routing contracts, review promotion, isolation, and packaging with curated/offline fixtures. It deliberately does not treat those regression results as population-level model evidence.

## 1. Build a blind labelled benchmark

Create a reviewer-approved dataset across:

- multiple tenants and business partners;
- common and long-tail product categories;
- languages and spelling/noise variants seen in production;
- explicit protected attributes such as color, material, size, and model;
- genuinely novel products that should abstain rather than auto-resolve.

Keep training/configuration examples separate from the blind evaluation set.

## 2. Calibrate routing thresholds to business risk

The most important error is not a missed automation opportunity; it is a **false automatic match** that silently books the wrong canonical product.

Primary rollout metrics should therefore include:

- false auto-resolution rate;
- abstention precision;
- human-review rate;
- retrieval Recall@K;
- protected-attribute conflict rate;
- tenant/partner leakage rate;
- percentage of repeated descriptions resolved by Tier 1.

Thresholds should be selected against an explicit business tolerance, for example a target false-auto-resolution rate agreed with finance/operations stakeholders.

## 3. Benchmark retrieval before enabling semantic vectors

The assessment currently uses approved lexical/token/trigram/attribute evidence. The PostgreSQL schema and interface are vector-ready, but semantic retrieval should only be enabled if labelled tests show a better operating point.

Compare:

- Recall@K;
- false-match rate;
- latency p50 / p95;
- memory/index size;
- re-indexing cost after taxonomy changes;
- performance across languages and short/noisy descriptions.

## 4. Run a controlled live-provider evaluation

Offline fixtures prove prompt/output contracts without provider drift or API cost. A production candidate still needs a controlled live evaluation covering:

- schema compliance;
- abstention behavior;
- hallucinated attributes;
- token usage;
- cost per unique unresolved concept;
- p50 / p95 latency;
- timeout/retry behavior;
- provider/model-version drift.

No live model should be allowed to mutate approved knowledge directly.

## 5. Validate document extraction on real invoice diversity

Test native and scanned invoices across:

- different templates/layouts;
- multilingual headers;
- wrapped descriptions;
- line-level discounts/taxes;
- missing subtotals or mixed commercial structures;
- decimal/thousands separator conventions;
- malformed or low-quality scans.

Track extraction success separately from canonicalization accuracy so ingestion failures do not become product-routing metrics.

## 6. Operational acceptance criteria

Before production rollout, define and measure:

- documents/hour and lines/hour;
- end-to-end p50 / p95 latency;
- queue age for blocking reviews;
- cost per 1,000 invoice lines;
- LLM calls per 1,000 lines;
- percentage of traffic using Tier 1;
- reviewer time per unique unresolved concept;
- rollback/audit completeness;
- incident and reprocessing procedures.

## 7. Rollout sequence

A sensible rollout is:

1. shadow mode - compare decisions without affecting booking;
2. reviewer-only suggestions - all uncertain decisions confirmed;
3. auto-resolve exact approved aliases;
4. enable only empirically calibrated high-confidence retrieval paths;
5. expand by tenant/category after monitoring confirms error targets.

The key principle remains unchanged: **automation expands only when measured evidence supports it.**
