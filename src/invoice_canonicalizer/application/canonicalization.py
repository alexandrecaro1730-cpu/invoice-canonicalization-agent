"""Business objective: produce reproducible product descriptions while minimizing model calls and unsafe knowledge changes.

Technical description: orchestrates cache/exact lookup, pending-candidate deduplication, hybrid retrieval, policy scoring, bounded generation, staged review, and audit.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

from invoice_canonicalizer.application.budget import CostBudget
from invoice_canonicalizer.application.ports import CatalogRepository, ModelProvider
from invoice_canonicalizer.application.review_scoring import generated_candidate_score, retrieval_decision_score
from invoice_canonicalizer.domain.attributes import extract_attributes, unsupported_attributes
from invoice_canonicalizer.domain.errors import BudgetExceededError, ProviderError
from invoice_canonicalizer.domain.models import (
    CanonicalizationDecision,
    DecisionKind,
    InvoiceLine,
    RetrievalCandidate,
    ReviewRecord,
)
from invoice_canonicalizer.infrastructure.llm.prompt_registry import PromptRegistry
from invoice_canonicalizer.infrastructure.retrieval.hybrid import HybridRetriever
from invoice_canonicalizer.observability.metrics import MetricsRegistry
from invoice_canonicalizer.security.input_guard import detect_untrusted_instruction, validate_generated_description
from invoice_canonicalizer.security.pii import redact_pii
from invoice_canonicalizer.utils.hashing import sha256_text
from invoice_canonicalizer.utils.money import ZERO
from invoice_canonicalizer.utils.text import normalize_text


class CanonicalizationService:
    def __init__(
        self,
        repository: CatalogRepository,
        retriever: HybridRetriever,
        provider: ModelProvider,
        prompts: PromptRegistry,
        client_styles: dict[str, dict[str, object]],
        taxonomy_version: str,
        proposal_threshold: float = 0.70,
        margin_threshold: float = 0.08,
        auto_resolve_threshold: float = 0.92,
        auto_margin_threshold: float = 0.08,
        top_k: int = 5,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.retriever = retriever
        self.provider = provider
        self.prompts = prompts
        self.client_styles = client_styles
        self.taxonomy_version = taxonomy_version
        self.proposal_threshold = proposal_threshold
        self.margin_threshold = margin_threshold
        self.auto_resolve_threshold = auto_resolve_threshold
        self.auto_margin_threshold = auto_margin_threshold
        self.top_k = top_k
        self.metrics = metrics or MetricsRegistry()

    def canonicalize(self, line: InvoiceLine, budget: CostBudget | None = None) -> CanonicalizationDecision:
        normalized = normalize_text(line.description)
        line_hash = sha256_text(f"{line.tenant_id}|{line.partner_id}|{normalized}")
        candidate_key = sha256_text(f"candidate|{line.tenant_id}|{line.partner_id}|{normalized}")
        flags = list(detect_untrusted_instruction(line.description))

        # Cache is safe only when no knowledge-review record is attached. A staged review may
        # have been approved since the previous call, so exact approved knowledge must win.
        cached = self.repository.get_cached_decision(line.tenant_id, line_hash, self.taxonomy_version)
        if cached and cached.review_id is None and not cached.requires_human_review:
            self.metrics.increment("cache_hits_total")
            return replace(cached, decision_kind=DecisionKind.CACHED, from_cache=True, source_line_id=line.source_line_id)

        exact_alias = self.repository.find_approved_alias(line.tenant_id, line.partner_id, normalized)
        if exact_alias:
            product = self.repository.get_product(line.tenant_id, exact_alias.product_id)
            if product is None:
                flags.append("orphan_alias")
            else:
                decision = CanonicalizationDecision(
                    decision_id=str(uuid.uuid4()), tenant_id=line.tenant_id, partner_id=line.partner_id,
                    source_line_id=line.source_line_id, input_description=line.description,
                    normalized_description=normalized, decision_kind=DecisionKind.EXACT_ALIAS,
                    canonical_product_id=product.product_id,
                    canonical_description=product.canonical_description, category=product.category,
                    confidence=1.0, requires_human_review=False, review_id=None,
                    evidence=({"type": "approved_alias", "alias_id": exact_alias.alias_id, "alias": exact_alias.alias_text},),
                    taxonomy_version=self.taxonomy_version, prompt_version=None, model=None, provider=None,
                    estimated_cost_usd=ZERO, flags=tuple(flags),
                )
                self.repository.save_decision(decision, line_hash)
                self.repository.record_audit(line.tenant_id, "canonicalization_exact_alias", {
                    "decision_id": decision.decision_id, "product_id": product.product_id,
                    "source_line_id": line.source_line_id,
                })
                self.metrics.increment("exact_alias_total")
                return decision

        # One pending knowledge candidate represents every repeated occurrence of the same
        # normalized unknown. This prevents N invoice lines from causing N model calls/reviews.
        pending = self.repository.find_pending_review_by_candidate_key(line.tenant_id, line.partner_id, candidate_key)
        if pending:
            return self._reuse_pending_review(
                line=line,
                normalized=normalized,
                line_hash=line_hash,
                pending=pending,
                flags=flags,
                record_occurrence=True,
            )

        # A final cached result without a direct alias can still be reused after checking for newly
        # approved knowledge and active staged candidates.
        if cached and not cached.requires_human_review:
            self.metrics.increment("cache_hits_total")
            return replace(cached, decision_kind=DecisionKind.CACHED, from_cache=True, source_line_id=line.source_line_id)

        # Obvious prompt-injection text is never sent to an external model. It becomes a bounded
        # human-review item instead of allowing document content to influence model instructions.
        if flags:
            return self._abstain(line, normalized, line_hash, candidate_key, (), flags)

        candidates = tuple(self.retriever.search(line, self.top_k))
        margin = candidates[0].score - candidates[1].score if len(candidates) > 1 else (candidates[0].score if candidates else 0.0)
        evidence = tuple(
            {
                "type": "retrieval",
                "product_id": candidate.product.product_id,
                "canonical_description": candidate.product.canonical_description,
                "matched_alias": candidate.matched_alias,
                "score": candidate.score,
                "lexical_score": candidate.lexical_score,
                "token_score": candidate.token_score,
                "attribute_score": candidate.attribute_score,
                "semantic_score": candidate.semantic_score,
                "conflicting_attributes": list(candidate.conflicting_attributes),
            }
            for candidate in candidates
        )

        if candidates:
            top = candidates[0]
            decision_score = retrieval_decision_score(top, margin)
            can_auto_resolve = bool(
                top.score >= self.proposal_threshold
                and margin >= self.auto_margin_threshold
                and decision_score >= self.auto_resolve_threshold
                and not top.conflicting_attributes
            )
            if can_auto_resolve:
                review = self._create_review(
                    line=line,
                    candidate_key=candidate_key,
                    proposed_description=top.product.canonical_description,
                    proposed_category=top.product.category,
                    attributes=dict(top.product.attributes),
                    evidence=evidence,
                    decision_score=decision_score,
                    retrieval_score=top.score,
                    retrieval_margin=margin,
                    llm_used=False,
                    blocks_transaction=False,
                    target_product_id=top.product.product_id,
                    risk_flags=tuple(flags + ["auto_resolved_pending_alias_promotion"]),
                )
                decision = CanonicalizationDecision(
                    decision_id=str(uuid.uuid4()), tenant_id=line.tenant_id, partner_id=line.partner_id,
                    source_line_id=line.source_line_id, input_description=line.description,
                    normalized_description=normalized, decision_kind=DecisionKind.AUTO_RETRIEVAL,
                    canonical_product_id=top.product.product_id,
                    canonical_description=top.product.canonical_description, category=top.product.category,
                    confidence=decision_score, requires_human_review=False, review_id=review.review_id,
                    evidence=evidence, taxonomy_version=self.taxonomy_version,
                    prompt_version=None, model=None, provider=None, estimated_cost_usd=ZERO,
                    flags=review.risk_flags,
                )
                self.repository.save_decision(decision, line_hash)
                self.metrics.increment("auto_retrieval_total")
                self.repository.record_audit(line.tenant_id, "canonicalization_auto_resolved_staged", {
                    "decision_id": decision.decision_id, "review_id": review.review_id,
                    "product_id": top.product.product_id, "decision_score": decision_score,
                })
                return decision

        # Medium-confidence and genuinely novel cases get one constrained model call per unique
        # normalized candidate, then enter the same review queue. Retrieval evidence is supplied to
        # the prompt so the model can agree with an existing product rather than always create one.
        return self._generate_review_candidate(
            line, normalized, line_hash, candidate_key, candidates, evidence, flags, margin, budget,
        )

    def _reuse_pending_review(
        self,
        *,
        line: InvoiceLine,
        normalized: str,
        line_hash: str,
        pending: ReviewRecord,
        flags: list[str],
        record_occurrence: bool,
    ) -> CanonicalizationDecision:
        if record_occurrence:
            pending = self.repository.record_review_occurrence(
                line.tenant_id,
                pending.review_id,
                line.description,
                line.source_line_id,
                abs(line.total or ZERO),
                line.currency,
            )
        self.metrics.increment("pending_review_reuse_total")
        self.metrics.increment("llm_calls_avoided_total")
        decision = CanonicalizationDecision(
            decision_id=str(uuid.uuid4()),
            tenant_id=line.tenant_id,
            partner_id=line.partner_id,
            source_line_id=line.source_line_id,
            input_description=line.description,
            normalized_description=normalized,
            decision_kind=DecisionKind.PENDING_REVIEW_REUSE,
            canonical_product_id=pending.target_product_id,
            canonical_description=(
                pending.proposed_description if pending.proposed_description != "Needs Product Review" else None
            ),
            category=pending.proposed_category if pending.proposed_category != "unknown" else None,
            confidence=pending.decision_score,
            requires_human_review=pending.blocks_transaction,
            review_id=pending.review_id,
            evidence=pending.evidence,
            taxonomy_version=self.taxonomy_version,
            prompt_version=pending.prompt_version,
            model=pending.model,
            provider=pending.provider,
            estimated_cost_usd=ZERO,
            flags=tuple(dict.fromkeys((*pending.risk_flags, *flags, "reused_pending_candidate"))),
        )
        self.repository.save_decision(decision, line_hash)
        return decision

    def _generate_review_candidate(
        self,
        line: InvoiceLine,
        normalized: str,
        line_hash: str,
        candidate_key: str,
        candidates: tuple[RetrievalCandidate, ...],
        evidence: tuple[dict[str, object], ...],
        flags: list[str],
        margin: float,
        budget: CostBudget | None,
    ) -> CanonicalizationDecision:
        # Atomically stage a placeholder before any model call. If two workers discover the same
        # new wording at once, the partial unique index selects one owner; every loser attaches to
        # that placeholder and returns without making a duplicate LLM call.
        claim_review_id = str(uuid.uuid4())
        top = candidates[0] if candidates else None
        retrieval_score = top.score if top else 0.0
        placeholder = self._create_review(
            line=line,
            candidate_key=candidate_key,
            proposed_description="Needs Product Review",
            proposed_category="unknown",
            attributes={},
            evidence=evidence,
            decision_score=0.0,
            retrieval_score=retrieval_score,
            retrieval_margin=margin,
            llm_used=False,
            blocks_transaction=True,
            target_product_id=None,
            risk_flags=tuple(flags + ["generation_in_progress"]),
            review_id=claim_review_id,
        )
        if placeholder.review_id != claim_review_id:
            return self._reuse_pending_review(
                line=line,
                normalized=normalized,
                line_hash=line_hash,
                pending=placeholder,
                flags=flags,
                record_occurrence=False,
            )

        system_template = self.prompts.load("canonicalize/system.txt")
        user_template = self.prompts.load("canonicalize/user.txt")
        style = self.client_styles.get(line.tenant_id, self.client_styles.get("default", {}))
        safe_description = redact_pii(line.description)
        user_prompt = user_template.render(
            source_description=safe_description,
            style_guide=json.dumps(style, sort_keys=True),
            source_attributes=json.dumps(extract_attributes(line.description), sort_keys=True),
            retrieved_candidates=json.dumps(list(evidence), sort_keys=True),
        )
        try:
            if budget:
                budget.reserve_call(self.provider.estimate_cost(system_template.body, user_prompt))
            self.metrics.increment("llm_call_attempts_total")
            provider_result = self.provider.generate_candidate(system_template.body, user_prompt)
            self.metrics.increment("llm_calls_total")
            if budget:
                budget.register_actual_cost(provider_result.estimated_cost_usd)
        except (BudgetExceededError, ProviderError) as exc:
            failure_flags = tuple(dict.fromkeys((*flags, type(exc).__name__.lower())))
            failed_review = self.repository.update_pending_review(replace(
                placeholder,
                risk_flags=failure_flags,
                llm_used=isinstance(exc, ProviderError),
                provider=self.provider.name if isinstance(exc, ProviderError) else None,
                model=self.provider.model if isinstance(exc, ProviderError) else None,
            ))
            decision = CanonicalizationDecision(
                decision_id=str(uuid.uuid4()),
                tenant_id=line.tenant_id,
                partner_id=line.partner_id,
                source_line_id=line.source_line_id,
                input_description=line.description,
                normalized_description=normalized,
                decision_kind=DecisionKind.ABSTAINED,
                canonical_product_id=None,
                canonical_description=None,
                category=None,
                confidence=0.0,
                requires_human_review=True,
                review_id=failed_review.review_id,
                evidence=failed_review.evidence,
                taxonomy_version=self.taxonomy_version,
                prompt_version=None,
                model=failed_review.model,
                provider=failed_review.provider,
                estimated_cost_usd=ZERO,
                flags=failed_review.risk_flags,
            )
            self.repository.save_decision(decision, line_hash)
            self.metrics.increment("abstentions_total")
            return decision

        output_flags = list(validate_generated_description(provider_result.proposed_description))
        unsupported = unsupported_attributes(extract_attributes(line.description), provider_result.attributes)
        output_flags.extend(f"unsupported_attribute_{name}" for name in unsupported)
        flags.extend(output_flags)

        retrieval_supports_existing = bool(
            top
            and top.score >= self.proposal_threshold
            and margin >= self.margin_threshold
            and not top.conflicting_attributes
        )
        llm_agrees = bool(
            retrieval_supports_existing
            and top
            and normalize_text(provider_result.proposed_description)
            == normalize_text(top.product.canonical_description)
        )
        decision_score = generated_candidate_score(retrieval_score, margin, llm_agrees, bool(output_flags))
        proposed_description = provider_result.proposed_description if not output_flags else "Needs Product Review"
        proposed_category = provider_result.category if not output_flags else "unknown"
        target_product_id = top.product.product_id if llm_agrees and top and not output_flags else None
        final_evidence = evidence + ({
            "type": "model_rationale",
            "rationale": provider_result.rationale,
            "llm_agrees_with_top_retrieval": llm_agrees,
        },)
        review = self.repository.update_pending_review(replace(
            placeholder,
            proposed_description=proposed_description,
            proposed_category=proposed_category,
            attributes=dict(provider_result.attributes) if not output_flags else {},
            evidence=final_evidence,
            decision_score=decision_score,
            retrieval_score=retrieval_score,
            retrieval_margin=margin,
            llm_used=True,
            blocks_transaction=True,
            target_product_id=target_product_id,
            risk_flags=tuple(flags),
            prompt_version=f"{system_template.version}:{user_template.version}",
            model=provider_result.model,
            provider=provider_result.provider,
        ))
        decision_kind = DecisionKind.GENERATED_CANDIDATE if not output_flags else DecisionKind.ABSTAINED
        decision = CanonicalizationDecision(
            decision_id=str(uuid.uuid4()),
            tenant_id=line.tenant_id,
            partner_id=line.partner_id,
            source_line_id=line.source_line_id,
            input_description=line.description,
            normalized_description=normalized,
            decision_kind=decision_kind,
            canonical_product_id=target_product_id,
            canonical_description=proposed_description if not output_flags else None,
            category=proposed_category if not output_flags else None,
            confidence=decision_score if not output_flags else 0.0,
            requires_human_review=True,
            review_id=review.review_id,
            evidence=review.evidence,
            taxonomy_version=self.taxonomy_version,
            prompt_version=review.prompt_version,
            model=review.model,
            provider=review.provider,
            estimated_cost_usd=provider_result.estimated_cost_usd,
            flags=review.risk_flags,
        )
        self.repository.save_decision(decision, line_hash)
        self.repository.record_audit(line.tenant_id, "canonicalization_review_created", {
            "decision_id": decision.decision_id,
            "review_id": review.review_id,
            "source_line_id": line.source_line_id,
            "decision_kind": decision_kind.value,
            "decision_score": decision_score,
        })
        self.metrics.increment("model_candidates_total")
        return decision

    def _abstain(
        self,
        line: InvoiceLine,
        normalized: str,
        line_hash: str,
        candidate_key: str,
        evidence: tuple[dict[str, object], ...],
        flags: list[str],
    ) -> CanonicalizationDecision:
        top_score = float(evidence[0].get("score", 0.0)) if evidence else 0.0
        review = self._create_review(
            line=line,
            candidate_key=candidate_key,
            proposed_description="Needs Product Review",
            proposed_category="unknown",
            attributes={}, evidence=evidence,
            decision_score=0.0, retrieval_score=top_score, retrieval_margin=0.0,
            llm_used=False, blocks_transaction=True, target_product_id=None,
            risk_flags=tuple(flags),
        )
        decision = CanonicalizationDecision(
            decision_id=str(uuid.uuid4()), tenant_id=line.tenant_id, partner_id=line.partner_id,
            source_line_id=line.source_line_id, input_description=line.description,
            normalized_description=normalized, decision_kind=DecisionKind.ABSTAINED,
            canonical_product_id=None, canonical_description=None, category=None,
            confidence=0.0, requires_human_review=True, review_id=review.review_id,
            evidence=evidence, taxonomy_version=self.taxonomy_version,
            prompt_version=None, model=None, provider=None, estimated_cost_usd=ZERO,
            flags=review.risk_flags,
        )
        self.repository.save_decision(decision, line_hash)
        self.metrics.increment("abstentions_total")
        return decision

    def _create_review(
        self,
        *,
        line: InvoiceLine,
        candidate_key: str,
        proposed_description: str,
        proposed_category: str,
        attributes: dict[str, str],
        evidence: tuple[dict[str, object], ...],
        decision_score: float,
        retrieval_score: float,
        retrieval_margin: float,
        llm_used: bool,
        blocks_transaction: bool,
        target_product_id: str | None,
        risk_flags: tuple[str, ...],
        prompt_version: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        review_id: str | None = None,
    ) -> ReviewRecord:
        review = ReviewRecord(
            review_id=review_id or str(uuid.uuid4()), tenant_id=line.tenant_id, partner_id=line.partner_id,
            candidate_key=candidate_key, source_description=line.description,
            source_variants=(line.description,), source_line_ids=(line.source_line_id,),
            occurrence_count=1, affected_value=abs(line.total or ZERO),
            affected_values_by_currency={line.currency or "UNSPECIFIED": abs(line.total or ZERO)},
            currency=line.currency,
            proposed_description=proposed_description, proposed_category=proposed_category,
            attributes=attributes, evidence=evidence, decision_score=decision_score,
            retrieval_score=retrieval_score, retrieval_margin=retrieval_margin,
            priority_score=0.0, llm_used=llm_used, blocks_transaction=blocks_transaction,
            risk_flags=risk_flags, prompt_version=prompt_version, model=model, provider=provider,
            target_product_id=target_product_id,
        )
        return self.repository.create_or_update_review(review)
