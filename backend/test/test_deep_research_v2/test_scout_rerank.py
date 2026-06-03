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
