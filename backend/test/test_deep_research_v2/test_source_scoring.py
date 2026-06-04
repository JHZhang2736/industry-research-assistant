from datetime import datetime, timezone, timedelta

from app.service.deep_research_v2.source_scoring import (
    recency_weight,
    final_credibility,
)

NOW = datetime(2026, 6, 4, tzinfo=timezone.utc)


def test_recency_tiers():
    assert recency_weight("", now=NOW) == 1.0                       # 无日期中性
    assert recency_weight((NOW - timedelta(days=30)).isoformat(), now=NOW) == 1.0
    assert recency_weight((NOW - timedelta(days=200)).isoformat(), now=NOW) == 0.9
    assert recency_weight((NOW - timedelta(days=700)).isoformat(), now=NOW) == 0.75
    assert recency_weight((NOW - timedelta(days=2000)).isoformat(), now=NOW) == 0.6


def test_recency_parses_bocha_offset_format():
    # 博查 datePublished 形如 2025-02-23T08:18:30+08:00
    assert recency_weight("2026-05-01T08:00:00+08:00", now=NOW) == 1.0


def test_recency_garbage_is_neutral():
    assert recency_weight("昨天", now=NOW) == 1.0
    assert recency_weight(None, now=NOW) == 1.0


def test_final_domain_overrides_low_llm():
    # 域名权威(0.95) 与 LLM 低分(0.3) 取 max，再乘新鲜乘子(1.0)
    v = final_credibility(0.3, "https://www.xinhuanet.com/x", "", now=NOW)
    assert abs(v - 0.95) < 1e-9


def test_final_uses_llm_when_domain_unknown():
    v = final_credibility(0.6, "https://random-xyz.com/p", "", now=NOW)
    assert abs(v - 0.6) < 1e-9


def test_final_recency_decay_applied():
    # 未知域名 LLM=0.8，>3 年 → 0.8 * 0.6 = 0.48
    old = (NOW - timedelta(days=2000)).isoformat()
    v = final_credibility(0.8, "https://random-xyz.com/p", old, now=NOW)
    assert abs(v - 0.48) < 1e-9


def test_final_llm_missing_defaults_half():
    v = final_credibility(None, "https://random-xyz.com/p", "", now=NOW)
    assert abs(v - 0.5) < 1e-9


def test_final_clamped_0_1():
    v = final_credibility(2.0, "https://www.stats.gov.cn/x", "", now=NOW)
    assert v == 1.0
