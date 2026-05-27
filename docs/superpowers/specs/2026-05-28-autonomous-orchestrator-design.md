# Autonomous Orchestrator Design — Industry Research Assistant

> 日期：2026-05-28
> 范围：将 `backend/app/service/deep_research_v2/` 从 hard-coded LangGraph workflow 重构为 **Plan-and-Execute supervisor 架构**，sub-agents 作为 tool 暴露；配套引入 **Higress AI Gateway** 统一治理多供应商、**LangSmith** 深度装点 trace
> 状态：📋 设计阶段（待用户审阅 → writing-plans）

---

## 1. 目标与非目标

### 1.1 目标

- 把现有 6-agent **静态 DAG workflow** 重构为 **autonomous Plan-and-Execute orchestrator**，使 multi-agent 调度由 LLM 决策而非代码硬编码
- 通过 **Send API** 实现章节级 fan-out（search × N、write × 6 并行），消除 ADR-003 阶段三的 TODO
- 引入 **Higress AI Gateway** 统一治理 DashScope / DeepSeek / OpenRouter 三家 LLM 供应商，提供多供应商 fallback + 统一 token 统计
- **LangSmith** 深度装点：自定义 `run_name` / `tags` / `metadata` / `cost`，使 multi-agent 调用链可审查、可成本归因
- 重构后**前端 SSE 协议零改动**，端到端体验（流式 / 检查点续作 / 取消）不退步
- 简历产出一段可定量讲解的架构演进故事 + 一篇技术博客

### 1.2 非目标（明确不做，独立项目处理）

| 项 | 推迟到 |
|---|---|
| **Memory 系统**（semantic / episodic / procedural） | 独立窗口，用户已明确等本期完成后另开 |
| **ReAct fallback 完整实现** | 本期仅预留 conditional edge 接口（`should_fallback` 恒 False + TODO），第二期依据 eval 数据决定 |
| **eval A/B 跑分** | 用户在本期完成后自行测试；开发期不以 eval 数据作为 gate |
| **AsyncPostgresSaver 替换 checkpoint_service** | ADR-003 阶段二，独立窗口 |
| **LangSmith 自建 dashboard** | YAGNI，先用 LangSmith UI |
| **Higress 内容审计 / consumer 体系 / TLS** | YAGNI，本期只做路由 + fallback + token 统计 |
| **前端"自主模式 vs workflow 模式"开关** | YAGNI，本期直接替换 v2 |
| **Human-in-the-loop `interrupt()`** | 独立窗口 |
| **claude-sonnet-4-6 作为 planner** | 用户明确放弃；改用 deepseek-v3.2 |

---

## 2. 关键决策清单

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| 2.1 | **Agent pattern** | **Plan-and-Execute**（planner / executor / critic / replanner 4 node）+ 预留 ReAct fallback 接口 | 流水线场景适合 P&E；token 成本可控；天然支持 Send API 并行；YAGNI 起步，eval 数据决定是否补 fallback |
| 2.2 | **Planner / Replanner 模型** | `deepseek-v3.2`（DashScope OpenAI 兼容模式）| 现有项目主力、function calling 稳定、成本极低、不引入访问稳定性风险 |
| 2.3 | **执行框架** | LangGraph 0.2+（不抛弃，自然扩展 ADR-003 阶段一）| LangGraph Supervisor pattern 是官方推荐做法；流式 / 检查点 / 取消免费复用 |
| 2.4 | **Sub-agent 模型** | 沿用现有混搭（Scout=qwen-plus，其他=deepseek-v3.2）| 模型混搭决策已在 ADR-004 论证 |
| 2.5 | **Architect 处理** | 吸收进 planner（删除 `architect.py`）| planner 的职责就是 outline + 任务清单，Architect 独立无价值 |
| 2.6 | **兼容策略** | 替换 v2（不并存 v3）| 干净彻底；eval A/B 通过 git checkout 旧 commit 跑 |
| 2.7 | **Higress 部署位置** | 阿里云 ECS（已有部署链路，PR #15）| 简历可写"生产环境部署"，比本地 Docker 含金量高 |
| 2.8 | **Higress 治理范围** | 路由 + 多供应商 fallback + token 统计 + rate limit | 前 4 项是简历故事的核心；内容审计 YAGNI |
| 2.9 | **LangSmith 集成深度** | 中等（自定义 run_name / tags / metadata / cost）| 不自建 UI，但定制化 trace 内容使可审查性具备 |
| 2.10 | **开发期通过标准** | 端到端能跑通 + SSE / 检查点 / 取消 / 前端零改动 | eval A/B 由用户在完成后自测，不阻塞开发 |

