"""Smoke test: 验证 types 模块可加载，dataclass 字段对得上。"""
from app.intent_eval.types import (
    EvalCase, CaseResult, INTENT_CLASSES, RESEARCH_TYPE_CLASSES,
)


def test_intent_classes_correct():
    assert INTENT_CLASSES == ["deep_research", "web_search", "simple_qa", "out_of_scope"]


def test_research_type_classes_correct():
    assert RESEARCH_TYPE_CLASSES == ["industry_analysis", "company_research", "comparative_analysis"]


def test_eval_case_construct():
    c = EvalCase(
        id="intent-001", query="分析新能源汽车行业",
        true_intent="deep_research", true_research_type="industry_analysis",
        subtype="标准行业分析", is_boundary=False,
    )
    assert c.id == "intent-001"
    assert c.true_research_type == "industry_analysis"


def test_case_result_intent_correct():
    case = EvalCase(id="x", query="q", true_intent="simple_qa",
                    true_research_type=None, subtype="", is_boundary=False)
    cr = CaseResult(case=case, predicted_intent="simple_qa",
                    predicted_research_type=None, intent_confidence=1.0,
                    research_type_confidence=None, intent_raw={}, research_type_raw=None,
                    latency_ms=500, error=None)
    assert cr.intent_correct is True
    assert cr.research_type_correct is None


def test_case_result_research_type_correct():
    case = EvalCase(id="x", query="q", true_intent="deep_research",
                    true_research_type="company_research", subtype="", is_boundary=False)
    cr = CaseResult(case=case, predicted_intent="deep_research",
                    predicted_research_type="industry_analysis",
                    intent_confidence=1.0, research_type_confidence=1.0,
                    intent_raw={}, research_type_raw={}, latency_ms=500, error=None)
    assert cr.intent_correct is True
    assert cr.research_type_correct is False
