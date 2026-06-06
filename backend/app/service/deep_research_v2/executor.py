"""DeepResearch v3 - Executor node + 并行调度逻辑

Executor 负责按 plan 调度 tools，处理并行组，merge tool 返回结果到 state。
不直接调 LLM，只做调度。
"""

import time
import asyncio
import functools
import logging
import hashlib
from typing import Dict, Any, List, Set

from .state import ResearchState
from .tools import search_section, analyze_facts, generate_charts, write_section

# 取消标志检查（与 graph.py 同样的 try/except 兼容路径）
try:
    from app.router.research_router import is_research_cancelled
except (ImportError, SyntaxError):
    try:
        from router.research_router import is_research_cancelled
    except (ImportError, SyntaxError):
        def is_research_cancelled(session_id: str) -> bool:
            return False

# LangSmith traceable：给每个 plan step 建独立 span。未安装 langsmith 时退化为
# 吃掉 langsmith_extra 的透传装饰器（no-op），保证非 langsmith 环境照常运行。
try:
    from langsmith import traceable
except ImportError:
    def traceable(*d_args, **d_kwargs):
        def _decorator(fn):
            # 同时支持 async / sync 被装饰函数：若把 sync 函数用 async 包裹，
            # 调用方拿到的是 coroutine 而非真实返回值，会静默丢结果。
            if asyncio.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def _async_wrapper(*args, **kwargs):
                    kwargs.pop("langsmith_extra", None)
                    return await fn(*args, **kwargs)
                return _async_wrapper

            @functools.wraps(fn)
            def _sync_wrapper(*args, **kwargs):
                kwargs.pop("langsmith_extra", None)
                return fn(*args, **kwargs)
            return _sync_wrapper
        if len(d_args) == 1 and callable(d_args[0]) and not d_kwargs:
            return _decorator(d_args[0])
        return _decorator

logger = logging.getLogger("deep_research_v3.executor")


def _maybe_cancel(state: ResearchState) -> None:
    """在 executor 内部 batch 边界检查取消标志，命中即抛 CancelledError。

    graph.py 的 _maybe_cancel 只在 node 入口跑；executor 内部跑 N 批 tool（可能
    几分钟），不在 batch 之间复查的话 cancel 按钮要等整个 executor 结束才生效。
    """
    session_id = state.get("session_id", "")
    if session_id and is_research_cancelled(session_id):
        logger.info(f"Executor cancelled mid-loop: session={session_id}")
        raise asyncio.CancelledError(f"research_cancelled:{session_id}")


