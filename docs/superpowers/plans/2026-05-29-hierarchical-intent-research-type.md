# 分层意图识别 + 细粒度研究类型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `intent_router`（Level 1）后新增 `research_type_router`（Level 2）节点，通过 YAML 配置文件驱动三种差异化的 Planner 策略（行业分析 / 公司调研 / 竞品对比）。

**Architecture:** Level 2 节点用 function calling 识别 `research_type`，写入 state；Planner 节点读取 `state["research_type"]`，加载对应 `research_skills/{type}.yaml`，将 `planner_prompt` 追加到 system prompt、`outline_template` 追加到 user prompt，LLM 在模板引导下自由生成 outline + plan。

**Tech Stack:** LangGraph, openai SDK (DashScope), PyYAML, 现有 `IntentService` 同款模式

---

## 文件结构

```
新建:
  backend/app/research_skills/
    industry_analysis.yaml          # 行业分析 Planner 配置
    company_research.yaml           # 公司调研 Planner 配置
    comparative_analysis.yaml       # 竞品对比 Planner 配置
  backend/app/service/research_type_service.py   # Level 2 分类服务
  backend/test/test_research_type_service.py     # 单元测试

修改:
  backend/app/service/deep_research_v2/graph.py  # 新增节点 + 修改路由
  backend/app/service/deep_research_v2/agents/planner.py  # 加载 YAML 注入 prompt
```

---

### Task 1: 创建三个 YAML 研究类型配置文件

**Files:**
- Create: `backend/app/research_skills/industry_analysis.yaml`
- Create: `backend/app/research_skills/company_research.yaml`
- Create: `backend/app/research_skills/comparative_analysis.yaml`

- [ ] **Step 1: 创建目录并写入 industry_analysis.yaml**

```bash
mkdir -p backend/app/research_skills
```

`backend/app/research_skills/industry_analysis.yaml` 内容：

```yaml
name: industry_analysis
description: 行业市场格局与竞争态势深度分析

planner_prompt: |
  你正在执行【行业分析】研究任务。报告需聚焦行业整体，而非单一公司。

  必须覆盖以下核心维度（作为 outline 章节）：
  1. 市场规模与增速（需有具体数字、CAGR、来源）
  2. 竞争格局（主要玩家、市场份额、CR4/CR8）
  3. 波特五力分析（供应商/买方议价、替代品、新进入者、同业竞争）
  4. 产业链与价值链分析
  5. 行业驱动因素与挑战
  6. 未来趋势与投资机会

  搜索策略：优先使用权威机构报告（艾瑞、IDC、麦肯锡、行业协会、政府白皮书）。
  报告格式：结构化分析报告，数据驱动，必须有图表支撑。

outline_template:
  - title: 市场规模与增速
    search_query_hints:
      - "{topic} 市场规模 {year}"
      - "{topic} 行业增速 CAGR 预测"
      - "{topic} 市场份额报告"
  - title: 竞争格局分析
    search_query_hints:
      - "{topic} 主要企业 市场份额"
      - "{topic} 行业竞争格局 CR4"
      - "{topic} 龙头企业 排名"
  - title: 波特五力分析
    search_query_hints:
      - "{topic} 行业壁垒 护城河"
      - "{topic} 供应链 议价能力"
      - "{topic} 替代品 威胁"
  - title: 产业链与价值链
    search_query_hints:
      - "{topic} 产业链 上下游"
      - "{topic} 价值链 利润分配"
  - title: 行业驱动因素与挑战
    search_query_hints:
      - "{topic} 增长驱动 政策利好"
      - "{topic} 行业痛点 挑战 风险"
  - title: 未来趋势与投资机会
    search_query_hints:
      - "{topic} 未来趋势 {year} 预测"
      - "{topic} 投资机会 新赛道"
```

- [ ] **Step 2: 写入 company_research.yaml**

`backend/app/research_skills/company_research.yaml` 内容：

