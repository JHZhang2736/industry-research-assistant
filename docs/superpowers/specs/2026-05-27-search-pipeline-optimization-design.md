# Search Pipeline 并行化优化设计 spec

> 日期：2026-05-27
> 范围：`backend/app/service/deep_research_v2/` —— Scout 多 query 并行 + Writer 多章节并行 + 全局限流保护
> 状态：草案 — 待审阅后进入 writing-plans

## 1. 目标与非目标

### 1.1 目标

把一次 deep research 的 wall time **从 30+ min（实测 1800s timeout）压到 < 15 min**，不损失产出质量（核心 evaluator 分数维持在质量护栏内）。

### 1.2 一期 vs 二期

| 阶段 | 内容 | 预期 wall time |
|---|---|---|
| **本 spec（一期）** | Scout query 级并行 + Scout URL 级并行 + Writer 6 章节并行 + provider 级限流保护 | **< 15 min** |
| 二期（不在本 spec 内） | DataAnalyst + CodeWizard 节点级并行 / Critic 简化只评摘要 / Scout 用更轻 LLM model | < 10 min |

二期触发条件：一期跑完仍 > 15 min，或后续有新需求需要进一步压缩。

### 1.3 非目标（明确不做）

- **不改 LangGraph 拓扑**：plan/research/analyze/write/review 五节点仍顺序。只在节点内部并行。
- **不引入磁盘缓存**：现有内存 search_cache 不变，跨 run 重新调 Bocha 接受。
- **不加 service 层 unit test**：与项目现状一致（service 当前 0 单测）。验证靠 smoke 实测 + 51 eval 单测回归。
- **不加 `EVAL_DISABLE_PARALLEL` 回滚开关**：YAGNI；并行实施后稳定即可。
- **不改 LLM model 配置**：deepseek-v3.2 / qwen-plus / qwen-max 维持。性能优化纯靠并行。
- **不并行 `_synthesize_report`**：本质串行（需要看到全部 draft_sections 才能整合，是前后一致性兜底位）。

## 2. 关键决策清单

| 项 | 决策 | 理由 |
|---|---|---|
| 并行手段 | `asyncio.gather(*, return_exceptions=True)` | asyncio 单线程，无需加锁；项目已大量使用 |
| 限流模型 | provider 级全局 `asyncio.Semaphore`，env 可调 | 跨所有 agent 共享，单一真相源；简单可预测 |
| 限流上限 | DASHSCOPE=10 / DEEPSEEK=20 / BOCHA=8 | 保守值，远低于 provider QPM 上限（dashscope/deepseek 60、bocha 10 RPS）；in-flight ≠ QPM（每 call 1-30s） |
| 失败聚合 | 单 query/章节失败 → log warning + 跳过；不带翻整批 | `return_exceptions=True` 捕获；`_synthesize_report` 已能处理章节缺失 |
| 前后一致性 | 不改 prompt，靠 `_synthesize_report` 整合 + Critic 评审兜底 | 当前实现本来就不传 `previous_sections` context，并行不丢一致性 |
| 数据竞态 | 不加锁，依赖 asyncio 单线程 + 单 statement 原子性 | `dict[k] = v` / `list.append` 都是单 bytecode 原子 |
| 监控 | `sem._value` 直读取 in-flight 计数；Critic 入口 log 一次 | 1 行胜过 30 行 wrapper；Python 3.4+ 稳定属性 |
| 验证手段 | Smoke 前后对比 + 质量护栏阈值 + 51 eval 单测回归 | 不写 mock 并发单测（mock 测的是 mock） |

## 3. 总体架构

### 3.1 4 处并行点（节点级仍串行）

