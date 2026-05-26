"""Test RelevanceEvaluator. Judge is mocked."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.evaluators.relevance import RelevanceEvaluator
from app.eval.types import EnsembleResult, EvalCase, EvalContext, JudgeScore


def make_ctx() -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="新能源汽车2024年市场", category="汽车", difficulty="easy"),
        state={"final_report": "## 市场规模\n2024 年销量增长 30%..."},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )


@pytest.mark.asyncio
async def test_relevance_happy_path():
    mock_judge = AsyncMock()
    mock_judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=8.0,
        median_score=8.0,
        std=0.5,
        individual=[JudgeScore("a", 8, "ok"), JudgeScore("b", 8, "ok"), JudgeScore("c", 8, "ok")],
        low_confidence=False,
        partial=False,
    ))
    res = await RelevanceEvaluator().evaluate(make_ctx(), mock_judge)
    assert res.score == 8.0
    assert res.low_confidence is False
    mock_judge.score.assert_awaited_once()


@pytest.mark.asyncio
async def test_relevance_no_report_returns_error():
    mock_judge = AsyncMock()
    ctx = EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"final_report": ""},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await RelevanceEvaluator().evaluate(ctx, mock_judge)
    assert res.score is None
    assert res.error is not None


@pytest.mark.asyncio
async def test_relevance_propagates_low_confidence():
    mock_judge = AsyncMock()
    mock_judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=6.0,
        median_score=6.0,
        std=3.0,
        individual=[JudgeScore("a", 3, ""), JudgeScore("b", 9, ""), JudgeScore("c", 6, "")],
        low_confidence=True,
        partial=False,
    ))
    res = await RelevanceEvaluator().evaluate(make_ctx(), mock_judge)
    assert res.low_confidence is True
