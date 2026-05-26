"""Shared pytest fixtures for eval tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_state() -> dict:
    """A real ResearchState snapshot. Created on first test, then committed."""
    path = FIXTURES / "sample_state.json"
    if not path.exists():
        # Minimal fallback state so tests can run before Task 22 generates real one
        return {
            "query": "新能源汽车2024年市场现状",
            "session_id": "test-001",
            "phase": "completed",
            "iteration": 1,
            "outline": [
                {"id": "s1", "title": "市场规模", "description": "..."},
                {"id": "s2", "title": "竞争格局", "description": "..."},
            ],
            "facts": [
                {"id": "f1", "content": "2024 年销量 950 万辆",
                 "source_url": "https://example.com/a", "source_name": "中汽协"},
            ],
            "references": [
                {"id": "r1", "url": "https://example.com/a", "title": "中汽协报告"},
            ],
            "draft_sections": {"s1": "...", "s2": "..."},
            "final_report": "# 报告\n\n## 市场规模\n2024 年销量 [1]。\n\n## 竞争格局\n...",
            "critic_feedback": [
                {"id": "c1", "issue_type": "missing_source", "severity": "minor",
                 "description": "...", "resolved": True},
                {"id": "c2", "issue_type": "logic_error", "severity": "major",
                 "description": "...", "resolved": False},
            ],
            "quality_score": 7.5,
            "logs": [
                {"agent": "architect", "tokens_used": 1200, "duration_ms": 5000,
                 "model": "qwen-max"},
                {"agent": "scout", "tokens_used": 3400, "duration_ms": 20000,
                 "model": "qwen-plus"},
                {"agent": "writer", "tokens_used": 8000, "duration_ms": 30000,
                 "model": "deepseek-v3.2"},
            ],
            "errors": [],
            "messages": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def make_openai_response(content: str) -> Any:
    """Build a fake openai response with given content."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = MagicMock()
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    return resp
