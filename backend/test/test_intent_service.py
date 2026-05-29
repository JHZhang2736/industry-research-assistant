import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.service.intent_service import IntentService, IntentResult


@pytest.fixture
def service():
    return IntentService(api_key="test-key", base_url="https://example.com", model="qwen-turbo")


@pytest.mark.asyncio
async def test_classify_deep_research(service):
    """深度研究意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "deep_research"
    mock_tool_call.function.arguments = '{"research_type": "general"}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("分析中国新能源汽车行业的竞争格局")

    assert result.intent == "deep_research"
    assert result.research_type == "general"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_web_search(service):
    """网络搜索意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "web_search"
    mock_tool_call.function.arguments = '{}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("最新CPI数据是多少")

    assert result.intent == "web_search"
    assert result.research_type == ""
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_fallback_on_exception(service):
    """调用异常时 fallback 到 deep_research"""
    with patch.object(service.client.chat.completions, "create", new=AsyncMock(side_effect=Exception("timeout"))):
        result = await service.classify("任意问题")

    assert result.intent == "deep_research"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_classify_simple_qa(service):
    """简单问答意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "simple_qa"
    mock_tool_call.function.arguments = '{}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("什么是市盈率PE")

    assert result.intent == "simple_qa"
    assert result.research_type == ""
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_out_of_scope(service):
    """领域外意图识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "out_of_scope"
    mock_tool_call.function.arguments = '{}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("帮我写首诗")

    assert result.intent == "out_of_scope"
    assert result.research_type == ""
    assert result.confidence == 1.0
