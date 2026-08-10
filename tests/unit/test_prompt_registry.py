"""Business objective: prove prompts are versioned, documented, complete, and stable.

Technical description: validates metadata parsing, placeholder contracts, path safety, and a golden rendered prompt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_canonicalizer.domain.errors import ValidationError
from invoice_canonicalizer.infrastructure.llm.prompt_registry import PromptRegistry

ROOT = Path(__file__).resolve().parents[2]


def test_prompt_metadata_and_placeholders() -> None:
    registry = PromptRegistry(ROOT / "prompts")
    prompt = registry.load("canonicalize/user.txt")
    assert prompt.placeholders == (
        "retrieved_candidates", "source_attributes", "source_description", "style_guide",
    )
    assert len(prompt.version) == 12


def test_rendered_prompt_matches_golden_file() -> None:
    registry = PromptRegistry(ROOT / "prompts")
    prompt = registry.load("canonicalize/user.txt")
    rendered = prompt.render(
        source_description="Black Leather Jacket Midnight",
        style_guide='{"maximum_words": 4}',
        source_attributes='{"category_hint": "jacket", "material": "leather"}',
        retrieved_candidates="[]",
    )
    golden = (ROOT / "tests/golden_prompts/leather_jacket_user.txt").read_text(encoding="utf-8").rstrip()
    assert rendered == golden


def test_prompt_registry_rejects_path_escape_and_missing_values(tmp_path: Path) -> None:
    registry = PromptRegistry(ROOT / "prompts")
    with pytest.raises(ValidationError):
        registry.load("../README.md")
    prompt = registry.load("canonicalize/user.txt")
    with pytest.raises(ValidationError):
        prompt.render(source_description="x")
