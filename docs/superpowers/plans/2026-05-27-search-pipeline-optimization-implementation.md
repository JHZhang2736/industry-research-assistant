# Search Pipeline 并行化优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把一次 deep research 的 wall time 从 30+ min（实测 1800s timeout）压到 < 15 min，靠 Scout 多 query 并行 + Writer 6 章节并行 + provider 级 Semaphore 限流。零质量退化（coherence/citation/relevance 维持质量护栏内）。

**Architecture:** 节点级保持顺序（不动 LangGraph 拓扑），节点内引入 3 个并行点：① Scout `_execute_deep_search` 内 query 级 `asyncio.gather`，② Writer `process` 内 6 章节 `asyncio.gather`，③ Bocha API 调用走全局 `BOCHA_SEM`。`_synthesize_report` 仍串行兜底前后一致性。3 个 provider 级 `asyncio.Semaphore`（DASHSCOPE / DEEPSEEK / BOCHA）共享于所有 agent，env 可调。

**Tech Stack:** Python 3.11+ asyncio / LangGraph 0.2+ / existing tenacity (eval-side only) / pytest（仅用作 eval 单测回归保护，service 层不加新单测，与项目现状一致）

**Spec reference:** `docs/superpowers/specs/2026-05-27-search-pipeline-optimization-design.md`（commit 599a1f2）

---

## File Structure

```
backend/app/service/deep_research_v2/
├── concurrency.py                # NEW: 3 provider semaphores + sem_status() helper
├── agents/
│   ├── base.py                   # MODIFY: call_llm wrap LLM call in provider-selected Semaphore
│   ├── scout.py                  # MODIFY: extract _ingest_facts helper; wrap Bocha call in BOCHA_SEM;
│   │                             #          _execute_deep_search inner for-loop → asyncio.gather
│   └── writer.py                 # MODIFY: process() chapter for-loop → asyncio.gather
└── graph.py                      # MODIFY: log sem_status() at review-node entry

backend/.env.example              # MODIFY: 3 new optional env vars with comments
```

**Responsibilities:**

- `concurrency.py`: single source of truth for provider rate-limit ceilings; pure data + 1 helper, no side effects on import
- `base.py`: every LLM call across all 6 agents auto-routes to the right provider sem
- `scout.py`: Scout's deep search becomes query-parallel within each section; helper extraction precedes parallelization (smaller diff to reason about)
- `writer.py`: section drafting parallelizes; synthesize stays serial
- `graph.py`: single observation log at review-node entry for tuning sem ceilings

**Why these boundaries:**
- `concurrency.py` is shared infra → its own file
- `base.py` change is a 5-line wrap on existing code, no extraction needed
- Scout has 2 distinct changes (helper extraction + parallelization), but they live in the same file because they touch the same method (`_execute_deep_search`); doing extraction first keeps the second diff small
- Writer has 1 change (loop → gather) so no extraction needed

---

## Task 1: 创建 `concurrency.py`

**Files:**
- Create: `backend/app/service/deep_research_v2/concurrency.py`

- [ ] **Step 1: 创建 `concurrency.py`**

```python
"""Global provider-level semaphores for LLM and search API rate protection.

Shared across all agents to bound concurrent in-flight requests under provider
QPM limits. In-flight count ≠ QPM since each LLM call takes 1-30s; 10-20
in-flight roughly maps to 30-60 QPM in practice.

Configurable via env:
  DASHSCOPE_MAX_INFLIGHT  (default 10)
  DEEPSEEK_MAX_INFLIGHT   (default 20)
  BOCHA_MAX_INFLIGHT      (default 8)
"""
from __future__ import annotations

import asyncio
import os


DASHSCOPE_MAX_INFLIGHT = int(os.getenv("DASHSCOPE_MAX_INFLIGHT", "10"))
DEEPSEEK_MAX_INFLIGHT  = int(os.getenv("DEEPSEEK_MAX_INFLIGHT", "20"))
BOCHA_MAX_INFLIGHT     = int(os.getenv("BOCHA_MAX_INFLIGHT", "8"))

DASHSCOPE_SEM = asyncio.Semaphore(DASHSCOPE_MAX_INFLIGHT)
DEEPSEEK_SEM  = asyncio.Semaphore(DEEPSEEK_MAX_INFLIGHT)
BOCHA_SEM     = asyncio.Semaphore(BOCHA_MAX_INFLIGHT)


def get_llm_semaphore(base_url: str) -> asyncio.Semaphore:
    """Select the right semaphore for an LLM provider based on its base_url.

    Default falls back to DASHSCOPE_SEM (most conservative) when base_url
    doesn't match a known provider.
    """
    if "dashscope" in base_url:
        return DASHSCOPE_SEM
    if "deepseek" in base_url:
        return DEEPSEEK_SEM
    return DASHSCOPE_SEM


def sem_status() -> dict:
    """Diagnostic snapshot of current in-flight counts.

    Reads Semaphore._value which is a stable Python 3.4+ attribute.
    Used by graph.py review-node to log peak concurrency.
    """
    return {
        "dashscope_inflight": DASHSCOPE_MAX_INFLIGHT - DASHSCOPE_SEM._value,
        "deepseek_inflight":  DEEPSEEK_MAX_INFLIGHT  - DEEPSEEK_SEM._value,
        "bocha_inflight":     BOCHA_MAX_INFLIGHT     - BOCHA_SEM._value,
    }
```

