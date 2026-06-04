"""Test JudgeClient base behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

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


def test_parse_response_rejects_out_of_range_high():
    # JSON has score=99 (out of [0,10]); JSON path rejects it,
    # regex fallback finds no word-bounded 0-10 number in the raw text → ValueError.
    # Without the range check, the JSON path would have returned 99.0 silently.
    with pytest.raises(ValueError):
        parse_judge_response('{"score": 99, "reasoning": "x"}')


def test_parse_response_negative_score_falls_through_to_regex():
    # JSON has score=-1 (out of [0,10]); JSON path rejects it,
    # regex fallback finds "1" in the raw text → 1.0.
    out = parse_judge_response('{"score": -1, "reasoning": "x"}')
    assert out[0] == 1.0


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

    # Use an openai SDK exception type that the retry filter actually matches.
    fake_request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    client._client.chat.completions.create = AsyncMock(
        side_effect=APIConnectionError(message="boom", request=fake_request)
    )

    score = await client.call_judge("prompt")
    assert score.failed is True
    assert "boom" in (score.error or "")
    # tenacity should have retried JUDGE_RETRY_ATTEMPTS times
    assert client._client.chat.completions.create.await_count >= 2


def test_all_three_judge_builders_importable():
    from app.eval.judges.deepseek import build_deepseek_judge
    from app.eval.judges.mimo import build_mimo_judge
    from app.eval.judges.qwen import build_qwen_judge

    # Note: these will read env keys; api_key may be None in test env, OK
    for build in (build_deepseek_judge, build_mimo_judge, build_qwen_judge):
        client = build()
        assert client.cfg.name in {"deepseek", "mimo", "qwen"}
