# LangSmith Trace 清晰度完善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一次研究 run 在 LangSmith 里呈现为层级清晰、可检索的 trace 树——每个 plan step 形成独立 span（内部 LLM 调用嵌套其下），顶层 run 带可读 run_name + metadata + tags + replan 轮次。

**Architecture:** 用 `langsmith.traceable` 包裹 `executor.py::execute_one_step`，配 `process_inputs`/`process_outputs` 把巨大的 `state` 裁剪成摘要避免 trace 臃肿；调用处用 `langsmith_extra` 做 per-invocation 的动态 span name / metadata / tags。顶层在 `graph.py` 的 `astream` 传 `RunnableConfig`（run_name/metadata/tags）。所有改动在未装 langsmith 或未开 `LANGSMITH_TRACING` 时均为零开销 no-op。

**Tech Stack:** Python 3.12, langsmith 0.8.5（`traceable` 装饰器 + `langsmith_extra`）, langgraph 1.2.1（`astream(config=...)`）, pytest。

---

## File Structure

| 文件 | 责任 | 改动类型 |
|------|------|---------|
| `backend/app/service/deep_research_v2/executor.py` | 调度 + 现在加 step 级 trace span | 加 no-op traceable import、3 个 trace 辅助纯函数、装饰 `execute_one_step`、调用处传 `langsmith_extra` |
| `backend/app/service/deep_research_v2/graph.py` | 主图驱动 | `_run_with_langgraph` 的 `astream` 传 trace config |
| `backend/test/test_deep_research_v3/test_executor.py` | executor 单测 | 新增 4 个 trace 辅助函数测试 |

Task 顺序：先 Task 1 落地可单测的纯函数（含 no-op import），再 Task 2 把它们接到 `execute_one_step`（靠回归保护），最后 Task 3 顶层 run config。

---

### Task 1: trace 辅助纯函数 + no-op traceable import

**Files:**
- Modify: `backend/app/service/deep_research_v2/executor.py`（顶部 import 区；在 `_emit_step` 之后、`pick_next_parallel_batch` 之前插入辅助函数）
- Test: `backend/test/test_deep_research_v3/test_executor.py`

- [ ] **Step 1: 写失败测试**

在 `backend/test/test_deep_research_v3/test_executor.py` 末尾追加：

```python
def test_trace_step_inputs_drops_state():
    """process_inputs 只保留 tool/args/step_id，丢掉巨大的 state"""
    from app.service.deep_research_v2.executor import _trace_step_inputs
    inputs = {
        "step": {"step_id": "s1", "tool": "search_section",
                 "args": {"section_id": "sec_1", "queries": ["q"]}},
        "state": {"facts": [1, 2, 3], "raw_sources": [1, 2]},
    }
    out = _trace_step_inputs(inputs)
    assert out == {"tool": "search_section",
                   "args": {"section_id": "sec_1", "queries": ["q"]},
                   "step_id": "s1"}
    assert "state" not in out


def test_trace_step_outputs_summarizes_counts():
    """process_outputs 把 StepResult 压成计数摘要，不带完整 facts"""
    from app.service.deep_research_v2.executor import _trace_step_outputs
    step_result = {
        "step_id": "s1", "tool": "search_section", "status": "success",
        "duration_ms": 1234,
        "output": {"facts": [1, 2, 3], "sources": [1, 2], "section_id": "sec_1"},
    }
    out = _trace_step_outputs(step_result)
    assert out["status"] == "success"
    assert out["duration_ms"] == 1234
    assert out["facts_count"] == 3
    assert out["sources_count"] == 2
    assert "facts" not in out  # 不泄漏完整内容


def test_step_trace_extra_name_with_section():
    """有 section_id 的 step → span name 带 [sec_x]，metadata 含 replan_count"""
    from app.service.deep_research_v2.executor import _step_trace_extra
    step = {"step_id": "s1", "tool": "search_section", "args": {"section_id": "sec_2"}}
    state = {"replan_count": 1}
    extra = _step_trace_extra(step, state)
    assert extra["name"] == "step:search_section[sec_2]"
    assert extra["metadata"]["replan_count"] == 1
    assert extra["metadata"]["step_id"] == "s1"
    assert "search_section" in extra["tags"]


def test_step_trace_extra_name_without_section():
    """无 section_id 的 step → span name 不带方括号，replan_count 缺省 0"""
    from app.service.deep_research_v2.executor import _step_trace_extra
    step = {"step_id": "s7", "tool": "analyze_facts", "args": {}}
    state = {}
    extra = _step_trace_extra(step, state)
    assert extra["name"] == "step:analyze_facts"
    assert extra["metadata"]["replan_count"] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_executor.py -k "trace_step or step_trace" -v`