- [ ] **Step 2: 验证 import 通过**

Run:
```bash
cd backend && python -c "from app.service.deep_research_v2.concurrency import DASHSCOPE_SEM, DEEPSEEK_SEM, BOCHA_SEM, get_llm_semaphore, sem_status; print('OK', sem_status())"
```
Expected: `OK {'dashscope_inflight': 0, 'deepseek_inflight': 0, 'bocha_inflight': 0}`

- [ ] **Step 3: 验证 eval 单测仍 pass**

Run:
```bash
cd backend && python -m pytest app/eval/tests/ -q
```
Expected: `51 passed`

- [ ] **Step 4: Commit**

```bash
git add backend/app/service/deep_research_v2/concurrency.py
git commit -m "feat(perf): 新增 provider 级 Semaphore（DASHSCOPE/DEEPSEEK/BOCHA）

3 个全局 asyncio.Semaphore 限并发 in-flight 请求；env 可调。
get_llm_semaphore(base_url) 路由；sem_status() 诊断。
为后续 Scout/Writer 并行化提供限流保护。"
```

---

## Task 2: `BaseAgent.call_llm` 加 sem wrap

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/base.py`

- [ ] **Step 1: 读现状定位**

```bash
cd backend && grep -n "response = await asyncio.to_thread" app/service/deep_research_v2/agents/base.py
```
Expected: 一行结果，记下行号（约 99 行附近）。

- [ ] **Step 2: 在文件顶部加 import（如已有则跳过）**

打开 `backend/app/service/deep_research_v2/agents/base.py`，在现有 `import` 区域末尾追加：

```python
from ..concurrency import get_llm_semaphore
```

- [ ] **Step 3: 修改 `call_llm`，wrap LLM 调用**

定位到 `async def call_llm(...)` 方法内 `response = await asyncio.to_thread(self.client.chat.completions.create, **kwargs)` 这一段。

**Current**（约 99 行附近）:

```python
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                **kwargs
            )
```

**Change to**:

```python
            # Bound concurrent in-flight LLM calls per provider to stay under QPM
            sem = get_llm_semaphore(getattr(self.client, "base_url", "") or "")
            async with sem:
                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    **kwargs
                )
```

注意：保持原有 `kwargs` 构造和 try/except 框架不变。只是把 `to_thread` 那一句包进 `async with sem:`。

- [ ] **Step 4: 验证 service import 不破**

```bash
cd backend && python -c "
import sys; sys.path.insert(0, 'app'); sys.path.insert(0, '.')
from app.service.deep_research_v2.agents.base import BaseAgent
print('base.py import OK')
"
```
Expected: `base.py import OK`

- [ ] **Step 5: 跑 eval 单测确保回归**

```bash
cd backend && python -m pytest app/eval/tests/ -q
```
Expected: `51 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/base.py
git commit -m "feat(perf): call_llm 加 provider Semaphore wrap

每次 LLM 调用按 base_url 路由到 DASHSCOPE_SEM / DEEPSEEK_SEM。
所有 18 处 self.call_llm(...) 调用自动受益，零接口变更。"
```

---

## Task 3: scout.py 抽出 `_ingest_facts` helper（refactor，零行为改动）

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`

**Why this task before parallelization:** `_execute_deep_search` 当前 inline 写 facts/data_points 逻辑约 45 行。直接在循环里并行化会把 gather body 撑得很大不易读。先把 ingestion 抽成 helper，第二步并行化只动 ~10 行循环。

- [ ] **Step 1: 读现状**

Run:
```bash
cd backend && sed -n '855,960p' app/service/deep_research_v2/agents/scout.py | head -110
```

