"""Business objective: ensure operational routing counters are observable and thread-safe in design.

Technical description: verifies snapshots and Prometheus-compatible output naming.
"""

from invoice_canonicalizer.observability.metrics import MetricsRegistry


def test_metrics_increment_and_render() -> None:
    metrics = MetricsRegistry()
    metrics.increment("exact_alias_total")
    metrics.increment("exact_alias_total", 2)
    assert metrics.snapshot() == {"exact_alias_total": 3}
    assert "invoice_canonicalizer_exact_alias_total 3" in metrics.render_prometheus()
