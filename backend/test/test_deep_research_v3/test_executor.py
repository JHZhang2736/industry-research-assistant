"""测试 Executor 调度逻辑（Send API 并行 + 依赖关系）"""
import pytest
from app.service.deep_research_v2.executor import (
    pick_next_parallel_batch,
    all_steps_done,
)


def test_pick_next_batch_no_deps_returns_first_parallel_group():
    """无依赖的 step 在同一 parallel_group → 一次性返回全部"""
    plan = [
        {"step_id": "s1", "tool": "search_section", "args": {"section_id": "sec_1"},
         "depends_on": [], "parallel_group": "search_batch"},
        {"step_id": "s2", "tool": "search_section", "args": {"section_id": "sec_2"},
         "depends_on": [], "parallel_group": "search_batch"},
        {"step_id": "s3", "tool": "analyze_facts", "args": {},
         "depends_on": ["s1", "s2"], "parallel_group": None},
    ]
    completed = []

    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 2
    assert {s["step_id"] for s in batch} == {"s1", "s2"}


def test_pick_next_batch_respects_depends_on():
    """依赖未完成时不返回该 step"""
    plan = [
        {"step_id": "s1", "tool": "search_section", "args": {},
         "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "analyze_facts", "args": {},
         "depends_on": ["s1"], "parallel_group": None},
    ]
    completed = []
    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 1
    assert batch[0]["step_id"] == "s1"

    completed = [{"step_id": "s1", "status": "success"}]
    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 1
    assert batch[0]["step_id"] == "s2"


def test_pick_next_batch_serial_when_no_group():
    """parallel_group=None 的 step 即使无依赖也单独返回（不与其他 None 合并）"""
    plan = [
        {"step_id": "s1", "tool": "analyze_facts", "args": {},
         "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "generate_charts", "args": {},
         "depends_on": [], "parallel_group": None},
    ]
    completed = []
    batch = pick_next_parallel_batch(plan, completed)
    assert len(batch) == 1


def test_all_steps_done_true():
    """所有 plan step 都在 completed 中 → done"""
    plan = [
        {"step_id": "s1", "tool": "x", "args": {}, "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "y", "args": {}, "depends_on": [], "parallel_group": None},
    ]
    completed = [
        {"step_id": "s1", "status": "success"},
        {"step_id": "s2", "status": "success"},
    ]
    assert all_steps_done(plan, completed) is True


def test_all_steps_done_false_when_pending():
    plan = [
        {"step_id": "s1", "tool": "x", "args": {}, "depends_on": [], "parallel_group": None},
        {"step_id": "s2", "tool": "y", "args": {}, "depends_on": [], "parallel_group": None},
    ]
    completed = [{"step_id": "s1", "status": "success"}]
    assert all_steps_done(plan, completed) is False


def test_failed_step_counts_as_done():
    """失败的 step 也算 done（避免死循环）"""
    plan = [
        {"step_id": "s1", "tool": "x", "args": {}, "depends_on": [], "parallel_group": None},
    ]
    completed = [{"step_id": "s1", "status": "failed", "error": "boom"}]
    assert all_steps_done(plan, completed) is True
