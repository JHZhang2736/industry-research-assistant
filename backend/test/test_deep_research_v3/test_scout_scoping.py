import pytest

from app.service.deep_research_v2.agents.scout import DeepScout
from app.service.deep_research_v2.state import create_initial_state


@pytest.mark.asyncio
async def test_scope_topic_uses_shallow_search_without_mutating_facts(monkeypatch):
    scout = DeepScout(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
        model="qwen-plus",
    )
    calls = []

    async def fake_execute_search(query, count=10):
        calls.append((query, count))
        return [
            {
                "url": f"https://example.com/{len(calls)}",
                "title": f"{query} market report",
                "summary": "battery storage policy demand supply chain",
                "snippet": "battery storage policy demand supply chain",
                "site_name": "Example Research",
                "date": "2026-01-01",
            }
        ]

    async def forbidden_deep_search(*args, **kwargs):
        raise AssertionError("_execute_deep_search must not run during scoping")

    monkeypatch.setattr(scout, "_execute_search", fake_execute_search)
    monkeypatch.setattr(scout, "_execute_deep_search", forbidden_deep_search)

    state = create_initial_state("battery storage industry", "sid_1")
    summary = await scout.scope_topic(state, "battery storage industry", count=2, max_queries=2)

    assert len(calls) == 2
    assert all(count == 2 for _, count in calls)
    assert state["facts"] == []
    assert state["raw_sources"] == []
    assert summary["queries"][0] == "battery storage industry"
    assert summary["initial_sources"][0]["site_name"] == "Example Research"
    assert "battery" in summary["hot_terms"]


@pytest.mark.asyncio
async def test_scope_topic_returns_warning_on_search_failure(monkeypatch):
    scout = DeepScout(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
        model="qwen-plus",
    )

    async def failing_execute_search(query, count=10):
        raise RuntimeError("search unavailable")

    monkeypatch.setattr(scout, "_execute_search", failing_execute_search)

    state = create_initial_state("robotics", "sid_1")
    summary = await scout.scope_topic(state, "robotics", count=2, max_queries=2)

    assert summary["queries"] == ["robotics"]
    assert summary["initial_sources"] == []
    assert "search unavailable" in summary["warning"]
    assert state["facts"] == []
