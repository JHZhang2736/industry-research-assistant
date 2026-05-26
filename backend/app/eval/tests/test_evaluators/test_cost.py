"""Test CostEvaluator."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.cost import CostEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(logs: list[dict]) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"logs": logs},
        started_at=datetime(2026, 5, 26, 14, 0, 0),
        finished_at=datetime(2026, 5, 26, 14, 5, 0),
    )


@pytest.mark.asyncio
async def test_cost_zero_when_no_logs():
    ctx = make_ctx([])
    res = await CostEvaluator().evaluate(ctx, judge=None)
    assert res.score == 0.0
    assert res.metadata["total_tokens"] == 0


@pytest.mark.asyncio
async def test_cost_sums_tokens_from_logs():
    ctx = make_ctx([
        {"tokens_used": 1000, "model": "qwen-max"},
        {"tokens_used": 2000, "model": "qwen-plus"},
    ])
    res = await CostEvaluator().evaluate(ctx, judge=None)
    assert res.metadata["total_tokens"] == 3000
    assert res.score > 0  # RMB


@pytest.mark.asyncio
async def test_cost_unknown_model_uses_fallback_pricing():
    ctx = make_ctx([{"tokens_used": 1000, "model": "unknown-model-xyz"}])
    res = await CostEvaluator().evaluate(ctx, judge=None)
    assert res.score >= 0
    assert "unknown-model-xyz" in res.metadata.get("unknown_models", [])
