"""Dataset 加载与 schema 校验测试。"""
import json
import pytest
from pathlib import Path
from app.intent_eval.dataset import load, DatasetError


def _write_jsonl(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "ds.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def test_load_valid(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q1", "true_intent": "simple_qa",
         "true_research_type": None, "subtype": "x", "is_boundary": False},
        {"id": "intent-002", "query": "q2", "true_intent": "deep_research",
         "true_research_type": "industry_analysis", "subtype": "y", "is_boundary": True},
    ])
    cases = load(p)
    assert len(cases) == 2
    assert cases[0].true_intent == "simple_qa"
    assert cases[0].true_research_type is None
    assert cases[1].true_research_type == "industry_analysis"
    assert cases[1].is_boundary is True


def test_load_invalid_intent_enum(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "nonsense",
         "true_research_type": None, "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="invalid true_intent"):
        load(p)


def test_load_invalid_research_type_enum(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "deep_research",
         "true_research_type": "wrong_type", "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="invalid true_research_type"):
        load(p)


def test_load_research_type_missing_on_deep_research(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "deep_research",
         "true_research_type": None, "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="true_research_type required"):
        load(p)


def test_load_research_type_set_on_non_deep_research(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "simple_qa",
         "true_research_type": "industry_analysis", "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="true_research_type must be null"):
        load(p)


def test_load_missing_field(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "simple_qa"},
    ])
    with pytest.raises(DatasetError, match="missing field"):
        load(p)


def test_load_duplicate_id(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q1", "true_intent": "simple_qa",
         "true_research_type": None, "subtype": "", "is_boundary": False},
        {"id": "intent-001", "query": "q2", "true_intent": "simple_qa",
         "true_research_type": None, "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="duplicate id"):
        load(p)


def test_load_file_not_found(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load(tmp_path / "missing.jsonl")


def test_load_invalid_json(tmp_path):
    p = tmp_path / "ds.jsonl"
    p.write_text("{not valid json}\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="invalid JSON"):
        load(p)
