"""Test EnsembleJudge aggregation + failure handling."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.judges.ensemble import EnsembleJudge
from app.eval.types import JudgeScore


class FakeClient:
    def __init__(self, name: str, score: float | None, failed: bool = False):
        self.cfg_name = name
        self._score = score
        self._failed = failed

    async def call_judge(self, prompt: str) -> JudgeScore:
        return JudgeScore(
            judge_name=self.cfg_name,
            score=self._score,
            reasoning="r",
            failed=self._failed,
            error=("e" if self._failed else None),
        )


@pytest.mark.asyncio
async def test_ensemble_all_succeed_mean_median_std():
    e = EnsembleJudge([FakeClient("a", 6.0), FakeClient("b", 8.0), FakeClient("c", 7.0)])
    r = await e.score("any prompt")
    assert r.mean_score == 7.0
    assert r.median_score == 7.0
    assert r.std == pytest.approx(1.0, abs=0.1)
    assert r.partial is False
    assert r.low_confidence is False
    assert len(r.individual) == 3


@pytest.mark.asyncio
async def test_ensemble_one_judge_fails_partial_true():
    e = EnsembleJudge([
        FakeClient("a", 6.0),
        FakeClient("b", None, failed=True),
        FakeClient("c", 8.0),
    ])
    r = await e.score("p")
    assert r.partial is True
    assert r.mean_score == 7.0
    assert len(r.individual) == 3  # individual still has all three


@pytest.mark.asyncio
async def test_ensemble_all_fail_score_none():
    e = EnsembleJudge([
        FakeClient("a", None, failed=True),
        FakeClient("b", None, failed=True),
        FakeClient("c", None, failed=True),
    ])
    r = await e.score("p")
    assert r.mean_score is None
    assert r.error is not None
    assert r.partial is True


@pytest.mark.asyncio
async def test_ensemble_high_variance_marks_low_confidence():
    e = EnsembleJudge([FakeClient("a", 3.0), FakeClient("b", 9.0), FakeClient("c", 5.0)])
    r = await e.score("p")
    assert r.std > 2.0
    assert r.low_confidence is True


@pytest.mark.asyncio
async def test_ensemble_single_judge_std_zero():
    e = EnsembleJudge([FakeClient("a", 7.0)])
    r = await e.score("p")
    assert r.std == 0
    assert r.low_confidence is False
