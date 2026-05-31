"""Convert claim-centered eval artifacts into final metric results."""
from __future__ import annotations

import re
from collections import defaultdict

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

        if artifact.errors:
            error = "upstream artifact error: " + "; ".join(artifact.errors)
            results.extend(
                EvalResult(evaluator_name=name, score=None, error=error)
                for name in _CLAIM_METRICS
            )
        else:
            results.extend(
                [
                    self._claim_support_rate(artifact),
                    self._citation_verifiability(artifact),
                    self._relevance_coverage(artifact),
                    self._completeness(artifact),
                ]
            )

        results.extend(self._quality_metrics(artifact))
        results.extend(
            [
                self._critic_loop_effectiveness(ctx),
                self._cost(ctx),
                self._latency(ctx),
            ]
        )
        return results

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
        cited_claims = [claim for claim in artifact.claims if claim.citation_ids]
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
            for citation_id in claim.citation_ids
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
                for citation_id in claim.citation_ids
                if _normalize_id(citation_id) in evidence_ids
            }
            if not claim_citations:
                continue
            verdict_evidence = {
                _normalize_id(evidence_id)
                for evidence_id in (
                    verdicts.get(claim.id).evidence_ids
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
            if requirement.importance.lower() == "high"
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
        for dimension in REPORT_QUALITY_DIMENSIONS:
            score = getattr(quality, dimension)
            if score is None:
                results.append(
                    EvalResult(
                        evaluator_name=dimension,
                        score=None,
                        raw_judge_outputs=quality.raw_judge_outputs,
                        metadata={"partial": quality.partial},
                        error=f"missing quality score for {dimension}",
                        low_confidence=dimension in quality.low_confidence_dimensions,
                    )
                )
                continue

            results.append(
                EvalResult(
                    evaluator_name=dimension,
                    score=score,
                    raw_judge_outputs=quality.raw_judge_outputs,
                    metadata={
                        "std": quality.std_by_dimension.get(dimension),
                        "partial": quality.partial,
                    },
                    error=quality.error,
                    low_confidence=dimension in quality.low_confidence_dimensions,
                )
            )
        return results

    def _critic_loop_effectiveness(self, ctx: EvalContext) -> EvalResult:
        feedback = ctx.state.get("critic_feedback") or []
        total = len(feedback)
        iterations = int(ctx.state.get("iteration") or 0)
        quality = float(ctx.state.get("quality_score") or 0.0)
        if total == 0:
            return EvalResult(
                evaluator_name="critic_loop_effectiveness",
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
            evaluator_name="critic_loop_effectiveness",
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
    return {requirement_id for claim in claims for requirement_id in claim.requirement_ids}


def _normalize_id(value: str) -> str:
    normalized = str(value).strip().lower()
    normalized = normalized.strip("[](){}")
    normalized = normalized.replace("-", "_")
    match = re.fullmatch(r"(?:ref|source|evidence|citation)_?(\d+)", normalized)
    if match:
        return match.group(1)
    return normalized
