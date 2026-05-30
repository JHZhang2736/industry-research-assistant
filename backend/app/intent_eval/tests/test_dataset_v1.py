"""V1 数据集的分布与 schema 自检 —— 改数据集时立即捕捉漂移。"""
from pathlib import Path
from collections import Counter
from app.intent_eval.dataset import load

DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "intent_eval_v1.jsonl"


def test_total_count_is_80():
    cases = load(DATASET_PATH)
    assert len(cases) == 80


def test_intent_distribution():
    cases = load(DATASET_PATH)
    intent_counts = Counter(c.true_intent for c in cases)
    assert intent_counts == {
        "deep_research": 20,
        "web_search": 20,
        "simple_qa": 20,
        "out_of_scope": 20,
    }


def test_research_type_distribution():
    cases = load(DATASET_PATH)
    rt_counts = Counter(c.true_research_type for c in cases if c.true_research_type is not None)
    assert rt_counts == {
        "industry_analysis": 7,
        "company_research": 7,
        "comparative_analysis": 6,
    }


def test_boundary_count_per_intent():
    cases = load(DATASET_PATH)
    boundary_counts = Counter(c.true_intent for c in cases if c.is_boundary)
    assert boundary_counts == {
        "deep_research": 4,
        "web_search": 4,
        "simple_qa": 4,
        "out_of_scope": 4,
    }


def test_ids_are_sequential():
    cases = load(DATASET_PATH)
    ids = [c.id for c in cases]
    expected = [f"intent-{i:03d}" for i in range(1, 81)]
    assert sorted(ids) == sorted(expected)


def test_query_length_range():
    cases = load(DATASET_PATH)
    lengths = [len(c.query) for c in cases]
    assert min(lengths) >= 4
    assert max(lengths) <= 80


def test_id_block_maps_to_intent():
    """编号区段必须对应固定意图，防止未来误把某条换进错误区段。"""
    by_id = {c.id: c for c in load(DATASET_PATH)}
    blocks = {
        "deep_research": range(1, 21),
        "web_search": range(21, 41),
        "simple_qa": range(41, 61),
        "out_of_scope": range(61, 81),
    }
    for intent, rng in blocks.items():
        for i in rng:
            assert by_id[f"intent-{i:03d}"].true_intent == intent


def test_non_deep_research_research_type_is_null():
    """非 deep_research 行的 true_research_type 必须为 None。"""
    for c in load(DATASET_PATH):
        if c.true_intent != "deep_research":
            assert c.true_research_type is None
