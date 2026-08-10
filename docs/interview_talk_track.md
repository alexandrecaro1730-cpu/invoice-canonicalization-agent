# Interview Talk Track

## Business objective

Present the assessment clearly in roughly 8-10 minutes while keeping deeper engineering evidence available for follow-up questions.

## Technical description

The main presentation uses three visual story slides, followed by the real architecture and measured evidence. Slides after the appendix divider are intended for questions rather than linear presentation.

## Recommended flow

### Slide 1 - thesis

"I treated this as a canonicalization problem rather than a prompt-engineering problem. If the organization already knows what a description means, I should not ask an LLM again."

### Slide 2 - every line is checked first

"Before AI, every invoice line - known or unknown - passes the same extraction and arithmetic quality gate. There is no point doing sophisticated retrieval on corrupted OCR."

### Slide 3 - tamed vs wild

"Known descriptions use an approved deterministic fast path with no LLM call. Unknowns are deliberately routed to an uncertainty path using approved evidence, bounded AI only when needed, and abstention when confidence is insufficient."

### Slide 4 - learning loop

"A human approves knowledge once, not every invoice. Once the mapping is promoted, the same description becomes an exact approved lookup. Model spend follows unique unresolved concepts rather than repeated invoice volume."

### Slide 5 - map metaphor to engineering

"That was the metaphor. This is the actual three-tier system in the code. The delivery primitives around it - REST, MCP, Docker, CI/CD and PostgreSQL - productionize the workflow but are not the business algorithm."

### Slide 6 - challenge evidence

"The six supplied challenge mappings are deliberately pre-seeded, so 6/6 is an integration smoke test, not an ML-accuracy claim. It proves deterministic replay and extraction integrity."

### Slide 7 - measured reliability

"The stronger evidence is the routing behavior: repeated unknowns are deduplicated, unsafe inputs can abstain, no unexpected LLM calls occur in the curated regression set, and the package builds/installs in isolation."

### Slide 8 - conclusion

"The goal is not to make the LLM more consistent. It is to need the LLM less often."

## Appendix routing

Use the appendix only when prompted:

- unseen-product lifecycle -> slide 10;
- human review -> slide 11;
- tenant collision -> slide 12;
- production scope -> slide 13;
- detailed sequence -> slide 14;
- testing -> slide 15;
- security/cost -> slide 16;
- retrieval/RAG -> slide 17;
- review data model -> slide 18;
- limitations/production validation -> slide 19;
- commands/artifacts -> slide 20.
