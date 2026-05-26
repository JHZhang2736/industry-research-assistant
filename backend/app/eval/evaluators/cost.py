"""Cost evaluator: sum tokens from logs, convert to RMB."""
from __future__ import annotations

from app.eval.evaluators.base import Evaluator
from app.eval.settings import PRICING_RMB_PER_M_TOKENS
from app.eval.types import EvalContext, EvalResult

# Fallback pricing when model not in PRICING table
_FALLBACK_INPUT = 2.0
_FALLBACK_OUTPUT = 6.0


class CostEvaluator(Evaluator):
    name = "cost"
    scale = (0, float("inf"))
    requires_judge = False
    requires_network = False

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        logs = ctx.state.get("logs") or []
        total_tokens = 0
        rmb = 0.0
        unknown_models: list[str] = []

        for log in logs:
            t = int(log.get("tokens_used") or 0)
            total_tokens += t
            model = log.get("model") or "unknown"
            pricing = PRICING_RMB_PER_M_TOKENS.get(model)
            if pricing is None:
                if model not in unknown_models:
                    unknown_models.append(model)
                in_price, out_price = _FALLBACK_INPUT, _FALLBACK_OUTPUT
            else:
                in_price, out_price = pricing
            # No input/output split in logs → assume 50/50
            half = t / 2
            rmb += (half * in_price + half * out_price) / 1_000_000

        return EvalResult(
            evaluator_name=self.name,
            score=round(rmb, 4),
            metadata={
                "total_tokens": total_tokens,
                "rmb": round(rmb, 4),
                "unknown_models": unknown_models,
            },
        )
