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
