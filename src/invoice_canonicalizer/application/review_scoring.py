"""Business objective: rank human-review work by business impact and uncertainty without inventing value across currencies.

Technical description: provides deterministic retrieval policy scores and queue priority; mixed-currency candidates intentionally fall back to frequency/uncertainty instead of summing incomparable money.
"""

from __future__ import annotations

import math
from decimal import Decimal

from invoice_canonicalizer.domain.models import RetrievalCandidate
from invoice_canonicalizer.utils.money import ZERO, to_decimal


def retrieval_decision_score(candidate: RetrievalCandidate, margin: float) -> float:
    """Combine retrieval quality and separation from the runner-up into a bounded policy score."""
    separation_bonus = min(0.15, max(0.0, margin) * 0.50)
    score = candidate.score + separation_bonus
    if candidate.conflicting_attributes:
        score *= 0.50
    return round(min(0.999, max(0.0, score)), 6)


def generated_candidate_score(retrieval_score: float, retrieval_margin: float, llm_agrees: bool, has_risk_flags: bool) -> float:
    """Score a generated proposal from observable signals without trusting model self-confidence."""
    base = 0.45 + (0.30 * retrieval_score) + (0.10 * min(1.0, retrieval_margin / 0.25))
    if llm_agrees:
        base += 0.10
    if has_risk_flags:
        base -= 0.35
    return round(min(0.95, max(0.0, base)), 6)


def review_priority_score(
    occurrence_count: int,
    affected_value: Decimal,
    decision_score: float,
    *,
    currency: str | None = None,
) -> float:
    """Prioritize frequent, valuable, uncertain candidates while refusing fake mixed-currency totals."""
    frequency = 1.0 + math.log1p(max(0, occurrence_count))
    parsed = to_decimal(affected_value, default=ZERO) or ZERO
    comparable_value = ZERO if currency == "MIXED" else abs(parsed)
    impact = 1.0 + math.log1p(float(comparable_value))
    uncertainty = max(0.05, 1.0 - min(1.0, max(0.0, decision_score)))
    return round(frequency * impact * uncertainty, 6)
