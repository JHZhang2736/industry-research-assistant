"""测试 Planner node 实现"""
import pytest
import json
from unittest.mock import AsyncMock
from app.service.deep_research_v2.agents.planner import Planner, PLANNER_PROMPT
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def planner():
    return Planner(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


def test_planner_prompt_contains_plan_schema(planner):
    """Planner prompt 必须包含 plan 输出 schema 说明"""
    assert "plan" in PLANNER_PROMPT.lower()
    assert "parallel_group" in PLANNER_PROMPT
    assert "outline" in PLANNER_PROMPT.lower()


@pytest.mark.asyncio
async def test_planner_returns_outline_and_plan(planner, monkeypatch):
    """planner 调用 LLM 返回 outline + plan 列表"""
    mock_response = json.dumps({
        "outline": [
            {"id": "sec_1", "title": "市场规模", "description": "...",
             "section_type": "quantitative", "status": "pending",
             "requires_data": True, "requires_chart": True},
        ],
        "plan": [
            {"step_id": "step_1", "tool": "search_section",
             "args": {"section_id": "sec_1", "queries": ["市场规模"]},
             "depends_on": [], "parallel_group": "search_batch"},
            {"step_id": "step_2", "tool": "analyze_facts",
             "args": {}, "depends_on": ["step_1"], "parallel_group": None},
        ],
    }, ensure_ascii=False)

    monkeypatch.setattr(planner, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="5G 市场分析", session_id="sid_1")
    result = await planner.process(state)

    assert len(result["outline"]) == 1
    assert result["outline"][0]["id"] == "sec_1"
    assert len(result["plan"]) == 2
    assert result["plan"][0]["tool"] == "search_section"
    assert result["plan"][1]["depends_on"] == ["step_1"]


@pytest.mark.asyncio
async def test_planner_fallback_template_on_llm_failure(planner, monkeypatch):
    """LLM 输出 JSON 解析失败时，回退到本地模板"""
    monkeypatch.setattr(planner, "call_llm", AsyncMock(return_value="not a valid json"))

    state = create_initial_state(query="测试", session_id="sid_1")
    result = await planner.process(state)

    assert len(result["outline"]) >= 1
    assert len(result["plan"]) >= 1
    assert all("step_id" in step for step in result["plan"])
