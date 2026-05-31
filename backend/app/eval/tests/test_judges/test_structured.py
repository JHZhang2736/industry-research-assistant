from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.judges.base import JudgeClient
from app.eval.judges.ensemble import EnsembleJudge
from app.eval.settings import JudgeConfig
from app.eval.types import StructuredJudgeResult
from app.eval.tests.conftest import make_openai_response


@pytest.fixture
def cfg() -> JudgeConfig:
    return JudgeConfig(
        name="testjudge",
        base_url="https://example.com/v1",
        model="test-model",
        api_key_env="NO_KEY",
        max_rate_per_min=100,
    )


@pytest.mark.asyncio
async def test_call_structured_returns_raw_content(cfg, monkeypatch):
    client = JudgeClient(cfg)
    fake_create = AsyncMock(return_value=make_openai_response('{"claims": []}'))
    client._client.chat.completions.create = fake_create

    result = await client.call_structured("prompt", system_prompt="system")

    assert result == StructuredJudgeResult(
        judge_name="testjudge",
        content='{"claims": []}',
        failed=False,
        error=None,
    )
    fake_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensemble_generate_structured_uses_primary_client():
    first = AsyncMock()
    second = AsyncMock()
    first.call_structured = AsyncMock(return_value=StructuredJudgeResult("a", '{"ok": true}'))
    second.call_structured = AsyncMock(return_value=StructuredJudgeResult("b", '{"ok": false}'))

    ensemble = EnsembleJudge([first, second])
    result = await ensemble.generate_structured("prompt", system_prompt="system")

    assert result.judge_name == "a"
    first.call_structured.assert_awaited_once()
    second.call_structured.assert_not_called()


@pytest.mark.asyncio
async def test_ensemble_generate_structured_all_calls_all_clients():
    first = AsyncMock()
    second = AsyncMock()
    first.call_structured = AsyncMock(return_value=StructuredJudgeResult("a", '{"score": 8}'))
    second.call_structured = AsyncMock(return_value=StructuredJudgeResult("b", '{"score": 7}'))

    ensemble = EnsembleJudge([first, second])
    results = await ensemble.generate_structured_all("prompt", system_prompt="system")

    assert [r.judge_name for r in results] == ["a", "b"]
