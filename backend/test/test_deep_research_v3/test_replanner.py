"""测试 Replanner node"""
import pytest
from app.service.deep_research_v2.agents.replanner import Replanner
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def replanner():
    return Replanner(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


@pytest.mark.asyncio
async def test_replanner_translates_actions_to_steps(replanner):
    """suggested_actions=['retry_search:sec_3'] → 生成对应 search_section step"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_3", "title": "三章"}]
    state["critic_feedback"] = [{"target_section": "sec_3"}]
    state["replan_count"] = 0

    result = await replanner.process(
        state=state,
        suggested_actions=["retry_search:sec_3"],
    )

    assert len(result["plan"]) >= 1
    assert any(s["tool"] == "search_section" for s in result["plan"])
    assert any(s["args"].get("section_id") == "sec_3" for s in result["plan"])
    assert result["replan_count"] == 1


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
    assert context["issues"][0] is not state["critic_feedback"][0]
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


@pytest.mark.asyncio
async def test_replanner_drops_stale_context_for_resolved_feedback(replanner):
    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "逻辑"}]
    state["revision_context_by_section"] = {
        "sec_1": {
            "section_id": "sec_1",
            "mode": "rewrite_with_feedback",
            "issues": [{"id": "old_issue"}],
        }
    }
    state["critic_feedback"] = [{
        "id": "old_issue",
        "target_section": "sec_1",
        "issue_type": "logic_error",
        "resolved": True,
    }]

    result = await replanner.process(state=state, suggested_actions=[])

    assert result["plan"] == []
    assert "sec_1" not in result["revision_context_by_section"]


@pytest.mark.asyncio
async def test_replanner_retry_search_subsumes_rewrite_for_same_section(replanner):
    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "逻辑"}]

    result = await replanner.process(
        state=state,
        suggested_actions=["retry_search:sec_1", "rewrite:sec_1"],
    )

    tools = [step["tool"] for step in result["plan"]]
    assert tools == ["search_section", "write_section"]
    assert result["plan"][1]["depends_on"] == [result["plan"][0]["step_id"]]


@pytest.mark.asyncio
async def test_replanner_add_data_subsumes_rewrite_for_same_section(replanner):
    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "逻辑"}]

    result = await replanner.process(
        state=state,
        suggested_actions=["rewrite:sec_1", "add_data:sec_1"],
    )

    tools = [step["tool"] for step in result["plan"]]
    assert tools == ["search_section", "analyze_facts", "write_section"]
    assert result["plan"][2]["depends_on"] == [result["plan"][1]["step_id"]]


@pytest.mark.asyncio
async def test_replanner_handles_rewrite_action(replanner):
    """suggested_actions=['rewrite:sec_5'] → write_section step"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_5", "title": "五章"}]
    state["replan_count"] = 1

    result = await replanner.process(
        state=state,
        suggested_actions=["rewrite:sec_5"],
    )

    assert any(s["tool"] == "write_section" for s in result["plan"])
    assert any(s["args"].get("section_id") == "sec_5" for s in result["plan"])
    assert result["replan_count"] == 2


@pytest.mark.asyncio
async def test_replanner_returns_empty_plan_when_no_actions(replanner):
    """空 suggested_actions → 空 plan"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["replan_count"] = 0

    result = await replanner.process(state=state, suggested_actions=[])
    assert result["plan"] == []


@pytest.mark.asyncio
async def test_replanner_unknown_action_logged_skipped(replanner):
    """未知 action 跳过但不抛异常"""
    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "一章"}]
    state["replan_count"] = 0

    result = await replanner.process(
        state=state,
        suggested_actions=["unknown_action:foo", "retry_search:sec_1"],
    )
    assert any(s["tool"] == "search_section" for s in result["plan"])
