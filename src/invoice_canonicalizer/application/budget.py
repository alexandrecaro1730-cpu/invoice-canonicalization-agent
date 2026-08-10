"""Business objective: prevent unexpected model cost and uncontrolled model usage.

Technical description: enforces per-document call and Decimal cost limits before provider invocation and records actual usage after each call.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from invoice_canonicalizer.domain.errors import BudgetExceededError
from invoice_canonicalizer.utils.money import ZERO, to_decimal


@dataclass(slots=True)
class CostBudget:
    max_calls: int
    max_cost_usd: Decimal
    calls: int = 0
    cost_usd: Decimal = ZERO

    def __post_init__(self) -> None:
        parsed = to_decimal(self.max_cost_usd, default=ZERO)
        assert parsed is not None
        self.max_cost_usd = parsed

    def reserve_call(self, estimated_cost_usd: Decimal = ZERO) -> None:
        estimate = to_decimal(estimated_cost_usd, default=ZERO)
        assert estimate is not None
        if self.calls + 1 > self.max_calls:
            raise BudgetExceededError("model call budget exceeded")
        if self.cost_usd + estimate > self.max_cost_usd:
            raise BudgetExceededError("model cost budget exceeded before provider invocation")
        self.calls += 1

    def register_actual_cost(self, estimated_cost_usd: Decimal) -> None:
        actual = to_decimal(estimated_cost_usd, default=ZERO)
        assert actual is not None
        self.cost_usd += actual
        if self.cost_usd > self.max_cost_usd:
            raise BudgetExceededError("actual model cost exceeded document budget")
