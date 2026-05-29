# 意图识别层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DeepResearchGraph 入口添加意图识别节点，通过 function calling 将用户查询自动分流到 deep_research / web_search / simple_qa / out_of_scope 四条路径。

**Architecture:** IntentRouter 成为 LangGraph 图的入口节点，通过 DashScope qwen-turbo function calling 分类意图，写入 ResearchState 后通过条件边路由；web_search / simple_qa / out_of_scope 三条轻量路径新增为独立节点，使用 `get_stream_writer()` 推 SSE 事件，不进入 Planner。

**Tech Stack:** LangGraph, openai SDK (DashScope compatible), langgraph.config.get_stream_writer, WebSearchService (Serper API)

---

## 文件结构

```
新建:
  backend/app/service/intent_service.py      # IntentService: function calling 分类
  backend/app/service/intent_handlers.py     # web_search_node / simple_qa_node / out_of_scope_node
  backend/tests/test_intent_service.py       # IntentService 单元测试

修改:
  backend/app/service/deep_research_v2/state.py   # 新增 intent / research_type 字段
  backend/app/service/deep_research_v2/graph.py   # 新增 intent_router 节点 + 条件边 + 轻量节点
  backend/app/config/llm_config.py                # 新增 intent_model 字段
```

---

### Task 1: 扩展 ResearchState

**Files:**
- Modify: `backend/app/service/deep_research_v2/state.py`

- [ ] **Step 1: 在 ResearchState 中新增两个字段**

在 `state.py` 的 `ResearchState` TypedDict，找到 `# 搜索模式配置` 段落，在其后添加：

```python
    # 意图识别结果
    intent: str                              # "deep_research" | "web_search" | "simple_qa" | "out_of_scope"
    research_type: str                       # deep_research 专用，默认 "general"
```

完整修改后该段落如下：

```python
    # 搜索模式配置
    search_web: bool                        # 是否启用网络搜索
    search_local: bool                      # 是否启用本地知识库搜索

    # 意图识别结果
    intent: str                              # "deep_research" | "web_search" | "simple_qa" | "out_of_scope"
    research_type: str                       # deep_research 专用，默认 "general"
```

- [ ] **Step 2: 在 create_initial_state 中设置默认值**

找到 `create_initial_state` 函数中的 `return ResearchState(...)` 调用，在 `search_web=search_web,` 之后添加：

```python
        intent="",
        research_type="general",
```

- [ ] **Step 3: 验证语法**

```bash
cd backend
python -c "from app.service.deep_research_v2.state import create_initial_state; s = create_initial_state('test', 'sid'); print(s['intent'], s['research_type'])"
```

Expected output: ` general`

- [ ] **Step 4: Commit**

```bash
git add backend/app/service/deep_research_v2/state.py
git commit -m "feat(intent): 在 ResearchState 中新增 intent/research_type 字段"
```

---

### Task 2: 新增 intent_model 配置

**Files:**
- Modify: `backend/app/config/llm_config.py`

- [ ] **Step 1: 在 LLMConfig 中新增 intent_model 字段**

在 `LLMConfig` dataclass 的 `default_model` 字段下方添加：

```python
    # 意图识别模型（轻量快速）
    intent_model: str = "qwen-turbo"
```

- [ ] **Step 2: 验证**

```bash
cd backend
python -c "from app.config.llm_config import get_config; c = get_config(); print(c.intent_model)"
```

Expected output: `qwen-turbo`

- [ ] **Step 3: Commit**

```bash
git add backend/app/config/llm_config.py
git commit -m "feat(intent): 新增 intent_model 配置项"
```

---

### Task 3: 实现 IntentService

**Files:**
- Create: `backend/app/service/intent_service.py`
- Create: `backend/tests/test_intent_service.py`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_intent_service.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.service.intent_service import IntentService, IntentResult


@pytest.fixture
def service():
    return IntentService(api_key="test-key", base_url="https://example.com", model="qwen-turbo")


