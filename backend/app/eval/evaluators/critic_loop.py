"""CriticLoopEffectiveness evaluator: resolution rate × 10."""
from __future__ import annotations

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult


class CriticLoopEvaluator(Evaluator):
    name = "critic_loop"
    scale = (0, 10)
    requires_judge = False
    requires_network = False

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        feedback = ctx.state.get("critic_feedback") or []
        total = len(feedback)
        iterations = int(ctx.state.get("iteration") or 0)
        quality = float(ctx.state.get("quality_score") or 0.0)

        if total == 0:
            return EvalResult(
                evaluator_name=self.name,
                score=None,
                metadata={
                    "total_feedback": 0,
                    "resolution_rate": None,
                    "iterations": iterations,
                    "final_quality_score": quality,
                    "note": "no critic feedback recorded",
                },
            )

        resolved = sum(1 for f in feedback if f.get("resolved") is True)
        rate = resolved / total
        return EvalResult(
            evaluator_name=self.name,
            score=round(rate * 10, 2),
            metadata={
                "total_feedback": total,
                "resolved": resolved,
                "resolution_rate": round(rate, 3),
                "iterations": iterations,
                "final_quality_score": quality,
                "severity_breakdown": {
                    "critical": sum(1 for f in feedback if f.get("severity") == "critical"),
                    "major": sum(1 for f in feedback if f.get("severity") == "major"),
                    "minor": sum(1 for f in feedback if f.get("severity") == "minor"),
                },
            },
        )
