# Critic Revision Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build A+B from the critic revision spec: first make each critic loop auditable, then make replans produce issue-aware section revisions.

**Architecture:** Keep the existing v3 Plan-and-Execute graph. Add JSON-serializable review history and revision context fields to `ResearchState`; let Critic append structured score/delta history, Replanner create deterministic section repair contexts, Writer consume those contexts during `write_section`, and Executor/Graph record whether revision actually changed content.

**Tech Stack:** Python 3.11, FastAPI service code, LangGraph state diffs, pytest + pytest-asyncio, existing OpenAI-compatible LLM client mocks.

---

## File Structure

- Modify `backend/app/service/deep_research_v2/state.py`
  - Add `review_history`, `revision_context_by_section`, and `critic_diagnostics` to `ResearchState` and `create_initial_state()`.

- Modify `backend/app/service/deep_research_v2/agents/critic.py`
  - Add deterministic helper functions for hashing, snapshots, deltas, dimension score coercion, weighted score calculation, feedback normalization, and cross-round issue continuity.
  - Extend `CriticMaster.process()` to return `dimension_scores`, `review_id`, updated `review_history`, and merged `critic_feedback`.

- Modify `backend/app/service/deep_research_v2/agents/replanner.py`
  - Build `revision_context_by_section` from targetable feedback.
  - Generate `write_section` after `retry_search`/`add_data` actions so new evidence is used in the rewrite.

- Modify `backend/app/service/deep_research_v2/agents/writer.py`
  - Add a section revision prompt.
  - Route `write_one_section()` to a revision-specific path when `revision_context_by_section[section_id]` exists.
  - Return `changes_made`, `addressed_issue_ids`, and `unable_to_address`.

- Modify `backend/app/service/deep_research_v2/executor.py`
  - Merge `addressed_issue_ids`, `unable_to_address`, and per-section before/after hashes into `critic_diagnostics`.

- Modify `backend/app/service/deep_research_v2/graph.py`
  - Use a single configured quality threshold.
  - Stop ineffective loops when diagnostics prove no report/evidence change across repeated low-score reviews.
  - Include `critic_loop_status` in completion events.

- Modify `backend/app/config/llm_config.py`
  - Set `ResearchConfig.quality_threshold` default to `7.0` so config and Critic prompt agree.

- Modify tests:
  - `backend/test/test_deep_research_v3/test_state.py`
  - `backend/test/test_deep_research_v3/test_critic_node.py`
  - `backend/test/test_deep_research_v3/test_replanner.py`
  - `backend/test/test_deep_research_v3/test_executor.py`
  - `backend/test/test_deep_research_v3/test_graph_integration.py`
  - Create `backend/test/test_deep_research_v3/test_writer_revision.py`

---

### Task 1: State Fields For Review History

**Files:**
- Modify: `backend/app/service/deep_research_v2/state.py:192-207`
- Modify: `backend/app/service/deep_research_v2/state.py:225-261`
- Test: `backend/test/test_deep_research_v3/test_state.py`

- [ ] **Step 1: Write the failing state test**

Append this test to `backend/test/test_deep_research_v3/test_state.py`:

```python
def test_research_state_critic_loop_fields_default_empty():
    state = create_initial_state(query="q", session_id="s")
    assert state["review_history"] == []
    assert state["revision_context_by_section"] == {}
    assert state["critic_diagnostics"] == []
```

- [ ] **Step 2: Run the state test to verify it fails**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_state.py::test_research_state_critic_loop_fields_default_empty -q
```

Expected: FAIL with `KeyError: 'review_history'`.

- [ ] **Step 3: Add the state fields**

In `backend/app/service/deep_research_v2/state.py`, add these fields below `pending_search_queries`:

```python
    review_history: List[Dict[str, Any]]     # 每轮 Critic 的评分、快照与差异
    revision_context_by_section: Dict[str, Dict[str, Any]]  # section_id -> 定向修订上下文
    critic_diagnostics: List[Dict[str, Any]] # Critic/Replanner/Writer/Executor 诊断事件