```yaml
name: company_research
description: 单一公司深度调研报告（尽调式）

planner_prompt: |
  你正在执行【公司调研】研究任务。报告聚焦于单一公司的全面深度分析。

  必须覆盖以下核心维度（作为 outline 章节）：
  1. 公司概况与商业模式（业务构成、收入来源、客户群体）
  2. 财务分析（营收/利润趋势、主要财务指标 PE/PB/ROE/毛利率）
  3. 核心竞争优势（技术壁垒、品牌、渠道、规模效应）
  4. 管理层与股权结构
  5. 行业地位与竞争对手
  6. 风险因素与投资建议

  搜索策略：优先使用公司官方财报、招股书、券商研究报告、公告。
  报告格式：尽调式深度报告，财务数据精确，风险明确量化。

outline_template:
  - title: 公司概况与商业模式
    search_query_hints:
      - "{topic} 商业模式 业务介绍"
      - "{topic} 收入构成 主营业务"
      - "{topic} 公司简介 发展历程"
  - title: 财务状况分析
    search_query_hints:
      - "{topic} 财报 营收 利润 {year}"
      - "{topic} 毛利率 净利率 ROE"
      - "{topic} 现金流 负债率"
  - title: 核心竞争优势
    search_query_hints:
      - "{topic} 竞争优势 护城河"
      - "{topic} 技术壁垒 专利"
      - "{topic} 品牌价值 市场地位"
  - title: 管理层与股权结构
    search_query_hints:
      - "{topic} 管理团队 CEO 创始人"
      - "{topic} 股权结构 大股东"
  - title: 行业地位与竞争对手
    search_query_hints:
      - "{topic} 市场份额 行业排名"
      - "{topic} 竞争对手 对比"
  - title: 风险因素与投资建议
    search_query_hints:
      - "{topic} 风险 挑战 不确定性"
      - "{topic} 投资价值 估值"
```

- [ ] **Step 3: 写入 comparative_analysis.yaml**

`backend/app/research_skills/comparative_analysis.yaml` 内容：

```yaml
name: comparative_analysis
description: 多主体横向对比分析报告

planner_prompt: |
  你正在执行【竞品对比】研究任务。报告需对多个主体（公司/产品/方案）进行结构化横向对比。

  必须覆盖以下核心维度（作为 outline 章节）：
  1. 对比主体概况（各主体基本信息并排呈现）
  2. 业务模式与产品对比
  3. 财务与规模对比（关键指标横向对比表格）
  4. 技术/产品能力对比
  5. 市场表现与用户口碑对比
  6. 综合评估与选择建议

  搜索策略：每个对比主体分别搜索，获取同维度可比数据。
  报告格式：大量使用表格进行并排对比，每维度给出优劣评分，最终给出综合结论。

outline_template:
  - title: 对比主体概况
    search_query_hints:
      - "{topic} 各主体 基本信息 概况"
      - "{topic} 成立时间 规模 背景"
  - title: 业务模式与产品对比
    search_query_hints:
      - "{topic} 产品功能 对比"
      - "{topic} 商业模式 差异"
  - title: 财务与规模对比
    search_query_hints:
      - "{topic} 营收 市值 规模 对比"
      - "{topic} 财务指标 对比表"
  - title: 技术与产品能力对比
    search_query_hints:
      - "{topic} 技术能力 对比"
      - "{topic} 产品优劣势 评测"
  - title: 市场表现与用户口碑
    search_query_hints:
      - "{topic} 用户评价 口碑"
      - "{topic} 市场占有率 对比"
  - title: 综合评估与选择建议
    search_query_hints:
      - "{topic} 综合评比 哪个更好"
      - "{topic} 推荐 适用场景"
```

- [ ] **Step 4: 验证 YAML 格式正确**

```bash
cd backend
python -c "
import yaml
for name in ['industry_analysis', 'company_research', 'comparative_analysis']:
    with open(f'app/research_skills/{name}.yaml', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    assert 'name' in data
    assert 'planner_prompt' in data
    assert 'outline_template' in data
    assert len(data['outline_template']) == 6
    print(f'{name}: OK ({len(data[\"outline_template\"])} sections)')
"
```

期望输出：
```
industry_analysis: OK (6 sections)
company_research: OK (6 sections)
comparative_analysis: OK (6 sections)
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/research_skills/
git commit -m "feat(research-type): 新增行业分析/公司调研/竞品对比 YAML 配置"
```

---

### Task 2: 实现 ResearchTypeService

**Files:**
- Create: `backend/app/service/research_type_service.py`
- Create: `backend/test/test_research_type_service.py`

- [ ] **Step 1: 写失败的测试**

