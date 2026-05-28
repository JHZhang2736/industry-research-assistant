"""测试 Critic node 改造后输出 suggested_actions"""
import pytest
import json
from unittest.mock import AsyncMock
from app.service.deep_research_v2.agents import CriticMaster
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def critic():
    return CriticMaster(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


@pytest.mark.asyncio
async def test_critic_outputs_suggested_actions_field(critic, monkeypatch):
    """Critic 输出新字段 suggested_actions: list[str]"""
    mock_response = json.dumps({
        "quality_score": 7.2,
        "critic_feedback": [
            {"id": "f1", "target_section": "sec_3", "issue_type": "missing_source",
             "severity": "major", "description": "...", "suggestion": "..."}
        ],
        "unresolved_issues": 2,
        "verdict": "needs_revision",
        "suggested_actions": ["retry_search:sec_3", "rewrite:sec_5"],
    }, ensure_ascii=False)

    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["draft_sections"] = {"sec_1": "draft", "sec_3": "draft", "sec_5": "draft"}
    state["facts"] = []
    state["outline"] = [{"id": "sec_3", "title": "三"}]

    result = await critic.process(state)

    assert "suggested_actions" in result
    assert "retry_search:sec_3" in result["suggested_actions"]
    assert "rewrite:sec_5" in result["suggested_actions"]
    assert result["quality_score"] == 7.2


@pytest.mark.asyncio
async def test_critic_empty_suggested_actions_on_pass(critic, monkeypatch):
    """verdict=pass 时 suggested_actions 为空"""
    mock_response = json.dumps({
        "quality_score": 9.0,
        "critic_feedback": [],
        "unresolved_issues": 0,
        "verdict": "pass",
        "suggested_actions": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["draft_sections"] = {"sec_1": "ok"}
    state["facts"] = []
    state["outline"] = []

    result = await critic.process(state)
    assert result["suggested_actions"] == []
    assert result["unresolved_issues"] == 0
