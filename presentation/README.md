# Assessor Presentation

## Business objective

Explain the invoice-canonicalization solution quickly, memorably, and without letting production plumbing overwhelm the core business idea.

## Presentation structure

The main story is intentionally short:

1. thesis / problem framing;
2. every invoice line passes the same quality boundary;
3. known products use the deterministic fast lane, unknowns enter uncertainty handling;
4. human approval turns a "wild" concept into reusable trusted knowledge;
5. metaphor mapped to the actual three-tier architecture;
6. supplied challenge as deterministic integration smoke test;
7. measured regression evidence;
8. conclusion.

Slides 9-20 are appendix material for technical follow-up questions.

## Files

- `Invoice_Canonicalization_Agent_Assessment.pptx` - editable final presentation;
- `Invoice_Canonicalization_Agent_Assessment.pdf` - portable rendered version;
- `story_assets/` - source images used in the visual opening.

## Core claim language

The deck deliberately says **"no LLM call"** or **"zero model cost"**, not "$0 processing." A deterministic lookup still has infrastructure cost; the economically relevant claim is that approved recurring descriptions avoid model inference and human review.

## Suggested close

> The goal is not to make the LLM more consistent. It is to need the LLM less often.
