from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builders.report_quality import ReportQualityBuilder
from app.eval.artifacts import AtomicClaim, ClaimVerdict, ReportSection
from app.eval.types import StructuredJudgeResult


def make_claim(claim_id: str = "c1", text: str = "Claim") -> AtomicClaim:
    return AtomicClaim(
        id=claim_id,
        text=text,
        section_id=None,
        importance="medium",
        citation_ids=[],
        requirement_ids=[],
    )


@pytest.mark.asyncio
async def test_report_quality_builder_aggregates_weighted_scores():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult(
                "deepseek",
                '{"coherence":{"score":8,"reasoning":"ok"},"cohesion_structure":{"score":7,"reasoning":"ok"},"analytical_depth":{"score":8,"reasoning":"ok"},"professionalism_readability":{"score":9,"reasoning":"ok"},"decision_usefulness":{"score":7,"reasoning":"ok"}}',
            ),
            StructuredJudgeResult(
                "qwen",
                '{"coherence":{"score":9,"reasoning":"ok"},"cohesion_structure":{"score":8,"reasoning":"ok"},"analytical_depth":{"score":8,"reasoning":"ok"},"professionalism_readability":{"score":8,"reasoning":"ok"},"decision_usefulness":{"score":8,"reasoning":"ok"}}',
            ),
            StructuredJudgeResult(
                "mimo",
                '{"coherence":{"score":6,"reasoning":"ok"},"cohesion_structure":{"score":6,"reasoning":"ok"},"analytical_depth":{"score":7,"reasoning":"ok"},"professionalism_readability":{"score":7,"reasoning":"ok"},"decision_usefulness":{"score":6,"reasoning":"ok"}}',
            ),
        ]
    )

    quality = await ReportQualityBuilder(
        weights={"deepseek": 0.4, "qwen": 0.4, "mimo": 0.2}
    ).build(
        query="Analyze market",
        sections=[ReportSection("s1", "Market", "Text", [])],
        claims=[make_claim()],
        verdicts=[ClaimVerdict("c1", True, "")],
        judge=judge,
    )

    assert quality.coherence == pytest.approx(8.0)
    assert quality.cohesion_structure == pytest.approx(7.2)
    assert quality.partial is False
    assert quality.raw_judge_outputs[0]["judge"] == "deepseek"


@pytest.mark.asyncio
async def test_report_quality_builder_skips_failed_judge():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("deepseek", "", failed=True, error="timeout"),
            StructuredJudgeResult("qwen", '{"coherence":{"score":8,"reasoning":"ok"}}'),
        ]
    )

    quality = await ReportQualityBuilder(weights={"deepseek": 0.5, "qwen": 0.5}).build(
        query="q",
        sections=[],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.coherence == 8.0
    assert quality.partial is True
