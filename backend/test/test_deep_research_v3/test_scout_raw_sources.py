"""DeepScout: raw_sources 写入 + 并发 diff + 停止抽数 测试"""
import asyncio
import pytest

from app.service.deep_research_v2.agents.scout import DeepScout
from app.service.deep_research_v2.state import create_initial_state


def _make_scout():
    return DeepScout(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
        model="qwen-plus",
    )


def test_ingest_facts_returns_appended_objects():
    """_ingest_facts 返回它实际 append 的 fact 对象列表（不再是 count）"""
    scout = _make_scout()
    state = create_initial_state("q", "sid")
    analysis = {
        "extracted_facts": [
            {"content": "中国新能源汽车市场规模突破万亿", "source_url": "http://a.com", "source_name": "A",
             "credibility_score": 0.9},
            {"content": "半导体芯片自给率已达到35%", "source_url": "http://b.com", "source_name": "B",
             "credibility_score": 0.9},
        ]
    }
    added = scout._ingest_facts(state, analysis, "sec_1", "q", "follow_up", 1,
                                {"http://a.com": "2026-01-01", "http://b.com": "2026-01-01"})
    assert isinstance(added, list)
    assert len(added) == 2
    assert {f["content"] for f in added} == {"中国新能源汽车市场规模突破万亿", "半导体芯片自给率已达到35%"}
    # 仍 in-place 写 state（机制 1 保留）
    assert state["facts"] == added


def test_ingest_facts_still_mutates_hypotheses():
    """守护点 A：保留对 state['hypotheses'] 的就地写"""
    scout = _make_scout()
    state = create_initial_state("q", "sid")
    state["hypotheses"] = [{"id": "h_1", "content": "假设1", "status": "unverified",
                            "evidence_for": [], "evidence_against": []}]
    analysis = {
        "extracted_facts": [
            {"content": "支持证据", "source_url": "http://a.com", "source_name": "A",
             "credibility_score": 0.9, "related_hypothesis": "h_1",
             "hypothesis_support": "supports"},
        ]
    }
    scout._ingest_facts(state, analysis, "sec_1", "q", "follow_up", 1,
                        {"http://a.com": "2026-01-01"})
    assert state["hypotheses"][0]["evidence_for"] == ["支持证据"]


def test_scout_no_longer_emits_data_points():
    """Scout 不再从 analysis 抽 data_point（DataAnalyst 接管）"""
    scout = _make_scout()
    state = create_initial_state("q", "sid")
    analysis = {
        "extracted_facts": [
            {"content": "事实", "source_url": "http://a.com", "source_name": "A",
             "credibility_score": 0.9},
        ],
        "data_points": [{"name": "市场规模", "value": "5000", "unit": "亿元", "year": 2024}],
    }
    scout._ingest_facts(state, analysis, "sec_1", "q", "follow_up", 1,
                        {"http://a.com": "2026-01-01"})
    assert state["data_points"] == []