Expected: FAIL，`ImportError: cannot import name '_trace_step_inputs'`（函数还没定义）

- [ ] **Step 3: 加 no-op traceable import**

在 `backend/app/service/deep_research_v2/executor.py` 顶部，把第 7-10 行的 import 块改为（加入 `functools`）：

```python
import time
import asyncio
import functools
import logging
from typing import Dict, Any, List, Set
```

紧接 `is_research_cancelled` 的 try/except 块之后（约第 24 行之后、`logger = ...` 之前）插入：

```python
# LangSmith traceable：给每个 plan step 建独立 span。未安装 langsmith 时退化为
# 吃掉 langsmith_extra 的透传装饰器（no-op），保证非 langsmith 环境照常运行。
try:
    from langsmith import traceable
except ImportError:
    def traceable(*d_args, **d_kwargs):
        def _decorator(fn):
            @functools.wraps(fn)
            async def _wrapper(*args, **kwargs):
                kwargs.pop("langsmith_extra", None)
                return await fn(*args, **kwargs)
            return _wrapper
        if len(d_args) == 1 and callable(d_args[0]) and not d_kwargs:
            return _decorator(d_args[0])
        return _decorator
```

- [ ] **Step 4: 加 3 个 trace 辅助纯函数**

在 `backend/app/service/deep_research_v2/executor.py` 的 `_emit_step` 函数之后、`pick_next_parallel_batch` 之前插入（此处 `TOOL_TO_STEP_TYPE` 已在前面定义）：

