"""Orchestrate claim-centered eval artifact construction."""
from __future__ import annotations

from typing import Any

from app.eval.artifact_builders.claim_extraction import ClaimExtractionBuilder
from app.eval.artifact_builders.claim_verification import ClaimVerificationBuilder
from app.eval.artifact_builders.evidence import EvidenceIndexBuilder
from app.eval.artifact_builders.report_quality import ReportQualityBuilder
from app.eval.artifact_builders.report_structure import parse_report_sections
from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    EvalArtifact,
    QueryRequirement,
    ReportQualityScores,
)
from app.eval.types import EvalContext


class EvalArtifactBuilder:
    """Build a unified eval artifact from a completed eval context."""

    def __init__(self) -> None:
        self.evidence_index = EvidenceIndexBuilder()
        self.claim_extractor = ClaimExtractionBuilder()
        self.claim_verifier = ClaimVerificationBuilder()
        self.report_quality = ReportQualityBuilder()

    async def build(self, ctx: EvalContext, judge: Any) -> EvalArtifact:
        evidence = self.evidence_index.build(ctx.state)
        sections = parse_report_sections(ctx.state.get("final_report") or "")
        errors: list[str] = []
        requirements: list[QueryRequirement] = []
        claims: list[AtomicClaim] = []
        verdicts: list[ClaimVerdict] = []

        try:
            requirements, claims = await self.claim_extractor.build(
                ctx.case.query,
                sections,
                judge,
            )
        except Exception as exc:
            errors.append(f"claim_extraction: {exc}")

        if claims:
            try:
                verdicts = await self.claim_verifier.build(claims, evidence, judge)
            except Exception as exc:
                errors.append(f"claim_verification: {exc}")

        try:
            quality = await self.report_quality.build(
                ctx.case.query,
                sections,
                claims,
                verdicts,
                judge,
            )
        except Exception as exc:
            errors.append(f"report_quality: {exc}")
            quality = ReportQualityScores(error=str(exc), partial=True)

        return EvalArtifact(
            evidence=evidence,
            sections=sections,
            requirements=requirements,
            claims=claims,
            verdicts=verdicts,
            quality=quality,
            errors=errors,
        )