```

In `create_initial_state()`, add these entries immediately after `pending_search_queries=[]`:

```python
        review_history=[],
        revision_context_by_section={},
        critic_diagnostics=[],
```

- [ ] **Step 4: Run the state tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_state.py -q
```

Expected: all tests in `test_state.py` pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/app/service/deep_research_v2/state.py backend/test/test_deep_research_v3/test_state.py
git commit -m "feat: add critic loop state fields"
```

---

### Task 2: Critic Diagnostics And Structured Score History

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/critic.py:1-305`
- Modify: `backend/test/test_deep_research_v3/test_critic_node.py`

- [ ] **Step 1: Add failing Critic tests**

Append these tests to `backend/test/test_deep_research_v3/test_critic_node.py`:

```python
@pytest.mark.asyncio
async def test_critic_dimension_scores_drive_weighted_quality(critic, monkeypatch):
    mock_response = json.dumps({
        "dimension_scores": {
            "factual_support": 4,
            "citation_integrity": 5,
            "coverage": 6,
            "reasoning": 7,
            "freshness": 8,
            "actionability": 9,
        },
        "quality_score": 1.0,
        "verdict": "needs_revision",
        "critic_feedback": [{
            "id": "issue_1",
            "target_section": "sec_1",
            "issue_type": "missing_source",
            "severity": "major",
            "description": "缺少来源",
            "suggestion": "补充引用",
            "acceptance_criteria": ["至少新增一个来源"],
        }],
        "unresolved_issues": 1,
        "suggested_actions": ["retry_search:sec_1"],
        "summary": "needs work",
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "原始内容"}

    result = await critic.process(state)

    assert result["quality_score"] == pytest.approx(6.05)
    assert result["dimension_scores"]["factual_support"] == 4.0
    assert result["review_history"][0]["quality_score"] == pytest.approx(6.05)
    assert result["review_history"][0]["input_snapshot"]["draft_hash_by_section"]["sec_1"].startswith("sha256:")


@pytest.mark.asyncio
async def test_critic_preserves_repeated_issue_id_with_same_as(critic, monkeypatch):
    mock_response = json.dumps({
        "quality_score": 4.5,
        "verdict": "needs_revision",
        "resolved_issue_ids": [],
        "critic_feedback": [{
            "same_as_issue_id": "issue_old",
            "target_section": "sec_1",
            "issue_type": "logic_error",
            "severity": "major",
            "description": "逻辑仍然跳跃",
            "suggestion": "补充推理链",
            "acceptance_criteria": ["解释因果关系"],
        }],
        "suggested_actions": ["rewrite:sec_1"],
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "内容"}
    state["critic_feedback"] = [{
        "id": "issue_old",
        "target_section": "sec_1",
        "issue_type": "logic_error",
        "severity": "major",
        "description": "逻辑跳跃",
        "suggestion": "补充推理",
        "resolved": False,
    }]

    result = await critic.process(state)

    assert result["critic_feedback"][0]["id"] == "issue_old"
    assert result["critic_feedback"][0]["resolved"] is False
```

- [ ] **Step 2: Run the Critic tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_critic_node.py::test_critic_dimension_scores_drive_weighted_quality test/test_deep_research_v3/test_critic_node.py::test_critic_preserves_repeated_issue_id_with_same_as -q
```

Expected: FAIL because `dimension_scores`, `review_history`, and `same_as_issue_id` support do not exist.

- [ ] **Step 3: Add Critic helper constants and functions**

In `backend/app/service/deep_research_v2/agents/critic.py`, add `hashlib` to imports:

```python
import hashlib
```

Add these constants and helper methods inside `CriticMaster`, above `process()`:

```python
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
            try:
                scores[key] = max(0.0, min(10.0, float(value.get(key, 0.0))))
            except (TypeError, ValueError):
                scores[key] = 0.0
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
            if issue_id in resolved_ids:
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
```

- [ ] **Step 4: Update `CriticMaster.process()`**

Replace the block from `parsed = await self._review_content(state) or {}` through the `result = {...}` assignment with:

```python
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
```

Remove the old loop that assigns feedback ids, because `_normalize_feedback()` now owns that responsibility.

- [ ] **Step 5: Run all Critic tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_critic_node.py -q
```

