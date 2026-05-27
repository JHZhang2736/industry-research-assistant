"""DeepResearch v3 - Executor node + 并行调度逻辑

Executor 负责按 plan 调度 tools，处理并行组，merge tool 返回结果到 state。
不直接调 LLM，只做调度。
"""

import time
import asyncio
import logging
from typing import Dict, Any, List

from .state import ResearchState
from .tools import search_section, analyze_facts, generate_charts, write_section

logger = logging.getLogger("deep_research_v3.executor")


TOOL_REGISTRY = {
    "search_section": search_section,
    "analyze_facts": analyze_facts,
    "generate_charts": generate_charts,
    "write_section": write_section,
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
        output = await tool_fn.ainvoke({**args, "state": state})
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
    merged_data_points = list(state.get("data_points", []))
    merged_knowledge_graph = {
        "nodes": list(state.get("knowledge_graph", {}).get("nodes", [])),
        "edges": list(state.get("knowledge_graph", {}).get("edges", [])),
    }
    merged_charts = list(state.get("charts", []))
    merged_code_executions = list(state.get("code_executions", []))
    merged_insights = list(state.get("insights", []))
    merged_draft_sections = dict(state.get("draft_sections", {}))

    while not all_steps_done(plan, completed):
        batch = pick_next_parallel_batch(plan, completed)
        if not batch:
            logger.error("executor deadlock: no ready steps but plan not done")
            break

        results = await asyncio.gather(*[
            execute_one_step(step, state) for step in batch
        ])

        for result in results:
            completed.append(result)
            if result["status"] != "success" or not result.get("output"):
                continue
            output = result["output"]

            if result["tool"] == "search_section":
                merged_facts.extend(output.get("facts", []))
                merged_sources.extend(output.get("sources", []))
            elif result["tool"] == "analyze_facts":
                merged_data_points.extend(output.get("data_points", []))
                kg = output.get("knowledge_graph", {})
                if kg:
                    merged_knowledge_graph["nodes"].extend(kg.get("nodes", []))
                    merged_knowledge_graph["edges"].extend(kg.get("edges", []))
                merged_insights.extend(output.get("insights", []))
            elif result["tool"] == "generate_charts":
                merged_charts.extend(output.get("charts", []))
                merged_code_executions.extend(output.get("code_executions", []))
            elif result["tool"] == "write_section":
                sec_id = output.get("section_id")
                content = output.get("content", "")
                if sec_id:
                    merged_draft_sections[sec_id] = content

    return {
        "completed_steps": completed,
        "facts": merged_facts,
        "raw_sources": merged_sources,
        "data_points": merged_data_points,
        "knowledge_graph": merged_knowledge_graph,
        "charts": merged_charts,
        "code_executions": merged_code_executions,
        "insights": merged_insights,
        "draft_sections": merged_draft_sections,
    }