---

## 3. 总体架构

### 3.1 新 graph 结构

```
                  ┌─────────┐
            ┌───→ │ planner │ ←─── initial（query 输入）
            │     └────┬────┘
            │          │ plan = [PlanStep(...), ...]
            │          ↓
            │     ┌──────────┐
            │     │ executor │ 按 plan 调 tools；Send API 章节级并行
            │     └────┬─────┘
            │          │ all steps done
            │          ↓
            │     ┌────────┐
            │     │ critic │ 评 quality_score / unresolved_issues
            │     └────┬───┘
            │          │
            │   ┌──────┼──────────────────────────┐
            │   ↓      ↓                          ↓
            │  END   replanner               [should_fallback=False
            │ (pass) (issues>0                 → 预留 ReAct supervisor,
            │        & iter<max)                第二期实现]
            │          │
            └──────────┘
```

### 3.2 6 个 sub-agent 在新架构里的位置

| 旧角色 | 新身份 | 文件改动 |
|--------|--------|---------|
| ChiefArchitect | **吸收进 planner**（不再独立调用）| `agents/architect.py` 删除；prompt 迁入 `agents/planner.py` |
| DeepScout | `search_section` tool | `agents/scout.py` 改造为 `@tool` 装饰函数 |
| DataAnalyst | `analyze_facts` tool | `agents/data_analyst.py` 改造 |
| CodeWizard | `generate_charts` tool | `agents/wizard.py` 改造 |
| LeadWriter | `write_section` tool | `agents/writer.py` 改造 |
| CriticMaster | **保留为独立 node**（不当 tool）| `agents/critic.py` 改为 LangGraph node 形态 |
| —（新增）| planner | `agents/planner.py` 新建 |
| —（新增）| replanner | `agents/replanner.py` 新建 |

### 3.3 ResearchState 字段变化

**新增**：
```python
plan: list[PlanStep]              # planner 输出，executor 消费
completed_steps: list[StepResult] # 已完成步骤的结果
replan_count: int                 # 累计 replan 次数（控制上限，默认 max=3）
fallback_triggered: bool          # 是否进入 ReAct fallback（本期恒 False）
```

`PlanStep` 结构：
```python
@dataclass
class PlanStep:
    step_id: str                   # 唯一 ID
    tool: str                      # tool 名称（search_section / analyze_facts / ...）
    args: dict                     # tool 参数
    depends_on: list[str]          # 依赖的前置 step_id（用于推导并行批次）
    parallel_group: str | None     # 同 group 内的 step 用 Send API 并行
```

**保留不变**：`query` / `outline` / `facts` / `data_points` / `charts` / `draft_sections` / `final_report` / `critic_feedback` / `quality_score` / `messages` 等。

**移除**：
- `phase: ResearchPhase` 字段（由 graph 当前 node 推导）
- `_should_revise()` 函数（被 critic → replanner 的 conditional edge 替代）

### 3.4 Send API 章节并行

executor 在分发 plan 时，按 `parallel_group` 字段决定串行/并行：

```python
def dispatch_step(state: ResearchState):
    next_batch = pick_next_parallel_batch(state["plan"], state["completed_steps"])
    if len(next_batch) == 1:
        return next_batch[0].tool  # 串行
    return [
        Send(step.tool, {"step": step, "state": state})
        for step in next_batch
    ]  # 并行
```

典型 plan 的 parallel_group 设计：
- `search_section[sec_1..sec_6]` → 同 group，6 路并行
- `analyze_facts` → 串行（依赖所有 search 完成）
- `generate_charts` → 串行（依赖 analyze）
- `write_section[sec_1..sec_6]` → 同 group，6 路并行

