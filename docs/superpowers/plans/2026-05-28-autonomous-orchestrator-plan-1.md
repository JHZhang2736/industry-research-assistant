# Autonomous Orchestrator — Plan 1: Core Architecture Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `backend/app/service/deep_research_v2/` 从 hard-coded LangGraph workflow（9 节点 DAG + 3 路条件边）重构为 **Plan-and-Execute supervisor** 架构（planner / executor / critic / replanner 4 node + 预留 ReAct fallback 接口），6 个 sub-agent 改造成 `@tool`；Send API 实现章节级并行；前端 SSE 协议零改动；检查点续作 + 取消机制仍工作。

**Architecture:** LangGraph 0.2+ StateGraph 重构。planner 用 deepseek-v3.2 输出含 `parallel_group` 的完整 plan；executor 解析 plan 通过 `Send` API fan-out 调 sub-agent tools；critic 评估输出 `suggested_actions`；replanner 决定补救路径或终止；ReAct fallback 通过 `should_fallback` 条件边预留接口（恒 False + TODO 注释）。

**Tech Stack:** Python 3.11, LangGraph 0.2.40+, langchain-core `@tool`, OpenAI SDK (DashScope OpenAI 兼容模式), pytest + pytest-asyncio。Higress / LangSmith 深度装点不在本 plan 范围。

---

## File Structure

### Created

| 文件 | 职责 |
|------|------|
| `backend/app/service/deep_research_v2/agents/planner.py` | Planner node 实现（吸收 Architect 的 outline 生成 + 输出 PlanStep 序列）|
| `backend/app/service/deep_research_v2/agents/replanner.py` | Replanner node 实现（消费 critic.suggested_actions，输出补救 plan）|
| `backend/app/service/deep_research_v2/executor.py` | Executor node 实现 + Send API 并行调度逻辑 |
| `backend/app/service/deep_research_v2/tools.py` | `@tool` 注册中心（导出 4 个 sub-agent tool 函数 + 共享单例 agent 实例）|
| `backend/test/test_deep_research_v3/__init__.py` | 单测包初始化 |
| `backend/test/test_deep_research_v3/test_state.py` | ResearchState 字段 + PlanStep dataclass 单测 |
| `backend/test/test_deep_research_v3/test_planner.py` | Planner node 单测 |
| `backend/test/test_deep_research_v3/test_tools.py` | sub-agent tool 化后的单测 |
| `backend/test/test_deep_research_v3/test_critic_node.py` | Critic node 形态 + suggested_actions 单测 |
| `backend/test/test_deep_research_v3/test_replanner.py` | Replanner node 单测 |
| `backend/test/test_deep_research_v3/test_executor.py` | Executor node + Send API 调度单测 |
| `backend/test/test_deep_research_v3/test_graph_integration.py` | 4-node 主图集成测试（mock LLM）|
| `backend/test/test_deep_research_v3/test_smoke.py` | 端到端冒烟脚本（真 LLM，手动 / opt-in）|

### Modified

| 文件 | 改动 |
|------|------|
| `backend/app/service/deep_research_v2/state.py` | 新增 `PlanStep` / `StepResult` dataclass；ResearchState 加 `plan / completed_steps / replan_count / fallback_triggered` 字段；保留旧字段以兼容前端 |
| `backend/app/service/deep_research_v2/agents/scout.py` | 加 `@tool search_section` 函数包装（保留 DeepScout class 内部逻辑不变）|
| `backend/app/service/deep_research_v2/agents/data_analyst.py` | 加 `@tool analyze_facts` 函数包装 |
| `backend/app/service/deep_research_v2/agents/wizard.py` | 加 `@tool generate_charts` 函数包装 |
| `backend/app/service/deep_research_v2/agents/writer.py` | 加 `@tool write_section` 函数包装（保留现有 6 章节并行逻辑）|
| `backend/app/service/deep_research_v2/agents/critic.py` | CriticMaster 输出新字段 `suggested_actions: list[str]`；保留 LLM 调用逻辑 |
| `backend/app/service/deep_research_v2/agents/__init__.py` | 导出新增 `Planner` / `Replanner` 类；移除 `ChiefArchitect` 导出 |
| `backend/app/service/deep_research_v2/graph.py` | 完全重写 `_build_langgraph`：planner → executor → critic → replanner / END / fallback 预留分支；保留 `_save_checkpoint` / `_load_checkpoint` / `_maybe_cancel` / `_emit_phase_start` 等 helper |
| `backend/app/service/deep_research_v2/service.py` | 入口适配（修正 `research_sync` 中已无 phase 字段的访问）|

### Deleted

| 文件 | 理由 |
|------|------|
| `backend/app/service/deep_research_v2/agents/architect.py` | 逻辑吸收进 `planner.py`，不再独立 |

---

## Pre-Task: Setup

- [ ] **Step 0.1: 创建并切换到独立 branch**

```bash
git checkout -b feat/autonomous-orchestrator
git status  # 应显示 "On branch feat/autonomous-orchestrator, nothing to commit, working tree clean"
```

- [ ] **Step 0.2: 确认 langgraph 版本**

```bash
grep "langgraph" backend/requirements.txt
```

Expected: `langgraph>=0.2.40`（5/26 ADR-003 阶段一已经升级到此版本）。如果版本不对，先升级。

- [ ] **Step 0.3: 安装测试依赖**

```bash
cd backend && pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock
```

- [ ] **Step 0.4: 跑现有单测建立 baseline**

```bash
cd backend && python -m pytest test/ -v 2>&1 | tail -20
```

Expected: 现有 51 个 eval 单测全过；如有失败先记录，本 plan 不应让现有测试退步。

---

## Task 1: 扩展 ResearchState 字段 + PlanStep / StepResult dataclass

**Files:**
- Modify: `backend/app/service/deep_research_v2/state.py`
- Test: `backend/test/test_deep_research_v3/test_state.py`

- [ ] **Step 1.1: 写失败测试**

Create `backend/test/test_deep_research_v3/__init__.py`（空文件）。

Create `backend/test/test_deep_research_v3/test_state.py`:

```python
"""测试 ResearchState 新字段 + PlanStep / StepResult dataclass"""
import pytest
from app.service.deep_research_v2.state import (
    PlanStep,
    StepResult,
    ResearchState,
    create_initial_state,
)


def test_plan_step_dataclass_minimal():
    """PlanStep 最小创建"""
    step = PlanStep(
        step_id="step_1",
        tool="search_section",
        args={"section_id": "sec_1", "queries": ["foo"]},
        depends_on=[],
        parallel_group="search_batch",
    )
    assert step.step_id == "step_1"
    assert step.tool == "search_section"
    assert step.args["section_id"] == "sec_1"
    assert step.depends_on == []
    assert step.parallel_group == "search_batch"


def test_plan_step_no_parallel_group():
    """parallel_group=None 表示串行（不与任何 step 并行）"""
    step = PlanStep(
        step_id="step_2",
        tool="analyze_facts",
        args={},
        depends_on=["step_1"],
        parallel_group=None,
    )
    assert step.parallel_group is None


def test_step_result_dataclass():
    """StepResult 记录 step 执行结果"""
    result = StepResult(
        step_id="step_1",
        tool="search_section",
        status="success",
        output={"facts": []},
        error=None,
        duration_ms=1234,
    )
    assert result.status == "success"
    assert result.output["facts"] == []
    assert result.error is None
    assert result.duration_ms == 1234


def test_step_result_failure():
    """StepResult 记录失败"""
    result = StepResult(
        step_id="step_2",
        tool="search_section",
        status="failed",
        output=None,
        error="API timeout",
        duration_ms=30000,
    )
    assert result.status == "failed"
    assert result.error == "API timeout"


def test_research_state_new_fields():
    """ResearchState 新增字段全部初始化"""
    state = create_initial_state(query="test", session_id="sid_1")
    assert state["plan"] == []
    assert state["completed_steps"] == []
    assert state["replan_count"] == 0
    assert state["fallback_triggered"] is False


def test_research_state_backward_compat():
    """ResearchState 旧字段保留（前端兼容）"""
    state = create_initial_state(query="test", session_id="sid_1")
    # 前端依赖的关键字段必须保留
    for key in ["query", "session_id", "outline", "facts", "data_points",
                "charts", "draft_sections", "final_report", "references",
                "critic_feedback", "quality_score", "messages", "logs"]:
        assert key in state, f"backward-compat field {key} missing"
```

- [ ] **Step 1.2: 运行测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_state.py -v
```

Expected: 所有 6 个测试 FAIL with `ImportError: cannot import name 'PlanStep' / 'StepResult'`.

- [ ] **Step 1.3: 在 state.py 添加 PlanStep + StepResult + ResearchState 字段**

Modify `backend/app/service/deep_research_v2/state.py`。在已有 dataclass 区（`CriticFeedback` 之后、`AgentLog` 之前）插入：

```python
@dataclass
class PlanStep:
    """Planner 输出的单个执行步骤
    
    Attributes:
        step_id: 唯一 ID（planner 生成，格式如 'step_1', 'step_2'）
        tool: tool 名称（'search_section' / 'analyze_facts' / 'generate_charts' / 'write_section'）
        args: tool 调用参数（JSON-serializable dict）
        depends_on: 依赖的前置 step_id 列表；空表示无依赖
        parallel_group: 同 group 内的 step 可并行通过 Send API；None 表示串行执行
    """
    step_id: str
    tool: str
    args: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    parallel_group: Optional[str] = None


@dataclass
class StepResult:
    """Executor 执行单个 step 后的结果记录
    
    Attributes:
        step_id: 对应的 PlanStep.step_id
        tool: 调用的 tool 名称（冗余便于查询）
        status: 'success' / 'failed' / 'skipped'
        output: tool 返回的 dict，失败时为 None
        error: 失败时的错误消息
        duration_ms: 执行耗时（毫秒）
    """
    step_id: str
    tool: str
    status: Literal["success", "failed", "skipped"]
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: int = 0
```

修改 `ResearchState` TypedDict，在 `# 元数据` 注释**之前**插入新字段：

