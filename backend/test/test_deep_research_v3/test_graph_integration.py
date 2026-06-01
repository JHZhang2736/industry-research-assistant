"""4-node 主图集成测试（mock LLM）"""
import pytest
import os
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def graph(monkeypatch):
    """创建 graph，所有 sub-agent 的 LLM 调用都 mock"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy")
    from app.service.deep_research_v2.graph import DeepResearchGraph
    g = DeepResearchGraph(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
    )
    return g


def test_graph_compiled_has_4_main_nodes(graph):
    """compile 后的 graph 应包含 planner / executor / critic / replanner 4 个主 node"""
    compiled = graph.graph
    node_names = set(compiled.get_graph().nodes.keys())
    assert "planner" in node_names
    assert "executor" in node_names
    assert "critic" in node_names
    assert "replanner" in node_names


def test_route_after_critic_pass_returns_end():
    """verdict=pass + 高分 → END"""
    from app.service.deep_research_v2.graph import route_after_critic
    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "pass"
    state["quality_score"] = 8.5
    state["unresolved_issues"] = 0
    state["suggested_actions"] = []
    state["replan_count"] = 0
    assert route_after_critic(state) == "END"


def test_route_after_critic_low_score_no_actions_still_replans():
    """新规则：critic 给低分但忘填 suggested_actions 也应触发 replanner"""
    from app.service.deep_research_v2.graph import route_after_critic
    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "needs_revision"
    state["quality_score"] = 4.5
    state["unresolved_issues"] = 0
    state["suggested_actions"] = []
    state["replan_count"] = 0
    assert route_after_critic(state) == "replanner"


def test_route_after_critic_needs_revision_goes_replanner():
    """有 unresolved + suggested_actions + 未达 max → replanner"""
    from app.service.deep_research_v2.graph import route_after_critic
    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "needs_revision"
    state["unresolved_issues"] = 2
    state["suggested_actions"] = ["retry_search:sec_1"]
    state["replan_count"] = 0
    assert route_after_critic(state) == "replanner"


def test_route_after_replanner_under_max_returns_executor():
    """replan_count 未达 max + fallback 未触发 → executor"""
    from app.service.deep_research_v2.graph import route_after_replanner
    state = create_initial_state(query="test", session_id="s")
    state["replan_count"] = 1
    state["fallback_triggered"] = False
    assert route_after_replanner(state) == "executor"


def test_route_after_replanner_at_max_returns_end():
    """达到 max_replan → END"""
    from app.service.deep_research_v2.graph import route_after_replanner
    state = create_initial_state(query="test", session_id="s")
    state["replan_count"] = 3
    state["fallback_triggered"] = False
    assert route_after_replanner(state) == "END"


@pytest.mark.asyncio
async def test_replanner_node_does_not_derive_actions_for_resolved_feedback(graph):
    state = create_initial_state(query="test", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Logic"}]
    state["suggested_actions"] = []
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

    result = await graph._replanner_node(state)

    assert result["plan"] == []
    assert "sec_1" not in result["revision_context_by_section"]