@pytest.mark.asyncio
async def test_classify_deep_research(service):
    """深度研究意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "deep_research"
    mock_tool_call.function.arguments = '{"research_type": "general"}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("分析中国新能源汽车行业的竞争格局")

    assert result.intent == "deep_research"
    assert result.research_type == "general"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_web_search(service):
    """网络搜索意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "web_search"
    mock_tool_call.function.arguments = '{}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("最新CPI数据是多少")

    assert result.intent == "web_search"
    assert result.research_type == ""
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_fallback_on_exception(service):
    """调用异常时 fallback 到 deep_research"""
    with patch.object(service.client.chat.completions, "create", new=AsyncMock(side_effect=Exception("timeout"))):
        result = await service.classify("任意问题")

    assert result.intent == "deep_research"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_classify_simple_qa(service):
    """简单问答意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "simple_qa"
    mock_tool_call.function.arguments = '{}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("什么是市盈率PE")

    assert result.intent == "simple_qa"


@pytest.mark.asyncio
async def test_classify_out_of_scope(service):
    """领域外意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "out_of_scope"
    mock_tool_call.function.arguments = '{}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("帮我写首诗")

    assert result.intent == "out_of_scope"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend
python -m pytest tests/test_intent_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.service.intent_service'`

- [ ] **Step 3: 实现 IntentService**

创建 `backend/app/service/intent_service.py`：

```python
"""意图识别服务 - 使用 DashScope qwen-turbo function calling"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

INTENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": (
                "用户需要对行业、市场、公司进行深度调研分析，需要综合多个信息源、"
                "生成结构化报告。例如：行业竞争格局分析、市场规模预测、公司基本面研究、"
                "政策影响分析、赛道对比研究等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "research_type": {
                        "type": "string",
                        "enum": ["general"],
                        "description": "研究类型，当前仅支持 general",
                    }
                },
                "required": ["research_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "用户需要获取实时、最新的信息，但不需要深度分析报告。"
                "例如：最新数据查询、近期新闻、实时行情、今日热点等。"
                "不适用于需要综合分析的问题。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simple_qa",
            "description": (
                "用户提出的是概念性、定义性、常识性问题，可以直接回答，"
                "不需要实时数据或深度调研。"
                "例如：解释金融术语、计算公式说明、基础概念问答。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "out_of_scope",
            "description": (
                "用户的问题与金融、行业研究、投资分析完全无关，属于领域外问题或闲聊。"
                "例如：诗歌创作、天气查询、游戏推荐、日常闲聊等。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

VALID_INTENTS = {"deep_research", "web_search", "simple_qa", "out_of_scope"}


@dataclass
class IntentResult:
    intent: Literal["deep_research", "web_search", "simple_qa", "out_of_scope"]
    research_type: str   # deep_research 时为 "general"，其余为 ""
    confidence: float    # 1.0 正常识别，0.0 表示 fallback


class IntentService:
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

    async def classify(self, query: str) -> IntentResult:
        """用 function calling 识别用户查询意图，失败时 fallback 到 deep_research。"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的意图分类器，服务于行业研究助手系统。"
                            "根据用户问题，选择最匹配的处理方式。"
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                tools=INTENT_TOOLS,
                tool_choice="required",
            )

            tool_call = response.choices[0].message.tool_calls[0]
            intent_name = tool_call.function.name

            if intent_name not in VALID_INTENTS:
                logger.warning(f"Unknown intent tool: {intent_name}, falling back to deep_research")
                return IntentResult(intent="deep_research", research_type="general", confidence=0.0)

            research_type = ""
            if intent_name == "deep_research":
                args = json.loads(tool_call.function.arguments or "{}")
                research_type = args.get("research_type", "general")

            return IntentResult(intent=intent_name, research_type=research_type, confidence=1.0)

        except Exception as e:
            logger.warning(f"IntentService.classify failed: {e}, falling back to deep_research")
            return IntentResult(intent="deep_research", research_type="general", confidence=0.0)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend
python -m pytest tests/test_intent_service.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/intent_service.py backend/tests/test_intent_service.py
git commit -m "feat(intent): 实现 IntentService（function calling 意图分类）"
```

---

### Task 4: 实现轻量节点函数

**Files:**
- Create: `backend/app/service/intent_handlers.py`

- [ ] **Step 1: 创建 intent_handlers.py**

