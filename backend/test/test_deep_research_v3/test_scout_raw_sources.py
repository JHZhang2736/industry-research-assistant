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


def _fake_search_factory():
    async def fake_execute_search(query, count=6):
        return [{"url": f"http://ex.com/{query}", "title": query, "summary": f"summary {query}",
                 "site_name": "Ex", "date": "2026-01-01", "relevance_score": 0.9}]
    return fake_execute_search


def _fake_analyze_factory():
    async def fake_analyze(original_query, search_query, results, search_type, hypotheses, state=None):
        # 注意：_compute_fact_fingerprint 用 numbers[:3] + CJK关键词[:5] 做指纹。
        # 纯 ASCII / 无数字的 content 会得到相同指纹 → 被误判重复而丢弃。
        # 这里给每个 query 注入一个唯一数字（ord 首字母），保证指纹互异。
        uniq = ord(search_query[0])  # a/b/c/d -> 97/98/99/100
        analysis = {
            "extracted_facts": [
                {"content": f"指标数值 {uniq} 来自查询", "source_url": f"http://ex.com/{search_query}",
                 "source_name": "Ex", "credibility_score": 0.9},
            ],
            "further_tracing_queries": [],
        }
        return analysis, results  # reranked = results
    return fake_analyze


@pytest.mark.asyncio
async def test_search_with_queries_concurrent_no_duplicate(monkeypatch):
    """两个 section 并发跑，返回的 facts/sources 无重复、总数正确（修复并发重复计数）"""
    scout = _make_scout()
    monkeypatch.setattr(scout, "_execute_search", _fake_search_factory())
    monkeypatch.setattr(scout, "_analyze_deep_search_results", _fake_analyze_factory())

    state = create_initial_state("q", "sid")
    res = await asyncio.gather(
        scout.search_with_queries("sec_1", ["a", "b"], state),
        scout.search_with_queries("sec_2", ["c", "d"], state),
    )
    facts = res[0]["facts"] + res[1]["facts"]
    fact_ids = [f["id"] for f in facts]
    assert len(fact_ids) == len(set(fact_ids)), "返回的 fact 不应重复"
    assert len(facts) == 4, "4 个 query 各 1 fact"

    sources = res[0]["sources"] + res[1]["sources"]
    urls = [s["url"] for s in sources]
    assert len(urls) == len(set(urls)), "返回的 source url 不应重复"
    assert len(sources) == 4


@pytest.mark.asyncio
async def test_raw_sources_written_with_relevance(monkeypatch):
    """raw_sources 被写入 state，带 relevance_score / related_sections / text"""
    scout = _make_scout()
    monkeypatch.setattr(scout, "_execute_search", _fake_search_factory())
    monkeypatch.setattr(scout, "_analyze_deep_search_results", _fake_analyze_factory())

    state = create_initial_state("q", "sid")
    await scout.search_with_queries("sec_1", ["a"], state)

    assert len(state["raw_sources"]) == 1
    src = state["raw_sources"][0]
    assert src["url"] == "http://ex.com/a"
    assert src["relevance_score"] == 0.9
    assert src["related_sections"] == ["sec_1"]
    assert src["text"] == "summary a"


@pytest.mark.asyncio
async def test_raw_sources_dedup_accumulates_related_sections(monkeypatch):
    """同一 url 跨章节出现时，raw_sources 去重且累加 related_sections"""
    scout = _make_scout()

    async def fixed_search(query, count=6):
        return [{"url": "http://same.com/x", "title": "T", "summary": "S",
                 "site_name": "Ex", "date": "2026-01-01", "relevance_score": 0.9}]

    async def fixed_analyze(oq, sq, results, st, hyp, state=None):
        uniq = ord(sq[0])  # 唯一数字避免 fact 指纹误判
        analysis = {
            "extracted_facts": [
                {"content": f"指标 {uniq} 数据", "source_url": "http://same.com/x",
                 "source_name": "Ex", "credibility_score": 0.9},
            ],
            "further_tracing_queries": [],
        }
        return analysis, results

    monkeypatch.setattr(scout, "_execute_search", fixed_search)
    monkeypatch.setattr(scout, "_analyze_deep_search_results", fixed_analyze)

    state = create_initial_state("q", "sid")
    await scout.search_with_queries("sec_1", ["a"], state)
    await scout.search_with_queries("sec_2", ["b"], state)

    assert len(state["raw_sources"]) == 1, "同 url 应去重为一条"
    assert state["raw_sources"][0]["related_sections"] == ["sec_1", "sec_2"]
