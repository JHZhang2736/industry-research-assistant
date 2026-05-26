"""SQLite storage for eval runs."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.eval.types import CaseResult

logger = logging.getLogger("eval.storage")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    suite TEXT,
    started_at TEXT,
    finished_at TEXT,
    git_commit TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS case_results (
    run_id TEXT,
    case_id TEXT,
    query TEXT,
    final_report TEXT,
    quality_score REAL,
    duration_sec REAL,
    total_tokens INTEGER,
    cost_rmb REAL,
    error TEXT,
    PRIMARY KEY (run_id, case_id)
);

CREATE TABLE IF NOT EXISTS evaluator_scores (
    run_id TEXT,
    case_id TEXT,
    evaluator_name TEXT,
    score REAL,
    raw_judge_outputs_json TEXT,
    std REAL,
    low_confidence INTEGER,
    metadata_json TEXT,
    PRIMARY KEY (run_id, case_id, evaluator_name)
);
"""


class EvalStorage:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def save_run_start(
        self,
        run_id: str,
        suite: str,
        started_at: datetime,
        git_commit: str,
        config: dict[str, Any],
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO eval_runs (run_id, suite, started_at, git_commit, config_json) VALUES (?, ?, ?, ?, ?)",
                (run_id, suite, started_at.isoformat(), git_commit, json.dumps(config, ensure_ascii=False)),
            )

    def save_run_end(self, run_id: str, finished_at: datetime) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE eval_runs SET finished_at=? WHERE run_id=?",
                (finished_at.isoformat(), run_id),
            )

    def save_case(self, run_id: str, case_result: CaseResult) -> None:
        c_id = case_result.case.id
        state = case_result.state or {}
        # Find cost/latency from results
        cost = next((r.score for r in case_result.results if r.evaluator_name == "cost"), None)
        latency = next((r.score for r in case_result.results if r.evaluator_name == "latency"), None)
        total_tokens = next(
            (r.metadata.get("total_tokens") for r in case_result.results if r.evaluator_name == "cost"),
            None,
        )

        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO case_results "
                "(run_id, case_id, query, final_report, quality_score, duration_sec, total_tokens, cost_rmb, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, c_id, case_result.case.query,
                    state.get("final_report"),
                    state.get("quality_score"),
                    latency,
                    total_tokens,
                    cost,
                    case_result.error,
                ),
            )
            # Wipe + reinsert evaluator rows (idempotent)
            c.execute(
                "DELETE FROM evaluator_scores WHERE run_id=? AND case_id=?",
                (run_id, c_id),
            )
            for r in case_result.results:
                c.execute(
                    "INSERT INTO evaluator_scores "
                    "(run_id, case_id, evaluator_name, score, raw_judge_outputs_json, std, low_confidence, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id, c_id, r.evaluator_name, r.score,
                        json.dumps(r.raw_judge_outputs, ensure_ascii=False),
                        r.metadata.get("std"),
                        1 if r.low_confidence else 0,
                        json.dumps(r.metadata, ensure_ascii=False),
                    ),
                )
