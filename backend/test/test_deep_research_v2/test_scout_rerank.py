from app.service.deep_research_v2.agents.scout import interleave_unique


def _r(u):
    return {"url": u, "title": u, "summary": u}


def test_round_robin_order():
    # 两个 query 的结果列表，轮转取：a1,b1,a2,b2...
    out = interleave_unique([[_r("a1"), _r("a2")], [_r("b1"), _r("b2")]], cap=10)
    assert [r["url"] for r in out] == ["a1", "b1", "a2", "b2"]


def test_dedup_by_url_across_lists():
    out = interleave_unique([[_r("x"), _r("y")], [_r("x"), _r("z")]], cap=10)
    assert [r["url"] for r in out] == ["x", "y", "z"]


def test_cap_truncates():
    lists = [[_r(f"a{i}") for i in range(40)], [_r(f"b{i}") for i in range(40)]]
    out = interleave_unique(lists, cap=50)
    assert len(out) == 50


def test_empty_input():
    assert interleave_unique([], cap=50) == []
    assert interleave_unique([[], []], cap=50) == []


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


def _fake_resp(results):
    class R:
        status_code = 200

        def json(self):
            return {"code": 200, "data": {"results": results}}
    return R()


@pytest.mark.asyncio
async def test_rerank_drops_below_threshold_and_sorts(scout, monkeypatch):
    docs = [_r("a"), _r("b"), _r("c")]
    # b 最相关、a 次之、c 低于 0.4 应被丢
    api_results = [
        {"index": 0, "relevance_score": 0.55},
        {"index": 1, "relevance_score": 0.91},
        {"index": 2, "relevance_score": 0.20},
    ]
    monkeypatch.setattr(
        "asyncio.to_thread", AsyncMock(return_value=_fake_resp(api_results))
    )
    out = await scout._rerank("query", docs, top_n=10)
    assert [r["url"] for r in out] == ["b", "a"]          # 排序 + 丢弃 c
    assert out[0]["relevance_score"] == 0.91


@pytest.mark.asyncio
async def test_rerank_top_n_limit(scout, monkeypatch):
    docs = [_r(f"d{i}") for i in range(5)]
    api_results = [{"index": i, "relevance_score": 0.9 - i * 0.05} for i in range(5)]
    monkeypatch.setattr(
        "asyncio.to_thread", AsyncMock(return_value=_fake_resp(api_results))
    )
    out = await scout._rerank("q", docs, top_n=3)
    assert len(out) == 3
    assert [r["url"] for r in out] == ["d0", "d1", "d2"]


@pytest.mark.asyncio
async def test_rerank_api_failure_falls_back(scout, monkeypatch):
    docs = [_r("a"), _r("b"), _r("c")]
    monkeypatch.setattr(
        "asyncio.to_thread", AsyncMock(side_effect=RuntimeError("boom"))
    )
    out = await scout._rerank("q", docs, top_n=2)
    # 降级：不 rerank，去重后取 top_n（原始顺序）
    assert [r["url"] for r in out] == ["a", "b"]


@pytest.mark.asyncio
async def test_rerank_dedup_before_call(scout, monkeypatch):
    docs = [_r("a"), _r("a"), _r("b")]
    captured = {}

    async def fake_to_thread(fn, *a, **k):
        captured["json"] = k.get("json")
        return _fake_resp([{"index": 0, "relevance_score": 0.8},
                           {"index": 1, "relevance_score": 0.7}])
    monkeypatch.setattr("asyncio.to_thread", AsyncMock(side_effect=fake_to_thread))
    out = await scout._rerank("q", docs, top_n=10)
    # 去重后只发 2 篇文档
    assert len(captured["json"]["documents"]) == 2
    assert len(out) == 2


@pytest.mark.asyncio
async def test_rerank_empty_returns_empty(scout):
    assert await scout._rerank("q", [], top_n=10) == []
