# ADR 001: Bounded workflow instead of autonomous multi-agent execution

## Business objective

Meet the reproducibility requirement while minimizing cost and silent errors.

## Technical description

**Decision:** use deterministic parsing, alias lookup, and retrieval first. Use one constrained proposal provider only when approved knowledge is insufficient. Require human approval for every new alias or product.

**Consequences:** known lines are fast and reproducible; model spend is low; approval provides auditability. The system is less autonomous by design.
