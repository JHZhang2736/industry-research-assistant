"""Eval framework dataclasses.

Pure data structures, no logic. Used across runner, evaluators, judges, storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EvalCase:
    """One test query from the dataset."""
    id: str
    query: str
    category: str
    difficulty: str        # "easy" | "medium" | "hard"


@dataclass
class JudgeScore:
    """One judge's scoring of one prompt."""
    judge_name: str
    score: float | None
    reasoning: str
    failed: bool = False
    error: str | None = None


@dataclass
class StructuredJudgeResult:
    """One judge's raw structured-output response."""
    judge_name: str
    content: str
    failed: bool = False
    error: str | None = None


@dataclass
class EnsembleResult:
    """Aggregated score from multiple judges."""
    mean_score: float | None
    median_score: float | None
    std: float
    individual: list[JudgeScore]
    low_confidence: bool   # std > threshold
    partial: bool          # some judges failed
    error: str | None = None


@dataclass
class EvalResult:
    """One evaluator's output for one case."""
    evaluator_name: str
    score: float | None
    raw_judge_outputs: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error: str | None = None
    low_confidence: bool = False


@dataclass
class EvalContext:
    """Data passed to each evaluator."""
    case: EvalCase
    state: dict                          # ResearchState (final, from PG checkpoint)
    started_at: datetime
    finished_at: datetime

    @property
    def duration_sec(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass
class CaseResult:
    """All evaluator outputs for one case, plus run-level status."""
    case: EvalCase
    results: list[EvalResult] = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    state: dict | None = None            # final state snapshot
    artifact: Any | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
