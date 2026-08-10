"""Business objective: assemble the same governed components for CLI, API, tests, and MCP.

Technical description: creates tenant-safe storage/authentication, bounded providers, parsers plus model extraction fallback, canonicalization, clustered review queue, prompts, retrieval extension points, metrics, and seeded runtime state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from invoice_canonicalizer.application.canonicalization import CanonicalizationService
from invoice_canonicalizer.application.ingestion import IngestionService
from invoice_canonicalizer.application.review_queue import ReviewQueueService
from invoice_canonicalizer.application.reviews import ReviewService
from invoice_canonicalizer.config import AppSettings
from invoice_canonicalizer.domain.errors import AuthenticationError
from invoice_canonicalizer.infrastructure.db.sqlite_repository import SQLiteCatalogRepository
from invoice_canonicalizer.infrastructure.documents.delimited_parser import DelimitedInvoiceParser
from invoice_canonicalizer.infrastructure.documents.docx_parser import DocxInvoiceParser
from invoice_canonicalizer.infrastructure.documents.json_parser import JsonInvoiceParser
from invoice_canonicalizer.infrastructure.documents.model_extractor import ModelDocumentExtractor
from invoice_canonicalizer.infrastructure.documents.pdf_parser import PdfInvoiceParser
from invoice_canonicalizer.infrastructure.documents.xlsx_parser import XlsxInvoiceParser
from invoice_canonicalizer.infrastructure.llm.fixture_provider import FixtureModelProvider
from invoice_canonicalizer.infrastructure.llm.openai_compatible import OpenAICompatibleProvider
from invoice_canonicalizer.infrastructure.llm.prompt_registry import PromptRegistry
from invoice_canonicalizer.infrastructure.retrieval.hybrid import HybridRetriever
from invoice_canonicalizer.infrastructure.retrieval.semantic import DisabledSemanticScoreProvider, SemanticScoreProvider
from invoice_canonicalizer.observability.metrics import MetricsRegistry
from invoice_canonicalizer.security.auth import ApiKeyAuthenticator, Authenticator, DisabledAuthenticator


@dataclass(slots=True)
class ApplicationContainer:
    settings: AppSettings
    repository: SQLiteCatalogRepository
    canonicalizer: CanonicalizationService
    ingestion: IngestionService
    reviews: ReviewService
    review_queue: ReviewQueueService
    metrics: MetricsRegistry
    authenticator: Authenticator


def build_container(
    settings: AppSettings,
    *,
    semantic_provider: SemanticScoreProvider | None = None,
) -> ApplicationContainer:
    repository = SQLiteCatalogRepository(settings.database_path)
    repository.initialize()
    repository.seed_from_file(settings.seed_catalog_path)
    prompts = PromptRegistry(settings.prompt_dir)
    for prompt_path in (
        "canonicalize/system.txt", "canonicalize/user.txt",
        "extract/system.txt", "extract/user.txt",
    ):
        prompts.load(prompt_path)
    styles = json.loads(settings.client_styles_path.read_text(encoding="utf-8"))
    if settings.provider_name == "fixture":
        provider = FixtureModelProvider(
            settings.prompt_dir / "fixtures" / "model_responses.json",
            model=settings.provider_model,
            extraction_fixture_path=settings.prompt_dir / "fixtures" / "extraction_responses.json",
        )
    elif settings.provider_name == "openai-compatible":
        provider = OpenAICompatibleProvider(
            base_url=settings.provider_base_url,
            model=settings.provider_model,
            api_key_env=settings.provider_api_key_env,
            timeout_seconds=settings.provider_timeout_seconds,
            input_cost_per_million=settings.provider_input_cost_per_million,
            output_cost_per_million=settings.provider_output_cost_per_million,
            max_output_tokens=settings.provider_max_output_tokens,
            max_retries=settings.provider_max_retries,
            retry_backoff_seconds=settings.provider_retry_backoff_seconds,
        )
    else:
        raise ValueError(f"unsupported provider: {settings.provider_name}")

    if settings.auth_mode == "disabled":
        authenticator: Authenticator = DisabledAuthenticator()
    elif settings.auth_mode == "api-key":
        authenticator = ApiKeyAuthenticator.from_environment(settings.auth_api_keys_env)
    else:
        raise AuthenticationError(f"unsupported auth mode: {settings.auth_mode}")

    if settings.semantic_retrieval_enabled and semantic_provider is None:
        raise ValueError(
            "semantic retrieval is enabled but no SemanticScoreProvider adapter was injected; "
            "keep it disabled until an approved embedding/pgvector adapter is benchmarked"
        )
    semantic = semantic_provider or DisabledSemanticScoreProvider()

    metrics = MetricsRegistry()
    canonicalizer = CanonicalizationService(
        repository=repository,
        retriever=HybridRetriever(
            repository,
            semantic_provider=semantic,
            semantic_weight=settings.semantic_retrieval_weight,
        ),
        provider=provider,
        prompts=prompts,
        client_styles=styles,
        taxonomy_version=settings.taxonomy_version,
        proposal_threshold=settings.retrieval_proposal_threshold,
        margin_threshold=settings.retrieval_margin_threshold,
        auto_resolve_threshold=settings.retrieval_auto_resolve_threshold,
        auto_margin_threshold=settings.retrieval_auto_margin_threshold,
        top_k=settings.retrieval_top_k,
        metrics=metrics,
    )
    parsers = (
        PdfInvoiceParser(enable_ocr_fallback=settings.enable_ocr_fallback),
        DocxInvoiceParser(),
        XlsxInvoiceParser(),
        JsonInvoiceParser(),
        DelimitedInvoiceParser(),
    )
    model_extractor = None
    if settings.enable_model_extraction_fallback:
        model_extractor = ModelDocumentExtractor(
            provider,
            prompts,
            enable_ocr=settings.enable_ocr_fallback,
            max_prompt_chars=settings.max_extraction_prompt_chars,
        )
    ingestion = IngestionService(
        parsers=parsers,
        canonicalizer=canonicalizer,
        max_file_size_bytes=settings.max_file_size_bytes,
        max_model_calls_per_document=settings.max_model_calls_per_document,
        max_cost_usd_per_document=settings.max_cost_usd_per_document,
        model_extractor=model_extractor,
        repository=repository,
    )
    reviews = ReviewService(repository)
    return ApplicationContainer(
        settings=settings,
        repository=repository,
        canonicalizer=canonicalizer,
        ingestion=ingestion,
        reviews=reviews,
        review_queue=ReviewQueueService(reviews),
        metrics=metrics,
        authenticator=authenticator,
    )
