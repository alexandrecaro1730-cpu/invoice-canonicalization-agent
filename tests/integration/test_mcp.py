"""Business objective: verify current MCP hosts can discover and call safe stateless tools.

Technical description: tests MCP 2026-07-28 metadata, discovery, cached tool lists, invocation, errors, and stdio framing.
"""

from __future__ import annotations

import io
import json

from invoice_canonicalizer.mcp.server import MCP_PROTOCOL_VERSION, McpServer, run_stdio


def _meta() -> dict[str, object]:
    return {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "test-client", "version": "1.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _request(request_id: int, method: str, **params) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {**params, "_meta": _meta()},
    }


def test_mcp_discovery_and_tools_are_stateless_and_cacheable(container) -> None:
    server = McpServer(container)
    discovered = server.handle(_request(1, "server/discover"))
    assert discovered["result"]["supportedVersions"] == [MCP_PROTOCOL_VERSION]
    assert discovered["result"]["capabilities"] == {"tools": {}}
    tools = server.handle(_request(2, "tools/list"))
    assert tools["result"]["resultType"] == "complete"
    assert tools["result"]["ttlMs"] == 300_000
    assert [tool["name"] for tool in tools["result"]["tools"]] == [
        "canonicalize_line", "get_review_status", "lookup_product",
    ]


def test_mcp_requires_per_request_metadata(container) -> None:
    response = McpServer(container).handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert response["error"]["code"] == -32602
    assert "_meta" in response["error"]["message"]


def test_mcp_canonicalize_tool_returns_structured_content(container) -> None:
    server = McpServer(container)
    response = server.handle(_request(
        3,
        "tools/call",
        name="canonicalize_line",
        arguments={
            "tenant_id": "testinger",
            "partner_id": "default-partner",
            "description": "Socks, black",
            "source_line_id": "mcp-1",
        },
    ))
    payload = response["result"]["structuredContent"]
    assert response["result"]["resultType"] == "complete"
    assert payload["canonical_description"] == "Crew Socks"
    assert not response["result"]["isError"]


def test_mcp_business_not_found_is_tool_error(container) -> None:
    response = McpServer(container).handle(_request(
        4,
        "tools/call",
        name="lookup_product",
        arguments={"tenant_id": "testinger", "product_id": "missing"},
    ))
    assert response["result"]["isError"]
    assert response["result"]["resultType"] == "complete"


def test_mcp_stdio_returns_parse_errors(container) -> None:
    input_stream = io.StringIO("not json\n" + json.dumps(_request(5, "ping")) + "\n")
    output_stream = io.StringIO()
    run_stdio(McpServer(container), input_stream, output_stream)
    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["result"]["resultType"] == "complete"