```
graph.py 流程（节点级顺序保持，节点内并行）：

  plan (1 LLM, 23s)
    ↓
  research [Scout]
    for section in outline:                              ← 串行 6 章（依赖 outline.section_id 路由 facts）
      queries = [q1, q2, ...qN]                          ← LLM 拆解出 N 个 query
      ▶ asyncio.gather(*[_process_one_query(q) for q in queries], return_exceptions=True)   ← 并行点 #1
          每个 _process_one_query:
            results = await _execute_search(q)            ← Bocha API，受 BOCHA_SEM 限流
            (可选) ▶ asyncio.gather(*[deep_read_url(u) for u in urls[:K]])  ← 并行点 #2（如 search_type=source_tracing）
            analysis = await _analyze_deep_search_results(...)   ← LLM call，受 DASHSCOPE_SEM 限流
            _ingest_facts(state, analysis, section_id, q)        ← 抽出 helper，纯本地写 state
    ↓
  analyze_data (DataAnalyst, 3 LLM, 178s)                ← 不动，小头
    ↓
  analyze_wizard (CodeWizard, 4 LLM, 157s)               ← 不动，小头
    ↓
  write [LeadWriter]
    unfinished = [s for s in outline if s.status not in ('final','drafted')]
    ▶ asyncio.gather(*[_write_section(s) for s in unfinished], return_exceptions=True)   ← 并行点 #3（6 章节）
    _synthesize_report(state)                            ← 串行，前后一致性兜底
    ↓
  review (Critic, 1 LLM, 153s)
    ↓
  [revise / re_research]
    revise 进 write 节点再跑 → 章节并行同样生效
```

### 3.2 新增模块边界

| 文件 | 性质 | 行数 |
|---|---|---|
| `service/deep_research_v2/concurrency.py` | 新增 | ~40 |
| `service/deep_research_v2/agents/base.py` | 修改：`call_llm` 加 sem wrap | +5 |
| `service/deep_research_v2/agents/scout.py` | 修改：`_execute_search` 加 BOCHA_SEM；`_execute_deep_search` 内循环改 gather；抽出 `_ingest_facts` | ~+60 / -30 |
| `service/deep_research_v2/agents/writer.py` | 修改：`process` 内章节循环改 gather | +5 / -3 |
| `service/deep_research_v2/graph.py` | 修改：Critic 节点入口 log `sem_status()` | +3 |

### 3.3 配置（env 可调）

```bash
# backend/.env 可选覆盖
DASHSCOPE_MAX_INFLIGHT=10
DEEPSEEK_MAX_INFLIGHT=20
BOCHA_MAX_INFLIGHT=8
```

不设则用代码默认值。

## 4. 组件设计

### 4.1 `concurrency.py`（新增）

```python
"""Global provider-level semaphores for LLM and search API rate protection.

Shared across all agents to bound concurrent in-flight requests under provider QPM.
"""
import asyncio
import os

# Concurrent in-flight ceilings. Defaults are conservative — well below provider QPM
# (dashscope 60, deepseek 60, bocha free tier ~10 RPS). In-flight count ≠ QPM since
# each LLM call takes 1-30s; 10-20 in-flight is ~30-60 QPM in practice.
DASHSCOPE_MAX_INFLIGHT = int(os.getenv("DASHSCOPE_MAX_INFLIGHT", "10"))
DEEPSEEK_MAX_INFLIGHT  = int(os.getenv("DEEPSEEK_MAX_INFLIGHT", "20"))
BOCHA_MAX_INFLIGHT     = int(os.getenv("BOCHA_MAX_INFLIGHT", "8"))

DASHSCOPE_SEM = asyncio.Semaphore(DASHSCOPE_MAX_INFLIGHT)
DEEPSEEK_SEM  = asyncio.Semaphore(DEEPSEEK_MAX_INFLIGHT)
BOCHA_SEM     = asyncio.Semaphore(BOCHA_MAX_INFLIGHT)


def get_llm_semaphore(base_url: str) -> asyncio.Semaphore:
    """Select the right semaphore for an LLM provider based on its base_url."""
    if "dashscope" in base_url:
        return DASHSCOPE_SEM
    if "deepseek" in base_url:
        return DEEPSEEK_SEM
    return DASHSCOPE_SEM   # default to most conservative


def sem_status() -> dict:
    """Diagnostic snapshot of current in-flight counts. Reads Semaphore._value
    which is a stable Python 3.4+ attribute."""
    return {
        "dashscope_inflight": DASHSCOPE_MAX_INFLIGHT - DASHSCOPE_SEM._value,
        "deepseek_inflight":  DEEPSEEK_MAX_INFLIGHT  - DEEPSEEK_SEM._value,
        "bocha_inflight":     BOCHA_MAX_INFLIGHT     - BOCHA_SEM._value,
    }
```