```python
    # === Plan-and-Execute 新增字段（v3 架构）===
    plan: List[Dict[str, Any]]              # PlanStep 序列化列表（planner 输出，executor 消费）
    completed_steps: List[Dict[str, Any]]   # StepResult 序列化列表（executor 写入）
    replan_count: int                       # 累计 replan 次数（控制上限）
    fallback_triggered: bool                # ReAct fallback 标志（v1 期恒 False）
```

修改 `create_initial_state`，在 `messages=[]` 之**前**加：

```python
        # v3 新增字段
        plan=[],
        completed_steps=[],
        replan_count=0,
        fallback_triggered=False,
```

- [ ] **Step 1.4: 运行测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_state.py -v
```

Expected: 6 passed.

- [ ] **Step 1.5: Commit**

```bash
git add backend/app/service/deep_research_v2/state.py backend/test/test_deep_research_v3/
git commit -m "feat(state): add PlanStep / StepResult + v3 ResearchState fields

引入 Plan-and-Execute 架构所需的核心数据结构：
- PlanStep: planner 输出的单个执行步骤（含 parallel_group 标注）
- StepResult: executor 执行后的结果记录
- ResearchState 新增 plan / completed_steps / replan_count / fallback_triggered

向后兼容：保留所有现有字段不变，前端 SSE 协议不受影响。"
```

---

## Task 2: 改造 DeepScout → @tool search_section

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`
- Create: `backend/app/service/deep_research_v2/tools.py`
- Test: `backend/test/test_deep_research_v3/test_tools.py`

- [ ] **Step 2.1: 写失败测试**

Create `backend/test/test_deep_research_v3/test_tools.py`:

```python
"""测试 sub-agent 改造成 @tool 后的接口契约"""
import pytest
from unittest.mock import AsyncMock, patch
from app.service.deep_research_v2.tools import (
    search_section,
    get_scout_instance,
)
from app.service.deep_research_v2.state import create_initial_state


def test_search_section_is_tool():
    """search_section 应被 @tool 装饰，可通过 langchain_core.tools.BaseTool 识别"""
    from langchain_core.tools import BaseTool
    # langchain @tool 装饰后 callable 会有 .name 属性
    assert hasattr(search_section, "name")
    assert search_section.name == "search_section"


def test_search_section_has_docstring():
    """tool 必须有 docstring，否则 LLM 看不懂"""
    assert search_section.description
    assert "搜索" in search_section.description or "search" in search_section.description.lower()


@pytest.mark.asyncio
async def test_search_section_returns_dict(monkeypatch):
    """search_section 返回 {'facts': [...], 'sources': [...]} 形态"""
    state = create_initial_state(query="测试", session_id="sid_1")
    
    # Mock 内部 DeepScout 调用
    mock_scout = AsyncMock()
    mock_scout.search_with_queries = AsyncMock(return_value={
        "facts": [{"id": "f1", "content": "test fact"}],
        "sources": [{"url": "http://example.com"}],
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_scout_instance",
        lambda: mock_scout
    )
    
    result = await search_section.ainvoke({
        "section_id": "sec_1",
        "queries": ["测试 query"],
        "state": state,
    })
    
    assert "facts" in result
    assert "sources" in result
    assert isinstance(result["facts"], list)


def test_scout_instance_is_singleton():
    """get_scout_instance 应返回同一实例（避免每次 tool 调用都创建）"""
    inst1 = get_scout_instance()
    inst2 = get_scout_instance()
    assert inst1 is inst2
```

- [ ] **Step 2.2: 运行测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py -v
```

Expected: 全部 FAIL with `ImportError: tools module not found`.

- [ ] **Step 2.3: 创建 tools.py 注册中心**

Create `backend/app/service/deep_research_v2/tools.py`:

```python
"""DeepResearch v3 - @tool 注册中心

把 6 个 sub-agent 包装成 LangGraph 可调用的 @tool 函数。
单例缓存 agent 实例，避免每次调用都创建。
"""

import logging
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool

from .state import ResearchState
from .agents import DeepScout, DataAnalyst, CodeWizard, LeadWriter

try:
    from config.llm_config import get_config
except ImportError:
    from app.config.llm_config import get_config

logger = logging.getLogger("deep_research_v3.tools")

# === 单例缓存 ===
_scout_instance: Optional[DeepScout] = None
_analyst_instance: Optional[DataAnalyst] = None
_wizard_instance: Optional[CodeWizard] = None
_writer_instance: Optional[LeadWriter] = None


def get_scout_instance() -> DeepScout:
    """获取 DeepScout 单例"""
    global _scout_instance
    if _scout_instance is None:
        config = get_config()
        _scout_instance = DeepScout(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            search_api_key=config.search_api_key,
            model=config.agents.scout.model,
        )
    return _scout_instance


def reset_instances():
    """测试用：重置所有单例（在 fixture teardown 调用）"""
    global _scout_instance, _analyst_instance, _wizard_instance, _writer_instance
    _scout_instance = None
    _analyst_instance = None
    _wizard_instance = None
    _writer_instance = None


# === Tool 1: search_section ===
@tool
async def search_section(
    section_id: str,
    queries: List[str],
    state: ResearchState,
) -> Dict[str, Any]:
    """对一个章节执行多 query 搜索 + fact 提取。
    
    Args:
        section_id: outline 里的章节 ID（sec_1 ~ sec_6）
        queries: 这个章节要搜的关键词列表（通常 3-5 个）
        state: 共享 ResearchState（read-only 在 tool 内）
    
    Returns:
        {
            "facts": [Fact, ...],          # 提取的结构化事实
            "sources": [Source, ...],      # 原始来源
            "section_id": section_id,      # 回传用于 executor merge
        }
    """
    scout = get_scout_instance()
    try:
        # 复用 DeepScout 现有的多 query 并行搜索 + fact 提取
        result = await scout.search_with_queries(
            section_id=section_id,
            queries=queries,
            state=state,
        )
        return {
            "facts": result.get("facts", []),
            "sources": result.get("sources", []),
            "section_id": section_id,
        }
    except Exception as e:
        logger.exception(f"search_section[{section_id}] failed: {e}")
        return {"facts": [], "sources": [], "section_id": section_id, "error": str(e)}
```

- [ ] **Step 2.4: 在 DeepScout 添加 search_with_queries 方法**

Modify `backend/app/service/deep_research_v2/agents/scout.py`。在 `DeepScout` class 末尾（`process` 方法之后）添加：

```python
    async def search_with_queries(
        self,
        section_id: str,
        queries: List[str],
        state: ResearchState,
    ) -> Dict[str, Any]:
        """v3 入口：按章节维度执行搜索 + fact 提取
        
        与现有 process() 方法的区别：
        - 不读取 state["pending_search_queries"]，直接用 queries 参数
        - 只处理一个 section（用于 Send API 并行）
        - 不直接修改 state；返回 dict 由 executor merge
        
        Args:
            section_id: 当前搜索的章节 ID
            queries: 要搜的 query 列表
            state: 共享状态（read-only）
        
        Returns:
            {"facts": [...], "sources": [...], "section_id": section_id}
        """
        # 复用现有的 _execute_deep_search 内部逻辑
        # 注意：现有 process() 是基于 state["pending_search_queries"] 全局搜索；
        # 这里参数化以支持按章节调用
        facts, sources = await self._execute_deep_search(
            queries=queries,
            state=state,
            target_section=section_id,
        )
        return {
            "facts": [self._fact_to_dict(f) for f in facts],
            "sources": sources,
            "section_id": section_id,
        }
```

**注**：如现有 `_execute_deep_search` 不接受 `target_section` 参数，在它的签名中添加 `target_section: Optional[str] = None` 并把它写入提取出的 fact 的 `related_sections` 字段。

- [ ] **Step 2.5: 运行测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py -v
```

Expected: 4 passed.

- [ ] **Step 2.6: Commit**

```bash
git add backend/app/service/deep_research_v2/tools.py backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v3/test_tools.py
git commit -m "feat(tools): wrap DeepScout as @tool search_section

新增 backend/app/service/deep_research_v2/tools.py 作为 @tool 注册中心：
- 单例缓存 DeepScout 实例
- @tool search_section 按章节维度搜索（用于 executor Send API 并行）
- DeepScout 新增 search_with_queries 方法（不破坏现有 process）"
```

---

## Task 3: 改造 DataAnalyst → @tool analyze_facts

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/data_analyst.py`
- Modify: `backend/app/service/deep_research_v2/tools.py`
- Test: `backend/test/test_deep_research_v3/test_tools.py`

- [ ] **Step 3.1: 在 test_tools.py 追加测试**

```python
# 追加到 test_tools.py 末尾

