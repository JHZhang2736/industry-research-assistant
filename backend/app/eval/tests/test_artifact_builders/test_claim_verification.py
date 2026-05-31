from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builders.claim_verification import ClaimVerificationBuilder
from app.eval.artifacts import AtomicClaim, EvidenceItem
from app.eval.types import StructuredJudgeResult


@pytest.mark.asyncio
async def test_claim_verification_builder_parses_verdicts():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"verdicts":[{"claim_id":"c1","supported":true,"reason":"supported","evidence_ids":["f1"],"confidence":"high"}]}',
    ))
    claims = [AtomicClaim(id="c1", text="Sales reached 9.5 million.")]
    evidence = [EvidenceItem(id="f1", text="Sales reached 9.5 million.", source_name="CAAM")]

    verdicts = await ClaimVerificationBuilder().build(claims, evidence, judge)

    assert verdicts[0].claim_id == "c1"
    assert verdicts[0].supported is True
    assert verdicts[0].evidence_ids == ["f1"]


@pytest.mark.asyncio
async def test_claim_verification_builder_marks_missing_verdicts_unsupported():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"verdicts":[]}',
    ))
    claims = [AtomicClaim(id="c1", text="Unsupported claim.")]

    verdicts = await ClaimVerificationBuilder().build(claims, [], judge)

    assert verdicts[0].claim_id == "c1"
    assert verdicts[0].supported is False
    assert verdicts[0].reason == "judge omitted verdict"
