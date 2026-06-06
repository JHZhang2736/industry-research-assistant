"""测试 sub-agent 改造成 @tool 后的接口契约"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.service.deep_research_v2.tools import (
    search_section,
    get_scout_instance,
    reset_instances,
)
from app.service.deep_research_v2.state import create_initial_state


def test_search_section_is_tool():
    """search_section 应被 @tool 装饰，可通过 .name 识别"""
    assert hasattr(search_section, "name")
    assert search_section.name == "search_section"


def test_search_section_has_docstring():
    """tool 必须有 docstring，否则 LLM 看不懂"""
    assert search_section.description
    desc = search_section.description.lower()
    # Check for either Chinese or English indicators
    has_search_indicator = "搜索" in search_section.description or "search" in desc
    assert has_search_indicator, f"Docstring missing search indicator: {search_section.description}"


@pytest.mark.asyncio
async def test_search_section_returns_dict(monkeypatch):
    """search_section 返回 {'facts': [...], 'sources': [...], 'section_id': ...}"""
    state = create_initial_state(query="测试", session_id="sid_1")

    mock_scout = AsyncMock()
    mock_scout.search_with_queries = AsyncMock(return_value={
        "facts": [{"id": "f1", "content": "test fact"}],
        "sources": [{"url": "http://example.com"}],
        "section_id": "sec_1",
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_scout_instance",
        lambda: mock_scout
    )

    result = await search_section.ainvoke({
        "section_id": "sec_1",
        "queries": ["测试 query"],
        "state": state,
    })

    assert "facts" in result
    assert "sources" in result
    assert result["section_id"] == "sec_1"
    assert isinstance(result["facts"], list)


def test_scout_instance_is_singleton():
    """get_scout_instance 应返回同一实例"""
    reset_instances()
    # Mock the config to avoid needing real API keys
    import unittest.mock as mock
    with mock.patch("app.service.deep_research_v2.tools.get_config") as mock_config:
        mock_config.return_value = MagicMock(
            api_key="test_key",
            base_url="http://test",
            search_api_key="search_key",
            agents=MagicMock(
                scout=MagicMock(model="test-model")
            )
        )

        inst1 = get_scout_instance()
        inst2 = get_scout_instance()
        assert inst1 is inst2

        reset_instances()


@pytest.mark.asyncio
async def test_analyze_facts_returns_data_points(monkeypatch):
    """analyze_facts 返回 {'data_points': [...], 'insights': [...]}"""
    from app.service.deep_research_v2.tools import analyze_facts

    state = create_initial_state(query="测试", session_id="sid_1")
    state["facts"] = [{"id": "f1", "content": "5G 用户突破 10 亿"}]

    mock_analyst = AsyncMock()
    mock_analyst.extract_data_points = AsyncMock(return_value={
        "data_points": [{"name": "5G 用户数", "value": 10, "unit": "亿"}],
        "insights": ["增长强劲"],
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_analyst_instance",
        lambda: mock_analyst
    )

    result = await analyze_facts.ainvoke({"state": state})

    assert "data_points" in result
    assert "insights" in result
    assert result["data_points"][0]["name"] == "5G 用户数"


@pytest.mark.asyncio
async def test_generate_charts_returns_charts(monkeypatch):
    """generate_charts 返回 {'charts': [...], 'code_executions': [...]}"""
    from app.service.deep_research_v2.tools import generate_charts

    state = create_initial_state(query="测试", session_id="sid_1")
    state["data_points"] = [{"name": "x", "value": 1}]

    mock_wizard = AsyncMock()
    mock_wizard.generate_charts_for_state = AsyncMock(return_value={
        "charts": [{"id": "c1", "chart_type": "bar"}],
        "code_executions": [{"code": "...", "ok": True}],
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_wizard_instance",
        lambda: mock_wizard
    )

    result = await generate_charts.ainvoke({"state": state})
    assert "charts" in result
    assert "code_executions" in result
    assert len(result["charts"]) == 1


@pytest.mark.asyncio
async def test_write_section_returns_draft(monkeypatch):
    """write_section 写一个章节，返回 {section_id, content}"""
    from app.service.deep_research_v2.tools import write_section

    state = create_initial_state(query="测试", session_id="sid_1")
    state["facts"] = [{"id": "f1", "content": "fact"}]
    state["outline"] = [{"id": "sec_1", "title": "第一章"}]

    mock_writer = AsyncMock()
    mock_writer.write_one_section = AsyncMock(return_value={
        "section_id": "sec_1",
        "content": "# 第一章\n章节内容...",
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_writer_instance",
        lambda: mock_writer
    )

    result = await write_section.ainvoke({
        "section_id": "sec_1",
        "state": state,
    })

    assert result["section_id"] == "sec_1"
    assert "content" in result


@pytest.mark.asyncio
async def test_analyze_facts_returns_timeseries_distributions(monkeypatch):
    """analyze_facts 返回里含 time_series / distributions"""
    from app.service.deep_research_v2.tools import analyze_facts

    state = create_initial_state(query="测试", session_id="sid_1")
    state["raw_sources"] = [{"url": "http://a.com", "text": "x", "relevance_score": 0.9}]

    mock_analyst = AsyncMock()
    mock_analyst.extract_data_points = AsyncMock(return_value={
        "data_points": [{"name": "m"}],
        "insights": ["i"],
        "time_series": [{"id": "ts1"}],
        "distributions": [{"id": "d1"}],
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_analyst_instance",
        lambda: mock_analyst,
    )

    result = await analyze_facts.ainvoke({"state": state})
    assert result["time_series"] == [{"id": "ts1"}]
    assert result["distributions"] == [{"id": "d1"}]
