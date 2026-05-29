# LangSmith Trace 清晰度完善 — 设计文档

> 日期：2026-05-29
> 范围：完善 `backend/app/service/deep_research_v2/` 的 LangSmith trace 结构，补齐 executor 下缺失的 step 层级，并为顶层 run 加 run_name / metadata / tags / replan 轮次标记
> 状态：📋 设计阶段（待用户审阅 → writing-plans）
> 前置决策：可观测性后端保持 LangSmith（不换 Langfuse，理由见对话：自托管 Langfuse v3 需 ClickHouse + 对象存储 + ~21GB，对个人项目过度工程）

---

## 1. 目标

让一次研究 run 在 LangSmith 里呈现为**层级清晰、可检索、可归因**的 trace 树：

- 每个 plan step（search_section / analyze_facts / generate_charts / write_section）形成独立 span，其内部的 LLM 调用嵌套在该 step 下
- 顶层 run 有可读名字（带 query）+ 可检索的 metadata（session_id / query）
- 可按 phase / agent / session 维度 tag 筛选
- 多轮 replan 的执行可通过 replan_count 区分

非目标（out of scope）：

| 不做 | 原因 |
|------|------|
| 换 Langfuse / 自建 dashboard | 已决策保持 LangSmith |
| cost 精确定价回填（deepseek/qwen 非 OpenAI 定价表）| LangSmith 自动记 token usage 已够；精确成本归因 YAGNI |
| 前端展示 trace | 与 SSE 协议无关 |

---

## 2. 现状诊断

当前 trace 树（`wrap_openai` + LangGraph node 自动 trace 已就位）：

```
graph run (默认名)
├── planner
│   └── Planner.planner.generate_plan        ← LLM span ✓
├── executor                                  ← 痛点
│   ├── DeepScout LLM call                    ┐ 6 路 search + analyze +
│   ├── DeepScout LLM call                    │ charts + 6 路 write 的
│   ├── ...                                   │ LLM 调用全部平铺，
│   └── LeadWriter LLM call ×6                ┘ 看不出归属哪个 step
├── critic
└── replanner
```

**根因**：6 个 agent 折叠进单个 executor node 后，`execute_one_step → tool → agent` 链路上的函数都是普通 async，不产生 span，故各 agent 的 `call_llm`（`wrap_openai` span）直接平铺在 executor 下。顶层 run 也没有 run_name / metadata，project 列表里难检索。

目标 trace 树：

```
research: <query 前 40 字>            ← run_name + metadata{session_id,query}
├── planner
│   └── Planner.planner.generate_plan
├── executor
│   ├── step:search_section[sec_1]    ← 新增 step span，记 args + 产出计数
│   │   └── DeepScout LLM call
│   ├── step:search_section[sec_2]
│   │   └── ...
│   ├── step:analyze_facts
│   │   └── DataAnalyst LLM call
│   └── step:write_section[sec_1]
│       └── LeadWriter LLM call
├── critic
└── replanner
```

---

## 3. 改进项

### ① 每个 plan step 一个 traceable span（核心）

- **位置**：`executor.py::execute_one_step`
- **做法**：用 `langsmith.traceable` 包裹（`run_type="tool"`）。调用时通过 `langsmith_extra` 动态设置 name = `step:{tool}[{section_id}]`（无 section_id 的 tool 用 `step:{tool}`）
- **关键设计 — 控制 span 输入输出不臃肿**：
  - 输入 **不记整个 state**（facts/sources 一大坨）。用 traceable 的 `process_inputs` 回调，只保留 `{tool, args, step_id}`
  - 输出用 `process_outputs` 裁剪为摘要：`{status, duration_ms, 产出计数}`（如 facts 数 / data_points 数 / chart 数 / 是否写出 section），不记完整内容
- **metadata**：`{replan_count, step_id}`（满足改进④）
- **tags**：`[tool_name, phase]`（满足改进③的 step 层）

### ② 顶层 run_name + metadata

- **位置**：`graph.py::_run_with_langgraph` 的 `self.graph.astream(state, ...)` 调用
- **做法**：传 `RunnableConfig`，含
  - `run_name = f"research: {query[:40]}"`
  - `metadata = {"session_id": ..., "query": ...}`
  - `tags = ["deep_research_v3", session_id]`
- query 从 `state["query"]` 取

### ③ 统一 tags（分布在三处）

| 层级 | tags | 位置 |
|------|------|------|
| 顶层 run | `["deep_research_v3", session_id]` | graph.astream config（②内完成）|
| step span | `[tool_name, phase]` | execute_one_step traceable（①内完成）|
| LLM span | `[agent_name, action]` | base.py（已存在，无需改）|

### ④ replan 轮次标记

- step span 的 metadata 带 `replan_count`（取自 `state.get("replan_count", 0)`）——①内完成
- 效果：多轮 replan 后，LangSmith 里按 metadata.replan_count 即可区分"第几轮执行的 step"

---

## 4. 兼容与降级

- **langsmith 未安装**：`from langsmith import traceable` 失败时提供 no-op `traceable`（同 base.py 对 `wrap_openai` 的 try/except 处理），保证非 langsmith 环境照常运行
- **LANGSMITH_TRACING 未开启**：traceable 自身为零开销 passthrough，不产生 span，功能不受影响
- **asyncio.gather 下的父子关系**：step span 在并行 batch（`asyncio.gather`）下的嵌套依赖 contextvar 传播，与已落地的 `AsyncOpenAI`（解决 wrap_openai 嵌套）同源，预期正常；需在 LangSmith UI 手动确认一次

---

## 5. 测试策略

- **回归**：现有 34 个 v3 测试在 traceable 包裹后应继续全绿（traceable 默认 no-op，不改变返回值）
- **新增单测**：
  - `execute_one_step` 在 traceable 包裹下仍返回结构正确的 StepResult（status/output/duration_ms 不变）
  - no-op fallback：模拟 `langsmith` import 失败，`traceable` 仍可调用且不报错
- **手动验证**（LangSmith UI，不进 CI）：
  - run 列表里能按 `research: <query>` 找到本次 run
  - executor 下出现 `step:*` 层级，LLM 调用嵌套其中
  - 触发一次 replan，确认 step span 的 metadata.replan_count 第二轮为 1

---

## 6. 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/app/service/deep_research_v2/executor.py` | `execute_one_step` 加 traceable + process_inputs/outputs 裁剪 + name/metadata/tags；顶部加 traceable 的 try/except no-op import |
| `backend/app/service/deep_research_v2/graph.py` | `_run_with_langgraph` 的 astream 传 run_name/metadata/tags config |
| `backend/test/test_deep_research_v3/test_executor.py` | 新增 traceable 包裹回归 + no-op fallback 测试 |

---

## 7. 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| traceable 在 gather 下未正确嵌套（contextvar 丢失）| step span 平铺而非嵌套 | 与 AsyncOpenAI 同源，预期正常；UI 手动验证；若丢失则改用显式 run_tree 传递 |
| process_inputs/outputs 裁剪遗漏，state 泄漏进 trace | trace 臃肿 / 潜在敏感数据 | 白名单式只保留指定字段，而非黑名单删除 |
| astream config 传参方式与当前 LangGraph 版本不符 | run_name 不生效 | 实现时对照 langgraph 1.2.1 的 RunnableConfig 字段确认 |
