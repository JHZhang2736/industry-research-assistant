# DeepScout rerank + 客观质量闸门 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 DeepScout 的搜索→抽取链路加上 Bocha 语义 rerank、客观信源可信度（域名权威 + 时效衰减）双闸门，并放宽 summary 截断，让 facts「选择性提取、按质量排序」。

**Architecture:** 在三处搜索分析入口（主研究 / 递归深搜 / 补充搜索）统一插入管线：`guard 注入防护 → 去重 → Bocha rerank（丢 relevance<0.4，取 top10）→ summary[:1000] 喂 LLM → 抽取后按 final_credibility(域名覆盖 LLM 分 × 时效乘子) 硬丢弃 <0.3 → 入库`。新增两个纯函数模块（域名表、组合打分），rerank 与轮转预截断作为 scout 内 helper。writer 写作时按 credibility 降序选 fact。

**Tech Stack:** Python 3.12, asyncio, requests（`asyncio.to_thread` 包装）, pytest（`asyncio_mode=auto`）, unittest.mock。Bocha Rerank API `https://api.bochaai.com/v1/rerank`，model `gte-rerank`（限免）。

**关键约定（已与用户确认）:**
- rerank 阈值 `RERANK_THRESHOLD = 0.4`，`RERANK_TOP_N = 10`，单次最多 `MAX_RERANK_DOCS = 50` 文档（轮转预截断兜底）。
- 可信度硬门 `CREDIBILITY_FLOOR = 0.3`。
- 域名命中与 LLM 分取 `max(域名分, LLM 分)`（避免压低 LLM 识别出的表外权威源）。
- 时效档位：≤3 月=1.0 / 3-12 月=0.9 / 1-3 年=0.75 / >3 年=0.6 / 无日期=1.0（中性不罚）。
- 日期取数沿用 `datePublished or dateLastCrawled`（博查二者均为发布时间, ISO8601 带 UTC+8 时区）。
- summary 截断 `300 → 1000`。
- 覆盖三处搜索路径；rerank 失败降级为「不 rerank，去重后 top10」。

**测试运行目录:** 所有 `pytest` 命令均从 `backend/` 目录执行（该目录有 `pytest.ini` 与 `conftest.py`，使 `app.` 包可导入）。

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `backend/app/config/source_authority.py` | 域名权威表 + `score_domain(url)`（TLD 规则 + 种子中文权威域名） | 新建 |
| `backend/app/service/deep_research_v2/source_scoring.py` | `recency_weight(date)` + `final_credibility(llm, url, date)` | 新建 |
| `backend/app/service/deep_research_v2/agents/scout.py` | 常量、`interleave_unique`、`_rerank`、`_gated_credibility`、三处 analyze 接入、三处 ingestion 闸门 | 修改 |
| `backend/app/service/deep_research_v2/agents/writer.py` | `related_facts` 按 credibility 降序 | 修改 |
| `backend/test/test_deep_research_v2/__init__.py` | 测试包 | 新建 |
| `backend/test/test_deep_research_v2/test_source_authority.py` | Task 1 测试 | 新建 |
| `backend/test/test_deep_research_v2/test_source_scoring.py` | Task 2 测试 | 新建 |
| `backend/test/test_deep_research_v2/test_scout_rerank.py` | Task 3/4 测试 | 新建 |
| `backend/test/test_deep_research_v2/test_scout_gate.py` | Task 5/6 测试 | 新建 |
| `backend/test/test_deep_research_v2/test_writer_sort.py` | Task 7 测试 | 新建 |
| `backend/test/test_security/test_scout_injection.py` | 既有注入测试需 mock 新增的 `_rerank` | 修改 |

---

## Task 0: 创建测试包

**Files:**
- Create: `backend/test/test_deep_research_v2/__init__.py`

- [ ] **Step 1: 建空包文件**

```python
# backend/test/test_deep_research_v2/__init__.py
```

（空文件即可，使该目录成为可发现的测试包。）

- [ ] **Step 2: Commit**

```bash
git add backend/test/test_deep_research_v2/__init__.py
git commit -m "test: 新增 deep_research_v2 测试包"
```

---

## Task 1: 域名权威表 `source_authority.py`

