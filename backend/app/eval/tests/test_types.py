"""Test eval types dataclasses."""
from datetime import datetime

from app.eval.types import (
    EvalCase, EvalContext, EvalResult,
    JudgeScore, EnsembleResult, CaseResult,
)


def test_eval_case_required_fields():
    case = EvalCase(id="q001", query="新能源汽车2024年", category="汽车", difficulty="easy")
    assert case.id == "q001"
    assert case.query == "新能源汽车2024年"
    assert case.category == "汽车"
    assert case.difficulty == "easy"


def test_judge_score_default_failed_false():
    s = JudgeScore(judge_name="qwen", score=8.0, reasoning="ok")
    assert s.failed is False
    assert s.error is None


def test_judge_score_failed_when_no_score():
    s = JudgeScore(judge_name="qwen", score=None, reasoning="", failed=True, error="parse error")
    assert s.failed is True
    assert s.score is None


def test_ensemble_result_mean_median_std():
    r = EnsembleResult(
        mean_score=7.5,
        median_score=8.0,
        std=1.0,
        individual=[],
        low_confidence=False,
        partial=False,
    )
    assert r.mean_score == 7.5
    assert r.std == 1.0
    assert r.low_confidence is False


def test_eval_result_default_metadata_is_dict():
    r = EvalResult(evaluator_name="cost", score=1.5, raw_judge_outputs=[])
    assert r.metadata == {}
    assert r.error is None
    assert r.low_confidence is False


def test_eval_context_construction():
    ctx = EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"final_report": "..."},
        started_at=datetime(2026, 5, 26, 14, 0, 0),
        finished_at=datetime(2026, 5, 26, 14, 5, 0),
    )
    assert ctx.duration_sec == 300.0


def test_case_result_ok_default():
    cr = CaseResult(case=EvalCase(id="q001", query="x", category="c", difficulty="easy"))
    assert cr.ok is True
    assert cr.error is None
    assert cr.results == []
