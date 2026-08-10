"""Business objective: verify external clients receive stable health, line, document, review, and metric contracts.

Technical description: uses FastAPI TestClient against an isolated dependency-injected container.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from invoice_canonicalizer.api.app import create_app
from invoice_canonicalizer.mcp.server import MCP_PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_health_and_line_canonicalization(container) -> None:
    client = TestClient(create_app(container=container))
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/v1/canonicalize", json={
        "tenant_id": "testinger", "partner_id": "default-partner",
        "source_line_id": "api-1", "description": "Socks, black",
    })
    assert response.status_code == 200
    assert response.json()["canonical_description"] == "Crew Socks"
    assert not response.json()["requires_human_review"]


def test_document_upload_and_metrics(container) -> None:
    client = TestClient(create_app(container=container))
    path = ROOT / "data/examples/input/equivalent_invoice.json"
    with path.open("rb") as handle:
        response = client.post(
            "/v1/documents",
            data={"tenant_id": "testinger", "partner_id": "default-partner"},
            files={"document": (path.name, handle, "application/json")},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["decisions"]) == 6
    assert payload["invoice"]["invoice_number"] == "19283746552"
    assert payload["invoice"]["financials"]["discount_total"] == "13.00"
    assert payload["invoice"]["financials"]["tax_total"] == "53.40"
    assert payload["invoice"]["financials"]["shipping_total"] == "12.00"
    assert payload["invoice"]["financials"]["amount_due"] == "332.40"
    parties = {item["role"]: item for item in payload["invoice"]["parties"]}
    assert parties["seller"]["name"] == "Testinger GmbH"
    assert parties["bill_to"]["name"] == "Recipient Corp."
    assert parties["ship_to"]["address_lines"][-1] == "0815 Austria"
    assert payload["financial_reconciliation"]["status"] == "PASS"

    persisted = client.get(f"/v1/documents/{payload['document_id']}", params={"tenant_id": "testinger"})
    assert persisted.status_code == 200
    persisted_payload = persisted.json()
    assert persisted_payload["invoice"] == payload["invoice"]
    assert len(persisted_payload["lines"]) == 6
    assert persisted_payload["lines"][0]["canonical_description"] == "Highlife Components"
    assert persisted_payload["lines"][0]["decision_kind"] == "exact_alias"
    assert persisted_payload["lines"][-1]["canonical_description"] == "Crew Socks"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "invoice_canonicalizer_exact_alias_total" in metrics.text


def test_review_approval_endpoint_teaches_alias(container) -> None:
    client = TestClient(create_app(container=container))
    first = client.post("/v1/canonicalize", json={
        "tenant_id": "testinger", "partner_id": "default-partner",
        "source_line_id": "api-new-1", "description": "Black Leather Jacket Midnight",
    })
    review_id = first.json()["review_id"]
    approval = client.post(f"/v1/reviews/{review_id}/approve", json={
        "tenant_id": "testinger", "approved_description": "Black Leather Jacket",
    })
    assert approval.status_code == 200
    second = client.post("/v1/canonicalize", json={
        "tenant_id": "testinger", "partner_id": "default-partner",
        "source_line_id": "api-new-2", "description": "Black Leather Jacket Midnight",
    })
    assert second.json()["decision_kind"] == "exact_alias"


def test_stateless_mcp_http_endpoint_validates_headers_and_metadata(container) -> None:
    client = TestClient(create_app(container=container))
    payload = {
        "jsonrpc": "2.0",
        "id": "discover-1",
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientInfo": {"name": "api-test", "version": "1.0.0"},
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }
    response = client.post(
        "/mcp",
        json=payload,
        headers={
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Mcp-Method": "server/discover",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["supportedVersions"] == [MCP_PROTOCOL_VERSION]
    bad = client.post("/mcp", json=payload, headers={"Mcp-Method": "server/discover"})
    assert bad.status_code == 400


def test_review_list_and_generic_action_endpoint(container) -> None:
    client = TestClient(create_app(container=container))
    first = client.post("/v1/canonicalize", json={
        "tenant_id": "testinger", "partner_id": "default-partner",
        "source_line_id": "api-review-list-1", "description": "Black crew athletic sock",
    })
    assert first.status_code == 200
    review_id = first.json()["review_id"]
    summary = client.get("/v1/reviews/summary", params={"tenant_id": "testinger"})
    assert summary.status_code == 200
    assert summary.json()["pending_unique_candidates"] == 1
    assert summary.json()["affected_invoice_lines"] == 1

    listing = client.get("/v1/reviews", params={"tenant_id": "testinger"})
    assert listing.status_code == 200
    item = next(item for item in listing.json()["items"] if item["review_id"] == review_id)
    assert item["llm_used"] is True
    assert item["target_product_id"] == "product-crew-socks"
    assert item["occurrence_count"] == 1

    action = client.post(f"/v1/reviews/{review_id}/action", json={
        "tenant_id": "testinger",
        "action": "approve_existing",
        "target_product_id": "product-crew-socks",
        "reviewer_notes": "Approved in API integration test",
    })
    assert action.status_code == 200
    assert action.json()["product_id"] == "product-crew-socks"
