import json
import pytest
from unittest.mock import AsyncMock

from app.service.deep_research_v2.agents.scout import DeepScout


@pytest.fixture
def scout():
    return DeepScout(
        llm_api_key="k", llm_base_url="http://localhost",
        search_api_key="s", model="qwen-plus",
    )


@pytest.mark.asyncio
async def test_analyze_passes_full_summary_and_uses_rerank(scout, monkeypatch):
    captured = {}

    async def fake_llm(system_prompt, user_prompt, **kwargs):
        captured["user_prompt"] = user_prompt
        return json.dumps({"extracted_facts": []})
    monkeypatch.setattr(scout, "call_llm", AsyncMock(side_effect=fake_llm))

    # _rerank 原样返回（按相关性已排序），用于隔离断言
    rerank_calls = {}

    async def fake_rerank(query, results, **kwargs):
        rerank_calls["query"] = query
        return results
    monkeypatch.setattr(scout, "_rerank", AsyncMock(side_effect=fake_rerank))

    long_summary = "数" * 700  # 700 字，旧逻辑会被截到 300
    results = [{"title": "市场", "url": "http://a", "site_name": "新华网",
                "date": "2025-01-01T00:00:00+08:00", "summary": long_summary}]
    section = {"title": "市场规模", "description": "规模"}

    await scout._analyze_search_results("AI 行业", section, results, hypotheses=[])

    # rerank 用章节标题作为 query
    assert rerank_calls["query"] == "市场规模"
    # summary 放宽到 1000：第 500 个字符仍在 prompt 中（旧逻辑 300 截断会丢）
    assert "数" * 500 in captured["user_prompt"]
