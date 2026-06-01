"""测试 Critic node 改造后输出 suggested_actions"""
import pytest
import json
from unittest.mock import AsyncMock
from app.service.deep_research_v2.agents import CriticMaster
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def critic():
    return CriticMaster(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


def test_critic_prompt_requests_structured_review_fields():
    prompt = CriticMaster.REVIEW_PROMPT

    assert "dimension_scores" in prompt
    assert "resolved_issue_ids" in prompt
    assert "same_as_issue_id" in prompt
    assert "acceptance_criteria" in prompt
    for dimension in [
        "factual_support",
        "citation_integrity",
        "coverage",
        "reasoning",
        "freshness",
        "actionability",
    ]:
        assert dimension in prompt
    for weight in CriticMaster.DIMENSION_WEIGHTS.values():
        assert f"{weight:.2f}" in prompt


@pytest.mark.asyncio
async def test_critic_prompt_includes_prior_issue_context(critic, monkeypatch):
    captured = {}

    async def fake_call_llm(*, user_prompt, **kwargs):
        captured["user_prompt"] = user_prompt
        return json.dumps({
            "quality_score": 8.0,
            "verdict": "pass",
            "critic_feedback": [],
            "unresolved_issues": 0,
            "suggested_actions": [],
        }, ensure_ascii=False)

    monkeypatch.setattr(critic, "call_llm", fake_call_llm)

    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "内容"}
    state["critic_feedback"] = [{
        "id": "issue_prior",
        "target_section": "sec_1",
        "severity": "major",
        "resolved": False,
        "description": "逻辑跳跃",
        "acceptance_criteria": ["解释因果关系"],
    }]

    await critic.process(state)

    prompt = captured["user_prompt"]
    assert "issue_prior" in prompt
    assert "sec_1" in prompt
    assert "major" in prompt
    assert "resolved=False" in prompt
    assert "逻辑跳跃" in prompt
    assert "解释因果关系" in prompt


@pytest.mark.asyncio
async def test_critic_outputs_suggested_actions_field(critic, monkeypatch):
    """Critic 输出新字段 suggested_actions: list[str]"""
    mock_response = json.dumps({
        "quality_score": 7.2,
        "critic_feedback": [
            {"id": "f1", "target_section": "sec_3", "issue_type": "missing_source",
             "severity": "major", "description": "...", "suggestion": "..."}
        ],
        "unresolved_issues": 2,
        "verdict": "needs_revision",
        "suggested_actions": ["retry_search:sec_3", "rewrite:sec_5"],
    }, ensure_ascii=False)

    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["draft_sections"] = {"sec_1": "draft", "sec_3": "draft", "sec_5": "draft"}
    state["facts"] = []
    state["outline"] = [{"id": "sec_3", "title": "三"}]

    result = await critic.process(state)

    assert "suggested_actions" in result
    assert "retry_search:sec_3" in result["suggested_actions"]
    assert "rewrite:sec_5" in result["suggested_actions"]
    assert result["quality_score"] == 7.2


@pytest.mark.asyncio
async def test_critic_empty_suggested_actions_on_pass(critic, monkeypatch):
    """verdict=pass 时 suggested_actions 为空"""
    mock_response = json.dumps({
        "quality_score": 9.0,
        "critic_feedback": [],
        "unresolved_issues": 0,
        "verdict": "pass",
        "suggested_actions": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["draft_sections"] = {"sec_1": "ok"}
    state["facts"] = []
    state["outline"] = []

    result = await critic.process(state)
    assert result["suggested_actions"] == []
    assert result["unresolved_issues"] == 0


@pytest.mark.asyncio
async def test_critic_dimension_scores_drive_weighted_quality(critic, monkeypatch):
    mock_response = json.dumps({
        "dimension_scores": {
            "factual_support": 4,
            "citation_integrity": 5,
            "coverage": 6,
            "reasoning": 7,
            "freshness": 8,
            "actionability": 9,
        },
        "quality_score": 1.0,
        "verdict": "needs_revision",
        "critic_feedback": [{
            "id": "issue_1",
            "target_section": "sec_1",
            "issue_type": "missing_source",
            "severity": "major",
            "description": "缺少来源",
            "suggestion": "补充引用",
            "acceptance_criteria": ["至少新增一个来源"],
        }],
        "unresolved_issues": 1,
        "suggested_actions": ["retry_search:sec_1"],
        "summary": "needs work",
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "原始内容"}

    result = await critic.process(state)

    assert result["quality_score"] == pytest.approx(5.85)
    assert result["dimension_scores"]["factual_support"] == 4.0
    assert result["review_history"][0]["quality_score"] == pytest.approx(5.85)
    assert result["review_history"][0]["input_snapshot"]["draft_hash_by_section"]["sec_1"].startswith("sha256:")


@pytest.mark.asyncio
async def test_critic_partial_dimension_scores_falls_back_to_quality_score(critic, monkeypatch):
    mock_response = json.dumps({
        "dimension_scores": {
            "factual_support": 4,
        },
        "quality_score": 7.3,
        "verdict": "pass",
        "critic_feedback": [],
        "unresolved_issues": 0,
        "suggested_actions": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "内容"}

    result = await critic.process(state)

    assert result["quality_score"] == 7.3
    assert result["dimension_scores"] == {}


@pytest.mark.asyncio
async def test_critic_preserves_repeated_issue_id_with_same_as(critic, monkeypatch):
    mock_response = json.dumps({
        "quality_score": 4.5,
        "verdict": "needs_revision",
        "resolved_issue_ids": [],
        "critic_feedback": [{
            "same_as_issue_id": "issue_old",
            "target_section": "sec_1",
            "issue_type": "logic_error",
            "severity": "major",
            "description": "逻辑仍然跳跃",
            "suggestion": "补充推理链",
            "acceptance_criteria": ["解释因果关系"],
        }],
        "suggested_actions": ["rewrite:sec_1"],
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "内容"}
    state["critic_feedback"] = [{
        "id": "issue_old",
        "target_section": "sec_1",
        "issue_type": "logic_error",
        "severity": "major",
        "description": "逻辑跳跃",
        "suggestion": "补充推理",
        "resolved": False,
    }]

    result = await critic.process(state)

    assert result["critic_feedback"][0]["id"] == "issue_old"
    assert result["critic_feedback"][0]["resolved"] is False


@pytest.mark.asyncio
async def test_critic_preserves_previously_resolved_feedback(critic, monkeypatch):
    mock_response = json.dumps({
        "quality_score": 4.5,
        "verdict": "needs_revision",
        "critic_feedback": [{
            "id": "issue_new",
            "target_section": "sec_1",
            "issue_type": "missing_source",
            "severity": "major",
            "description": "缺少来源",
            "suggestion": "补充引用",
            "acceptance_criteria": ["至少新增一个来源"],
        }],
        "suggested_actions": ["retry_search:sec_1"],
    }, ensure_ascii=False)
    monkeypatch.setattr(critic, "call_llm", AsyncMock(return_value=mock_response))

    state = create_initial_state(query="测试", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一"}]
    state["draft_sections"] = {"sec_1": "内容"}
    state["critic_feedback"] = [{
        "id": "issue_resolved",
        "target_section": "sec_1",
        "issue_type": "logic_error",
        "severity": "major",
        "description": "旧问题",
        "suggestion": "已处理",
        "resolved": True,
    }]

    result = await critic.process(state)

    feedback_by_id = {item["id"]: item for item in result["critic_feedback"]}
    assert feedback_by_id["issue_resolved"]["resolved"] is True
    assert feedback_by_id["issue_new"]["resolved"] is False
