"""Completeness evaluator: outline → report coverage via LLM-judge."""
from __future__ import annotations

from pathlib import Path

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult

_PROMPT_PATH = Path(__file__).parent / "prompts" / "completeness.md"
_REPORT_EXCERPT_CHARS = 4000


class CompletenessEvaluator(Evaluator):
    name = "completeness"
    scale = (0, 10)
    requires_judge = True
    requires_network = False

    _template: str | None = None

    @classmethod
    def _load_template(cls) -> str:
        if cls._template is None:
            cls._template = _PROMPT_PATH.read_text(encoding="utf-8")
        return cls._template

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        if judge is None:
            return EvalResult(evaluator_name=self.name, score=None, error="needs judge")

        outline = ctx.state.get("outline") or []
        report = ctx.state.get("final_report") or ""
        if not outline:
            return EvalResult(evaluator_name=self.name, score=None, error="empty outline")
        if not report.strip():
            return EvalResult(evaluator_name=self.name, score=None, error="empty report")

        outline_str = "\n".join(
            f"- {s.get('id', '?')}: {s.get('title', '')} — {s.get('description', '')[:100]}"
            for s in outline
        )

        prompt = self._load_template().format(
            outline_str=outline_str,
            report_excerpt=report[:_REPORT_EXCERPT_CHARS],
        )
        result = await judge.score(prompt)

        return EvalResult(
            evaluator_name=self.name,
            score=result.mean_score,
            raw_judge_outputs=[
                {"judge": s.judge_name, "score": s.score, "reasoning": s.reasoning, "failed": s.failed}
                for s in result.individual
            ],
            metadata={
                "outline_section_count": len(outline),
                "median": result.median_score,
                "std": result.std,
                "partial": result.partial,
            },
            low_confidence=result.low_confidence,
            error=result.error,
        )
