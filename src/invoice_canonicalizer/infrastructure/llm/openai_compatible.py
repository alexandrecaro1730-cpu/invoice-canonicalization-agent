"""Business objective: allow controlled production model integration with enforceable cost and resilience limits.

Technical description: calls an OpenAI-compatible chat-completions endpoint with JSON output, Decimal usage pricing, bounded output tokens, timeout, and retry/backoff for transient failures.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any

from invoice_canonicalizer.domain.errors import ProviderError
from invoice_canonicalizer.domain.models import ExtractionProviderResult, ProviderResult
from invoice_canonicalizer.infrastructure.documents.common import parse_decimal
from invoice_canonicalizer.utils.money import ZERO, to_decimal


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str,
        timeout_seconds: float = 30.0,
        input_cost_per_million: Decimal | float | str = ZERO,
        output_cost_per_million: Decimal | float | str = ZERO,
        max_output_tokens: int = 350,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds
        self.input_cost_per_million = to_decimal(input_cost_per_million, default=ZERO) or ZERO
        self.output_cost_per_million = to_decimal(output_cost_per_million, default=ZERO) or ZERO
        self.max_output_tokens = max(1, int(max_output_tokens))
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    @property
    def name(self) -> str:
        return "openai-compatible"

    @property
    def model(self) -> str:
        return self._model

    def estimate_cost(self, system_prompt: str, user_prompt: str, *, output_token_budget: int | None = None) -> Decimal:
        """Conservatively estimate cost before a network call using a four-characters-per-token heuristic."""
        input_tokens = max(1, (len(system_prompt) + len(user_prompt) + 3) // 4)
        output_tokens = self.max_output_tokens if output_token_budget is None else max(1, int(output_token_budget))
        return self._cost(input_tokens, output_tokens)

    def generate_candidate(self, system_prompt: str, user_prompt: str) -> ProviderResult:
        result, input_tokens, output_tokens, cost = self._request_json(system_prompt, user_prompt)
        try:
            return ProviderResult(
                proposed_description=str(result["proposed_description"]),
                category=str(result["category"]),
                attributes={str(key): str(value) for key, value in dict(result.get("attributes", {})).items()},
                rationale=str(result.get("rationale", "")),
                model=self.model,
                provider=self.name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"model response violated canonicalization JSON contract: {exc}") from exc

    def extract_invoice(self, system_prompt: str, user_prompt: str) -> ExtractionProviderResult:
        result, input_tokens, output_tokens, cost = self._request_json(system_prompt, user_prompt)
        try:
            raw_lines = result["lines"]
            if not isinstance(raw_lines, list) or not raw_lines:
                raise ValueError("lines must be a non-empty array")
            lines: list[dict[str, str | None]] = []
            for raw_line in raw_lines:
                if not isinstance(raw_line, dict) or not str(raw_line.get("description", "")).strip():
                    raise ValueError("each line requires description")
                lines.append({
                    "description": str(raw_line["description"]),
                    "quantity": None if raw_line.get("quantity") is None else str(raw_line["quantity"]),
                    "unit_price": None if raw_line.get("unit_price") is None else str(raw_line["unit_price"]),
                    "total": None if raw_line.get("total") is None else str(raw_line["total"]),
                })
            subtotal = parse_decimal(result.get("declared_subtotal"))
            return ExtractionProviderResult(
                lines=tuple(lines),
                declared_subtotal=subtotal,
                rationale=str(result.get("rationale", "")),
                model=self.model,
                provider=self.name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"model response violated extraction JSON contract: {exc}") from exc

    def _request_json(self, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], int, int, Decimal]:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise ProviderError(f"missing API credential environment variable: {self.api_key_env}")
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        raw = self._send_with_retry(request)
        try:
            content = raw["choices"][0]["message"]["content"]
            result: dict[str, Any] = json.loads(content)
            usage = raw.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
            cost = self._cost(input_tokens, output_tokens)
            return result, input_tokens, output_tokens, cost
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(f"model response violated JSON envelope: {exc}") from exc

    def _send_with_retry(self, request: urllib.request.Request) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * (2**attempt))
                    continue
                raise ProviderError(f"model HTTP request failed with status {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * (2**attempt))
                    continue
                raise ProviderError(f"model request failed after bounded retries: {exc}") from exc
        raise ProviderError("model request failed")

    def _cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        million = Decimal("1000000")
        return (
            Decimal(input_tokens) * self.input_cost_per_million / million
            + Decimal(output_tokens) * self.output_cost_per_million / million
        )
