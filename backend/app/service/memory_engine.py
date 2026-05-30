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
