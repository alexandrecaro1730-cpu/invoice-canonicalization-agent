"""Business objective: prove the external-provider adapter sends bounded JSON requests and validates responses.

Technical description: mocks urllib transport to test credentials, usage accounting, JSON parsing, and failures offline.
"""

from __future__ import annotations

import io
import json
import os
from decimal import Decimal
from unittest.mock import patch

import pytest

from invoice_canonicalizer.domain.errors import ProviderError
from invoice_canonicalizer.infrastructure.llm.openai_compatible import OpenAICompatibleProvider


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._bytes


def test_provider_requires_credential(monkeypatch) -> None:
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    provider = OpenAICompatibleProvider("https://example.invalid", "model", "TEST_API_KEY")
    with pytest.raises(ProviderError):
        provider.generate_candidate("system", "user")


def test_provider_parses_contract_and_cost(monkeypatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "test-secret-from-env")
    payload = {
        "choices": [{"message": {"content": json.dumps({
            "proposed_description": "Cotton Cap", "category": "headwear",
            "attributes": {"material": "cotton"}, "rationale": "explicit material",
        })}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
    }
    provider = OpenAICompatibleProvider(
        "https://example.invalid", "model", "TEST_API_KEY",
        input_cost_per_million=1.0, output_cost_per_million=2.0,
    )
    with patch("urllib.request.urlopen", return_value=FakeResponse(payload)):
        result = provider.generate_candidate("system", "user")
    assert result.proposed_description == "Cotton Cap"
    assert result.estimated_cost_usd == Decimal("0.002")


def test_provider_rejects_invalid_contract(monkeypatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "test-secret-from-env")
    provider = OpenAICompatibleProvider("https://example.invalid", "model", "TEST_API_KEY")
    with patch("urllib.request.urlopen", return_value=FakeResponse({"choices": []})):
        with pytest.raises(ProviderError):
            provider.generate_candidate("system", "user")


def test_provider_estimates_worst_case_cost_before_call() -> None:
    provider = OpenAICompatibleProvider(
        "https://example.invalid", "model", "TEST_API_KEY",
        input_cost_per_million="1.00", output_cost_per_million="4.00", max_output_tokens=100,
    )
    # 8 prompt characters -> 2 estimated input tokens, plus 100-token output budget.
    assert provider.estimate_cost("abcd", "efgh") == Decimal("0.000402")


def test_provider_parses_extraction_contract(monkeypatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "test-secret-from-env")
    payload = {
        "choices": [{"message": {"content": json.dumps({
            "lines": [{"description": "Widget", "quantity": "2", "unit_price": "12.50", "total": "25.00"}],
            "declared_subtotal": "25.00",
            "rationale": "table row",
        })}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    provider = OpenAICompatibleProvider(
        "https://example.invalid", "model", "TEST_API_KEY",
        input_cost_per_million="1", output_cost_per_million="2",
    )
    with patch("urllib.request.urlopen", return_value=FakeResponse(payload)):
        result = provider.extract_invoice("system", "user")
    assert result.lines[0]["description"] == "Widget"
    assert result.declared_subtotal == Decimal("25.00")
    assert result.estimated_cost_usd == Decimal("0.00005")


def test_provider_retries_transient_http_failure_only_within_bound(monkeypatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "test-secret-from-env")
    payload = {
        "choices": [{"message": {"content": json.dumps({
            "proposed_description": "Cotton Cap", "category": "headwear", "attributes": {}, "rationale": "ok",
        })}}],
        "usage": {},
    }
    transient = __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
        "https://example.invalid", 429, "too many", None, io.BytesIO(b""),
    )
    provider = OpenAICompatibleProvider(
        "https://example.invalid", "model", "TEST_API_KEY", max_retries=1, retry_backoff_seconds=0,
    )
    with patch("urllib.request.urlopen", side_effect=[transient, FakeResponse(payload)]) as mocked:
        result = provider.generate_candidate("system", "user")
    assert result.proposed_description == "Cotton Cap"
    assert mocked.call_count == 2