定位到 `_execute_deep_search` 方法内的 `for query in queries:` 循环（约 859 行）。读懂 line 898-941 的 inline 提取 facts + data_points 逻辑。

- [ ] **Step 2: 新增 `_ingest_facts` helper（不动其他代码）**

在 `_execute_deep_search` 方法定义**之前**（约 820 行 def 之前），插入新方法：

```python
    def _ingest_facts(
        self,
        state: ResearchState,
        analysis: Dict[str, Any],
        section_id: str,
        query: str,
        search_type: str,
        depth: int,
    ) -> int:
        """Append extracted facts + data_points from one analysis result into state.

        Returns number of new facts added (after dedup). Pure local mutation;
        safe to call concurrently from multiple coroutines because:
          - state['facts']/['data_points'] are list.append (atomic in asyncio)
          - hypothesis evidence is appended via setdefault (atomic)
          - _is_duplicate_fact reads then writes; under asyncio single-thread,
            no other coroutine can interleave between read and append (no await
            inside the dedup check).
        """
        added_facts = 0
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

                hypothesis_support = fact.get("hypothesis_support")
                if hypothesis_support and fact.get("related_hypothesis"):
                    h_id = fact["related_hypothesis"]
                    for h in state.get("hypotheses", []):
                        if h.get("id") == h_id:
                            if hypothesis_support == "supports":
                                h.setdefault("evidence_for", []).append(content[:100])
                            elif hypothesis_support == "refutes":
                                h.setdefault("evidence_against", []).append(content[:100])

        for dp in analysis.get("data_points", []):
            state["data_points"].append({
                "id": f"dp_{uuid.uuid4().hex[:8]}",
                "name": dp.get("name"),
                "value": dp.get("value"),
                "unit": dp.get("unit", ""),
                "year": dp.get("year"),
                "source": dp.get("source", query),
                "confidence": dp.get("confidence", 0.7),
                "search_depth": depth,
            })

        return added_facts
```

- [ ] **Step 3: 替换 `_execute_deep_search` 内 inline 代码为 helper 调用**

定位 `_execute_deep_search` 方法内 line 898-941（"提取并添加事实" 注释到 "提取数据点" 末尾）。

**Current**（line 898-941）:

```python
            # 提取并添加事实
            added_facts = 0
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
                        "search_type": search_type
                    }
                    state["facts"].append(fact_entry)
                    added_facts += 1

                    # 更新假设证据（如果有）
                    hypothesis_support = fact.get("hypothesis_support")
                    if hypothesis_support and fact.get("related_hypothesis"):
                        h_id = fact["related_hypothesis"]
                        for h in state.get("hypotheses", []):
                            if h.get("id") == h_id:
                                if hypothesis_support == "supports":
                                    h.setdefault("evidence_for", []).append(content[:100])
                                elif hypothesis_support == "refutes":
                                    h.setdefault("evidence_against", []).append(content[:100])

            # 提取数据点
            for dp in analysis.get("data_points", []):
                state["data_points"].append({
                    "id": f"dp_{uuid.uuid4().hex[:8]}",
                    "name": dp.get("name"),
                    "value": dp.get("value"),
                    "unit": dp.get("unit", ""),
                    "year": dp.get("year"),
                    "source": dp.get("source", query),
                    "confidence": dp.get("confidence", 0.7),
                    "search_depth": depth
                })
```

**Replace with**:

```python
            # 提取并添加事实（含数据点） — 抽出 _ingest_facts helper 便于并行调用
            added_facts = self._ingest_facts(
                state, analysis, section_id, query, search_type, depth
            )
```

- [ ] **Step 4: 验证 import + 行为不变**

```bash
cd backend && python -c "
import sys; sys.path.insert(0, 'app'); sys.path.insert(0, '.')
from app.service.deep_research_v2.agents.scout import DeepScout
import inspect
src = inspect.getsource(DeepScout)
assert '_ingest_facts' in src
assert 'added_facts = self._ingest_facts(' in src
print('scout.py refactor OK')
"
```
Expected: `scout.py refactor OK`

- [ ] **Step 5: 跑 eval 单测**

```bash
cd backend && python -m pytest app/eval/tests/ -q
```
Expected: `51 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py
git commit -m "refactor(scout): 抽出 _ingest_facts helper（零行为改动）

把 _execute_deep_search 内 inline 的 facts + data_points 提取逻辑
（45 行）抽成 helper。为下一步 query 级并行铺路，避免 gather body 过大。"
```

---

