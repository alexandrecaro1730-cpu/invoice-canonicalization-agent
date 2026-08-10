# Operating Runbook

## Business objective

Give operators a clear response path for authentication, extraction, model, database, human-review, latency, cost, and quality incidents.

## Technical description

### Startup / release prerequisites

- install exact `requirements-dev.lock` pins and the project with `--no-deps`;
- production config must use `auth.mode=api-key` (or an organizational replacement at the gateway) and inject `ICA_API_KEYS_JSON` from a secret manager;
- replace example model pricing with the approved current contract before live calls;
- provide model credentials through the configured secret environment variable;
- run `make assess-full` in the release environment so Ruff, mypy and Docker are mandatory;
- test PostgreSQL migrations/RLS against staging identities/data.

### Health checks

`/health` confirms process liveness. `/ready` validates repository initialization and reports taxonomy version. `/metrics` exposes routing/model counters. Authenticated review endpoints expose the pending knowledge backlog for the principal’s tenant.

### Weekly review operation

```bash
make review-export
# edit only the reviewer override/notes/status columns in .runtime/review_queue.csv
make review-process
```

Successfully processed items are removed from the active CSV. Outcomes are appended to `.runtime/review_archive.jsonl`; authoritative review/audit history is retained. Deferred/invalid actions remain pending. Never delete audit history merely to make the active queue empty.

### Common incidents

**Authentication/authorization failure:** verify bearer injection, principal tenant/roles, and auth configuration. Never “fix” a failure by trusting a request-provided tenant. Reviewer mutations require the reviewer role.

**Deterministic extraction failure:** inspect parser/quality category, not raw PII in logs. Check file validity and whether line/subtotal arithmetic failed. If local OCR/model extraction fallback is enabled, confirm its result passes the same Decimal arithmetic gate before accepting it.

**High model-extraction fallback rate:** investigate upstream document/layout/parser changes. A rising fallback rate is a reliability/cost regression even if outputs still pass.

**Model provider failure:** the workflow abstains/keeps a pending review. Check credentials, endpoint, configured pricing, timeout, token cap, response contract and remaining document budget. Retry is intentionally bounded; repeated invoice lines should attach to one pending candidate rather than cause repeated calls.

**Cost spike:** inspect model-call attempts, fallback rate, pending-dedup savings, model/token usage and configured prices. Verify no taxonomy/cache regression pushed known aliases into AI paths.

**Review backlog growth:** compare unique candidates vs affected occurrence count, sort by priority/age, and verify atomic candidate deduplication. Increase reviewer capacity or change thresholds only after labelled evaluation shows the false-auto-resolution objective remains satisfied.

**Accuracy regression:** compare taxonomy, prompt, fixture, model, retrieval/policy and code versions. Run `make assess`; inspect evaluation and interview-demo evidence. Roll back the immutable release if canonical/routing/LLM-use/security metrics regress.

**Latency increase:** separate parser, extraction quality, exact alias, pending lookup, retrieval, repository and provider timings. Verify database indexes/pooling, cache hit rate and model-call percentage.

**Suspected tenant leak:** disable affected integration, preserve audit evidence, rotate credentials if relevant, verify API principal binding and database RLS, and follow organizational incident response.

**Review CSV spreadsheet alert/formula behavior:** do not remove CSV escaping. Untrusted invoice text is intentionally neutralized before spreadsheet export.

### Live-provider smoke test

Normal CI is offline. A live smoke requires explicit model, API key and contract pricing:

```bash
export ICA_PROVIDER=openai-compatible
export ICA_MODEL='<approved-model>'
export ICA_MODEL_INPUT_COST_PER_MILLION='<approved-price>'
export ICA_MODEL_OUTPUT_COST_PER_MILLION='<approved-price>'
# Inject OPENAI_API_KEY through the deployment secret manager before this command.
python scripts/live_provider_smoke.py
```

Do not run this automatically on ordinary pull requests.

### Release checklist

- `make assess-full` passes in the release/CI environment;
- exact dependency locks validated;
- Ruff/mypy/static contract clean;
- extraction quality + model fallback tests pass;
- auth/tenant/reviewer security tests pass;
- routing thresholds, prompt/taxonomy/model versions reviewed;
- PostgreSQL migrations and forced RLS tested;
- secret and sanitized-report gates clean;
- container runs as non-root and health check passes;
- rollback package/image is available;
- live provider smoke manually approved when applicable;
- review backlog, fallback rate, model-call, cost and safety dashboards/alerts are active.