---

## 4. 组件设计

### 4.1 Planner

**职责**：接收 query，输出 outline + 完整 plan（含并行分组）。

**实现要点**：
- 使用 `with_structured_output(PlanSchema)` 强 schema，解析失败时本地降级模板兜底
- prompt 模板复用现有 Architect 的"行业研究 6 章节"基线，叠加"输出 plan 任务清单 + parallel_group 标注"指令
- 单次 LLM 调用产出 outline + plan

**输入**：`state["query"]` + （resume 时）`state` 现有内容
**输出**：`{"outline": [...], "plan": [PlanStep, ...], "messages": [...]}`

### 4.2 Executor

**职责**：按 plan 调度 tools，处理 Send API 并行，写回结果到 state。

**实现要点**：
- 不直接调 LLM；只做调度逻辑
- 每个 tool 调用结果 append 到 `completed_steps`
- 失败 step 重试上限 2 次（保留现有 sub-agent 的重试语义）
- 共享 ResearchState 给所有 tool（read），tool 返回结果由 executor merge 到 state（write）

### 4.3 Sub-agent → Tool 改造（示例）

```python
from langchain_core.tools import tool

@tool
async def search_section(
    section_id: str,
    queries: list[str],
    state: ResearchState,
) -> dict:
    """对一个章节执行多 query 搜索 + fact 提取。
    
    Args:
        section_id: outline 里的章节 ID（sec_1 ~ sec_6）
        queries: 这个章节要搜的关键词列表
        state: 共享 ResearchState（read-only 在 tool 内）
    
    Returns:
        {"facts": [Fact, ...], "sources": [Source, ...], "cost": {...}}
    """
    scout = DeepScout(config=...)
    return await scout.search_with_queries(section_id, queries, state)
```

**改造规则**（适用所有 6 个 sub-agent）：
- 每个 tool 保留现有 agent 的所有能力（流式 `add_message` / 并发 Semaphore / 重试 / JSON 解析）
- 入口标准化为 `@tool` 装饰，参数加 type hint + docstring（给 LLM tool description）
- tool 内部仍走 `BaseAgent.add_message` → `get_stream_writer()` 流式
- **tool 只读 state，不写 state**；返回 dict 由 executor merge 到 state。**只有 4 个 node（planner / executor / critic / replanner）可直接写 state**

### 4.4 Critic（保留 node 形态）

**职责**：评估 executor 产出的 `draft_sections`，输出 `quality_score` + `unresolved_issues` + 建议动作。

**改动**：
- 现有 `_should_revise()` 函数 → 删除
- Critic 输出新字段 `suggested_actions: list[str]`（如 `["retry_search:sec_3", "rewrite:sec_5"]`），供 replanner 消费

### 4.5 Replanner

**职责**：根据 critic 的 `suggested_actions` 生成补救 plan，写回 `state["plan"]`，让 executor 重跑增量步骤。

**实现要点**：
- 输入：现有 state + critic_feedback
- 输出：新的 `plan`（仅含补救步骤）+ `replan_count += 1`
- 上限：`replan_count >= 3` 强制走 END（避免死循环）
- 与 planner 同模型（deepseek-v3.2），prompt 模板独立

### 4.6 ReAct Fallback 接口预留

```python
def route_after_replanner(state: ResearchState) -> str:
    if state["replan_count"] >= MAX_REPLAN:
        return END
    if state.get("fallback_triggered", False):  # 本期恒 False
        return "supervisor_fallback"  # 预留分支，节点不实现
    return "executor"

# TODO(phase-2): 实现 supervisor_fallback node
# 触发条件：连续 3 次 replan 后 unresolved_issues 仍 > 0
# 该 node 用 deepseek-v3.2.bind_tools(all_tools) 自由 ReAct
```

---

## 5. Higress AI Gateway 集成

### 5.1 部署形态

