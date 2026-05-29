"""意图识别服务 - 使用 DashScope qwen-turbo function calling"""
import json
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

INTENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": (
                "用户需要对行业、市场、公司进行深度调研分析，需要综合多个信息源、"
                "生成结构化报告。例如：行业竞争格局分析、市场规模预测、公司基本面研究、"
                "政策影响分析、赛道对比研究等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "research_type": {
                        "type": "string",
                        "enum": ["general"],
                        "description": "研究类型，当前仅支持 general",
                    }
                },
                "required": ["research_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "用户需要获取实时、最新的信息，但不需要深度分析报告。"
                "例如：最新数据查询、近期新闻、实时行情、今日热点等。"
                "不适用于需要综合分析的问题。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simple_qa",
            "description": (
                "用户提出的是概念性、定义性、常识性问题，可以直接回答，"
                "不需要实时数据或深度调研。"
                "例如：解释金融术语、计算公式说明、基础概念问答。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "out_of_scope",
            "description": (
                "用户的问题与金融、行业研究、投资分析完全无关，属于领域外问题或闲聊。"
                "例如：诗歌创作、天气查询、游戏推荐、日常闲聊等。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

VALID_INTENTS = {"deep_research", "web_search", "simple_qa", "out_of_scope"}


@dataclass
class IntentResult:
    intent: Literal["deep_research", "web_search", "simple_qa", "out_of_scope"]
    research_type: str   # deep_research 时为 "general"，其余为 ""
    confidence: float    # 1.0 正常识别，0.0 表示 fallback


class IntentService:
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

    async def classify(self, query: str) -> IntentResult:
        """用 function calling 识别用户查询意图，失败时 fallback 到 deep_research。"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的意图分类器，服务于行业研究助手系统。"
                            "根据用户问题，选择最匹配的处理方式。"
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                tools=INTENT_TOOLS,
                tool_choice="required",
            )

            tool_call = response.choices[0].message.tool_calls[0]
            intent_name = tool_call.function.name

            if intent_name not in VALID_INTENTS:
                logger.warning(f"Unknown intent tool: {intent_name}, falling back to deep_research")
                return IntentResult(intent="deep_research", research_type="general", confidence=0.0)

            research_type = ""
            if intent_name == "deep_research":
                args = json.loads(tool_call.function.arguments or "{}")
                research_type = args.get("research_type", "general")

            return IntentResult(intent=intent_name, research_type=research_type, confidence=1.0)

        except Exception as e:
            logger.warning(f"IntentService.classify failed: {e}, falling back to deep_research")
            return IntentResult(intent="deep_research", research_type="general", confidence=0.0)
