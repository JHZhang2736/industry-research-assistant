from __future__ import annotations

import json
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


def make_payload(**scores: float | str) -> str:
    dimensions = {
        "coherence": 8,
        "cohesion_structure": 8,
        "analytical_depth": 8,
        "professionalism_readability": 8,
        "decision_usefulness": 8,
    }
    dimensions.update(scores)
    return json.dumps(
        {
            dimension: {"score": score, "reasoning": "ok"}
            for dimension, score in dimensions.items()
            if score != "OMIT"
        }
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


@pytest.mark.asyncio
async def test_report_quality_builder_marks_missing_and_bad_dimensions_partial():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult(
                "deepseek",
                make_payload(coherence=7, analytical_depth="bad"),
            ),
            StructuredJudgeResult(
                "qwen",
                make_payload(coherence=9, cohesion_structure="OMIT"),
            ),
        ]
    )

    quality = await ReportQualityBuilder(weights={"deepseek": 0.5, "qwen": 0.5}).build(
        query="q",
        sections=[],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.coherence == pytest.approx(8.0)
    assert quality.professionalism_readability == pytest.approx(8.0)
    assert quality.partial is True
    assert quality.raw_judge_outputs[0]["invalid_dimensions"] == ["analytical_depth"]
    assert quality.raw_judge_outputs[1]["missing_dimensions"] == ["cohesion_structure"]


@pytest.mark.asyncio
async def test_report_quality_builder_marks_high_variance_low_confidence():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("deepseek", make_payload(coherence=0)),
            StructuredJudgeResult("qwen", make_payload(coherence=10)),
        ]
    )

    quality = await ReportQualityBuilder(weights={"deepseek": 0.5, "qwen": 0.5}).build(
        query="q",
        sections=[],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.std_by_dimension["coherence"] > 2.0
    assert "coherence" in quality.low_confidence_dimensions


@pytest.mark.asyncio
async def test_report_quality_builder_single_valid_score_has_zero_std():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("deepseek", "", failed=True, error="timeout"),
            StructuredJudgeResult("qwen", make_payload(coherence=8)),
        ]
    )

    quality = await ReportQualityBuilder(weights={"deepseek": 0.5, "qwen": 0.5}).build(
        query="q",
        sections=[],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.std_by_dimension["coherence"] == 0
    assert "coherence" not in quality.low_confidence_dimensions


@pytest.mark.asyncio
async def test_report_quality_builder_unknown_judge_defaults_to_weight_one():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("deepseek", make_payload(coherence=2)),
            StructuredJudgeResult("unknown", make_payload(coherence=8)),
        ]
    )

    quality = await ReportQualityBuilder(weights={"deepseek": 0.0}).build(
        query="q",
        sections=[],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.coherence == 8.0


@pytest.mark.asyncio
async def test_report_quality_builder_all_zero_weights_produce_none_and_partial():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("deepseek", make_payload(coherence=2)),
            StructuredJudgeResult("qwen", make_payload(coherence=8)),
        ]
    )

    quality = await ReportQualityBuilder(weights={"deepseek": 0.0, "qwen": 0.0}).build(
        query="q",
        sections=[],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.coherence is None
    assert quality.partial is True
    assert "coherence" in quality.raw_judge_outputs[0]["weight_error_dimensions"]
    assert "coherence" in quality.raw_judge_outputs[1]["weight_error_dimensions"]


@pytest.mark.asyncio
async def test_report_quality_builder_prompt_format_handles_literal_braces():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("qwen", make_payload()),
        ]
    )

    quality = await ReportQualityBuilder().build(
        query="Analyze {market}",
        sections=[ReportSection("s1", "Market", "Text with {literal}", [])],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.coherence == 8.0


@pytest.mark.asyncio
async def test_report_quality_builder_invalid_json_marks_partial_and_uses_valid_judge():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("deepseek", "not json"),
            StructuredJudgeResult("qwen", make_payload(coherence=8)),
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
    assert quality.raw_judge_outputs[0]["failed"] is True
