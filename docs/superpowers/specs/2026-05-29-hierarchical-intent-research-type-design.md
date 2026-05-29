# 分层意图识别 + 细粒度研究类型 设计文档

## 目标

在现有 Level 1 意图识别（intent_router）基础上，新增 Level 2 研究类型路由节点（research_type_router），实现两级分层意图识别。通过 YAML 配置文件驱动不同研究类型的 Planner 策略，支持无代码扩展新研究类型。

---

## 架构概览

```
intent_router（Level 1，已有）
  ├── web_search     → WebSearchNode → END
  ├── simple_qa      → SimpleQANode  → END
  ├── out_of_scope   → OutOfScopeNode → END
  └── deep_research  → research_type_router（Level 2，新增）
                          └── 任意 research_type → planner（加载 YAML）→ executor → critic → ...
```

**分层职责：**

| 层级 | 节点 | 职责 | 技术实现 |
|---|---|---|---|
| Level 1 | `intent_router` | 粗粒度：做什么任务 | function calling，4 类意图 |
| Level 2 | `research_type_router` | 细粒度：怎么研究 | function calling，N 类研究类型 |
| 配置层 | YAML 文件 | 研究结构：用什么框架 | 代码加载，注入 Planner |
| 执行层 | `planner` LLM | query 定制：搜什么 | LLM 在模板内自由生成 |

---

## 新增 / 修改文件

```
新建:
  backend/app/research_skills/
    industry_analysis.yaml       # 行业分析
    company_research.yaml        # 公司调研
    comparative_analysis.yaml    # 竞品对比

  backend/app/service/research_type_service.py   # Level 2 分类服务

修改:
  backend/app/service/deep_research_v2/graph.py  # 新增 research_type_router 节点 + 条件边
  backend/app/service/deep_research_v2/agents/planner.py（或 graph.py 中的 _planner_node）
                                                 # 启动时读 YAML，注入 system prompt
```

---

## YAML Schema

每个研究类型配置文件结构：

```yaml
name: industry_analysis
description: 行业市场格局与竞争态势深度分析

# 注入 Planner system prompt 的追加内容
planner_prompt: |
  你正在执行【行业分析】研究任务。
  报告必须包含以下核心维度，不得遗漏：
  1. 市场规模与增速（需有具体数字和来源）
  2. 竞争格局（主要玩家、市场份额）
  3. 波特五力分析
  4. 行业发展趋势与驱动因素
  搜索时优先使用权威机构报告（艾瑞、麦肯锡、行业协会等）。

# 大纲模板：Planner 生成 outline 时的参考结构
# {topic} 由 Planner LLM 替换为具体研究对象
outline_template:
  - title: 市场规模与增速
    search_query_hints:
      - "{topic} 市场规模 {year}"
      - "{topic} 行业增速 CAGR"
  - title: 竞争格局
    search_query_hints:
      - "{topic} 主要企业 市场份额"
      - "{topic} 行业 CR4 CR8"
  - title: 波特五力分析
    search_query_hints:
      - "{topic} 行业壁垒"
      - "{topic} 供应链 议价能力"
  - title: 发展趋势与驱动因素
    search_query_hints:
      - "{topic} 行业趋势 {year}"
      - "{topic} 政策利好 新技术"
```

三种初始类型的差异：

| 字段 | industry_analysis | company_research | comparative_analysis |
|---|---|---|---|
| 核心维度 | 市场规模/竞争格局/波特五力/趋势 | 商业模式/财务/管理层/风险 | 多主体并排/各维度评分 |
| 搜索词倾向 | 行业报告/权威机构 | 财报/招股书/公告 | 多目标同时对比 |
| 报告格式要求 | 结构化分析报告 | 尽调式深度报告 | 表格对比 + 综合结论 |

---

## ResearchTypeService 设计

