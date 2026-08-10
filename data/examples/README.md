# Runnable Example Inputs

## Business objective

Make the assessment inputs obvious to an evaluator: the application can be run directly against a real PDF invoice and equivalent representations in the other supported document formats.

## Technical description

- `input/challenge_invoice.pdf` is page 2 of the supplied assessment PDF and is the primary real PDF demo input.
- `input/equivalent_invoice.*` files contain the same **full invoice** rendered as PDF, DOCX, XLSX, JSON, CSV, and TXT: header, seller/bill-to/ship-to parties, addresses/contact evidence, six line items, discount, tax, shipping and amount due.
- `expected/challenge_expected.json` records both the source-derived invoice metadata contract and the approved canonical outputs used by the deterministic integration smoke test.

The six approved challenge mappings are intentionally seeded in `data/seed/catalog.json`; therefore successful replay is evidence of deterministic integration, not a claim of model accuracy.

Run the real PDF input with:

```bash
make demo
```

Regenerate the equivalent cross-format examples with:

```bash
make fixtures
```

## Why keep non-product invoice fields?

Party/header data is useful for tenant/partner organization, traceability and future entity resolution. Discount, tax, shipping and amount due are stored for reconciliation and downstream accounting but are intentionally kept out of product canonicalization logic. Contact/address fields are persisted as invoice evidence and are not sent to the canonicalization LLM.
