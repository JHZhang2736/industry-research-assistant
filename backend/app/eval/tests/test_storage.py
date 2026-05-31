"""Test SQLite storage."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.eval.artifacts import AtomicClaim, ClaimVerdict, EvalArtifact, EvidenceItem
from app.eval.storage import EvalStorage
from app.eval.types import CaseResult, EvalCase, EvalResult


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_eval.db")


def test_storage_creates_schema(db_path: str):
    s = EvalStorage(db_path)
    s.init_schema()
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "eval_runs",
        "case_results",
        "evaluator_scores",
        "eval_artifacts",
        "claim_verdicts",
    }.issubset(tables)
    conn.close()


def test_storage_save_run_and_case(db_path: str):
    s = EvalStorage(db_path)
    s.init_schema()
    s.save_run_start(
        run_id="run-001",
        suite="full",
        started_at=datetime(2026, 5, 26, 14, 0),
        git_commit="abc123",
        config={"concurrency": 5},
    )

    cr = CaseResult(
        case=EvalCase(id="q001", query="new energy", category="auto", difficulty="easy"),
        results=[
            EvalResult(
                evaluator_name="relevance",
                score=8.0,
                raw_judge_outputs=[{"judge": "a", "score": 8}],
            ),
            EvalResult(
                evaluator_name="cost",
                score=0.34,
                metadata={"total_tokens": 12000},
            ),
        ],
        ok=True,
        state={"final_report": "...", "quality_score": 7.5},
        artifact=EvalArtifact(
            evidence=[
                EvidenceItem(
                    id="e1",
                    text="Battery costs fell in 2025.",
                    source_name="Industry Report",
                    source_url="https://example.com/report",
                    source_type="report",
                )
            ],
            claims=[
                AtomicClaim(
                    id="c1",
                    text="Battery costs fell in 2025.",
                    section_id="s1",
                    importance="high",
                    citation_ids=["cite-1"],
                    requirement_ids=["req-1"],
                )
            ],
            verdicts=[
                ClaimVerdict(
                    claim_id="c1",
                    supported=True,
                    reason="supported",
                    evidence_ids=["e1"],
                    confidence=None,
                )
            ],
        ),
        started_at=datetime(2026, 5, 26, 14, 1),
        finished_at=datetime(2026, 5, 26, 14, 4),
    )
    s.save_case(run_id="run-001", case_result=cr)

    s.save_run_end(run_id="run-001", finished_at=datetime(2026, 5, 26, 14, 5))

    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT case_id, query FROM case_results WHERE run_id='run-001'"))
    assert rows == [("q001", "new energy")]
    score_rows = list(conn.execute(
        "SELECT evaluator_name, score FROM evaluator_scores WHERE run_id='run-001' ORDER BY evaluator_name"
    ))
    assert score_rows == [("cost", 0.34), ("relevance", 8.0)]
    artifact_rows = list(conn.execute(
        "SELECT artifact_json FROM eval_artifacts WHERE run_id='run-001' AND case_id='q001'"
    ))
    assert len(artifact_rows) == 1
    artifact_payload = json.loads(artifact_rows[0][0])
    assert artifact_payload["claims"][0]["text"] == "Battery costs fell in 2025."
    verdict_rows = list(conn.execute(
        "SELECT claim_id, supported, reason FROM claim_verdicts "
        "WHERE run_id='run-001' AND case_id='q001'"
    ))
    assert verdict_rows == [("c1", 1, "supported")]
    conn.close()


def test_storage_save_idempotent(db_path: str):
    s = EvalStorage(db_path)
    s.init_schema()
    s.save_run_start("run-2", "full", datetime(2026, 5, 26), "abc", {})
    cr = CaseResult(
        case=EvalCase(id="q002", query="x", category="c", difficulty="easy"),
        results=[EvalResult(evaluator_name="cost", score=1.0)],
        artifact=EvalArtifact(
            claims=[
                AtomicClaim(
                    id="c1",
                    text="A claim.",
                    section_id="s1",
                    importance="medium",
                )
            ],
        ),
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    s.save_case("run-2", cr)
    s.save_case("run-2", cr)  # second insert should overwrite, not error
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM case_results WHERE run_id='run-2'").fetchone()[0]
    assert n == 1
    claim_n = conn.execute("SELECT COUNT(*) FROM claim_verdicts WHERE run_id='run-2'").fetchone()[0]
    assert claim_n == 1
    conn.close()


def test_storage_clears_claim_verdicts_when_artifact_removed(db_path: str):
    s = EvalStorage(db_path)
    s.init_schema()
    s.save_run_start("run-3", "full", datetime(2026, 5, 26), "abc", {})
    with_artifact = CaseResult(
        case=EvalCase(id="q003", query="x", category="c", difficulty="easy"),
        results=[EvalResult(evaluator_name="cost", score=1.0)],
        artifact=EvalArtifact(
            claims=[
                AtomicClaim(
                    id="c1",
                    text="A claim.",
                    section_id="s1",
                    importance="medium",
                )
            ],
        ),
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    without_artifact = CaseResult(
        case=EvalCase(id="q003", query="x", category="c", difficulty="easy"),
        results=[EvalResult(evaluator_name="cost", score=1.0)],
        artifact=None,
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )

    s.save_case("run-3", with_artifact)
    s.save_case("run-3", without_artifact)

    conn = sqlite3.connect(db_path)
    claim_n = conn.execute(
        "SELECT COUNT(*) FROM claim_verdicts WHERE run_id='run-3' AND case_id='q003'"
    ).fetchone()[0]
    assert claim_n == 0
    conn.close()
