# 意图识别层 设计文档

## 目标

在 `/research/stream` 接口前置一层意图识别，将用户查询自动分流到合适的处理路径，避免所有请求都触发代价高昂的 Plan-and-Execute 全流程。

---

## 架构概览

```
POST /research/stream
  │
  ├─ IntentService（qwen-turbo, few-shot, <500ms）
  │     └─ 发送 SSE: intent_detected
  │
  ├─ deep_research  → DeepResearchV2Service（现有，不改）
  ├─ web_search     → WebSearchHandler（新建）
  ├─ simple_qa      → SimpleQAHandler（新建）
  └─ out_of_scope   → OutOfScopeHandler（新建）
```

---

## 意图分类

| 意图 | 触发场景 | 示例 |
|---|---|---|
| `deep_research` | 需要深度调研的行业/市场/公司分析 | "分析中国新能源汽车行业的竞争格局" |
| `web_search` | 需要实时信息但不需要深度分析 | "最新CPI数据是多少" / "今天有什么财经新闻" |
| `simple_qa` | 概念解释、定义、常识性问题 | "什么是市盈率PE" / "ROE怎么计算" |
| `out_of_scope` | 领域外问题、闲聊 | "帮我写首诗" / "今天天气怎么样" |

---

## 新建文件

### `backend/app/service/intent_service.py`

**职责：** 调用 DashScope qwen-turbo，few-shot 分类用户查询，返回结构化意图结果。

**接口：**
```python
class IntentService:
    async def classify(self, query: str) -> IntentResult:
        ...

@dataclass
class IntentResult:
    intent: Literal["deep_research", "web_search", "simple_qa", "out_of_scope"]
    confidence: float   # 0.0 ~ 1.0
    reasoning: str      # 一句话解释
```

**实现细节：**
- 使用 `openai` SDK 连接 DashScope（`DASHSCOPE_API_KEY` + `DASHSCOPE_BASE_URL`，已有）
- 模型：`qwen-turbo`
- 请求 JSON output（`response_format={"type": "json_object"}`）
- Few-shot prompt 每类 3 条示例，共 12 条，覆盖边界情况
- 解析失败时默认 fallback 到 `deep_research`，confidence=0.0

**Few-shot 示例设计原则：**
- `deep_research` vs `web_search` 边界：是否需要多源综合分析
- `simple_qa` vs `deep_research` 边界：是否需要实时数据支撑
- `out_of_scope`：明确非金融/行业研究领域

---

### `backend/app/service/intent_handlers.py`

**职责：** 三个轻量 handler，每个返回 `AsyncGenerator[str, None]`（SSE 格式），与现有 DeepResearchV2Service 接口一致。

#### WebSearchHandler

```
流程：
1. WebSearchService.search(query, gl="cn", hl="zh-cn") → top 5 结果
2. 将结果格式化为 context
3. qwen-turbo 流式生成回答（stream=True）
4. yield SSE 事件
```

SSE 事件序列：
```
{"type": "search_results", "results": [...]}   # 搜索结果摘要
{"type": "answer_chunk", "content": "..."}     # 多条，流式
{"type": "done"}
```

#### SimpleQAHandler

```
流程：
1. qwen-turbo 直接流式生成（stream=True）
2. yield SSE 事件
```

SSE 事件序列：
```
{"type": "answer_chunk", "content": "..."}     # 多条，流式
{"type": "done"}
```

**system prompt：** 定位为专业金融/行业研究助手，回答简洁准确，不超过 300 字。

#### OutOfScopeHandler

```
流程：
1. 直接 yield 固定拒绝消息
```

SSE 事件序列：
```
{"type": "answer_chunk", "content": "抱歉，我专注于行业研究和金融分析领域，暂时无法回答这类问题。"}
{"type": "done"}
```

---

## 修改文件

### `backend/app/router/research_router.py`

在 `stream_research` 中，`DeepResearchV2Service.research()` 调用前插入意图识别：

```python
async def generate_sse():
    # 1. 意图识别
    intent_result = await intent_service.classify(request.query)
    yield format_sse({"type": "intent_detected",
                      "intent": intent_result.intent,
                      "confidence": intent_result.confidence})

    # 2. 分流
    if intent_result.intent == "deep_research":
        async for event in service_v2.research(...):
            yield event
    elif intent_result.intent == "web_search":
        async for event in web_search_handler.handle(request.query):
            yield event
    elif intent_result.intent == "simple_qa":
        async for event in simple_qa_handler.handle(request.query):
            yield event
    else:  # out_of_scope
        async for event in out_of_scope_handler.handle():
            yield event
```

### `backend/app/config/llm_config.py`

新增 intent 模型配置：

```python
@dataclass
class LLMConfig:
    ...
    intent_model: str = "qwen-turbo"   # 意图识别专用模型
```

---

## SSE 新增事件类型

| 事件类型 | 字段 | 说明 |
|---|---|---|
| `intent_detected` | `intent`, `confidence` | 意图识别完成，分流前发送 |
| `search_results` | `results: List[{title, url, snippet}]` | web_search handler 专用 |
| `answer_chunk` | `content: str` | simple_qa / web_search / out_of_scope 的流式内容 |
| `done` | — | 非 deep_research 路径的结束标志 |

> `deep_research` 路径沿用现有所有事件类型，不变。

---

## 错误处理

- IntentService 调用超时（>3s）或异常 → fallback `deep_research`，不中断请求
- WebSearchService 失败 → 降级为 simple_qa（不带搜索结果直接回答）
- LLM 调用失败 → yield `{"type": "error", "content": "..."}` 后结束

---

## 不在本期范围内

- 多轮确认研究范围（Gemini Deep Research 风格）
- 意图识别结果缓存
- 前端 UI 按意图类型差异化展示（前端可自行根据 `intent_detected` 事件适配）
- BERT 微调替换 few-shot（后续优化项）
