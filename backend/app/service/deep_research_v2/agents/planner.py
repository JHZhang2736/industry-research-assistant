"""DeepResearch v3 - Planner Agent

吸收 ChiefArchitect 的 outline 生成职责，并扩展输出完整 plan（含 parallel_group）。
"""

import logging
import uuid
from typing import Dict, Any

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
{
  "outline": [
    {
      "id": "sec_1",
      "title": "章节标题",
      "description": "章节说明",
      "section_type": "qualitative" | "quantitative" | "mixed",
      "status": "pending",
      "requires_data": true | false,
      "requires_chart": true | false
    }
  ],
  "plan": [
    {
      "step_id": "step_1",
      "tool": "search_section",
      "args": { "section_id": "sec_1", "queries": ["关键词1", "关键词2"] },
      "depends_on": [],
      "parallel_group": "search_batch"
    }
  ]
}
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
                system_prompt=PLANNER_PROMPT.replace("{query}", query),
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
        search_step_ids = []
        for sec in outline:
            step_id = f"step_search_{sec['id']}"
            plan.append({
                "step_id": step_id,
                "tool": "search_section",
                "args": {"section_id": sec["id"], "queries": [query, f"{query} {sec['title']}"]},
                "depends_on": [],
                "parallel_group": "search_batch",
            })
            search_step_ids.append(step_id)
        plan.append({
            "step_id": "step_analyze",
            "tool": "analyze_facts",
            "args": {},
            "depends_on": search_step_ids,
            "parallel_group": None,
        })
        plan.append({
            "step_id": "step_charts",
            "tool": "generate_charts",
            "args": {},
            "depends_on": ["step_analyze"],
            "parallel_group": None,
        })
        for sec in outline:
            plan.append({
                "step_id": f"step_write_{sec['id']}",
                "tool": "write_section",
                "args": {"section_id": sec["id"]},
                "depends_on": ["step_charts"],
                "parallel_group": "write_batch",
            })
        return {"outline": outline, "plan": plan}
