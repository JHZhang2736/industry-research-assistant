"""Latency evaluator: total duration + per-agent breakdown."""
from __future__ import annotations

from collections import defaultdict

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult


class LatencyEvaluator(Evaluator):
    name = "latency"
    scale = (0, float("inf"))
    requires_judge = False
    requires_network = False

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        total = ctx.duration_sec
        per_agent: dict[str, float] = defaultdict(float)
        for log in (ctx.state.get("logs") or []):
            agent = log.get("agent") or "unknown"
            per_agent[agent] += (log.get("duration_ms") or 0) / 1000.0

        return EvalResult(
            evaluator_name=self.name,
            score=round(total, 1),
            metadata={
                "total_sec": round(total, 1),
                "per_agent_sec": {k: round(v, 1) for k, v in per_agent.items()},
            },
        )
