"""测试 ResearchState 新字段 + PlanStep / StepResult dataclass"""
import pytest
from app.service.deep_research_v2.state import (
    PlanStep,
    StepResult,
    ResearchState,
    create_initial_state,
)


def test_plan_step_dataclass_minimal():
    """PlanStep 最小创建"""
    step = PlanStep(
        step_id="step_1",
        tool="search_section",
        args={"section_id": "sec_1", "queries": ["foo"]},
        depends_on=[],
        parallel_group="search_batch",
    )
    assert step.step_id == "step_1"
    assert step.tool == "search_section"
    assert step.args["section_id"] == "sec_1"
    assert step.depends_on == []
    assert step.parallel_group == "search_batch"


def test_plan_step_no_parallel_group():
    """parallel_group=None 表示串行（不与任何 step 并行）"""
    step = PlanStep(
        step_id="step_2",
        tool="analyze_facts",
        args={},
        depends_on=["step_1"],
        parallel_group=None,
    )
    assert step.parallel_group is None


def test_step_result_dataclass():
    """StepResult 记录 step 执行结果"""
    result = StepResult(
        step_id="step_1",
        tool="search_section",
        status="success",
        output={"facts": []},
        error=None,
        duration_ms=1234,
    )
    assert result.status == "success"
    assert result.output["facts"] == []
    assert result.error is None
    assert result.duration_ms == 1234


def test_step_result_failure():
    """StepResult 记录失败"""
    result = StepResult(
        step_id="step_2",
        tool="search_section",
        status="failed",
        output=None,
        error="API timeout",
        duration_ms=30000,
    )
    assert result.status == "failed"
    assert result.error == "API timeout"


def test_research_state_new_fields():
    """ResearchState 新增字段全部初始化"""
    state = create_initial_state(query="test", session_id="sid_1")
    assert state["plan"] == []
    assert state["completed_steps"] == []
    assert state["replan_count"] == 0
    assert state["fallback_triggered"] is False


def test_research_state_backward_compat():
    """ResearchState 旧字段保留（前端兼容）"""
    state = create_initial_state(query="test", session_id="sid_1")
    for key in ["query", "session_id", "outline", "facts", "data_points",
                "charts", "draft_sections", "final_report", "references",
                "critic_feedback", "quality_score", "messages", "logs"]:
        assert key in state, f"backward-compat field {key} missing"


def test_research_state_has_user_id():
    state = create_initial_state(query="q", session_id="s", user_id="u1")
    assert state["user_id"] == "u1"


def test_research_state_user_id_defaults_empty():
    state = create_initial_state(query="q", session_id="s")
    assert state["user_id"] == ""