### 4.2 `BaseAgent.call_llm` 加 sem wrap

```python
# base.py (in call_llm, around the asyncio.to_thread call)
from .concurrency import get_llm_semaphore

sem = get_llm_semaphore(getattr(self.client, "base_url", "") or "")
async with sem:
    response = await asyncio.to_thread(
        self.client.chat.completions.create,
        **kwargs
    )
```

零接口变更，18 处 `self.call_llm(...)` 调用自动受益。

### 4.3 `Scout._execute_search` 加 Bocha 限流

```python
# scout.py (in _execute_search, wrap the Bocha API call)
from ..concurrency import BOCHA_SEM

async with BOCHA_SEM:
    response = await asyncio.to_thread(
        requests.post, url, headers=headers, json=payload, timeout=30
    )
```

### 4.4 `Scout._execute_deep_search` query 级并行

替换原 `for query in queries:` 串行循环：

```python
async def _process_one_query(query: str):
    results = await self._execute_search(query, count=6)
    if not results:
        return

    # UI emit search_results event (was inline, keep as-is)
    ...

    analysis = await self._analyze_deep_search_results(
        state["query"], query, results, search_type, hypotheses, state=state,
    )
    if not analysis:
        return

    self._ingest_facts(state, analysis, section_id, query, search_type, depth)

results_or_excs = await asyncio.gather(
    *[_process_one_query(q) for q in queries],
    return_exceptions=True,
)
errs = [r for r in results_or_excs if isinstance(r, Exception)]
if errs:
    self.logger.warning(
        f"[Scout._execute_deep_search] {len(errs)}/{len(queries)} queries failed: "
        f"{[type(e).__name__ for e in errs[:3]]}"
    )
```

`_ingest_facts` 是把现有 inline fact append + reference add + knowledge_graph update 逻辑抽成 helper（约 30 行）。

### 4.5 `Scout` URL 级并行（条件性）

当前 `_execute_deep_search` 在 `source_tracing` 类型时会调 `deep_read_url` 抽取每个 URL 的正文。这部分如果是 `for url in urls: await deep_read_url(url)` 串行，改为：

```python
extracted = await asyncio.gather(
    *[self.deep_read_url(u, t, q, state=state) for u, t in urls_with_titles[:K]],
    return_exceptions=True,
)
extracted = [e for e in extracted if isinstance(e, dict)]
```

实施时检查实际代码位置：若 `deep_read_url` 当前不在循环里，则跳过本子项（仅做 4.4）。

### 4.6 `LeadWriter.process` 章节级并行

```python
# writer.py (in process, replace the chapter-writing for-loop)
unfinished = [s for s in state["outline"] if s.get("status") not in ["final", "drafted"]]

results = await asyncio.gather(
    *[self._write_section(state, s) for s in unfinished],
    return_exceptions=True,
)
errs = [r for r in results if isinstance(r, Exception)]
if errs:
    self.logger.warning(
        f"[LeadWriter] {len(errs)}/{len(unfinished)} sections failed to write: "
        f"{[type(e).__name__ for e in errs[:3]]}"
    )
```

`_write_section` 内部 mutate `state["draft_sections"][section_id]`，每章节独占自己的 key，不冲突。

### 4.7 监控 log

在 `graph.py` 的 `_review_node`（Critic 节点入口）log 一次：

```python
from .concurrency import sem_status
self.logger.info(f"[concurrency] in-flight snapshot at review: {sem_status()}")
```

跑完一次 smoke 后看峰值是否撞到 max_inflight。撞了说明可以再调高 max。

## 5. 数据流

### 5.1 优化前后 wall time 对比（基于 smoke-003 实测 baseline）

