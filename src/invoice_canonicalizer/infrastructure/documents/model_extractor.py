"""Business objective: recover invoice lines when native parsing/OCR cannot pass deterministic quality gates without making the model authoritative.

Technical description: builds a PII-minimized extraction prompt, enforces the shared model budget, validates the strict JSON contract, and rejects model output that fails Decimal arithmetic checks.
"""

from __future__ import annotations

from pathlib import Path

from invoice_canonicalizer.application.budget import CostBudget
from invoice_canonicalizer.application.ports import ModelProvider
from invoice_canonicalizer.domain.errors import BudgetExceededError, DocumentExtractionError, ProviderError
from invoice_canonicalizer.domain.models import ExtractionQualityStatus, InvoiceLine, ParsedDocument
from invoice_canonicalizer.infrastructure.documents.common import parse_decimal
from invoice_canonicalizer.infrastructure.documents.extraction_quality import validate_extraction_quality, validate_financial_quality
from invoice_canonicalizer.infrastructure.documents.invoice_context import context_from_text
from invoice_canonicalizer.infrastructure.documents.raw_text import extract_raw_text, minimize_invoice_text
from invoice_canonicalizer.infrastructure.llm.prompt_registry import PromptRegistry
from invoice_canonicalizer.utils.hashing import sha256_file


class ModelDocumentExtractor:
    def __init__(
        self,
        provider: ModelProvider,
        prompts: PromptRegistry,
        *,
        enable_ocr: bool,
        max_prompt_chars: int,
    ) -> None:
        self.provider = provider
        self.prompts = prompts
        self.enable_ocr = enable_ocr
        self.max_prompt_chars = max(1_000, int(max_prompt_chars))

    def extract(
        self,
        path: Path,
        tenant_id: str,
        partner_id: str,
        budget: CostBudget,
        original_error: Exception | None = None,
    ) -> ParsedDocument:
        system = self.prompts.load("extract/system.txt")
        user = self.prompts.load("extract/user.txt")
        try:
            raw_text = extract_raw_text(path, enable_ocr=self.enable_ocr)
            context = context_from_text(raw_text)
            minimized = minimize_invoice_text(raw_text, self.max_prompt_chars)
            if len(minimized.strip()) < 10:
                raise DocumentExtractionError("insufficient local text for model extraction fallback")
            user_prompt = user.render(invoice_text=minimized)
            estimated = self.provider.estimate_cost(system.body, user_prompt)
            budget.reserve_call(estimated)
            result = self.provider.extract_invoice(system.body, user_prompt)
            budget.register_actual_cost(result.estimated_cost_usd)
        except (BudgetExceededError, ProviderError, OSError, ValueError) as exc:
            error_suffix = f"; deterministic extraction error: {original_error}" if original_error else ""
            raise DocumentExtractionError(f"model extraction fallback failed: {exc}{error_suffix}") from exc

        lines: list[InvoiceLine] = []
        for index, item in enumerate(result.lines, start=1):
            try:
                lines.append(InvoiceLine(
                    tenant_id=tenant_id,
                    partner_id=partner_id,
                    description=str(item["description"]),
                    source_line_id=f"model-extract-{index}",
                    quantity=parse_decimal(item.get("quantity")),
                    unit_price=parse_decimal(item.get("unit_price")),
                    total=parse_decimal(item.get("total")),
                    currency=context.financials.currency,
                ))
            except (KeyError, ValueError, TypeError) as exc:
                raise DocumentExtractionError(f"model extraction line {index} failed validation: {exc}") from exc
        declared_subtotal = context.financials.subtotal or result.declared_subtotal
        quality = validate_extraction_quality(lines, declared_subtotal)
        if quality.status is ExtractionQualityStatus.FAIL:
            raise DocumentExtractionError(
                "model extraction output failed arithmetic quality gate: " + ", ".join(quality.checks)
            )
        warning = "model_extraction_fallback_used"
        if original_error:
            warning += f":{type(original_error).__name__}"
        return ParsedDocument(
            document_id=sha256_file(path),
            source_name=path.name,
            parser_name="model-structured-fallback",
            lines=tuple(lines),
            context=context,
            warnings=(warning,),
            quality=quality,
            financial_quality=validate_financial_quality(context.financials),
        )
