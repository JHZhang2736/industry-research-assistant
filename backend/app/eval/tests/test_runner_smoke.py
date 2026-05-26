"""Test Runner end-to-end with mocked service + mocked judges."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.eval.runner import EvalRunner
from app.eval.types import EvalCase


@pytest.fixture
def two_cases() -> list[EvalCase]:
    return [
        EvalCase(id="q001", query="测试 query 1", category="汽车", difficulty="easy"),
        EvalCase(id="q002", query="测试 query 2", category="汽车", difficulty="easy"),
    ]


@pytest.mark.asyncio
async def test_runner_executes_all_cases(tmp_path, two_cases, sample_state, monkeypatch):
    """Mock service.research + checkpoint read + all judges."""
    db_path = str(tmp_path / "eval.db")
    out_dir = str(tmp_path / "results")

    # Patch service factory
    fake_service = MagicMock()

    async def fake_research(query, session_id, **kwargs):
        yield "data: {\"type\": \"phase\"}\n\n"
        yield "data: [DONE]\n\n"

    fake_service.research = fake_research

    # Patch checkpoint read to return sample_state
    async def fake_load_state(session_id):
        return sample_state

    # Patch EnsembleJudge.score
    from app.eval.types import EnsembleResult, JudgeScore
    fake_ensemble_result = EnsembleResult(
        mean_score=7.5, median_score=7.5, std=0.5,
        individual=[JudgeScore("a", 7.5, ""), JudgeScore("b", 7.5, ""), JudgeScore("c", 7.5, "")],
        low_confidence=False, partial=False,
    )

    fake_ensemble = MagicMock()
    fake_ensemble.score = AsyncMock(return_value=fake_ensemble_result)

    runner = EvalRunner(
        service=fake_service,
        load_final_state=fake_load_state,
        judge=fake_ensemble,
        db_path=db_path,
        out_dir=out_dir,
        concurrency=2,
        git_commit="testsha",
        langsmith_project="test",
    )

    summary = await runner.run("smoke", two_cases)
    assert summary["total"] == 2
    assert summary["ok"] == 2

    # Verify markdown produced
    md_files = list(Path(out_dir).glob("*.md"))
    assert len(md_files) == 1
