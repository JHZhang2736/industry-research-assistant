"""Markdown 报表生成测试。"""
from pathlib import Path
from app.intent_eval.reporter import write_markdown, _escape_pipe
from app.intent_eval.types import (
    EvalCase, CaseResult, PerClassMetrics, LevelMetrics, RunSummary, ERROR_LABEL,
)
from app.intent_eval.metrics import compute_level_metrics


def _make_summary_and_results():
    cases = [
        EvalCase(id="intent-001", query="什么是 PE", true_intent="simple_qa",
                 true_research_type=None, subtype="术语定义", is_boundary=False),
        EvalCase(id="intent-002", query="茅台 | 五粮液 对比", true_intent="deep_research",
                 true_research_type="comparative_analysis", subtype="对比", is_boundary=True),
        EvalCase(id="intent-003", query="新能源行业现状", true_intent="deep_research",
                 true_research_type="industry_analysis", subtype="行业", is_boundary=False),
    ]
    results = [
        CaseResult(case=cases[0], predicted_intent="simple_qa", predicted_research_type=None,
                   intent_confidence=1.0, research_type_confidence=None,
                   intent_raw={}, research_type_raw=None, latency_ms=100, error=None),
        CaseResult(case=cases[1], predicted_intent="deep_research",
                   predicted_research_type="industry_analysis",
                   intent_confidence=1.0, research_type_confidence=1.0,
                   intent_raw={}, research_type_raw={}, latency_ms=200, error=None),
        CaseResult(case=cases[2], predicted_intent="deep_research",
                   predicted_research_type="industry_analysis",
                   intent_confidence=1.0, research_type_confidence=1.0,
                   intent_raw={}, research_type_raw={}, latency_ms=300, error=None),
    ]
    l1 = compute_level_metrics(
        [c.true_intent for c in cases],
        [r.predicted_intent for r in results],
        ["deep_research", "web_search", "simple_qa", "out_of_scope"],
    )
    l2_pairs = [(c.true_research_type, r.predicted_research_type)
                for c, r in zip(cases, results) if c.true_research_type]
    l2 = compute_level_metrics(
        [t for t, _ in l2_pairs], [p for _, p in l2_pairs],
        ["industry_analysis", "company_research", "comparative_analysis"],
    )
    summary = RunSummary(
        run_id="run-test",
        started_at="2026-05-30T14:00:00", finished_at="2026-05-30T14:02:00",
        git_commit="abc1234", dataset_version="v1",
        level1_model="qwen-turbo", level2_model="qwen-turbo",
        concurrency=10, duration_sec=120.0,
        level1=l1, level2=l2,
    )
    return summary, results


def test_escape_pipe():
    assert _escape_pipe("a|b") == "a\\|b"
    assert _escape_pipe("no pipe") == "no pipe"


def test_write_markdown_creates_file(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    assert out.exists()
    assert out.suffix == ".md"


def test_filename_format(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    # 文件名包含 finished_at 时间戳与 git_commit short sha
    assert "abc1234" in out.name
    # finished_at 里的冒号必须被替换，避免 Windows 非法文件名
    assert ":" not in out.name


def test_report_contains_required_sections(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    md = out.read_text(encoding="utf-8")
    assert "# Intent Eval Report" in md
    assert "Level 1: Intent Classification" in md
    assert "Level 2: Research Type Classification" in md
    assert "Confusion Matrix" in md
    assert "Badcases" in md
    assert "Run Metadata" in md


def test_report_escapes_pipe_in_query(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    md = out.read_text(encoding="utf-8")
    # badcase 表里 intent-002 query 含 |，必须转义
    assert "茅台 \\| 五粮液 对比" in md


def test_boundary_badcases_first(tmp_path):
    """is_boundary=true 的 badcase 应排在非 boundary 之前。"""
    summary, results = _make_summary_and_results()
    # 把 intent-001 改成预测错的非 boundary case
    results[0] = CaseResult(
        case=results[0].case, predicted_intent="web_search",
        predicted_research_type=None, intent_confidence=1.0,
        research_type_confidence=None, intent_raw={}, research_type_raw=None,
        latency_ms=100, error=None,
    )
    # intent-002 也错（是 boundary）
    results[1] = CaseResult(
        case=results[1].case, predicted_intent="simple_qa",
        predicted_research_type=None, intent_confidence=1.0,
        research_type_confidence=None, intent_raw={}, research_type_raw=None,
        latency_ms=200, error=None,
    )
    out = write_markdown(summary, results, output_dir=tmp_path)
    md = out.read_text(encoding="utf-8")
    idx_002 = md.find("intent-002")
    idx_001 = md.find("intent-001")
    assert 0 <= idx_002 < idx_001