```python
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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_executor.py -k "trace_step or step_trace" -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/service/deep_research_v2/executor.py backend/test/test_deep_research_v3/test_executor.py
git commit -m "feat(trace): add step-span input/output trimming + langsmith_extra builder

Pure helpers for LangSmith step spans: _trace_step_inputs drops the bulky
state, _trace_step_outputs summarizes StepResult to counts, _step_trace_extra
builds per-invocation name/metadata/tags. No-op traceable fallback when
langsmith is absent.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: 装饰 execute_one_step + 调用处传 langsmith_extra

**Files:**
- Modify: `backend/app/service/deep_research_v2/executor.py`（`execute_one_step` 加装饰器；`_gather_with_cancel_watch` 的 gather 列表推导传 `langsmith_extra`）
- Test: 复用现有 `backend/test/test_deep_research_v3/test_executor.py` 全量回归

- [ ] **Step 1: 给 execute_one_step 加 traceable 装饰器**

在 `backend/app/service/deep_research_v2/executor.py` 找到 `async def execute_one_step(`（约第 212 行），在其上方加装饰器：

```python
@traceable(run_type="tool",
           process_inputs=_trace_step_inputs,
           process_outputs=_trace_step_outputs)
async def execute_one_step(
    step: Dict[str, Any],
    state: ResearchState,
) -> Dict[str, Any]:
    """执行单个 step，返回 StepResult dict"""
```

函数体保持不变。

- [ ] **Step 2: 调用处传 langsmith_extra（动态 name/metadata/tags）**

在 `backend/app/service/deep_research_v2/executor.py` 的 `_gather_with_cancel_watch` 里，把 gather 列表推导（约第 52-54 行）改为：

```python
    gather_future = asyncio.gather(*[
        execute_one_step(step, state, langsmith_extra=_step_trace_extra(step, state))
        for step in batch
    ])
```

- [ ] **Step 3: 跑全量 executor 测试确认无回归**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_executor.py -v`
Expected: 全部 passed（原有调度测试 + Task 1 的 4 个 trace 测试）。说明：测试环境未设 `LANGSMITH_TRACING`，traceable 消费 `langsmith_extra` 后零开销执行原函数，返回值不变。

- [ ] **Step 4: 跑全量 v3 测试确认无回归**

Run: `cd backend && python -m pytest test/test_deep_research_v3/ -q`
Expected: 全部 passed（应为 38 个：原 34 + Task 1 新增 4）

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/executor.py
git commit -m "feat(trace): wrap execute_one_step in a traceable step span

Each plan step now nests its agent LLM calls under a step:<tool>[<section>]
span with replan_count/step_id metadata and [tool, phase] tags. Input/output
trimmed via process_inputs/outputs so state never bloats the trace.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: 顶层 run_name + metadata + tags

**Files:**
- Modify: `backend/app/service/deep_research_v2/graph.py`（`_run_with_langgraph` 的 `astream` 调用）
- Test: 复用现有 `backend/test/test_deep_research_v3/test_graph_integration.py` 回归

- [ ] **Step 1: 在 astream 前构造 trace config 并传入**

在 `backend/app/service/deep_research_v2/graph.py` 的 `_run_with_langgraph` 方法里，找到 `async for mode, chunk in self.graph.astream(` 这段。在它前面（`try:` 之内、astream 之前）插入 trace config 构造，并给 astream 加 `config=` 参数。改动后该段形如：

```python
        query = state.get("query", "")
        trace_config = {
            "run_name": f"research: {query[:40]}" if query else "research",
            "metadata": {"session_id": session_id, "query": query},
            "tags": ["deep_research_v3"] + ([session_id] if session_id else []),
        }

        try:
            async for mode, chunk in self.graph.astream(
                state,
                config=trace_config,
                stream_mode=["custom", "updates"],
            ):
```

注意：`session_id` 在 `_run_with_langgraph` 开头已有定义（`session_id = state.get("session_id", "")`）；`query` 为新增局部变量。若 `query` 变量名在该作用域已存在则复用、不要重复定义。

- [ ] **Step 2: 跑 graph 集成测试确认无回归**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_graph_integration.py -v`
Expected: 全部 passed（compile 4-node + 路由测试不受 astream config 影响）

- [ ] **Step 3: 跑全量 v3 测试**

Run: `cd backend && python -m pytest test/test_deep_research_v3/ -q`
Expected: 全部 passed（38 个）

- [ ] **Step 4: Commit**

```bash
git add backend/app/service/deep_research_v2/graph.py
git commit -m "feat(trace): name the top-level run + attach session/query metadata

astream now passes run_name 'research: <query>' plus metadata
{session_id, query} and tags [deep_research_v3, session_id], so runs are
findable and filterable in the LangSmith project list.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 手动验证（LangSmith UI，不进 CI）

实现完成后，设 `LANGSMITH_TRACING=true`（`.env` 已有 `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT`），重启后端跑一次研究，在 https://smith.langchain.com 对应 project 确认：

1. run 列表里能按 `research: <query>` 找到本次 run
2. `executor` 节点下出现 `step:search_section[sec_1]` 等 step span，agent 的 LLM 调用嵌套其中（不再平铺）
3. step span 的 Input 只有 `{tool, args, step_id}`，Output 只有计数摘要（无完整 facts）
4. 触发一次 replan（critic 评分 <7），确认第二轮 step span 的 `metadata.replan_count == 1`

若第 2 点中 step span 未嵌套而是平铺（contextvar 在 `asyncio.gather` 下丢失），回退方案见 spec §7：改用显式 run_tree 传递。

---

## Notes
- DRY / YAGNI / TDD / 频繁提交。
- 三个 task 顺序有依赖：Task 2 用到 Task 1 定义的函数，Task 3 独立但建议最后做。
- 不改 `base.py`（LLM span 的 tags 已就位）。
