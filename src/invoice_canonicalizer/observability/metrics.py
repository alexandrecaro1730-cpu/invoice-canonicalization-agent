"""Business objective: expose quality, cost, and routing behavior without external infrastructure.

Technical description: provides a thread-safe in-memory counter registry and Prometheus-style rendering.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock


class MetricsRegistry:
    def __init__(self) -> None:
        self._values: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._values[name] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)

    def render_prometheus(self) -> str:
        snapshot = self.snapshot()
        return "\n".join(f"invoice_canonicalizer_{key} {value}" for key, value in sorted(snapshot.items())) + "\n"
