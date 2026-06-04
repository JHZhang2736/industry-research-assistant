"""4-node 主图集成测试（mock LLM）"""
import pytest
from unittest.mock import AsyncMock
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
    """outer graph wraps the 4-node deep research workflow as a subgraph."""
    outer_names = set(graph.graph.get_graph().nodes.keys())
    assert "intent_router" in outer_names
    assert "deep_research" in outer_names

    subgraph = graph._build_deep_research_subgraph()
    inner_names = set(subgraph.get_graph().nodes.keys())
    assert "planner" in inner_names
    assert "executor" in inner_names
    assert "critic" in inner_names
    assert "replanner" in inner_names


def test_graph_compiled_has_scoping_before_planner(graph):
    subgraph = graph._build_deep_research_subgraph()
    inner = subgraph.get_graph()
    inner_names = set(inner.nodes.keys())
    assert "scoping" in inner_names


@pytest.mark.asyncio
async def test_scoping_node_returns_summary(graph, monkeypatch):
    state = create_initial_state(query="energy storage", session_id="s")
    state["research_type"] = "industry_analysis"

    async def fake_scope_topic(state, query, count=3, max_queries=3):
        return {"queries": [query], "key_subdomains": ["grid"], "initial_sources": []}

    monkeypatch.setattr(graph.scout, "scope_topic", fake_scope_topic)

    result = await graph._scoping_node(state)

    assert result["scoping_summary"]["key_subdomains"] == ["grid"]


def test_checkpoint_event_includes_scoping_stats(graph, monkeypatch):
    state = create_initial_state(query="energy storage", session_id="s")
    state["scoping_summary"] = {
        "initial_sources": [{"title": "A"}, {"title": "B"}],
        "hot_terms": ["battery", "grid", "lithium"],
    }
    ui_state = {
        "research_steps": [],
        "search_results": [],
        "charts": [],
        "streaming_report": "",
    }

    graph.checkpoint_service = object()
    monkeypatch.setattr(graph, "_save_checkpoint", lambda *args, **kwargs: True)

    event = graph._build_checkpoint_event(state, None, ui_state, "scoping")

    assert event["type"] == "checkpoint_saved"
    assert ui_state["research_steps"][0]["type"] == "scoping"
    assert ui_state["research_steps"][0]["stats"] == {
        "sources": 2,
        "hot_terms": 3,
    }


@pytest.mark.asyncio
async def test_run_pauses_after_planner_when_approval_pending(graph, monkeypatch):
    state = create_initial_state(query="energy storage", session_id="s")
    state["intent"] = "deep_research"
    state["research_type"] = "industry_analysis"
    state["scoping_summary"] = {"key_subdomains": ["grid"]}

    async def fake_astream(*args, **kwargs):
        yield ((), "updates", {
            "planner": {
                "outline": [{"id": "sec_1", "title": "Demand", "description": "D"}],
                "plan": [{
                    "step_id": "step_search_sec_1",
                    "tool": "search_section",
                    "args": {"section_id": "sec_1", "queries": ["Demand"]},
                    "depends_on": [],
                    "parallel_group": "search_batch",
                }],
            }
        })
        raise AssertionError("executor must not run after approval pause")

    saved = {}

    def fake_save_checkpoint(state, user_id=None, ui_state=None, status=None):
        saved["state"] = dict(state)
        saved["status"] = status
        return True

    monkeypatch.setattr(graph.graph, "astream", fake_astream)
    monkeypatch.setattr(graph, "_save_checkpoint", fake_save_checkpoint)

    events = [event async for event in graph._run_with_langgraph(state)]

    approval_events = [
        e for e in events if e.get("type") == "outline_approval_required"
    ]
    assert approval_events
    assert approval_events[0]["outline"][0]["title"] == "Demand"
    assert approval_events[0]["scoping_summary"] == {"key_subdomains": ["grid"]}
    assert saved["status"] == "paused"


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


def test_route_after_critic_pass_with_low_score_replans():
    from app.service.deep_research_v2.graph import _route_after_critic_with_status

    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "pass"
    state["quality_score"] = 6.5
    state["unresolved_issues"] = 0
    state["suggested_actions"] = []
    state["replan_count"] = 0

    assert _route_after_critic_with_status(state) == ("replanner", "needs_revision")