**Files:**
- Create: `backend/app/config/source_authority.py`
- Test: `backend/test/test_deep_research_v2/test_source_authority.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/test/test_deep_research_v2/test_source_authority.py
from app.config.source_authority import score_domain


def test_gov_tld_high_score():
    assert score_domain("https://www.stats.gov.cn/sj/zxfb/202402/t20240228.html") == 0.97
    # 未具名的 .gov.cn 走 TLD 规则
    assert score_domain("http://some-bureau.gov.cn/notice") == 0.95


def test_edu_tld():
    assert score_domain("https://www.tsinghua.edu.cn/page") == 0.9


def test_named_authoritative_domain():
    assert score_domain("https://www.xinhuanet.com/fortune/x.htm") == 0.95
    assert score_domain("https://www.caixin.com/2024/a.html") == 0.85


def test_self_media_low_score():
    assert score_domain("https://mp.weixin.qq.com/s/abc") == 0.4
    assert score_domain("https://zhuanlan.zhihu.com/p/123") == 0.45


def test_subdomain_and_www_stripped():
    # 子域命中母域规则
    assert score_domain("https://finance.people.com.cn/n1/x.html") == 0.95


def test_unknown_returns_none():
    assert score_domain("https://random-blog-xyz.com/post") is None


def test_blank_or_garbage_returns_none():
    assert score_domain("") is None
    assert score_domain("not a url") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run（从 `backend/`）: `python -m pytest test/test_deep_research_v2/test_source_authority.py -v`
Expected: FAIL（`ModuleNotFoundError: app.config.source_authority`）

- [ ] **Step 3: 写实现**

```python
# backend/app/config/source_authority.py
"""
信源域名权威度表 + 打分。

为 DeepScout 的可信度闸门提供「客观锚点」：相比 LLM 主观打分，
域名/TLD 是确定性信号。命中返回 0-1 基准分，未命中返回 None（交回 LLM 分）。

表以中文权威源为主（博查中文搜索的实际命中域名）。需要扩充时
直接往 DOMAIN_SCORES 加条目即可，无需改打分逻辑。
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

# 具名域名基准分（母域写法，子域自动命中）。score ∈ [0,1]
DOMAIN_SCORES = {
    # —— 官方 / 统计 ——
    "stats.gov.cn": 0.97,      # 国家统计局
    "pbc.gov.cn": 0.96,        # 中国人民银行
    "mof.gov.cn": 0.96,        # 财政部
    "ndrc.gov.cn": 0.95,       # 发改委
    # —— 央媒 / 权威媒体 ——
    "xinhuanet.com": 0.95,     # 新华网
    "people.com.cn": 0.95,     # 人民网
    "cctv.com": 0.85,          # 央视
    "chinanews.com.cn": 0.85,  # 中新网
    "ce.cn": 0.85,             # 中国经济网
    # —— 财经权威 ——
    "caixin.com": 0.85,        # 财新
    "yicai.com": 0.82,         # 第一财经
    "cnstock.com": 0.8,        # 中国证券网
    "stcn.com": 0.8,           # 证券时报
    "cs.com.cn": 0.8,          # 中证网
    "21jingji.com": 0.8,       # 21 世纪经济报道
    # —— 研究 / 咨询 ——
    "iresearch.com.cn": 0.78,  # 艾瑞咨询
    "gartner.com": 0.9,
    "mckinsey.com": 0.85,
    "statista.com": 0.8,
    # —— 一般科技媒体 ——
    "jiemian.com": 0.7,        # 界面新闻
    "36kr.com": 0.6,
    "huxiu.com": 0.6,
    # —— 自媒体 / 社区（低）——
    "mp.weixin.qq.com": 0.4,   # 公众号
    "baijiahao.baidu.com": 0.4,
    "zhihu.com": 0.45,
    "zhuanlan.zhihu.com": 0.45,
    "xueqiu.com": 0.5,
}

# TLD 后缀规则（确定性、零维护）。按列表顺序优先匹配。
TLD_RULES = [
    (".gov.cn", 0.95),
    (".gov", 0.95),
    (".edu.cn", 0.9),
    (".edu", 0.9),
]


def score_domain(url: str) -> Optional[float]:
    """根据 URL 域名返回客观权威基准分；无法判定返回 None。

    匹配优先级：具名域名（最长后缀优先）> TLD 规则 > None。
    """
    if not url or not isinstance(url, str):
        return None
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return None
    if not host:
        return None
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]

    # 具名域名：精确或子域命中，取最长匹配（finance.people.com.cn -> people.com.cn）
    best_score: Optional[float] = None
    best_len = -1
    for dom, sc in DOMAIN_SCORES.items():
        if host == dom or host.endswith("." + dom):
            if len(dom) > best_len:
                best_score = sc
                best_len = len(dom)
    if best_score is not None:
        return best_score

    # TLD 规则
    for suffix, sc in TLD_RULES:
        if host.endswith(suffix):
            return sc

    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/test_deep_research_v2/test_source_authority.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/config/source_authority.py backend/test/test_deep_research_v2/test_source_authority.py
git commit -m "feat: 新增信源域名权威度表与 score_domain"
```

---

## Task 2: 组合打分 `source_scoring.py`

**Files:**
- Create: `backend/app/service/deep_research_v2/source_scoring.py`
- Test: `backend/test/test_deep_research_v2/test_source_scoring.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/test/test_deep_research_v2/test_source_scoring.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/test_deep_research_v2/test_source_scoring.py -v`
Expected: FAIL（`ModuleNotFoundError: ...source_scoring`）

- [ ] **Step 3: 写实现**

```python
# backend/app/service/deep_research_v2/source_scoring.py
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/test_deep_research_v2/test_source_scoring.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/source_scoring.py backend/test/test_deep_research_v2/test_source_scoring.py
git commit -m "feat: 新增 final_credibility 组合打分（域名+时效）"
```

---

## Task 3: 轮转去重预截断 `interleave_unique`

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`（模块级函数，加在 `_ensure_str` 之后，约 67 行后）
- Test: `backend/test/test_deep_research_v2/test_scout_rerank.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/test/test_deep_research_v2/test_scout_rerank.py
from app.service.deep_research_v2.agents.scout import interleave_unique


def _r(u):
    return {"url": u, "title": u, "summary": u}


def test_round_robin_order():
    # 两个 query 的结果列表，轮转取：a1,b1,a2,b2...
    out = interleave_unique([[_r("a1"), _r("a2")], [_r("b1"), _r("b2")]], cap=10)
    assert [r["url"] for r in out] == ["a1", "b1", "a2", "b2"]


def test_dedup_by_url_across_lists():
    out = interleave_unique([[_r("x"), _r("y")], [_r("x"), _r("z")]], cap=10)
    assert [r["url"] for r in out] == ["x", "y", "z"]


def test_cap_truncates():
    lists = [[_r(f"a{i}") for i in range(40)], [_r(f"b{i}") for i in range(40)]]
    out = interleave_unique(lists, cap=50)
    assert len(out) == 50


def test_empty_input():
    assert interleave_unique([], cap=50) == []
    assert interleave_unique([[], []], cap=50) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/test_deep_research_v2/test_scout_rerank.py -v`
Expected: FAIL（`ImportError: cannot import name 'interleave_unique'`）

- [ ] **Step 3: 写实现（加在 scout.py 中 `_ensure_str` 函数定义之后、`class DeepScout` 之前）**

```python
def interleave_unique(result_lists, cap: int = 50):
    """跨多个 query 的结果列表做轮转(round-robin) + URL 去重 + 截断到 cap。

    目的：当一个章节多个 query 的结果合并后可能超过 Bocha rerank 单次 50 篇上限时，
    公平地从各 query 取样（而非被某个 query 刷屏），并去掉重复 URL。
    """
    seen = set()
    out = []
    if not result_lists:
        return out
    idx = 0
    remaining = True
    while remaining and len(out) < cap:
        remaining = False
        for lst in result_lists:
            if idx < len(lst):
                remaining = True
                r = lst[idx]
                u = r.get("url", "")
                if u and u in seen:
                    continue
                if u:
                    seen.add(u)
                out.append(r)
                if len(out) >= cap:
                    break
        idx += 1
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/test_deep_research_v2/test_scout_rerank.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v2/test_scout_rerank.py
git commit -m "feat: 新增 interleave_unique 轮转去重预截断"
```

---

## Task 4: `_rerank` helper + 常量 + 缓存

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`
  - 模块顶部加常量（约 23 行 import security 之后）
  - `DeepScout.__init__` 加 `self.rerank_cache`（约 203 行 `self.search_cache` 之后）
  - 加 `async def _rerank`（加在 `_execute_search` 之后，约 1200 行后）
- Test: `backend/test/test_deep_research_v2/test_scout_rerank.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 backend/test/test_deep_research_v2/test_scout_rerank.py 末尾
import json
import pytest
from unittest.mock import AsyncMock

from app.service.deep_research_v2.agents.scout import DeepScout


@pytest.fixture
def scout():
    return DeepScout(
        llm_api_key="k", llm_base_url="http://localhost",
        search_api_key="s", model="qwen-plus",
    )


def _fake_resp(results):
    class R:
        status_code = 200

        def json(self):
            return {"code": 200, "data": {"results": results}}
    return R()


@pytest.mark.asyncio
async def test_rerank_drops_below_threshold_and_sorts(scout, monkeypatch):
    docs = [_r("a"), _r("b"), _r("c")]
    # b 最相关、a 次之、c 低于 0.4 应被丢
    api_results = [
        {"index": 0, "relevance_score": 0.55},
        {"index": 1, "relevance_score": 0.91},
        {"index": 2, "relevance_score": 0.20},
    ]
    monkeypatch.setattr(
        "asyncio.to_thread", AsyncMock(return_value=_fake_resp(api_results))
    )
    out = await scout._rerank("query", docs, top_n=10)
    assert [r["url"] for r in out] == ["b", "a"]          # 排序 + 丢弃 c
    assert out[0]["relevance_score"] == 0.91


@pytest.mark.asyncio
async def test_rerank_top_n_limit(scout, monkeypatch):
    docs = [_r(f"d{i}") for i in range(5)]
    api_results = [{"index": i, "relevance_score": 0.9 - i * 0.05} for i in range(5)]
    monkeypatch.setattr(
        "asyncio.to_thread", AsyncMock(return_value=_fake_resp(api_results))
    )
    out = await scout._rerank("q", docs, top_n=3)
    assert len(out) == 3
    assert [r["url"] for r in out] == ["d0", "d1", "d2"]


@pytest.mark.asyncio
async def test_rerank_api_failure_falls_back(scout, monkeypatch):
    docs = [_r("a"), _r("b"), _r("c")]
    monkeypatch.setattr(
        "asyncio.to_thread", AsyncMock(side_effect=RuntimeError("boom"))
    )
    out = await scout._rerank("q", docs, top_n=2)
    # 降级：不 rerank，去重后取 top_n（原始顺序）
    assert [r["url"] for r in out] == ["a", "b"]


@pytest.mark.asyncio
async def test_rerank_dedup_before_call(scout, monkeypatch):
    docs = [_r("a"), _r("a"), _r("b")]
    captured = {}

    async def fake_to_thread(fn, *a, **k):
        captured["json"] = k.get("json")
        return _fake_resp([{"index": 0, "relevance_score": 0.8},
                           {"index": 1, "relevance_score": 0.7}])
    monkeypatch.setattr("asyncio.to_thread", AsyncMock(side_effect=fake_to_thread))
    out = await scout._rerank("q", docs, top_n=10)
    # 去重后只发 2 篇文档
    assert len(captured["json"]["documents"]) == 2
    assert len(out) == 2


@pytest.mark.asyncio
async def test_rerank_empty_returns_empty(scout):
    assert await scout._rerank("q", [], top_n=10) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/test_deep_research_v2/test_scout_rerank.py -v`
Expected: FAIL（`AttributeError: 'DeepScout' object has no attribute '_rerank'`）

- [ ] **Step 3a: 加模块常量（scout.py，在 `from ..security import ...` 那一行之后）**

```python
# Bocha 语义 rerank 配置
RERANK_API_URL = "https://api.bochaai.com/v1/rerank"
RERANK_MODEL = "gte-rerank"
RERANK_THRESHOLD = 0.4      # relevance_score 低于此值的结果丢弃
RERANK_TOP_N = 10           # rerank 后进入 LLM 抽取的结果数
MAX_RERANK_DOCS = 50        # Bocha rerank 单次最多文档数
RERANK_DOC_MAXLEN = 1500    # 单文档拼接最大字符（rerank 仅取前 512 token）
CREDIBILITY_FLOOR = 0.3     # 最终可信度低于此值的 fact 硬丢弃
```

- [ ] **Step 3b: `__init__` 加缓存（在 `self.search_cache: Dict[str, List] = {}` 之后）**

```python
        self.rerank_cache: Dict[str, List] = {}
```

- [ ] **Step 3c: 加 `_rerank` 方法（在 `_execute_search` 方法之后）**

```python
    async def _rerank(
        self,
        query: str,
        results: List[Dict],
        top_n: int = RERANK_TOP_N,
        threshold: float = RERANK_THRESHOLD,
    ) -> List[Dict]:
        """用 Bocha 语义 rerank 对搜索结果做相关性排序 + 阈值硬丢弃。

        流程：URL 去重 → 截到 MAX_RERANK_DOCS → 调 rerank →
        丢 relevance_score < threshold → 按分降序 → 取 top_n。
        任何失败都降级为「不 rerank，去重后取 top_n（原始顺序）」，不阻塞主流程。
        命中的结果会带上 relevance_score 字段。
        """
        if not results:
            return []

        # 去重（保序）
        seen = set()
        deduped = []
        for r in results:
            u = r.get("url", "")
            if u and u in seen:
                continue
            if u:
                seen.add(u)
            deduped.append(r)

        if len(deduped) <= 1:
            return deduped[:top_n]

        candidates = deduped[:MAX_RERANK_DOCS]

        # 缓存键：query + 候选 URL 集
        cache_key = hashlib.md5(
            (query + "|" + "|".join(r.get("url", "") for r in candidates)).encode()
        ).hexdigest()
        if cache_key in self.rerank_cache:
            return self.rerank_cache[cache_key]

        documents = [
            f"{r.get('title', '')} {r.get('summary', '') or r.get('snippet', '')}"[:RERANK_DOC_MAXLEN]
            for r in candidates
        ]

        try:
            headers = {
                "Authorization": f"Bearer {self.search_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": RERANK_MODEL,
                "query": query,
                "documents": documents,
                "return_documents": False,
            }
            async with BOCHA_SEM:
                response = await asyncio.to_thread(
                    requests.post, RERANK_API_URL,
                    headers=headers, json=payload, timeout=30,
                )
            if response.status_code != 200:
                raise RuntimeError(f"rerank http {response.status_code}")
            data = response.json()
            if data.get("code") != 200:
                raise RuntimeError(f"rerank code {data.get('code')}")

            scored = []
            for item in data.get("data", {}).get("results", []):
                idx = item.get("index")
                score = item.get("relevance_score", 0.0)
                if isinstance(idx, int) and 0 <= idx < len(candidates) and score >= threshold:
                    r = dict(candidates[idx])
                    r["relevance_score"] = score
                    scored.append(r)

            scored.sort(key=lambda r: r.get("relevance_score", 0.0), reverse=True)
            out = scored[:top_n]
            self.rerank_cache[cache_key] = out
            self.logger.info(
                f"Rerank: {len(candidates)} -> {len(out)} kept "
                f"(threshold={threshold}) for query '{query[:30]}...'"
            )
            return out

        except Exception as e:
            self.logger.warning(f"[Rerank] failed, fallback to no-rerank: {e}")
            return deduped[:top_n]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/test_deep_research_v2/test_scout_rerank.py -v`
Expected: PASS（13 passed：含 Task 3 的 4 个）

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v2/test_scout_rerank.py
git commit -m "feat: 新增 _rerank（Bocha 语义排序+阈值过滤+降级）"
```

---

## Task 5: 三处 analyze 接入 rerank + summary 放宽

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`
  - `_analyze_search_results`（约 1202-1263）
  - `_analyze_supplementary_results`（约 484-547）
  - `_analyze_deep_search_results`（约 997-1076）
- Modify: `backend/test/test_security/test_scout_injection.py`（既有两个测试需 mock `_rerank`）
- Test: `backend/test/test_deep_research_v2/test_scout_gate.py`

**说明：** 每处把「`guard_results(results[:N])` 后切片」改为「`guard_results(results)`（全量）→ `await self._rerank(rerank_query, guarded.kept)` → 用 reranked 结果 → `summary[:300]` 改 `summary[:1000]`」。rerank_query 取该路径最具体的查询词。

- [ ] **Step 1: 写失败测试**

```python
# backend/test/test_deep_research_v2/test_scout_gate.py
import json
import pytest
from unittest.mock import AsyncMock

from app.service.deep_research_v2.agents.scout import DeepScout


@pytest.fixture
def scout():
    return DeepScout(
        llm_api_key="k", llm_base_url="http://localhost",
        search_api_key="s", model="qwen-plus",
    )


@pytest.mark.asyncio
async def test_analyze_passes_full_summary_and_uses_rerank(scout, monkeypatch):
    captured = {}

    async def fake_llm(system_prompt, user_prompt, **kwargs):
        captured["user_prompt"] = user_prompt
        return json.dumps({"extracted_facts": []})
    monkeypatch.setattr(scout, "call_llm", AsyncMock(side_effect=fake_llm))

    # _rerank 原样返回（按相关性已排序），用于隔离断言
    rerank_calls = {}

    async def fake_rerank(query, results, **kwargs):
        rerank_calls["query"] = query
        return results
    monkeypatch.setattr(scout, "_rerank", AsyncMock(side_effect=fake_rerank))

    long_summary = "数" * 700  # 700 字，旧逻辑会被截到 300
    results = [{"title": "市场", "url": "http://a", "site_name": "新华网",
                "date": "2025-01-01T00:00:00+08:00", "summary": long_summary}]
    section = {"title": "市场规模", "description": "规模"}

    await scout._analyze_search_results("AI 行业", section, results, hypotheses=[])

    # rerank 用章节标题作为 query
    assert rerank_calls["query"] == "市场规模"
    # summary 放宽到 1000：第 500 个字符仍在 prompt 中（旧逻辑 300 截断会丢）
    assert "数" * 500 in captured["user_prompt"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/test_deep_research_v2/test_scout_gate.py -v`
Expected: FAIL（rerank query 断言失败 / summary 被截到 300）

- [ ] **Step 3a: 改 `_analyze_search_results`**

把（约 1214-1234）：

```python
        # 注入防护：丢弃可疑结果
        guarded = guard_results(
            results[:15],
            text_of=lambda r: f"{r.get('title', '')} {r.get('summary', '')}",
        )
        for dropped, verdict in guarded.dropped:
            self.logger.warning(
                f"[InjectionGuard] 丢弃疑似注入来源 {dropped.get('url', '')}: "
                f"{verdict.matched_patterns}"
            )

        # 格式化保留的搜索结果
        formatted_results = []
        for i, r in enumerate(guarded.kept):
            formatted_results.append(f"""
