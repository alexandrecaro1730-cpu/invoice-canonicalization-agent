"""Business objective: verify an explicitly approved live model contract with a bounded single request.

Technical description: requires external-provider configuration and canonicalizes one non-sensitive synthetic line.
"""

from __future__ import annotations

import json

from invoice_canonicalizer.application.factory import build_container
from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.domain.models import InvoiceLine


def main() -> int:
    settings = load_settings()
    if settings.provider_name != "openai-compatible":
        raise SystemExit("Set ICA_PROVIDER=openai-compatible for the live smoke test")
    container = build_container(settings)
    result = container.canonicalizer.canonicalize(InvoiceLine(
        tenant_id="testinger", partner_id="default-partner",
        description="Cotton Cap Sunrise", source_line_id="live-smoke-1",
    ))
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.requires_human_review else 1


if __name__ == "__main__":
    raise SystemExit(main())