| 阶段 | 优化前 wall | 优化后期望 | 优化方式 |
|---|---|---|---|
| plan | 23s | 23s | 不变 |
| research (Scout) | ~1241s | **~160s** | query 级并行 + sem=10，~1241/10 × 1.3 余量 |
| analyze_data + wizard | 335s | 335s | 不变（一期不做） |
| write | ~673s | **~100s** | 6 章并行 + sem=20，~70s 最长 + 30s synthesize |
| review | 153s | 153s | 不变 |
| revise（1 轮） | timeout 没跑到 | ~150s | 章节并行已生效 |
| **总计** | **~2700s** | **~920s ≈ 15 min** | 70% wall time 节省 |

### 5.2 数据竞态分析

| state 字段 | 操作 | 并发安全 |
|---|---|---|
| `draft_sections[section_id]` | 写：每章节独占 key | ✅ asyncio 单 statement 原子 |
| `facts` | append：多 query 并行 append | ✅ `list.append` 原子 |
| `references` | append + 去重检查 | ✅ 单 statement |
| `messages` | append（add_message） | ✅ |
| `logs` | append（call_llm 自动写） | ✅ |
| `outline / data_points / insights / charts` | 只读 | ✅ |
| `knowledge_graph` | 嵌套 dict 写入 | ✅ |

不加锁，依赖 asyncio 单线程保证。

### 5.3 错误传播

```
单 query 失败
  ↓
return_exceptions=True 捕获 → log warning
  ↓
其他 queries 继续 → ingest 它们的 facts
  ↓
本章节 facts 数偏少 → Writer 写时素材减少 → completeness/citation 略低
  ↓
Critic 可能 catch missing_source 标 issue → revise 阶段补搜
```

研究不中断，质量略降但有自愈路径。

### 5.4 取消信号

LangGraph cancel → `asyncio.CancelledError` 在 await 点传播 → `asyncio.gather` 默认会把 cancel 传给所有子任务 → **`return_exceptions=True` 不吞 `CancelledError`**（Python 特殊行为，gather re-raise）。用户取消语义不变。

## 6. 错误处理

### 6.1 分级

| 失败类型 | 等级 | 处理 |
|---|---|---|
| 单 query Bocha 5xx / 网络 timeout | Local | `_execute_search` 内现有 try/except → 返回 []；上层 `_process_one_query` 见 `if not results: return`；不影响其他 query |
| 单章节 LLM 401 / 429 / 5xx | Local | base.py `call_llm` 当前无 retry（只 raise），被 `return_exceptions=True` 捕获；失败章节 draft_sections 缺失 → synthesize 兜底"暂无章节内容" |
| 章节内 deep_read_url 失败 | Cosmetic | `_check_url` 自身有 try/except 返 None；继续 |
| concurrency.py import 失败 | Suite-fatal | service 启动就失败，立即可见 |
| 全部 query 都失败（如全网络断） | Section-fatal | 该章节 facts=0；Writer 仍能写但无素材 |

### 6.2 retry / limiter 兜底

| 类型 | 策略 |
|---|---|
| LLM 429 / 5xx | **无主动 retry**（service base.py 当前没接 tenacity，只 raise）；被 `return_exceptions=True` 接住，失败章节走 synthesize 兜底 |
| Provider 限流 | Semaphore 在调用前 await，主动等空位 |
| Bocha 5xx | `_execute_search` 现有 try/except 返 [] |

**留作技术债**：service 的 LLM call 没 retry 是已知短板（与 eval/judges 用 tenacity 的设计不一致）。本 spec 不修，保持改动聚焦"只做并行"。后续可统一基础设施。

### 6.3 监控

实施完成后第一次跑 smoke 时，log 中应该看到（Critic 节点入口）：

```
[concurrency] in-flight snapshot at review: {
  'dashscope_inflight': 0,    # review 阶段 LLM 调用已结束
  'deepseek_inflight': 0,
  'bocha_inflight': 0
}
```

但研究中段（Scout 跑时）有峰值。可在 Scout 进 review 前再 log 一次看实际峰值。

## 7. 测试策略

### 7.1 与项目现状对齐：不加 service 单测

