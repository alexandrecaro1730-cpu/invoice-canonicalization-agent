"""Business objective: ensure routing and review-priority policy is deterministic and monotonic.

Technical description: unit-tests bounded retrieval/generation scores and business-impact review prioritization.
"""

from __future__ import annotations

from invoice_canonicalizer.application.review_scoring import generated_candidate_score, retrieval_decision_score, review_priority_score
from invoice_canonicalizer.domain.models import CanonicalProduct, RetrievalCandidate


def _candidate(score: float, conflicts: tuple[str, ...] = ()) -> RetrievalCandidate:
    return RetrievalCandidate(
        product=CanonicalProduct("p1", "t1", "v1", "Crew Socks", "socks"),
        score=score, lexical_score=score, token_score=score, attribute_score=1.0,
        matched_alias="Athletic Socks", conflicting_attributes=conflicts,
    )


def test_retrieval_score_rewards_margin_and_penalizes_conflict() -> None:
    low_margin = retrieval_decision_score(_candidate(0.85), 0.02)
    high_margin = retrieval_decision_score(_candidate(0.85), 0.30)
    conflicted = retrieval_decision_score(_candidate(0.85, ("color",)), 0.30)
    assert high_margin > low_margin
    assert conflicted < low_margin
    assert 0 <= conflicted <= high_margin <= 0.999


def test_generated_score_uses_evidence_not_model_self_confidence() -> None:
    base = generated_candidate_score(0.6, 0.1, False, False)
    agreement = generated_candidate_score(0.6, 0.1, True, False)
    risky = generated_candidate_score(0.6, 0.1, True, True)
    assert agreement > base > risky


def test_review_priority_increases_with_frequency_and_value_but_falls_with_certainty() -> None:
    baseline = review_priority_score(1, 10, 0.5)
    frequent = review_priority_score(100, 10, 0.5)
    valuable = review_priority_score(1, 10_000, 0.5)
    certain = review_priority_score(1, 10, 0.99)
    assert frequent > baseline
    assert valuable > baseline
    assert certain < baseline