创建 `backend/test/test_research_type_service.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.service.research_type_service import ResearchTypeService, ResearchTypeResult


@pytest.fixture
def service():
    return ResearchTypeService(api_key="test-key", base_url="https://example.com", model="qwen-turbo")


@pytest.mark.asyncio
async def test_classify_industry_analysis(service):
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "industry_analysis"
    mock_tool_call.function.arguments = "{}"
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("分析中国新能源汽车行业的市场格局")

    assert result.research_type == "industry_analysis"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_company_research(service):
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "company_research"
    mock_tool_call.function.arguments = "{}"
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("深度分析比亚迪公司的基本面")

    assert result.research_type == "company_research"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_comparative_analysis(service):
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "comparative_analysis"
    mock_tool_call.function.arguments = "{}"
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]
    mock_message.tool_calls = [mock_tool_call]
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("比较比亚迪和宁德时代的竞争优势")

    assert result.research_type == "comparative_analysis"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_fallback_on_exception(service):
    with patch.object(service.client.chat.completions, "create", new=AsyncMock(side_effect=Exception("timeout"))):
        result = await service.classify("任意问题")

    assert result.research_type == "industry_analysis"
    assert result.confidence == 0.0
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend
python -m pytest test/test_research_type_service.py -v 2>&1 | head -10
```

期望：`ModuleNotFoundError: No module named 'app.service.research_type_service'`

- [ ] **Step 3: 创建 research_type_service.py**

```python
"""研究类型识别服务 - Level 2 意图识别，使用 DashScope qwen-turbo function calling"""
import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

RESEARCH_TYPE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "industry_analysis",
            "description": (
                "对某个行业、赛道、市场进行深度分析，包括市场规模、竞争格局、"
                "波特五力、发展趋势等宏观分析。"
                "适用于：'分析新能源汽车行业'、'光伏赛道市场现状'、'XX行业竞争格局'等。"
                "不适用于聚焦单一公司或多公司对比的问题。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "company_research",
            "description": (
                "对单一公司进行深度调研，包括商业模式、财务状况、"
                "管理层、竞争优势与风险的尽调式分析。"
                "适用于：'分析比亚迪'、'XX公司基本面研究'、'XX公司投资价值'等。"
                "核心特征：问题中只涉及一个主体。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comparative_analysis",
            "description": (
                "对多个公司、产品或方案进行横向对比分析，输出结构化对比表格与综合结论。"
                "适用于：'比较比亚迪和宁德时代'、'XX vs YY 哪个更好'、'多家公司对比'等。"
                "核心特征：问题中明确涉及两个及以上对比主体。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

VALID_RESEARCH_TYPES = {"industry_analysis", "company_research", "comparative_analysis"}


@dataclass
class ResearchTypeResult:
    research_type: Literal["industry_analysis", "company_research", "comparative_analysis"]
    confidence: float  # 1.0 正常识别，0.0 表示 fallback


class ResearchTypeService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "qwen-turbo",
    ):
        self.model = model
        self.client = AsyncOpenAI(
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY", ""),
            base_url=base_url or os.getenv(
                "LLM_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )

    async def classify(self, query: str) -> ResearchTypeResult:
        """识别深度研究的具体类型，失败时 fallback 到 industry_analysis。"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的研究类型分类器。"
                            "根据用户的研究问题，判断属于行业分析、公司调研还是竞品对比。"
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                tools=RESEARCH_TYPE_TOOLS,
                tool_choice="required",
            )

            tool_call = response.choices[0].message.tool_calls[0]
            research_type = tool_call.function.name

            if research_type not in VALID_RESEARCH_TYPES:
                logger.warning(f"Unknown research type: {research_type}, falling back")
                return ResearchTypeResult(research_type="industry_analysis", confidence=0.0)

            return ResearchTypeResult(research_type=research_type, confidence=1.0)

        except Exception as e:
            logger.warning(f"ResearchTypeService.classify failed: {e}, falling back to industry_analysis")
            return ResearchTypeResult(research_type="industry_analysis", confidence=0.0)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend
python -m pytest test/test_research_type_service.py -v
```

期望：4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/research_type_service.py backend/test/test_research_type_service.py
git commit -m "feat(research-type): 实现 ResearchTypeService（Level 2 意图识别）"
```

---

### Task 3: 在 DeepResearchGraph 中添加 research_type_router 节点

**Files:**
- Modify: `backend/app/service/deep_research_v2/graph.py`

- [ ] **Step 1: 在 graph.py 顶部新增 import**

找到：
```python
try:
    from service.intent_service import IntentService
    from service.intent_handlers import web_search_node, simple_qa_node, out_of_scope_node
except ImportError:
    from app.service.intent_service import IntentService
    from app.service.intent_handlers import web_search_node, simple_qa_node, out_of_scope_node