## Task 4: scout.py `_execute_search` 加 BOCHA_SEM

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`

- [ ] **Step 1: 在文件顶部 import 区域加 BOCHA_SEM 引用**

定位 scout.py 顶部 import 区。追加：

```python
from ..concurrency import BOCHA_SEM
```

- [ ] **Step 2: 修改 `_execute_search` wrap Bocha 调用**

定位约 1100 行 `_execute_search` 方法内 `response = await asyncio.to_thread(requests.post, ...)`。

**Current** (约 1100 行):

```python
            response = await asyncio.to_thread(
                requests.post,
                url,
                headers=headers,
                json=payload,
                timeout=30
            )
```

**Change to**:

```python
            # Bound concurrent Bocha API calls under free-tier ~10 RPS
            async with BOCHA_SEM:
                response = await asyncio.to_thread(
                    requests.post,
                    url,
                    headers=headers,
                    json=payload,
                    timeout=30
                )
```

- [ ] **Step 3: 跑 eval 单测**

```bash
cd backend && python -m pytest app/eval/tests/ -q
```
Expected: `51 passed`

- [ ] **Step 4: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py
git commit -m "feat(perf): _execute_search 加 BOCHA_SEM wrap

把 Bocha API 调用包进全局 BOCHA_SEM（默认 8 并发）。
准备好后续 query 级并行 gather 后不会瞬间撞 Bocha 限流。"
```

---

## Task 5: scout.py `_execute_deep_search` 内 query 级并行

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`

- [ ] **Step 1: 重新读 `_execute_deep_search` 当前状态**

```bash
cd backend && sed -n '820,920p' app/service/deep_research_v2/agents/scout.py
```

经过 Task 3 + 4 后，循环体应该是这样（约 859-913 行）：

```python
        for query in queries:
            # 执行搜索
            results = await self._execute_search(query, count=6)

            if not results:
                continue

            # 立即发送搜索结果供前端展示（增量）
            search_results_for_ui = [
                {
                    "id": f"sr_{uuid.uuid4().hex[:6]}",
                    "title": r.get("title", "")[:80],
                    "source": r.get("site_name", "未知来源"),
                    "url": r.get("url", ""),
                    "snippet": r.get("summary", "") or r.get("snippet", ""),
                    "date": r.get("date", "")
                }
                for r in results[:5]
            ]
            self.add_message(state, "search_results", {
                "results": search_results_for_ui,
                "isIncremental": True,
                "searchType": type_labels.get(search_type, search_type),
                "depth": depth
            })

            # 分析结果
            analysis = await self._analyze_deep_search_results(
                state["query"],
                query,
                results,
                search_type,
                hypotheses,
                state=state,
            )

            if not analysis:
                continue

            # 提取并添加事实（含数据点） — 抽出 _ingest_facts helper 便于并行调用
            added_facts = self._ingest_facts(
                state, analysis, section_id, query, search_type, depth
            )

            self.logger.info(f"Deep search ({search_type}, depth={depth}): +{added_facts} facts for query '{query[:30]}...'")

            # 如果发现更多需要追溯的线索，继续递归（但不超过max_depth）
            if depth < max_depth:
                further_tracing = analysis.get("further_tracing_queries", [])
                if further_tracing:
                    self.add_message(state, "thought", {
                        "agent": self.name,
                        "content": f"发现更深层线索 (深度{depth+1}): {', '.join(further_tracing[:2])}"
                    })
                    await self._execute_deep_search(
                        state, section_id, further_tracing[:2],
                        search_type, hypotheses,
                        depth=depth + 1, max_depth=max_depth
                    )
