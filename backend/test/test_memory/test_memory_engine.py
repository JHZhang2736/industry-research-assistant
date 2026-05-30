from unittest.mock import MagicMock
import pytest
from app.service.memory_engine import MemoryEngine


def _make_engine_with_mock_mem():
    """构造一个注入了 mock mem0 client 的 MemoryEngine（绕过真实初始化）。"""
    engine = MemoryEngine.__new__(MemoryEngine)  # 不走 __init__
    engine._mem = MagicMock()
    return engine


def test_remember_preferences_calls_mem_add():
    engine = _make_engine_with_mock_mem()
    msgs = [{"role": "user", "content": "报告要简洁"}]
    engine.remember_preferences("u1", msgs)
    engine._mem.add.assert_called_once()
    kwargs = engine._mem.add.call_args.kwargs
    assert kwargs["user_id"] == "u1"
    assert kwargs["metadata"] == {"type": "preference"}


def test_remember_preferences_swallows_errors():
    engine = _make_engine_with_mock_mem()
    engine._mem.add.side_effect = RuntimeError("mem0 down")
    engine.remember_preferences("u1", [{"role": "user", "content": "x"}])


def test_recall_preferences_formats_context():
    engine = _make_engine_with_mock_mem()
    engine._mem.search.return_value = {
        "results": [
            {"memory": "用户只关注智慧交通", "metadata": {"type": "preference"}},
            {"memory": "报告要简洁", "metadata": {"type": "preference"}},
        ]
    }
    ctx = engine.recall_preferences("u1", "写一份报告")
    assert "[用户偏好]" in ctx
    assert "用户只关注智慧交通" in ctx
    assert "报告要简洁" in ctx


def test_recall_preferences_handles_list_shape():
    engine = _make_engine_with_mock_mem()
    engine._mem.search.return_value = [{"memory": "偏好A", "metadata": {"type": "preference"}}]
    ctx = engine.recall_preferences("u1", "q")
    assert "偏好A" in ctx


def test_recall_preferences_empty_returns_blank():
    engine = _make_engine_with_mock_mem()
    engine._mem.search.return_value = {"results": []}
    assert engine.recall_preferences("u1", "q") == ""


def test_recall_preferences_swallows_errors():
    engine = _make_engine_with_mock_mem()
    engine._mem.search.side_effect = RuntimeError("boom")
    assert engine.recall_preferences("u1", "q") == ""
