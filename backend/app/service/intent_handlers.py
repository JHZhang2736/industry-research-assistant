"""
轻量意图处理节点 - web_search / simple_qa / out_of_scope

每个函数是 LangGraph 节点，通过 get_stream_writer() 推 SSE 事件。
返回空 dict（不需要修改 ResearchState）。
"""
import os
import logging
from typing import Dict, Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _get_writer():
    """获取 LangGraph stream writer，非图上下文时返回 None。"""
    try:
        from langgraph.config import get_stream_writer
        return get_stream_writer()
    except (ImportError, RuntimeError, KeyError):
        return None


def _emit(writer, event: Dict[str, Any]) -> None:
    if writer:
        writer(event)


def _make_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        base_url=os.getenv(
            "LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    )


# ── LangGraph 节点函数 ────────────────────────────────────────────────────────

async def web_search_node(state: Dict[str, Any]) -> Dict:
    """网络搜索节点：Serper 搜索 + qwen-turbo 合成，流式输出。"""
    try:
        from app.service.web_search_service import WebSearchService
        from app.service.config import ServiceConfig
    except ImportError:
        from service.web_search_service import WebSearchService
        from service.config import ServiceConfig

    writer = _get_writer()
    query = state.get("query", "")

    # 1. 搜索
    config = ServiceConfig.get_api_config()
    svc = WebSearchService(api_key=config.get("serper_api_key"))
    raw = svc.search(query, gl="cn", hl="zh-cn")
    results = svc.extract_search_results(raw)[:5]

    _emit(writer, {
        "type": "search_results",
        "results": [
            {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
            for r in results
        ],
    })

    # 2. LLM 合成（流式）
    context = "\n\n".join(
        f"[{i+1}] {r.get('title', '')}\n{r.get('snippet', '')}"
        for i, r in enumerate(results)
    )
    client = _make_llm_client()
    stream = await client.chat.completions.create(
        model="qwen-turbo",
        messages=[
            {
                "role": "system",
                "content": "你是专业的金融行业研究助手，请根据以下搜索结果简洁准确地回答用户问题，不超过500字。",
            },
            {
                "role": "user",
                "content": f"问题：{query}\n\n搜索结果：\n{context}",
            },
        ],
        stream=True,
    )

    async for chunk in stream:
        content = chunk.choices[0].delta.content or ""
        if content:
            _emit(writer, {"type": "answer_chunk", "content": content})

    _emit(writer, {"type": "done"})
    return {}


async def simple_qa_node(state: Dict[str, Any]) -> Dict:
    """直接问答节点：qwen-turbo 直接回答，流式输出。"""
    writer = _get_writer()
    query = state.get("query", "")

    client = _make_llm_client()
    stream = await client.chat.completions.create(
        model="qwen-turbo",
        messages=[
            {
                "role": "system",
                "content": (
                    "你是专业的金融行业研究助手，擅长解释金融概念、投资术语和行业知识。"
                    "请简洁准确地回答问题，不超过300字。"
                ),
            },
            {"role": "user", "content": query},
        ],
        stream=True,
    )

    async for chunk in stream:
        content = chunk.choices[0].delta.content or ""
        if content:
            _emit(writer, {"type": "answer_chunk", "content": content})

    _emit(writer, {"type": "done"})
    return {}


async def out_of_scope_node(state: Dict[str, Any]) -> Dict:
    """领域外问题节点：发送固定拒绝消息。"""
    writer = _get_writer()
    _emit(writer, {
        "type": "answer_chunk",
        "content": "抱歉，我专注于行业研究和金融分析领域，暂时无法回答这类问题。如有行业研究相关的问题，欢迎继续提问。",
    })
    _emit(writer, {"type": "done"})
    return {}