```

- [ ] **Step 2: 把整个 for 循环替换为 inner func + asyncio.gather**

定位 `for query in queries:` 开始的整块（约 line 859 至 line 957 末尾的递归 await）。

**Replace the entire `for query in queries:` block with**:

```python
        async def _process_one_query(query: str):
            """Process one search query end-to-end. Safe to run concurrently.

            Mutates state via _ingest_facts (which is asyncio-safe — see its
            docstring). The recursive call to _execute_deep_search is kept
            serial within this query's processing to bound recursion fan-out.
            """
            results = await self._execute_search(query, count=6)
            if not results:
                return

            # 立即发送搜索结果供前端展示（增量）
            search_results_for_ui = [
                {
                    "id": f"sr_{uuid.uuid4().hex[:6]}",
                    "title": r.get("title", "")[:80],
                    "source": r.get("site_name", "未知来源"),
                    "url": r.get("url", ""),
                    "snippet": r.get("summary", "") or r.get("snippet", ""),
                    "date": r.get("date", ""),
                }
                for r in results[:5]
            ]
            self.add_message(state, "search_results", {
                "results": search_results_for_ui,
                "isIncremental": True,
                "searchType": type_labels.get(search_type, search_type),
                "depth": depth,
            })

            # 分析结果
            analysis = await self._analyze_deep_search_results(
                state["query"],
                query,
                results,
                search_type,
                hypotheses,
                state=state,
            )

            if not analysis:
                return

            # 提取并添加事实（含数据点）
            added_facts = self._ingest_facts(
                state, analysis, section_id, query, search_type, depth
            )

            self.logger.info(
                f"Deep search ({search_type}, depth={depth}): "
                f"+{added_facts} facts for query '{query[:30]}...'"
            )

            # 递归更深层线索（深度受 max_depth 控）
            if depth < max_depth:
                further_tracing = analysis.get("further_tracing_queries", [])
                if further_tracing:
                    self.add_message(state, "thought", {
                        "agent": self.name,
                        "content": f"发现更深层线索 (深度{depth+1}): {', '.join(further_tracing[:2])}",
                    })
                    await self._execute_deep_search(
                        state, section_id, further_tracing[:2],
                        search_type, hypotheses,
                        depth=depth + 1, max_depth=max_depth,
                    )

        # 并行处理本层所有 query（每 query 内部仍按原顺序：search → analyze → ingest）
        results_or_excs = await asyncio.gather(
            *[_process_one_query(q) for q in queries],
            return_exceptions=True,
        )
        errs = [r for r in results_or_excs if isinstance(r, Exception)]
        if errs:
            self.logger.warning(
                f"[Scout._execute_deep_search] {len(errs)}/{len(queries)} "
                f"queries failed (depth={depth}): "
                f"{[type(e).__name__ for e in errs[:3]]}"
            )
```

- [ ] **Step 3: 确认 `asyncio` 已在 scout.py 顶部 import**

```bash
cd backend && grep -n "^import asyncio" app/service/deep_research_v2/agents/scout.py
```
Expected: 一行（如已 import 则 OK）。如未 import 在文件顶部加 `import asyncio`。

- [ ] **Step 4: 跑 eval 单测**

```bash
cd backend && python -m pytest app/eval/tests/ -q
```
Expected: `51 passed`

- [ ] **Step 5: 静态检查 scout.py 语法**

```bash
cd backend && python -c "
import ast
with open('app/service/deep_research_v2/agents/scout.py', encoding='utf-8') as f:
    ast.parse(f.read())
print('scout.py syntax OK')
"
```
Expected: `scout.py syntax OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py
git commit -m "feat(perf): _execute_deep_search 内 query 级并行（核心优化）

把 for query in queries 串行改成 asyncio.gather(_process_one_query)。
单 query 失败用 return_exceptions=True 兜住不带翻整批；递归调用保持
原层级以限制深度爆炸。预期 Scout wall 1241s → ~160s（受 DASHSCOPE_SEM=10
限流，实测可能更高/低，下一步 smoke 验证）。"
```

---

## Task 6: writer.py 6 章节并行

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/writer.py`

- [ ] **Step 1: 定位 `process` 方法内章节循环**

Run:
```bash
cd backend && sed -n '250,270p' app/service/deep_research_v2/agents/writer.py
```

定位（约 line 257-260）:

```python
        # 逐章节撰写
        for section in state["outline"]:
            if section.get("status") not in ["final", "drafted"]:
                await self._write_section(state, section)
```

- [ ] **Step 2: 确认 `asyncio` 已 import**

```bash
cd backend && grep -n "^import asyncio" app/service/deep_research_v2/agents/writer.py
```
如未 import，在文件顶部加 `import asyncio`。

- [ ] **Step 3: 替换 for 循环为 gather**

**Current** (约 line 257-260):

```python
        # 逐章节撰写
        for section in state["outline"]:
            if section.get("status") not in ["final", "drafted"]:
                await self._write_section(state, section)
```

**Replace with**:

```python
        # 并行撰写各章节
        # _write_section 内部 mutate state['draft_sections'][section_id]，每章节独占自己的 key 不冲突。
        # state['facts']/['data_points']/['insights'] 是 read-only，无竞态。
        # 前后一致性靠 _synthesize_report 阶段兜底（参见 spec §1.3 / §5.2）。
        unfinished = [
            s for s in state["outline"]
            if s.get("status") not in ["final", "drafted"]
        ]
        results = await asyncio.gather(
            *[self._write_section(state, s) for s in unfinished],
            return_exceptions=True,
        )
        errs = [r for r in results if isinstance(r, Exception)]
        if errs:
            self.logger.warning(
                f"[LeadWriter] {len(errs)}/{len(unfinished)} sections failed "
                f"to write: {[type(e).__name__ for e in errs[:3]]}"
            )
```

