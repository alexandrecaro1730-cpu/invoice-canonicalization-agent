# Failure Taxonomy

## Business objective

Make failures observable, testable, and suitable for a safe reject, retry, staged decision, or human action without silently corrupting trusted product knowledge.

## Technical description

| Category | Examples | Safe action |
|---|---|---|
| Authentication | missing/invalid bearer key | deny; do not process |
| Authorization/tenant | processor attempts review; supplied tenant differs from principal | deny and audit |
| Input validation | unsupported type, bad signature, oversize | reject before parsing |
| Deterministic extraction | no table/rows, malformed document | OCR/model extraction fallback only if enabled; otherwise document review |
| Extraction arithmetic | qty×price mismatch, subtotal mismatch | mark FAIL; do not canonicalize extracted rows; bounded fallback or review |
| Model extraction | invalid JSON/fields, provider failure, arithmetic FAIL | reject fallback; preserve deterministic failure context; review |
| Retrieval ambiguity | low score, small margin, protected-attribute conflict | bounded model assist or blocking review |
| Pending duplication | repeated/concurrent unknown while review open | reuse atomic pending claim, increment evidence, no additional model call |
| Provider | timeout, transient 429/5xx, credential missing | bounded retry for transient failure; otherwise abstain/stage review |
| Output safety | invented color/material, unsupported field, URL/empty result | abstain and review |
| Budget | call or Decimal dollar threshold exceeded | stop further model calls; stage/review |
| Human action | missing redirect target, invalid status, stale completed review | reject that action; keep/re-export pending item where applicable |
| Persistence/concurrency | transaction conflict, duplicate active candidate | rollback/retry idempotently; uniqueness prevents duplicate model ownership |
| Currency | multiple currencies on one review cluster | retain exact per-currency amounts; do not create fake aggregate |
| CSV safety | untrusted text begins with formula prefix | escape before export |
| Knowledge poisoning | model/staged value accidentally treated as approved retrieval | block via approved-only repository boundary; release test failure |
| Quality regression | canonical/routing/LLM-use/extraction/security evaluation mismatch | block release |
| Build/reproducibility | lock mismatch, static analysis failure, package smoke failure | block release |
| Report leakage | workspace/private package-index details in generated reports | sanitize + fail report leak gate if still present |
