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


def test_gated_credibility_drops_below_floor(scout):
    # 未知域名 + LLM 0.2 + 旧文(>3y) → 0.2*0.6=0.12 < 0.3 → None
    url_date = {"http://x": "2019-01-01T00:00:00+08:00"}
    assert scout._gated_credibility(0.2, "http://x", url_date) is None


def test_gated_credibility_domain_rescues(scout):
    # 权威域名把 LLM 低分救回：max(0.95,0.2)=0.95 → 通过
    v = scout._gated_credibility(0.2, "https://www.xinhuanet.com/x", {})
    assert v is not None and v > 0.9


@pytest.mark.asyncio
async def test_research_section_ingest_applies_gate(scout, monkeypatch):
    # 两条 fact：一条来自权威源（保留），一条低质（丢弃）
    analysis = {
        "extracted_facts": [
            {"content": "权威事实 A", "source_url": "https://www.stats.gov.cn/a",
             "source_name": "统计局", "credibility_score": 0.4, "importance": "high"},
            {"content": "低质事实 B", "source_url": "http://blog-xyz.com/b",
             "source_name": "某博客", "credibility_score": 0.2, "importance": "low"},
        ],
    }
    monkeypatch.setattr(scout, "_analyze_search_results", AsyncMock(return_value=analysis))
    monkeypatch.setattr(scout, "_execute_search", AsyncMock(return_value=[
        {"url": "https://www.stats.gov.cn/a", "title": "t", "summary": "s",
         "site_name": "统计局", "date": "2026-05-01T00:00:00+08:00"},
        {"url": "http://blog-xyz.com/b", "title": "t", "summary": "s",
         "site_name": "blog", "date": "2019-01-01T00:00:00+08:00"},
    ]))

    state = {
        "query": "Q", "facts": [], "data_points": [], "insights": [],
        "hypotheses": [], "iteration": 99, "max_iterations": 1,
        "search_web": True, "search_local": False, "messages": [], "phase": "researching",
    }
    section = {"id": "s1", "title": "章节", "search_queries": ["q1"]}

    await scout._research_section(state, section)

    contents = [f["content"] for f in state["facts"]]
    assert "权威事实 A" in contents          # 高质保留
    assert "低质事实 B" not in contents      # 低质被闸门丢弃
    a = next(f for f in state["facts"] if f["content"] == "权威事实 A")
    assert a["importance"] == "high"          # importance 落库
    assert a["credibility_score"] > 0.9       # 存的是 final_credibility
