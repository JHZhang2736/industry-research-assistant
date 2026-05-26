"""Test LangSmithAdapter — only the fail-open behavior. No real network."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.eval.langsmith_adapter import LangSmithAdapter
from app.eval.types import CaseResult, EvalCase, EvalResult


def test_adapter_disabled_when_no_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    a = LangSmithAdapter(project="test")
    assert a.enabled is False
    # upload is a no-op
    a.upload_case_sync(
        run_id="r1",
        case_result=CaseResult(
            case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
            results=[],
            started_at=datetime(2026, 5, 26),
            finished_at=datetime(2026, 5, 26),
        ),
    )


def test_adapter_swallows_exceptions(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake")
    a = LangSmithAdapter(project="test")
    a._client = MagicMock()
    a._client.create_run.side_effect = RuntimeError("network down")

    # Should NOT raise
    a.upload_case_sync(
        run_id="r1",
        case_result=CaseResult(
            case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
            results=[EvalResult(evaluator_name="cost", score=1.0)],
            started_at=datetime(2026, 5, 26),
            finished_at=datetime(2026, 5, 26),
        ),
    )
