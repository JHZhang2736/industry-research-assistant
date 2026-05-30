from unittest.mock import MagicMock
from app.service.deep_research_v2.agents.planner import _build_memory_prefix, _recall_memory


def test_planner_memory_prefix_combines_pref_and_lessons():
    engine = MagicMock()
    engine.recall_preferences.return_value = "[用户偏好]\n- 报告要简洁\n"
    engine.recall_lessons.return_value = "[过往研究教训（请在规划时主动规避）]\n- 教训X\n"
    prefix = _build_memory_prefix(engine, user_id="u1", query="智慧交通市场")
    assert "报告要简洁" in prefix
    assert "教训X" in prefix
    engine.recall_lessons.assert_called_once()


def test_planner_memory_prefix_empty_engine_returns_blank():
    assert _build_memory_prefix(None, user_id="u1", query="q") == ""


def test_planner_memory_prefix_no_user_id_returns_blank():
    engine = MagicMock()
    assert _build_memory_prefix(engine, user_id="", query="q") == ""


def test_recall_memory_returns_structured_dict():
    engine = MagicMock()
    engine.recall_preferences.return_value = "[用户偏好]\n- 简洁\n"
    engine.recall_lessons.return_value = "[过往研究教训]\n- 教训X\n"
    mem = _recall_memory(engine, "u1", "智慧交通市场")
    assert mem == {"preferences": "[用户偏好]\n- 简洁\n", "lessons": "[过往研究教训]\n- 教训X\n"}
    engine.recall_lessons.assert_called_once()


def test_recall_memory_none_engine_or_no_user_returns_empty():
    assert _recall_memory(None, "u1", "q") == {"preferences": "", "lessons": ""}
    engine = MagicMock()
    assert _recall_memory(engine, "", "q") == {"preferences": "", "lessons": ""}
    engine.recall_preferences.assert_not_called()
