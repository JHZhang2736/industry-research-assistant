"""长期记忆引擎（mem0 封装）+ 行业分类器。

两层记忆：
- 偏好层：scope = user_id
- 方法规范层(SOP)：scope = f"sop::{industry}"
"""

from typing import List, Dict, Any, Optional

# 4 个预置行业的关键词表（命中即归类；落不到则 general）
_INDUSTRY_KEYWORDS: Dict[str, List[str]] = {
    "智慧交通": ["智慧交通", "车路协同", "智慧高速", "智能公交", "智慧停车", "交通大脑", "自动驾驶", "交通"],
    "金融科技": ["金融科技", "fintech", "支付", "数字货币", "区块链金融", "监管科技", "银行", "证券", "保险科技"],
    "医疗健康": ["医疗健康", "创新药", "医疗", "医药", "生物医药", "医疗器械", "诊断", "健康"],
    "能源电力": ["能源电力", "新能源", "储能", "电力", "光伏", "风电", "氢能", "电网", "碳中和"],
}


def classify_industry(query: str) -> str:
    """把研究问题归到 4 个预置行业之一，落不到返回 'general'。"""
    if not query:
        return "general"
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                return industry
    return "general"


import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("memory_engine")


def _extract_results(search_ret: Any) -> List[Dict[str, Any]]:
    """兼容 mem0 search 的两种返回形状：{"results": [...]} 或裸 list。"""
    if isinstance(search_ret, dict):
        return search_ret.get("results", []) or []
    if isinstance(search_ret, list):
        return search_ret
    return []


def _memory_text(item: Dict[str, Any]) -> str:
    """取记忆文本，兼容字段名 memory / text。"""
    return item.get("memory") or item.get("text") or ""


class MemoryEngine:
    """mem0 封装：偏好层(user_id) + 方法规范层(sop::industry)。

    所有方法 best-effort：读失败返回空，写失败静默。
    """

    def __init__(self) -> None:
        from mem0 import Memory
        self._mem = Memory.from_config(self._build_config())

    @staticmethod
    def _build_config() -> Dict[str, Any]:
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
        return {
            "vector_store": {
                "provider": "milvus",
                "config": {
                    "collection_name": "mem0_memories",
                    "embedding_model_dims": 1024,
                    "url": milvus_uri,
                    "metric_type": "COSINE",
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "qwen-plus",
                    "api_key": api_key,
                    "openai_base_url": base_url,
                    "temperature": 0.2,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "text-embedding-v4",
                    "api_key": api_key,
                    "openai_base_url": base_url,
                    "embedding_dims": 1024,
                },
            },
        }

    # ── 偏好层（scope = user_id）─────────────────────────────
    def remember_preferences(self, user_id: str, messages: List[Dict[str, Any]]) -> None:
        if not user_id or not messages:
            return
        try:
            self._mem.add(messages, user_id=user_id, metadata={"type": "preference"})
        except Exception as e:
            logger.warning(f"remember_preferences failed: {e}")

    def recall_preferences(self, user_id: str, query: str, k: int = 5) -> str:
        if not user_id or not query:
            return ""
        try:
            ret = self._mem.search(query, user_id=user_id, limit=k)
            items = [
                _memory_text(it)
                for it in _extract_results(ret)
                if (it.get("metadata") or {}).get("type") == "preference"
            ]
            items = [t for t in items if t]
            if not items:
                return ""
            lines = ["[用户偏好]"] + [f"- {t}" for t in items] + [""]
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"recall_preferences failed: {e}")
            return ""

    # ── 方法规范层（scope = "sop::{industry}"）───────────────
    @staticmethod
    def _sop_scope(industry: str) -> str:
        return f"sop::{industry or 'general'}"

    @staticmethod
    def _lesson_text(fb: Dict[str, Any]) -> str:
        """把一条 CriticFeedback 提炼成可复用的"研究教训"文本。"""
        issue = fb.get("issue_type", "issue")
        desc = fb.get("description", "")
        sugg = fb.get("suggestion", "")
        return f"教训({issue}): {desc} → 改进: {sugg}".strip()

    def remember_lessons(self, industry: str, critic_feedback: List[Dict[str, Any]],
                         quality_score: float) -> None:
        if not critic_feedback:
            return
        scope = self._sop_scope(industry)
        for fb in critic_feedback:
            text = self._lesson_text(fb)
            if not text:
                continue
            try:
                self._mem.add(
                    [{"role": "user", "content": text}],
                    user_id=scope,
                    metadata={"type": "sop", "issue_type": fb.get("issue_type", "issue")},
                )
            except Exception as e:
                logger.warning(f"remember_lessons add failed: {e}")

    def recall_lessons(self, industry: str, query: str, k: int = 5,
                       min_recurrence: int = 2) -> str:
        if not query:
            return ""
        scope = self._sop_scope(industry)
        try:
            ret = self._mem.search(query, user_id=scope, limit=k)
            items = [
                _memory_text(it)
                for it in _extract_results(ret)
                if (it.get("metadata") or {}).get("type") == "sop"
            ]
            items = [t for t in items if t]
            if not items:
                return ""
            lines = ["[过往研究教训（请在规划时主动规避）]"] + [f"- {t}" for t in items] + [""]
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"recall_lessons failed: {e}")
            return ""
