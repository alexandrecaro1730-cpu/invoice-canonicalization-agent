"""Business objective: prove production API callers cannot choose another tenant and only reviewers can mutate approved knowledge.

Technical description: enables bearer API-key mode with two tenant-bound principals and exercises processor/reviewer role gates plus authenticated MCP tenant binding.
"""

from __future__ import annotations

import json
from dataclasses import replace

from fastapi.testclient import TestClient

from invoice_canonicalizer.api.app import create_app
from invoice_canonicalizer.application.factory import build_container
from invoice_canonicalizer.domain.models import InvoiceLine
from invoice_canonicalizer.mcp.server import MCP_PROTOCOL_VERSION


def _auth_container(settings, monkeypatch):
    monkeypatch.setenv("ICA_API_KEYS_JSON", json.dumps({
        "processor-secret": {
            "subject": "processor-test",
            "tenant_id": "testinger",
            "roles": ["processor"],
        },
        "reviewer-secret": {
            "subject": "reviewer-test",
            "tenant_id": "testinger",
            "roles": ["reviewer"],
        },
    }))
    return build_container(replace(settings, auth_mode="api-key"))


def test_processor_is_tenant_bound_and_cannot_review(settings, monkeypatch) -> None:
    client = TestClient(create_app(container=_auth_container(settings, monkeypatch)))
    headers = {"Authorization": "Bearer processor-secret"}

    response = client.post("/v1/canonicalize", headers=headers, json={
        "partner_id": "default-partner",
        "source_line_id": "auth-1",
        "description": "Socks, black",
    })
    assert response.status_code == 200
    assert response.json()["canonical_description"] == "Crew Socks"

    mismatch = client.post("/v1/canonicalize", headers=headers, json={
        "tenant_id": "other-tenant",
        "partner_id": "default-partner",
        "source_line_id": "auth-2",
        "description": "White Tee",
    })
    assert mismatch.status_code == 403

    review_list = client.get("/v1/reviews", headers=headers)
    assert review_list.status_code == 403


def test_reviewer_can_review_but_cannot_process(settings, monkeypatch) -> None:
    runtime = _auth_container(settings, monkeypatch)
    # Seed a review via the application service, then verify only the reviewer API can see it.
    runtime.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger",
        partner_id="default-partner",
        source_line_id="auth-review-seed",
        description="Black Leather Jacket Midnight",
    ))
    client = TestClient(create_app(container=runtime))
    headers = {"Authorization": "Bearer reviewer-secret"}
    listing = client.get("/v1/reviews", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    process = client.post("/v1/canonicalize", headers=headers, json={
        "partner_id": "default-partner",
        "source_line_id": "auth-reviewer-process",
        "description": "Socks, black",
    })
    assert process.status_code == 403


def test_missing_or_invalid_api_key_is_401(settings, monkeypatch) -> None:
    client = TestClient(create_app(container=_auth_container(settings, monkeypatch)))
    request = {
        "partner_id": "default-partner",
        "source_line_id": "auth-missing",
        "description": "Socks, black",
    }
    assert client.post("/v1/canonicalize", json=request).status_code == 401
    assert client.post(
        "/v1/canonicalize",
        headers={"Authorization": "Bearer wrong"},
        json=request,
    ).status_code == 401


def test_authenticated_mcp_uses_bound_tenant_and_rejects_override(settings, monkeypatch) -> None:
    client = TestClient(create_app(container=_auth_container(settings, monkeypatch)))
    headers = {
        "Authorization": "Bearer processor-secret",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "canonicalize_line",
    }
    meta = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "auth-test", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    payload = {
        "jsonrpc": "2.0",
        "id": "mcp-auth-1",
        "method": "tools/call",
        "params": {
            "_meta": meta,
            "name": "canonicalize_line",
            "arguments": {
                "partner_id": "default-partner",
                "source_line_id": "mcp-auth-line",
                "description": "Socks, black",
            },
        },
    }
    response = client.post("/mcp", headers=headers, json=payload)
    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["canonical_description"] == "Crew Socks"

    payload["params"]["arguments"]["tenant_id"] = "other-tenant"
    rejected = client.post("/mcp", headers=headers, json=payload)
    assert rejected.status_code == 200
    assert "does not match authenticated MCP tenant" in rejected.json()["error"]["message"]