- [ ] **Step 4: 跑 eval 单测**

```bash
cd backend && python -m pytest app/eval/tests/ -q
```
Expected: `51 passed`

- [ ] **Step 5: 静态检查 writer.py 语法**

```bash
cd backend && python -c "
import ast
with open('app/service/deep_research_v2/agents/writer.py', encoding='utf-8') as f:
    ast.parse(f.read())
print('writer.py syntax OK')
"
```
Expected: `writer.py syntax OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/service/deep_research_v2/agents/writer.py
git commit -m "feat(perf): Writer 6 章节并行撰写

把 process() 内 for section 串行改 asyncio.gather。每章节独占
draft_sections[section_id] key 无写竞态；前后一致性由 synthesize 兜底。
预期 Writer wall 673s → ~100s。"
```

---

## Task 7: graph.py Critic 节点入口 log sem_status

**Files:**
- Modify: `backend/app/service/deep_research_v2/graph.py`

- [ ] **Step 1: 定位 Critic 节点函数**

```bash
cd backend && grep -n "def _review_node\|async def _review_node" app/service/deep_research_v2/graph.py
```
Expected: 一行结果，记下行号。

- [ ] **Step 2: 在 `_review_node` 入口加 sem 状态 log**

打开 `backend/app/service/deep_research_v2/graph.py`，定位 `_review_node` 方法定义。在方法体第一行（紧跟函数签名和 docstring，如有）加 log。

**示例**（具体行视实际代码而定）:

```python
    async def _review_node(self, state: ResearchState) -> dict:
        """Critic 评审节点."""
        # 记录此刻 in-flight 峰值，便于实施后调优 sem 上限
        from .concurrency import sem_status
        self.logger.info(f"[concurrency] in-flight at review entry: {sem_status()}")

        self._emit_phase_start("reviewing", "开始评审")
        self._maybe_cancel(state)
        # ... existing code继续
```

注意：实际代码已有 `_emit_phase_start` 和 `_maybe_cancel` 模式（参见迁移后的其他节点），把 sem log 放在它们**之前**作为第一句。如果原本就没有这两个调用，仍把 sem log 加在方法体最开头（紧跟 docstring）。

- [ ] **Step 3: 跑 eval 单测**

```bash
cd backend && python -m pytest app/eval/tests/ -q
```
Expected: `51 passed`

- [ ] **Step 4: 静态语法检查**

```bash
cd backend && python -c "
import ast
with open('app/service/deep_research_v2/graph.py', encoding='utf-8') as f:
    ast.parse(f.read())
print('graph.py syntax OK')
"
```
Expected: `graph.py syntax OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/service/deep_research_v2/graph.py
git commit -m "feat(perf): Critic 节点入口 log sem_status 用于调优

在 review 阶段记录 in-flight 峰值，便于跑完 smoke 后判断
DASHSCOPE_MAX_INFLIGHT/DEEPSEEK_MAX_INFLIGHT 是否撞顶可继续提高。"
```

---

## Task 8: `.env.example` 补 3 个并发上限环境变量

**Files:**
- Modify: `backend/.env.example`

- [ ] **Step 1: 在 .env.example 末尾 "Eval Framework" 之前或之后加并发段**

定位 `backend/.env.example` 末尾（约 line 90-95，"其他配置" 之前）。追加：

```
# ==================== Deep Research 并发上限 ====================
# 控制 service/deep_research_v2/concurrency.py 里的 provider 级 Semaphore。
# in-flight 计数 ≠ QPM（每次 LLM call 1-30s），保守默认值远低于厂商 QPM 上限。
# 跑完一次研究后看日志的 [concurrency] in-flight 峰值，撞顶就调高。

# DashScope (qwen-max/qwen-plus，QPM ~60)
# DASHSCOPE_MAX_INFLIGHT=10

# DeepSeek (deepseek-v3.2/deepseek-chat，QPM ~60)
# DEEPSEEK_MAX_INFLIGHT=20

# Bocha 搜索 API（免费档 ~10 RPS）
# BOCHA_MAX_INFLIGHT=8
```

注意：3 条都加 `#` 注释掉，让用户按需打开。代码里有 default 值。

- [ ] **Step 2: 验证 .env.example 仍可读（不会被 dotenv 解析失败）**

