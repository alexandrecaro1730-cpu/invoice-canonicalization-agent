"""Business objective: make operational behavior explicit, reviewable, and environment-specific.

Technical description: loads validated YAML/environment settings for storage, authentication, model cost/resilience, extraction fallback, retrieval, and observability without global state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import yaml

from invoice_canonicalizer.utils.money import ZERO, to_decimal


@dataclass(frozen=True, slots=True)
class AppSettings:
    project_root: Path
    database_path: Path
    prompt_dir: Path
    seed_catalog_path: Path
    client_styles_path: Path
    provider_name: str = "fixture"
    provider_model: str = "fixture-canonicalizer-v1"
    provider_base_url: str = "https://api.openai.com"
    provider_api_key_env: str = "OPENAI_API_KEY"
    provider_input_cost_per_million: Decimal = ZERO
    provider_output_cost_per_million: Decimal = ZERO
    provider_max_output_tokens: int = 350
    provider_timeout_seconds: float = 30.0
    provider_max_retries: int = 2
    provider_retry_backoff_seconds: float = 0.25
    taxonomy_version: str = "2026.08.1"
    retrieval_top_k: int = 5
    retrieval_proposal_threshold: float = 0.60
    retrieval_margin_threshold: float = 0.08
    retrieval_auto_resolve_threshold: float = 0.92
    retrieval_auto_margin_threshold: float = 0.08
    semantic_retrieval_enabled: bool = False
    semantic_retrieval_weight: float = 0.20
    max_file_size_bytes: int = 10_000_000
    max_model_calls_per_document: int = 25
    max_cost_usd_per_document: Decimal = Decimal("0.25")
    enable_ocr_fallback: bool = False
    enable_model_extraction_fallback: bool = True
    max_extraction_prompt_chars: int = 12_000
    auth_mode: str = "disabled"
    auth_api_keys_env: str = "ICA_API_KEYS_JSON"
    log_level: str = "INFO"


def _deep_get(mapping: Mapping[str, Any], key: str, default: Any) -> Any:
    current: Any = mapping
    for part in key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _decimal(value: Any, default: str = "0") -> Decimal:
    parsed = to_decimal(value, default=Decimal(default))
    assert parsed is not None
    return parsed


def load_settings(
    project_root: Path | None = None,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppSettings:
    env = dict(os.environ if environ is None else environ)
    if project_root is not None:
        root = project_root.resolve()
    elif env.get("ICA_PROJECT_ROOT"):
        root = Path(env["ICA_PROJECT_ROOT"]).resolve()
    elif (Path.cwd() / "config" / "default.yaml").exists():
        root = Path.cwd().resolve()
    else:
        root = Path(__file__).resolve().parents[2]
    path = config_path or root / "config" / "default.yaml"
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    settings = AppSettings(
        project_root=root,
        database_path=root / str(_deep_get(raw, "storage.database_path", ".runtime/catalog.db")),
        prompt_dir=root / str(_deep_get(raw, "prompts.directory", "prompts")),
        seed_catalog_path=root / str(_deep_get(raw, "storage.seed_catalog", "data/seed/catalog.json")),
        client_styles_path=root / str(_deep_get(raw, "storage.client_styles", "data/seed/client_styles.json")),
        provider_name=str(_deep_get(raw, "model.provider", "fixture")),
        provider_model=str(_deep_get(raw, "model.model", "fixture-canonicalizer-v1")),
        provider_base_url=str(_deep_get(raw, "model.base_url", "https://api.openai.com")),
        provider_api_key_env=str(_deep_get(raw, "model.api_key_env", "OPENAI_API_KEY")),
        provider_input_cost_per_million=_decimal(_deep_get(raw, "model.input_cost_per_million", "0")),
        provider_output_cost_per_million=_decimal(_deep_get(raw, "model.output_cost_per_million", "0")),
        provider_max_output_tokens=int(_deep_get(raw, "model.max_output_tokens", 350)),
        provider_timeout_seconds=float(_deep_get(raw, "model.timeout_seconds", 30.0)),
        provider_max_retries=int(_deep_get(raw, "model.max_retries", 2)),
        provider_retry_backoff_seconds=float(_deep_get(raw, "model.retry_backoff_seconds", 0.25)),
        taxonomy_version=str(_deep_get(raw, "taxonomy.version", "2026.08.1")),
        retrieval_top_k=int(_deep_get(raw, "retrieval.top_k", 5)),
        retrieval_proposal_threshold=float(_deep_get(raw, "retrieval.proposal_threshold", 0.60)),
        retrieval_margin_threshold=float(_deep_get(raw, "retrieval.margin_threshold", 0.08)),
        retrieval_auto_resolve_threshold=float(_deep_get(raw, "retrieval.auto_resolve_threshold", 0.92)),
        retrieval_auto_margin_threshold=float(_deep_get(raw, "retrieval.auto_margin_threshold", 0.08)),
        semantic_retrieval_enabled=_bool(_deep_get(raw, "retrieval.semantic.enabled", False)),
        semantic_retrieval_weight=float(_deep_get(raw, "retrieval.semantic.weight", 0.20)),
        max_file_size_bytes=int(_deep_get(raw, "security.max_file_size_bytes", 10_000_000)),
        max_model_calls_per_document=int(_deep_get(raw, "cost.max_model_calls_per_document", 25)),
        max_cost_usd_per_document=_decimal(_deep_get(raw, "cost.max_cost_usd_per_document", "0.25"), "0.25"),
        enable_ocr_fallback=_bool(_deep_get(raw, "documents.enable_ocr_fallback", False)),
        enable_model_extraction_fallback=_bool(_deep_get(raw, "documents.enable_model_extraction_fallback", True)),
        max_extraction_prompt_chars=int(_deep_get(raw, "documents.max_extraction_prompt_chars", 12_000)),
        auth_mode=str(_deep_get(raw, "auth.mode", "disabled")),
        auth_api_keys_env=str(_deep_get(raw, "auth.api_keys_env", "ICA_API_KEYS_JSON")),
        log_level=str(_deep_get(raw, "observability.log_level", "INFO")),
    )

    overrides: dict[str, Any] = {}
    mapping: dict[str, tuple[str, Any]] = {
        "ICA_DATABASE_PATH": ("database_path", lambda value: root / value),
        "ICA_PROVIDER": ("provider_name", str),
        "ICA_MODEL": ("provider_model", str),
        "ICA_BASE_URL": ("provider_base_url", str),
        "ICA_MODEL_INPUT_COST_PER_MILLION": ("provider_input_cost_per_million", _decimal),
        "ICA_MODEL_OUTPUT_COST_PER_MILLION": ("provider_output_cost_per_million", _decimal),
        "ICA_MODEL_MAX_OUTPUT_TOKENS": ("provider_max_output_tokens", int),
        "ICA_MODEL_TIMEOUT_SECONDS": ("provider_timeout_seconds", float),
        "ICA_MODEL_MAX_RETRIES": ("provider_max_retries", int),
        "ICA_TAXONOMY_VERSION": ("taxonomy_version", str),
        "ICA_LOG_LEVEL": ("log_level", str),
        "ICA_AUTO_RESOLVE_THRESHOLD": ("retrieval_auto_resolve_threshold", float),
        "ICA_ENABLE_OCR": ("enable_ocr_fallback", _bool),
        "ICA_ENABLE_MODEL_EXTRACTION": ("enable_model_extraction_fallback", _bool),
        "ICA_AUTH_MODE": ("auth_mode", str),
    }
    for env_name, (field_name, caster) in mapping.items():
        if env_name in env:
            overrides[field_name] = caster(env[env_name])
    return replace(settings, **overrides)
