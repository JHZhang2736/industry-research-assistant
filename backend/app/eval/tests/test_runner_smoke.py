"""Test Runner end-to-end with mocked service + mocked judges."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.eval.runner import EvalRunner
from app.eval.types import CaseResult, EvalCase, StructuredJudgeResult


@pytest.fixture
def two_cases() -> list[EvalCase]:
    return [
        EvalCase(id="q001", query="测试 query 1", category="汽车", difficulty="easy"),
        EvalCase(id="q002", query="测试 query 2", category="汽车", difficulty="easy"),
    ]


@pytest.mark.asyncio
async def test_runner_executes_all_cases(tmp_path, two_cases, sample_state):
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

    fake_ensemble = MagicMock()

    extraction_json = json.dumps(
        {
            "requirements": [
                {"id": "r1", "text": "market", "importance": "high"},
            ],
            "claims": [
                {
                    "id": "c1",
                    "text": "2024 sales grew.",
                    "section_id": "s1",
                    "importance": "high",
                    "citation_ids": ["1"],
                    "requirement_ids": ["r1"],
                },
            ],
        }
    )
    verification_json = json.dumps(
        {
            "verdicts": [
                {
                    "claim_id": "c1",
                    "supported": True,
                    "reason": "supported",
                    "evidence_ids": ["f1"],
                    "confidence": "high",
                },
            ],
        }
    )
    quality_json = json.dumps(
        {
            dimension: {"score": 8, "reasoning": "solid"}
            for dimension in [
                "coherence",
                "cohesion_structure",
                "analytical_depth",
                "professionalism_readability",
                "decision_usefulness",
            ]
        }
    )

    async def fake_generate_structured(prompt, system_prompt=None):
        if "extract evaluation artifacts" in system_prompt:
            return StructuredJudgeResult("qwen", extraction_json)
        if "verify report claims" in system_prompt:
            return StructuredJudgeResult("qwen", verification_json)
        raise AssertionError(f"unexpected structured prompt: {system_prompt}")

    fake_ensemble.generate_structured = AsyncMock(side_effect=fake_generate_structured)
    fake_ensemble.generate_structured_all = AsyncMock(
        return_value=[
            StructuredJudgeResult("deepseek", quality_json),
            StructuredJudgeResult("qwen", quality_json),
            StructuredJudgeResult("kimi", quality_json),
        ]
    )

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
    saved_cases: list[CaseResult] = []
    runner.storage.save_case = MagicMock(side_effect=lambda run_id, cr: saved_cases.append(cr))

    summary = await runner.run("smoke", two_cases)
    assert summary["total"] == 2
    assert summary["ok"] == 2
    assert fake_ensemble.generate_structured.await_count == 4
    assert fake_ensemble.generate_structured_all.await_count == 2
    assert all(case_result.artifact is not None for case_result in saved_cases)

    # Verify markdown produced
    md_files = list(Path(out_dir).glob("*.md"))
    assert len(md_files) == 1
    md = md_files[0].read_text(encoding="utf-8")
    assert "claim_support_rate" in md
    assert "coherence" in md
    assert "decision_usefulness" in md

    csv_files = list(Path(out_dir).glob("*.csv"))
    assert len(csv_files) == 1
    csv = csv_files[0].read_text(encoding="utf-8")
    assert "claim_support_rate" in csv
    assert "coherence" in csv
    assert "decision_usefulness" in csv
