"""Test JudgeClient base behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.eval.judges.base import JudgeClient, parse_judge_response
from app.eval.tests.conftest import make_openai_response
from app.eval.settings import JudgeConfig


@pytest.fixture
def cfg():
    return JudgeConfig(
        name="testjudge",
        base_url="https://example.com/v1",
        model="test-model",
        api_key_env="TEST_KEY",
        max_rate_per_min=100,
    )


def test_parse_response_clean_json():
    out = parse_judge_response('{"score": 8.0, "reasoning": "good"}')
    assert out == (8.0, "good")


def test_parse_response_with_markdown_fence():
    raw = '```json\n{"score": 7.5, "reasoning": "ok"}\n```'
    out = parse_judge_response(raw)
    assert out == (7.5, "ok")


def test_parse_response_fallback_regex_on_invalid_json():
    raw = "judge thinks score is 6 because reasons"
    out = parse_judge_response(raw)
    # regex fallback: first number 0-10
    assert out[0] == 6.0
    assert out[1] == raw


def test_parse_response_raises_when_no_number():
    with pytest.raises(ValueError):
        parse_judge_response("totally garbage text")


@pytest.mark.asyncio
async def test_call_judge_happy_path(cfg, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "fake-key")
    client = JudgeClient(cfg)

    fake = make_openai_response('{"score": 8.5, "reasoning": "great"}')
    client._client.chat.completions.create = AsyncMock(return_value=fake)

    score = await client.call_judge("prompt")
    assert score.judge_name == "testjudge"
    assert score.score == 8.5
    assert score.failed is False


@pytest.mark.asyncio
async def test_call_judge_parse_failure_marks_failed(cfg, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "fake-key")
    client = JudgeClient(cfg)

    fake = make_openai_response("complete garbage")
    client._client.chat.completions.create = AsyncMock(return_value=fake)

    score = await client.call_judge("prompt")
    assert score.failed is True
    assert score.error is not None


@pytest.mark.asyncio
async def test_call_judge_api_error_retried_then_fails(cfg, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "fake-key")
    client = JudgeClient(cfg)

    client._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    score = await client.call_judge("prompt")
    assert score.failed is True
    assert "boom" in (score.error or "")
    # tenacity should have retried JUDGE_RETRY_ATTEMPTS times
    assert client._client.chat.completions.create.await_count >= 2