理由：
- mock asyncio.gather 测的是 mock 本身，不是真实并发行为，价值低
- 真要测并发安全得跑真实 LLM call，那是 smoke 范畴
- 51 个 eval 框架单测继续 pass，作为回归保护

### 7.2 验证手段

**Smoke 前后对比 + 质量护栏阈值**：

| 指标 | smoke-003 baseline | 优化后期望 | 通过阈值 |
|---|---|---|---|
| **Wall time** | 1800s timeout | < 900s（15 min） | **< 1200s** |
| Scout 阶段 wall | ~1241s | < 250s | **< 400s** |
| Writer 阶段 wall | ~673s | < 150s | **< 250s** |
| relevance | 9.5 | ≥ 9.0 | **≥ 8.0** |
| coherence | 8.67 | ≥ 8.0 | **≥ 7.5** ⚠️ 关键质量护栏 |
| completeness | 6.33 | ≥ 6.0 | **≥ 5.5** |
| citation | 8.07 | ≥ 7.5 | **≥ 6.5** |
| critic_loop | 0（被 timeout 截） | ≥ 5 | **≥ 3** |
| cost | 1.13 RMB | ≤ 2 RMB | **≤ 3 RMB** |

**关键质量护栏**：coherence ≥ 7.5。如跌破说明并行真破坏一致性，要回退。

### 7.3 回归保护

```bash
cd backend && python -m pytest app/eval/tests/ -v
# 期望: 51 passed
```

### 7.4 实施流程

1. 实施 concurrency.py + 4 处改动
2. `pytest app/eval/tests/` → 51 passed
3. 跑 1 个 smoke（同 query "新能源汽车2024年市场现状"，case-id parallel-001）
4. 查 PG checkpoint dump 各 evaluator 分数 + wall time
5. 对照 7.2 阈值；通过则合并；不通过看哪个指标失分定位

## 8. 风险

| 风险 | 缓解 |
|---|---|
| Provider 实际 QPM 比预估低，sem=10/20 仍撞 429 | tenacity retry 兜底；监控发现后调低 max_inflight |
| 6 章节并行写引入隐性竞态（虽然 §5.2 分析认为没有） | smoke 跑完后人工 inspect final_report 看是否有重复段落 / 术语撞车 |
| `_value` 属性在未来 Python 版本变化 | 加 `try/except AttributeError` 5 行 fallback；当前 3.4-3.12 都稳定 |
| coherence 跌破护栏 | 把 `_write_section` prompt 加 "outline 总览" 字段（看到所有章节标题+描述），仍并行写但有全局上下文；二期再做 |
| `_ingest_facts` 抽 helper 改动大于预期 | 实施时若改动过深，先做 4.4-4.7 跳过 4.4 helper 抽取（直接 inline 在 _process_one_query 里） |

## 9. 简历叙事

实施完成后对外可讲：

- 把 deep research 单次 wall time 从 30+ min 压到 < 15 min，**70% 时间节省**
- Provider 级 `asyncio.Semaphore` 限流，跨 agent 共享，env 可调
- `asyncio.gather(return_exceptions=True)` 单失败不带翻整批
- 数据竞态分析：基于 asyncio 单线程 + 单 statement 原子性，零锁设计
- 实测验证（smoke 前后对比 + 7 维 evaluator 分数护栏）
- 一期 < 15 min 后还可加二期（DataAnalyst+Wizard 并行 / Critic 简化）压到 < 10 min

## 10. 不在本 spec 范围（二期可选）

- **DataAnalyst + CodeWizard 节点级并行**：约 158s 节省，需改 graph.py 拓扑
- **Critic 简化为只评摘要 + 大纲一致性**：约 80s 节省，需重写 critic.py prompt
- **Scout 用 qwen-turbo 替代 qwen-plus**：约 50% Scout 时间节省，但 fact 提取质量可能下降
- **跨 run 磁盘缓存 Bocha 结果**：对重复 query 提速明显，但与本 spec 的"性能优化纯靠并行"主轴不一致

---

**实施计划由 writing-plans skill 后续生成。**
