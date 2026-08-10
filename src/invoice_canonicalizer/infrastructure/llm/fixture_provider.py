"""Business objective: make both AI canonicalization and AI extraction fallbacks reproducible without network access or API spend.

Technical description: returns manually curated model outputs from versioned JSON fixtures and records prompt calls for deterministic tests.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoice_canonicalizer.domain.errors import ProviderError
from invoice_canonicalizer.domain.models import ExtractionProviderResult, ProviderResult
from invoice_canonicalizer.infrastructure.documents.common import parse_decimal
from invoice_canonicalizer.utils.money import ZERO
from invoice_canonicalizer.utils.text import normalize_text

_SOURCE_PATTERN = re.compile(r"<source_description>(.*?)</source_description>", re.DOTALL)
_INVOICE_PATTERN = re.compile(r"<invoice_text>(.*?)</invoice_text>", re.DOTALL)


class FixtureModelProvider:
    def __init__(
        self,
        fixture_path: Path,
        model: str = "fixture-canonicalizer-v1",
        extraction_fixture_path: Path | None = None,
    ) -> None:
        self.fixture_path = fixture_path
        self._model = model
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        self._responses = {normalize_text(key): value for key, value in payload["responses"].items()}
        self._default = payload.get("default")
        extraction_payload: dict[str, Any] = {"responses": []}
        if extraction_fixture_path is not None and extraction_fixture_path.exists():
            extraction_payload = json.loads(extraction_fixture_path.read_text(encoding="utf-8"))
        self._extraction_responses = list(extraction_payload.get("responses", []))
        self.call_count = 0
        self.canonicalization_call_count = 0
        self.extraction_call_count = 0
        self.last_system_prompt: str | None = None
        self.last_user_prompt: str | None = None

    @property
    def name(self) -> str:
        return "fixture"

    @property
    def model(self) -> str:
        return self._model

    def estimate_cost(self, system_prompt: str, user_prompt: str, *, output_token_budget: int | None = None) -> Decimal:
        del system_prompt, user_prompt, output_token_budget
        return ZERO

    def generate_candidate(self, system_prompt: str, user_prompt: str) -> ProviderResult:
        self.call_count += 1
        self.canonicalization_call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        match = _SOURCE_PATTERN.search(user_prompt)
        if not match:
            raise ProviderError("fixture provider could not locate source_description tag")
        source = normalize_text(match.group(1))
        response = self._responses.get(source, self._default)
        if response is None:
            raise ProviderError(f"no fixture response for: {source}")
        return ProviderResult(
            proposed_description=response["proposed_description"],
            category=response["category"],
            attributes=dict(response.get("attributes", {})),
            rationale=response.get("rationale", "fixture response"),
            model=self.model,
            provider=self.name,
            input_tokens=max(1, len((system_prompt + user_prompt).split())),
            output_tokens=max(1, len(json.dumps(response).split())),
            estimated_cost_usd=ZERO,
        )

    def extract_invoice(self, system_prompt: str, user_prompt: str) -> ExtractionProviderResult:
        self.call_count += 1
        self.extraction_call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        match = _INVOICE_PATTERN.search(user_prompt)
        if not match:
            raise ProviderError("fixture provider could not locate invoice_text tag")
        invoice_text = match.group(1)
        selected: dict | None = None
        for case in self._extraction_responses:
            if str(case.get("contains", "")) in invoice_text:
                selected = dict(case["result"])
                break
        if selected is None:
            raise ProviderError("no manual extraction fixture matched the invoice text")
        raw_lines = selected.get("lines", [])
        if not isinstance(raw_lines, list) or not raw_lines:
            raise ProviderError("manual extraction fixture has no lines")
        lines = tuple({
            "description": str(item["description"]),
            "quantity": None if item.get("quantity") is None else str(item["quantity"]),
            "unit_price": None if item.get("unit_price") is None else str(item["unit_price"]),
            "total": None if item.get("total") is None else str(item["total"]),
        } for item in raw_lines)
        return ExtractionProviderResult(
            lines=lines,
            declared_subtotal=parse_decimal(selected.get("declared_subtotal")),
            rationale=str(selected.get("rationale", "manual extraction fixture")),
            model=self.model,
            provider=self.name,
            input_tokens=max(1, len((system_prompt + user_prompt).split())),
            output_tokens=max(1, len(json.dumps(selected).split())),
            estimated_cost_usd=ZERO,
        )
