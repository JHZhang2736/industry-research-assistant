"""Test CoherenceEvaluator (mocked judge)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.evaluators.coherence import CoherenceEvaluator
from app.eval.types import EnsembleResult, EvalCase, EvalContext, JudgeScore


@pytest.mark.asyncio
async def test_coherence_happy_path():
    judge = AsyncMock()
    judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=7.5, median_score=7.5, std=0.3,
        individual=[JudgeScore("a", 7.5, "ok"), JudgeScore("b", 7.5, "ok"), JudgeScore("c", 7.5, "ok")],
        low_confidence=False, partial=False,
    ))
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={"final_report": "## 段一\n内容。\n\n## 段二\n内容。"},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CoherenceEvaluator().evaluate(ctx, judge)
    assert res.score == 7.5


@pytest.mark.asyncio
async def test_coherence_empty_report_error():
    judge = AsyncMock()
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={"final_report": ""},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CoherenceEvaluator().evaluate(ctx, judge)
    assert res.score is None
    assert res.error is not None
