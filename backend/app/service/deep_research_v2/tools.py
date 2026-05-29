"""DeepResearch v3 - @tool 注册中心

把 sub-agent 包装成 LangGraph 可调用的 @tool 函数。
单例缓存 agent 实例，避免每次调用都创建。
"""

import logging
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool

from .state import ResearchState
from .agents import DeepScout, DataAnalyst, CodeWizard, LeadWriter

try:
    from config.llm_config import get_config
except ImportError:
    from app.config.llm_config import get_config

logger = logging.getLogger("deep_research_v3.tools")

_scout_instance: Optional[DeepScout] = None
_analyst_instance: Optional[DataAnalyst] = None
_wizard_instance: Optional[CodeWizard] = None
_writer_instance: Optional[LeadWriter] = None


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
    global _scout_instance, _analyst_instance, _wizard_instance, _writer_instance
    _scout_instance = None
    _analyst_instance = None
    _wizard_instance = None
    _writer_instance = None


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


def get_analyst_instance() -> DataAnalyst:
    """获取 DataAnalyst 单例"""
    global _analyst_instance
    if _analyst_instance is None:
        config = get_config()
        _analyst_instance = DataAnalyst(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            model=config.agents.data_analyst.model,
        )
    return _analyst_instance


@tool
async def analyze_facts(state: ResearchState) -> Dict[str, Any]:
    """从已收集的 facts 中提取 data points + 生成 insights。

    Args:
        state: 共享 ResearchState，读取 state["facts"]

    Returns:
        {
            "data_points": [...],
            "insights": [str, ...],
        }
    """
    analyst = get_analyst_instance()
    try:
        return await analyst.extract_data_points(state)
    except Exception as e:
        logger.exception(f"analyze_facts failed: {e}")
        return {
            "data_points": [],
            "insights": [],
            "error": str(e),
        }


def get_wizard_instance() -> CodeWizard:
    """获取 CodeWizard 单例"""
    global _wizard_instance
    if _wizard_instance is None:
        config = get_config()
        _wizard_instance = CodeWizard(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            model=config.agents.wizard.model,
        )
    return _wizard_instance


@tool
async def generate_charts(state: ResearchState) -> Dict[str, Any]:
    """根据 data_points 生成可视化图表（matplotlib + ECharts option）。

    Args:
        state: 共享 ResearchState，读取 state["data_points"]

    Returns:
        {"charts": [...], "code_executions": [...]}
    """
    wizard = get_wizard_instance()
    try:
        return await wizard.generate_charts_for_state(state)
    except Exception as e:
        logger.exception(f"generate_charts failed: {e}")
        return {"charts": [], "code_executions": [], "error": str(e)}


def get_writer_instance() -> LeadWriter:
    """获取 LeadWriter 单例"""
    global _writer_instance
    if _writer_instance is None:
        config = get_config()
        _writer_instance = LeadWriter(
            llm_api_key=config.api_key,
            llm_base_url=config.base_url,
            model=config.agents.writer.model,
        )
    return _writer_instance


@tool
async def write_section(
    section_id: str,
    state: ResearchState,
) -> Dict[str, Any]:
    """撰写一个章节的 Markdown 内容（复用 facts + data_points + charts）。

    Args:
        section_id: 要写的章节 ID（来自 outline）
        state: 共享 ResearchState

    Returns:
        {"section_id": section_id, "content": "# Markdown..."}
    """
    writer = get_writer_instance()
    try:
        return await writer.write_one_section(section_id=section_id, state=state)
    except Exception as e:
        logger.exception(f"write_section[{section_id}] failed: {e}")
        return {"section_id": section_id, "content": "", "error": str(e)}