```bash
cd backend && python -c "
from dotenv import dotenv_values
config = dotenv_values('.env.example')
print('parsed', len(config), 'keys; sample DASHSCOPE_MAX_INFLIGHT:', config.get('DASHSCOPE_MAX_INFLIGHT', '(commented out, OK)'))
"
```
Expected: `parsed N keys; sample DASHSCOPE_MAX_INFLIGHT: (commented out, OK)` 或类似输出（数字 N 取决于 .env.example 当前 key 总数）。

- [ ] **Step 3: Commit**

```bash
git add backend/.env.example
git commit -m "docs(env): .env.example 加 3 个并发上限可选 env 变量

DASHSCOPE_MAX_INFLIGHT / DEEPSEEK_MAX_INFLIGHT / BOCHA_MAX_INFLIGHT
均为可选；默认值已在 concurrency.py 内；按需 uncomment 覆盖。"
```

---

## Task 9: Smoke benchmark 验证 + 报告

**Files:**
- Create: `docs/superpowers/reports/2026-05-27-parallel-optimization-smoke.md`

- [ ] **Step 1: 跑 smoke 实测**

⚠️ 前提：PG/Redis 已起，5 个 API key 都在 env。建议把 `EVAL_RESEARCH_TIMEOUT_SEC` 调到 3000（50 min）防意外 timeout：

```bash
cd backend && \
  EVAL_RESEARCH_TIMEOUT_SEC=3000 \
  python -m app.eval.cli smoke \
    --query "新能源汽车2024年市场现状" \
    --case-id parallel-001
```

Expected: 跑完 ~10-15 min，控制台 `Smoke complete`，产出 `docs/eval-results/YYYY-MM-DD-smoke-*.md`。

如果第一次跑就出错（如 import / 限流 / 数据竞态），抓错栈定位 Task 1-7 哪步出问题，回到对应 task 修。

- [ ] **Step 2: 抓 timing + 评分**

```bash
cd backend && python -c "
import sys; sys.path.insert(0, 'app'); sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from app.service.checkpoint_service import CheckpointService
from collections import defaultdict

state = CheckpointService().load_checkpoint('parallel-001')
logs = state.get('logs') or []
print(f'phase: {state.get(\"phase\")} / iteration: {state.get(\"iteration\")}/{state.get(\"max_iterations\")}')
print(f'final_report len: {len(state.get(\"final_report\") or \"\")}')
print(f'facts: {len(state.get(\"facts\") or [])}, refs: {len(state.get(\"references\") or [])}')
print(f'critic_feedback: {len(state.get(\"critic_feedback\") or [])}, resolved: {sum(1 for f in state.get(\"critic_feedback\") or [] if f.get(\"resolved\"))}')
print(f'total LLM calls: {len(logs)}')

by_agent = defaultdict(lambda: {'count': 0, 'duration_ms': 0})
for l in logs:
    a = l.get('agent', '?')
    by_agent[a]['count'] += 1
    by_agent[a]['duration_ms'] += int(l.get('duration_ms') or 0)
print()
print(f'{\"Agent\":<20} {\"Calls\":>6} {\"LLM time(s)\":>12}')
for a, d in sorted(by_agent.items(), key=lambda x: -x[1]['duration_ms']):
    print(f'{a:<20} {d[\"count\"]:>6} {d[\"duration_ms\"]/1000:>12.1f}')
print(f'Total LLM time: {sum(d[\"duration_ms\"] for d in by_agent.values())/1000:.1f}s')
"
```

记录输出。同时打开 markdown 报表 `docs/eval-results/YYYY-MM-DD-smoke-parallel-001-*.md` 看 7 维 evaluator 分数 + wall time。

- [ ] **Step 3: 对照 spec §7.2 质量护栏**

| 指标 | spec baseline | 通过阈值 | 实测值 | 通过? |
|---|---|---|---|---|
| Wall time | 1800s | **< 1200s** | （填实测） | |
| Scout 阶段 LLM 时间 | 1241s | < 400s（参考值） | | |
| Writer 阶段 LLM 时间 | 673s | < 250s（参考值） | | |
| relevance | 9.5 | **≥ 8.0** | | |
| coherence | 8.67 | **≥ 7.5** ⚠️ 关键护栏 | | |
| completeness | 6.33 | **≥ 5.5** | | |
| citation | 8.07 | **≥ 6.5** | | |
| critic_loop | 0（被截） | **≥ 3** | | |
| cost | 1.13 RMB | **≤ 3 RMB** | | |

如全部通过 → 进 Step 4 写报告；如有指标失败 → 看是哪一栏定位回归（如 coherence 跌破 7.5 说明并行真破坏一致性，回退到 Task 6 前）。