```python
"""
轻量意图处理节点 - web_search / simple_qa / out_of_scope

每个函数是 LangGraph 节点，通过 get_stream_writer() 推 SSE 事件。
返回空 dict（不需要修改 ResearchState）。
"""
import os
import logging
from typing import Dict, Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _get_writer():
    """获取 LangGraph stream writer，非图上下文时返回 None。"""
    try:
        from langgraph.config import get_stream_writer
        return get_stream_writer()
    except (ImportError, RuntimeError, KeyError):
        return None


def _emit(writer, event: Dict[str, Any]) -> None:
    if writer:
        writer(event)


def _make_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        base_url=os.getenv(
            "LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )


# ── LangGraph 节点函数 ────────────────────────────────────────────────────────

async def web_search_node(state: Dict[str, Any]) -> Dict:
    """网络搜索节点：Serper 搜索 + qwen-turbo 合成，流式输出。"""
    from app.service.web_search_service import WebSearchService
    from app.service.config import ServiceConfig

    writer = _get_writer()
    query = state.get("query", "")

    # 1. 搜索
    config = ServiceConfig.get_api_config()
    svc = WebSearchService(api_key=config.get("serper_api_key"))
    raw = svc.search(query, gl="cn", hl="zh-cn")
    results = svc.extract_search_results(raw)[:5]

    _emit(writer, {
        "type": "search_results",
        "results": [
            {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
            for r in results
        ],
    })

    # 2. LLM 合成（流式）
    context = "\n\n".join(
        f"[{i+1}] {r.get('title', '')}\n{r.get('snippet', '')}"
        for i, r in enumerate(results)
    )
    client = _make_llm_client()
    stream = await client.chat.completions.create(
        model="qwen-turbo",
        messages=[
            {
                "role": "system",
                "content": "你是专业的金融行业研究助手，请根据以下搜索结果简洁准确地回答用户问题，不超过500字。",
            },
            {
                "role": "user",
                "content": f"问题：{query}\n\n搜索结果：\n{context}",
            },
        ],
        stream=True,
    )

    async for chunk in stream:
        content = chunk.choices[0].delta.content or ""
        if content:
            _emit(writer, {"type": "answer_chunk", "content": content})

    _emit(writer, {"type": "done"})
    return {}


async def simple_qa_node(state: Dict[str, Any]) -> Dict:
    """直接问答节点：qwen-turbo 直接回答，流式输出。"""
    writer = _get_writer()
    query = state.get("query", "")

    client = _make_llm_client()
    stream = await client.chat.completions.create(
        model="qwen-turbo",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是专业的金融行业研究助手，擅长解释金融概念、投资术语和行业知识。"
                    "请简洁准确地回答问题，不超过300字。"
                ),
            },
            {"role": "user", "content": query},
        ],
        stream=True,
    )

    async for chunk in stream:
        content = chunk.choices[0].delta.content or ""
        if content:
            _emit(writer, {"type": "answer_chunk", "content": content})

    _emit(writer, {"type": "done"})
    return {}


async def out_of_scope_node(state: Dict[str, Any]) -> Dict:
    """领域外问题节点：发送固定拒绝消息。"""
    writer = _get_writer()
    _emit(writer, {
        "type": "answer_chunk",
        "content": "抱歉，我专注于行业研究和金融分析领域，暂时无法回答这类问题。如有行业研究相关的问题，欢迎继续提问。",
    })
    _emit(writer, {"type": "done"})
    return {}
```

- [ ] **Step 2: 验证语法**

```bash
cd backend
python -c "from app.service.intent_handlers import web_search_node, simple_qa_node, out_of_scope_node; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/service/intent_handlers.py
git commit -m "feat(intent): 实现 web_search / simple_qa / out_of_scope 轻量节点"
```

---

### Task 5: 在 DeepResearchGraph 中添加 IntentRouter 节点

**Files:**
- Modify: `backend/app/service/deep_research_v2/graph.py`

- [ ] **Step 1: 在 graph.py 顶部 import 区新增导入**

在 `from .state import ResearchState, ResearchPhase, create_initial_state` 这行之后添加：

```python
from service.intent_service import IntentService
from service.intent_handlers import web_search_node, simple_qa_node, out_of_scope_node
```

同样加入 try/except 兼容模式（与文件其他 import 风格一致）：

```python
try:
    from service.intent_service import IntentService
    from service.intent_handlers import web_search_node, simple_qa_node, out_of_scope_node
except ImportError:
    from app.service.intent_service import IntentService
    from app.service.intent_handlers import web_search_node, simple_qa_node, out_of_scope_node
```

- [ ] **Step 2: 在 DeepResearchGraph.__init__ 中初始化 IntentService**

在 `__init__` 方法末尾，`self.graph = self._build_langgraph()` 之前，添加：

```python
        # 意图识别服务
        self.intent_service = IntentService(
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            model=config.intent_model,
        )
```

