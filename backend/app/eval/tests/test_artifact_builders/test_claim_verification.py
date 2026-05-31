from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builders.claim_verification import ClaimVerificationBuilder
from app.eval.artifacts import AtomicClaim, EvidenceItem
from app.eval.types import StructuredJudgeResult


def test_claim_verification_import_does_not_mutate_artifact_constructors():
    assert len(AtomicClaim.__init__.__defaults__ or ()) == 2
    assert len(EvidenceItem.__init__.__defaults__ or ()) == 1


@pytest.mark.asyncio
async def test_claim_verification_builder_parses_verdicts():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"verdicts":[{"claim_id":"c1","supported":true,"reason":"supported","evidence_ids":["f1"],"confidence":"high"}]}',
    ))
    claims = [
        AtomicClaim(
            id="c1",
            text="Sales reached 9.5 million.",
            section_id=None,
            importance="medium",
            citation_ids=[],
            requirement_ids=[],
        )
    ]
    evidence = [
        EvidenceItem(
            id="f1",
            text="Sales reached 9.5 million.",
            source_name="CAAM",
            source_url="",
            source_type="",
        )
    ]

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
    claims = [
        AtomicClaim(
            id="c1",
            text="Unsupported claim.",
            section_id=None,
            importance="medium",
            citation_ids=[],
            requirement_ids=[],
        )
    ]

    verdicts = await ClaimVerificationBuilder().build(claims, [], judge)

    assert verdicts[0].claim_id == "c1"
    assert verdicts[0].supported is False
    assert verdicts[0].reason == "judge omitted verdict"


@pytest.mark.asyncio
async def test_claim_verification_builder_skips_malformed_verdicts():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"verdicts":[{"supported":true,"reason":"missing id"},{"claim_id":"unknown","supported":true,"reason":"unknown claim"},{"claim_id":"c1","supported":"false","reason":"not supported","evidence_ids":["f1"]}]}',
    ))
    claims = [
        AtomicClaim(
            id="c1",
            text="Unsupported claim.",
            section_id=None,
            importance="medium",
            citation_ids=[],
            requirement_ids=[],
        )
    ]

    verdicts = await ClaimVerificationBuilder().build(claims, [], judge)

    assert verdicts[0].claim_id == "c1"
    assert verdicts[0].supported is False
    assert verdicts[0].reason == "not supported"
