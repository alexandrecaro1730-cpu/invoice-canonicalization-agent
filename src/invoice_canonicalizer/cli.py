"""Business objective: provide one-command assessment, demo, API, MCP, and weekly review-queue operations.

Technical description: parses CLI arguments and delegates to dependency-injected application services without duplicating business logic.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import uvicorn

from invoice_canonicalizer.application.factory import build_container
from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.domain.models import InvoiceLine
from invoice_canonicalizer.mcp.server import McpServer, run_stdio
from invoice_canonicalizer.observability.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="invoice-canonicalizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    line = subparsers.add_parser("line", help="canonicalize one description")
    line.add_argument("description")
    line.add_argument("--tenant", default="testinger")
    line.add_argument("--partner", default="default-partner")
    line.add_argument("--source-line-id", default="cli-1")

    document = subparsers.add_parser("document", help="process an invoice document")
    document.add_argument("path", type=Path)
    document.add_argument("--tenant", default="testinger")
    document.add_argument("--partner", default="default-partner")

    document_show = subparsers.add_parser("document-show", help="read a persisted invoice with parties and financial metadata")
    document_show.add_argument("document_id")
    document_show.add_argument("--tenant", default="testinger")

    review_export = subparsers.add_parser("review-export", help="export pending review candidates to an editable CSV")
    review_export.add_argument("--tenant", default="testinger")
    review_export.add_argument("--path", type=Path, default=Path(".runtime/review_queue.csv"))

    review_process = subparsers.add_parser("review-process", help="apply human-edited CSV actions and clear resolved rows")
    review_process.add_argument("--path", type=Path, default=Path(".runtime/review_queue.csv"))
    review_process.add_argument("--archive", type=Path, default=Path(".runtime/review_archive.jsonl"))

    review_list = subparsers.add_parser("review-list", help="show pending clustered review candidates as JSON")
    review_list.add_argument("--tenant", default="testinger")
    review_list.add_argument("--limit", type=int, default=100)

    serve = subparsers.add_parser("serve", help="run the FastAPI service")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    subparsers.add_parser("mcp", help="run the MCP JSON-RPC stdio adapter")
    subparsers.add_parser("assess", help="run the offline production quality gate")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    configure_logging(settings.log_level)
    if args.command == "assess":
        return subprocess.call([sys.executable, str(settings.project_root / "scripts" / "quality_gate.py")], cwd=settings.project_root)
    if args.command == "serve":
        uvicorn.run("invoice_canonicalizer.api.app:app", host=args.host, port=args.port, reload=False)
        return 0

    container = build_container(settings)
    if args.command == "mcp":
        run_stdio(McpServer(container))
        return 0
    if args.command == "line":
        decision = container.canonicalizer.canonicalize(InvoiceLine(
            tenant_id=args.tenant, partner_id=args.partner,
            description=args.description, source_line_id=args.source_line_id,
        ))
        print(json.dumps(decision.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "document":
        document_result = container.ingestion.process(args.path, args.tenant, args.partner)
        document_payload = {
            "document_id": document_result.document_id,
            "source_name": document_result.source_name,
            "parser_name": document_result.parser_name,
            "warnings": list(document_result.warnings),
            "invoice": document_result.context.to_dict(),
            "extraction_quality": document_result.quality.to_dict() if document_result.quality else None,
            "financial_reconciliation": document_result.financial_quality.to_dict() if document_result.financial_quality else None,
            "decisions": [decision.to_dict() for decision in document_result.decisions],
        }
        print(json.dumps(document_payload, indent=2, sort_keys=True))
        return 0
    if args.command == "document-show":
        parsed = container.repository.get_invoice_document(args.tenant, args.document_id)
        if parsed is None:
            print(json.dumps({"error": "document_not_found", "document_id": args.document_id}, indent=2))
            return 1
        stored_document_payload = {
            "document_id": parsed.document_id,
            "source_name": parsed.source_name,
            "parser_name": parsed.parser_name,
            "invoice": parsed.context.to_dict(),
            "lines": [line.to_dict() for line in container.repository.get_invoice_line_records(args.tenant, args.document_id)],
            "extraction_quality": parsed.quality.to_dict() if parsed.quality else None,
            "financial_reconciliation": parsed.financial_quality.to_dict() if parsed.financial_quality else None,
        }
        print(json.dumps(stored_document_payload, indent=2, sort_keys=True))
        return 0
    if args.command == "review-export":
        path = args.path if args.path.is_absolute() else settings.project_root / args.path
        count = container.review_queue.export(args.tenant, path)
        print(json.dumps({"exported": count, "path": str(path)}, indent=2))
        return 0
    if args.command == "review-process":
        path = args.path if args.path.is_absolute() else settings.project_root / args.path
        archive = args.archive if args.archive.is_absolute() else settings.project_root / args.archive
        review_result = container.review_queue.process(path, archive)
        print(json.dumps(review_result, indent=2, sort_keys=True))
        return 1 if review_result["errors"] else 0
    if args.command == "review-list":
        pending = container.reviews.list_pending(args.tenant, limit=args.limit)
        review_payload = [{
            "review_id": item.review_id,
            "source_description": item.source_description,
            "source_variants": list(item.source_variants),
            "occurrence_count": item.occurrence_count,
            "affected_value": format(item.affected_value, "f"),
            "affected_values_by_currency": {key: format(value, "f") for key, value in item.affected_values_by_currency.items()},
            "proposed_description": item.proposed_description,
            "target_product_id": item.target_product_id,
            "decision_score": item.decision_score,
            "priority_score": item.priority_score,
            "llm_used": item.llm_used,
            "blocks_transaction": item.blocks_transaction,
            "risk_flags": list(item.risk_flags),
        } for item in pending]
        print(json.dumps(review_payload, indent=2, sort_keys=True))
        return 0
    return 2
