"""Business objective: provide isolated repeatable application environments for every test.

Technical description: adds the source tree to imports and builds a seeded temporary SQLite container per test.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from invoice_canonicalizer.application.factory import ApplicationContainer, build_container
from invoice_canonicalizer.config import AppSettings, load_settings


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return replace(load_settings(ROOT), database_path=tmp_path / "catalog.db")


@pytest.fixture()
def container(settings: AppSettings) -> ApplicationContainer:
    return build_container(settings)


@pytest.fixture()
def expected_descriptions() -> list[str]:
    payload = json.loads((ROOT / "data/examples/expected/challenge_expected.json").read_text(encoding="utf-8"))
    return [item["canonical_description"] for item in payload["mappings"]]