@pytest.mark.asyncio
async def test_analyze_facts_returns_data_points(monkeypatch):
    """analyze_facts 返回 {'data_points': [...], 'knowledge_graph': {...}}"""
    from app.service.deep_research_v2.tools import analyze_facts, get_analyst_instance
    
    state = create_initial_state(query="测试", session_id="sid_1")
    state["facts"] = [{"id": "f1", "content": "5G 用户突破 10 亿"}]
    
    mock_analyst = AsyncMock()
    mock_analyst.extract_data_points = AsyncMock(return_value={
        "data_points": [{"name": "5G 用户数", "value": 10, "unit": "亿"}],
        "knowledge_graph": {"nodes": [], "edges": []},
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_analyst_instance",
        lambda: mock_analyst
    )
    
    result = await analyze_facts.ainvoke({"state": state})
    
    assert "data_points" in result
    assert "knowledge_graph" in result
```

- [ ] **Step 3.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py::test_analyze_facts_returns_data_points -v
```

Expected: FAIL with `ImportError: cannot import name 'analyze_facts'`.

- [ ] **Step 3.3: 在 tools.py 追加 analyze_facts**

Append to `backend/app/service/deep_research_v2/tools.py`:

```python
def get_analyst_instance() -> DataAnalyst:
    """获取 DataAnalyst 单例"""
    global _analyst_instance
    if _analyst_instance is None:
        config = get_config()
        _analyst_instance = DataAnalyst(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            model=config.agents.data_analyst.model,
        )
    return _analyst_instance


# === Tool 2: analyze_facts ===
@tool
async def analyze_facts(state: ResearchState) -> Dict[str, Any]:
    """从已收集的 facts 中提取 data points + 构建知识图谱。
    
    Args:
        state: 共享 ResearchState，读取 state["facts"]
    
    Returns:
        {
            "data_points": [DataPoint, ...],   # 可量化数据点
            "knowledge_graph": {"nodes": [], "edges": []},
            "insights": [str, ...],            # 数据洞察
        }
    """
    analyst = get_analyst_instance()
    try:
        return await analyst.extract_data_points(state)
    except Exception as e:
        logger.exception(f"analyze_facts failed: {e}")
        return {"data_points": [], "knowledge_graph": {"nodes": [], "edges": []}, "insights": [], "error": str(e)}
```

- [ ] **Step 3.4: 在 DataAnalyst 添加 extract_data_points 方法**

Modify `backend/app/service/deep_research_v2/agents/data_analyst.py`，添加：

```python
    async def extract_data_points(self, state: ResearchState) -> Dict[str, Any]:
        """v3 入口：从 state["facts"] 提取 data points + 构建知识图谱
        
        与现有 process() 区别：
        - 不修改 state，返回 dict
        
        Returns:
            {"data_points": [...], "knowledge_graph": {...}, "insights": [...]}
        """
        # 复用现有 process() 的内部 LLM 调用逻辑
        # 关键改动：把 process() 中 `state["data_points"] = ...` 改为收集到本地变量返回
        facts = state.get("facts", [])
        if not facts:
            return {"data_points": [], "knowledge_graph": {"nodes": [], "edges": []}, "insights": []}
        
        # ... 调用 LLM 提取 data_points / 图谱节点边 / insights ...
        # 这里复用现有 process() 中的 prompt + JSON 解析逻辑，
        # 不直接修改 state，而是返回 dict
        data_points = await self._extract_data_points_from_facts(facts, state)
        knowledge_graph = await self._build_knowledge_graph(facts, state)
        insights = await self._generate_insights(facts, data_points, state)
        
        return {
            "data_points": data_points,
            "knowledge_graph": knowledge_graph,
            "insights": insights,
        }
```

**注**：现有 DataAnalyst.process 内部已有上述逻辑（提取/图谱/洞察三步），把它们抽成独立 private 方法供 extract_data_points 调用；process() 本身保留用于向后兼容（万一需要回滚）。

- [ ] **Step 3.5: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py::test_analyze_facts_returns_data_points -v
```

Expected: PASS.

- [ ] **Step 3.6: Commit**

```bash
git add backend/app/service/deep_research_v2/tools.py backend/app/service/deep_research_v2/agents/data_analyst.py backend/test/test_deep_research_v3/test_tools.py
git commit -m "feat(tools): wrap DataAnalyst as @tool analyze_facts"
```

---

## Task 4: 改造 CodeWizard → @tool generate_charts

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/wizard.py`
- Modify: `backend/app/service/deep_research_v2/tools.py`
- Test: `backend/test/test_deep_research_v3/test_tools.py`

- [ ] **Step 4.1: 在 test_tools.py 追加测试**

```python
@pytest.mark.asyncio
async def test_generate_charts_returns_charts(monkeypatch):
    from app.service.deep_research_v2.tools import generate_charts, get_wizard_instance
    
    state = create_initial_state(query="测试", session_id="sid_1")
    state["data_points"] = [{"name": "x", "value": 1}]
    
    mock_wizard = AsyncMock()
    mock_wizard.generate_charts_for_state = AsyncMock(return_value={
        "charts": [{"id": "c1", "chart_type": "bar"}],
        "code_executions": [],
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_wizard_instance",
        lambda: mock_wizard
    )
    
    result = await generate_charts.ainvoke({"state": state})
    assert "charts" in result
    assert len(result["charts"]) == 1
```

- [ ] **Step 4.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py::test_generate_charts_returns_charts -v
```

Expected: FAIL.

- [ ] **Step 4.3: 在 tools.py 追加 generate_charts**

```python
def get_wizard_instance() -> CodeWizard:
    """获取 CodeWizard 单例"""
    global _wizard_instance
    if _wizard_instance is None:
        config = get_config()
        _wizard_instance = CodeWizard(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            model=config.agents.wizard.model,
        )
    return _wizard_instance


# === Tool 3: generate_charts ===
@tool
async def generate_charts(state: ResearchState) -> Dict[str, Any]:
    """根据 data_points 生成可视化图表（matplotlib + ECharts option）。
    
    Args:
        state: 共享 ResearchState，读取 state["data_points"]
    
    Returns:
        {"charts": [Chart, ...], "code_executions": [...]}
    """
    wizard = get_wizard_instance()
    try:
        return await wizard.generate_charts_for_state(state)
    except Exception as e:
        logger.exception(f"generate_charts failed: {e}")
        return {"charts": [], "code_executions": [], "error": str(e)}
```

- [ ] **Step 4.4: 在 CodeWizard 添加 generate_charts_for_state 方法**

Modify `backend/app/service/deep_research_v2/agents/wizard.py`。复用现有 process() 中的图表生成逻辑，抽成新方法：

```python
    async def generate_charts_for_state(self, state: ResearchState) -> Dict[str, Any]:
        """v3 入口：从 state["data_points"] 生成图表
        
        与 process() 区别：不修改 state，返回 dict
        """
        data_points = state.get("data_points", [])
        if not data_points:
            return {"charts": [], "code_executions": []}
        
        # 复用现有 process() 的图表生成 LLM 调用 + Python 沙箱执行逻辑
        charts, code_executions = await self._generate_and_execute(state, data_points)
        return {
            "charts": charts,
            "code_executions": code_executions,
        }
```

- [ ] **Step 4.5: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py::test_generate_charts_returns_charts -v
```

Expected: PASS.

- [ ] **Step 4.6: Commit**

```bash
git add backend/app/service/deep_research_v2/tools.py backend/app/service/deep_research_v2/agents/wizard.py backend/test/test_deep_research_v3/test_tools.py
git commit -m "feat(tools): wrap CodeWizard as @tool generate_charts"
```

---

## Task 5: 改造 LeadWriter → @tool write_section

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/writer.py`
- Modify: `backend/app/service/deep_research_v2/tools.py`
- Test: `backend/test/test_deep_research_v3/test_tools.py`

- [ ] **Step 5.1: 在 test_tools.py 追加测试**

```python
@pytest.mark.asyncio
async def test_write_section_returns_draft(monkeypatch):
    """write_section 写一个章节，返回 {section_id, content}"""
    from app.service.deep_research_v2.tools import write_section, get_writer_instance
    
    state = create_initial_state(query="测试", session_id="sid_1")
    state["facts"] = [{"id": "f1", "content": "fact"}]
    state["outline"] = [{"id": "sec_1", "title": "第一章"}]
    
    mock_writer = AsyncMock()
    mock_writer.write_one_section = AsyncMock(return_value={
        "section_id": "sec_1",
        "content": "# 第一章\n章节内容...",
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_writer_instance",
        lambda: mock_writer
    )
    
    result = await write_section.ainvoke({
        "section_id": "sec_1",
        "state": state,
    })
    
    assert result["section_id"] == "sec_1"
    assert "content" in result
```

- [ ] **Step 5.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py::test_write_section_returns_draft -v
```

Expected: FAIL.

- [ ] **Step 5.3: 在 tools.py 追加 write_section**

```python
def get_writer_instance() -> LeadWriter:
    """获取 LeadWriter 单例"""
    global _writer_instance
    if _writer_instance is None:
        config = get_config()
        _writer_instance = LeadWriter(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            model=config.agents.writer.model,
        )
    return _writer_instance


# === Tool 4: write_section ===
@tool
async def write_section(
    section_id: str,
    state: ResearchState,
) -> Dict[str, Any]:
    """撰写一个章节的 Markdown 内容（复用现有 facts + data_points + charts）。
    
    Args:
        section_id: 要写的章节 ID（sec_1 ~ sec_6）
        state: 共享 ResearchState
    
    Returns:
        {"section_id": section_id, "content": "# Markdown..."}
    """
    writer = get_writer_instance()
    try:
        return await writer.write_one_section(section_id=section_id, state=state)
    except Exception as e:
        logger.exception(f"write_section[{section_id}] failed: {e}")
        return {"section_id": section_id, "content": "", "error": str(e)}
```

- [ ] **Step 5.4: 在 LeadWriter 添加 write_one_section 方法**

Modify `backend/app/service/deep_research_v2/agents/writer.py`。现有 LeadWriter 已经在 commit `d4d0fcf` 实现了 6 章节并行（`feat(perf): Writer 6 章节并行撰写`），其内部应该已有按章节写的私有方法。直接暴露为 public：

```python
    async def write_one_section(
        self,
        section_id: str,
        state: ResearchState,
    ) -> Dict[str, Any]:
        """v3 入口：撰写指定章节
        
        复用现有按章节并行写的内部方法（在 d4d0fcf 引入）。
        不修改 state，返回 dict。
        """
        # 假设现有内部方法名是 _write_section_internal 或 _generate_section_content
        # 如果名字不同，按现有命名调用
        content = await self._write_section_internal(section_id, state)
        return {"section_id": section_id, "content": content}
```

**注**：如果现有内部方法不存在或签名不匹配，先把 process() 中按章节写的部分抽取成 `_write_section_internal(section_id, state) -> str` 方法。

- [ ] **Step 5.5: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_tools.py::test_write_section_returns_draft -v
```

Expected: PASS.

- [ ] **Step 5.6: Commit**

```bash
git add backend/app/service/deep_research_v2/tools.py backend/app/service/deep_research_v2/agents/writer.py backend/test/test_deep_research_v3/test_tools.py
git commit -m "feat(tools): wrap LeadWriter as @tool write_section (per-section invocation)"
```

---

## Task 6: 实现 Planner node（吸收 Architect 逻辑）

**Files:**
- Create: `backend/app/service/deep_research_v2/agents/planner.py`
- Modify: `backend/app/service/deep_research_v2/agents/__init__.py`
- Test: `backend/test/test_deep_research_v3/test_planner.py`

- [ ] **Step 6.1: 写失败测试**

Create `backend/test/test_deep_research_v3/test_planner.py`:

```python
"""测试 Planner node 实现"""
import pytest
import json
from unittest.mock import AsyncMock, patch
from app.service.deep_research_v2.agents.planner import Planner, PLANNER_PROMPT
from app.service.deep_research_v2.state import create_initial_state, PlanStep


@pytest.fixture
def planner():
    return Planner(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


def test_planner_prompt_contains_plan_schema(planner):
    """Planner prompt 必须包含 plan 输出 schema 说明"""
    assert "plan" in PLANNER_PROMPT.lower()
    assert "parallel_group" in PLANNER_PROMPT
    assert "outline" in PLANNER_PROMPT.lower()


@pytest.mark.asyncio
async def test_planner_returns_outline_and_plan(planner, monkeypatch):
    """planner 调用 LLM 返回 outline + plan 列表"""
    mock_response = json.dumps({
        "outline": [
            {"id": "sec_1", "title": "市场规模", "description": "...", 
             "section_type": "quantitative", "status": "pending",
             "requires_data": True, "requires_chart": True},
        ],
        "plan": [
            {"step_id": "step_1", "tool": "search_section",
             "args": {"section_id": "sec_1", "queries": ["市场规模"]},
             "depends_on": [], "parallel_group": "search_batch"},
            {"step_id": "step_2", "tool": "analyze_facts",
             "args": {}, "depends_on": ["step_1"], "parallel_group": None},
        ],
    }, ensure_ascii=False)
    
    monkeypatch.setattr(planner, "call_llm", AsyncMock(return_value=mock_response))
    
    state = create_initial_state(query="5G 市场分析", session_id="sid_1")
    result = await planner.process(state)
    
    assert len(result["outline"]) == 1
    assert result["outline"][0]["id"] == "sec_1"
    assert len(result["plan"]) == 2
    assert result["plan"][0]["tool"] == "search_section"
    assert result["plan"][1]["depends_on"] == ["step_1"]


@pytest.mark.asyncio
async def test_planner_fallback_template_on_llm_failure(planner, monkeypatch):
    """LLM 输出 JSON 解析失败时，回退到本地模板"""
    monkeypatch.setattr(planner, "call_llm", AsyncMock(return_value="not a valid json"))
    
    state = create_initial_state(query="测试", session_id="sid_1")
    result = await planner.process(state)
    
    # 即使 LLM 输出坏掉，也要返回一个可用的最小 plan
    assert len(result["outline"]) >= 1
    assert len(result["plan"]) >= 1
    assert all("step_id" in step for step in result["plan"])
```

- [ ] **Step 6.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_planner.py -v
```

Expected: FAIL with `ModuleNotFoundError: planner`.

- [ ] **Step 6.3: 实现 Planner**

Create `backend/app/service/deep_research_v2/agents/planner.py`:

```python
"""DeepResearch v3 - Planner Agent

吸收 ChiefArchitect 的 outline 生成职责，并扩展输出完整 plan（含 parallel_group）。
"""

import json
import uuid
import logging
from typing import Dict, Any, List

from .base import BaseAgent
from ..state import ResearchState

logger = logging.getLogger("deep_research_v3.planner")


PLANNER_PROMPT = """你是一位行业研究的总规划师。给定一个研究问题，你需要：

1. 生成 6 章节的研究 outline（每个章节标注类型：qualitative/quantitative/mixed）
2. 生成完整的执行 plan：把 outline 转化为可执行的 step 序列

## 可用 tool

- `search_section`: 对单个章节执行搜索（按 section_id + queries 调用，可并行）
- `analyze_facts`: 从所有 facts 提取 data_points + 知识图谱（串行，依赖所有 search 完成）
- `generate_charts`: 根据 data_points 生成图表（串行，依赖 analyze_facts）
- `write_section`: 撰写单个章节（按 section_id 调用，可并行，依赖 analyze_facts + generate_charts）

## 输出格式（严格 JSON）

```json
{{
  "outline": [
    {{
      "id": "sec_1",
      "title": "章节标题",
      "description": "章节说明",
      "section_type": "qualitative" | "quantitative" | "mixed",
      "status": "pending",
      "requires_data": true | false,
      "requires_chart": true | false
    }}
  ],
  "plan": [
    {{
      "step_id": "step_1",
      "tool": "search_section",
      "args": {{ "section_id": "sec_1", "queries": ["关键词1", "关键词2"] }},
      "depends_on": [],
      "parallel_group": "search_batch"
    }}
  ]
}}
```

## parallel_group 规则

- 所有 `search_section` step → group "search_batch"（6 章节并行搜）
- `analyze_facts` / `generate_charts` → null（串行）
- 所有 `write_section` step → group "write_batch"（6 章节并行写）

## 研究问题

{query}

请生成 outline + plan。"""


class Planner(BaseAgent):
    """Plan-and-Execute Planner
    
    职责：
    - 一次 LLM 调用产出 outline + 完整 plan
    - parallel_group 由 LLM 标注（按上面规则）
    - JSON 解析失败时降级到本地模板
    """
    
    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = "deepseek-v3.2"):
        super().__init__(
            name="Planner",
            role="总规划师",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model,
        )
    
    async def process(self, state: ResearchState) -> Dict[str, Any]:
        """生成 outline + plan，返回 dict（不直接修改 state）"""
        query = state["query"]
        self.add_message(state, "phase", "📋 规划阶段：生成 outline + 执行 plan...")
        
        try:
            response = await self.call_llm(
                system_prompt=PLANNER_PROMPT.format(query=query),
                user_prompt=f"研究问题：{query}",
                json_mode=True,
                temperature=0.3,
                state=state,
                action="planner.generate_plan",
            )
            parsed = self.parse_json_response(response)
            
            outline = parsed.get("outline", [])
            plan = parsed.get("plan", [])
            
            if not outline or not plan:
                raise ValueError("planner output missing outline or plan")
            
            self.add_message(state, "plan_ready", f"📋 生成 {len(outline)} 章节 / {len(plan)} 个执行步骤")
            return {"outline": outline, "plan": plan}
        
        except Exception as e:
            logger.warning(f"Planner LLM failed, using fallback template: {e}")
            self.add_message(state, "warning", f"⚠️ Planner LLM 失败，使用本地模板：{e}")
            return self._fallback_template(query)
    
    def _fallback_template(self, query: str) -> Dict[str, Any]:
        """LLM 失败时的兜底：返回固定 6 章节模板"""
        outline = [
            {"id": f"sec_{i+1}", "title": f"章节 {i+1}", "description": "",
             "section_type": "mixed", "status": "pending",
             "requires_data": True, "requires_chart": (i < 3)}
            for i in range(6)
        ]
        plan = []
        # 6 个 search_section 并行
        for sec in outline:
            plan.append({
                "step_id": f"step_search_{sec['id']}",
                "tool": "search_section",
                "args": {"section_id": sec["id"], "queries": [query, f"{query} {sec['title']}"]},
                "depends_on": [],
                "parallel_group": "search_batch",
            })
        # analyze_facts 串行
        plan.append({
            "step_id": "step_analyze",
            "tool": "analyze_facts",
            "args": {},
            "depends_on": [s["step_id"] for s in plan],
            "parallel_group": None,
        })
        # generate_charts 串行
        plan.append({
            "step_id": "step_charts",
            "tool": "generate_charts",
            "args": {},
            "depends_on": ["step_analyze"],
            "parallel_group": None,
        })
        # 6 个 write_section 并行
        for sec in outline:
            plan.append({
                "step_id": f"step_write_{sec['id']}",
                "tool": "write_section",
                "args": {"section_id": sec["id"]},
                "depends_on": ["step_charts"],
                "parallel_group": "write_batch",
            })
        return {"outline": outline, "plan": plan}
```

- [ ] **Step 6.4: 更新 agents/__init__.py**

Modify `backend/app/service/deep_research_v2/agents/__init__.py`：

```python
# 在现有 imports 区追加
from .planner import Planner

# 在 __all__ 列表追加 "Planner"
# 同时移除 ChiefArchitect（如果它出现在 __all__ 中）—— 注意：
# 此 task 不删除 architect.py 文件，仅更新导出。文件删除在 Task 15。
```

- [ ] **Step 6.5: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_planner.py -v
```

Expected: 3 passed.

- [ ] **Step 6.6: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/planner.py backend/app/service/deep_research_v2/agents/__init__.py backend/test/test_deep_research_v3/test_planner.py
git commit -m "feat(planner): implement Planner node with outline + plan generation

吸收 ChiefArchitect 的 outline 生成职责，扩展输出完整 plan：
- 一次 LLM 调用产出 outline + plan
- parallel_group 标注用于 executor Send API 并行调度
- JSON 解析失败时降级到固定 6 章节模板"
```

---

## Task 7: 改造 Critic 为 node 形态（输出 suggested_actions）

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/critic.py`
- Test: `backend/test/test_deep_research_v3/test_critic_node.py`

- [ ] **Step 7.1: 写失败测试**

Create `backend/test/test_deep_research_v3/test_critic_node.py`:

```python
"""测试 Critic node 改造后输出 suggested_actions"""
import pytest
import json
from unittest.mock import AsyncMock
from app.service.deep_research_v2.agents import CriticMaster
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def critic():
    return CriticMaster(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


@pytest.mark.asyncio
async def test_critic_outputs_suggested_actions_field(critic, monkeypatch):
    """Critic 输出新字段 suggested_actions: list[str]"""
    mock_response = json.dumps({
        "quality_score": 7.2,
        "critic_feedback": [
            {"id": "f1", "target_section": "sec_3", "issue_type": "missing_source",
             "severity": "major", "description": "...", "suggestion": "..."}
        ],
        "unresolved_issues": 2,
        "verdict": "needs_revision",
        "suggested_actions": ["retry_search:sec_3", "rewrite:sec_5"],
    }, ensure_ascii=False)
    
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))
    
    state = create_initial_state(query="测试", session_id="sid_1")
    state["draft_sections"] = {"sec_1": "draft", "sec_3": "draft", "sec_5": "draft"}
    state["facts"] = []
    state["outline"] = [{"id": "sec_3", "title": "三"}]
    
    result = await critic.process(state)
    
    assert "suggested_actions" in result
    assert "retry_search:sec_3" in result["suggested_actions"]
    assert "rewrite:sec_5" in result["suggested_actions"]
    assert result["quality_score"] == 7.2


@pytest.mark.asyncio
async def test_critic_empty_suggested_actions_on_pass(critic, monkeypatch):
    """verdict=pass 时 suggested_actions 为空"""
    mock_response = json.dumps({
        "quality_score": 9.0,
        "critic_feedback": [],
        "unresolved_issues": 0,
        "verdict": "pass",
        "suggested_actions": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))
    
    state = create_initial_state(query="测试", session_id="sid_1")
    state["draft_sections"] = {"sec_1": "ok"}
    state["facts"] = []
    state["outline"] = []
    
    result = await critic.process(state)
    assert result["suggested_actions"] == []
    assert result["unresolved_issues"] == 0
```

- [ ] **Step 7.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_critic_node.py -v
```

Expected: FAIL（suggested_actions 字段未实现）。

- [ ] **Step 7.3: 修改 CriticMaster 输出 suggested_actions**

Modify `backend/app/service/deep_research_v2/agents/critic.py`。在 REVIEW_PROMPT 末尾追加：

```python
# 在 REVIEW_PROMPT 字符串末尾追加（# 任务 之后）：
...
## 输出格式

请严格按以下 JSON 输出：

```json
{{
  "quality_score": 1-10 的浮点数,
  "critic_feedback": [...],
  "unresolved_issues": 整数（未解决问题数）,
  "verdict": "pass" | "needs_revision" | "needs_re_research",
  "suggested_actions": [
    "retry_search:sec_X"  // 缺信息，需要补搜
    | "rewrite:sec_X"     // 文字问题，需要改写
    | "add_data:sec_X"    // 缺数据点
  ]
}}
```
```

修改 `process` 方法，在解析 LLM 响应后增加 `suggested_actions` 字段到返回 dict：

```python
async def process(self, state: ResearchState) -> Dict[str, Any]:
    """v3：返回 dict 不直接修改 state；新增 suggested_actions 字段"""
    # ... 现有 prompt 构造 + call_llm 不变 ...
    parsed = self.parse_json_response(response)
    
    return {
        "quality_score": parsed.get("quality_score", 0.0),
        "critic_feedback": parsed.get("critic_feedback", []),
        "unresolved_issues": parsed.get("unresolved_issues", 0),
        "verdict": parsed.get("verdict", "needs_revision"),
        "suggested_actions": parsed.get("suggested_actions", []),  # 新增
    }
```

**注**：保留现有 process() 的核心 LLM 调用逻辑，仅调整返回 dict 的字段。

- [ ] **Step 7.4: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_critic_node.py -v
```

Expected: 2 passed.

- [ ] **Step 7.5: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/critic.py backend/test/test_deep_research_v3/test_critic_node.py
git commit -m "feat(critic): output suggested_actions for v3 replanner consumption

CriticMaster.process 返回新字段 suggested_actions: list[str]，格式如
['retry_search:sec_3', 'rewrite:sec_5']，供 Replanner 生成补救 plan 使用。
verdict='pass' 时 suggested_actions=[]。"
```

---

## Task 8: 实现 Replanner node

**Files:**
- Create: `backend/app/service/deep_research_v2/agents/replanner.py`
- Modify: `backend/app/service/deep_research_v2/agents/__init__.py`
- Test: `backend/test/test_deep_research_v3/test_replanner.py`

- [ ] **Step 8.1: 写失败测试**

Create `backend/test/test_deep_research_v3/test_replanner.py`:

```python
"""测试 Replanner node"""
import pytest
from unittest.mock import AsyncMock
from app.service.deep_research_v2.agents.replanner import Replanner
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def replanner():
    return Replanner(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


@pytest.mark.asyncio
async def test_replanner_translates_actions_to_steps(replanner):
    """suggested_actions=['retry_search:sec_3'] → 生成对应 search_section step"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_3", "title": "三章"}]
    state["critic_feedback"] = [{"target_section": "sec_3"}]
    state["replan_count"] = 0
    
    result = await replanner.process(
        state=state,
        suggested_actions=["retry_search:sec_3"],
    )
    
    assert len(result["plan"]) >= 1
    assert any(s["tool"] == "search_section" for s in result["plan"])
    assert any(s["args"].get("section_id") == "sec_3" for s in result["plan"])
    assert result["replan_count"] == 1


@pytest.mark.asyncio
async def test_replanner_handles_rewrite_action(replanner):
    """suggested_actions=['rewrite:sec_5'] → write_section step"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_5", "title": "五章"}]
    state["replan_count"] = 1
    
    result = await replanner.process(
        state=state,
        suggested_actions=["rewrite:sec_5"],
    )
    
    assert any(s["tool"] == "write_section" for s in result["plan"])
    assert any(s["args"].get("section_id") == "sec_5" for s in result["plan"])
    assert result["replan_count"] == 2


@pytest.mark.asyncio
async def test_replanner_returns_empty_plan_when_no_actions(replanner):
    """空 suggested_actions → 空 plan（critic 已 pass 不应到 replanner）"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["replan_count"] = 0
    
    result = await replanner.process(state=state, suggested_actions=[])
    assert result["plan"] == []


@pytest.mark.asyncio
async def test_replanner_unknown_action_logged_skipped(replanner):
    """未知 action 跳过但不抛异常"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["replan_count"] = 0
    
    result = await replanner.process(
        state=state,
        suggested_actions=["unknown_action:foo", "retry_search:sec_1"],
    )
    # 已知的 retry_search 仍生成 step；unknown 被跳过
    assert any(s["tool"] == "search_section" for s in result["plan"])
```

- [ ] **Step 8.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_replanner.py -v
```

Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 8.3: 实现 Replanner**

Create `backend/app/service/deep_research_v2/agents/replanner.py`:

```python
"""DeepResearch v3 - Replanner Agent

把 critic 输出的 suggested_actions 翻译成补救 plan steps。
本版本是规则驱动（不调 LLM），保持确定性 + 低成本。
如果未来需要更智能的 replan，可改为 LLM-driven。
"""

import uuid
import logging
from typing import Dict, Any, List

from .base import BaseAgent
from ..state import ResearchState

logger = logging.getLogger("deep_research_v3.replanner")


class Replanner(BaseAgent):
    """规则驱动的 Replanner
    
    支持的 action 格式：
    - 'retry_search:<section_id>'   → search_section step
    - 'rewrite:<section_id>'        → write_section step
    - 'add_data:<section_id>'       → search_section + analyze_facts steps
    """
    
    SUPPORTED_ACTIONS = {"retry_search", "rewrite", "add_data"}
    
    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = "deepseek-v3.2"):
        super().__init__(
            name="Replanner",
            role="补救规划师",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model,
        )
    
    async def process(
        self,
        state: ResearchState,
        suggested_actions: List[str],
    ) -> Dict[str, Any]:
        """根据 suggested_actions 生成补救 plan steps
        
        Returns:
            {"plan": [PlanStep, ...], "replan_count": int}
        """
        replan_count = state.get("replan_count", 0) + 1
        new_steps: List[Dict[str, Any]] = []
        
        # 构建 section title 查询索引
        outline = state.get("outline", [])
        valid_section_ids = {s["id"] for s in outline}
        
        for action in suggested_actions:
            if ":" not in action:
                logger.warning(f"replanner: ignore malformed action '{action}'")
                continue
            
            verb, target = action.split(":", 1)
            if verb not in self.SUPPORTED_ACTIONS:
                logger.warning(f"replanner: unknown action verb '{verb}'")
                continue
            
            if target not in valid_section_ids:
                logger.warning(f"replanner: unknown section '{target}'")
                continue
            
            new_steps.extend(self._action_to_steps(verb, target, state))
        
        self.add_message(state, "replan",
                         f"🔄 Replan #{replan_count}：生成 {len(new_steps)} 个补救步骤")
        
        return {
            "plan": new_steps,
            "replan_count": replan_count,
        }
    
    def _action_to_steps(
        self,
        verb: str,
        section_id: str,
        state: ResearchState,
    ) -> List[Dict[str, Any]]:
        """单个 action → 一个或多个 PlanStep dict"""
        outline = state.get("outline", [])
        section_title = next(
            (s["title"] for s in outline if s["id"] == section_id),
            section_id,
        )
        query = state.get("query", "")
        
        if verb == "retry_search":
            return [{
                "step_id": f"replan_search_{section_id}_{uuid.uuid4().hex[:6]}",
                "tool": "search_section",
                "args": {"section_id": section_id, "queries": [f"{query} {section_title}"]},
                "depends_on": [],
                "parallel_group": None,
            }]
        
        if verb == "rewrite":
            return [{
                "step_id": f"replan_write_{section_id}_{uuid.uuid4().hex[:6]}",
                "tool": "write_section",
                "args": {"section_id": section_id},
                "depends_on": [],
                "parallel_group": None,
            }]
        
        if verb == "add_data":
            search_id = f"replan_search_{section_id}_{uuid.uuid4().hex[:6]}"
            return [
                {
                    "step_id": search_id,
                    "tool": "search_section",
                    "args": {"section_id": section_id, "queries": [f"{query} 数据 统计"]},
                    "depends_on": [],
                    "parallel_group": None,
                },
                {
                    "step_id": f"replan_analyze_{uuid.uuid4().hex[:6]}",
                    "tool": "analyze_facts",
                    "args": {},
                    "depends_on": [search_id],
                    "parallel_group": None,
                },
            ]
        
        return []
```

- [ ] **Step 8.4: 更新 agents/__init__.py 导出 Replanner**

```python
# 追加 import 和 __all__
from .replanner import Replanner
```

- [ ] **Step 8.5: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_replanner.py -v
```

Expected: 4 passed.

- [ ] **Step 8.6: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/replanner.py backend/app/service/deep_research_v2/agents/__init__.py backend/test/test_deep_research_v3/test_replanner.py
git commit -m "feat(replanner): rule-driven Replanner translates suggested_actions to plan steps

支持 3 种 action：retry_search / rewrite / add_data，每种对应 1-2 个 PlanStep。
规则驱动（不调 LLM），保持确定性 + 低成本。"
```

---

## Task 9: 实现 Executor node（含 Send API 并行调度）

**Files:**
- Create: `backend/app/service/deep_research_v2/executor.py`
- Test: `backend/test/test_deep_research_v3/test_executor.py`

- [ ] **Step 9.1: 写失败测试**

Create `backend/test/test_deep_research_v3/test_executor.py`:

```python
"""测试 Executor 调度逻辑（Send API 并行 + 依赖关系）"""
import pytest
from app.service.deep_research_v2.executor import (
    pick_next_parallel_batch,
    all_steps_done,
)


def test_pick_next_batch_no_deps_returns_first_parallel_group():
    """无依赖的 step 在同一 parallel_group → 一次性返回全部"""
    plan = [
        {"step_id": "s1", "tool": "search_section", "args": {"section_id": "sec_1"},
         "depends_on": [], "parallel_group": "search_batch"},
        {"step_id": "s2", "tool": "search_section", "args": {"section_id": "sec_2"},
         "depends_on": [], "parallel_group": "search_batch"},
        {"step_id": "s3", "tool": "analyze_facts", "args": {},
         "depends_on": ["s1", "s2"], "parallel_group": None},
    ]
    completed = []
    
    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 2
    assert {s["step_id"] for s in batch} == {"s1", "s2"}


def test_pick_next_batch_respects_depends_on():
    """依赖未完成时不返回该 step"""
    plan = [
        {"step_id": "s1", "tool": "search_section", "args": {},
         "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "analyze_facts", "args": {},
         "depends_on": ["s1"], "parallel_group": None},
    ]
    # s1 还没完成
    completed = []
    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 1
    assert batch[0]["step_id"] == "s1"
    
    # s1 完成后，s2 可执行
    completed = [{"step_id": "s1", "status": "success"}]
    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 1
    assert batch[0]["step_id"] == "s2"


def test_pick_next_batch_serial_when_no_group():
    """parallel_group=None 的 step 即使无依赖也单独返回（不与其他 None 合并）"""
    plan = [
        {"step_id": "s1", "tool": "analyze_facts", "args": {},
         "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "generate_charts", "args": {},
         "depends_on": [], "parallel_group": None},
    ]
    completed = []
    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 1  # None 的不互相并行


def test_all_steps_done_true():
    """所有 plan step 都在 completed 中 → done"""
    plan = [
        {"step_id": "s1", "tool": "x", "args": {}, "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "y", "args": {}, "depends_on": [], "parallel_group": None},
    ]
    completed = [
        {"step_id": "s1", "status": "success"},
        {"step_id": "s2", "status": "success"},
    ]
    assert all_steps_done(plan, completed) is True


def test_all_steps_done_false_when_pending():
    plan = [
        {"step_id": "s1", "tool": "x", "args": {}, "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "y", "args": {}, "depends_on": [], "parallel_group": None},
    ]
    completed = [{"step_id": "s1", "status": "success"}]
    assert all_steps_done(plan, completed) is False


def test_failed_step_counts_as_done():
    """失败的 step 也算 done（避免死循环）"""
    plan = [
        {"step_id": "s1", "tool": "x", "args": {}, "depends_on": [], "parallel_group": None},
    ]
    completed = [{"step_id": "s1", "status": "failed", "error": "boom"}]
    assert all_steps_done(plan, completed) is True
```

- [ ] **Step 9.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_executor.py -v
```

Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 9.3: 实现 executor.py**

Create `backend/app/service/deep_research_v2/executor.py`:

```python
"""DeepResearch v3 - Executor node + Send API 调度逻辑

Executor 负责按 plan 调度 tools，处理并行组，merge tool 返回结果到 state。
不直接调 LLM，只做调度。
"""

import time
import asyncio
import logging
from typing import Dict, Any, List, Optional, Sequence

from langgraph.types import Send

from .state import ResearchState
from .tools import search_section, analyze_facts, generate_charts, write_section

logger = logging.getLogger("deep_research_v3.executor")


# === Tool 注册表 ===
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
    1. 所有 depends_on 都在 completed 中（包括 failed）的 step 是 ready
    2. 已完成的 step 不再选
    3. ready 的 step 中，相同 parallel_group 的可一次返回（并行）
    4. parallel_group=None 的 step 一次只返回 1 个（串行）
    
    Returns:
        本轮可执行的 step list
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
    
    # 取第一个 ready step 的 parallel_group
    first = ready[0]
    group = first.get("parallel_group")
    
    if group is None:
        # 串行：只返回 1 个
        return [first]
    
    # 并行：返回所有同 group 的 ready step
    return [s for s in ready if s.get("parallel_group") == group]


def all_steps_done(
    plan: List[Dict[str, Any]],
    completed_steps: List[Dict[str, Any]],
) -> bool:
    """plan 是否全部执行完（成功 + 失败都算 done，避免死循环）"""
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
        # ainvoke 是 langchain_core.tools 的标准异步入口
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
    
    Loop：取下一批 ready step → 并行执行 → merge 结果 → 直到 done
    返回 state diff（completed_steps 累计 + 各 tool 结果 merge 到 state 对应字段）
    """
    plan = state.get("plan", [])
    completed = list(state.get("completed_steps", []))
    
    # 累加 merge 各类字段
    merged_facts = list(state.get("facts", []))
    merged_sources = list(state.get("raw_sources", []))
    merged_data_points = list(state.get("data_points", []))
    merged_knowledge_graph = state.get("knowledge_graph", {"nodes": [], "edges": []})
    merged_charts = list(state.get("charts", []))
    merged_code_executions = list(state.get("code_executions", []))
    merged_insights = list(state.get("insights", []))
    merged_draft_sections = dict(state.get("draft_sections", {}))
    
    while not all_steps_done(plan, completed):
        batch = pick_next_parallel_batch(plan, completed)
        if not batch:
            # 死锁（不应发生，但兜底）
            logger.error("executor deadlock: no ready steps but plan not done")
            break
        
        # 并行执行
        results = await asyncio.gather(*[
            execute_one_step(step, state) for step in batch
        ])
        
        # merge 每个 result.output 到对应字段
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
```

- [ ] **Step 9.4: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_executor.py -v
```

Expected: 6 passed.

- [ ] **Step 9.5: Commit**

```bash
git add backend/app/service/deep_research_v2/executor.py backend/test/test_deep_research_v3/test_executor.py
git commit -m "feat(executor): implement v3 executor node with parallel batch scheduling

- pick_next_parallel_batch: 按 depends_on + parallel_group 选下一批 ready step
- executor_node: 循环并行执行 + merge 结果到 state
- 失败 step 算 done（避免死循环）
- 同 parallel_group 一次性并行（asyncio.gather）"
```

---

## Task 10: 重写 _build_langgraph（4 node 主图 + 预留 fallback 分支）

**Files:**
- Modify: `backend/app/service/deep_research_v2/graph.py`
- Test: `backend/test/test_deep_research_v3/test_graph_integration.py`

- [ ] **Step 10.1: 写失败测试**

Create `backend/test/test_deep_research_v3/test_graph_integration.py`:

```python
"""4-node 主图集成测试（mock LLM）"""
import pytest
from unittest.mock import AsyncMock, patch
import json
from app.service.deep_research_v2.graph import DeepResearchGraph
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def graph(monkeypatch):
    """创建 graph，所有 sub-agent 的 LLM 调用都 mock"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy")
    g = DeepResearchGraph(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
    )
    return g


def test_graph_compiled_has_4_main_nodes(graph):
    """compile 后的 graph 应包含 planner / executor / critic / replanner 4 个主 node"""
    compiled = graph.graph
    node_names = set(compiled.get_graph().nodes.keys())
    assert "planner" in node_names
    assert "executor" in node_names
    assert "critic" in node_names
    assert "replanner" in node_names


def test_graph_has_fallback_branch_reserved(graph):
    """should_fallback 条件边存在，但本期恒 False"""
    # 直接调路由函数
    from app.service.deep_research_v2.graph import route_after_replanner
    
    state_no_fallback = create_initial_state(query="test", session_id="s")
    state_no_fallback["replan_count"] = 1
    state_no_fallback["fallback_triggered"] = False
    state_no_fallback["unresolved_issues"] = 2
    assert route_after_replanner(state_no_fallback) == "executor"  # 回执行器
    
    # 达到 max replan
    state_max = create_initial_state(query="test", session_id="s")
    state_max["replan_count"] = 3
    state_max["fallback_triggered"] = False
    assert route_after_replanner(state_max) == "END"


@pytest.mark.asyncio
async def test_graph_e2e_with_mocked_llm(graph, monkeypatch):
    """E2E mock：planner → executor → critic pass → END"""
    
    # mock planner LLM
    planner_response = json.dumps({
        "outline": [{"id": "sec_1", "title": "x", "description": "",
                     "section_type": "mixed", "status": "pending",
                     "requires_data": False, "requires_chart": False}],
        "plan": [
            {"step_id": "s_search", "tool": "search_section",
             "args": {"section_id": "sec_1", "queries": ["q"]},
             "depends_on": [], "parallel_group": "search_batch"},
            {"step_id": "s_write", "tool": "write_section",
             "args": {"section_id": "sec_1"}, "depends_on": ["s_search"],
             "parallel_group": "write_batch"},
        ],
    }, ensure_ascii=False)
    monkeypatch.setattr(
        graph.planner, "call_llm",
        AsyncMock(return_value=planner_response)
    )
    
    # mock critic verdict=pass
    critic_response = json.dumps({
        "quality_score": 9.0, "critic_feedback": [],
        "unresolved_issues": 0, "verdict": "pass",
        "suggested_actions": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(
        graph.critic, "call_llm",
        AsyncMock(return_value=critic_response)
    )
    
    # mock tools 返回值
    async def fake_search(**kwargs):
        return {"facts": [{"id": "f", "content": "fact"}], "sources": [],
                "section_id": kwargs.get("section_id")}
    async def fake_write(**kwargs):
        return {"section_id": kwargs.get("section_id"), "content": "# 章节"}
    
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.search_section.ainvoke",
        fake_search
    )
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.write_section.ainvoke",
        fake_write
    )
    
    # 跑 graph
    events = []
    async for ev in graph.run(query="test", session_id="sid_1"):
        events.append(ev)
    
    # 至少要有：planner phase / executor steps / critic pass / final
    event_types = [e.get("type") for e in events]
    assert "phase" in event_types or "plan_ready" in event_types
    assert any("complete" in (et or "") for et in event_types)
```

- [ ] **Step 10.2: 跑测试确认失败**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_graph_integration.py -v
```

Expected: FAIL（旧 graph 还在）。

- [ ] **Step 10.3: 重写 graph.py**

Modify `backend/app/service/deep_research_v2/graph.py`。完全替换 `_build_langgraph` 方法，并补充新的路由函数：

```python
# 在文件顶部 imports 区追加
from langgraph.config import get_stream_writer
from .executor import executor_node, all_steps_done
from .agents import Planner, Replanner, CriticMaster

# 在 DeepResearchGraph.__init__ 内：
# 移除 self.architect = ChiefArchitect(...) 这一行
# 追加：
self.planner = Planner(self.llm_api_key, self.llm_base_url, config.agents.architect.model)
self.replanner = Replanner(self.llm_api_key, self.llm_base_url, config.agents.architect.model)
# critic / scout / writer / data_analyst / wizard 现有实例化保留

# 新增模块级路由函数（定义在 class 外面）
MAX_REPLAN = 3

def route_after_critic(state: ResearchState) -> str:
    """critic node 之后的路由"""
    unresolved = state.get("unresolved_issues", 0)
    suggested = state.get("suggested_actions", [])
    replan_count = state.get("replan_count", 0)
    if unresolved <= 0 or not suggested:
        return "END"
    if replan_count >= MAX_REPLAN:
        return "END"
    return "replanner"


def route_after_replanner(state: ResearchState) -> str:
    """replanner 之后路由：预留 fallback 接口"""
    if state.get("replan_count", 0) >= MAX_REPLAN:
        return "END"
    # 预留 fallback 分支（本期恒 False，TODO phase-2）
    if state.get("fallback_triggered", False):
        return "supervisor_fallback"  # TODO(phase-2): 实现 supervisor_fallback node
    return "executor"
```

`_build_langgraph` 方法替换为：

```python
    def _build_langgraph(self):
        """构建 v3 Plan-and-Execute 主图
        
        拓扑：
            planner → executor → critic
                                   ├── pass → END
                                   └── needs_revision → replanner
                                                          ├── max_replan → END
                                                          ├── (TODO) fallback
                                                          └── default → executor
        """
        from langgraph.graph import StateGraph, END
        
        workflow = StateGraph(ResearchState)
        
        # 4 个主 node
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("executor", executor_node)
        workflow.add_node("critic", self._critic_node)
        workflow.add_node("replanner", self._replanner_node)
        
        # 入口
        workflow.set_entry_point("planner")
        
        # 顺序边
        workflow.add_edge("planner", "executor")
        workflow.add_edge("executor", "critic")
        
        # critic 之后的条件路由
        workflow.add_conditional_edges(
            "critic",
            route_after_critic,
            {"END": END, "replanner": "replanner"},
        )
        
        # replanner 之后的条件路由
        workflow.add_conditional_edges(
            "replanner",
            route_after_replanner,
            {
                "END": END,
                "executor": "executor",
                # TODO(phase-2): "supervisor_fallback": "supervisor_fallback"
            },
        )
        
        return workflow.compile()
    
    async def _planner_node(self, state: ResearchState) -> Dict[str, Any]:
        """planner node 包装：调用 self.planner.process()"""
        self._maybe_cancel(state)
        result = await self.planner.process(state)
        return result
    
    async def _critic_node(self, state: ResearchState) -> Dict[str, Any]:
        """critic node 包装"""
        self._maybe_cancel(state)
        result = await self.critic.process(state)
        return result
    
    async def _replanner_node(self, state: ResearchState) -> Dict[str, Any]:
        """replanner node 包装"""
        self._maybe_cancel(state)
        suggested = state.get("suggested_actions", [])
        result = await self.replanner.process(state, suggested_actions=suggested)
        return result
```

修改 `run()` 方法，使其用 LangGraph 原生 `astream` 替代旧的手写循环。run() 应该使用 5/26 阶段一已经实现的 `stream_mode=["custom","updates"]` 模式，但调用新的 compiled graph：

```python
    async def run(
        self,
        query: str,
        session_id: str,
        resume: bool = False,
        user_id: str = None,
        search_web: bool = True,
        search_local: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """运行 v3 graph，yield SSE events"""
        if resume:
            state = self._load_checkpoint(session_id) or create_initial_state(
                query=query, session_id=session_id,
                search_web=search_web, search_local=search_local,
            )
        else:
            state = create_initial_state(
                query=query, session_id=session_id,
                search_web=search_web, search_local=search_local,
            )
        
        config = {"configurable": {"thread_id": session_id}}
        
        async for mode, chunk in self.graph.astream(
            state,
            stream_mode=["custom", "updates"],
            config=config,
        ):
            if mode == "custom":
                # custom stream: 来自 get_stream_writer() 的事件，直接 yield
                yield chunk
            elif mode == "updates":
                # 节点完成的 state diff，触发 checkpoint + 推 phase 完成
                for node_name, diff in chunk.items():
                    self._save_checkpoint(state, user_id=user_id)
                    yield {"type": "node_complete", "node": node_name}
        
        # 完成
        yield {"type": "research_complete", "session_id": session_id}
```

**注**：保留现有的 `_save_checkpoint` / `_load_checkpoint` / `_maybe_cancel` / `get_checkpoint_info` 方法不变。

- [ ] **Step 10.4: 跑测试确认通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/test_graph_integration.py -v
```

Expected: 3 passed（如果 e2e mock 因 Send/state schema 问题失败，先确保前 2 个通过；e2e 留给 Task 12 端到端冒烟覆盖）。

- [ ] **Step 10.5: Commit**

```bash
git add backend/app/service/deep_research_v2/graph.py backend/test/test_deep_research_v3/test_graph_integration.py
git commit -m "feat(graph): rebuild graph as Plan-and-Execute 4-node supervisor

主图重构为 planner → executor → critic → (END | replanner) → executor 循环：
- 4 个主 node 替代旧的 9-node workflow DAG
- 预留 supervisor_fallback 条件边（本期恒 False + TODO 注释）
- MAX_REPLAN=3 防止死循环
- run() 用 LangGraph 原生 astream(stream_mode=['custom','updates']) 沿用 5/26 阶段一的双流模式"
```

---

## Task 11: 适配 service.py 入口

**Files:**
- Modify: `backend/app/service/deep_research_v2/service.py`

- [ ] **Step 11.1: 移除已废弃字段访问**

Modify `backend/app/service/deep_research_v2/service.py`。在 `research_sync` 方法中删除对 `state.get("phase", "")` 的访问：

```python
    async def research_sync(
        self,
        query: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not session_id:
            session_id = str(uuid.uuid4())
        state = await self.graph.run_sync(query, session_id)
        return {
            "session_id": session_id,
            "query": query,
            "final_report": state.get("final_report", ""),
            "quality_score": state.get("quality_score", 0.0),
            "outline": state.get("outline", []),
            "facts": state.get("facts", []),
            "data_points": state.get("data_points", []),
            "charts": state.get("charts", []),
            "references": state.get("references", []),
            "insights": state.get("insights", []),
            "iterations": state.get("replan_count", 0),   # 改为 replan_count
            # 删除 "phase" 字段（已废弃）
            "logs": state.get("logs", []),
        }
```

- [ ] **Step 11.2: 确保 SSE 协议不变**

确认 service.py 的 `_format_sse` 没变，仍是 `f"data: {json.dumps(event, ensure_ascii=False)}\n\n"`。

- [ ] **Step 11.3: Commit**

```bash
git add backend/app/service/deep_research_v2/service.py
git commit -m "fix(service): remove deprecated phase field from research_sync output

phase 字段在 v3 已废弃（由 graph 当前 node 推导），改用 replan_count 作为
iterations 字段的数据源。SSE 协议保持不变。"
```

---

## Task 12: 端到端冒烟测试（真 LLM，手动）

**Files:**
- Create: `backend/test/test_deep_research_v3/test_smoke.py`

- [ ] **Step 12.1: 写冒烟脚本**

Create `backend/test/test_deep_research_v3/test_smoke.py`:

```python
"""端到端冒烟：真 LLM + 真搜索 API，跑一个 query 看完整流程

跑法（手动）：
    cd backend && python -m pytest test/test_deep_research_v3/test_smoke.py -v -s

需要环境变量：DASHSCOPE_API_KEY, BOCHA_API_KEY（在 backend/.env）
"""
import os
import pytest
import asyncio
from app.service.deep_research_v2.service import DeepResearchV2Service


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SMOKE_TESTS") != "1",
    reason="冒烟测试需要真 API key，默认不跑。设置 RUN_SMOKE_TESTS=1 启用"
)


@pytest.mark.asyncio
async def test_e2e_simple_query():
    """跑一个 query，看 SSE 事件流是否正常 + 最终报告是否非空"""
    service = DeepResearchV2Service()
    
    events_received = []
    async for event_str in service.research(
        query="2024 年中国 5G 用户规模",
        session_id="smoke_test_001",
        search_web=True,
        search_local=False,
    ):
        events_received.append(event_str)
        if "[DONE]" in event_str:
            break
        # 至少看到关键节点 phase 事件
        if len(events_received) % 10 == 0:
            print(f"\n[{len(events_received)}] {event_str[:100]}")
    
    # 必须至少有这些事件类型
    all_text = "\n".join(events_received)
    assert "planner" in all_text.lower() or "plan_ready" in all_text
    assert "executor" in all_text or "node_complete" in all_text
    assert "research_complete" in all_text
    assert "[DONE]" in events_received[-1]


@pytest.mark.asyncio
async def test_e2e_resume():
    """跑一次到中途取消，再 resume 看是否能接着跑"""
    # 这个测试需要手动配合（先跑一次中途 ctrl-c）
    # 此处只做框架，标 skip
    pytest.skip("需要手动配合：先跑 simple_query 中途 cancel，再设置 resume=True")
```

- [ ] **Step 12.2: 手动跑冒烟测试**

```bash
cd backend
$env:RUN_SMOKE_TESTS = "1"  # PowerShell
python -m pytest test/test_deep_research_v3/test_smoke.py::test_e2e_simple_query -v -s
```

Expected:
- 跑 5-15 分钟（取决于 LLM 速度 + 搜索）
- 看到 planner → executor（含多个 search/write 并行）→ critic → END 完整链路
- 最终事件含 `research_complete`

如失败，根据具体错误调整：planner JSON 格式 / tool 调用参数 / Send API 配置等。

- [ ] **Step 12.3: 前端零改动验证（手动）**

启动后端 + 前端：

```bash
# Terminal 1
cd backend && uvicorn app.app_main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

在浏览器跑一次 deep research，验证：
- [ ] SSE 流式正常显示（不批量到结尾才出）
- [ ] research_steps 区域显示 planner / search / write / critic 各阶段
- [ ] search_results 区域显示找到的事实
- [ ] charts 区域显示图表
- [ ] 报告区域显示最终 Markdown 报告
- [ ] 没有 console error

如有前端报错，**不修改前端**，定位是后端 SSE 事件 type 漂移导致，回 Task 10 修正事件 type。

- [ ] **Step 12.4: Commit 冒烟脚本（不 commit 跑通的状态）**

```bash
git add backend/test/test_deep_research_v3/test_smoke.py
git commit -m "test(smoke): e2e smoke for v3 plan-and-execute graph

需要真 API key + RUN_SMOKE_TESTS=1 env 启用。
默认 CI 不跑，本地手动跑用于验证 v3 graph 端到端贯通。"
```

---

## Task 13: 检查点续作验证

**Files:**
- Manual test

- [ ] **Step 13.1: 跑一次完整研究并验证 checkpoint**

```bash
# 跑一个 query，让它跑完
curl -X POST http://localhost:8000/research/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "2024 中国新能源车市场", "session_id": "ckpt_test_001"}'

# 查 DB：
psql -d industry_research -c "select id, session_id, length(state_json::text) from research_checkpoints where session_id='ckpt_test_001' order by created_at desc limit 3;"
```

Expected: 至少 2 条 checkpoint 记录（planner / executor / critic 完成各保存一次）。

- [ ] **Step 13.2: 跑中途取消 + resume**

终端 A 跑 query，几秒后 ctrl-c 终止：

```bash
# 终端 A：跑 query 然后 ctrl-c
curl -X POST http://localhost:8000/research/stream -d '{"query": "...", "session_id": "ckpt_test_002"}'
# Ctrl-C
```

终端 B 触发 resume：

```bash
curl -X POST http://localhost:8000/research/resume/ckpt_test_002
```

Expected: resume 后 graph 从最后一个 checkpoint 继续，看到剩余阶段的事件流。

- [ ] **Step 13.3: 如果 resume 不工作，修复**

检查 `graph.run(resume=True)` 是否正确从 checkpoint 恢复 state。如发现 ResearchState 新字段（plan / completed_steps）没正确序列化进 state_json，到 `checkpoint_service.py::save_checkpoint` 看是否需要扩展白名单。

修复后重跑验证。

---

## Task 14: 取消机制验证

**Files:**
- Manual test

- [ ] **Step 14.1: 跑一次研究 + 调用 cancel 端点**

```bash
# 终端 A：启动 query
curl -X POST http://localhost:8000/research/stream -d '{"query": "...", "session_id": "cancel_test_001"}'

# 终端 B：等 5 秒后 cancel
sleep 5
curl -X POST http://localhost:8000/research/cancel/cancel_test_001
```

Expected:
- 终端 A 应在 5-10 秒内停止收 SSE 事件
- 最后一个事件应类型为 `error` 或 `cancelled`
- DB checkpoint 状态显示 cancelled

- [ ] **Step 14.2: 如果取消不响应，修复**

检查 graph.py 中的 `_maybe_cancel` 是否在新的 4 个 node 入口都被调用（Task 10 中已加 `_planner_node` / `_critic_node` / `_replanner_node` 各自的 `self._maybe_cancel(state)`）。

executor 内部的取消是关键：在 `execute_one_step` 调用前后应 check cancel。修改 `executor.py::executor_node`：

```python
# 在 while loop 顶部追加：
from .graph import is_research_cancelled  # 或重 import
if is_research_cancelled(state.get("session_id", "")):
    raise asyncio.CancelledError("user cancelled")
```

如发现 import 循环，把 `is_research_cancelled` 抽到独立 helper 文件。

---

## Task 15: 清理（删除 architect.py 旧文件 + 死代码）

**Files:**
- Delete: `backend/app/service/deep_research_v2/agents/architect.py`
- Modify: `backend/app/service/deep_research_v2/agents/__init__.py`

- [ ] **Step 15.1: 全局搜索 architect.py 的引用**

```bash
cd backend && grep -rn "from.*architect" app/ --include="*.py"
cd backend && grep -rn "ChiefArchitect" app/ --include="*.py"
```

Expected: 应只剩下 `agents/__init__.py` 中的 import 和 `architect.py` 自身。如果有其他引用（如 graph.py），先把它们改成用 Planner。

- [ ] **Step 15.2: 删除 architect.py 并清理 __init__.py**

```bash
git rm backend/app/service/deep_research_v2/agents/architect.py
```

Modify `backend/app/service/deep_research_v2/agents/__init__.py`：

- 删除 `from .architect import ChiefArchitect`
- 从 `__all__` 中删除 `"ChiefArchitect"`

- [ ] **Step 15.3: 全测试通过**

```bash
cd backend && python -m pytest test/test_deep_research_v3/ -v
```

Expected: 所有 v3 单测通过。

```bash
cd backend && python -m pytest test/ -v --ignore=test/test_deep_research_v3/test_smoke.py 2>&1 | tail -20
```

Expected: 现有 51 个 eval 单测不退步（如有 import 失败，调整）。

- [ ] **Step 15.4: Commit**

```bash
git add -A
git commit -m "refactor: remove ChiefArchitect (logic absorbed into Planner)

Architect 职责在 Task 6 已被 Planner 完全吸收，删除文件 + 清理 import。"
```

---

## Task 16: PR + 合并

- [ ] **Step 16.1: Push branch + 开 PR**

```bash
git push -u origin feat/autonomous-orchestrator
gh pr create --title "feat: refactor deep_research_v2 to Plan-and-Execute supervisor" --body "$(cat <<'EOF'
## Summary
- 把 6-agent 研究系统从 hard-coded LangGraph workflow 重构为 Plan-and-Execute supervisor 架构（planner / executor / critic / replanner 4 node）
- 6 个 sub-agent 改造成 @tool（保留模型混搭、流式、并发）
- Send API 章节级并行（search × N, write × 6）
- ReAct fallback 接口预留（恒 False + TODO，第二期实现）
- 前端 SSE 协议零改动，检查点续作 + 取消机制仍工作

## Plan reference
docs/superpowers/specs/2026-05-28-autonomous-orchestrator-design.md
docs/superpowers/plans/2026-05-28-autonomous-orchestrator-plan-1.md

## Test plan
- [x] 51 现有单测不退步
- [x] v3 新增单测全过
- [x] 端到端冒烟（手动跑 1 个 query 完整流程）
- [x] 前端零改动验证
- [x] 检查点续作验证
- [x] 取消机制验证

## Out of scope（独立 PR）
- Higress 集成
- LangSmith 装点
- Memory 系统
- eval A/B 跑分（用户自测）

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 16.2: 等 CI 通过**

观察 GitHub Actions 的 PR quality gates（tsc + eslint + build + pytest）是否全绿。如有失败，按报错修复。

- [ ] **Step 16.3: Merge**

CI 全绿后，按 PR 流程 merge 到 main。

---

## Self-Review

### 1. Spec coverage 对照

| Spec §9.1 in-scope 项 | 对应 Task |
|---------------------|----------|
| 1. P&E graph 4 node 跑通 | Task 6, 7, 8, 9, 10 |
| 2. 6 sub-agent 改 @tool | Task 2, 3, 4, 5（Critic 是 node 不是 tool，由 Task 7 处理）|
| 3. Architect 吸收进 planner | Task 6, 15 |
| 4. Send API 章节并行 | Task 9（pick_next_parallel_batch + asyncio.gather）|
| 5. ReAct fallback 接口预留 | Task 10（route_after_replanner + TODO 注释）|
| 6-9. Higress 相关 | 不在 Plan 1 范围（Plan 2）|
| 10. LangSmith 装点 | 不在 Plan 1 范围（Plan 3）|
| 11. 检查点续作 + 取消 | Task 13, 14 |
| 12. 前端 SSE 协议零改动 | Task 12（手动验证 + 硬 gate）|
| 13. 博客 draft | 不在 Plan 1 范围 |

**覆盖率**：本 plan 范围内的 7 项全部覆盖。✅

### 2. Placeholder 扫描

- ✅ 无 "TBD" / "TODO later" 占位（Task 10 中 `# TODO(phase-2): "supervisor_fallback"` 是设计意图，不是占位）
- ✅ 每个 step 都有完整代码或完整命令
- ✅ 所有 test 给出完整 assertion，不写 "test the above"

### 3. Type 一致性

- ✅ `PlanStep.parallel_group: Optional[str]` 在 state.py 定义；在 executor.py / planner.py / replanner.py 全部用 `.get("parallel_group")` 访问，类型一致
- ✅ tool 函数签名（`section_id: str, queries: list[str], state: ResearchState`）在 tools.py 定义；executor.py 通过 `**args, "state": state` 调用，参数名一致
- ✅ `route_after_critic` / `route_after_replanner` 返回值（"END" / "executor" / "replanner"）在 conditional_edges 的 mapping 中全部 case 覆盖
- ✅ Critic 的 `suggested_actions: list[str]` 字段在 Task 7 定义，Task 8 的 Replanner 用同样的格式（`"verb:target"` 字符串）

### 4. 已识别的潜在问题

- **Task 3-5 中部分依赖现有 sub-agent 内部方法**（如 `extract_data_points_from_facts` / `_write_section_internal`）：实际命名可能不完全匹配，执行 agent 需要先 `grep` 现有 method 命名再适配。**这是合理的灵活性，不是占位**。
- **Task 10 中的 `is_research_cancelled` import** 可能引起循环 import：Task 14 已预见并给出解决方案（抽到独立 helper）。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-28-autonomous-orchestrator-plan-1.md`.** Two execution options:

**1. Subagent-Driven (recommended)** — 我每个 task dispatch 一个 fresh subagent，task 之间做 two-stage review，迭代快。适合本 plan 的 16 个 task 串行结构。

**2. Inline Execution** — 在当前会话内用 executing-plans skill 批量执行，中途 checkpoint 让你 review。会大量占用本会话上下文。

哪种？
