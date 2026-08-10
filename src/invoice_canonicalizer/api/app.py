"""Business objective: expose tenant-bound canonicalization, document, review, MCP, and metrics endpoints safely.

Technical description: builds a dependency-injected FastAPI app where bearer authentication binds tenant scope, processor/reviewer roles gate operations, and local auth-disabled mode remains explicit for the assessment.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

from invoice_canonicalizer import __version__
from invoice_canonicalizer.api.schemas import (
    CanonicalizeRequest,
    DecisionResponse,
    ReviewActionRequest,
    ReviewApprovalRequest,
    ReviewRejectionRequest,
)
from invoice_canonicalizer.application.factory import ApplicationContainer, build_container
from invoice_canonicalizer.config import AppSettings, load_settings
from invoice_canonicalizer.domain.errors import (
    AuthenticationError,
    AuthorizationError,
    CanonicalizationError,
)
from invoice_canonicalizer.domain.models import CanonicalizationDecision, InvoiceLine, ReviewAction, ReviewRecord
from invoice_canonicalizer.mcp.server import MCP_PROTOCOL_VERSION, McpServer
from invoice_canonicalizer.security.auth import Principal, Role, require_role, resolve_tenant


def _decision_response(decision: CanonicalizationDecision) -> DecisionResponse:
    return DecisionResponse(
        decision_id=decision.decision_id,
        decision_kind=decision.decision_kind.value,
        canonical_product_id=decision.canonical_product_id,
        canonical_description=decision.canonical_description,
        category=decision.category,
        confidence=decision.confidence,
        requires_human_review=decision.requires_human_review,
        review_id=decision.review_id,
        evidence=list(decision.evidence),
        flags=list(decision.flags),
        taxonomy_version=decision.taxonomy_version,
        prompt_version=decision.prompt_version,
        model=decision.model,
        provider=decision.provider,
        estimated_cost_usd=decision.estimated_cost_usd,
        from_cache=decision.from_cache,
    )


def _review_payload(review: ReviewRecord) -> dict[str, object]:
    return {
        "review_id": review.review_id,
        "tenant_id": review.tenant_id,
        "partner_id": review.partner_id,
        "candidate_key": review.candidate_key,
        "source_description": review.source_description,
        "source_variants": list(review.source_variants),
        "source_line_ids": list(review.source_line_ids),
        "occurrence_count": review.occurrence_count,
        "affected_value": format(review.affected_value, "f"),
        "affected_values_by_currency": {
            key: format(value, "f") for key, value in review.affected_values_by_currency.items()
        },
        "currency": review.currency,
        "first_seen_at": review.first_seen_at,
        "last_seen_at": review.last_seen_at,
        "proposed_description": review.proposed_description,
        "proposed_category": review.proposed_category,
        "attributes": review.attributes,
        "evidence": list(review.evidence),
        "decision_score": review.decision_score,
        "retrieval_score": review.retrieval_score,
        "retrieval_margin": review.retrieval_margin,
        "priority_score": review.priority_score,
        "llm_used": review.llm_used,
        "blocks_transaction": review.blocks_transaction,
        "risk_flags": list(review.risk_flags),
        "prompt_version": review.prompt_version,
        "model": review.model,
        "provider": review.provider,
        "target_product_id": review.target_product_id,
        "status": review.status.value,
    }


def create_app(settings: AppSettings | None = None, container: ApplicationContainer | None = None) -> FastAPI:
    runtime = container or build_container(settings or load_settings())
    app = FastAPI(title="Invoice Canonicalization Agent", version=__version__)
    app.state.container = runtime

    def authenticate(authorization: str | None = Header(default=None)) -> Principal:
        try:
            return runtime.authenticator.authenticate(authorization)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc

    def processor(principal: Principal = Depends(authenticate)) -> Principal:
        try:
            require_role(principal, Role.PROCESSOR)
            return principal
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def reviewer(principal: Principal = Depends(authenticate)) -> Principal:
        try:
            require_role(principal, Role.REVIEWER)
            return principal
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def tenant(principal: Principal, supplied: str | None) -> str:
        try:
            return resolve_tenant(principal, supplied)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        runtime.repository.initialize()
        return {"status": "ready", "taxonomy_version": runtime.settings.taxonomy_version}

    @app.post("/v1/canonicalize", response_model=DecisionResponse)
    def canonicalize(
        request: CanonicalizeRequest,
        principal: Principal = Depends(processor),
    ) -> DecisionResponse:
        try:
            tenant_id = tenant(principal, request.tenant_id)
            payload = request.model_dump(exclude={"tenant_id"})
            line = InvoiceLine(tenant_id=tenant_id, **payload)
            return _decision_response(runtime.canonicalizer.canonicalize(line))
        except (CanonicalizationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/documents")
    async def process_document(
        principal: Principal = Depends(processor),
        partner_id: str = Form(...),
        document: UploadFile = File(...),
        tenant_id: str | None = Form(None),
    ) -> dict[str, object]:
        suffix = Path(document.filename or "upload.bin").suffix
        scoped_tenant = tenant(principal, tenant_id)
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                temporary_path = Path(handle.name)
                shutil.copyfileobj(document.file, handle)
            result = runtime.ingestion.process(temporary_path, scoped_tenant, partner_id)
            return {
                "document_id": result.document_id,
                "source_name": result.source_name,
                "parser_name": result.parser_name,
                "warnings": list(result.warnings),
                "invoice": result.context.to_dict(),
                "extraction_quality": result.quality.to_dict() if result.quality else None,
                "financial_reconciliation": result.financial_quality.to_dict() if result.financial_quality else None,
                "decisions": [_decision_response(item).model_dump(mode="json") for item in result.decisions],
            }
        except (CanonicalizationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if "temporary_path" in locals():
                temporary_path.unlink(missing_ok=True)

    @app.get("/v1/documents/{document_id}")
    def get_document(
        document_id: str,
        principal: Principal = Depends(processor),
        tenant_id: str | None = None,
    ) -> dict[str, object]:
        scoped_tenant = tenant(principal, tenant_id)
        parsed = runtime.repository.get_invoice_document(scoped_tenant, document_id)
        if parsed is None:
            raise HTTPException(status_code=404, detail="document not found")
        return {
            "document_id": parsed.document_id,
            "source_name": parsed.source_name,
            "parser_name": parsed.parser_name,
            "invoice": parsed.context.to_dict(),
            "lines": [line.to_dict() for line in runtime.repository.get_invoice_line_records(scoped_tenant, document_id)],
            "extraction_quality": parsed.quality.to_dict() if parsed.quality else None,
            "financial_reconciliation": parsed.financial_quality.to_dict() if parsed.financial_quality else None,
        }

    @app.post("/v1/reviews/{review_id}/approve")
    def approve_review(
        review_id: str,
        request: ReviewApprovalRequest,
        principal: Principal = Depends(reviewer),
    ) -> dict[str, object]:
        scoped_tenant = tenant(principal, request.tenant_id)
        try:
            product = runtime.reviews.approve(
                tenant_id=scoped_tenant,
                review_id=review_id,
                approved_description=request.approved_description,
                target_product_id=request.target_product_id,
                approved_category=request.approved_category,
            )
            return {
                "status": "approved",
                "product": {
                    "product_id": product.product_id,
                    "canonical_description": product.canonical_description,
                    "category": product.category,
                },
            }
        except CanonicalizationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/reviews/{review_id}/reject")
    def reject_review(
        review_id: str,
        request: ReviewRejectionRequest,
        principal: Principal = Depends(reviewer),
    ) -> dict[str, object]:
        scoped_tenant = tenant(principal, request.tenant_id)
        try:
            review = runtime.reviews.reject(scoped_tenant, review_id, request.reviewer_notes)
            return {"status": review.status.value, "review_id": review.review_id}
        except CanonicalizationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/reviews/summary")
    def review_summary(
        principal: Principal = Depends(reviewer),
        tenant_id: str | None = None,
    ) -> dict[str, object]:
        return runtime.reviews.summary(tenant(principal, tenant_id))

    @app.get("/v1/reviews")
    def list_reviews(
        principal: Principal = Depends(reviewer),
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        scoped_tenant = tenant(principal, tenant_id)
        pending = runtime.reviews.list_pending(scoped_tenant, limit=limit)
        return {
            "tenant_id": scoped_tenant,
            "count": len(pending),
            "items": [_review_payload(item) for item in pending],
        }

    @app.post("/v1/reviews/{review_id}/action")
    def apply_review_action(
        review_id: str,
        request: ReviewActionRequest,
        principal: Principal = Depends(reviewer),
    ) -> dict[str, object]:
        scoped_tenant = tenant(principal, request.tenant_id)
        try:
            return runtime.reviews.apply_action(
                tenant_id=scoped_tenant,
                review_id=review_id,
                action=ReviewAction(request.action),
                approved_description=request.approved_description,
                target_product_id=request.target_product_id,
                approved_category=request.approved_category,
                reviewer_notes=request.reviewer_notes,
            )
        except CanonicalizationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/mcp")
    async def mcp_endpoint(
        request: Request,
        principal: Principal = Depends(processor),
        mcp_protocol_version: str | None = Header(default=None, alias="MCP-Protocol-Version"),
        mcp_method: str | None = Header(default=None, alias="Mcp-Method"),
        mcp_name: str | None = Header(default=None, alias="Mcp-Name"),
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except ValueError as exc:
            return JSONResponse(status_code=400, content=McpServer._error(None, -32700, f"parse error: {exc}"))
        body_method = payload.get("method") if isinstance(payload, dict) else None
        body_name = payload.get("params", {}).get("name") if isinstance(payload, dict) and isinstance(payload.get("params"), dict) else None
        if mcp_protocol_version != MCP_PROTOCOL_VERSION:
            return JSONResponse(
                status_code=400,
                content=McpServer._error(payload.get("id") if isinstance(payload, dict) else None, -32602, "unsupported or missing MCP-Protocol-Version header"),
            )
        if mcp_method != body_method:
            return JSONResponse(
                status_code=400,
                content=McpServer._error(payload.get("id") if isinstance(payload, dict) else None, -32602, "Mcp-Method header does not match JSON-RPC method"),
            )
        if body_method == "tools/call" and mcp_name != body_name:
            return JSONResponse(
                status_code=400,
                content=McpServer._error(payload.get("id") if isinstance(payload, dict) else None, -32602, "Mcp-Name header does not match tool name"),
            )
        response = McpServer(runtime, bound_tenant_id=principal.tenant_id).handle(payload)
        return JSONResponse(status_code=200, content=response or {})

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return runtime.metrics.render_prometheus()

    return app


app = create_app()
