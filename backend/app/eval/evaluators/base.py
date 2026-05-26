"""Evaluator abstract base."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.eval.types import EvalContext, EvalResult

if TYPE_CHECKING:
    from app.eval.judges.ensemble import EnsembleJudge


class Evaluator(ABC):
    """Abstract evaluator. Subclasses set class-level metadata + implement evaluate()."""

    name: str = ""
    scale: tuple[float, float] = (0, 10)
    requires_judge: bool = False
    requires_network: bool = False

    @abstractmethod
    async def evaluate(
        self,
        ctx: EvalContext,
        judge: "EnsembleJudge | None",
    ) -> EvalResult:
        """Evaluate one case, return EvalResult. Must never raise — wrap errors in result.error."""
        ...