```
backend (FastAPI on ECS)
    │
    │ POST /v1/chat/completions
    │ Authorization: Bearer <higress-key>
    │ Model: dashscope/qwen-plus | deepseek/deepseek-v3.2 | openrouter/...
    ↓
Higress :8080 (同 ECS 或独立 ECS)
    │
    ├─→ dashscope.aliyuncs.com/compatible-mode/v1 (qwen-plus, deepseek-v3.2 阿里通道)
    ├─→ api.deepseek.com/v1                       (deepseek-v3.2 官方)
    └─→ openrouter.ai/api/v1                      (兜底，所有模型)
```

### 5.2 启用的 Higress 插件

| 插件 | 配置 | 简历价值 |
|------|------|---------|
| `ai-proxy` | 按 model name 前缀路由到对应 upstream；主供应商失败自动 failover 到备 | ⭐⭐⭐⭐⭐ 多供应商容灾故事核心 |
| `ai-token-statistics` | 按 consumer × model 维度落 Prometheus / 日志 | ⭐⭐⭐⭐ 给 LangSmith trace 回填 cost 字段的数据源 |
| `ai-token-ratelimit` | 按 token / qpm 限流，替换现有 provider Semaphore | ⭐⭐⭐⭐ 统一治理 |
| access log | JSON 格式落本地，可选 ES | ⭐⭐⭐ 审计 + debug |

### 5.3 后端改动

- `backend/app/service/config.py`：新增 `HIGRESS_BASE_URL`、`HIGRESS_API_KEY` 配置
- `backend/app/service/deep_research_v2/agents/base.py::call_llm`：
  - `base_url` 统一切到 `HIGRESS_BASE_URL`
  - 模型名加 provider 前缀（如 `dashscope/qwen-plus`、`deepseek/deepseek-v3.2`）
- **删除** `backend/app/service/deep_research_v2/concurrency.py` 的 provider Semaphore（Higress 接管限流）

### 5.4 配置文件位置

- `infra/higress/config.yaml` 新建，提交到仓库
- 部署脚本扩展现有 PR #15 的 ECS deploy workflow：先 docker-compose up higress，再 deploy backend

---

## 6. LangSmith 深度装点

### 6.1 接入清单

```python
# 环境变量
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=industry-research-assistant
LANGCHAIN_API_KEY=ls__...

# 装点策略
# 1. 每个 LangGraph node：自动 trace（LangSmith 原生）
# 2. 每个 sub-agent tool：用 @traceable 装饰器手动加 run_name
# 3. critic / planner / replanner 输出：在 metadata 里塞 quality_score / replan_count / plan_step_count
# 4. 每次 LLM 调用：从 Higress token 统计响应头回填 cost 字段
```

### 6.2 trace 结构（面试可视化范例）

```
research_run [tags: v3, P&E, model_mix]
├── planner.v3 [model: deepseek-v3.2, plan_steps: 14, cost: ¥0.012]
│   └── output: {outline: [...], plan: [PlanStep × 14]}
├── executor [tags: parallel_batch_1]
│   ├── tool.search_section[sec_1] [model: qwen-plus, cost: ¥0.003]
│   ├── tool.search_section[sec_2] [parallel via Send API]
│   ├── tool.search_section[sec_3..sec_6]
│   ├── tool.analyze_facts [model: deepseek-v3.2]
│   ├── tool.generate_charts [model: deepseek-v3.2, py_exec: true]
│   └── tool.write_section[sec_X] × 6 [parallel]
├── critic [model: deepseek-v3.2, quality_score: 7.2, unresolved: 2]
└── replanner.v3 [iter: 1, action: retry_search]
    └── (回 executor with patch plan)
```

### 6.3 简历可写

> "为 multi-agent run 设计结构化 LangSmith trace schema（run_name / tags / cost metadata），结合 Higress 落地的 token 统计回填到 trace，使 multi-agent 调用链可审查、可成本归因"

---

## 7. 兼容性与回滚

### 7.1 前端兼容

- SSE 事件 type 保持现有契约：`phase` / `agent_thinking` / `search_progress` / `chart_ready` / `section_draft` / `quality_score` / `research_complete` / `error`
- 后端在 planner / executor / critic / replanner 各 node 内继续 emit 上述事件，type 字段不变
- **前端零改动作为兼容性硬 gate**：本期任何破坏前端 SSE 协议的改动都视为不通过

