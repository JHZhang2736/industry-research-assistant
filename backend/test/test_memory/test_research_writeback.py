from unittest.mock import MagicMock
from app.service.deep_research_v2.graph import _writeback_research_memory


def test_writeback_calls_lessons_and_preferences():
    engine = MagicMock()
    state = {
        "user_id": "u1",
        "query": "智慧交通市场规模",
        "critic_feedback": [{"issue_type": "missing_source", "description": "x", "suggestion": "y"}],
        "quality_score": 7.0,
        "messages": [{"role": "user", "content": "智慧交通市场规模"}],
    }
    _writeback_research_memory(engine, state)
    engine.remember_lessons.assert_called_once()
    assert engine.remember_lessons.call_args.args[0] == "智慧交通"
    engine.remember_preferences.assert_called_once()


def test_writeback_noop_without_engine_or_user():
    _writeback_research_memory(None, {"user_id": "u1"})
    engine = MagicMock()
    _writeback_research_memory(engine, {"user_id": ""})
    engine.remember_lessons.assert_not_called()


def test_writeback_swallows_errors():
    engine = MagicMock()
    engine.remember_lessons.side_effect = RuntimeError("down")
    _writeback_research_memory(engine, {"user_id": "u1", "query": "q",
                                        "critic_feedback": [], "quality_score": 5.0,
                                        "messages": []})
