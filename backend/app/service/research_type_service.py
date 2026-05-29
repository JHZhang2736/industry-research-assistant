"""研究类型识别服务 - Level 2 意图识别，使用 DashScope qwen-turbo function calling"""
import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

from openai import AsyncOpenAI

try:
    from langsmith.wrappers import wrap_openai
except ImportError:
    def wrap_openai(client):
        return client

logger = logging.getLogger(__name__)

RESEARCH_TYPE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "industry_analysis",
            "description": (
                "对某个行业、赛道、市场进行深度分析，包括市场规模、竞争格局、"
                "波特五力、发展趋势等宏观分析。"
                "适用于：'分析新能源汽车行业'、'光伏赛道市场现状'、'XX行业竞争格局'等。"
                "不适用于聚焦单一公司或多公司对比的问题。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "company_research",
            "description": (
                "对单一公司进行深度调研，包括商业模式、财务状况、"
                "管理层、竞争优势与风险的尽调式分析。"
                "适用于：'分析比亚迪'、'XX公司基本面研究'、'XX公司投资价值'等。"
                "核心特征：问题中只涉及一个主体。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comparative_analysis",
            "description": (
                "对多个公司、产品或方案进行横向对比分析，输出结构化对比表格与综合结论。"
                "适用于：'比较比亚迪和宁德时代'、'XX vs YY 哪个更好'、'多家公司对比'等。"
                "核心特征：问题中明确涉及两个及以上对比主体。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

VALID_RESEARCH_TYPES = {"industry_analysis", "company_research", "comparative_analysis"}


@dataclass
class ResearchTypeResult:
    research_type: Literal["industry_analysis", "company_research", "comparative_analysis"]
    confidence: float  # 1.0 正常识别，0.0 表示 fallback


class ResearchTypeService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "qwen-turbo",
    ):
        self.model = model
        self.client = wrap_openai(AsyncOpenAI(
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY", ""),
            base_url=base_url or os.getenv(
                "LLM_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        ))

    async def classify(self, query: str) -> ResearchTypeResult:
        """识别深度研究的具体类型，失败时 fallback 到 industry_analysis。"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的研究类型分类器。"
                            "根据用户的研究问题，判断属于行业分析、公司调研还是竞品对比。"
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                tools=RESEARCH_TYPE_TOOLS,
                tool_choice="required",
            )

            tool_call = response.choices[0].message.tool_calls[0]
            research_type = tool_call.function.name

            if research_type not in VALID_RESEARCH_TYPES:
                logger.warning(f"Unknown research type: {research_type}, falling back")
                return ResearchTypeResult(research_type="industry_analysis", confidence=0.0)

            return ResearchTypeResult(research_type=research_type, confidence=1.0)

        except Exception as e:
            logger.warning(f"ResearchTypeService.classify failed: {e}, falling back to industry_analysis")
            return ResearchTypeResult(research_type="industry_analysis", confidence=0.0)