- [ ] **Step 4: 写 benchmark 报告 markdown**

创建 `docs/superpowers/reports/2026-05-27-parallel-optimization-smoke.md`，包含：

```markdown
# Parallel Optimization Smoke Benchmark

> 日期：2026-05-27
> Spec: `docs/superpowers/specs/2026-05-27-search-pipeline-optimization-design.md`
> Plan: `docs/superpowers/plans/2026-05-27-search-pipeline-optimization-implementation.md`

## 实测对照

| 指标 | smoke-003 baseline (优化前) | parallel-001 实测 (优化后) | 阈值 | 通过? |
|---|---|---|---|---|
| Wall time | 1800s (timeout) | <填> | < 1200s | <填> |
| relevance | 9.5 | <填> | ≥ 8.0 | <填> |
| coherence | 8.67 | <填> | ≥ 7.5 | <填> |
| completeness | 6.33 | <填> | ≥ 5.5 | <填> |
| citation | 8.07 | <填> | ≥ 6.5 | <填> |
| critic_loop | 0 | <填> | ≥ 3 | <填> |
| cost (RMB) | 1.13 | <填> | ≤ 3 | <填> |

## 各 agent LLM 时间分布

<贴 Step 2 输出表>

## In-flight 峰值（来自 graph.py review 入口 log）

dashscope_inflight: <填>
deepseek_inflight:  <填>
bocha_inflight:     <填>

## 结论

- 一期目标 (< 15 min wall time)：<达成 / 未达成>
- 质量护栏：<全通过 / coherence 等失败>
- 下一步：<进二期 / 调 sem 上限再跑 / 排查回归>
```

- [ ] **Step 5: Commit benchmark 报告**

```bash
git add docs/superpowers/reports/2026-05-27-parallel-optimization-smoke.md
git commit -m "docs(perf): smoke benchmark 报告（一期落地实测）

记录 Scout query 级并行 + Writer 章节并行 + Bocha 限流上线后
首跑 wall time / 7 维 evaluator / in-flight 峰值。"
```

---

## Self-Review

**1. Spec coverage:**

| Spec 章节 | 覆盖 Task |
|---|---|
| §1.1 目标 < 15 min | Task 9 验证 |
| §1.3 不动 LangGraph 拓扑 | 整个 plan 都遵守（仅节点内并行） |
| §2 决策清单 | Task 1（限流模型）/ Task 5（return_exceptions）/ Task 6（数据竞态分析注释） |
| §3.1 4 处并行点流程 | URL 级并行确认不存在 → 删除；Task 4 (Bocha) / Task 5 (query 级) / Task 6 (章节级) |
| §4.1 concurrency.py | Task 1 |
| §4.2 BaseAgent.call_llm wrap | Task 2 |
| §4.3 _execute_search 加 BOCHA_SEM | Task 4 |
| §4.4 _execute_deep_search 并行 + _ingest_facts helper | Task 3 + Task 5 |
| §4.5 URL 级并行 | 已确认不存在循环调用 → 不在 plan 中 |
| §4.6 LeadWriter.process 章节并行 | Task 6 |
| §4.7 sem_status() log | Task 7 |
| §3.3 .env.example 配置 | Task 8 |
| §7 测试策略（不加 service 单测 + smoke 验证） | 每 task 跑 eval 51 单测 + Task 9 smoke |

**Spec 全覆盖。** §4.5 (URL 级并行) 经实际 grep 确认 scout.py 没有循环调用 `deep_read_url`，从 plan 中合理删除。

**2. Placeholder scan:**

无 TBD / TODO / "implement later" / "add appropriate error handling" 等占位符。报告 markdown 模板里有 `<填>`，那是预留给 implementer 填实测值的位置，标记清晰非占位符。

**3. Type consistency:**

- `get_llm_semaphore(base_url: str) -> asyncio.Semaphore`：Task 1 定义，Task 2 使用，签名一致
- `sem_status() -> dict`：Task 1 定义，Task 7 使用
- `_ingest_facts(state, analysis, section_id, query, search_type, depth) -> int`：Task 3 定义并使用
- `BOCHA_SEM` / `DASHSCOPE_SEM` / `DEEPSEEK_SEM`：Task 1 定义；Task 2 通过 `get_llm_semaphore` 间接用 LLM sem；Task 4 直接 import `BOCHA_SEM`
- `_process_one_query(query: str)`：Task 5 inner func，只在 `_execute_deep_search` 内部使用

签名前后一致。

Plan 自检无 issue。