```

在其后添加：
```python
try:
    from service.research_type_service import ResearchTypeService
except ImportError:
    from app.service.research_type_service import ResearchTypeService
```

- [ ] **Step 2: 在 __init__ 中初始化 ResearchTypeService**

找到：
```python
        # 意图识别服务
        self.intent_service = IntentService(
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            model=config.intent_model,
        )
```

在其后添加：
```python
        # 研究类型识别服务（Level 2）
        self.research_type_service = ResearchTypeService(
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            model=config.intent_model,
        )
```

- [ ] **Step 3: 添加 _research_type_router_node 方法**

找到 `_intent_router_node` 方法，在其**之后**插入：

```python
    async def _research_type_router_node(self, state: ResearchState) -> Dict[str, Any]:
        """研究类型识别节点（Level 2）：仅在 deep_research 路径触发。"""
        self._maybe_cancel(state)

        query = state.get("query", "")
        result = await self.research_type_service.classify(query)

        logger.info(
            f"Research type detected: {result.research_type} "
            f"(confidence={result.confidence:.2f}) for: {query[:50]}"
        )

        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
            writer({
                "type": "research_type_detected",
                "research_type": result.research_type,
                "confidence": result.confidence,
            })
        except (ImportError, RuntimeError, KeyError):
            pass

        return {"research_type": result.research_type}
```

- [ ] **Step 4: 修改 route_after_intent，将 deep_research 路由到 research_type_router**

找到：
```python
def route_after_intent(state: ResearchState) -> str:
    """intent_router 节点后的条件路由。"""
    intent = state.get("intent", "deep_research")
    if intent == "web_search":
        return "web_search"
    if intent == "simple_qa":
        return "simple_qa"
    if intent == "out_of_scope":
        return "out_of_scope"
    return "planner"
```

替换为：
```python
def route_after_intent(state: ResearchState) -> str:
    """intent_router 节点后的条件路由。"""
    intent = state.get("intent", "deep_research")
    if intent == "web_search":
        return "web_search"
    if intent == "simple_qa":
        return "simple_qa"
    if intent == "out_of_scope":
        return "out_of_scope"
    return "research_type_router"
```

- [ ] **Step 5: 修改 _build_langgraph，插入新节点**

找到 `_build_langgraph` 方法中的注册节点部分，在 `workflow.add_node("planner", ...)` 之前添加：

```python
        # Level 2 研究类型路由节点
        workflow.add_node("research_type_router", self._research_type_router_node)
```

找到条件边：
```python
        workflow.add_conditional_edges(
            "intent_router",
            route_after_intent,
            {
                "web_search": "web_search",
                "simple_qa": "simple_qa",
                "out_of_scope": "out_of_scope",
                "planner": "planner",
            },
        )
```

替换为：
```python
        workflow.add_conditional_edges(
            "intent_router",
            route_after_intent,
            {
                "web_search": "web_search",
                "simple_qa": "simple_qa",
                "out_of_scope": "out_of_scope",
                "research_type_router": "research_type_router",
            },
        )
```

在 `workflow.add_edge("web_search", END)` 之后添加：
```python
        workflow.add_edge("research_type_router", "planner")
```

- [ ] **Step 6: 更新 node_to_phase_info**

找到 `node_to_phase_info` 字典，在 `"intent_router"` 条目后添加：

```python
            "research_type_router": ("research_type", "研究类型识别完成"),
```

- [ ] **Step 7: 验证图构建**

```bash
cd backend
python -c "
from app.service.deep_research_v2.graph import DeepResearchGraph
g = DeepResearchGraph(llm_api_key='test', llm_base_url='http://test', search_api_key='test', model='qwen-turbo')
nodes = list(g.graph.nodes)
print('Nodes:', nodes)
assert 'research_type_router' in nodes
assert 'intent_router' in nodes
assert 'planner' in nodes
print('PASS')
"
```

期望：`PASS`，节点列表包含 `research_type_router`

- [ ] **Step 8: Commit**

```bash
git add backend/app/service/deep_research_v2/graph.py
git commit -m "feat(research-type): 在 DeepResearchGraph 中插入 research_type_router 节点"
```

---

### Task 4: 修改 Planner 加载 YAML 并注入 prompt

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/planner.py`

- [ ] **Step 1: 在 planner.py 顶部添加 import**

在现有 import 区（`import logging` 等之后）添加：

