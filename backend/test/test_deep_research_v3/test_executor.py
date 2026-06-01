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


def test_trace_step_inputs_drops_state():
    """process_inputs 只保留 tool/args/step_id，丢掉巨大的 state"""
    from app.service.deep_research_v2.executor import _trace_step_inputs
    inputs = {
        "step": {"step_id": "s1", "tool": "search_section",
                 "args": {"section_id": "sec_1", "queries": ["q"]}},
        "state": {"facts": [1, 2, 3], "raw_sources": [1, 2]},
    }
    out = _trace_step_inputs(inputs)
    assert out == {"tool": "search_section",
                   "args": {"section_id": "sec_1", "queries": ["q"]},
                   "step_id": "s1"}
    assert "state" not in out


def test_trace_step_outputs_summarizes_counts():
    """process_outputs 把 StepResult 压成计数摘要，不带完整 facts"""
    from app.service.deep_research_v2.executor import _trace_step_outputs
    step_result = {
        "step_id": "s1", "tool": "search_section", "status": "success",
        "duration_ms": 1234,
        "output": {"facts": [1, 2, 3], "sources": [1, 2], "section_id": "sec_1"},
    }
    out = _trace_step_outputs(step_result)
    assert out["status"] == "success"
    assert out["duration_ms"] == 1234
    assert out["facts_count"] == 3
    assert out["sources_count"] == 2
    assert "facts" not in out  # 不泄漏完整内容


def test_step_trace_extra_name_with_section():
    """有 section_id 的 step → span name 带 [sec_x]，metadata 含 replan_count"""
    from app.service.deep_research_v2.executor import _step_trace_extra
    step = {"step_id": "s1", "tool": "search_section", "args": {"section_id": "sec_2"}}
    state = {"replan_count": 1}
    extra = _step_trace_extra(step, state)
    assert extra["name"] == "step:search_section[sec_2]"
    assert extra["metadata"]["replan_count"] == 1
    assert extra["metadata"]["step_id"] == "s1"
    assert "search_section" in extra["tags"]
    assert "searching" in extra["tags"]  # phase tag（TOOL_TO_STEP_TYPE 映射）


def test_step_trace_extra_name_without_section():
    """无 section_id 的 step → span name 不带方括号，replan_count 缺省 0"""
    from app.service.deep_research_v2.executor import _step_trace_extra
    step = {"step_id": "s7", "tool": "analyze_facts", "args": {}}
    state = {}
    extra = _step_trace_extra(step, state)
    assert extra["name"] == "step:analyze_facts"
    assert extra["metadata"]["replan_count"] == 0
    assert "analyzing" in extra["tags"]  # phase tag（analyze_facts → analyzing）


async def test_execute_one_step_traceable_returns_stepresult():
    """spec §5：execute_one_step 被 @traceable 包裹后仍返回结构正确的 StepResult，
    且 langsmith_extra kwarg 被装饰器消费、不会泄漏进函数体而报错。
    用 unknown tool 走 failed 分支，避免触发真实 LLM/搜索调用。"""
    from app.service.deep_research_v2.executor import execute_one_step, _step_trace_extra
    step = {"step_id": "s1", "tool": "no_such_tool", "args": {}}
    state = {"facts": [], "replan_count": 0}
    result = await execute_one_step(
        step, state, langsmith_extra=_step_trace_extra(step, state)
    )
    assert result["step_id"] == "s1"
    assert result["tool"] == "no_such_tool"
    assert result["status"] == "failed"
    assert "duration_ms" in result


def test_noop_traceable_decorator_consumes_langsmith_extra():
    """spec §5：no-op traceable fallback 的核心契约——装饰后函数被调用时，
    langsmith_extra 被吞掉、不进入函数体，且返回值原样透传。
    这里直接构造 no-op 装饰器逻辑（langsmith 缺失时走的分支）来验证。"""
    import asyncio
    import functools

    def noop_traceable(*d_args, **d_kwargs):
        def _decorator(fn):
            if asyncio.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def _aw(*args, **kwargs):
                    kwargs.pop("langsmith_extra", None)
                    return await fn(*args, **kwargs)
                return _aw

            @functools.wraps(fn)
            def _sw(*args, **kwargs):
                kwargs.pop("langsmith_extra", None)
                return fn(*args, **kwargs)
            return _sw
        if len(d_args) == 1 and callable(d_args[0]) and not d_kwargs:
            return _decorator(d_args[0])
        return _decorator

    @noop_traceable(run_type="tool")
    def add(a, b):
        return a + b

    # langsmith_extra 必须被吞掉，不会作为未知 kwarg 传进 add() 报 TypeError
    assert add(2, 3, langsmith_extra={"name": "x"}) == 5


@pytest.mark.asyncio
async def test_executor_records_writer_revision_diagnostics(monkeypatch):
    from app.service.deep_research_v2 import executor as executor_module
    from app.service.deep_research_v2.state import create_initial_state

    async def fake_write_section(section_id, state):
        return {
            "section_id": section_id,
            "content": "修订内容",
            "addressed_issue_ids": ["issue_1"],
            "unable_to_address": [{"issue_id": "issue_2", "reason": "无来源"}],
            "changes_made": ["补充引用"],
        }

    monkeypatch.setattr(
        executor_module,
        "TOOL_REGISTRY",
        dict(executor_module.TOOL_REGISTRY, write_section=fake_write_section),
    )

    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "旧内容"}
    state["plan"] = [{
        "step_id": "write_1",
        "tool": "write_section",
        "args": {"section_id": "sec_1"},
        "depends_on": [],
        "parallel_group": None,
    }]

    result = await executor_module.executor_node(state)

    assert result["draft_sections"]["sec_1"] == "修订内容"
    diagnostic = result["critic_diagnostics"][0]
    assert diagnostic["type"] == "writer_revision"
    assert diagnostic["section_id"] == "sec_1"
    assert diagnostic["addressed_issue_ids"] == ["issue_1"]
    assert diagnostic["before_hash"].startswith("sha256:")
    assert diagnostic["after_hash"].startswith("sha256:")
    assert diagnostic["before_hash"] != diagnostic["after_hash"]
