import json
from unittest.mock import AsyncMock

import pytest

from app.service.deep_research_v2.agents.writer import LeadWriter
from app.service.deep_research_v2.state import create_initial_state


@pytest.fixture
def writer():
    return LeadWriter(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        model="deepseek-v3.2",
    )


@pytest.mark.asyncio
async def test_write_one_section_uses_revision_context(writer, monkeypatch):
    response = json.dumps({
        "content": "修订后内容，补充了来源 [1]",
        "changes_made": ["补充来源"],
        "addressed_issue_ids": ["issue_1"],
        "unable_to_address": [],
        "citations": [{"source": "来源A", "url": "https://example.com"}],
    }, ensure_ascii=False)
    monkeypatch.setattr(writer, "call_llm", AsyncMock(return_value=response))

    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一", "description": "描述", "section_type": "mixed"}]
    state["draft_sections"] = {"sec_1": "旧内容"}
    state["facts"] = [{
        "id": "f1",
        "content": "事实一",
        "source_name": "来源A",
        "source_url": "https://facts.example.com/a",
        "credibility_score": 0.9,
        "related_sections": ["sec_1"],
    }]
    state["revision_context_by_section"] = {
        "sec_1": {
            "section_id": "sec_1",
            "mode": "rewrite_with_feedback",
            "issues": [{
                "id": "issue_1",
                "severity": "major",
                "description": "缺少来源",
                "suggestion": "补充来源",
                "acceptance_criteria": ["新增引用"],
            }],
            "required_actions": ["rewrite"],
        }
    }

    result = await writer.write_one_section("sec_1", state)

    assert result["content"] == "修订后内容，补充了来源 [1]"
    assert result["addressed_issue_ids"] == ["issue_1"]
    assert state["draft_sections"]["sec_1"] == "修订后内容，补充了来源 [1]"
    assert state["outline"][0]["status"] == "drafted"
    assert state["references"][-1]["source"] == "来源A"
    assert state["references"][-1]["url"] == "https://example.com"
    called_prompt = writer.call_llm.await_args.kwargs["user_prompt"]
    assert "旧内容" in called_prompt
    assert "缺少来源" in called_prompt
    assert "新增引用" in called_prompt
    assert "https://facts.example.com/a" in called_prompt


@pytest.mark.asyncio
async def test_write_one_section_revision_parse_failure_is_reported(writer, monkeypatch):
    monkeypatch.setattr(writer, "call_llm", AsyncMock(return_value="not json"))

    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一", "description": "描述", "section_type": "mixed"}]
    state["draft_sections"] = {"sec_1": "旧内容"}
    state["revision_context_by_section"] = {
        "sec_1": {
            "section_id": "sec_1",
            "issues": [{
                "id": "issue_1",
                "description": "缺少来源",
            }],
        }
    }

    result = await writer.write_one_section("sec_1", state)

    assert result["revision_failed"] is True
    assert result["content"] == "旧内容"
    assert state["draft_sections"]["sec_1"] == "旧内容"
    assert result["changes_made"] == []
    assert result["addressed_issue_ids"] == []
    assert result["unable_to_address"][0]["issue_id"] == "issue_1"
    assert result["unable_to_address"][0]["reason"]
    assert "status" not in state["outline"][0]


@pytest.mark.asyncio
async def test_write_one_section_revision_empty_content_is_reported(writer, monkeypatch):
    response = json.dumps({
        "content": "",
        "changes_made": ["claimed change"],
        "addressed_issue_ids": ["issue_1"],
        "unable_to_address": [],
        "citations": [{"source": "来源A", "url": "https://example.com"}],
    }, ensure_ascii=False)
    monkeypatch.setattr(writer, "call_llm", AsyncMock(return_value=response))

    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一", "description": "描述", "section_type": "mixed"}]
    state["draft_sections"] = {"sec_1": "旧内容"}
    state["revision_context_by_section"] = {
        "sec_1": {
            "section_id": "sec_1",
            "issues": [{
                "id": "issue_1",
                "description": "缺少来源",
            }],
        }
    }

    result = await writer.write_one_section("sec_1", state)

    assert result["revision_failed"] is True
    assert result["content"] == "旧内容"
    assert state["draft_sections"]["sec_1"] == "旧内容"
    assert result["changes_made"] == []
    assert result["addressed_issue_ids"] == []
    assert result["unable_to_address"][0]["issue_id"] == "issue_1"
    assert result["unable_to_address"][0]["reason"]
    assert state["references"] == []
    assert "status" not in state["outline"][0]


@pytest.mark.asyncio
async def test_write_one_section_without_revision_context_uses_normal_path(writer, monkeypatch):
    monkeypatch.setattr(writer, "_write_section", AsyncMock())
    state = create_initial_state(query="测试主题", session_id="sid_1")
    state["outline"] = [{"id": "sec_1", "title": "章节一", "description": "描述", "section_type": "mixed"}]
    state["draft_sections"] = {"sec_1": "普通内容"}

    result = await writer.write_one_section("sec_1", state)

    writer._write_section.assert_awaited_once()
    assert result["section_id"] == "sec_1"
    assert result["content"] == "普通内容"
