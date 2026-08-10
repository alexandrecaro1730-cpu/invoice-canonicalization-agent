"""Business objective: process whole invoice documents through one governed canonicalization workflow.

Technical description: selects an allow-listed parser, shares one Decimal model budget across extraction/canonicalization, enforces arithmetic quality gates, and invokes bounded model extraction only after deterministic failure.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Iterable

from invoice_canonicalizer.application.budget import CostBudget
from invoice_canonicalizer.application.ports import Canonicalizer, CatalogRepository, DocumentParser
from invoice_canonicalizer.domain.errors import DocumentExtractionError, UnsupportedDocumentError
from invoice_canonicalizer.domain.models import DocumentProcessingResult, ExtractionQualityStatus, ParsedDocument
from invoice_canonicalizer.infrastructure.documents.model_extractor import ModelDocumentExtractor
from invoice_canonicalizer.security.file_validation import validate_document_path


class IngestionService:
    def __init__(
        self,
        parsers: Iterable[DocumentParser],
        canonicalizer: Canonicalizer,
        max_file_size_bytes: int,
        max_model_calls_per_document: int,
        max_cost_usd_per_document: Decimal,
        model_extractor: ModelDocumentExtractor | None = None,
        repository: CatalogRepository | None = None,
    ) -> None:
        self._parsers = {extension: parser for parser in parsers for extension in parser.extensions}
        self.canonicalizer = canonicalizer
        self.max_file_size_bytes = max_file_size_bytes
        self.max_model_calls_per_document = max_model_calls_per_document
        self.max_cost_usd_per_document = max_cost_usd_per_document
        self.model_extractor = model_extractor
        self.repository = repository

    def process(self, path: Path, tenant_id: str, partner_id: str) -> DocumentProcessingResult:
        validate_document_path(path, self.max_file_size_bytes)
        parser = self._parsers.get(path.suffix.lower())
        if parser is None:
            raise UnsupportedDocumentError(path.suffix.lower())
        budget = CostBudget(
            max_calls=self.max_model_calls_per_document,
            max_cost_usd=self.max_cost_usd_per_document,
        )
        parsed = self._parse_with_fallback(parser, path, tenant_id, partner_id, budget)
        if self.repository is not None:
            self.repository.save_invoice_document(parsed, tenant_id, partner_id)
        decisions = tuple(self.canonicalizer.canonicalize(line, budget) for line in parsed.lines)
        if self.repository is not None:
            for line, decision in zip(parsed.lines, decisions, strict=True):
                self.repository.link_invoice_decision(tenant_id, parsed.document_id, line.source_line_id, decision)
        return DocumentProcessingResult(
            document_id=parsed.document_id,
            source_name=parsed.source_name,
            parser_name=parsed.parser_name,
            decisions=decisions,
            context=parsed.context,
            warnings=parsed.warnings,
            quality=parsed.quality,
            financial_quality=parsed.financial_quality,
        )

    def _parse_with_fallback(
        self,
        parser: DocumentParser,
        path: Path,
        tenant_id: str,
        partner_id: str,
        budget: CostBudget,
    ) -> ParsedDocument:
        original_error: Exception | None = None
        try:
            parsed = parser.parse(path, tenant_id, partner_id)
            if parsed.quality is None or parsed.quality.status is not ExtractionQualityStatus.FAIL:
                return parsed
            original_error = DocumentExtractionError(
                "deterministic extraction failed arithmetic quality gate: " + ", ".join(parsed.quality.checks)
            )
        except DocumentExtractionError as exc:
            original_error = exc

        if self.model_extractor is None:
            assert original_error is not None
            raise original_error
        return self.model_extractor.extract(
            path,
            tenant_id,
            partner_id,
            budget,
            original_error=original_error,
        )
