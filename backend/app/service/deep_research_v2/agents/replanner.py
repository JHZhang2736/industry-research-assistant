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
            {"plan": [PlanStep dict, ...], "replan_count": int}
        """
        replan_count = state.get("replan_count", 0) + 1
        new_steps: List[Dict[str, Any]] = []

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

        self.add_message(
            state,
            "replan",
            f"🔄 Replan #{replan_count}：生成 {len(new_steps)} 个补救步骤",
        )

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