### 7.2 检查点与续作

- 沿用现有 `research_checkpoints` 表 + `checkpoint_service.py`（不引入 AsyncPostgresSaver，那是 ADR-003 阶段二）
- 在 planner / executor / critic / replanner 每个 node 完成后通过 LangGraph `updates` stream 触发 save
- `state` 字段变化（新增 plan / completed_steps / replan_count）通过 alembic migration 不必动（state_json 是 JSONB，schema-less）

### 7.3 取消

- 沿用 Redis `research:cancel:{session_id}` 标志
- 每个 node 入口 + tool 内长循环点继续轮询 `_maybe_cancel`
- LangGraph `task.cancel()` 作为正常路径，Redis flag 作跨进程兜底

### 7.4 回滚策略

- 重构在独立 branch（如 `feat/autonomous-orchestrator`）开发，PR 形式合并 main
- 任何阶段失败可 `git revert` 回 ADR-003 阶段一的 main 状态
- Higress 切流通过 `HIGRESS_ENABLED=true/false` 环境变量控制，紧急情况可回退到直连 provider endpoint

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| **Planner 计划质量不稳定**：deepseek-v3.2 输出的 plan JSON 格式偶尔不规范 | executor 跑不动 | 用 `with_structured_output(PlanSchema)` 强 schema；解析失败时本地降级模板兜底（按 query 类型预制 3 套 plan 模板）|
| **Higress 部署遇坑**（路由配置 / 文档少 / 阿里云镜像源问题）| 第 3 周延期 | Week 1 末就在本地 Docker 把 Higress 配置打通；Week 3 只搬运到 ECS |
| **现有 v2 代码大幅改动引入回归**：流式 / 取消 / 续作 | 用户体验回退 | 每个 sub-tool 改造后跑 smoke test；前端零改动作为硬 gate |
| **Send API 并行打爆 LLM 限流** | 章节并行任务报错 | Higress rate limit 兜底；planner 在 `parallel_group` 字段里标注最大并发上限 |
| **本期范围超 4 周** | 后续 Memory 项目挤压 | Section 9 in-scope 已严格收口；如 Week 3 末 Higress 未通，把 Higress 推到第二期、本期只做架构重构 |
| **deepseek-v3.2 function calling 在多 tool 场景下失稳** | planner 输出 plan 不规范 | 备选方案：planner 不用 function calling，改用 structured output；replanner 同理 |

---

## 9. 范围（in / out scope 终稿）

### 9.1 in scope（必做）

1. Plan-and-Execute graph（planner / executor / critic / replanner 4 node）跑通
2. 6 个 sub-agent 改造成 `@tool`（保留模型混搭、流式、并发、重试）
3. Architect 吸收进 planner，`architect.py` 删除
4. Send API 章节级并行（search × N、write × 6）
5. ReAct fallback 接口预留（不实现）：`should_fallback` 条件边存在但恒 False + TODO 注释
6. Higress 部署到阿里云 ECS（基于 PR #15 部署链路扩展）
7. `call_llm` 切流到 Higress，模型名加 provider 前缀
8. Higress 多供应商 fallback 配置（DashScope 主 + DeepSeek 备 + OpenRouter 兜底）
9. Higress token 统计 + rate limit 启用
10. LangSmith 中等深度装点（run_name / tags / metadata / cost 回填）
11. 检查点续作 + 取消机制在新架构下仍工作
12. 前端 SSE 协议零改动
13. 一篇技术博客 draft（架构演进 + 决策推导）

### 9.2 out of scope（独立处理）

| 项 | 处理方式 |
|---|---|
| Memory 系统 | 独立窗口 |
| ReAct fallback 实现 | 第二期 |
| eval A/B 跑分 | 用户自测 |
| AsyncPostgresSaver | ADR-003 阶段二 |
| LangSmith 自建 dashboard | YAGNI |
| Higress 内容审计 / consumer / TLS | YAGNI |
| 前端"自主 vs workflow"开关 | YAGNI |
| Human-in-the-loop interrupt | 独立窗口 |

---

## 10. 时间表

