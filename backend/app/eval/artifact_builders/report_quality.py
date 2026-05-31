"""Build weighted multi-judge report quality scores."""

from __future__ import annotations

import json
import statistics
from dataclasses import fields
from pathlib import Path
from typing import Any

from app.eval.artifact_builders.json_utils import parse_json_object
from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    ReportQualityScores,
    ReportSection,
)
from app.eval.settings import (
    JUDGE_WEIGHTS,
    LOW_CONFIDENCE_STD_THRESHOLD,
    REPORT_QUALITY_DIMENSIONS,
)

_SYSTEM_PROMPT = (
    "You score report quality for claim-centered evaluation. "
    "Respond only with a JSON object matching the requested schema."
)
_PROMPT_PATH = Path(__file__).parent / "prompts" / "report_quality.md"


class ReportQualityBuilder:
    """Score report quality with all structured judges and weighted aggregation."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(weights or JUDGE_WEIGHTS)

    async def build(
        self,
        query: str,
        sections: list[ReportSection],
        claims: list[AtomicClaim],
        verdicts: list[ClaimVerdict],
        judge: Any,
    ) -> ReportQualityScores:
        prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
            query=query,
            sections_json=json.dumps(
                [_to_jsonable(section) for section in sections],
                ensure_ascii=False,
            ),
            claim_summary_json=json.dumps(
                {
                    "claims": [_to_jsonable(claim) for claim in claims],
                    "verdicts": [_to_jsonable(verdict) for verdict in verdicts],
                },
                ensure_ascii=False,
            ),
        )
        results = await judge.generate_structured_all(
            prompt, system_prompt=_SYSTEM_PROMPT
        )

        partial = False
        raw_outputs: list[dict[str, Any]] = []
        scores_by_dimension: dict[str, list[tuple[str, float]]] = {
            dimension: [] for dimension in REPORT_QUALITY_DIMENSIONS
        }

        for result in results:
            raw_output = {
                "judge": result.judge_name,
                "content": result.content,
                "failed": result.failed,
                "error": result.error,
            }
            raw_outputs.append(raw_output)

            if result.failed:
                partial = True
                continue

            try:
                payload = parse_json_object(result.content)
            except ValueError as exc:
                raw_output["failed"] = True
                raw_output["error"] = str(exc)
                partial = True
                continue

            for dimension in REPORT_QUALITY_DIMENSIONS:
                score = _extract_score(payload.get(dimension))
                if score is not None:
                    scores_by_dimension[dimension].append((result.judge_name, score))

        aggregated = ReportQualityScores(
            raw_judge_outputs=raw_outputs,
            partial=partial,
        )
        for dimension, scores in scores_by_dimension.items():
            if not scores:
                continue
            setattr(aggregated, dimension, _weighted_mean(scores, self.weights))
            std = (
                statistics.stdev([score for _, score in scores])
                if len(scores) > 1
                else 0
            )
            aggregated.std_by_dimension[dimension] = std
            if std > LOW_CONFIDENCE_STD_THRESHOLD:
                aggregated.low_confidence_dimensions.append(dimension)

        return aggregated


def _extract_score(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("score")
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return min(10.0, max(0.0, score))


def _weighted_mean(
    scores: list[tuple[str, float]],
    weights: dict[str, float],
) -> float:
    weighted_total = 0.0
    weight_total = 0.0
    for judge_name, score in scores:
        weight = weights.get(judge_name, 1.0)
        weighted_total += score * weight
        weight_total += weight
    if weight_total == 0:
        return statistics.mean([score for _, score in scores])
    return weighted_total / weight_total


def _to_jsonable(item: Any) -> dict[str, Any]:
    return {field.name: getattr(item, field.name) for field in fields(item)}
