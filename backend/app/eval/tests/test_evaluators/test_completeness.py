"""Test CompletenessEvaluator."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.evaluators.completeness import CompletenessEvaluator
from app.eval.types import EnsembleResult, EvalCase, EvalContext, JudgeScore


@pytest.mark.asyncio
async def test_completeness_happy_path():
    judge = AsyncMock()
    judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=8.0, median_score=8.0, std=0.5,
        individual=[JudgeScore("a", 8, ""), JudgeScore("b", 8, ""), JudgeScore("c", 8, "")],
        low_confidence=False, partial=False,
    ))
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={
            "outline": [{"id": "s1", "title": "A"}, {"id": "s2", "title": "B"}],
            "final_report": "## A\n内容...\n\n## B\n内容...",
        },
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CompletenessEvaluator().evaluate(ctx, judge)
    assert res.score == 8.0


@pytest.mark.asyncio
async def test_completeness_no_outline_returns_error():
    judge = AsyncMock()
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={"outline": [], "final_report": "..."},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CompletenessEvaluator().evaluate(ctx, judge)
    assert res.score is None
    assert res.error is not None