def test_route_after_critic_pass_with_unresolved_major_replans():
    from app.service.deep_research_v2.graph import _route_after_critic_with_status

    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "pass"
    state["quality_score"] = 8.5
    state["unresolved_issues"] = 0
    state["suggested_actions"] = []
    state["critic_feedback"] = [{
        "id": "issue_major",
        "severity": "major",
        "resolved": False,
    }]
    state["replan_count"] = 0

    assert _route_after_critic_with_status(state) == ("replanner", "needs_revision")


def test_route_after_critic_clean_pass_sets_passed_status():
    from app.service.deep_research_v2.graph import _route_after_critic_with_status

    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "pass"
    state["quality_score"] = 8.5
    state["unresolved_issues"] = 0
    state["suggested_actions"] = []
    state["critic_feedback"] = []
    state["replan_count"] = 0

    assert _route_after_critic_with_status(state) == ("END", "passed")


def test_route_after_critic_clean_pass_with_flat_deltas_stays_passed():
    from app.service.deep_research_v2.graph import _route_after_critic_with_status

    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "pass"
    state["quality_score"] = 8.5
    state["unresolved_issues"] = 0
    state["suggested_actions"] = []
    state["critic_feedback"] = []
    state["review_history"] = [
        {
            "quality_score": 8.5,
            "delta_from_previous": {
                "score_delta": 0.0,
                "changed_sections": [],
                "new_facts_count": 0,
                "new_references_count": 0,
            },
        },
        {
            "quality_score": 8.5,
            "delta_from_previous": {
                "score_delta": 0.0,
                "changed_sections": [],
                "new_facts_count": 0,
                "new_references_count": 0,
            },
        },
    ]

    assert _route_after_critic_with_status(state) == ("END", "passed")


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


def test_route_after_critic_no_effective_revision_returns_end():
    from app.service.deep_research_v2.graph import (
        _route_after_critic_with_status,
        route_after_critic,
    )
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
    route, status = _route_after_critic_with_status(state)
    assert route == "END"
    assert status == "no_effective_revision"
    assert route_after_critic(state) == "END"
    assert state["critic_loop_status"] == ""


def test_route_after_critic_minor_near_threshold_passes_with_warnings():
    from app.service.deep_research_v2.graph import (
        _route_after_critic_with_status,
        route_after_critic,
    )
    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "needs_revision"
    state["quality_score"] = 6.85
    state["replan_count"] = 1
    state["critic_feedback"] = [{
        "id": "minor_1",
        "severity": "minor",
        "resolved": False,
    }]
    route, status = _route_after_critic_with_status(state)
    assert route == "END"
    assert status == "passed_with_minor_warnings"
    assert route_after_critic(state) == "END"
    assert state["critic_loop_status"] == ""


def test_route_after_critic_baseline_plus_one_ineffective_still_replans():
    from app.service.deep_research_v2.graph import _route_after_critic_with_status
    state = create_initial_state(query="test", session_id="s")
    state["verdict"] = "needs_revision"
    state["quality_score"] = 4.5
    state["replan_count"] = 1
    state["review_history"] = [
        {
            "quality_score": 4.5,
            "delta_from_previous": {
                "score_delta": None,
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

    assert _route_after_critic_with_status(state) == ("replanner", "needs_revision")


def test_route_after_critic_final_report_changed_still_replans():
    from app.service.deep_research_v2.graph import _route_after_critic_with_status
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
                "final_report_changed": True,
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

    assert _route_after_critic_with_status(state) == ("replanner", "needs_revision")


@pytest.mark.asyncio
async def test_critic_node_returns_persisted_loop_status(graph):
    state = create_initial_state(query="test", session_id="s")
    graph.critic.process = AsyncMock(return_value={
        "verdict": "needs_revision",
        "quality_score": 6.85,
        "replan_count": 1,
        "critic_feedback": [{
            "id": "minor_1",
            "severity": "minor",
            "resolved": False,
        }],
        "unresolved_issues": 0,
        "suggested_actions": [],
    })

    result = await graph._critic_node(state)

    assert result["critic_loop_status"] == "passed_with_minor_warnings"
