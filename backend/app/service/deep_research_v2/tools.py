"""DeepResearch v3 - @tool 注册中心

把 sub-agent 包装成 LangGraph 可调用的 @tool 函数。
单例缓存 agent 实例，避免每次调用都创建。
"""

import logging
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool

from .state import ResearchState
from .agents import DeepScout

try:
    from config.llm_config import get_config
except ImportError:
    from app.config.llm_config import get_config

logger = logging.getLogger("deep_research_v3.tools")

_scout_instance: Optional[DeepScout] = None


def get_scout_instance() -> DeepScout:
    """获取 DeepScout 单例"""
    global _scout_instance
    if _scout_instance is None:
        config = get_config()
        _scout_instance = DeepScout(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            search_api_key=config.search_api_key,
            model=config.agents.scout.model,
        )
    return _scout_instance


def reset_instances():
    """测试用：重置所有单例"""
    global _scout_instance
    _scout_instance = None


@tool
async def search_section(
    section_id: str,
    queries: List[str],
    state: ResearchState,
) -> Dict[str, Any]:
    """对一个章节执行多 query 搜索 + fact 提取。

    Args:
        section_id: outline 里的章节 ID（sec_1 ~ sec_6）
        queries: 这个章节要搜的关键词列表（通常 3-5 个）
        state: 共享 ResearchState（read 在 tool 内；具体说明见 DeepScout.search_with_queries）

    Returns:
        {
            "facts": [Fact, ...],       # 本次调用新增的 facts
            "sources": [Source, ...],   # 本次调用新增的 sources
            "section_id": section_id,   # 回传用于 executor merge
        }
    """
    scout = get_scout_instance()
    try:
        return await scout.search_with_queries(
            section_id=section_id,
            queries=queries,
            state=state,
        )
    except Exception as e:
        logger.exception(f"search_section[{section_id}] failed: {e}")
        return {"facts": [], "sources": [], "section_id": section_id, "error": str(e)}