```
Week 1   ┃ planner / executor / critic / replanner 4 node 实现
         ┃ + sub-agent tool 化（base.py 加 @tool 适配层）
         ┃ + ResearchState 字段调整 + 单元测试
Week 2   ┃ Send API 并行 + 端到端冒烟（前端零改动 gate）
         ┃ + 检查点续作 / 取消验证
         ┃ + 本地 Docker 跑通 Higress
Week 3   ┃ Higress 部署 ECS（扩展 PR #15）
         ┃ + call_llm 切流 + 多供应商 fallback 配置
         ┃ + Higress token 统计接入
Week 4   ┃ LangSmith 装点完成（run_name / tags / cost 回填）
         ┃ + 技术博客 draft
         ┃ + 简历条目定稿
         ┃ + 移交给用户做 eval A/B
```

---

## 11. 简历叙事（终稿草案）

### 11.1 项目条目

> **行业研究多 Agent 系统 / 自主架构演进**（个人项目，2026.05-06）
> - 将 6-agent 研究系统从 **hard-coded LangGraph workflow** 重构为 **Plan-and-Execute supervisor 架构**（基于 LangGraph 0.2+ Supervisor pattern，预留 ReAct fallback），sub-agents 作为 tool 暴露
> - 通过 **Send API** 实现章节级 fan-out，search / write 阶段 6 路并行
> - 引入 **Higress AI Gateway**（部署于阿里云 ECS）统一治理 DashScope / DeepSeek / OpenRouter 三家供应商，配置多供应商 fallback + token 统计 + rate limit
> - **LangSmith** 深度装点 trace（自定义 run_name / tags / cost metadata），实现 multi-agent 调用链可审查 + 成本归因
> - 配套 7 维 / 3 家族 LLM-as-judge eval 框架（先期完成）端到端 A/B 量化新旧架构表现

### 11.2 面试 talk track（30 秒电梯版）

> "我把项目原本基于 LangGraph 写死的 multi-agent workflow，重构成 Plan-and-Execute supervisor —— planner 用 deepseek-v3.2 出完整任务计划，executor 通过 Send API 并行调度 search / write 这种章节级任务，critic 评估后由 replanner 决定是否补救。配套引入 Higress 网关统一治理多供应商（DashScope + DeepSeek + OpenRouter），LangSmith 做 trace 装点支持可审查。我选 P&E 而不是纯 ReAct 是因为在 deep research 这种 tool 调用结构稳定的流水线任务里，ReAct 每步 LLM 决策的 token 成本翻倍且无法批量并行；但 review 后的修订循环灵活性需求高，我在 replanner 之外预留了 ReAct fallback 接口，留给 eval 数据驱动决策是否启用。"

### 11.3 可深挖的面试问题清单

| 问题 | 准备的回答方向 |
|------|--------------|
| 为什么选 P&E 而不是纯 ReAct？ | token 成本 + 并行能力 + 流水线场景特性 |
| 为什么不一开始就做 fallback？ | YAGNI + 数据驱动决策 + 预留扩展点 |
| Higress 相比 LiteLLM 的差异？ | 云原生 / 阿里生态 / 插件体系 / 跟进新技术能力的体现 |
| planner 输出格式不稳怎么办？ | structured output + 本地降级模板 + JSON 多段防御解析（已在 BaseAgent 里）|
| 章节并行的 LLM 限流怎么处理？ | Higress rate limit + planner 在 parallel_group 标最大并发 |
| 怎么证明新架构比旧的好？ | eval 框架 7 维 A/B + paired t-test（用户自测后补数据）|

---

## 12. 索引

- [01-项目整体分析](../../01-项目整体分析.md) — 项目定位、技术栈、Agent 架构总览
- [02-架构决策记录](../../02-架构决策记录.md) — ADR-001~004
- [eval-framework-interview-brief](../../eval-framework-interview-brief.md) — 5/26 完成的 eval 框架
- [2026-05-26-eval-framework-design](2026-05-26-eval-framework-design.md) — eval 框架 spec
- [2026-05-27-search-pipeline-optimization-design](2026-05-27-search-pipeline-optimization-design.md) — 5/27 并发优化 spec