Expected: all tests in `test_critic_node.py` pass, including existing compatibility tests that do not provide `dimension_scores`.

- [ ] **Step 6: Commit Task 2**

```bash
git add backend/app/service/deep_research_v2/agents/critic.py backend/test/test_deep_research_v3/test_critic_node.py
git commit -m "feat: record critic review history"
```

---

### Task 3: Replanner Revision Context

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/replanner.py:38-129`
- Modify: `backend/test/test_deep_research_v3/test_replanner.py`

- [ ] **Step 1: Add failing Replanner tests**

Append these tests to `backend/test/test_deep_research_v3/test_replanner.py`:

```python
@pytest.mark.asyncio
async def test_replanner_builds_revision_context_for_missing_source(replanner):
    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_3", "title": "市场规模"}]
    state["draft_sections"] = {"sec_3": "原章节"}
    state["review_history"] = [{"review_id": "review_1"}]
    state["critic_feedback"] = [{
        "id": "issue_1",
        "target_section": "sec_3",
        "issue_type": "missing_source",
        "severity": "major",
        "description": "市场规模缺少来源",
        "suggestion": "补充来源",
        "acceptance_criteria": ["新增一个来源"],
        "resolved": False,
    }]

    result = await replanner.process(
        state=state,
        suggested_actions=["retry_search:sec_3"],
    )

    tools = [step["tool"] for step in result["plan"]]
    assert tools == ["search_section", "write_section"]
    assert result["plan"][1]["depends_on"] == [result["plan"][0]["step_id"]]
    context = result["revision_context_by_section"]["sec_3"]
    assert context["source_review_id"] == "review_1"
    assert context["issues"][0]["id"] == "issue_1"
    assert context["previous_content_hash"].startswith("sha256:")


@pytest.mark.asyncio
async def test_replanner_builds_context_when_actions_empty_but_feedback_targetable(replanner):
    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "逻辑"}]
    state["critic_feedback"] = [{
        "id": "issue_logic",
        "target_section": "sec_1",
        "issue_type": "logic_error",
        "severity": "major",
        "description": "逻辑跳跃",
        "suggestion": "补齐因果链",
        "acceptance_criteria": ["解释原因和结果"],
        "resolved": False,
    }]

    result = await replanner.process(state=state, suggested_actions=[])

    assert [step["tool"] for step in result["plan"]] == ["write_section"]
    assert "sec_1" in result["revision_context_by_section"]
```

- [ ] **Step 2: Run the Replanner tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_replanner.py::test_replanner_builds_revision_context_for_missing_source test/test_deep_research_v3/test_replanner.py::test_replanner_builds_context_when_actions_empty_but_feedback_targetable -q
```

Expected: FAIL because `revision_context_by_section` is not returned and `retry_search` does not add a dependent `write_section`.

- [ ] **Step 3: Add hash and feedback grouping helpers**

In `backend/app/service/deep_research_v2/agents/replanner.py`, add this import:

```python
import hashlib
```

Add these methods inside `Replanner`, above `process()`:

```python
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
        contexts.update(existing)
        grouped = self._targetable_feedback_by_section(state)
        review_id = self._latest_review_id(state)
        draft_sections = state.get("draft_sections", {}) or {}
        for section_id, issues in grouped.items():
            required_actions = []
            for issue in issues:
                issue_type = issue.get("issue_type", "")
                if issue_type in ("missing_source", "outdated", "incomplete"):
                    required_actions.extend(["retry_search", "rewrite"])
                elif issue_type in ("logic_error", "bias", "hallucination"):
                    required_actions.append("rewrite")
                else:
                    required_actions.append("rewrite")
            contexts[section_id] = {
                "section_id": section_id,
                "mode": "rewrite_with_feedback",
                "source_review_id": review_id,
                "issues": issues,
                "required_actions": list(dict.fromkeys(required_actions)),
                "previous_content_hash": self._hash_text(draft_sections.get(section_id, "")),
            }
        return contexts

    def _derive_actions_from_feedback(self, state: ResearchState) -> List[str]:
        actions: List[str] = []
        grouped = self._targetable_feedback_by_section(state)
        for section_id, issues in grouped.items():
            needs_search = any(
                issue.get("issue_type") in ("missing_source", "outdated", "incomplete")
                for issue in issues
            )
            if needs_search:
                actions.append(f"retry_search:{section_id}")
            else:
                actions.append(f"rewrite:{section_id}")
        return actions
```

