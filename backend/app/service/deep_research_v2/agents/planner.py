"""DeepResearch v3 - Planner Agent

吸收 ChiefArchitect 的 outline 生成职责，并扩展输出完整 plan（含 parallel_group）。
"""

import logging
import uuid
from pathlib import Path
from typing import Dict, Any
import yaml

from .base import BaseAgent
from ..state import ResearchState
try:
    from service.memory_engine import get_memory_engine, classify_industry
except ImportError:
    from app.service.memory_engine import get_memory_engine, classify_industry

logger = logging.getLogger("deep_research_v3.planner")


def _recall_memory(engine, user_id: str, query: str) -> Dict[str, str]:
    """召回结构化长期记忆：{"preferences": str, "lessons": str}。best-effort。

    返回结构化 dict（而非拼好的字符串），便于写入 state 供 checkpoint 持久化与
    LangSmith 观测；prompt 前缀由 _format_memory_prefix 单独组装。
    """
    if engine is None or not user_id:
        return {"preferences": "", "lessons": ""}
    try:
        return {
            "preferences": engine.recall_preferences(user_id, query) or "",
            "lessons": engine.recall_lessons(classify_industry(query), query) or "",
        }
    except Exception:
        return {"preferences": "", "lessons": ""}


def _format_memory_prefix(recalled: Dict[str, str]) -> str:
    """把结构化记忆拼成注入 prompt 的前缀。"""
    blocks = [b for b in (recalled.get("preferences", ""), recalled.get("lessons", "")) if b]
    return ("\n".join(blocks) + "\n") if blocks else ""


def _build_memory_prefix(engine, user_id: str, query: str) -> str:
    """组装注入 Planner 的记忆前缀：用户偏好 + 本行业历史教训。best-effort。"""
    return _format_memory_prefix(_recall_memory(engine, user_id, query))


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


def _format_scoping_summary(scoping_summary: dict) -> str:
    if not scoping_summary:
        return ""
    lines = [
        "Initial scoping result (planning context only; not verified report evidence):"
    ]
    key_subdomains = scoping_summary.get("key_subdomains") or []
    hot_terms = scoping_summary.get("hot_terms") or []
    source_notes = scoping_summary.get("source_notes") or []
    initial_sources = scoping_summary.get("initial_sources") or []
    warning = scoping_summary.get("warning") or ""
    if key_subdomains:
        lines.append("Key subdomains: " + ", ".join(map(str, key_subdomains[:8])))
    if hot_terms:
        lines.append("Hot terms: " + ", ".join(map(str, hot_terms[:12])))
    if source_notes:
        lines.append("Source notes: " + "; ".join(map(str, source_notes[:6])))
    if initial_sources:
        lines.append("Initial sources:")
        for source in initial_sources[:8]:
            title = source.get("title", "")
            site = source.get("site_name", "")
            url = source.get("url", "")
            lines.append(f"- {title} ({site}) {url}")
    if warning:
        lines.append(f"Scoping warning: {warning}")
    lines.append("Generate the outline based on this scoping map and the user's query.")
    return "\n".join(lines)