```python
from pathlib import Path
import yaml
```

- [ ] **Step 2: 添加 _load_research_skill 辅助函数**

在 `PLANNER_PROMPT` 常量之前插入：

```python
def _load_research_skill(research_type: str) -> dict:
    """加载 research_skills/{research_type}.yaml，文件不存在或格式错误时返回空配置。"""
    if not research_type or research_type == "general":
        return {}
    skill_path = Path(__file__).parent.parent.parent.parent / "research_skills" / f"{research_type}.yaml"
    try:
        if skill_path.exists():
            return yaml.safe_load(skill_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning(f"Failed to load research skill '{research_type}': {e}")
    return {}


def _format_outline_hint(outline_template: list) -> str:
    """将 outline_template 格式化为 Planner user prompt 中的参考文本。"""
    if not outline_template:
        return ""
    lines = ["参考章节框架（请以此为基础生成 outline，可根据具体问题适当调整）："]
    for i, section in enumerate(outline_template, 1):
        title = section.get("title", "")
        hints = section.get("search_query_hints", [])
        lines.append(f"{i}. {title}")
        if hints:
            lines.append(f"   搜索词示例：{', '.join(hints[:2])}")
    return "\n".join(lines)
```

- [ ] **Step 3: 修改 Planner.process() 注入 YAML 内容**

找到 `process` 方法中的 `try` 块，原始代码为：

```python
        try:
            response = await self.call_llm(
                system_prompt=PLANNER_PROMPT.replace("{query}", query),
                user_prompt=f"研究问题：{query}",
                json_mode=True,
                temperature=0.3,
                state=state,
                action="planner.generate_plan",
            )
```

替换为：

```python
        try:
            # 加载研究类型技能配置
            research_type = state.get("research_type", "")
            skill = _load_research_skill(research_type)
            skill_prompt = skill.get("planner_prompt", "")
            outline_hint = _format_outline_hint(skill.get("outline_template", []))

            # 构建 system prompt：技能 prompt 前置，提供具体研究框架
            base_system_prompt = PLANNER_PROMPT.replace("{query}", query)
            system_prompt = (
                skill_prompt.strip() + "\n\n" + base_system_prompt
                if skill_prompt
                else base_system_prompt
            )

            # 构建 user prompt：追加大纲参考
            user_prompt = f"研究问题：{query}"
            if outline_hint:
                user_prompt += f"\n\n{outline_hint}"

            response = await self.call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_mode=True,
                temperature=0.3,
                state=state,
                action="planner.generate_plan",
            )
```

- [ ] **Step 4: 验证 Planner 能正确加载 YAML**

```bash
cd backend
python -c "
from app.service.deep_research_v2.agents.planner import _load_research_skill, _format_outline_hint

skill = _load_research_skill('industry_analysis')
assert skill.get('name') == 'industry_analysis', f'Got: {skill}'
assert 'planner_prompt' in skill
assert len(skill.get('outline_template', [])) == 6

hint = _format_outline_hint(skill['outline_template'])
assert '市场规模' in hint
print('industry_analysis YAML loaded OK')

skill2 = _load_research_skill('nonexistent_type')
assert skill2 == {}, f'Expected empty dict, got: {skill2}'
print('fallback for unknown type: OK')

skill3 = _load_research_skill('general')
assert skill3 == {}
print('fallback for general: OK')
"
```

期望：3 行 OK 输出

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/planner.py
git commit -m "feat(research-type): Planner 按 research_type 加载 YAML 注入 prompt"
```

---

### Task 5: 端到端冒烟验证

**Files:**
- 无新增文件，仅运行验证

- [ ] **Step 1: 运行研究类型单元测试**

```bash
cd backend
python -m pytest test/test_research_type_service.py -v
```

期望：4 tests PASSED

- [ ] **Step 2: 验证图路由：deep_research → research_type_router → planner**

```bash
cd backend
python -c "
import asyncio
from unittest.mock import AsyncMock, patch
from app.service.intent_service import IntentResult
from app.service.research_type_service import ResearchTypeResult

