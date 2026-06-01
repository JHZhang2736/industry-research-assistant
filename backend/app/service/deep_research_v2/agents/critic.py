

"""
DeepResearch V2.0 - 毒舌评论家 Agent (CriticMaster)

职责：
1. 对抗式质检 - 永远不满意，找出问题
2. 逻辑漏洞检测 - 检查推理链条
3. 幻觉查杀 - 识别无来源或错误的信息
4. 偏见识别 - 发现观点偏颇
"""

import hashlib
import uuid
from typing import Dict, Any, List
from datetime import datetime

from .base import BaseAgent
from ..state import ResearchState, ResearchPhase


class CriticMaster(BaseAgent):
    """
    毒舌评论家 - 质量守门人

    特点：
    - 对抗式思维：假设一切都有问题
    - 严格的证据要求
    - 逻辑一致性检查
    - 有权打回重写
    """

    REVIEW_PROMPT = """你是一位极其严苛的学术审稿人和事实核查专家。你的任务是找出研究报告中的所有问题。

## 审核原则（必须严格执行）
1. **零容忍幻觉**：任何没有明确来源的数据或事实，都是问题
2. **逻辑闭环**：论点必须有论据支撑，论据必须有来源
3. **偏见警惕**：单方面观点、情绪化表达都是问题
4. **时效性**：过时的数据（超过2年）必须标注
5. **完整性**：是否遗漏重要方面

## 研究问题
{query}

## 研究大纲
{outline}

## 待审核内容

### 章节草稿
{draft_content}

### 引用的事实
{facts}

### 使用的数据点
{data_points}

## 历史 Critic 问题
以下是上一轮或历史 Critic 反馈。你必须用这些 id 判断问题是否已经解决，仍然存在时用 same_as_issue_id 关联旧 id，已经解决时放入 resolved_issue_ids。
{previous_feedback}

## 任务
逐条审核上述内容，找出所有问题。你必须扮演一个"找茬专家"的角色。

## 输出格式

请严格按以下 JSON schema 输出（扁平结构，配合 Replanner 使用）：

```json
{{
    "quality_score": 1-10 的浮点数,
    "dimension_scores": {{
        "factual_support": 1-10,      // 权重 0.30：事实和证据支撑是否充分
        "citation_integrity": 1-10,   // 权重 0.20：引用是否存在、可用并支撑相邻论断
        "coverage": 1-10,             // 权重 0.15：是否覆盖大纲和用户问题
        "reasoning": 1-10,            // 权重 0.15：论证链是否清晰、一致
        "freshness": 1-10,            // 权重 0.10：时效性要求是否满足
        "actionability": 1-10         // 权重 0.10：反馈是否具体可执行
    }},
    "verdict": "pass" | "needs_revision" | "needs_re_research",
    "summary": "整体评估摘要",
    "resolved_issue_ids": ["本轮确认已经解决的历史 issue id"],
    "critic_feedback": [
        {{
            "id": "issue_xxx",
            "same_as_issue_id": "如果这是历史未解决问题的延续，填写旧 issue id；否则省略",
            "target_section": "章节ID或'全局'",
            "issue_type": "missing_source/logic_error/bias/hallucination/outdated/incomplete",
            "severity": "critical/major/minor",
            "description": "问题详细描述",
            "suggestion": "具体的修改建议",
            "acceptance_criteria": ["critical/major 问题必须给出可验证的验收标准"]
        }}
    ],
    "unresolved_issues": 严重/重大问题计数（整数）,
    "missing_aspects": ["报告中遗漏的重要方面"],
    "suggested_actions": [
        "retry_search:sec_X"  // 缺信息，需要补充搜索（X 是 outline 中的 section_id）
        | "rewrite:sec_X"     // 文字/逻辑问题，需要改写
        | "add_data:sec_X"    // 缺数据点
    ]
}}
```

## 严重程度说明
- critical: 必须修复，否则报告不可用（如：核心数据错误、严重幻觉）
- major: 强烈建议修复，影响报告质量（如：缺少来源、逻辑漏洞）
- minor: 建议修复，提升报告质量（如：表述不够精确）

## 评分标准（1-10分制）
- 9-10分：优秀，几乎无问题，可直接发布
- 7-8分：良好，有小问题但不影响整体质量，审核通过（verdict=pass）
- 5-6分：一般，有明显问题需要修订
- 3-4分：较差，问题较多，需要大幅修改
- 1-2分：很差，存在严重问题或大量错误

注意：quality_score >= 7 时才能设置 verdict 为 "pass"

⚠️ 关键约束：当 verdict 不是 "pass" 时（即 quality_score < 7），
`suggested_actions` **必须非空**，并且对每个出现 critical/major 问题的章节，
至少给一条对应的 action（retry_search/rewrite/add_data）。
**绝对不允许出现"verdict=needs_revision 但 suggested_actions=[]"** 这种自相矛盾的输出。
否则你的输出会被判为失败。

开始你的审核："""

    FINAL_CHECK_PROMPT = """你是最终质量把关人。这是修订后的研究报告。

## 原始问题
{query}

## 之前的问题
{previous_issues}

## 修订后的内容
{revised_content}

## 任务
检查之前的问题是否已解决，是否有新问题产生。

输出JSON：
```json
{{
    "resolved_issues": ["已解决的问题ID列表"],
    "unresolved_issues": ["未解决的问题ID列表"],
    "new_issues": [{{
        "description": "新发现的问题",
        "severity": "critical/major/minor"
    }}],
    "final_verdict": "approved/needs_more_work",
    "final_score": 1-10,
    "publication_readiness": "ready/almost_ready/not_ready",
    "final_comments": "最终评语"
}}
```"""

    def __init__(self, llm_api_key: str, llm_base_url: str, model: str = "qwen-max"):
        super().__init__(
            name="CriticMaster",
            role="毒舌评论家",
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            model=model
        )

    DIMENSION_WEIGHTS = {
        "factual_support": 0.30,
        "citation_integrity": 0.20,
        "coverage": 0.15,
        "reasoning": 0.15,
        "freshness": 0.10,
        "actionability": 0.10,
    }

    def _hash_text(self, text: str) -> str:
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _build_input_snapshot(self, state: ResearchState) -> Dict[str, Any]:
        draft_sections = state.get("draft_sections", {}) or {}
        return {
            "final_report_hash": self._hash_text(state.get("final_report", "")),
            "draft_hash_by_section": {
                section_id: self._hash_text(content)
                for section_id, content in draft_sections.items()
            },
            "facts_count": len(state.get("facts", []) or []),
            "data_points_count": len(state.get("data_points", []) or []),
            "references_count": len(state.get("references", []) or []),
        }

    def _build_delta_from_previous(
        self,
        state: ResearchState,
        current_snapshot: Dict[str, Any],
        quality_score: float,
    ) -> Dict[str, Any]:
        history = state.get("review_history", []) or []
        if not history:
            return {
                "final_report_changed": None,
                "changed_sections": [],
                "new_facts_count": 0,
                "new_references_count": 0,
                "score_delta": None,
            }
        previous = history[-1]
        previous_snapshot = previous.get("input_snapshot", {}) or {}
        previous_hashes = previous_snapshot.get("draft_hash_by_section", {}) or {}
        current_hashes = current_snapshot.get("draft_hash_by_section", {}) or {}
        changed_sections = sorted(
            section_id
            for section_id, current_hash in current_hashes.items()
            if previous_hashes.get(section_id) != current_hash
        )
        return {
            "final_report_changed": (
                previous_snapshot.get("final_report_hash")
                != current_snapshot.get("final_report_hash")
            ),
            "changed_sections": changed_sections,
            "new_facts_count": max(
                0,
                int(current_snapshot.get("facts_count", 0))
                - int(previous_snapshot.get("facts_count", 0)),
            ),
            "new_references_count": max(
                0,
                int(current_snapshot.get("references_count", 0))
                - int(previous_snapshot.get("references_count", 0)),
            ),
            "score_delta": round(
                quality_score - float(previous.get("quality_score", 0.0) or 0.0),
                3,
            ),
        }

    def _coerce_dimension_scores(self, value: Any) -> Dict[str, float]:
        if not isinstance(value, dict):
            return {}
        scores: Dict[str, float] = {}
        for key in self.DIMENSION_WEIGHTS:
            if key not in value:
                return {}
            try:
                scores[key] = max(0.0, min(10.0, float(value[key])))
            except (TypeError, ValueError):
                return {}
        return scores

    def _quality_from_dimensions(
        self,
        dimension_scores: Dict[str, float],
        fallback: Any,
    ) -> float:
        if dimension_scores:
            total = sum(
                dimension_scores[key] * weight
                for key, weight in self.DIMENSION_WEIGHTS.items()
            )
            return round(total, 2)
        try:
            return float(fallback)
        except (TypeError, ValueError):
            return 0.0

    def _normalize_feedback(
        self,
        state: ResearchState,
        parsed: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        resolved_ids = set(parsed.get("resolved_issue_ids", []) or [])
        previous_by_id = {
            item.get("id"): dict(item)
            for item in state.get("critic_feedback", []) or []
            if isinstance(item, dict) and item.get("id")
        }

        merged: List[Dict[str, Any]] = []
        for issue_id, previous in previous_by_id.items():
            if issue_id in resolved_ids or previous.get("resolved") is True:
                previous["resolved"] = True
                merged.append(previous)

        for fb in parsed.get("critic_feedback", []) or []:
            if not isinstance(fb, dict):
                continue
            same_as = fb.get("same_as_issue_id")
            if same_as and same_as in previous_by_id:
                fb["id"] = same_as
            if "id" not in fb or not fb.get("id"):
                fb["id"] = f"issue_{uuid.uuid4().hex[:8]}"
            fb.setdefault("resolved", False)
            if fb["id"] in resolved_ids:
                fb["resolved"] = True
            merged.append(fb)

        seen = set()
        unique: List[Dict[str, Any]] = []
        for fb in merged:
            issue_id = fb.get("id")
            key = issue_id or uuid.uuid4().hex
            if key in seen:
                unique = [item for item in unique if item.get("id") != key]
            seen.add(key)
            unique.append(fb)
        return unique

    async def process(self, state: ResearchState) -> Dict[str, Any]:
        """v3 节点形态：返回扁平 dict，不直接修改 state

        Returns:
            {
                "quality_score": float,
                "verdict": "pass" | "needs_revision" | "needs_re_research",
                "critic_feedback": list[dict],
                "unresolved_issues": int,
                "suggested_actions": list[str],   # 给 Replanner 消费
                "missing_aspects": list[str],
                "summary": str,
            }
        """
        self.add_message(state, "thought", {
            "agent": self.name,
            "content": "开始严格审核研究报告，准备找出所有问题...",
        })

        parsed = await self._review_content(state) or {}

        dimension_scores = self._coerce_dimension_scores(parsed.get("dimension_scores"))
        quality_score = self._quality_from_dimensions(
            dimension_scores,
            parsed.get("quality_score", 0.0),
        )
        feedback = self._normalize_feedback(state, parsed)
        unresolved_count = parsed.get(
            "unresolved_issues",
            len([
                i for i in feedback
                if not i.get("resolved")
                and i.get("severity") in ("critical", "major")
            ]),
        )
        review_id = parsed.get("review_id") or f"review_{uuid.uuid4().hex[:8]}"
        snapshot = self._build_input_snapshot(state)
        delta = self._build_delta_from_previous(state, snapshot, quality_score)
        history_entry = {
            "review_id": review_id,
            "round": len(state.get("review_history", []) or []),
            "quality_score": quality_score,
            "verdict": parsed.get("verdict", "needs_revision"),
            "dimension_scores": dimension_scores,
            "issue_ids": [fb.get("id") for fb in feedback if not fb.get("resolved")],
            "suggested_actions": parsed.get("suggested_actions", []),
            "input_snapshot": snapshot,
            "delta_from_previous": delta,
            "summary": parsed.get("summary", ""),
        }

        result = {
            "review_id": review_id,
            "quality_score": quality_score,
            "dimension_scores": dimension_scores,
            "verdict": parsed.get("verdict", "needs_revision"),
            "critic_feedback": feedback,
            "unresolved_issues": unresolved_count,
            "suggested_actions": parsed.get("suggested_actions", []),
            "missing_aspects": parsed.get("missing_aspects", []),
            "summary": parsed.get("summary", ""),
            "review_history": list(state.get("review_history", []) or []) + [history_entry],
        }

        self.add_message(state, "review", {
            "agent": self.name,
            "verdict": result["verdict"],
            "quality_score": result["quality_score"],
            "issues_count": len(result["critic_feedback"]),
            "suggested_actions": result["suggested_actions"],
            "summary": result["summary"],
        })

        return result

    def _analyze_issues_for_routing(self, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析问题类型，决定路由方向

        Returns:
            {
                "should_research": bool,  # 是否需要重新搜索
                "search_queries": List[str]  # 建议的搜索查询
            }
        """
        issues = review_result.get("issues", [])
        missing_aspects = review_result.get("missing_aspects", [])

        # 需要补充搜索的问题类型
        research_needed_types = {"missing_source", "incomplete", "outdated"}

        search_queries = []
        research_issues_count = 0

        for issue in issues:
            issue_type = issue.get("issue_type", "")
            severity = issue.get("severity", "minor")

            # 检查是否是需要搜索的问题类型
            if issue_type in research_needed_types and severity in ["critical", "major"]:
                research_issues_count += 1

                # 收集搜索建议
                if issue.get("requires_new_search") and issue.get("search_query"):
                    search_queries.append(issue["search_query"])

        # 添加遗漏方面的搜索查询
        for aspect in missing_aspects[:3]:
            search_queries.append(aspect)

        # 决策：如果有超过30%的严重问题需要搜索，或者有明确的搜索建议，则回到搜索阶段
        total_critical_major = len([i for i in issues if i.get("severity") in ["critical", "major"]])
        should_research = (
            len(search_queries) > 0 and
            (research_issues_count > 0 or len(missing_aspects) > 0) and
            (total_critical_major == 0 or research_issues_count / max(total_critical_major, 1) > 0.3)
        )

        return {
            "should_research": should_research,
            "search_queries": list(set(search_queries))[:5]  # 去重，最多5个查询
        }

    async def _review_content(self, state: ResearchState) -> Dict[str, Any]:
        """审核内容"""
        self.logger.info(f"[CriticMaster] _review_content 开始")

        # 准备草稿内容
        draft_content = ""
        for section_id, content in state["draft_sections"].items():
            section = next((s for s in state["outline"] if s.get("id") == section_id), {})
            draft_content += f"\n## {section.get('title', section_id)}\n{content}\n"

        if not draft_content:
            draft_content = state.get("final_report", "（暂无内容）")

        self.logger.info(f"[CriticMaster] 待审核内容长度: {len(draft_content)}")

        # 准备事实列表
        facts_summary = []
        for fact in state["facts"][:20]:
            facts_summary.append(f"- [{fact.get('id')}] {fact.get('content', '')[:150]} (来源: {fact.get('source_name')}, 可信度: {fact.get('credibility_score')})")

        # 准备数据点列表
        data_summary = []
        for dp in state["data_points"][:15]:
            data_summary.append(f"- {dp.get('name')}: {dp.get('value')} {dp.get('unit', '')} (来源: {dp.get('source')})")

        # 格式化大纲
        outline_summary = []
        for section in state["outline"]:
            outline_summary.append(f"- {section.get('id')}: {section.get('title')} ({section.get('status', 'pending')})")

        previous_feedback = []
        for issue in state.get("critic_feedback", []) or []:
            if not isinstance(issue, dict):
                continue
            criteria = issue.get("acceptance_criteria", []) or []
            criteria_text = "; ".join(str(item) for item in criteria) if criteria else "none"
            previous_feedback.append(
                f"- id={issue.get('id')}; "
                f"target_section={issue.get('target_section')}; "
                f"severity={issue.get('severity')}; "
                f"resolved={issue.get('resolved', False)}; "
                f"description={issue.get('description', '')}; "
                f"acceptance_criteria={criteria_text}"
            )

        prompt = self.REVIEW_PROMPT.format(
            query=state["query"],
            outline="\n".join(outline_summary),
            draft_content=draft_content[:8000],  # 限制长度
            facts="\n".join(facts_summary) if facts_summary else "（暂无事实记录）",
            data_points="\n".join(data_summary) if data_summary else "（暂无数据点）",
            previous_feedback="\n".join(previous_feedback) if previous_feedback else "none",
        )

        self.logger.info(f"[CriticMaster] 调用 LLM 进行审核...")
        response = await self.call_llm(
            system_prompt="你是一位极其严苛的质量审核专家，专门找出研究报告中的问题。你永远不会轻易满意。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2,
            max_tokens=16000,  # 拉满到最大值
            state=state,
            action="review_content",
        )
        self.logger.info(f"[CriticMaster] LLM 响应长度: {len(response)}")

        result = self.parse_json_response(response)
        self.logger.info(f"[CriticMaster] JSON 解析结果: {bool(result)}, verdict: {result.get('overall_assessment', {}).get('verdict') if result else 'N/A'}")
        return result

    async def final_check(self, state: ResearchState) -> Dict[str, Any]:
        """最终检查"""
        # 收集之前的问题
        previous_issues = []
        for issue in state["critic_feedback"]:
            if not issue.get("resolved"):
                previous_issues.append(f"- [{issue.get('severity')}] {issue.get('description')}")

        prompt = self.FINAL_CHECK_PROMPT.format(
            query=state["query"],
            previous_issues="\n".join(previous_issues) if previous_issues else "无之前的问题",
            revised_content=state.get("final_report", "")[:8000]
        )

        response = await self.call_llm(
            system_prompt="你是最终质量把关人。",
            user_prompt=prompt,
            json_mode=True,
            state=state,
            action="final_check",
        )

        return self.parse_json_response(response)
