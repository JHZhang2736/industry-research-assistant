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
