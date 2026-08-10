"""Business objective: ensure source, installed-wheel, and container deployments resolve configuration predictably.

Technical description: verifies explicit project roots, environment roots, and current-working-directory detection.
"""

from __future__ import annotations

from pathlib import Path

from invoice_canonicalizer.config import load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_explicit_project_root_wins() -> None:
    settings = load_settings(project_root=ROOT, environ={})
    assert settings.project_root == ROOT
    assert settings.prompt_dir == ROOT / "prompts"


def test_environment_project_root_supports_installed_wheel_runtime() -> None:
    settings = load_settings(environ={"ICA_PROJECT_ROOT": str(ROOT)})
    assert settings.project_root == ROOT


def test_current_working_directory_is_used_when_it_contains_config(monkeypatch) -> None:
    monkeypatch.chdir(ROOT)
    settings = load_settings(environ={})
    assert settings.project_root == ROOT


def test_live_model_pricing_can_be_overridden_from_secret_safe_environment() -> None:
    settings = load_settings(project_root=ROOT, environ={
        "ICA_MODEL_INPUT_COST_PER_MILLION": "2.50",
        "ICA_MODEL_OUTPUT_COST_PER_MILLION": "7.75",
        "ICA_MODEL_MAX_OUTPUT_TOKENS": "180",
        "ICA_MODEL_MAX_RETRIES": "1",
    })
    assert str(settings.provider_input_cost_per_million) == "2.50"
    assert str(settings.provider_output_cost_per_million) == "7.75"
    assert settings.provider_max_output_tokens == 180
    assert settings.provider_max_retries == 1
