"""Business objective: ensure model calls cannot exceed a document's approved spend or call count.

Technical description: exercises pre-call reservation and post-call actual-cost enforcement.
"""

import pytest

from invoice_canonicalizer.application.budget import CostBudget
from invoice_canonicalizer.domain.errors import BudgetExceededError


def test_call_limit_is_enforced_before_call() -> None:
    budget = CostBudget(max_calls=1, max_cost_usd=1.0)
    budget.reserve_call()
    with pytest.raises(BudgetExceededError):
        budget.reserve_call()


def test_cost_limit_is_enforced() -> None:
    budget = CostBudget(max_calls=2, max_cost_usd=0.1)
    budget.reserve_call(0.05)
    budget.register_actual_cost(0.05)
    with pytest.raises(BudgetExceededError):
        budget.reserve_call(0.06)
