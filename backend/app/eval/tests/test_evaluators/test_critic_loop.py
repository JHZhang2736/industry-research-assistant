"""Test CriticLoopEvaluator."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.critic_loop import CriticLoopEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(feedback: list[dict], iteration: int = 1, quality: float = 7.5) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={
            "critic_feedback": feedback,
            "iteration": iteration,
            "quality_score": quality,
        },
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )


@pytest.mark.asyncio
async def test_critic_no_feedback_score_none():
    res = await CriticLoopEvaluator().evaluate(make_ctx([]), judge=None)
    assert res.score is None
    assert res.metadata["total_feedback"] == 0


@pytest.mark.asyncio
async def test_critic_resolution_rate_half():
    fb = [
        {"id": "c1", "severity": "minor", "resolved": True},
        {"id": "c2", "severity": "major", "resolved": False},
    ]
    res = await CriticLoopEvaluator().evaluate(make_ctx(fb), judge=None)
    assert res.metadata["resolution_rate"] == 0.5
    assert res.score == 5.0  # 0.5 × 10


@pytest.mark.asyncio
async def test_critic_all_resolved_full_score():
    fb = [
        {"id": "c1", "severity": "minor", "resolved": True},
        {"id": "c2", "severity": "major", "resolved": True},
    ]
    res = await CriticLoopEvaluator().evaluate(make_ctx(fb, iteration=2), judge=None)
    assert res.metadata["resolution_rate"] == 1.0
    assert res.score == 10.0
    assert res.metadata["iterations"] == 2
