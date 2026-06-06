"""DataAnalyst: 改读 raw_sources 抽数 + 超集 schema"""
import json
import pytest

from app.service.deep_research_v2.agents.data_analyst import DataAnalyst
from app.service.deep_research_v2.state import create_initial_state


def _make_analyst():
    return DataAnalyst(llm_api_key="dummy", llm_base_url="http://dummy", model="qwen-max")


@pytest.mark.asyncio
async def test_extract_data_reads_raw_sources(monkeypatch):
    """_extract_data 从 raw_sources 抽数，产出超集 schema，并存 time_series/distributions"""
    analyst = _make_analyst()
    state = create_initial_state("AI 市场", "sid")
    state["raw_sources"] = [
        {"url": "http://gov.cn/r1", "title": "报告1", "site_name": "统计局",
         "date": "2026-01-01", "text": "2024 年市场规模 5000 亿元",
         "related_sections": ["sec_1"], "relevance_score": 0.95},
    ]

    captured = {}

    async def fake_call_llm(*a, **k):
        captured["prompt"] = k.get("user_prompt", "")
        return json.dumps({
            "data_points": [
                {"metric_key": "ai_market_size", "name": "AI市场规模", "value": 5000,
                 "unit": "亿元", "year": 2024, "source_url": "http://gov.cn/r1",
                 "confidence": 0.9},
            ],
            "time_series": [{"id": "ts1", "metric": "AI市场规模", "data": [{"year": 2024, "value": 5000}]}],
            "distributions": [{"id": "d1", "name": "细分占比", "data": []}],
            "insights": ["市场规模快速增长"],
        })

    monkeypatch.setattr(analyst, "call_llm", fake_call_llm)
    result = await analyst._extract_data(state)

    assert "5000 亿元" in captured["prompt"]
    dp = state["data_points"][0]
    assert dp["metric_key"] == "ai_market_size"
    assert dp["source_url"] == "http://gov.cn/r1"
    assert "source_name" in dp and "credibility" in dp
    assert dp["source"] == dp["source_name"]       # 旧别名
    assert dp["confidence"] == dp["credibility"]   # 旧别名
    assert dp["related_sections"] == ["sec_1"]     # 取自命中 raw_source
    assert state["time_series"] == [{"id": "ts1", "metric": "AI市场规模", "data": [{"year": 2024, "value": 5000}]}]
    assert state["distributions"] == [{"id": "d1", "name": "细分占比", "data": []}]
    assert set(result.keys()) >= {"data_points", "time_series", "distributions", "insights"}


@pytest.mark.asyncio
async def test_extract_data_drops_below_credibility_floor(monkeypatch):
    """低可信度 data_point 被硬丢弃"""
    analyst = _make_analyst()
    state = create_initial_state("q", "sid")
    state["raw_sources"] = [
        {"url": "http://spam.example/x", "title": "t", "site_name": "自媒体",
         "date": "2020-01-01", "text": "随便一个数 1", "related_sections": ["sec_1"],
         "relevance_score": 0.4},
    ]

    async def fake_call_llm(*a, **k):
        return json.dumps({"data_points": [
            {"metric_key": "x", "name": "x", "value": 1, "unit": "", "year": 2020,
             "source_url": "http://spam.example/x", "confidence": 0.2}],
            "time_series": [], "distributions": [], "insights": []})

    monkeypatch.setattr(analyst, "call_llm", fake_call_llm)
    await analyst._extract_data(state)
    assert state["data_points"] == []


@pytest.mark.asyncio
async def test_extract_data_points_diff_returns_four_kinds(monkeypatch):
    """v3 入口 extract_data_points 的 diff 返回扩展到四类"""
    analyst = _make_analyst()
    state = create_initial_state("q", "sid")
    state["raw_sources"] = [
        {"url": "http://gov.cn/r1", "title": "t", "site_name": "统计局",
         "date": "2026-01-01", "text": "数据 100", "related_sections": ["sec_1"],
         "relevance_score": 0.9},
    ]

    async def fake_call_llm(*a, **k):
        return json.dumps({"data_points": [
            {"metric_key": "m", "name": "m", "value": 100, "unit": "", "year": 2026,
             "source_url": "http://gov.cn/r1", "confidence": 0.9}],
            "time_series": [{"id": "ts1"}], "distributions": [{"id": "d1"}],
            "insights": ["x"]})

    monkeypatch.setattr(analyst, "call_llm", fake_call_llm)
    diff = await analyst.extract_data_points(state)
    assert len(diff["data_points"]) == 1
    assert diff["time_series"] == [{"id": "ts1"}]
    assert diff["distributions"] == [{"id": "d1"}]
    assert diff["insights"] == ["x"]