- [ ] **Step 3: 在 DeepResearchGraph 中添加 _intent_router_node 方法**

在 `_maybe_cancel` 方法之前插入：

```python
    async def _intent_router_node(self, state: ResearchState) -> Dict[str, Any]:
        """意图识别入口节点：function calling 分类，写入 intent/research_type，推 SSE 事件。"""
        self._maybe_cancel(state)

        query = state.get("query", "")
        result = await self.intent_service.classify(query)

        logger.info(f"Intent detected: {result.intent} (confidence={result.confidence:.2f}) for: {query[:50]}")

        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
            writer({
                "type": "intent_detected",
                "intent": result.intent,
                "research_type": result.research_type,
                "confidence": result.confidence,
            })
        except (ImportError, RuntimeError, KeyError):
            pass

        return {"intent": result.intent, "research_type": result.research_type}
```

- [ ] **Step 4: 添加路由函数 route_after_intent**

在模块顶层（`MAX_REPLAN` 常量下方）添加：

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
    return "planner"   # deep_research 或未知意图都走 planner
```

- [ ] **Step 5: 修改 _build_langgraph，添加新节点和条件边**

找到 `_build_langgraph` 方法，将其完整替换为：

```python
    def _build_langgraph(self):
        """构建 v3 Plan-and-Execute 主图（含意图路由入口）

        拓扑：

            intent_router
              ├── web_search   → END
              ├── simple_qa    → END
              ├── out_of_scope → END
              └── planner → executor → critic
                                         ├── pass → END
                                         └── needs_revision → replanner
                                                                ├── max_replan → END
                                                                └── default → executor
        """
        workflow = StateGraph(ResearchState)

        # 意图路由入口
        workflow.add_node("intent_router", self._intent_router_node)

        # 轻量路径节点
        workflow.add_node("web_search", web_search_node)
        workflow.add_node("simple_qa", simple_qa_node)
        workflow.add_node("out_of_scope", out_of_scope_node)

        # 深度研究路径节点（原有）
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("executor", executor_node)
        workflow.add_node("critic", self._critic_node)
        workflow.add_node("replanner", self._replanner_node)

        # 入口改为 intent_router
        workflow.set_entry_point("intent_router")

        # intent_router 条件分流
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

        # 轻量路径直接结束
        workflow.add_edge("web_search", END)
        workflow.add_edge("simple_qa", END)
        workflow.add_edge("out_of_scope", END)

        # 深度研究路径（原有逻辑不变）
        workflow.add_edge("planner", "executor")
        workflow.add_edge("executor", "critic")

        workflow.add_conditional_edges(
            "critic",
            route_after_critic,
            {"END": END, "replanner": "replanner"},
        )

        workflow.add_conditional_edges(
            "replanner",
            route_after_replanner,
            {
                "END": END,
                "executor": "executor",
            },
        )

        return workflow.compile()
```

- [ ] **Step 6: 更新 _run_with_langgraph 中的 node_to_phase_info**

找到 `node_to_phase_info` 字典，添加新节点映射：

```python
        node_to_phase_info = {
            "intent_router": ("intent", "意图识别完成"),
            "web_search": ("web_search", "网络搜索完成"),
            "simple_qa": ("simple_qa", "问答完成"),
            "out_of_scope": ("out_of_scope", "已处理"),
            "planner": ("planning", "规划完成"),
            "executor": ("executing", "执行批次完成"),
            "critic": ("reviewing", "审核完成"),
            "replanner": ("replanning", "重规划完成"),
        }
```

- [ ] **Step 7: 验证图构建不报错**

```bash
cd backend
python -c "
from app.service.deep_research_v2.graph import DeepResearchGraph
g = DeepResearchGraph(llm_api_key='test', llm_base_url='http://test', search_api_key='test', model='qwen-turbo')
print('Graph built OK, nodes:', list(g.graph.nodes))
"
```

Expected: `Graph built OK, nodes: ['intent_router', 'web_search', 'simple_qa', 'out_of_scope', 'planner', 'executor', 'critic', 'replanner', '__start__']`

- [ ] **Step 8: Commit**

```bash
git add backend/app/service/deep_research_v2/graph.py
git commit -m "feat(intent): 在 DeepResearchGraph 中添加 intent_router 入口节点和轻量路径"
```

---

### Task 6: 端到端冒烟验证

**Files:**
- 无新增文件，仅运行验证

- [ ] **Step 1: 运行所有意图相关测试**

```bash
cd backend
python -m pytest tests/test_intent_service.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 2: 验证 out_of_scope 路径（mock 意图识别）**