- [ ] **Step 4: Update `process()` to return contexts and derive actions**

Replace this line:

```python
        new_steps: List[Dict[str, Any]] = []
```

with:

```python
        new_steps: List[Dict[str, Any]] = []
        revision_contexts = self._build_revision_contexts(state)
        if not suggested_actions:
            suggested_actions = self._derive_actions_from_feedback(state)
```

Replace the return dict with:

```python
        return {
            "plan": new_steps,
            "replan_count": replan_count,
            "revision_context_by_section": revision_contexts,
        }
```

- [ ] **Step 5: Make search/data actions flow into write actions**

Replace `_action_to_steps()` with:

```python
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
```

- [ ] **Step 6: Run Replanner tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_replanner.py -q
```

Expected: all tests pass. Existing `test_replanner_translates_actions_to_steps` still passes because it only requires at least one `search_section`.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/service/deep_research_v2/agents/replanner.py backend/test/test_deep_research_v3/test_replanner.py
git commit -m "feat: build revision contexts in replanner"
```

---

### Task 4: Writer Consumes Revision Context

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/writer.py:37-93`
- Modify: `backend/app/service/deep_research_v2/agents/writer.py:542-559`
- Create: `backend/test/test_deep_research_v3/test_writer_revision.py`

- [ ] **Step 1: Create failing writer revision tests**

Create `backend/test/test_deep_research_v3/test_writer_revision.py`:

```python
import json
from unittest.mock import AsyncMock

import pytest

