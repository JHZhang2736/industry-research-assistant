import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.service.research_type_service import ResearchTypeService, ResearchTypeResult


@pytest.fixture
def service():
    return ResearchTypeService(api_key="test-key", base_url="https://example.com", model="qwen-turbo")


@pytest.mark.asyncio
async def test_classify_industry_analysis(service):
    """行业分析识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "industry_analysis"
    mock_tool_call.function.arguments = "{}"
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("分析中国新能源汽车行业的市场格局")

    assert result.research_type == "industry_analysis"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_company_research(service):
    """公司调研识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "company_research"
    mock_tool_call.function.arguments = "{}"
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("深度分析比亚迪公司的基本面")

    assert result.research_type == "company_research"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_comparative_analysis(service):
    """竞品对比识别"""
    mock_tool_call = MagicMock()
    mock_tool_call.function.name = "comparative_analysis"
    mock_tool_call.function.arguments = "{}"
    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=mock_message)]

    with patch.object(service.client.chat.completions, "create", new=AsyncMock(return_value=mock_response)):
        result = await service.classify("比较比亚迪和宁德时代的竞争优势")

    assert result.research_type == "comparative_analysis"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_classify_fallback_on_exception(service):
    """调用异常时 fallback 到 industry_analysis"""
    with patch.object(service.client.chat.completions, "create", new=AsyncMock(side_effect=Exception("timeout"))):
        result = await service.classify("任意问题")

    assert result.research_type == "industry_analysis"
    assert result.confidence == 0.0
