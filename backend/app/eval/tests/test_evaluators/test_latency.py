"""Test LatencyEvaluator."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.latency import LatencyEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(logs: list[dict], duration_min: int = 5) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"logs": logs},
        started_at=datetime(2026, 5, 26, 14, 0, 0),
        finished_at=datetime(2026, 5, 26, 14, duration_min, 0),
    )


@pytest.mark.asyncio
async def test_latency_total_duration():
    res = await LatencyEvaluator().evaluate(make_ctx([], duration_min=3), judge=None)
    assert res.score == 180.0


@pytest.mark.asyncio
async def test_latency_per_agent_breakdown():
    logs = [
        {"agent": "architect", "duration_ms": 5000},
        {"agent": "scout", "duration_ms": 20000},
        {"agent": "scout", "duration_ms": 10000},
        {"agent": "writer", "duration_ms": 30000},
    ]
    res = await LatencyEvaluator().evaluate(make_ctx(logs), judge=None)
    per_agent = res.metadata["per_agent_sec"]
    assert per_agent["architect"] == 5.0
    assert per_agent["scout"] == 30.0
    assert per_agent["writer"] == 30.0