from app.service.deep_research_v2.agents.writer import LeadWriter
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def writer():
    return LeadWriter(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


@pytest.mark.asyncio
async def test_write_one_section_uses_revision_context(writer, monkeypatch):
    response = json.dumps({
        "content": "修订后内容，补充了来源 [1]",
        "changes_made": ["补充来源"],
        "addressed_issue_ids": ["issue_1"],
        "unable_to_address": [],
        "citations": [{"source": "来源A", "url": "https://example.com"}],
    }, ensure_ascii=False)
    monkeypatch.setattr(writer, "call_llm", AsyncMock(return_value=response))

    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一", "description": "描述", "section_type": "mixed"}]
    state["draft_sections"] = {"sec_1": "旧内容"}
    state["facts"] = [{
        "id": "f1",
        "content": "事实一",
        "source_name": "来源A",
        "credibility_score": 0.9,
        "related_sections": ["sec_1"],
    }]
    state["revision_context_by_section"] = {
        "sec_1": {
            "section_id": "sec_1",
            "mode": "rewrite_with_feedback",
            "issues": [{
                "id": "issue_1",
                "severity": "major",
                "description": "缺少来源",
                "suggestion": "补充来源",
                "acceptance_criteria": ["新增引用"],
            }],
            "required_actions": ["rewrite"],
        }
    }

    result = await writer.write_one_section("sec_1", state)

    assert result["content"] == "修订后内容，补充了来源 [1]"
    assert result["addressed_issue_ids"] == ["issue_1"]
    assert state["draft_sections"]["sec_1"] == "修订后内容，补充了来源 [1]"
    called_prompt = writer.call_llm.await_args.kwargs["user_prompt"]
    assert "旧内容" in called_prompt
    assert "缺少来源" in called_prompt
    assert "新增引用" in called_prompt


@pytest.mark.asyncio
async def test_write_one_section_without_revision_context_uses_normal_path(writer, monkeypatch):
    monkeypatch.setattr(writer, "_write_section", AsyncMock())
    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一", "description": "描述", "section_type": "mixed"}]
    state["draft_sections"] = {"sec_1": "普通内容"}

    result = await writer.write_one_section("sec_1", state)

    writer._write_section.assert_awaited_once()
    assert result["section_id"] == "sec_1"
    assert result["content"] == "普通内容"
```

- [ ] **Step 2: Run writer revision tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_writer_revision.py -q
```

Expected: first test fails because `write_one_section()` ignores `revision_context_by_section`.

- [ ] **Step 3: Add the revision section prompt**

In `backend/app/service/deep_research_v2/agents/writer.py`, add this class constant after `SECTION_WRITING_PROMPT`:

```python
    REVISION_SECTION_PROMPT = """你是一位负责定向修订研究报告章节的资深编辑。

## 研究主题
{query}

## 当前章节
标题: {section_title}
描述: {section_description}
类型: {section_type}

## 旧章节内容
{previous_content}

## 必须解决的 Critic 问题
{issues}

## 可用事实
{facts}

## 数据点
{data_points}

## 写作要求
1. 只重写当前章节，不输出章节标题。
2. 必须优先满足每个问题的 acceptance_criteria。
3. 如果某个问题没有足够证据解决，删除或弱化 unsupported claim，并在 unable_to_address 中说明原因。
4. 关键事实必须带引用标记 [N]。
5. 不要为了看起来解决问题而编造来源。

输出JSON：
```json
{{
    "content": "修订后的章节正文（Markdown，不包含章节标题）",
    "changes_made": ["具体修改"],
    "addressed_issue_ids": ["issue_xxx"],
    "unable_to_address": [
        {{"issue_id": "issue_xxx", "reason": "无法解决原因"}}
    ],
    "citations": [
        {{"source": "来源名称", "url": "完整URL"}}
    ]
}}
```

开始修订："""
```

- [ ] **Step 4: Add revision formatting helpers and `_revise_section()`**

Inside `LeadWriter`, add these methods above `write_one_section()`:

```python
    def _format_revision_issues(self, context: Dict[str, Any]) -> str:
        lines = []
        for issue in context.get("issues", []) or []:
            criteria = issue.get("acceptance_criteria", []) or []
            criteria_text = "; ".join(str(item) for item in criteria) if criteria else "无"
            lines.append(
                f"- ID: {issue.get('id')}\n"
                f"  严重程度: {issue.get('severity')}\n"
                f"  问题: {issue.get('description')}\n"
                f"  建议: {issue.get('suggestion')}\n"
                f"  验收标准: {criteria_text}"
            )
        return "\n".join(lines) if lines else "无具体问题"

    async def _revise_section(
        self,
        state: ResearchState,
        section: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        section_id = section["id"]
        previous_content = state.get("draft_sections", {}).get(section_id, "")
        related_facts = [
            f for f in state.get("facts", [])
            if section_id in f.get("related_sections", [])
        ] or list(state.get("facts", [])[:10])
        facts_text = [
            f"- [{fact.get('id')}] {fact.get('content')} "
            f"(来源: {fact.get('source_name')}, 可信度: {fact.get('credibility_score')})"
            for fact in related_facts
        ]
        data_text = [
            f"- {dp.get('name')}: {dp.get('value')} {dp.get('unit', '')} ({dp.get('year', 'N/A')})"
            for dp in state.get("data_points", [])[:10]
        ]
        prompt = self.REVISION_SECTION_PROMPT.format(
            query=state["query"],
            section_title=section.get("title", ""),
            section_description=section.get("description", ""),
            section_type=section.get("section_type", "mixed"),
            previous_content=previous_content or "（暂无旧内容）",
            issues=self._format_revision_issues(context),
            facts="\n".join(facts_text) if facts_text else "（暂无相关事实）",
            data_points="\n".join(data_text) if data_text else "（暂无数据点）",
        )
        response = await self.call_llm(
            system_prompt="你是负责修订报告章节的资深编辑。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.3,
            max_tokens=16000,
            state=state,
            action="revise_section",
        )
        result = self.parse_json_response(response)
        content = result.get("content", "") if result else ""
        if content:
            state["draft_sections"][section_id] = content
        for citation in (result.get("citations", []) if result else []):
            state["references"].append({
                "id": len(state["references"]) + 1,
                "marker": citation.get("marker"),
                "source": citation.get("source"),
                "url": citation.get("url", ""),
            })
        return {
            "section_id": section_id,
            "content": content or previous_content,
            "changes_made": result.get("changes_made", []) if result else [],
            "addressed_issue_ids": result.get("addressed_issue_ids", []) if result else [],
            "unable_to_address": result.get("unable_to_address", []) if result else [],
        }
```

- [ ] **Step 5: Route `write_one_section()` through revision path**

In `write_one_section()`, replace:

```python
        await self._write_section(state, section)
        content = state.get("draft_sections", {}).get(section_id, "")
        return {"section_id": section_id, "content": content}
```

with:

```python
        revision_context = (
            state.get("revision_context_by_section", {}) or {}
        ).get(section_id)
        if revision_context:
            return await self._revise_section(state, section, revision_context)

        await self._write_section(state, section)
        content = state.get("draft_sections", {}).get(section_id, "")
        return {"section_id": section_id, "content": content}
```

- [ ] **Step 6: Run writer revision tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_writer_revision.py -q
```

Expected: both tests pass.

- [ ] **Step 7: Run writer-adjacent tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_tools.py test/test_deep_research_v3/test_executor.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add backend/app/service/deep_research_v2/agents/writer.py backend/test/test_deep_research_v3/test_writer_revision.py
git commit -m "feat: revise sections with critic context"
```

---

### Task 5: Executor Merges Revision Diagnostics

**Files:**
- Modify: `backend/app/service/deep_research_v2/executor.py:1-453`
- Modify: `backend/test/test_deep_research_v3/test_executor.py`

- [ ] **Step 1: Add failing executor test**

Append this test to `backend/test/test_deep_research_v3/test_executor.py`:

```python
@pytest.mark.asyncio
async def test_executor_records_writer_revision_diagnostics(monkeypatch):
    from app.service.deep_research_v2 import executor as executor_module
    from app.service.deep_research_v2.state import create_initial_state

    async def fake_write_section(section_id, state):
        return {
            "section_id": section_id,
            "content": "修订内容",
            "addressed_issue_ids": ["issue_1"],
            "unable_to_address": [{"issue_id": "issue_2", "reason": "无来源"}],
            "changes_made": ["补充引用"],
        }

    monkeypatch.setattr(
        executor_module,
        "TOOL_REGISTRY",
        dict(executor_module.TOOL_REGISTRY, write_section=fake_write_section),
    )

    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "旧内容"}
    state["plan"] = [{
        "step_id": "write_1",
        "tool": "write_section",
        "args": {"section_id": "sec_1"},
        "depends_on": [],
        "parallel_group": None,
    }]

    result = await executor_module.executor_node(state)

    assert result["draft_sections"]["sec_1"] == "修订内容"
    diagnostic = result["critic_diagnostics"][0]
    assert diagnostic["type"] == "writer_revision"
    assert diagnostic["section_id"] == "sec_1"
    assert diagnostic["addressed_issue_ids"] == ["issue_1"]
    assert diagnostic["before_hash"].startswith("sha256:")
    assert diagnostic["after_hash"].startswith("sha256:")
    assert diagnostic["before_hash"] != diagnostic["after_hash"]
```

- [ ] **Step 2: Run executor test to verify it fails**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_executor.py::test_executor_records_writer_revision_diagnostics -q
```

Expected: FAIL because `critic_diagnostics` is not returned.

- [ ] **Step 3: Add hash helper**

In `backend/app/service/deep_research_v2/executor.py`, add import:

```python
import hashlib
```

Add this helper near `_stats_for()`:

```python
def _hash_text(text: str) -> str:
    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
```

- [ ] **Step 4: Track diagnostics in `executor_node()`**

After `merged_draft_sections = dict(state.get("draft_sections", {}))`, add:

```python
    merged_critic_diagnostics = list(state.get("critic_diagnostics", []) or [])
```

Inside the `elif result["tool"] == "write_section":` branch, replace:

```python
                if sec_id:
                    merged_draft_sections[sec_id] = content
```

with:

```python
                if sec_id:
                    before_content = merged_draft_sections.get(sec_id, "")
                    merged_draft_sections[sec_id] = content
                    if output.get("addressed_issue_ids") or output.get("unable_to_address"):
                        merged_critic_diagnostics.append({
                            "type": "writer_revision",
                            "section_id": sec_id,
                            "addressed_issue_ids": output.get("addressed_issue_ids", []),
                            "unable_to_address": output.get("unable_to_address", []),
                            "changes_made": output.get("changes_made", []),
                            "before_hash": _hash_text(before_content),
                            "after_hash": _hash_text(content),
                        })
```

In the return dict, add:

```python
        "critic_diagnostics": merged_critic_diagnostics,
```

- [ ] **Step 5: Run executor tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_executor.py -q
```

Expected: all executor tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add backend/app/service/deep_research_v2/executor.py backend/test/test_deep_research_v3/test_executor.py
git commit -m "feat: record writer revision diagnostics"
```

---

### Task 6: Graph Threshold And Ineffective Loop Stop

**Files:**
- Modify: `backend/app/config/llm_config.py:85-103`
- Modify: `backend/app/service/deep_research_v2/graph.py:145-193`
- Modify: `backend/app/service/deep_research_v2/graph.py:947-965`
- Modify: `backend/test/test_deep_research_v3/test_graph_integration.py`

- [ ] **Step 1: Add failing graph route tests**

Append these tests to `backend/test/test_deep_research_v3/test_graph_integration.py`:

```python
def test_route_after_critic_no_effective_revision_returns_end():
    from app.service.deep_research_v2.graph import route_after_critic
    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "needs_revision"
    state["quality_score"] = 4.5
    state["replan_count"] = 2
    state["review_history"] = [
        {
            "quality_score": 4.5,
            "delta_from_previous": {
                "score_delta": 0.0,
                "changed_sections": [],
                "new_facts_count": 0,
                "new_references_count": 0,
            },
        },
        {
            "quality_score": 4.5,
            "delta_from_previous": {
                "score_delta": 0.0,
                "changed_sections": [],
                "new_facts_count": 0,
                "new_references_count": 0,
            },
        },
    ]
    assert route_after_critic(state) == "END"
    assert state["critic_loop_status"] == "no_effective_revision"


def test_route_after_critic_minor_near_threshold_passes_with_warnings():
    from app.service.deep_research_v2.graph import route_after_critic
    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "needs_revision"
    state["quality_score"] = 6.85
    state["replan_count"] = 1
    state["critic_feedback"] = [{
        "id": "minor_1",
        "severity": "minor",
        "resolved": False,
    }]
    assert route_after_critic(state) == "END"
    assert state["critic_loop_status"] == "passed_with_minor_warnings"
```

- [ ] **Step 2: Run graph route tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_graph_integration.py::test_route_after_critic_no_effective_revision_returns_end test/test_deep_research_v3/test_graph_integration.py::test_route_after_critic_minor_near_threshold_passes_with_warnings -q
```

Expected: FAIL because route does not set `critic_loop_status`.

- [ ] **Step 3: Align default quality threshold**

In `backend/app/config/llm_config.py`, change:

```python
    quality_threshold: float = 6.0
```

to:

```python
    quality_threshold: float = 7.0
```

- [ ] **Step 4: Add graph route helpers**

In `backend/app/service/deep_research_v2/graph.py`, replace:

```python
QUALITY_PASS_THRESHOLD = 7.0  # critic 给分 < 该值即视为"未通过"，需 replan
```

with:

```python
def _quality_pass_threshold() -> float:
    try:
        return float(get_config().research.quality_threshold)
    except Exception:
        return 7.0


def _only_minor_unresolved(state: ResearchState) -> bool:
    feedback = state.get("critic_feedback", []) or []
    unresolved = [
        item for item in feedback
        if isinstance(item, dict) and not item.get("resolved")
    ]
    return bool(unresolved) and all(
        item.get("severity") == "minor" for item in unresolved
    )


def _has_no_effective_revision(state: ResearchState) -> bool:
    history = state.get("review_history", []) or []
    if len(history) < 2:
        return False
    recent = history[-2:]
    for entry in recent:
        delta = entry.get("delta_from_previous", {}) or {}
        if abs(float(delta.get("score_delta") or 0.0)) >= 0.3:
            return False
        if delta.get("changed_sections"):
            return False
        if int(delta.get("new_facts_count") or 0) > 0:
            return False
        if int(delta.get("new_references_count") or 0) > 0:
            return False
    return True
```

- [ ] **Step 5: Update `route_after_critic()`**

Inside `route_after_critic()`, after computing `score`, add:

```python
    threshold = _quality_pass_threshold()

    if _has_no_effective_revision(state):
        state["critic_loop_status"] = "no_effective_revision"
        return "END"

    if _only_minor_unresolved(state) and score >= threshold - 0.2:
        state["critic_loop_status"] = "passed_with_minor_warnings"
        return "END"
```

Replace:

```python
    if suggested or unresolved > 0 or score < QUALITY_PASS_THRESHOLD or verdict in ("needs_revision", "needs_re_research"):
        return "replanner"
    return "END"
```

with:

```python
    if suggested or unresolved > 0 or score < threshold or verdict in ("needs_revision", "needs_re_research"):
        state["critic_loop_status"] = "needs_revision"
        return "replanner"
    state["critic_loop_status"] = "passed"
    return "END"
```

Also set statuses for the early returns:

```python
    if replan_count >= MAX_REPLAN:
        state["critic_loop_status"] = "max_replan_reached"
        return "END"

    verdict = (state.get("verdict") or "").lower()
    if verdict == "pass":
        state["critic_loop_status"] = "passed"
        return "END"
```

- [ ] **Step 6: Include loop status in completion event**

In `_build_completion_event()`, add:

```python
            "critic_loop_status": state.get("critic_loop_status", ""),
            "unresolved_issues": state.get("unresolved_issues", 0),
```

inside the returned dict.

- [ ] **Step 7: Run graph integration tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_graph_integration.py -q
```

Expected: all graph integration tests pass.

- [ ] **Step 8: Commit Task 6**

```bash
git add backend/app/config/llm_config.py backend/app/service/deep_research_v2/graph.py backend/test/test_deep_research_v3/test_graph_integration.py
git commit -m "feat: stop ineffective critic loops"
```

---

### Task 7: Focused Regression Run

**Files:**
- No source changes unless a previous task failed verification.

- [ ] **Step 1: Run the focused deep research v3 tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3 -q
```

Expected: all tests in `test_deep_research_v3` pass.

- [ ] **Step 2: Run eval tests that consume critic feedback**

Run:

```bash
cd backend
pytest app/eval/tests/test_evaluators/test_critic_loop.py app/eval/tests/test_metric_calculator.py -q
```

Expected: all selected eval tests pass. The old `critic_loop` metric can still score `resolved=True` feedback; this implementation only improves how runtime feedback gets resolved.

- [ ] **Step 3: Run a wider backend smoke set**

Run:

```bash
cd backend
pytest test/test_deep_research_v3 app/eval/tests/test_evaluators/test_critic_loop.py app/eval/tests/test_metric_calculator.py test/test_memory/test_research_writeback.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: empty output.

- [ ] **Step 5: Record verification commit if needed**

If Task 7 required any code or test adjustment, commit it:

```bash
git add backend/app backend/test
git commit -m "test: verify critic revision loop"
```

If Task 7 required no file changes, do not create an empty commit.

---

## Self-Review Notes

Spec coverage:

- Diagnostic observability is covered by Tasks 1, 2, and 5.
- Directed revision loop is covered by Tasks 3 and 4.
- Threshold consolidation and no-effective-revision stop conditions are covered by Task 6.
- Offline claim-centered eval is intentionally out of scope.

Type consistency:

- `review_history`, `revision_context_by_section`, and `critic_diagnostics` are JSON-serializable values in `ResearchState`.
- `revision_context_by_section` is produced by Replanner and consumed by Writer using the same section-id key.
- `addressed_issue_ids`, `unable_to_address`, and `changes_made` are emitted by Writer and read by Executor using identical names.

Verification:

- Every behavior change has a failing test first.
- All tests are mocked/offline and do not require LLM or search network calls.

