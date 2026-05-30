"""异步 runner：并发跑 IntentService + ResearchTypeService 并收集 CaseResult。

设计：依赖注入 service 实例，便于 mock 测试。结果列表与输入 cases 同序。
"""
import asyncio
import time
from dataclasses import asdict
from typing import Any
from app.intent_eval.types import EvalCase, CaseResult


def _to_dict_safely(obj: Any) -> dict:
    """把 IntentResult / ResearchTypeResult（dataclass 或 Mock）转 dict 落档。"""
    if obj is None:
        return {}
    try:
        return asdict(obj)
    except TypeError:
        # 非 dataclass（如 Mock），只取已知字段
        return {
            k: getattr(obj, k, None)
            for k in ("intent", "research_type", "confidence")
            if hasattr(obj, k)
        }


async def _run_one(
    case: EvalCase, intent_svc, research_type_svc
) -> CaseResult:
    started = time.perf_counter()
    error = None
    predicted_intent = None
    intent_confidence = 0.0
    intent_raw: dict = {}
    predicted_rt = None
    rt_confidence: float | None = None
    rt_raw: dict | None = None

    try:
        intent_result = await intent_svc.classify(case.query)
        predicted_intent = intent_result.intent
        intent_confidence = intent_result.confidence
        intent_raw = _to_dict_safely(intent_result)
        if case.true_intent == "deep_research":
            rt_result = await research_type_svc.classify(case.query)
            predicted_rt = rt_result.research_type
            rt_confidence = rt_result.confidence
            rt_raw = _to_dict_safely(rt_result)
    except Exception as e:
        error = str(e)

    latency_ms = int((time.perf_counter() - started) * 1000)
    return CaseResult(
        case=case,
        predicted_intent=predicted_intent,
        predicted_research_type=predicted_rt,
        intent_confidence=intent_confidence,
        research_type_confidence=rt_confidence,
        intent_raw=intent_raw,
        research_type_raw=rt_raw,
        latency_ms=latency_ms,
        error=error,
    )


async def run(
    cases: list[EvalCase],
    intent_svc,
    research_type_svc,
    concurrency: int = 10,
) -> list[CaseResult]:
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(case: EvalCase) -> CaseResult:
        async with sem:
            return await _run_one(case, intent_svc, research_type_svc)

    return await asyncio.gather(*[_bounded(c) for c in cases])