async def test():
    from app.service.deep_research_v2.graph import DeepResearchGraph
    from app.service.deep_research_v2.state import create_initial_state

    g = DeepResearchGraph(
        llm_api_key='test',
        llm_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        search_api_key='test',
        model='qwen-turbo',
    )

    # mock Level 1: deep_research
    mock_intent = IntentResult(intent='deep_research', research_type='general', confidence=1.0)
    # mock Level 2: company_research
    mock_rtype = ResearchTypeResult(research_type='company_research', confidence=1.0)
    # mock Planner LLM（防止真实调用）
    mock_planner_resp = '{\"outline\": [{\"id\": \"sec_1\", \"title\": \"公司概况\", \"description\": \"...\", \"section_type\": \"qualitative\", \"status\": \"pending\", \"requires_data\": false, \"requires_chart\": false}], \"plan\": [{\"step_id\": \"step_search_sec_1\", \"tool\": \"search_section\", \"args\": {\"section_id\": \"sec_1\", \"queries\": [\"比亚迪 商业模式\"]}, \"depends_on\": [], \"parallel_group\": \"search_batch\"}]}'

    with patch.object(g.intent_service, 'classify', new=AsyncMock(return_value=mock_intent)), \
         patch.object(g.research_type_service, 'classify', new=AsyncMock(return_value=mock_rtype)), \
         patch.object(g.planner, 'call_llm', new=AsyncMock(return_value=mock_planner_resp)):

        state = create_initial_state('深度分析比亚迪公司', 'test-session')
        events = []
        async for mode, chunk in g.graph.astream(state, stream_mode=['custom', 'updates']):
            events.append((mode, chunk))

        custom = [c for m, c in events if m == 'custom']
        print('Custom events:', [e.get('type') for e in custom])

        # 验证两个意图识别事件都出现了
        assert any(e.get('type') == 'intent_detected' for e in custom), 'Missing intent_detected'
        assert any(e.get('type') == 'research_type_detected' for e in custom), 'Missing research_type_detected'

        rtype_event = next(e for e in custom if e.get('type') == 'research_type_detected')
        assert rtype_event['research_type'] == 'company_research'
        print('PASS: two-level intent recognition works, research_type_detected = company_research')

asyncio.run(test())
"
```

期望：`PASS: two-level intent recognition works`

- [ ] **Step 3: 验证 YAML 注入影响 Planner prompt（日志检查）**

```bash
cd backend
python -c "
from app.service.deep_research_v2.agents.planner import _load_research_skill, _format_outline_hint, PLANNER_PROMPT

# 模拟 Planner 构建 system_prompt 的逻辑
research_type = 'company_research'
skill = _load_research_skill(research_type)
skill_prompt = skill.get('planner_prompt', '')
outline_hint = _format_outline_hint(skill.get('outline_template', []))

system_prompt = skill_prompt.strip() + '\n\n' + PLANNER_PROMPT.replace('{query}', 'test')

assert '公司调研' in system_prompt, 'YAML prompt not injected'
assert '财务分析' in outline_hint, 'Outline hint missing expected section'
print('System prompt injection: OK')
print('Outline hint preview:')
print(outline_hint[:300])
"
```

期望：`System prompt injection: OK` + outline_hint 前 300 字符

- [ ] **Step 4: 运行全量 eval 测试确认无回归**

```bash
cd backend
python -m pytest app/eval/tests/ -q 2>&1 | tail -5
```

期望：51 passed，无新失败

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit --allow-empty -m "test(research-type): 端到端冒烟验证通过"
```

---

## 自检结果

**Spec 覆盖：**
- ✅ 三个 YAML 文件（industry_analysis / company_research / comparative_analysis）→ Task 1
- ✅ ResearchTypeService（function calling，3 类工具，fallback）→ Task 2
- ✅ research_type_router 节点 → Task 3
- ✅ route_after_intent 改为路由到 research_type_router → Task 3 Step 4
- ✅ research_type_router → planner 无条件边 → Task 3 Step 5
- ✅ node_to_phase_info 更新 → Task 3 Step 6
- ✅ _load_research_skill 辅助函数 → Task 4 Step 2
- ✅ Planner.process() 注入 skill_prompt + outline_hint → Task 4 Step 3
- ✅ 错误处理：YAML 不存在返回空配置 → Task 4 Step 2
- ✅ SSE 新事件 research_type_detected → Task 3 Step 3

**类型一致性：**
- `ResearchTypeResult.research_type` 在 Task 2 定义，Task 3 `_research_type_router_node` 读 `.research_type` / `.confidence` ✅
- `_load_research_skill(research_type: str) -> dict` 在 Task 4 定义，Task 5 Step 3 验证调用 ✅
- YAML key `planner_prompt` / `outline_template` 在 Task 1 定义，Task 4 读取时使用相同 key ✅
