from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builder import EvalArtifactBuilder
from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    QueryRequirement,
    ReportQualityScores,
)
from app.eval.types import EvalCase, EvalContext


def make_context() -> EvalContext:
    return EvalContext(
        case=EvalCase(
            id="q1",
            query="Analyze market size",
            category="auto",
            difficulty="easy",
        ),
        state={
            "final_report": "## Market\nSales reached 9.5 million [1].",
            "facts": [
                {
                    "id": "f1",
                    "content": "Sales reached 9.5 million.",
                    "source_url": "https://example.com",
                }
            ],
        },
        started_at=datetime(2026, 5, 31),
        finished_at=datetime(2026, 5, 31),
    )


@pytest.mark.asyncio
async def test_artifact_builder_builds_claim_centered_artifact():
    builder = EvalArtifactBuilder()
    builder.claim_extractor.build = AsyncMock(
        return_value=(
            [QueryRequirement(id="r1", text="market size", importance="high")],
            [
                AtomicClaim(
                    id="c1",
                    text="Sales reached 9.5 million.",
                    section_id="s1",
                    importance="high",
                    citation_ids=["1"],
                    requirement_ids=["r1"],
                )
            ],
        )
    )
    builder.claim_verifier.build = AsyncMock(
        return_value=[
            ClaimVerdict(
                claim_id="c1",
                supported=True,
                reason="supported",
                evidence_ids=["f1"],
                confidence="high",
            )
        ]
    )
    builder.report_quality.build = AsyncMock(
        return_value=ReportQualityScores(coherence=8.0)
    )

    artifact = await builder.build(make_context(), judge=AsyncMock())

    assert artifact.evidence[0].id == "f1"
    assert artifact.sections[0].id == "s1"
    assert artifact.claims[0].id == "c1"
    assert artifact.verdicts[0].supported is True
    assert artifact.quality.coherence == 8.0


@pytest.mark.asyncio
async def test_artifact_builder_fail_soft_when_claim_extraction_raises():
    builder = EvalArtifactBuilder()
    builder.claim_extractor.build = AsyncMock(side_effect=RuntimeError("extract boom"))
    builder.claim_verifier.build = AsyncMock()
    builder.report_quality.build = AsyncMock(
        return_value=ReportQualityScores(coherence=7.0)
    )

    artifact = await builder.build(make_context(), judge=AsyncMock())

    assert artifact.evidence[0].id == "f1"
    assert artifact.sections[0].id == "s1"
    assert artifact.errors == ["claim_extraction: extract boom"]
    assert artifact.requirements == []
    assert artifact.claims == []
    assert artifact.verdicts == []
    builder.claim_verifier.build.assert_not_awaited()
    builder.report_quality.build.assert_awaited_once()
    assert builder.report_quality.build.await_args.args[2] == []
    assert builder.report_quality.build.await_args.args[3] == []


@pytest.mark.asyncio
async def test_artifact_builder_fail_soft_when_claim_verification_raises():
    builder = EvalArtifactBuilder()
    claims = [
        AtomicClaim(
            id="c1",
            text="Sales reached 9.5 million.",
            section_id="s1",
            importance="high",
        )
    ]
    builder.claim_extractor.build = AsyncMock(
        return_value=([QueryRequirement("r1", "market size", "high")], claims)
    )
    builder.claim_verifier.build = AsyncMock(side_effect=RuntimeError("verify boom"))
    builder.report_quality.build = AsyncMock(
        return_value=ReportQualityScores(coherence=6.0)
    )

    artifact = await builder.build(make_context(), judge=AsyncMock())

    assert artifact.claims == claims
    assert artifact.errors == ["claim_verification: verify boom"]
    assert artifact.verdicts == []
    builder.report_quality.build.assert_awaited_once()
    assert builder.report_quality.build.await_args.args[2] == claims
    assert builder.report_quality.build.await_args.args[3] == []


@pytest.mark.asyncio
async def test_artifact_builder_fail_soft_when_report_quality_raises():
    builder = EvalArtifactBuilder()
    claims = [
        AtomicClaim(
            id="c1",
            text="Sales reached 9.5 million.",
            section_id="s1",
            importance="high",
        )
    ]
    builder.claim_extractor.build = AsyncMock(return_value=([], claims))
    builder.claim_verifier.build = AsyncMock(
        return_value=[ClaimVerdict("c1", True, "supported")]
    )
    builder.report_quality.build = AsyncMock(side_effect=RuntimeError("quality boom"))

    artifact = await builder.build(make_context(), judge=AsyncMock())

    assert artifact.errors == ["report_quality: quality boom"]
    assert type(artifact.quality) is ReportQualityScores
    assert artifact.quality.partial is True
    assert artifact.quality.error == "quality boom"