[{i+1}] {r.get('title', 'N/A')}
URL: {r.get('url', '')}
来源: {r.get('site_name', 'N/A')}
日期: {r.get('date', 'N/A')}
摘要: {r.get('summary', '')[:300]}
""")
```

改为：

```python
        # 注入防护：先丢弃可疑结果（在 rerank 前，不浪费 rerank 名额）
        guarded = guard_results(
            results,
            text_of=lambda r: f"{r.get('title', '')} {r.get('summary', '')}",
        )
        for dropped, verdict in guarded.dropped:
            self.logger.warning(
                f"[InjectionGuard] 丢弃疑似注入来源 {dropped.get('url', '')}: "
                f"{verdict.matched_patterns}"
            )

        # 语义 rerank：按章节相关性排序 + 阈值过滤，取 top_n
        rerank_query = section.get("title") or query
        reranked = await self._rerank(rerank_query, guarded.kept)

        # 格式化保留的搜索结果
        formatted_results = []
        for i, r in enumerate(reranked):
            formatted_results.append(f"""
[{i+1}] {r.get('title', 'N/A')}
URL: {r.get('url', '')}
来源: {r.get('site_name', 'N/A')}
日期: {r.get('date', 'N/A')}
摘要: {r.get('summary', '')[:1000]}
""")
```

- [ ] **Step 3b: 改 `_analyze_supplementary_results`**

把（约 492-502）：

```python
        guarded = guard_results(
            results[:8],
            text_of=lambda r: f"{r.get('title', '')} {r.get('summary', '')}",
        )
        for dropped, verdict in guarded.dropped:
            self.logger.warning(
                f"[InjectionGuard] 补充搜索丢弃 {dropped.get('url', '')}: {verdict.matched_patterns}"
            )
        results_text = []
        for r in guarded.kept:
            results_text.append(f"标题: {r.get('title', 'N/A')}\n来源: {r.get('site_name', 'N/A')}\n内容: {r.get('summary', '')[:300]}")
```

改为：

```python
        guarded = guard_results(
            results,
            text_of=lambda r: f"{r.get('title', '')} {r.get('summary', '')}",
        )
        for dropped, verdict in guarded.dropped:
            self.logger.warning(
                f"[InjectionGuard] 补充搜索丢弃 {dropped.get('url', '')}: {verdict.matched_patterns}"
            )
        reranked = await self._rerank(search_query, guarded.kept)
        results_text = []
        for r in reranked:
            results_text.append(f"标题: {r.get('title', 'N/A')}\n来源: {r.get('site_name', 'N/A')}\n内容: {r.get('summary', '')[:1000]}")
```

- [ ] **Step 3c: 改 `_analyze_deep_search_results`**

把（约 1007-1017）：

```python
        guarded = guard_results(
            results[:6],
            text_of=lambda r: f"{r.get('title', '')} {r.get('summary', '')}",
        )
        for dropped, verdict in guarded.dropped:
            self.logger.warning(
                f"[InjectionGuard] deep_search 丢弃 {dropped.get('url', '')}: {verdict.matched_patterns}"
            )
        results_text = []
        for r in guarded.kept:
            results_text.append(f"标题: {r.get('title', 'N/A')}\n来源: {r.get('site_name', 'N/A')}\n内容: {r.get('summary', '')[:300]}")
```

改为：

```python
        guarded = guard_results(
            results,
            text_of=lambda r: f"{r.get('title', '')} {r.get('summary', '')}",
        )
        for dropped, verdict in guarded.dropped:
            self.logger.warning(
                f"[InjectionGuard] deep_search 丢弃 {dropped.get('url', '')}: {verdict.matched_patterns}"
            )
        reranked = await self._rerank(search_query, guarded.kept)
        results_text = []
        for r in reranked:
            results_text.append(f"标题: {r.get('title', 'N/A')}\n来源: {r.get('site_name', 'N/A')}\n内容: {r.get('summary', '')[:1000]}")
```

- [ ] **Step 3d: 既有注入测试 mock `_rerank`**

在 `backend/test/test_security/test_scout_injection.py` 的两个测试
`test_analyze_search_results_drops_injection_and_adds_preamble` 与
`test_deep_search_results_guarded` 中，在 `monkeypatch.setattr(scout, "call_llm", ...)`
之后各加一行（让 rerank 原样返回，避免真实网络调用）：

```python
    monkeypatch.setattr(
        scout, "_rerank",
        AsyncMock(side_effect=lambda query, results, **kw: results),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```
python -m pytest test/test_deep_research_v2/test_scout_gate.py test/test_security/test_scout_injection.py -v
```
Expected: PASS（gate 新测试 1 个 + 注入 3 个）

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v2/test_scout_gate.py backend/test/test_security/test_scout_injection.py
git commit -m "feat: 三处 analyze 接入 rerank 并放宽 summary 截断至 1000"
```

---

## Task 6: 入库可信度闸门（三处 ingestion）

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`
  - 加 `_gated_credibility` 方法（加在 `_is_duplicate_fact` 之后，约 1436 行后）
  - `_research_section` 主流程入库循环（约 682-723）
  - `_ingest_facts`（约 816-877，加 `url_date_map` 参数）及其调用处 `_process_one_query`（约 960-963）
  - `_supplementary_research` 入库循环（约 348-365）
- Test: `backend/test/test_deep_research_v2/test_scout_gate.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 backend/test/test_deep_research_v2/test_scout_gate.py
def test_gated_credibility_drops_below_floor(scout):
    # 未知域名 + LLM 0.2 + 旧文(>3y) → 0.2*0.6=0.12 < 0.3 → None
    url_date = {"http://x": "2019-01-01T00:00:00+08:00"}
    assert scout._gated_credibility(0.2, "http://x", url_date) is None


def test_gated_credibility_domain_rescues(scout):
    # 权威域名把 LLM 低分救回：max(0.95,0.2)=0.95 → 通过
    v = scout._gated_credibility(0.2, "https://www.xinhuanet.com/x", {})
    assert v is not None and v > 0.9


@pytest.mark.asyncio
async def test_research_section_ingest_applies_gate(scout, monkeypatch):
    # 两条 fact：一条来自权威源（保留），一条低质（丢弃）
    analysis = {
        "extracted_facts": [
            {"content": "权威事实 A", "source_url": "https://www.stats.gov.cn/a",
             "source_name": "统计局", "credibility_score": 0.4, "importance": "high"},
            {"content": "低质事实 B", "source_url": "http://blog-xyz.com/b",
             "source_name": "某博客", "credibility_score": 0.2, "importance": "low"},
        ],
    }
    monkeypatch.setattr(scout, "_analyze_search_results", AsyncMock(return_value=analysis))
    monkeypatch.setattr(scout, "_execute_search", AsyncMock(return_value=[
        {"url": "https://www.stats.gov.cn/a", "title": "t", "summary": "s",
         "site_name": "统计局", "date": "2026-05-01T00:00:00+08:00"},
        {"url": "http://blog-xyz.com/b", "title": "t", "summary": "s",
         "site_name": "blog", "date": "2019-01-01T00:00:00+08:00"},
    ]))

    state = {
        "query": "Q", "facts": [], "data_points": [], "insights": [],
        "hypotheses": [], "iteration": 99, "max_iterations": 1,
        "search_web": True, "search_local": False, "messages": [], "phase": "researching",
    }
    section = {"id": "s1", "title": "章节", "search_queries": ["q1"]}

    await scout._research_section(state, section)

    contents = [f["content"] for f in state["facts"]]
    assert "权威事实 A" in contents          # 高质保留
    assert "低质事实 B" not in contents      # 低质被闸门丢弃
    a = next(f for f in state["facts"] if f["content"] == "权威事实 A")
    assert a["importance"] == "high"          # importance 落库
    assert a["credibility_score"] > 0.9       # 存的是 final_credibility
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/test_deep_research_v2/test_scout_gate.py -v`
Expected: FAIL（`AttributeError: _gated_credibility` / 低质 fact 未被丢弃 / 无 importance）

- [ ] **Step 3a: 加 import 与 `_gated_credibility` 方法**

在 scout.py 顶部 import 区（约 23 行 security import 之后）加：

```python
try:
    from service.deep_research_v2.source_scoring import final_credibility
except ImportError:
    from app.service.deep_research_v2.source_scoring import final_credibility
```

在 `_is_duplicate_fact` 方法之后加：

```python
    def _gated_credibility(self, llm_score, source_url: str, url_date_map: Dict[str, str]):
        """计算 fact 的最终可信度并应用硬丢弃阈值。

        返回 final_credibility（>= CREDIBILITY_FLOOR）或 None（应丢弃）。
        date 从本批搜索结果的 url->date 映射里取（客观、来自 Bocha）。
        """
        date = url_date_map.get(source_url, "")
        final = final_credibility(llm_score, source_url, date)
        if final < CREDIBILITY_FLOOR:
            return None
        return final
```

- [ ] **Step 3b: 改 `_research_section` 入库循环**

在该方法内、`if analysis:` 之后、`for fact in analysis.get("extracted_facts", []):` 循环之前，先建 url->date 映射（`all_results` 在该作用域已存在）：

```python
            url_date_map = {r.get("url", ""): r.get("date", "") for r in all_results}
```

把循环体（约 686-710）：

```python
            for fact in analysis.get("extracted_facts", []):
                content = _ensure_str(fact.get("content"))
                source_url = _ensure_str(fact.get("source_url"))

                # 去重检查
                if self._is_duplicate_fact(content, source_url):
                    duplicate_facts += 1
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": content,
                    "source_url": source_url,
                    "source_name": fact.get("source_name", ""),
                    "source_type": fact.get("source_type", "news"),
                    "credibility_score": fact.get("credibility_score", 0.5),
                    "extracted_at": datetime.now().isoformat(),
                    "related_sections": [section_id],
                    "verified": False,
                    "related_hypothesis": fact.get("related_hypothesis"),
                    "hypothesis_support": fact.get("hypothesis_support"),
                    "metadata": {}
                }
                state["facts"].append(fact_entry)
                added_facts += 1
```

改为：

```python
            for fact in analysis.get("extracted_facts", []):
                content = _ensure_str(fact.get("content"))
                source_url = _ensure_str(fact.get("source_url"))

                # 去重检查
                if self._is_duplicate_fact(content, source_url):
                    duplicate_facts += 1
                    continue

                # 可信度闸门：低于阈值硬丢弃
                final_cred = self._gated_credibility(
                    fact.get("credibility_score", 0.5), source_url, url_date_map
                )
                if final_cred is None:
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": content,
                    "source_url": source_url,
                    "source_name": fact.get("source_name", ""),
                    "source_type": fact.get("source_type", "news"),
                    "credibility_score": final_cred,
                    "importance": fact.get("importance", "medium"),
                    "extracted_at": datetime.now().isoformat(),
                    "related_sections": [section_id],
                    "verified": False,
                    "related_hypothesis": fact.get("related_hypothesis"),
                    "hypothesis_support": fact.get("hypothesis_support"),
                    "metadata": {}
                }
                state["facts"].append(fact_entry)
                added_facts += 1
```

- [ ] **Step 3c: 改 `_ingest_facts` 签名与循环**

把签名（约 816-824）加一个参数：

```python
    def _ingest_facts(
        self,
        state: ResearchState,
        analysis: Dict[str, Any],
        section_id: str,
        query: str,
        search_type: str,
        depth: int,
        url_date_map: Optional[Dict[str, str]] = None,
    ) -> int:
```

在方法体开头加：

```python
        url_date_map = url_date_map or {}
```

把循环体（约 836-853）：

```python
        for fact in analysis.get("extracted_facts", []):
            content = _ensure_str(fact.get("content"))
            source_url = _ensure_str(fact.get("source_url"))

            if not self._is_duplicate_fact(content, source_url):
                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": content,
                    "source_url": source_url,
                    "source_name": fact.get("source_name", ""),
                    "source_type": fact.get("source_type", "news"),
                    "credibility_score": fact.get("credibility_score", 0.5),
                    "related_sections": [section_id],
                    "search_depth": depth,
                    "search_type": search_type,
                }
                state["facts"].append(fact_entry)
                added_facts += 1
```

改为：

```python
        for fact in analysis.get("extracted_facts", []):
            content = _ensure_str(fact.get("content"))
            source_url = _ensure_str(fact.get("source_url"))

            if not self._is_duplicate_fact(content, source_url):
                final_cred = self._gated_credibility(
                    fact.get("credibility_score", 0.5), source_url, url_date_map
                )
                if final_cred is None:
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": content,
                    "source_url": source_url,
                    "source_name": fact.get("source_name", ""),
                    "source_type": fact.get("source_type", "news"),
                    "credibility_score": final_cred,
                    "importance": fact.get("importance", "medium"),
                    "related_sections": [section_id],
                    "search_depth": depth,
                    "search_type": search_type,
                }
                state["facts"].append(fact_entry)
                added_facts += 1
```

- [ ] **Step 3d: 改 `_ingest_facts` 调用处（`_process_one_query` 内，约 961-963）**

把：

```python
            added_facts = self._ingest_facts(
                state, analysis, section_id, query, search_type, depth
            )
```

改为：

```python
            url_date_map = {r.get("url", ""): r.get("date", "") for r in results}
            added_facts = self._ingest_facts(
                state, analysis, section_id, query, search_type, depth, url_date_map
            )
```

- [ ] **Step 3e: 改 `_supplementary_research` 入库循环（约 348-365）**

把：

```python
                    # 添加新事实
                    for fact in analysis.get("extracted_facts", []):
                        content = _ensure_str(fact.get("content"))
                        source_url = _ensure_str(fact.get("source_url"))

                        if not self._is_duplicate_fact(content, source_url):
                            fact_entry = {
                                "id": f"fact_{uuid.uuid4().hex[:8]}",
                                "content": content,
                                "source_url": source_url,
                                "source_name": fact.get("source_name", ""),
                                "source_type": fact.get("source_type", "news"),
                                "credibility_score": fact.get("credibility_score", 0.5),
                                "is_supplementary": True,  # 标记为补充搜索获得
                                "related_sections": []
                            }
                            state["facts"].append(fact_entry)
```

改为：

```python
                    # 添加新事实
                    url_date_map = {r.get("url", ""): r.get("date", "") for r in results}
                    for fact in analysis.get("extracted_facts", []):
                        content = _ensure_str(fact.get("content"))
                        source_url = _ensure_str(fact.get("source_url"))

                        if not self._is_duplicate_fact(content, source_url):
                            final_cred = self._gated_credibility(
                                fact.get("credibility_score", 0.5), source_url, url_date_map
                            )
                            if final_cred is None:
                                continue
                            fact_entry = {
                                "id": f"fact_{uuid.uuid4().hex[:8]}",
                                "content": content,
                                "source_url": source_url,
                                "source_name": fact.get("source_name", ""),
                                "source_type": fact.get("source_type", "news"),
                                "credibility_score": final_cred,
                                "importance": fact.get("importance", "medium"),
                                "is_supplementary": True,  # 标记为补充搜索获得
                                "related_sections": []
                            }
                            state["facts"].append(fact_entry)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/test_deep_research_v2/test_scout_gate.py -v`
Expected: PASS（gate 全部：含 Task 5 的 1 个 + 本任务 3 个）

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v2/test_scout_gate.py
git commit -m "feat: facts 入库加客观可信度硬丢弃闸门并落库 importance"
```

---

## Task 7: writer 按可信度排序选 fact

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/writer.py`（约 372-375 与 631-634）
- Test: `backend/test/test_deep_research_v2/test_writer_sort.py`

**说明：** writer 两处选 `related_facts` 时由「列表顺序」改为「按 credibility 降序、importance 次级」，让高可信 fact 优先进写作上下文。新增一个模块级排序 helper 复用。

- [ ] **Step 1: 写失败测试**

```python
# backend/test/test_deep_research_v2/test_writer_sort.py
from app.service.deep_research_v2.agents.writer import sort_facts_by_quality


def test_sort_by_credibility_desc():
    facts = [
        {"content": "a", "credibility_score": 0.4, "importance": "low"},
        {"content": "b", "credibility_score": 0.9, "importance": "medium"},
        {"content": "c", "credibility_score": 0.7, "importance": "high"},
    ]
    out = sort_facts_by_quality(facts)
    assert [f["content"] for f in out] == ["b", "c", "a"]


def test_importance_breaks_tie():
    facts = [
        {"content": "a", "credibility_score": 0.8, "importance": "low"},
        {"content": "b", "credibility_score": 0.8, "importance": "high"},
    ]
    out = sort_facts_by_quality(facts)
    assert [f["content"] for f in out] == ["b", "a"]


def test_missing_fields_default():
    facts = [{"content": "a"}, {"content": "b", "credibility_score": 0.9}]
    out = sort_facts_by_quality(facts)
    assert out[0]["content"] == "b"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/test_deep_research_v2/test_writer_sort.py -v`
Expected: FAIL（`ImportError: cannot import name 'sort_facts_by_quality'`）

- [ ] **Step 3a: 在 writer.py 加模块级 helper（放在文件 import 之后、类定义之前）**

```python
_IMPORTANCE_RANK = {"high": 2, "medium": 1, "low": 0}


def sort_facts_by_quality(facts):
    """按 (credibility 降序, importance 降序) 排序 facts，高质量优先进写作上下文。"""
    return sorted(
        facts,
        key=lambda f: (
            f.get("credibility_score", 0.5),
            _IMPORTANCE_RANK.get(f.get("importance", "medium"), 1),
        ),
        reverse=True,
    )
```

- [ ] **Step 3b: 改第一处（约 372-375）**

把：

```python
        related_facts = [f for f in state["facts"] if section_id in f.get("related_sections", [])]
        if not related_facts:
            # 如果没有特定关联，使用所有事实
            related_facts = state["facts"][:10]
```

改为：

```python
        related_facts = [f for f in state["facts"] if section_id in f.get("related_sections", [])]
        if not related_facts:
            # 如果没有特定关联，使用所有事实
            related_facts = list(state["facts"])
        # 高可信优先
        related_facts = sort_facts_by_quality(related_facts)[:10]
```

- [ ] **Step 3c: 改第二处（约 631-634）**

把：

```python
        related_facts = [
            f for f in state.get("facts", [])
            if section_id in f.get("related_sections", [])
        ] or list(state.get("facts", [])[:10])
```

改为：

```python
        related_facts = [
            f for f in state.get("facts", [])
            if section_id in f.get("related_sections", [])
        ] or list(state.get("facts", []))
        related_facts = sort_facts_by_quality(related_facts)[:10]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/test_deep_research_v2/test_writer_sort.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/writer.py backend/test/test_deep_research_v2/test_writer_sort.py
git commit -m "feat: writer 按可信度+重要性降序选取 fact"
```

---

## Task 8: 全量回归

- [ ] **Step 1: 跑相关测试套件**

Run（从 `backend/`）:
```
python -m pytest test/test_deep_research_v2 test/test_security/test_scout_injection.py test/test_deep_research_v3 -v
```
Expected: 全部 PASS。注意 `test_deep_research_v3/test_graph_integration.py::test_graph_compiled_has_4_main_nodes` 为既有遗留失败（与本次改动无关），若仅它失败可忽略。

- [ ] **Step 2: 若有失败，按 superpowers:systematic-debugging 排查**

- [ ] **Step 3: 最终确认提交干净**

Run: `git status`
Expected: working tree clean（所有任务已分别 commit）

---

## Self-Review 记录

- **Spec 覆盖：** 三大诉求均落任务——信息丢失(summary 300→1000, Task 5; rerank 取最相关而非最先, Task 4-5)、选择性提取(rerank 0.4 门 Task 4-5 + 可信度 0.3 门 Task 6)、Bocha rerank(Task 4-5)；P1 writer 排序(Task 7)；域名+时效客观锚点(Task 1-2-6)。三处搜索路径全覆盖(Task 5/6)。
- **类型一致性：** `score_domain`/`recency_weight`/`final_credibility`/`interleave_unique`/`_rerank`/`_gated_credibility`/`sort_facts_by_quality` 在定义任务与使用任务中签名一致。`final_credibility` 不做阈值判断（纯函数），阈值由 `_gated_credibility` 用 `CREDIBILITY_FLOOR` 应用。
- **无占位符：** 每个代码步骤均为可直接落地的完整代码。
- **已知遗留：** `test_graph_compiled_has_4_main_nodes` 为预存失败，非本次引入（见项目记忆）。
```