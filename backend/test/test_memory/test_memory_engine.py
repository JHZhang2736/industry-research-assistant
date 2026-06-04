from unittest.mock import MagicMock
from app.service.memory_engine import MemoryEngine


def _make_engine_with_mock_mem():
    """构造一个注入了 mock mem0 client 的 MemoryEngine（绕过真实初始化）。"""
    engine = MemoryEngine.__new__(MemoryEngine)  # 不走 __init__
    engine._mem = MagicMock()
    return engine


def test_build_config_uses_milvus_host_and_port_when_uri_is_missing(monkeypatch):
    monkeypatch.delenv("MILVUS_URI", raising=False)
    monkeypatch.setenv("MILVUS_HOST", "milvus-standalone")
    monkeypatch.setenv("MILVUS_PORT", "19530")

    cfg = MemoryEngine._build_config()

    assert cfg["vector_store"]["config"]["url"] == "http://milvus-standalone:19530"


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
    # 锁定 mem0 2.0.4 真实 search API：filters/top_k（不是 user_id/limit）
    engine._mem.search.assert_called_once_with("写一份报告", filters={"user_id": "u1"}, top_k=5)


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


def _critic_feedback_sample():
    return [
        {"issue_type": "missing_source", "severity": "critical",
         "description": "渗透率数据无官方来源", "suggestion": "补充国家统计局口径"},
        {"issue_type": "outdated", "severity": "minor",
         "description": "引用了2019年数据", "suggestion": "更新到最近年份"},
    ]


def test_remember_lessons_adds_per_feedback():
    engine = _make_engine_with_mock_mem()
    engine.remember_lessons("智慧交通", _critic_feedback_sample(), quality_score=6.0)
    assert engine._mem.add.call_count == 2
    kwargs = engine._mem.add.call_args_list[0].kwargs
    assert kwargs["user_id"] == "sop::智慧交通"
    assert kwargs["metadata"]["type"] == "sop"
    assert kwargs["metadata"]["issue_type"] == "missing_source"
    # 教训需原样存储：infer=False（否则 mem0 LLM 抽取会判"无事实可记"而丢弃）
    assert kwargs["infer"] is False


def test_remember_lessons_skips_when_empty():
    engine = _make_engine_with_mock_mem()
    engine.remember_lessons("智慧交通", [], quality_score=9.0)
    engine._mem.add.assert_not_called()


def test_remember_lessons_swallows_errors():
    engine = _make_engine_with_mock_mem()
    engine._mem.add.side_effect = RuntimeError("down")
    engine.remember_lessons("智慧交通", _critic_feedback_sample(), 5.0)


def test_recall_lessons_filters_by_type_and_recurrence():
    engine = _make_engine_with_mock_mem()
    engine._mem.search.return_value = {
        "results": [
            {"memory": "政策类结论必须引用原文", "metadata": {"type": "sop"}, "score": 0.9},
            {"memory": "渗透率必须标注口径", "metadata": {"type": "sop"}, "score": 0.8},
            {"memory": "无关偏好", "metadata": {"type": "preference"}, "score": 0.7},
        ]
    }
    ctx = engine.recall_lessons("智慧交通", "市场规模", k=5, min_recurrence=1)
    assert "[过往研究教训" in ctx
    assert "政策类结论必须引用原文" in ctx
    assert "无关偏好" not in ctx


def test_recall_lessons_empty_returns_blank():
    engine = _make_engine_with_mock_mem()
    engine._mem.search.return_value = {"results": []}
    assert engine.recall_lessons("智慧交通", "q") == ""


def test_list_memories_returns_normalized():
    engine = _make_engine_with_mock_mem()
    engine._mem.get_all.return_value = {
        "results": [
            {"id": "m1", "memory": "偏好A", "metadata": {"type": "preference"}},
        ]
    }
    out = engine.list_memories("u1")
    assert out == [{"id": "m1", "content": "偏好A", "type": "preference"}]
    # 锁定 mem0 2.0.4 真实 get_all API：filters（不是 user_id）
    engine._mem.get_all.assert_called_once_with(filters={"user_id": "u1"})


def test_list_memories_swallows_errors():
    engine = _make_engine_with_mock_mem()
    engine._mem.get_all.side_effect = RuntimeError("down")
    assert engine.list_memories("u1") == []


def test_delete_memory_calls_mem():
    engine = _make_engine_with_mock_mem()
    engine.delete_memory("m1")
    engine._mem.delete.assert_called_once_with(memory_id="m1")
