"""
信源综合可信度打分：域名权威（客观）+ 时效衰减。

final_credibility = clamp( max(域名分, LLM 分) * recency_weight, 0, 1 )

- 域名命中时与 LLM 分取 max：避免压低 LLM 识别出的、表里暂无的权威源。
- recency 只奖近罚远，无日期视为中性（不罚），避免把「日期未知」误判成旧。
- 本模块为纯函数，不做硬丢弃阈值判断（阈值在 scout 入库处统一应用）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from config.source_authority import score_domain
except ImportError:
    from app.config.source_authority import score_domain


def recency_weight(date_str: Optional[str], now: Optional[datetime] = None) -> float:
    """按发布日期返回时效乘子；无法解析或为空时返回中性 1.0。

    博查 datePublished / dateLastCrawled 均为发布时间，形如
    2025-02-23T08:18:30+08:00（ISO8601 带时区）。
    """
    if not date_str or not isinstance(date_str, str):
        return 1.0
    now = now or datetime.now(timezone.utc)

    raw = date_str.strip().replace("Z", "+00:00")
    dt: Optional[datetime] = None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # 退化尝试：仅日期部分 YYYY-MM-DD
        try:
            dt = datetime.fromisoformat(raw[:10])
        except ValueError:
            return 1.0

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    age_days = (now - dt).total_seconds() / 86400.0
    if age_days < 0:
        return 1.0
    if age_days <= 90:
        return 1.0
    if age_days <= 365:
        return 0.9
    if age_days <= 1095:
        return 0.75
    return 0.6


def final_credibility(
    llm_score,
    url: str,
    date_str: Optional[str],
    now: Optional[datetime] = None,
) -> float:
    """综合可信度：max(域名分, LLM 分) * 时效乘子，截断到 [0,1]。"""
    try:
        llm = float(llm_score)
    except (TypeError, ValueError):
        llm = 0.5

    dom = score_domain(url)
    base = max(dom, llm) if dom is not None else llm
    final = base * recency_weight(date_str, now=now)
    return max(0.0, min(1.0, final))