```python
# backend/app/service/research_type_service.py

RESEARCH_TYPE_TOOLS = [
    {
        "name": "industry_analysis",
        "description": (
            "对某个行业/赛道进行深度分析，包括市场规模、竞争格局、"
            "波特五力、发展趋势等。适用于：'分析新能源汽车行业'、"
            "'XX赛道市场现状'等。"
        )
    },
    {
        "name": "company_research",
        "description": (
            "对单一公司进行深度调研，包括商业模式、财务状况、"
            "管理层、竞争优势与风险。适用于：'分析比亚迪'、"
            "'XX公司尽调报告'等。"
        )
    },
    {
        "name": "comparative_analysis",
        "description": (
            "对多个公司或产品进行横向对比分析，输出结构化对比表格"
            "与综合结论。适用于：'比较比亚迪和宁德时代'、"
            "'XX vs YY 竞争优劣势'等。"
        )
    },
]

@dataclass
class ResearchTypeResult:
    research_type: str   # "industry_analysis" | "company_research" | "comparative_analysis"
    confidence: float

class ResearchTypeService:
    async def classify(self, query: str) -> ResearchTypeResult: ...
    # 失败时 fallback → "industry_analysis"，confidence=0.0
```

---

## research_type_router 节点

```python
async def _research_type_router_node(self, state: ResearchState) -> Dict[str, Any]:
    """Level 2 研究类型识别节点：仅在 deep_research 路径触发。"""
    self._maybe_cancel(state)

    result = await self.research_type_service.classify(state["query"])

    # 推 SSE 事件
    writer({"type": "research_type_detected",
            "research_type": result.research_type,
            "confidence": result.confidence})

    return {"research_type": result.research_type}
```

图结构改动（`_build_langgraph`）：

```python
# 在 intent_router → planner 的边之间插入 research_type_router
# intent_router 条件边改为：deep_research → research_type_router
# research_type_router → planner（无条件边，类型已写入 state）

workflow.add_conditional_edges(
    "intent_router",
    route_after_intent,
    {
        "web_search":    "web_search",
        "simple_qa":     "simple_qa",
        "out_of_scope":  "out_of_scope",
        "planner":       "research_type_router",  # deep_research → 先过 Level 2
    },
)
workflow.add_edge("research_type_router", "planner")
```

---

## Planner 改动

Planner 节点在构建 system prompt 时，读取 `state["research_type"]`，加载对应 YAML：

```python
def _load_research_skill(research_type: str) -> dict:
    """加载 research_skills/{research_type}.yaml，不存在时返回空配置。"""
    skill_path = Path(__file__).parent.parent.parent / "research_skills" / f"{research_type}.yaml"
    if skill_path.exists():
        return yaml.safe_load(skill_path.read_text(encoding="utf-8"))
    return {}

# 在 _planner_node 中：
skill = _load_research_skill(state.get("research_type", ""))
skill_prompt = skill.get("planner_prompt", "")
outline_hint = yaml.dump(skill.get("outline_template", []), allow_unicode=True)

system_prompt = BASE_PLANNER_PROMPT + "\n\n" + skill_prompt
user_prompt = f"用户问题：{query}\n\n参考大纲结构：\n{outline_hint}\n\n请生成完整研究计划..."
```

Planner LLM 仍然自由生成，YAML 只是引导，不强制替换 outline。

---

## SSE 新增事件

| 事件类型 | 字段 | 说明 |
|---|---|---|
| `research_type_detected` | `research_type`, `confidence` | Level 2 分类完成 |

---

## 错误处理

| 场景 | 处理方式 |
|---|---|
| ResearchTypeService 调用失败 | fallback `industry_analysis`，confidence=0.0 |
| YAML 文件不存在 | 返回空配置，Planner 使用默认 prompt |
| YAML 格式错误 | 捕获异常，返回空配置，记录 warning |

---

## 不在本期范围

- Planner 以外的 Agent（Scout、Writer、Critic）按研究类型定制化
- YAML 文件热重载（无需重启服务）
- 研究类型配置的 API 管理界面
- 超过三种初始研究类型
