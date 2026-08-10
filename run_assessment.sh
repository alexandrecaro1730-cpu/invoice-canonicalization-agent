#!/usr/bin/env bash
# Business objective: let a reviewer prepare and assess the complete project with one command.
# Technical description: installs the exact CI/dev lock when required, tolerates tool-install restrictions only for optional local static checks, and runs the offline production quality gate.
set -euo pipefail
cd "$(dirname "$0")"

core_missing=0
if ! python3 - <<'PY'
import importlib
for module in ["fastapi", "pydantic", "pypdf", "multipart", "yaml", "uvicorn", "coverage", "httpx", "pytest", "docx", "reportlab"]:
    importlib.import_module(module)
PY
then
  core_missing=1
fi

if [[ "$core_missing" == "1" ]]; then
  echo "Installing exact CI/dev dependency lock..."
  python3 -m pip install -r requirements-dev.lock
else
  if ! python3 - <<'PY'
import importlib
for module in ["ruff", "mypy"]:
    importlib.import_module(module)
PY
  then
    echo "Static-analysis tools are not installed; attempting locked install..."
    if ! python3 -m pip install -r requirements-dev.lock; then
      echo "WARNING: dependency installation is restricted in this environment. Ruff/mypy will be reported as SKIP locally; CI requires them."
    fi
  fi
fi

PYTHONPATH=src python3 scripts/quality_gate.py
