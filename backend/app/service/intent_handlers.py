"""
轻量意图处理节点 - web_search / simple_qa / out_of_scope

每个函数是 LangGraph 节点，通过 get_stream_writer() 推 SSE 事件。
返回空 dict（不需要修改 ResearchState）。
"""
import os
import asyncio
import logging
from typing import Dict, Any, List

import requests
from openai import AsyncOpenAI

try:
    from langsmith.wrappers import wrap_openai
except ImportError:
    def wrap_openai(client):
        return client

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
    return wrap_openai(AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY", ""),
        base_url=os.getenv(
            "LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
    ))


# ── LangGraph 节点函数 ────────────────────────────────────────────────────────

async def _bocha_search(query: str, count: int = 5) -> List[Dict[str, Any]]:
    """调用 Bocha Web Search API，返回归一化的结果列表 [{title, url, snippet}]。

    与 Scout 用的是同一个 Bocha 接口（复用 BOCHA_API_KEY），失败时返回空列表。
    """
    api_key = os.getenv("BOCHA_API_KEY", "")
    if not api_key:
        logger.warning("BOCHA_API_KEY 未配置，web_search 无法搜索")
        return []
    try:
        resp = await asyncio.to_thread(
            requests.post,
            "https://api.bocha.cn/v1/web-search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "summary": True, "count": count, "freshness": "noLimit"},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Bocha API error: {resp.status_code} - {resp.text[:200]}")
            return []
        data = resp.json()
        if data.get("code") != 200:
            logger.error(f"Bocha API returned error: {data.get('msg', 'Unknown error')}")
            return []
        webpages = data.get("data", {}).get("webPages", {}).get("value", [])
        results = []
        for item in webpages:
            if item.get("url") and (item.get("snippet") or item.get("summary")):
                results.append({
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("summary", "") or item.get("snippet", ""),
                })
        return results
    except Exception as e:
        logger.error(f"Bocha search error for '{query[:30]}': {e}")
        return []


async def web_search_node(state: Dict[str, Any]) -> Dict:
    """网络搜索节点：Bocha 搜索 + qwen-turbo 合成，流式输出。"""
    writer = _get_writer()
    query = state.get("query", "")

    # 1. 搜索（复用 Scout 同款 Bocha 接口）
    results = await _bocha_search(query, count=5)

    _emit(writer, {
        "type": "search_results",
        "results": [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("snippet", "")}
            for r in results
        ],
    })

    if not results:
        _emit(writer, {"type": "answer_chunk", "content": "抱歉，没有搜索到相关的实时信息，请稍后再试或换个问法。"})
        _emit(writer, {"type": "done"})
        return {}

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
