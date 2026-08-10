# Technical References

## Business objective

Record the primary specifications used for protocol and deployment decisions so reviewers can verify design intent.

## Technical description

- Model Context Protocol 2026-07-28 release: `https://blog.modelcontextprotocol.io/posts/2026-07-28/`
- MCP server discovery: `https://modelcontextprotocol.io/specification/draft/server/discover`
- MCP tools: `https://modelcontextprotocol.io/specification/draft/server/tools`
- JSON Schema 2020-12: `https://json-schema.org/draft/2020-12/schema`

The project does not fetch these references at runtime. They are review-time sources for the stateless `_meta`, `server/discover`, deterministic `tools/list`, cache metadata, `resultType`, and tool-result contracts.
