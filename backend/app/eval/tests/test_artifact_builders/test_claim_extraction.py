from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builders.claim_extraction import ClaimExtractionBuilder
from app.eval.artifacts import ReportSection
from app.eval.types import StructuredJudgeResult


@pytest.mark.asyncio
async def test_claim_extraction_builder_parses_requirements_and_claims():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"requirements":[{"id":"r1","text":"market size","importance":"high"}],"claims":[{"id":"c1","text":"Sales reached 9.5 million.","section_id":"s1","importance":"high","citation_ids":["1"],"requirement_ids":["r1"]}]}',
    ))
    sections = [ReportSection(id="s1", title="Market", text="Sales reached 9.5 million [1].", citation_ids=["1"])]

    requirements, claims = await ClaimExtractionBuilder(max_claims=10).build(
        query="Analyze market size",
        sections=sections,
        judge=judge,
    )

    assert requirements[0].id == "r1"
    assert claims[0].citation_ids == ["1"]
    assert claims[0].requirement_ids == ["r1"]


@pytest.mark.asyncio
async def test_claim_extraction_builder_defaults_sparse_items():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"requirements":[{"text":" market size "}],"claims":[{"text":" Sales grew. "}]}',
    ))

    requirements, claims = await ClaimExtractionBuilder(max_claims=10).build(
        query="Analyze market size",
        sections=[],
        judge=judge,
    )

    assert requirements[0].id == "r1"
    assert requirements[0].text == "market size"
    assert requirements[0].importance == "medium"
    assert claims[0].id == "c1"
    assert claims[0].text == "Sales grew."
    assert claims[0].importance == "medium"
    assert claims[0].citation_ids == []
    assert claims[0].requirement_ids == []


@pytest.mark.asyncio
async def test_claim_extraction_builder_rejects_bad_json():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult("qwen", "not json"))

    with pytest.raises(ValueError, match="could not parse"):
        await ClaimExtractionBuilder().build("query", [], judge)
