# 意图识别层 设计文档

## 目标

在现有 Plan-and-Execute 研究流程前置一层意图识别，将用户查询自动分流到合适的处理路径，避免所有请求都触发代价高昂的全流程。不需要规划的任务不进入 Planner。

---

## 最终架构：LangGraph 子图方案

```
POST /research/stream
  │
  └─ RouterGraph（新，外层路由图）
       │
       ├─ IntentRouter 节点（新）
       │    function calling → qwen-turbo
       │    写入 intent / research_type 到 state
       │    发送 SSE: intent_detected
       │
       ├─ deep_research ──→ DeepResearchSubgraph（现有图，直接编译为子图）
       │                      Planner → Executor → Critic → Replanner
       │
       ├─ web_search ─────→ WebSearchNode（新，Serper + qwen-turbo 合成）
       │
       ├─ simple_qa ──────→ SimpleQANode（新，qwen-turbo 直接回答）
       │
       └─ out_of_scope ───→ OutOfScopeNode（新，固定拒绝消息）
```

---

## 意图分类（Function Calling 工具定义）

每个意图对应一个独立 tool，LLM 选择最匹配的工具：

| Tool 名称 | 触发场景 | 示例 |
|---|---|---|
| `deep_research` | 需要深度调研的行业/市场/公司分析 | "分析中国新能源汽车行业的竞争格局" |
| `web_search` | 需要实时信息但不需要深度分析 | "最新CPI数据" / "今天有什么财经新闻" |
| `simple_qa` | 概念解释、定义、常识性问题 | "什么是市盈率PE" / "ROE怎么计算" |
| `out_of_scope` | 领域外问题、闲聊 | "帮我写首诗" / "今天天气怎么样" |

`deep_research` tool 携带 `research_type` 参数，供后续细分研究流程：

```python
{
  "name": "deep_research",
  "parameters": {
    "research_type": {
      "type": "string",
      "enum": ["general"],   # 后续扩展: "industry_analysis", "company_research", "comparative"
      "description": "研究类型，影响 Planner 使用的 prompt 配置"
    }
  }
}
```

> 扩展新研究类型只需：① 在 enum 加一项 ② Planner 里加对应 prompt 配置，其余代码不动。

---

## State 设计

### 外层 RouterState（新建）

```python
class RouterState(TypedDict):
    query: str
    session_id: str
    intent: str                    # "deep_research" | "web_search" | "simple_qa" | "out_of_scope"
    research_type: str             # deep_research 专用，默认 "general"
    messages: List[Dict]           # SSE 消息队列（与内层图共享 key）
```

### 内层 ResearchState（现有，不改）

父子图通过共享 key 通信：`query`、`session_id`、`messages` 三个字段对齐，其余字段（`outline`、`facts` 等）只存在于子图内部。

---

## 新建 / 修改文件

### 新建文件

| 文件 | 职责 | 预估行数 |
|---|---|---|
| `backend/app/service/intent_service.py` | IntentService：function calling 分类，返回 IntentResult | ~80 行 |
| `backend/app/service/router_graph.py` | RouterGraph：外层路由图，含 4 个条件边 | ~100 行 |
| `backend/app/service/intent_handlers.py` | WebSearchNode / SimpleQANode / OutOfScopeNode | ~80 行 |

### 修改文件

| 文件 | 改动内容 |
|---|---|
| `backend/app/service/deep_research_v2/graph.py` | 暴露 `compile_as_subgraph()` 方法（+5 行） |
| `backend/app/service/deep_research_v2/state.py` | ResearchState 新增 `intent`、`research_type` 字段 |
| `backend/app/service/deep_research_v2/service.py` | 换成调用 RouterGraph 而非 DeepResearchGraph |
| `backend/app/config/llm_config.py` | 新增 `intent_model: str = "qwen-turbo"` |

---

## IntentService 设计

```python
@dataclass
class IntentResult:
    intent: Literal["deep_research", "web_search", "simple_qa", "out_of_scope"]
    research_type: str    # deep_research 时有值，其余为 ""
    confidence: float

class IntentService:
    async def classify(self, query: str) -> IntentResult: ...
```

- 使用 `openai` SDK 连接 DashScope（`DASHSCOPE_API_KEY` + `DASHSCOPE_BASE_URL`，已有环境变量）
- 模型：`qwen-turbo`，`tool_choice="required"`
- 解析失败时 fallback 到 `deep_research`，`confidence=0.0`
- 目标延迟 **< 500ms**

---

## 各节点 SSE 事件序列

所有路径均以 `intent_detected` 开始、`done` 结束：

**deep_research：**
```
intent_detected → （现有所有事件不变）→ done
```

**web_search：**
```
intent_detected → search_results → answer_chunk(×N) → done
```

**simple_qa：**
```
intent_detected → answer_chunk(×N) → done
```

**out_of_scope：**
```
intent_detected → answer_chunk → done
```

### 新增 SSE 事件类型

| 事件类型 | 字段 | 说明 |
|---|---|---|
| `intent_detected` | `intent`, `research_type`, `confidence` | 分流前发送 |
| `search_results` | `results: [{title, url, snippet}]` | web_search 专用 |
| `answer_chunk` | `content: str` | 非 deep_research 路径的流式内容 |

---

## 错误处理

| 场景 | 处理方式 |
|---|---|
| IntentService 超时（>3s）或异常 | fallback `deep_research`，继续执行 |
| WebSearchService 失败 | 降级为不带搜索结果的 simple_qa |
| LLM 调用失败 | `{"type": "error", "content": "..."}` 后结束 |

---

## 不在本期范围

- `deep_research` 细分类型（`industry_analysis` / `company_research` / `comparative_analysis`）—— 架构已预留，后续加 enum 值即可
- 多轮确认研究范围（Gemini Deep Research 风格）
- 意图识别结果缓存
- BERT 微调替换 function calling
