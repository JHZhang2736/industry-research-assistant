"""Runner 并发与调用条件测试。Mock service，不烧 LLM 钱。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.intent_eval.runner import run
from app.intent_eval.types import EvalCase


def _make_intent_result(name: str, confidence: float = 1.0, research_type: str = ""):
    """模拟 IntentService.classify 的返回 (IntentResult 鸭子类型)。"""
    return MagicMock(intent=name, research_type=research_type, confidence=confidence)


def _make_rt_result(name: str, confidence: float = 1.0):
    return MagicMock(research_type=name, confidence=confidence)


@pytest.fixture
def cases() -> list[EvalCase]:
    return [
        EvalCase(id="c1", query="q1", true_intent="deep_research",
                 true_research_type="industry_analysis", subtype="", is_boundary=False),
        EvalCase(id="c2", query="q2", true_intent="simple_qa",
                 true_research_type=None, subtype="", is_boundary=False),
        EvalCase(id="c3", query="q3", true_intent="web_search",
                 true_research_type=None, subtype="", is_boundary=False),
    ]


async def test_run_all_cases(cases):
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(side_effect=[
        _make_intent_result("deep_research", research_type="general"),
        _make_intent_result("simple_qa"),
        _make_intent_result("web_search"),
    ])
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    results = await run(cases, intent_svc, rt_svc, concurrency=2)
    assert len(results) == 3
    assert {r.case.id for r in results} == {"c1", "c2", "c3"}


async def test_level2_only_called_on_true_deep_research(cases):
    """Level 2 只在 true_intent == 'deep_research' 时调用，不管 Level 1 预测对错。"""
    intent_svc = MagicMock()
    # 故意让所有预测都是 simple_qa，验证 Level 2 是否仍在 c1 上跑
    intent_svc.classify = AsyncMock(return_value=_make_intent_result("simple_qa"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    await run(cases, intent_svc, rt_svc, concurrency=1)
    assert rt_svc.classify.call_count == 1   # 仅 c1
    rt_svc.classify.assert_called_with("q1")


async def test_level2_not_called_when_no_deep_research():
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(return_value=_make_intent_result("simple_qa"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock()

    cases = [
        EvalCase(id="c1", query="q1", true_intent="simple_qa",
                 true_research_type=None, subtype="", is_boundary=False),
        EvalCase(id="c2", query="q2", true_intent="web_search",
                 true_research_type=None, subtype="", is_boundary=False),
    ]
    await run(cases, intent_svc, rt_svc, concurrency=1)
    assert rt_svc.classify.call_count == 0


async def test_results_preserve_input_order(cases):
    """结果列表与输入 cases 同序，方便后续 metrics 对齐。"""
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(return_value=_make_intent_result("simple_qa"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    results = await run(cases, intent_svc, rt_svc, concurrency=2)
    assert [r.case.id for r in results] == ["c1", "c2", "c3"]


async def test_latency_recorded(cases):
    intent_svc = MagicMock()

    async def slow_classify(_):
        await asyncio.sleep(0.05)
        return _make_intent_result("simple_qa")

    intent_svc.classify = slow_classify
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    results = await run(cases[:1], intent_svc, rt_svc, concurrency=1)
    assert results[0].latency_ms >= 50


async def test_service_exception_recorded_as_error(cases):
    """Service 直接抛异常 → CaseResult.error 记录，predicted_intent = None。"""
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(side_effect=RuntimeError("boom"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock()

    results = await run(cases[:1], intent_svc, rt_svc, concurrency=1)
    assert results[0].predicted_intent is None
    assert results[0].error == "boom"


async def test_concurrency_limit_respected():
    """同时运行的协程不超过 concurrency 限制。"""
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def tracking_classify(_):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        return _make_intent_result("simple_qa")

    cases = [
        EvalCase(id=f"c{i}", query=f"q{i}", true_intent="simple_qa",
                 true_research_type=None, subtype="", is_boundary=False)
        for i in range(10)
    ]
    intent_svc = MagicMock(); intent_svc.classify = tracking_classify
    rt_svc = MagicMock(); rt_svc.classify = AsyncMock()

    await run(cases, intent_svc, rt_svc, concurrency=3)
    assert max_in_flight <= 3
