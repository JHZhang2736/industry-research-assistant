"""Convert claim-centered eval artifacts into final metric results."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable

from app.eval.artifacts import AtomicClaim, EvalArtifact
from app.eval.settings import PRICING_RMB_PER_M_TOKENS, REPORT_QUALITY_DIMENSIONS
from app.eval.types import EvalContext, EvalResult

_FALLBACK_INPUT = 2.0
_FALLBACK_OUTPUT = 6.0
_CLAIM_METRICS = (
    "claim_support_rate",
    "citation_verifiability",
    "relevance_coverage",
    "completeness",
)


class MetricCalculator:
    """Calculate deterministic eval metrics from an :class:`EvalArtifact`."""

    def calculate(self, ctx: EvalContext, artifact: EvalArtifact) -> list[EvalResult]:
        results: list[EvalResult] = []

        results.extend(
            [
                self._claim_metric_result(
                    artifact,
                    "claim_support_rate",
                    ("claim_extraction", "claim_verification"),
                    lambda: self._claim_support_rate(artifact),
                ),
                self._claim_metric_result(
                    artifact,
                    "citation_verifiability",
                    ("claim_extraction", "claim_verification"),
                    lambda: self._citation_verifiability(artifact),
                ),
                self._claim_metric_result(
                    artifact,
                    "relevance_coverage",
                    ("claim_extraction",),
                    lambda: self._relevance_coverage(artifact),
                ),
                self._claim_metric_result(
                    artifact,
                    "completeness",
                    ("claim_extraction", "claim_verification"),
                    lambda: self._completeness(artifact),
                ),
            ]
        )

        results.extend(self._quality_metrics(artifact))
        critic_loop = self._safe_result("critic_loop", lambda: self._critic_loop(ctx))
        results.extend(
            [
                critic_loop,
                EvalResult(
                    evaluator_name="critic_loop_effectiveness",
                    score=critic_loop.score,
                    raw_judge_outputs=critic_loop.raw_judge_outputs,
                    metadata=critic_loop.metadata,
                    error=critic_loop.error,
                    low_confidence=critic_loop.low_confidence,
                ),
                self._safe_result("cost", lambda: self._cost(ctx)),
                self._safe_result("latency", lambda: self._latency(ctx)),
            ]
        )
        return results

    def _claim_metric_result(
        self,
        artifact: EvalArtifact,
        evaluator_name: str,
        blocking_components: tuple[str, ...],
        calculate: Callable[[], EvalResult],
    ) -> EvalResult:
        blocking_errors = _component_errors(artifact.errors, blocking_components)
        if blocking_errors:
            return EvalResult(
                evaluator_name=evaluator_name,
                score=None,
                error="upstream artifact error: " + "; ".join(blocking_errors),
            )
        return self._safe_result(evaluator_name, calculate)

    def _safe_result(
        self,
        evaluator_name: str,
        calculate: Callable[[], EvalResult],
    ) -> EvalResult:
        try:
            return calculate()
        except Exception as exc:  # noqa: BLE001 - eval metrics must fail softly.
            return EvalResult(
                evaluator_name=evaluator_name,
                score=None,
                error=f"{evaluator_name} failed: {exc}",
            )

    def _claim_support_rate(self, artifact: EvalArtifact) -> EvalResult:
        verdicts = {verdict.claim_id: verdict for verdict in artifact.verdicts}
        high_confidence = [
            claim
            for claim in artifact.claims
            if (verdicts.get(claim.id) and verdicts[claim.id].confidence == "high")
            or getattr(claim, "confidence", None) == "high"
        ]
        claims = high_confidence or artifact.claims
        if not claims:
            return EvalResult(
                evaluator_name="claim_support_rate",
                score=None,
                error="no applicable claims for claim support rate",
            )

        supported = sum(
            1
            for claim in claims
            if verdicts.get(claim.id) and verdicts[claim.id].supported
        )
        score = round((supported / len(claims)) * 10, 2)
        return EvalResult(
            evaluator_name="claim_support_rate",
            score=score,
            metadata={
                "supported": supported,
                "total_claims": len(claims),
                "used_high_confidence_claims": bool(high_confidence),
            },
        )

    def _citation_verifiability(self, artifact: EvalArtifact) -> EvalResult:
        cited_claims = [
            claim for claim in artifact.claims if _as_list(claim.citation_ids)
        ]
        if not cited_claims:
            return EvalResult(
                evaluator_name="citation_verifiability",
                score=None,
                error="no cited claims for citation verifiability",
            )

        evidence_ids = {_normalize_id(item.id) for item in artifact.evidence}
        verdicts = {verdict.claim_id: verdict for verdict in artifact.verdicts}
        normalized_citations = [
            _normalize_id(citation_id)
            for claim in cited_claims
            for citation_id in _as_list(claim.citation_ids)
        ]

        known_citations = [
            citation_id
            for citation_id in normalized_citations
            if citation_id in evidence_ids
        ]
        supported_cited = sum(
            1
            for claim in cited_claims
            if verdicts.get(claim.id) and verdicts[claim.id].supported
        )

        overlap_hits = 0
        overlap_total = 0
        for claim in cited_claims:
            claim_citations = {
                _normalize_id(citation_id)
                for citation_id in _as_list(claim.citation_ids)
                if _normalize_id(citation_id) in evidence_ids
            }
            if not claim_citations:
                continue
            verdict_evidence = {
                _normalize_id(evidence_id)
                for evidence_id in (
                    _as_list(verdicts.get(claim.id).evidence_ids)
                    if verdicts.get(claim.id)
                    else []
                )
            }
            overlap_hits += len(claim_citations & verdict_evidence)
            overlap_total += len(claim_citations)

        known_rate = len(known_citations) / len(normalized_citations) if normalized_citations else 0.0
        supported_rate = supported_cited / len(cited_claims)
        overlap_rate = overlap_hits / overlap_total if overlap_total else 0.0
        score = round(((known_rate + supported_rate + overlap_rate) / 3) * 10, 2)

        return EvalResult(
            evaluator_name="citation_verifiability",
            score=score,
            metadata={
                "known_citation_rate": known_rate,
                "supported_cited_claim_rate": supported_rate,
                "citation_evidence_overlap_rate": overlap_rate,
                "known_citations": len(known_citations),
                "total_citations": len(normalized_citations),
                "cited_claims": len(cited_claims),
            },
        )

    def _relevance_coverage(self, artifact: EvalArtifact) -> EvalResult:
        requirement_ids = {requirement.id for requirement in artifact.requirements}
        if not requirement_ids:
            return EvalResult(
                evaluator_name="relevance_coverage",
                score=None,
                error="no requirements for relevance coverage",
            )

        covered = _covered_requirement_ids(artifact.claims) & requirement_ids
        score = round((len(covered) / len(requirement_ids)) * 10, 2)
        return EvalResult(
            evaluator_name="relevance_coverage",
            score=score,
            metadata={
                "covered_requirements": sorted(covered),
                "total_requirements": len(requirement_ids),
            },
        )

    def _completeness(self, artifact: EvalArtifact) -> EvalResult:
        high_importance = [
            requirement
            for requirement in artifact.requirements
            if str(requirement.importance or "").lower() == "high"
        ]
        requirements = high_importance or artifact.requirements
        if not requirements:
            return EvalResult(
                evaluator_name="completeness",
                score=None,
                error="no applicable requirements for completeness",
            )

        supported_claim_ids = {
            verdict.claim_id for verdict in artifact.verdicts if verdict.supported
        }
        supported_claims = [claim for claim in artifact.claims if claim.id in supported_claim_ids]
        requirement_ids = {requirement.id for requirement in requirements}
        covered = _covered_requirement_ids(supported_claims) & requirement_ids
        score = round((len(covered) / len(requirement_ids)) * 10, 2)
        return EvalResult(
            evaluator_name="completeness",
            score=score,
            metadata={
                "covered_requirements": sorted(covered),
                "total_requirements": len(requirement_ids),
                "used_high_importance_requirements": bool(high_importance),
            },
        )

    def _quality_metrics(self, artifact: EvalArtifact) -> list[EvalResult]:
        results: list[EvalResult] = []
        quality = artifact.quality
        raw_judge_outputs = (
            quality.raw_judge_outputs
            if isinstance(getattr(quality, "raw_judge_outputs", None), list)
            else []
        )
        std_by_dimension = (
            quality.std_by_dimension
            if isinstance(getattr(quality, "std_by_dimension", None), dict)
            else {}
        )
        low_confidence_dimensions = (
            quality.low_confidence_dimensions
            if isinstance(
                getattr(quality, "low_confidence_dimensions", None),
                (list, tuple, set),
            )
            else set()
        )
        partial = bool(getattr(quality, "partial", False))
        quality_error = getattr(quality, "error", None)

        for dimension in REPORT_QUALITY_DIMENSIONS:
            score = getattr(quality, dimension, None)
            if score is None:
                results.append(
                    EvalResult(
                        evaluator_name=dimension,
                        score=None,
                        raw_judge_outputs=raw_judge_outputs,
                        metadata={"partial": partial},
                        error=f"missing quality score for {dimension}",
                        low_confidence=dimension in low_confidence_dimensions,
                    )
                )
                continue

            results.append(
                EvalResult(
                    evaluator_name=dimension,
                    score=score,
                    raw_judge_outputs=raw_judge_outputs,
                    metadata={
                        "std": std_by_dimension.get(dimension),
                        "partial": partial,
                    },
                    error=quality_error,
                    low_confidence=dimension in low_confidence_dimensions,
                )
            )
        return results

    def _critic_loop(self, ctx: EvalContext) -> EvalResult:
        feedback = ctx.state.get("critic_feedback") or []
        total = len(feedback)
        iterations = int(ctx.state.get("iteration") or 0)
        quality = float(ctx.state.get("quality_score") or 0.0)
        if total == 0:
            return EvalResult(
                evaluator_name="critic_loop",
                score=None,
                metadata={
                    "total_feedback": 0,
                    "resolution_rate": None,
                    "iterations": iterations,
                    "final_quality_score": quality,
                    "note": "no critic feedback recorded",
                },
            )

        resolved = sum(1 for item in feedback if item.get("resolved") is True)
        rate = resolved / total
        return EvalResult(
            evaluator_name="critic_loop",
            score=round(rate * 10, 2),
            metadata={
                "total_feedback": total,
                "resolved": resolved,
                "resolution_rate": round(rate, 3),
                "iterations": iterations,
                "final_quality_score": quality,
                "severity_breakdown": {
                    "critical": sum(
                        1 for item in feedback if item.get("severity") == "critical"
                    ),
                    "major": sum(
                        1 for item in feedback if item.get("severity") == "major"
                    ),
                    "minor": sum(
                        1 for item in feedback if item.get("severity") == "minor"
                    ),
                },
            },
        )

    def _cost(self, ctx: EvalContext) -> EvalResult:
        total_tokens = 0
        rmb = 0.0
        unknown_models: list[str] = []

        for log in ctx.state.get("logs") or []:
            tokens = int(log.get("tokens_used") or 0)
            total_tokens += tokens
            model = log.get("model") or "unknown"
            pricing = PRICING_RMB_PER_M_TOKENS.get(model)
            if pricing is None:
                if model not in unknown_models:
                    unknown_models.append(model)
                input_price, output_price = _FALLBACK_INPUT, _FALLBACK_OUTPUT
            else:
                input_price, output_price = pricing
            half = tokens / 2
            rmb += (half * input_price + half * output_price) / 1_000_000

        return EvalResult(
            evaluator_name="cost",
            score=round(rmb, 4),
            metadata={
                "total_tokens": total_tokens,
                "rmb": round(rmb, 4),
                "unknown_models": unknown_models,
            },
        )

    def _latency(self, ctx: EvalContext) -> EvalResult:
        total = ctx.duration_sec
        per_agent: dict[str, float] = defaultdict(float)
        for log in ctx.state.get("logs") or []:
            agent = log.get("agent") or "unknown"
            per_agent[agent] += (log.get("duration_ms") or 0) / 1000.0

        return EvalResult(
            evaluator_name="latency",
            score=round(total, 1),
            metadata={
                "total_sec": round(total, 1),
                "per_agent_sec": {
                    key: round(value, 1) for key, value in per_agent.items()
                },
            },
        )


def _covered_requirement_ids(claims: list[AtomicClaim]) -> set[str]:
    return {
        requirement_id
        for claim in claims
        for requirement_id in _as_list(claim.requirement_ids)
    }


def _component_errors(errors: list[str] | None, components: tuple[str, ...]) -> list[str]:
    prefixes = tuple(f"{component}:" for component in components)
    return [error for error in (errors or []) if str(error).startswith(prefixes)]


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, str):
        return [value]
    raise TypeError(f"expected list-like value, got {type(value).__name__}")


def _normalize_id(value: str) -> str:
    normalized = str(value).strip().lower()
    normalized = normalized.strip("[](){}")
    normalized = normalized.replace("-", "_")
    match = re.fullmatch(r"(?:ref|source|evidence|citation)_?(\d+)", normalized)
    if match:
        return match.group(1)
    return normalized
