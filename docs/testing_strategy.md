# Testing Strategy

## Business objective

Prove not only that expected descriptions are produced, but that the system chooses the **correct reliability path**: deterministic when possible, AI only when justified, safe abstention when uncertain, and human promotion before knowledge changes.

## Technical description

The default suite is offline and deterministic. Manual model outputs are versioned in text/JSON fixtures, so pull-request CI spends no API credits and can reproduce every decision path.

## Test layers

### Unit tests

Cover:

- Unicode/text normalization and fingerprints;
- US/EU Decimal parsing and money quantization;
- line arithmetic + subtotal extraction-quality states;
- attribute extraction/conflict rules;
- retrieval lexical/token/trigram scoring and semantic extension seam;
- deterministic policy/review priority scoring;
- prompt registry/contracts;
- model-call and dollar budget accounting;
- live-provider cost calculation, worst-case estimate, response parsing and transient retry;
- authentication, roles and tenant resolution helpers;
- CSV spreadsheet-safety escaping.

### Integration tests

Cover:

- SQLite repository transactions/tenant scoping;
- exact approved aliases;
- pending review lifecycle and human actions;
- mixed-currency accumulation with per-currency values;
- CSV export/edit/process/archive behavior;
- native document parsers;
- deterministic extraction failure -> fixture-model structured extraction -> arithmetic revalidation;
- FastAPI canonicalization/review endpoints;
- authenticated cross-tenant denial and reviewer authorization;
- MCP tool/resource boundary;
- **concurrent first-seen unknown:** many simultaneous identical lines produce one active review and one model call.

### End-to-end / metamorphic tests

The evaluator-visible examples live under `data/examples/input/`. The same logical invoice is rendered as:

```text
equivalent_invoice.pdf
equivalent_invoice.docx
equivalent_invoice.xlsx
equivalent_invoice.json
equivalent_invoice.csv
equivalent_invoice.txt
```

and must converge to the same canonical results. In addition, `data/examples/input/challenge_invoice.pdf` is the actual invoice page extracted from page 2 of the supplied assessment and is exercised directly. The untouched two-page source remains under `data/reference/`. This tests the business invariant rather than one parser implementation.

### Security/adversarial tests

Include:

- prompt-injection-like descriptions;
- unsupported/hallucinated attributes;
- malformed files/signatures;
- cross-tenant calls;
- unauthorized reviewer calls;
- CSV formula injection;
- invalid provider output;
- budget exhaustion and provider failure.

### Performance tests

Local deterministic latency is bounded to catch accidental expensive work in the exact/retrieval paths. Large-scale production latency targets should be benchmarked with representative catalog sizes and concurrency, not inferred from the small fixture catalog.

## Explicit AI routing evaluation

`evals/cases/canonicalization_cases.jsonl` and `scripts/run_evaluation.py` validate more than string accuracy:

- canonical exact-match accuracy;
- transaction routing correctness;
- whether a knowledge review was required/created correctly;
- whether LLM usage matched policy;
- decision-kind correctness;
- unsafe blocking bypass count;
- unexpected model-call count.

Representative scenarios include:

1. known challenge product -> exact alias -> no LLM;
2. high-confidence unknown synonym -> existing product -> no LLM -> staged alias review;
3. novel product -> LLM -> blocking review;
4. same novel product again -> pending reuse -> no second LLM;
5. human approval -> future exact alias;
6. LLM invents unsupported attribute -> abstain;
7. injection-like input -> flagged / model not trusted;
8. provider/budget failure -> safe review path.

## Extraction quality evaluation

A parsed document can be syntactically valid and still be wrong. Tests therefore assert:

```text
quantity × unit price == line total (within Decimal tolerance)
sum line totals == declared subtotal (when declared subtotal is available)
```

Model-extraction fallback fixtures must pass the same quality gate. EU and US number formats are tested separately.

## Concurrency invariant

The important production property is **one model proposal per active normalized unknown**, including the first concurrent occurrence. The integration suite starts many workers on the same unknown and asserts:

```text
one pending review
occurrence_count == number of requests
model calls == 1
```

This protects both cost and review scalability.

## Static/reproducibility gates

The release architecture contains three static layers:

- Ruff for Python undefined-name/syntax-family lint checks;
- mypy for typed production modules;
- `scripts/static_contract.py` as a mandatory repository-level fallback for typed signatures, wildcard-import/bare-except/eval/exec rules.

Ruff/mypy are mandatory in CI and `make assess-full`. A constrained local environment that does not contain those binaries reports them as `SKIP` rather than falsely claiming they ran; the mandatory internal static contract still runs.

Dependency lock validation requires exact pins and checks direct project constraints. Package testing also builds the wheel and imports/runs it from an isolated install location.

## Quality gate sequence

`make assess` / `scripts/quality_gate.py` runs:

```text
lock validation
Ruff (if installed locally; mandatory in CI)
mypy (if installed locally; mandatory in CI)
mandatory static contract
compile
documentation gate
architecture order gate
completeness/wiring audit
secret scan
pytest + branch coverage
coverage threshold/XML
offline AI evaluation
wheel build
isolated wheel smoke
Docker build when available
report sanitization
```

`make assess-full` additionally makes Docker and external static tools mandatory.

## Live-provider testing

Paid/network evaluation is intentionally separate from normal CI. `scripts/live_provider_smoke.py` and the manual workflow require explicit credentials/model/pricing. The purpose is provider-contract validation, not replacing the deterministic offline regression suite.

## Full-invoice evidence contract

Cross-format tests now assert that PDF, DOCX, XLSX, JSON, CSV, and TXT representations preserve the same invoice number/date/terms, seller, bill-to, ship-to, addresses/contact fields, subtotal, discount, tax, shipping, amount due, and six line items before canonicalization. The same tests verify that source evidence is persisted and that canonical outcomes are linked back to the raw invoice lines.

Two failure classes are tested separately: line arithmetic corruption is a blocking extraction failure (or triggers bounded extraction fallback), while a document-level commercial mismatch such as an incorrect amount due is persisted as a failed financial reconciliation but does not alter the canonical product name.
