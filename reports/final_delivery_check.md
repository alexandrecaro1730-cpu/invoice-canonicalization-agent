# Final Delivery Check

## Business objective

Record the final assessor-facing verification for the deterministic-first invoice canonicalization package.

## Technical description

Package version: `1.0.0`. Detailed machine-readable evidence remains in `quality_summary.*`, `evaluation.json`, `interview_demo.json`, and `demo_output.json`.

| Check | Result | Evidence |
|---|---|---|
| Offline quality gate | PASS | `reports/quality_summary.html` |
| Automated tests | 107 passed | pytest + branch coverage |
| Branch-aware coverage | 83% | threshold >= 80% |
| Exact lock validation | PASS | 16 runtime + 40 dev/CI exact pins |
| Mandatory internal static contract | PASS | typed-signature / unsafe-Python contract |
| Ruff in this sandbox | SKIP | CI/`make assess-full` requires Ruff |
| mypy in this sandbox | SKIP | CI/`make assess-full` requires mypy |
| Secret scan | PASS | no committed credential pattern |
| Report sanitization | PASS | no workspace/private-index leakage in text reports |
| Challenge integration smoke test | PASS | seeded replay: 6/6 exact aliases; 0 canonicalization LLM calls; not an ML-accuracy claim |
| Challenge extraction quality | PASS | Decimal row arithmetic + subtotal check |
| Full invoice context | PASS | seller/bill-to/ship-to, dates/terms, discount, tax, shipping and amount due persisted |
| Commercial reconciliation | PASS | discount + tax + shipping + amount-due checks are separate from product naming |
| Offline routing evaluation | PASS | 11 curated cases |
| False blocking bypasses | 0 | target 0 |
| Unexpected LLM calls | 0 | target 0 |
| Interview demo regression | PASS | deterministic -> retrieval -> LLM -> dedup -> human approval -> learned exact alias |
| Wheel build | PASS | generated under `reports/wheels/` by the quality gate (git-ignored build artifact) |
| Isolated wheel smoke | PASS | installed outside source tree |
| Docker execution in this sandbox | SKIP | strict CI / `make assess-full` requires Docker |
| Assessor presentation | PRESENT | `presentation/Invoice_Canonicalization_Agent_Assessment.pptx` + `.pdf` |

## Assessor-facing three-tier architecture

1. **Tier 1 - deterministic approved lookup:** exact tenant/partner aliases, zero model call.
2. **Tier 2 - bounded retrieval / AI / abstention:** use approved evidence first, allow one bounded proposal for unresolved uncertainty, and abstain rather than force an unsafe match.
3. **Tier 3 - governed human learning:** promote approved knowledge so future occurrences return to Tier 1.

Document extraction/arithmetic validation is an upstream reliability guardrail. Full invoice header, party snapshots and commercial totals are persisted for audit/reconciliation but excluded from product naming. REST, MCP, Docker, CI/CD, and PostgreSQL are delivery primitives around the core.

## Internal machine-checked processing order (appendix)

1. Authentication and tenant binding
2. File validation
3. Deterministic document parsing
4. Decimal extraction quality gate
5. Model extraction fallback only after deterministic failure
6. Persist invoice header, party snapshots, financials and raw lines
7. Text normalization
8. Safe taxonomy-versioned cache precheck
9. Approved exact-alias lookup
10. Atomic pending-candidate deduplication
11. Approved-only hybrid retrieval
12. Deterministic policy scoring/routing
13. Bounded generation
14. Output/attribute/security validation
15. Staged review queue
16. Human review action
17. Approved knowledge promotion
18. Audit and metrics

The detailed order is machine-checked by `architecture_manifest.yaml` and `scripts/validate_architecture.py`, but it is intentionally not the primary presentation diagram.

## Delivery caveat

The current execution environment does not contain Ruff, mypy, or a Docker engine, so those external-tool gates are reported explicitly as `SKIP` locally rather than being misrepresented as executed. GitHub CI installs the exact dev lock, sets `REQUIRE_STATIC_TOOLS=1`, and independently builds the container; `make assess-full` makes both static tools and Docker mandatory in a suitable release environment.