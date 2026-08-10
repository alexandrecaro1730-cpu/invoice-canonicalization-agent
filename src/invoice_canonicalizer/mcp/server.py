"""Business objective: expose safe canonicalization capabilities to current MCP-compatible AI hosts without allowing model-controlled tenant switching or approval mutation.

Technical description: implements the stateless MCP 2026-07-28 JSON-RPC core; HTTP deployments can bind the server to an authenticated tenant while stdio mode keeps explicit tenant arguments.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from invoice_canonicalizer import __version__
from invoice_canonicalizer.application.factory import ApplicationContainer
from invoice_canonicalizer.domain.models import InvoiceLine

MCP_PROTOCOL_VERSION = "2026-07-28"
_REQUIRED_META_KEYS = (
    "io.modelcontextprotocol/protocolVersion",
    "io.modelcontextprotocol/clientInfo",
    "io.modelcontextprotocol/clientCapabilities",
)


@dataclass(slots=True)
class McpServer:
    container: ApplicationContainer
    bound_tenant_id: str | None = None

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return self._error(request_id, -32600, "invalid JSON-RPC request")
        method = request["method"]
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self._error(request_id, -32602, "params must be an object")
        meta_error = self._validate_meta(params.get("_meta"))
        if meta_error:
            return self._error(request_id, -32602, meta_error)

        if method == "server/discover":
            return self._result(request_id, {
                "resultType": "complete",
                "supportedVersions": [MCP_PROTOCOL_VERSION],
                "capabilities": {"tools": {}},
                "_meta": {
                    "io.modelcontextprotocol/serverInfo": {
                        "name": "invoice-canonicalizer",
                        "version": __version__,
                    }
                },
                "instructions": (
                    "Use canonicalize_line to resolve approved invoice descriptions or create a human-review proposal. "
                    "This server never exposes an approval mutation as a model-controlled tool."
                ),
                "ttlMs": 3_600_000,
                "cacheScope": "private" if self.bound_tenant_id else "public",
            })
        if method == "ping":
            return self._result(request_id, {"resultType": "complete"})
        if method == "tools/list":
            return self._result(request_id, {
                "resultType": "complete",
                "tools": self._tools(),
                "ttlMs": 300_000,
                "cacheScope": "private" if self.bound_tenant_id else "public",
            })
        if method == "tools/call":
            return self._call_tool(request_id, params)
        return self._error(request_id, -32601, f"method not found: {method}")

    @staticmethod
    def _validate_meta(meta: Any) -> str | None:
        if not isinstance(meta, dict):
            return "params._meta is required"
        missing = [key for key in _REQUIRED_META_KEYS if key not in meta]
        if missing:
            return f"missing MCP metadata: {missing}"
        if meta["io.modelcontextprotocol/protocolVersion"] != MCP_PROTOCOL_VERSION:
            return f"unsupported protocol version: {meta['io.modelcontextprotocol/protocolVersion']}"
        client_info = meta["io.modelcontextprotocol/clientInfo"]
        if not isinstance(client_info, dict) or not client_info.get("name") or not client_info.get("version"):
            return "clientInfo must include name and version"
        if not isinstance(meta["io.modelcontextprotocol/clientCapabilities"], dict):
            return "clientCapabilities must be an object"
        return None

    def _tenant(self, arguments: dict[str, Any]) -> str:
        supplied = str(arguments.get("tenant_id", "")).strip()
        if self.bound_tenant_id:
            if supplied and supplied != self.bound_tenant_id:
                raise ValueError("tenant_id does not match authenticated MCP tenant")
            return self.bound_tenant_id
        if not supplied:
            raise ValueError("tenant_id is required in unbound stdio mode")
        return supplied

    def _call_tool(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return self._error(request_id, -32602, "arguments must be an object")
        try:
            tenant_id = self._tenant(arguments)
        except ValueError as exc:
            return self._error(request_id, -32602, str(exc))

        if name == "canonicalize_line":
            required = ("partner_id", "description", "source_line_id")
            missing = [key for key in required if not arguments.get(key)]
            if missing:
                return self._error(request_id, -32602, f"missing arguments: {missing}")
            decision = self.container.canonicalizer.canonicalize(InvoiceLine(
                tenant_id=tenant_id,
                partner_id=str(arguments["partner_id"]),
                description=str(arguments["description"]),
                source_line_id=str(arguments["source_line_id"]),
            ))
            payload = decision.to_dict()
            return self._result(request_id, {
                "resultType": "complete",
                "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                "structuredContent": payload,
                "isError": False,
            })
        if name == "lookup_product":
            product_id = str(arguments.get("product_id", ""))
            if not product_id:
                return self._error(request_id, -32602, "product_id is required")
            product = self.container.repository.get_product(tenant_id, product_id)
            if product is None:
                return self._tool_error(request_id, "Product was not found in the authorized tenant scope.")
            payload = {
                "product_id": product.product_id,
                "canonical_description": product.canonical_description,
                "category": product.category,
                "attributes": product.attributes,
            }
            return self._result(request_id, {
                "resultType": "complete",
                "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                "structuredContent": payload,
                "isError": False,
            })
        if name == "get_review_status":
            review_id = str(arguments.get("review_id", ""))
            if not review_id:
                return self._error(request_id, -32602, "review_id is required")
            review = self.container.repository.get_review(tenant_id, review_id)
            if review is None:
                return self._tool_error(request_id, "Review was not found in the authorized tenant scope.")
            payload = {"review_id": review.review_id, "status": review.status.value}
            return self._result(request_id, {
                "resultType": "complete",
                "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
                "structuredContent": payload,
                "isError": False,
            })
        return self._error(request_id, -32602, f"unknown tool: {name}")

    def _tools(self) -> list[dict[str, Any]]:
        tenant_property = {"tenant_id": {"type": "string", "minLength": 1}}
        tenant_required = [] if self.bound_tenant_id else ["tenant_id"]
        return [
            {
                "name": "canonicalize_line",
                "title": "Canonicalize Invoice Line",
                "description": "Resolve an invoice line to approved product knowledge or create a human-review proposal.",
                "inputSchema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "additionalProperties": False,
                    "required": tenant_required + ["partner_id", "description", "source_line_id"],
                    "properties": {
                        **tenant_property,
                        "partner_id": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "source_line_id": {"type": "string", "minLength": 1},
                    },
                },
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
            },
            {
                "name": "get_review_status",
                "title": "Get Review Status",
                "description": "Read the status of a human review without mutating it.",
                "inputSchema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object", "additionalProperties": False,
                    "required": tenant_required + ["review_id"],
                    "properties": {**tenant_property, "review_id": {"type": "string"}},
                },
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
            },
            {
                "name": "lookup_product",
                "title": "Look Up Canonical Product",
                "description": "Read one canonical product within an authorized tenant boundary.",
                "inputSchema": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object", "additionalProperties": False,
                    "required": tenant_required + ["product_id"],
                    "properties": {**tenant_property, "product_id": {"type": "string"}},
                },
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
            },
        ]

    @classmethod
    def _tool_error(cls, request_id: Any, message: str) -> dict[str, Any]:
        return cls._result(request_id, {
            "resultType": "complete",
            "content": [{"type": "text", "text": message}],
            "isError": True,
        })

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def run_stdio(server: McpServer, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> None:
    """Serve modern stateless MCP requests over newline-delimited stdio."""
    for raw_line in input_stream:
        if not raw_line.strip():
            continue
        try:
            request = json.loads(raw_line)
            response = server.handle(request)
        except json.JSONDecodeError as exc:
            response = McpServer._error(None, -32700, f"parse error: {exc}")
        except Exception as exc:  # JSON-RPC boundary must not crash its host process.
            request_id = request.get("id") if "request" in locals() and isinstance(request, dict) else None
            response = McpServer._error(request_id, -32603, f"internal error: {type(exc).__name__}")
        if response is not None:
            output_stream.write(json.dumps(response, sort_keys=True) + "\n")
            output_stream.flush()
