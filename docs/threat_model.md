# Threat Model

## Business objective

Prevent invoice content, model output, tenant mistakes, reviewer actions, or deployment configuration from leaking customer data or promoting unsafe knowledge.

## Technical description

### Trust boundaries

1. Uploaded documents and invoice descriptions are untrusted input.
2. Authentication proves the application principal; caller-supplied tenant identifiers are not trusted in production.
3. Approved catalog data is trusted business knowledge; staged/model-generated candidates are not.
4. External model providers are outside the trusted data boundary.
5. Human reviewers are authorized actors, but their actions are still validated and audited.
6. CSV exports may be opened by spreadsheet software and therefore require formula-injection defenses.
7. CI/build logs may contain environment-specific paths/indexes and are sanitized before delivery evidence is published.

### Implemented controls

| Threat | Control |
|---|---|
| Cross-tenant request | bearer principal binds tenant; mismatching `tenant_id` is rejected; repository predicates and PostgreSQL forced RLS add defense in depth |
| Unauthorized knowledge mutation | reviewer role required for review endpoints/actions |
| Prompt injection in invoice text | invoice text is treated as data; input guard flags instruction-like payloads; model receives constrained prompts and no direct database tool |
| PII over-sharing | extraction fallback minimizes raw text before provider use; contact fields are not required for product canonicalization |
| Hallucinated attributes | generated structured output is checked against protected/source attributes; unsupported additions cause abstention/review |
| Knowledge-base poisoning | staged candidates are excluded from approved retrieval until human promotion |
| Repeated/parallel model amplification | atomic pending-candidate claim occurs before generation; concurrent repeats reuse one candidate/model proposal |
| Model-cost abuse | per-document call + Decimal dollar budget, pre-call worst-case estimate, max output, timeout and bounded retries |
| Provider transient failure | only bounded retry on transient failures; safe abstention/review otherwise |
| Malformed/oversized input | allow-listed extension/signature/size checks before parsing |
| Bad extraction | Decimal row/subtotal arithmetic gate; model fallback must pass the same gate |
| CSV formula injection | untrusted cells beginning with spreadsheet formula prefixes are escaped on export |
| Mixed-currency misleading totals | exact per-currency breakdown is stored; cross-currency values are not summed as if comparable |
| Secret leakage | credentials are environment/secret-manager inputs; repository secret scanner; reports redact workspace/private-index details |
| Container privilege | non-root runtime, hardened Compose capabilities/security options, health check |
| Supply-chain drift | exact runtime/dev lock files checked against `pyproject.toml`; container installs runtime wheels from an offline wheelhouse |
| Silent AI regression | versioned prompts/fixtures, offline routing evaluation, tests for LLM-use discipline and false blocking bypasses |

### Security invariants

- A model response cannot directly create an approved alias/product.
- A pending candidate cannot be used as approved RAG evidence.
- A production caller cannot choose another tenant by editing request JSON/query parameters.
- Reviewer permissions are separate from processing permissions.
- Financial extraction is never accepted only because a model produced syntactically valid JSON.
- Model calls stop when the shared call/dollar budget is exhausted.
- Completing the active review queue never deletes audit history.

### Remaining production integration work

The assessment includes application-level tenant-bound API keys and forced database RLS, but an enterprise deployment should still integrate them with the organization’s identity/security platform. Typical production additions are:

- gateway/OIDC workload and user identity instead of the assessment API-key mechanism;
- KMS/vault-backed secrets and key rotation;
- TLS/mTLS and explicit egress allow-lists;
- encrypted object storage and database encryption/backups;
- malware/content scanning for uploaded files where required;
- centralized tamper-evident audit retention and reviewer identity/signature capture;
- API rate limiting/WAF and abuse monitoring;
- formal data retention/deletion and privacy impact policy;
- SAST/SCA/container vulnerability scanning and SBOM/signing in the organization’s release platform.

These are deployment-platform responsibilities rather than reasons to make the local assessment depend on proprietary infrastructure.

## Invoice party/contact privacy boundary

Invoice parties and addresses are useful tenant-scoped business evidence, so the database retains seller/bill-to/ship-to snapshots, phone numbers, emails, and addresses. These values are not authorization inputs and cannot override the authenticated tenant. They are also excluded from product-canonicalization prompts; adversarial tests verify that party PII and document-level financial values remain outside the bounded model context.

For a real deployment, database encryption at rest, field-level access controls where required, retention/deletion policies, and data-classification rules should be aligned with the organization's privacy and accounting obligations. Those deployment policies are outside the supplied assessment data and are therefore documented rather than invented here.
