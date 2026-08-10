"""Business objective: make the assessment's three-run reproducibility requirement an executable acceptance contract.

Technical description: validates both the three inconsistent output runs shown on page 1 of the challenge and three repeated replays of the raw invoice descriptions. All supplied examples must converge to the same six canonical descriptions without model calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from invoice_canonicalizer.application.factory import ApplicationContainer
from invoice_canonicalizer.domain.models import DecisionKind, InvoiceLine
from invoice_canonicalizer.infrastructure.llm.fixture_provider import FixtureModelProvider

ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = json.loads(
    (ROOT / "data/examples/expected/challenge_three_run_acceptance.json").read_text(encoding="utf-8")
)
EXPECTED = ACCEPTANCE["expected_canonical_descriptions"]
OBSERVED_RUNS = ACCEPTANCE["observed_runs"]
RAW_INVOICE_DESCRIPTIONS = [
    "Highlife Steel Accessories",
    "Sneaker “Unstoppable”",
    "T-Shirt White “Polarbear”",
    "T-Shirt Beige “Grizzly”",
    "Shorts “El Camino”",
    "Socks, black",
]


def _provider_calls(container: ApplicationContainer) -> int:
    provider = container.canonicalizer.provider
    assert isinstance(provider, FixtureModelProvider)
    return provider.canonicalization_call_count


@pytest.mark.parametrize("run", OBSERVED_RUNS, ids=lambda item: f"challenge-run-{item['run']}")
def test_supplied_three_run_variants_converge_without_llm(
    container: ApplicationContainer,
    run: dict[str, object],
) -> None:
    descriptions = run["descriptions"]
    assert isinstance(descriptions, list)
    before = _provider_calls(container)

    decisions = [
        container.canonicalizer.canonicalize(
            InvoiceLine(
                tenant_id="testinger",
                partner_id="default-partner",
                description=str(description),
                source_line_id=f"challenge-run-{run['run']}-{index}",
            )
        )
        for index, description in enumerate(descriptions, start=1)
    ]

    assert [decision.canonical_description for decision in decisions] == EXPECTED
    assert all(decision.decision_kind is DecisionKind.EXACT_ALIAS for decision in decisions)
    assert _provider_calls(container) == before


def test_raw_challenge_invoice_replays_identically_three_times_without_llm(
    container: ApplicationContainer,
) -> None:
    before = _provider_calls(container)
    outputs: list[list[str | None]] = []

    for replay in range(1, 4):
        decisions = [
            container.canonicalizer.canonicalize(
                InvoiceLine(
                    tenant_id="testinger",
                    partner_id="default-partner",
                    description=description,
                    source_line_id=f"raw-replay-{replay}-{index}",
                )
            )
            for index, description in enumerate(RAW_INVOICE_DESCRIPTIONS, start=1)
        ]
        outputs.append([decision.canonical_description for decision in decisions])

    assert outputs == [EXPECTED, EXPECTED, EXPECTED]
    assert _provider_calls(container) == before
