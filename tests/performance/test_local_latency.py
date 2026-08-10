"""Business objective: ensure the deterministic known-alias path remains suitable for high-volume invoice lines.

Technical description: measures 500 cached and exact local decisions under a generous CI-safe latency ceiling.
"""

from __future__ import annotations

import time

import pytest

from invoice_canonicalizer.domain.models import InvoiceLine


@pytest.mark.performance
def test_500_known_lines_complete_under_two_seconds(container) -> None:
    started = time.perf_counter()
    for index in range(500):
        container.canonicalizer.canonicalize(InvoiceLine(
            tenant_id="testinger", partner_id="default-partner",
            description="Socks, black", source_line_id=f"perf-{index}",
        ))
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