```bash
cd backend
python -c "
import asyncio
from unittest.mock import AsyncMock, patch
from app.service.intent_service import IntentResult

async def test():
    from app.service.deep_research_v2.graph import DeepResearchGraph
    from app.service.deep_research_v2.state import create_initial_state

    g = DeepResearchGraph(
        llm_api_key='test',
        llm_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        search_api_key='test',
        model='qwen-turbo',
    )

    # mock 意图识别返回 out_of_scope
    mock_result = IntentResult(intent='out_of_scope', research_type='', confidence=1.0)
    with patch.object(g.intent_service, 'classify', new=AsyncMock(return_value=mock_result)):
        state = create_initial_state('帮我写首诗', 'test-session')
        events = []
        async for mode, chunk in g.graph.astream(state, stream_mode=['custom', 'updates']):
            events.append((mode, chunk))
        print('Events received:', len(events))
        custom_events = [c for m, c in events if m == 'custom']
        print('Custom events:', custom_events)
        assert any(e.get('type') == 'done' for e in custom_events), 'Missing done event'
        print('PASS: out_of_scope path works')

asyncio.run(test())
"
```

Expected: `PASS: out_of_scope path works`

- [ ] **Step 3: 验证 simple_qa 路径（mock 意图识别 + mock LLM）**

```bash
cd backend
python -c "
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock
from app.service.intent_service import IntentResult

async def test():
    from app.service.deep_research_v2.graph import DeepResearchGraph
    from app.service.deep_research_v2.state import create_initial_state

    g = DeepResearchGraph(
        llm_api_key='test',
        llm_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        search_api_key='test',
        model='qwen-turbo',
    )

    # mock 意图识别 + LLM 流式响应
    mock_intent = IntentResult(intent='simple_qa', research_type='', confidence=1.0)

    # 模拟 stream chunk
    mock_chunk = MagicMock()
    mock_chunk.choices = [MagicMock(delta=MagicMock(content='市盈率是股价除以每股收益。'))]

    async def mock_stream():
        yield mock_chunk

    mock_create = AsyncMock(return_value=mock_stream())

    with patch.object(g.intent_service, 'classify', new=AsyncMock(return_value=mock_intent)), \
         patch('app.service.intent_handlers.AsyncOpenAI') as MockClient:
        MockClient.return_value.chat.completions.create = mock_create
        state = create_initial_state('什么是市盈率', 'test-session')
        events = []
        async for mode, chunk in g.graph.astream(state, stream_mode=['custom', 'updates']):
            events.append((mode, chunk))
        custom_events = [c for m, c in events if m == 'custom']
        intents = [e for e in custom_events if e.get('type') == 'intent_detected']
        assert intents[0]['intent'] == 'simple_qa', f'Wrong intent: {intents}'
        print('PASS: simple_qa path - intent_detected event correct')

asyncio.run(test())
"
```

Expected: `PASS: simple_qa path - intent_detected event correct`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(intent): 意图识别层完成 - function calling 路由 + 轻量节点"
```

---

## 自检结果

**Spec 覆盖：**
- ✅ IntentService（function calling，qwen-turbo，fallback）→ Task 3
- ✅ 4 类意图工具定义 → Task 3 `INTENT_TOOLS`
- ✅ intent/research_type 写入 ResearchState → Task 1 + Task 5
- ✅ intent_detected SSE 事件 → Task 5 `_intent_router_node`
- ✅ web_search_node（Serper + LLM 合成）→ Task 4
- ✅ simple_qa_node（直接 LLM）→ Task 4
- ✅ out_of_scope_node（固定消息）→ Task 4
- ✅ 条件路由边 → Task 5 `route_after_intent`
- ✅ node_to_phase_info 更新 → Task 5 Step 6
- ✅ 错误处理 fallback → Task 3 `classify` except 块
- ✅ intent_model 配置 → Task 2

**类型一致性：**
- `IntentResult.intent` 在 Task 3 定义，Task 5 `_intent_router_node` 读 `.intent` / `.research_type` / `.confidence` ✅
- `route_after_intent` 读 `state.get("intent")` ✅，Task 1 确保字段存在 ✅
- `web_search_node / simple_qa_node / out_of_scope_node` 签名均为 `(state: Dict) -> Dict` ✅
