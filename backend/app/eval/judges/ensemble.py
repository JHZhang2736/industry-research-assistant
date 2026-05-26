"""Aggregate scores from multiple judge families."""
from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Protocol

from app.eval.settings import LOW_CONFIDENCE_STD_THRESHOLD
from app.eval.types import EnsembleResult, JudgeScore

logger = logging.getLogger("eval.ensemble")


class _JudgeProtocol(Protocol):
    async def call_judge(self, prompt: str) -> JudgeScore: ...


class EnsembleJudge:
    """Run N judges in parallel, aggregate to a single EnsembleResult."""

    def __init__(self, clients: list[_JudgeProtocol]):
        if not clients:
            raise ValueError("EnsembleJudge needs at least one client")
        self.clients = clients

    async def score(self, prompt: str) -> EnsembleResult:
        raw = await asyncio.gather(
            *[c.call_judge(prompt) for c in self.clients],
            return_exceptions=True,
        )

        individual: list[JudgeScore] = []
        for r in raw:
            if isinstance(r, JudgeScore):
                individual.append(r)
            else:
                # Bare exception slipped through
                individual.append(JudgeScore(
                    judge_name="unknown",
                    score=None,
                    reasoning="",
                    failed=True,
                    error=str(r),
                ))

        valid = [s for s in individual if not s.failed and s.score is not None]

        if not valid:
            return EnsembleResult(
                mean_score=None,
                median_score=None,
                std=0,
                individual=individual,
                low_confidence=False,
                partial=True,
                error="all judges failed",
            )

        scores = [s.score for s in valid]
        mean = statistics.mean(scores)
        median = statistics.median(scores)
        std = statistics.stdev(scores) if len(scores) > 1 else 0
        return EnsembleResult(
            mean_score=mean,
            median_score=median,
            std=std,
            individual=individual,
            low_confidence=std > LOW_CONFIDENCE_STD_THRESHOLD,
            partial=len(valid) < len(self.clients),
        )
