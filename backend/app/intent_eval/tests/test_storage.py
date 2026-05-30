"""SQLite 持久化单测：写一个 run + cases，读回来字段一致。"""
import sqlite3
from app.intent_eval.storage import Storage
from app.intent_eval.types import (
    EvalCase, CaseResult, PerClassMetrics, LevelMetrics, RunSummary,
)


def _sample_summary(run_id: str = "run-001") -> RunSummary:
    pc1 = {c: PerClassMetrics(1.0, 1.0, 1.0, 5) for c in
           ["deep_research", "web_search", "simple_qa", "out_of_scope"]}
    cm1 = {c: {} for c in pc1}
    pc2 = {c: PerClassMetrics(1.0, 1.0, 1.0, 5) for c in
           ["industry_analysis", "company_research", "comparative_analysis"]}
    cm2 = {c: {} for c in pc2}
    return RunSummary(
        run_id=run_id,
        started_at="2026-05-30T14:00:00",
        finished_at="2026-05-30T14:02:00",
        git_commit="abc1234",
        dataset_version="v1",
        level1_model="qwen-turbo",
        level2_model="qwen-turbo",
        concurrency=10,
        duration_sec=120.0,
        level1=LevelMetrics(accuracy=0.95, macro_f1=0.94, per_class=pc1, confusion=cm1, n=80),
        level2=LevelMetrics(accuracy=0.9, macro_f1=0.89, per_class=pc2, confusion=cm2, n=20),
    )


def _sample_case_result(case_id: str = "intent-001") -> CaseResult:
    case = EvalCase(id=case_id, query="q", true_intent="simple_qa",
                    true_research_type=None, subtype="", is_boundary=False)
    return CaseResult(
        case=case, predicted_intent="simple_qa", predicted_research_type=None,
        intent_confidence=1.0, research_type_confidence=None,
        intent_raw={"name": "simple_qa"}, research_type_raw=None,
        latency_ms=512, error=None,
    )


def test_storage_creates_schema(tmp_path):
    db = tmp_path / "test.db"
    Storage(db).init_schema()
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"runs", "case_results"}
    conn.close()


def test_storage_wal_mode_enabled(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(db)
    s.init_schema()
    with s._conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_save_run_roundtrip(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(db)
    s.init_schema()
    summary = _sample_summary()
    cr = _sample_case_result()
    s.save_run(summary, [cr])
    conn = sqlite3.connect(db)
    runs = conn.execute("SELECT run_id, level1_accuracy, level2_macro_f1 FROM runs").fetchall()
    assert runs == [("run-001", 0.95, 0.89)]
    cases = conn.execute(
        "SELECT case_id, true_intent, predicted_intent, intent_correct FROM case_results"
    ).fetchall()
    assert cases == [("intent-001", "simple_qa", "simple_qa", 1)]
    conn.close()


def test_save_multiple_runs_independent(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(db)
    s.init_schema()
    s.save_run(_sample_summary("run-001"), [_sample_case_result("intent-001")])
    s.save_run(_sample_summary("run-002"), [_sample_case_result("intent-001")])
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert n == 2
    n_cases = conn.execute("SELECT COUNT(*) FROM case_results").fetchone()[0]
    assert n_cases == 2
    conn.close()


def test_init_schema_idempotent(tmp_path):
    db = tmp_path / "test.db"
    Storage(db).init_schema()
    Storage(db).init_schema()   # 二次调用不报错
