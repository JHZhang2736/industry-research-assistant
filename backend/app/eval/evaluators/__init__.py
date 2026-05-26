"""Eval registry. Populated by subsequent tasks."""
from __future__ import annotations

from app.eval.evaluators.base import Evaluator


def build_all_evaluators() -> list[Evaluator]:
    """Build the full evaluator list. Lazy imports avoid circular deps."""
    from app.eval.evaluators.cost import CostEvaluator
    from app.eval.evaluators.latency import LatencyEvaluator
    from app.eval.evaluators.critic_loop import CriticLoopEvaluator
    from app.eval.evaluators.citation import CitationEvaluator
    from app.eval.evaluators.relevance import RelevanceEvaluator
    from app.eval.evaluators.coherence import CoherenceEvaluator
    from app.eval.evaluators.completeness import CompletenessEvaluator

    return [
        RelevanceEvaluator(),
        CoherenceEvaluator(),
        CitationEvaluator(),
        CompletenessEvaluator(),
        CriticLoopEvaluator(),
        CostEvaluator(),
        LatencyEvaluator(),
    ]


__all__ = ["Evaluator", "build_all_evaluators"]
