"""Business objective: prove the built wheel runs outside the source tree with explicit deployment resources.

Technical description: installs the newest wheel into a temporary target and executes a seeded canonicalization from another working directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    wheels = sorted((ROOT / "reports" / "wheels").glob("*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels:
        print("No wheel found in reports/wheels")
        return 1
    wheel = wheels[-1]
    with tempfile.TemporaryDirectory(prefix="invoice-wheel-smoke-") as directory:
        temp = Path(directory)
        target = temp / "site"
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            print(install.stdout + install.stderr)
            return install.returncode
        code = """
import json
from invoice_canonicalizer.application.factory import build_container
from invoice_canonicalizer.config import load_settings
from invoice_canonicalizer.domain.models import InvoiceLine
container = build_container(load_settings())
decision = container.canonicalizer.canonicalize(InvoiceLine(
    tenant_id='testinger', partner_id='default-partner',
    description='Socks, black', source_line_id='wheel-smoke-1'))
print(json.dumps({'description': decision.canonical_description, 'review': decision.requires_human_review}))
assert decision.canonical_description == 'Crew Socks'
assert decision.requires_human_review is False
"""
        environment = {
            **os.environ,
            "PYTHONPATH": str(target),
            "ICA_PROJECT_ROOT": str(ROOT),
            "ICA_DATABASE_PATH": str(temp / "wheel.db"),
        }
        run = subprocess.run([sys.executable, "-c", code], cwd=temp, env=environment, capture_output=True, text=True)
        print(run.stdout + run.stderr)
        return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
