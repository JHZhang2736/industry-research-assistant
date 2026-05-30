"""加载 intent eval jsonl 数据集并做 schema 校验。"""
import json
from pathlib import Path
from app.intent_eval.types import EvalCase, INTENT_CLASSES, RESEARCH_TYPE_CLASSES

REQUIRED_FIELDS = ["id", "query", "true_intent", "true_research_type", "subtype", "is_boundary"]


class DatasetError(ValueError):
    """数据集校验失败。"""


def _validate_row(row: dict, line_no: int) -> EvalCase:
    for field in REQUIRED_FIELDS:
        if field not in row:
            raise DatasetError(f"line {line_no}: missing field '{field}'")
    if row["true_intent"] not in INTENT_CLASSES:
        raise DatasetError(
            f"line {line_no}: invalid true_intent {row['true_intent']!r}, "
            f"expected one of {INTENT_CLASSES}"
        )
    if row["true_intent"] == "deep_research":
        if row["true_research_type"] is None:
            raise DatasetError(
                f"line {line_no}: true_research_type required when true_intent='deep_research'"
            )
        if row["true_research_type"] not in RESEARCH_TYPE_CLASSES:
            raise DatasetError(
                f"line {line_no}: invalid true_research_type {row['true_research_type']!r}, "
                f"expected one of {RESEARCH_TYPE_CLASSES}"
            )
    else:
        if row["true_research_type"] is not None:
            raise DatasetError(
                f"line {line_no}: true_research_type must be null when true_intent != 'deep_research'"
            )
    return EvalCase(
        id=row["id"],
        query=row["query"],
        true_intent=row["true_intent"],
        true_research_type=row["true_research_type"],
        subtype=row["subtype"],
        is_boundary=bool(row["is_boundary"]),
    )


def load(path: Path) -> list[EvalCase]:
    path = Path(path)
    if not path.exists():
        raise DatasetError(f"dataset file not found: {path}")
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise DatasetError(f"line {line_no}: invalid JSON ({e})") from e
            case = _validate_row(row, line_no)
            if case.id in seen_ids:
                raise DatasetError(f"line {line_no}: duplicate id {case.id!r}")
            seen_ids.add(case.id)
            cases.append(case)
    return cases