PLANNER_PROMPT = """你是一位行业研究的总规划师。给定一个研究问题，你需要：

1. 生成 6 章节的研究 outline（每个章节标注类型：qualitative/quantitative/mixed）
2. 生成完整的执行 plan：把 outline 转化为可执行的 step 序列

## 可用 tool

- `search_section`: 对单个章节执行搜索（按 section_id + queries 调用，可并行）
- `analyze_facts`: 从所有 facts 提取 data_points + insights（串行，依赖所有 search 完成）
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
      "step_id": "step_search_sec_1",
      "tool": "search_section",
      "args": { "section_id": "sec_1", "queries": ["关键词1", "关键词2"] },
      "depends_on": [],
      "parallel_group": "search_batch"
    },
    {
      "step_id": "step_search_sec_2",
      "tool": "search_section",
      "args": { "section_id": "sec_2", "queries": ["..."] },
      "depends_on": [],
      "parallel_group": "search_batch"
    },
    {
      "step_id": "step_analyze",
      "tool": "analyze_facts",
      "args": {},
      "depends_on": ["step_search_sec_1", "step_search_sec_2", "...所有 search step_id..."],
      "parallel_group": null
    },
    {
      "step_id": "step_charts",
      "tool": "generate_charts",
      "args": {},
      "depends_on": ["step_analyze"],
      "parallel_group": null
    },
    {
      "step_id": "step_write_sec_1",
      "tool": "write_section",
      "args": { "section_id": "sec_1" },
      "depends_on": ["step_analyze", "step_charts"],
      "parallel_group": "write_batch"
    }
  ]
}
```

## 依赖与并行规则（必须严格遵守）

- `search_section`：`depends_on=[]`，`parallel_group="search_batch"`（所有章节并行搜）
- `analyze_facts`：`depends_on=[所有 search_section 的 step_id]`，`parallel_group=null`（串行）
- `generate_charts`：`depends_on=[analyze_facts 的 step_id]`，`parallel_group=null`（串行）
- `write_section`：`depends_on=[analyze_facts 的 step_id, generate_charts 的 step_id]`，`parallel_group="write_batch"`（章节间并行写）

> 错的 depends_on 会让数据分析拿不到搜索结果，直接产空报告。务必按上述规则填。

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
            scoping_hint = _format_scoping_summary(state.get("scoping_summary", {}))
            if scoping_hint:
                user_prompt += f"\n\n{scoping_hint}"

            # 召回长期记忆（偏好 + 历史教训）：一次召回，写入 state 供 checkpoint/LangSmith，
            # 同时拼成前缀注入 prompt
            recalled_memory = _recall_memory(
                get_memory_engine(), state.get("user_id", ""), query
            )
            mem_prefix = _format_memory_prefix(recalled_memory)
            if mem_prefix:
                user_prompt = f"{mem_prefix}\n{user_prompt}"

            response = await self.call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
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

            # LLM 经常瞎填 depends_on / parallel_group（especially for analyze/charts/write），
            # 这里按 tool 类型确定性地重写拓扑，保证 executor 能按正确顺序调度。
            plan = self._enforce_plan_topology(plan)

            self.add_message(state, "plan_ready", f"📋 生成 {len(outline)} 章节 / {len(plan)} 个执行步骤")
            return {"outline": outline, "plan": plan, "recalled_memory": recalled_memory}

        except Exception as e:
            logger.warning(f"Planner LLM failed, using fallback template: {e}")
            self.add_message(state, "warning", f"⚠️ Planner LLM 失败，使用本地模板：{e}")
            return self._fallback_template(query)

    def _enforce_plan_topology(self, plan: list) -> list:
        """按 tool 类型重写 depends_on / parallel_group（不动 args/step_id）。

        规则：
        - search_section: deps=[], group="search_batch"
        - analyze_facts: deps=[所有 search step_id], group=None
        - generate_charts: deps=[analyze step_id], group=None
        - write_section: deps=[analyze step_id, charts step_id], group="write_batch"

        未知 tool 保持原样。
        """
        search_ids = [s["step_id"] for s in plan if s.get("tool") == "search_section"]
        analyze_ids = [s["step_id"] for s in plan if s.get("tool") == "analyze_facts"]
        charts_ids = [s["step_id"] for s in plan if s.get("tool") == "generate_charts"]

        for step in plan:
            tool = step.get("tool")
            if tool == "search_section":
                step["depends_on"] = []
                step["parallel_group"] = "search_batch"
            elif tool == "analyze_facts":
                step["depends_on"] = list(search_ids)
                step["parallel_group"] = None
            elif tool == "generate_charts":
                step["depends_on"] = list(analyze_ids)
                step["parallel_group"] = None
            elif tool == "write_section":
                step["depends_on"] = list(analyze_ids) + list(charts_ids)
                step["parallel_group"] = "write_batch"
        return plan

    def refresh_plan_queries(
        self,
        query: str,
        outline: list,
        plan: list,
    ) -> list:
        sections_by_id = {
            section.get("id"): section
            for section in outline
            if section.get("id")
        }
        refreshed = []
        for step in plan:
            new_step = dict(step)
            new_step["args"] = dict(step.get("args", {}) or {})
            if step.get("tool") == "search_section":
                section_id = new_step["args"].get("section_id")
                section = sections_by_id.get(section_id)
                if section:
                    title = str(section.get("title", "")).strip()
                    description = str(section.get("description", "")).strip()
                    queries = [str(query).strip()]
                    if title:
                        queries.append(title)
                    if title and description:
                        queries.append(f"{title} {description}"[:160])
                    deduped = []
                    for item in queries:
                        if item and item not in deduped:
                            deduped.append(item)
                    new_step["args"]["queries"] = deduped
            refreshed.append(new_step)
        return self._enforce_plan_topology(refreshed)

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
