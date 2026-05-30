"""SQLite 持久化：2 表 + WAL mode + busy_timeout 5s。"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from app.intent_eval.types import CaseResult, RunSummary


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    git_commit      TEXT,
    dataset_version TEXT NOT NULL,
    level1_model    TEXT NOT NULL,
    level2_model    TEXT NOT NULL,
    concurrency     INTEGER NOT NULL,
    duration_sec    REAL NOT NULL,
    level1_n        INTEGER NOT NULL,
    level2_n        INTEGER NOT NULL,
    level1_accuracy REAL NOT NULL,
    level2_accuracy REAL NOT NULL,
    level1_macro_f1 REAL NOT NULL,
    level2_macro_f1 REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS case_results (
    run_id                  TEXT NOT NULL,
    case_id                 TEXT NOT NULL,
    query                   TEXT NOT NULL,
    true_intent             TEXT NOT NULL,
    predicted_intent        TEXT,
    intent_correct          INTEGER NOT NULL,
    true_research_type      TEXT,
    predicted_research_type TEXT,
    research_type_correct   INTEGER,
    raw_response_json       TEXT,
    latency_ms              INTEGER NOT NULL,
    error                   TEXT,
    PRIMARY KEY (run_id, case_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_case_results_run_id ON case_results(run_id);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def save_run(self, summary: RunSummary, case_results: list[CaseResult]) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO runs (
                    run_id, started_at, finished_at, git_commit, dataset_version,
                    level1_model, level2_model, concurrency, duration_sec,
                    level1_n, level2_n, level1_accuracy, level2_accuracy,
                    level1_macro_f1, level2_macro_f1
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    summary.run_id, summary.started_at, summary.finished_at,
                    summary.git_commit, summary.dataset_version,
                    summary.level1_model, summary.level2_model,
                    summary.concurrency, summary.duration_sec,
                    summary.level1.n, summary.level2.n,
                    summary.level1.accuracy, summary.level2.accuracy,
                    summary.level1.macro_f1, summary.level2.macro_f1,
                ),
            )
            rows = []
            for cr in case_results:
                raw = {
                    "intent": cr.intent_raw,
                    "research_type": cr.research_type_raw,
                }
                rt_correct = (
                    None if cr.research_type_correct is None
                    else int(cr.research_type_correct)
                )
                rows.append((
                    summary.run_id, cr.case.id, cr.case.query,
                    cr.case.true_intent, cr.predicted_intent,
                    int(cr.intent_correct),
                    cr.case.true_research_type, cr.predicted_research_type,
                    rt_correct,
                    json.dumps(raw, ensure_ascii=False),
                    cr.latency_ms, cr.error,
                ))
            conn.executemany(
                """INSERT INTO case_results (
                    run_id, case_id, query, true_intent, predicted_intent, intent_correct,
                    true_research_type, predicted_research_type, research_type_correct,
                    raw_response_json, latency_ms, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