async def _gather_with_cancel_watch(
    state: ResearchState,
    batch: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """跑一个 batch，同时起一个 watcher 协程每秒查 cancel 标志。

    命中即 cancel 整个 gather future —— 在跑的 tool 调用会收到 CancelledError
    并立刻退出（包括 await 中的 LLM/HTTP）。比 batch 边界检查激进得多：
    最坏延迟约 1 秒而不是整批跑完。
    """
    # asyncio.gather 已经返回一个自动调度的 _GatheringFuture，不能再 wrap
    # 到 create_task 里（Py 3.11+ 会报 TypeError: a coroutine was expected）。
    gather_future = asyncio.gather(*[
        execute_one_step(step, state, langsmith_extra=_step_trace_extra(step, state))
        for step in batch
    ])

    session_id = state.get("session_id", "")

    async def _watch() -> None:
        while not gather_future.done():
            if session_id and is_research_cancelled(session_id):
                logger.info(
                    f"Cancel flag detected mid-batch, aborting tasks: session={session_id}"
                )
                gather_future.cancel()
                return
            await asyncio.sleep(1.0)

    watcher = asyncio.create_task(_watch()) if session_id else None
    try:
        return await gather_future
    finally:
        if watcher and not watcher.done():
            watcher.cancel()


TOOL_REGISTRY = {
    "search_section": search_section,
    "analyze_facts": analyze_facts,
    "generate_charts": generate_charts,
    "write_section": write_section,
}


def _resolve_callable(tool_obj):
    """从 @tool 包装拿到底层 coroutine 函数。

    LangChain @tool.ainvoke 会用 pydantic v2 对参数做 schema 验证 ——
    对 TypedDict 参数（ResearchState）会构造新 dict 并递归验证 List[Fact] 等
    内部字段，导致 search_section 在 tool 上下文里 append 的 facts 落到新对象上，
    后续 analyze_facts 从原 state 读到的还是空 list。直接调底层 coroutine 跳过
    校验，state 按引用透传。
    """
    # langchain_core StructuredTool: async 函数存在 .coroutine，sync 存在 .func
    fn = getattr(tool_obj, "coroutine", None) or getattr(tool_obj, "func", None)
    return fn or tool_obj


def _merge_raw_sources(merged_sources, sources_by_url, new_sources):
    """按 url 去重把 new_sources 并进 merged_sources（原地）。

    已存在的 url 累加 related_sections（去重），新 url 追加。覆盖式合并模型下，
    跨章节/跨 tool 的同 url raw_source 必须在此统一去重。
    注意：existing 可能与 state["raw_sources"] 中的对象是同一引用（merged_sources = list(state[...]) 浅拷贝），
    这里对 related_sections 的就地累加是有意为之；dedup 检查保证重复 sid 不会被重复追加（幂等）。
    """
    for src in new_sources:
        url = src.get("url")
        if url and url in sources_by_url:
            existing = sources_by_url[url]
            existing.setdefault("related_sections", [])
            for sid in src.get("related_sections", []):
                if sid not in existing["related_sections"]:
                    existing["related_sections"].append(sid)
        else:
            merged_sources.append(src)
            if url:
                sources_by_url[url] = src


# tool 名 -> 前端 research_step.step_type（驱动侧边栏详情容器）
# search_section 故意映射到 'searching'（前端 search_results 优先找 searching）
# generate_charts 复用 'analyzing'（前端 charts 事件 attach 到 analyzing 详情）
TOOL_TO_STEP_TYPE = {
    "search_section": "searching",
    "analyze_facts": "analyzing",
    "generate_charts": "analyzing",
    "write_section": "writing",
}

STEP_TYPE_META = {
    "searching": ("🔍 深度搜索", "并行检索各章节资料"),
    "analyzing": ("📊 数据分析", "提取数据点 + 构建知识图谱"),
    "writing": ("✍️ 撰写报告", "按章节生成 Markdown"),
}


def _emit(event_type: str, content: Dict[str, Any]) -> None:
    """安全推送 custom stream 事件（非 graph 上下文时静默丢弃）"""
    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        writer({"type": event_type, "content": content})
    except (ImportError, RuntimeError, KeyError):
        pass


def _stats_for(
    step_type: str,
    facts: List[Any],
    sources: List[Any],
    charts: List[Any],
    draft_sections: Dict[str, Any],
) -> Dict[str, Any]:
    """根据当前合并后的累计数据生成前端期望的 stats（snake_case）"""
    if step_type == "searching":
        return {
            "results_count": len(facts),
            "sources_count": len(sources),
        }
    if step_type == "analyzing":
        return {
            "charts_count": len(charts),
        }
    if step_type == "writing":
        word_count = sum(len(c or "") for c in draft_sections.values())
        return {
            "sections_count": len(draft_sections),
            "word_count": word_count,
        }
    return {}


def _hash_text(text: str) -> str:
    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _emit_step(
    step_type: str,
    status: str,
    stats: Dict[str, Any] | None = None,
) -> None:
    title, subtitle = STEP_TYPE_META.get(step_type, (step_type, ""))
    _emit("research_step", {
        "step_type": step_type,
        "title": title,
        "subtitle": subtitle,
        "status": status,
        "stats": stats or {},
    })


def _trace_step_inputs(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """traceable process_inputs：只保留 step 的 tool/args/step_id，丢掉巨大的 state。"""
    step = inputs.get("step", {}) or {}
    return {
        "tool": step.get("tool"),
        "args": step.get("args", {}),
        "step_id": step.get("step_id"),
    }


def _trace_step_outputs(outputs: Dict[str, Any]) -> Dict[str, Any]:
    """traceable process_outputs：把 StepResult 压成计数摘要，不记完整 facts/内容。"""
    if not isinstance(outputs, dict):
        return {"result": str(outputs)[:200]}
    summary = {
        "status": outputs.get("status"),
        "duration_ms": outputs.get("duration_ms"),
    }
    if outputs.get("error"):
        summary["error"] = outputs["error"]
    out = outputs.get("output")
    if isinstance(out, dict):
        if "facts" in out:
            summary["facts_count"] = len(out.get("facts") or [])
        if "sources" in out:
            summary["sources_count"] = len(out.get("sources") or [])
        if "data_points" in out:
            summary["data_points_count"] = len(out.get("data_points") or [])
        if "charts" in out:
            summary["charts_count"] = len(out.get("charts") or [])
        if out.get("section_id"):
            summary["section_written"] = out.get("section_id")
    return summary


def _step_trace_extra(step: Dict[str, Any], state: ResearchState) -> Dict[str, Any]:
    """构造 per-invocation langsmith_extra：动态 span name + metadata + tags。"""
    tool = step.get("tool", "?")
    section_id = (step.get("args") or {}).get("section_id")
    name = f"step:{tool}[{section_id}]" if section_id else f"step:{tool}"
    phase = TOOL_TO_STEP_TYPE.get(tool, tool)
    return {
        "name": name,
        "metadata": {
            "replan_count": state.get("replan_count", 0),
            "step_id": step.get("step_id"),
        },
        "tags": [tool, phase],
    }


def pick_next_parallel_batch(
    plan: List[Dict[str, Any]],
    completed_steps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """选出下一批可执行的 step

    规则：
    1. 所有 depends_on 都在 completed 中（成功或失败均算 done）的 step 是 ready
    2. 已完成的 step 不再选
    3. ready 的 step 中，相同 parallel_group 的可一次返回（并行）
    4. parallel_group=None 的 step 一次只返回 1 个（串行）
    """
    completed_ids = {s["step_id"] for s in completed_steps}

    ready = []
    for step in plan:
        if step["step_id"] in completed_ids:
            continue
        deps = step.get("depends_on", [])
        if all(d in completed_ids for d in deps):
            ready.append(step)

    if not ready:
        return []

    first = ready[0]
    group = first.get("parallel_group")

    if group is None:
        return [first]

    return [s for s in ready if s.get("parallel_group") == group]


def all_steps_done(
    plan: List[Dict[str, Any]],
    completed_steps: List[Dict[str, Any]],
) -> bool:
    """plan 是否全部执行完（成功 + 失败都算 done）"""
    completed_ids = {s["step_id"] for s in completed_steps}
    return all(step["step_id"] in completed_ids for step in plan)


@traceable(run_type="tool",
           process_inputs=_trace_step_inputs,
           process_outputs=_trace_step_outputs)
async def execute_one_step(
    step: Dict[str, Any],
    state: ResearchState,
) -> Dict[str, Any]:
    """执行单个 step，返回 StepResult dict"""
    step_id = step["step_id"]
    tool_name = step["tool"]
    args = step.get("args", {})

    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        return {
            "step_id": step_id,
            "tool": tool_name,
            "status": "failed",
            "error": f"unknown tool: {tool_name}",
            "duration_ms": 0,
        }

    start = time.time()
    try:
        # 直接调底层 coroutine，绕过 @tool.ainvoke 的 pydantic schema 校验
        # （否则 ResearchState TypedDict 会被复制成新 dict，state mutation 不穿透）
        callable_fn = _resolve_callable(tool_fn)
        output = await callable_fn(**args, state=state)
        return {
            "step_id": step_id,
            "tool": tool_name,
            "status": "success",
            "output": output,
            "duration_ms": int((time.time() - start) * 1000),
        }
    except Exception as e:
        logger.exception(f"step {step_id} ({tool_name}) failed")
        return {
            "step_id": step_id,
            "tool": tool_name,
            "status": "failed",
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000),
        }


async def executor_node(state: ResearchState) -> Dict[str, Any]:
    """LangGraph node 入口

    循环：取下一批 ready step → 并行执行 → merge 结果 → 直到 done
    返回 state diff（completed_steps + 各 tool 输出字段）
    """
    plan = state.get("plan", [])
    completed = list(state.get("completed_steps", []))

    merged_facts = list(state.get("facts", []))
    merged_sources = list(state.get("raw_sources", []))
    sources_by_url = {s.get("url"): s for s in merged_sources if s.get("url")}
    merged_data_points = list(state.get("data_points", []))
    merged_charts = list(state.get("charts", []))
    merged_code_executions = list(state.get("code_executions", []))
    merged_insights = list(state.get("insights", []))
    merged_time_series = list(state.get("time_series", []))
    merged_distributions = list(state.get("distributions", []))
    merged_draft_sections = dict(state.get("draft_sections", {}))
    merged_critic_diagnostics = list(state.get("critic_diagnostics", []) or [])

    started_steps: Set[str] = set()

    # 入口检查一次：planner 跑完到 executor 调度前如果用户已经点 cancel，立刻退
    _maybe_cancel(state)

    while not all_steps_done(plan, completed):
        # 每批前再查：长 plan 可能跑十几个 batch，cancel 在任一 batch 边界生效
        _maybe_cancel(state)

        batch = pick_next_parallel_batch(plan, completed)
        if not batch:
            logger.error("executor deadlock: no ready steps but plan not done")
            break

        # 在批次开跑前，为本批次涉及的 step_type 建容器（前端 research_step:running）
        batch_step_types = {
            TOOL_TO_STEP_TYPE[s["tool"]]
            for s in batch
            if s["tool"] in TOOL_TO_STEP_TYPE
        }
        for st in batch_step_types:
            if st not in started_steps:
                _emit_step(st, status="running")
                started_steps.add(st)

        results = await _gather_with_cancel_watch(state, batch)

        for result in results:
            completed.append(result)
            if result["status"] != "success" or not result.get("output"):
                continue
            output = result["output"]

            if result["tool"] == "search_section":
                merged_facts.extend(output.get("facts", []))
                _merge_raw_sources(merged_sources, sources_by_url, output.get("sources", []))
            elif result["tool"] == "analyze_facts":
                merged_data_points.extend(output.get("data_points", []))
                merged_insights.extend(output.get("insights", []))
                merged_time_series.extend(output.get("time_series", []))
                merged_distributions.extend(output.get("distributions", []))
            elif result["tool"] == "generate_charts":
                merged_charts.extend(output.get("charts", []))
                merged_code_executions.extend(output.get("code_executions", []))
            elif result["tool"] == "write_section":
                sec_id = output.get("section_id")
                content = output.get("content", "")
                if sec_id:
                    before_content = merged_draft_sections.get(sec_id, "")
                    if output.get("revision_failed") is True:
                        content = before_content
                    merged_draft_sections[sec_id] = content

                    revision_keys = {
                        "addressed_issue_ids",
                        "unable_to_address",
                        "changes_made",
                        "revision_failed",
                    }
                    if any(key in output for key in revision_keys):
                        diagnostic = {
                            "type": "writer_revision",
                            "section_id": sec_id,
                            "addressed_issue_ids": output.get("addressed_issue_ids", []),
                            "unable_to_address": output.get("unable_to_address", []),
                            "changes_made": output.get("changes_made", []),
                            "before_hash": _hash_text(before_content),
                            "after_hash": _hash_text(content),
                        }
                        if "revision_failed" in output:
                            diagnostic["revision_failed"] = output["revision_failed"]
                        merged_critic_diagnostics.append(diagnostic)

        # 批次结束后，更新本批涉及 step_type 的累计 stats（仍 status=running，直到全 plan 完成）
        for st in batch_step_types:
            _emit_step(st, status="running", stats=_stats_for(
                st, merged_facts, merged_sources,
                merged_charts, merged_draft_sections,
            ))

    # 整个 plan 跑完后，把开过的每个 step_type 标 completed
    for st in started_steps:
        _emit_step(st, status="completed", stats=_stats_for(
            st, merged_facts, merged_sources,
            merged_charts, merged_draft_sections,
        ))

    # 按 outline 顺序拼装 final_report（并行写完后，draft_sections 的 dict
    # 顺序是完成顺序——必须按 outline 重排，否则报告章节会乱序）
    final_report = ""
    if merged_draft_sections:
        outline = state.get("outline", [])
        parts: List[str] = []
        for section in outline:
            sec_id = section.get("id")
            content = merged_draft_sections.get(sec_id, "").strip()
            if not content:
                continue
            # 单章节内容可能已包含 # 标题，也可能没有；统一在外层加 ## 标题
            title = section.get("title", sec_id)
            parts.append(f"## {title}\n\n{content}")
        # 兜底：outline 之外但 draft_sections 里有的（不应发生）追加在末尾
        seen_ids = {s.get("id") for s in outline}
        for sec_id, content in merged_draft_sections.items():
            if sec_id in seen_ids:
                continue
            stripped = (content or "").strip()
            if stripped:
                parts.append(f"## {sec_id}\n\n{stripped}")
        final_report = "\n\n".join(parts)

        # 通知前端用 outline 顺序的版本覆盖此前按到达顺序拼出来的 streamingReport
        _emit("report_draft", {
            "content": final_report,
            "word_count": len(final_report),
            "references_count": len(state.get("references", [])),
        })

    return {
        "completed_steps": completed,
        "facts": merged_facts,
        "raw_sources": merged_sources,
        "data_points": merged_data_points,
        "time_series": merged_time_series,
        "distributions": merged_distributions,
        "charts": merged_charts,
        "code_executions": merged_code_executions,
        "insights": merged_insights,
        "draft_sections": merged_draft_sections,
        "critic_diagnostics": merged_critic_diagnostics,
        "final_report": final_report,
    }
