from app.service.deep_research_v2.agents.writer import sort_facts_by_quality


def test_sort_by_credibility_desc():
    facts = [
        {"content": "a", "credibility_score": 0.4, "importance": "low"},
        {"content": "b", "credibility_score": 0.9, "importance": "medium"},
        {"content": "c", "credibility_score": 0.7, "importance": "high"},
    ]
    out = sort_facts_by_quality(facts)
    assert [f["content"] for f in out] == ["b", "c", "a"]


def test_importance_breaks_tie():
    facts = [
        {"content": "a", "credibility_score": 0.8, "importance": "low"},
        {"content": "b", "credibility_score": 0.8, "importance": "high"},
    ]
    out = sort_facts_by_quality(facts)
    assert [f["content"] for f in out] == ["b", "a"]


def test_missing_fields_default():
    facts = [{"content": "a"}, {"content": "b", "credibility_score": 0.9}]
    out = sort_facts_by_quality(facts)
    assert out[0]["content"] == "b"
