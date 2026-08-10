# Verified Results Snapshot

## Business objective

Provide a concise, assessor-readable record of what the final repository actually verified locally, while separating regression evidence from production claims.

## Technical description

This snapshot is regenerated/confirmed for the final `v1.0.0` assessment delivery. Machine-readable reports can be recreated with `./run_assessment.sh`.

## Final local verification

- 107 automated tests passed.
- Branch-aware coverage: 83%, above the configured 80% minimum.
- Six supplied challenge descriptions replay through seeded approved aliases with zero canonicalization LLM calls.
- Challenge invoice extraction passes line arithmetic and subtotal reconciliation.
- Eleven curated routing cases match their expected canonical/routing behavior.
- Repeated unresolved `Black Leather Jacket Midnight` occurrences reuse one pending concept/model proposal; after human approval, the next occurrence is an exact approved alias with zero additional LLM calls.
- Cross-tenant collision behavior is covered: identical raw text may map to different canonical products under different tenant scopes.
- Package wheel builds and passes isolated-install smoke testing.
- Secret/report-sanitization gates pass.

## Interpretation

These results prove **regression correctness and deterministic workflow behavior for the tested contracts**. They do not prove population-level unseen-product accuracy, statistically calibrated thresholds, real-provider latency/cost, or semantic-vector superiority.

See `docs/production_validation_plan.md` for the evidence required before production rollout.
