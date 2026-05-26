"""Test Reporter markdown + csv generation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.eval.reporter import Reporter
from app.eval.types import CaseResult, EvalCase, EvalResult


def make_case_result(case_id: str, scores: dict[str, float], ok: bool = True, error=None) -> CaseResult:
    return CaseResult(
        case=EvalCase(id=case_id, query=f"q-{case_id}", category="汽车", difficulty="easy"),
        results=[
            EvalResult(evaluator_name=name, score=s) for name, s in scores.items()
        ],
        ok=ok,
        error=error,
        started_at=datetime(2026, 5, 26, 14, 0),
        finished_at=datetime(2026, 5, 26, 14, 5),
    )


def test_reporter_writes_markdown(tmp_path: Path):
    out_dir = tmp_path / "results"
    cases = [
        make_case_result("q001", {"relevance": 8.0, "cost": 0.34}),
        make_case_result("q002", {"relevance": 7.5, "cost": 0.41}),
    ]
    r = Reporter(out_dir=str(out_dir))
    paths = r.write(
        run_id="run-001",
        suite="full",
        git_commit="abc1234",
        started_at=datetime(2026, 5, 26, 14, 0),
        finished_at=datetime(2026, 5, 26, 14, 30),
        case_results=cases,
        langsmith_url=None,
    )
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "run-001" in md
    assert "abc1234" in md
    assert "## Overall Scores" in md
    assert "relevance" in md
    csv_path = Path(paths["csv"])
    assert csv_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "q001" in csv_text and "q002" in csv_text


def test_reporter_marks_failed_cases(tmp_path: Path):
    cases = [
        make_case_result("q001", {"relevance": 7.0}),
        make_case_result("q002", {}, ok=False, error="TimeoutError"),
    ]
    r = Reporter(out_dir=str(tmp_path))
    paths = r.write(
        run_id="run-2",
        suite="mini",
        git_commit="abc",
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
        case_results=cases,
        langsmith_url=None,
    )
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "## Failed Cases" in md
    assert "q002" in md
    assert "TimeoutError" in md
