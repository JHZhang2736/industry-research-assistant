"""DeepResearch v3 - Replanner Agent.

Translates critic suggested_actions and structured feedback into deterministic
repair plan steps. This agent is rule-driven and does not call an LLM.
"""

import hashlib
import logging
import uuid
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..state import ResearchState

logger = logging.getLogger("deep_research_v3.replanner")


class Replanner(BaseAgent):
    """Rule-driven replanner for section repair actions."""

    SUPPORTED_ACTIONS = {"retry_search", "rewrite", "add_data"}
    ACTION_PRECEDENCE = {"rewrite": 1, "retry_search": 2, "add_data": 3}

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = "deepseek-v3.2"):
        super().__init__(
            name="Replanner",
            role="补救规划师",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model,
        )

    def _hash_text(self, text: str) -> str:
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _latest_review_id(self, state: ResearchState) -> str:
        history = state.get("review_history", []) or []
        if not history:
            return ""
        return str(history[-1].get("review_id", ""))

    def _targetable_feedback_by_section(
        self,
        state: ResearchState,
    ) -> Dict[str, List[Dict[str, Any]]]:
        outline = state.get("outline", []) or []
        valid_section_ids = {s.get("id") for s in outline if s.get("id")}
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for fb in state.get("critic_feedback", []) or []:
            if not isinstance(fb, dict) or fb.get("resolved"):
                continue
            target = fb.get("target_section")
            if target in valid_section_ids:
                grouped.setdefault(target, []).append(fb)
        return grouped

    def _build_revision_contexts(
        self,
        state: ResearchState,
    ) -> Dict[str, Dict[str, Any]]:
        contexts: Dict[str, Dict[str, Any]] = {}
        existing = state.get("revision_context_by_section", {}) or {}
        grouped = self._targetable_feedback_by_section(state)
        review_id = self._latest_review_id(state)
        draft_sections = state.get("draft_sections", {}) or {}
        for section_id, raw_issues in grouped.items():
            issues = [dict(issue) for issue in raw_issues]
            required_actions = []
            for issue in issues:
                issue_type = issue.get("issue_type", "")
                if issue_type in ("missing_source", "outdated", "incomplete"):
                    required_actions.extend(["retry_search", "rewrite"])
                elif issue_type in ("logic_error", "bias", "hallucination"):
                    required_actions.append("rewrite")
                else:
                    required_actions.append("rewrite")
            context = {}
            existing_context = existing.get(section_id)
            if isinstance(existing_context, dict):
                context.update(existing_context)
            context.update({
                "section_id": section_id,
                "mode": "rewrite_with_feedback",
                "source_review_id": review_id,
                "issues": issues,
                "required_actions": list(dict.fromkeys(required_actions)),
                "previous_content_hash": self._hash_text(draft_sections.get(section_id, "")),
            })
            contexts[section_id] = context
        return contexts

    def _derive_actions_from_feedback(self, state: ResearchState) -> List[str]:
        actions: List[str] = []
        grouped = self._targetable_feedback_by_section(state)
        for section_id, issues in grouped.items():
            actions.append(f"{self._required_action_for_issues(issues)}:{section_id}")
        return actions

    def _required_action_for_issues(self, issues: List[Dict[str, Any]]) -> str:
        required = "rewrite"
        for issue in issues:
            issue_type = issue.get("issue_type", "")
            if issue_type in ("missing_source", "outdated", "incomplete"):
                required = "retry_search"
            if issue_type == "missing_data":
                return "add_data"
        return required

    def _normalize_actions(
        self,
        suggested_actions: List[str],
        valid_section_ids: set,
        targetable_feedback: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        has_critic_feedback: bool = False,
    ) -> List[tuple]:
        targetable_feedback = targetable_feedback or {}
        chosen_by_section: Dict[str, str] = {}
        section_order: List[str] = []

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

            if has_critic_feedback and target not in targetable_feedback:
                logger.info(f"replanner: drop stale action '{action}' without unresolved feedback")
                continue

            if target in targetable_feedback:
                required = self._required_action_for_issues(targetable_feedback[target])
                if self.ACTION_PRECEDENCE[required] > self.ACTION_PRECEDENCE[verb]:
                    verb = required

            if target not in chosen_by_section:
                section_order.append(target)
                chosen_by_section[target] = verb
                continue

            existing = chosen_by_section[target]
            if self.ACTION_PRECEDENCE[verb] > self.ACTION_PRECEDENCE[existing]:
                chosen_by_section[target] = verb

        return [(chosen_by_section[section_id], section_id) for section_id in section_order]

    async def process(
        self,
        state: ResearchState,
        suggested_actions: List[str],
    ) -> Dict[str, Any]:
        """Generate repair plan steps from suggested actions or targetable feedback."""
        replan_count = state.get("replan_count", 0) + 1
        new_steps: List[Dict[str, Any]] = []
        revision_contexts = self._build_revision_contexts(state)
        targetable_feedback = self._targetable_feedback_by_section(state)
        has_critic_feedback = any(
            isinstance(fb, dict) for fb in state.get("critic_feedback", []) or []
        )
        if not suggested_actions:
            suggested_actions = self._derive_actions_from_feedback(state)

        outline = state.get("outline", [])
        valid_section_ids = {s["id"] for s in outline}

        normalized_actions = self._normalize_actions(
            suggested_actions,
            valid_section_ids,
            targetable_feedback=targetable_feedback,
            has_critic_feedback=has_critic_feedback,
        )
        for verb, target in normalized_actions:
            new_steps.extend(self._action_to_steps(verb, target, state))

        self.add_message(
            state,
            "replan",
            f"🔄 Replan #{replan_count}：生成 {len(new_steps)} 个补救步骤",
        )

        return {
            "plan": new_steps,
            "replan_count": replan_count,
            "revision_context_by_section": revision_contexts,
        }

    def _action_to_steps(
        self,
        verb: str,
        section_id: str,
        state: ResearchState,
    ) -> List[Dict[str, Any]]:
        """Single action to one or more PlanStep dicts."""
        outline = state.get("outline", [])
        section_title = next(
            (s["title"] for s in outline if s["id"] == section_id),
            section_id,
        )
        query = state.get("query", "")

        if verb == "retry_search":
            search_id = f"replan_search_{section_id}_{uuid.uuid4().hex[:6]}"
            return [
                {
                    "step_id": search_id,
                    "tool": "search_section",
                    "args": {"section_id": section_id, "queries": [f"{query} {section_title}"]},
                    "depends_on": [],
                    "parallel_group": None,
                },
                {
                    "step_id": f"replan_write_{section_id}_{uuid.uuid4().hex[:6]}",
                    "tool": "write_section",
                    "args": {"section_id": section_id},
                    "depends_on": [search_id],
                    "parallel_group": None,
                },
            ]

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
            analyze_id = f"replan_analyze_{section_id}_{uuid.uuid4().hex[:6]}"
            return [
                {
                    "step_id": search_id,
                    "tool": "search_section",
                    "args": {"section_id": section_id, "queries": [f"{query} {section_title} 数据 统计"]},
                    "depends_on": [],
                    "parallel_group": None,
                },
                {
                    "step_id": analyze_id,
                    "tool": "analyze_facts",
                    "args": {},
                    "depends_on": [search_id],
                    "parallel_group": None,
                },
                {
                    "step_id": f"replan_write_{section_id}_{uuid.uuid4().hex[:6]}",
                    "tool": "write_section",
                    "args": {"section_id": section_id},
                    "depends_on": [analyze_id],
                    "parallel_group": None,
                },
            ]

        return []
