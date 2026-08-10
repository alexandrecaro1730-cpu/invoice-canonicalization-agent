# Assessor Summary

## Business objective

Explain the solution in the shortest business-first narrative while clearly separating what solves the assignment from what productionizes it.

## Technical description

This summary is the recommended interview storyline for version 1.0.0. Detailed security, persistence, CI/CD, MCP, and internal stage sequencing remain available in the appendix documentation.

## The original problem

The source system asks an LLM to describe invoice products and receives different wording on repeated runs. The requirement is reproducibility: equivalent booking text should converge to one stable canonical identity and description.

## The design thesis

**Do not ask a language model a question the organization has already answered.**

The core therefore has three tiers:

1. **Deterministic no-LLM lookup** - approved tenant/partner aliases return an exact canonical product with no model inference.
2. **Bounded retrieval / AI fallback** - only unknown descriptions consume retrieval; uncertain cases receive at most one constrained proposal per unique pending concept and may abstain instead of forcing a match.
3. **Governed human learning** - human approvals promote aliases/products so future occurrences return to Tier 1.

Document parsing is upstream. REST, MCP, Docker, CI/CD, and PostgreSQL are delivery primitives around the solution.

## What we retain from the invoice

The source document is not reduced to product text. The database retains invoice number/date/terms, seller, bill-to, ship-to, address/contact evidence, line amounts, subtotal, discount, tax, shipping and amount due. These fields support client/partner organization, audit and reconciliation. They are deliberately **decoupled** from product naming: canonicalization receives the line description and approved product evidence, not addresses, emails or invoice-level charges.

## Why the arithmetic extraction gate matters

Canonicalization is only useful if the invoice rows were extracted correctly. Before product routing, complete rows are checked with Decimal arithmetic and the calculated subtotal is compared with the document subtotal when available. Corrupted OCR/parser output is stopped before it can pollute normalization, retrieval, or model prompts.

## How to interpret the supplied challenge

The six challenge mappings are deliberately seeded approved aliases. Therefore the 6/6 outcome is an **integration smoke test**, not an ML accuracy benchmark. It proves that once knowledge is approved, replay is deterministic, auditable, and requires no canonicalization model call.

## Multi-client taxonomy collisions

Aliases are scoped by tenant and partner. Identical raw wording may map to different internal products without leakage. The project explicitly tests `Steel Accessories` resolving to different canonical products for `testinger` and `other-tenant`.

## Economics

Unknowns are deduplicated before generation, so repeated occurrences attach to one candidate. Human approval converts that candidate into exact knowledge. As the catalog matures, the share of Tier 1 traffic grows and the average model-call rate declines toward zero for recurring descriptions.

## What is core vs optional

### Core business logic

- normalization;
- approved alias catalog;
- tenant/partner scoping;
- retrieval policy;
- bounded generation for uncertainty;
- human promotion of trusted knowledge.

### Operational guardrails

- extraction arithmetic gate;
- security/input validation;
- cost budgets/timeouts/retries;
- audit and observability.

### Delivery primitives

- REST;
- MCP;
- Docker;
- CI/CD;
- PostgreSQL migrations.

The project includes the latter groups to show production readiness, but the interview should lead with the core business logic.
