# raw_sources 接活 + 数据点抽取收敛 DataAnalyst 独占 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 DeepScout 把 rerank 后原文写进 `state["raw_sources"]` 并停止抽 data_point；DataAnalyst 改读未压缩原文成为唯一抽数 owner；顺带修复 time_series/distributions 丢弃与并发重复计数两个 bug。

**Architecture:** v3 是 LangGraph Plan-and-Execute——`executor_node` 在**一次节点调用内**用 while 循环跑完整个 plan（search→analyze→write），全程共享同一 `state` 对象，节点末尾才 return `merged_*`。因此存在两套并存机制:**(1) in-place 写 `state[...]`** 供节点内 step 间数据流（Writer 读 facts、DataAnalyst 读 raw_sources）;**(2) executor return `merged_*`** 供下个节点 + checkpoint。并发重复计数 bug 只在机制 (2)（切片重叠），本次只改"返回值"，所有 in-place 写保留。

**Tech Stack:** Python 3.12 / pytest / pytest-asyncio / LangGraph / LangChain `@tool`。测试目录 `backend/test/test_deep_research_v3/`，运行命令一律 `cd backend && python -m pytest ...`。

**Spec:** `docs/superpowers/specs/2026-06-05-raw-sources-data-analyst-refactor-design.md`

---

## 文件结构

| 文件 | 职责 | 改动 |
| --- | --- | --- |
| `backend/app/service/deep_research_v2/state.py` | 全局状态 TypedDict + 初始化 | 加 `time_series`/`distributions` 字段 |
| `backend/app/service/deep_research_v2/agents/scout.py` | DeepScout：搜索 + fact + raw_sources | `_ingest_facts` 返回对象+停抽数；`_analyze_deep_search_results` 返回 reranked；`_process_one_query`/`_execute_deep_search`/`search_with_queries` 返回新增对象+写 raw_sources；清 legacy 抽数 |
| `backend/app/service/deep_research_v2/agents/data_analyst.py` | DataAnalyst：唯一抽数 owner | `_extract_data` 改读 raw_sources + 超集 schema + 重算可信度 + 存 time_series/distributions；`extract_data_points` diff 扩展 |
| `backend/app/service/deep_research_v2/executor.py` | plan 调度 + merge | search_section 分支 url 去重合并；analyze_facts 分支 merge time_series/distributions；返回新增字段 |
| `backend/app/service/deep_research_v2/tools.py` | @tool 注册 | `analyze_facts` 返回追加 time_series/distributions |
| `backend/test/test_deep_research_v3/test_state.py` | state 测试 | 加字段断言 |
| `backend/test/test_deep_research_v3/test_scout_raw_sources.py` | **新建** scout 测试 | _ingest_facts/并发/raw_sources/停抽数 |
| `backend/test/test_deep_research_v3/test_executor.py` | executor 测试 | 加 url 去重 + ts/dist 合并 |
| `backend/test/test_deep_research_v3/test_data_analyst_extract.py` | **新建** DataAnalyst 测试 | 读 raw_sources + 超集 schema |

执行顺序依赖：Task 1（state 字段）→ Task 2/3（scout 内部返回值改造）→ Task 4（聚合返回，依赖 3 的 tuple）→ Task 5（清 legacy）→ Task 6（executor）→ Task 7（DataAnalyst，依赖 1 的字段）→ Task 8（tools）→ Task 9（全量回归）。每个 Task 结束时 `test_deep_research_v3` 全绿。

---

## Task 1: state 新增 time_series / distributions 字段

**Files:**
- Modify: `backend/app/service/deep_research_v2/state.py`
- Test: `backend/test/test_deep_research_v3/test_state.py`

- [ ] **Step 1: 写失败测试**

在 `backend/test/test_deep_research_v3/test_state.py` 末尾追加：

```python
def test_initial_state_has_timeseries_and_distributions():
    """create_initial_state 应初始化 time_series / distributions 为空 list"""
    from app.service.deep_research_v2.state import create_initial_state
    state = create_initial_state(query="q", session_id="sid")
    assert state["time_series"] == []
    assert state["distributions"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_state.py::test_initial_state_has_timeseries_and_distributions -v`
Expected: FAIL with `KeyError: 'time_series'`

- [ ] **Step 3: 加字段到 ResearchState 与 create_initial_state**

在 `state.py` 的 `ResearchState` 中，`raw_sources` 声明行下方插入：

```python
    raw_sources: List[Dict[str, Any]]       # 原始来源（网页内容）
    time_series: List[Dict[str, Any]]       # 时间序列数据（DataAnalyst 抽取，仅存待消费）
    distributions: List[Dict[str, Any]]     # 分布/占比数据（DataAnalyst 抽取，仅存待消费）
```

在 `create_initial_state` 的 `raw_sources=[],` 行下方插入：

```python
        raw_sources=[],
        time_series=[],
        distributions=[],
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_state.py -v`
Expected: PASS（含既有 test_state 用例）

- [ ] **Step 5: 提交**

```bash
git add backend/app/service/deep_research_v2/state.py backend/test/test_deep_research_v3/test_state.py
git commit -m "feat: state 新增 time_series/distributions 字段"
```

---

## Task 2: `_ingest_facts` 返回新增 fact 对象 + 停止抽 data_point（保留 hypothesis 就地写）

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`（`_ingest_facts`，约 1093-1163）
- Test: `backend/test/test_deep_research_v3/test_scout_raw_sources.py`（新建）

**说明:** `_ingest_facts` 现在返回 count。改为返回它实际 append 的 fact 对象 list（机制 2 的基础）。**保留** `state["facts"].append`（机制 1）和 hypothesis 就地写（其唯一持久化路径）。**删除** 顶层 `data_points` 入库块（DataAnalyst 接管抽数）。

- [ ] **Step 1: 写失败测试**

新建 `backend/test/test_deep_research_v3/test_scout_raw_sources.py`：

```python
"""DeepScout: raw_sources 写入 + 并发 diff + 停止抽数 测试"""
import asyncio
import pytest

from app.service.deep_research_v2.agents.scout import DeepScout
from app.service.deep_research_v2.state import create_initial_state


def _make_scout():
    return DeepScout(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
        model="qwen-plus",
    )


def test_ingest_facts_returns_appended_objects():
    """_ingest_facts 返回它实际 append 的 fact 对象列表（不再是 count）"""
    scout = _make_scout()
    state = create_initial_state("q", "sid")
    analysis = {
        "extracted_facts": [
            {"content": "事实A", "source_url": "http://a.com", "source_name": "A",
             "credibility_score": 0.9},
            {"content": "事实B", "source_url": "http://b.com", "source_name": "B",
             "credibility_score": 0.9},
        ]
    }
    added = scout._ingest_facts(state, analysis, "sec_1", "q", "follow_up", 1,
                                {"http://a.com": "2026-01-01", "http://b.com": "2026-01-01"})
    assert isinstance(added, list)
    assert len(added) == 2
    assert {f["content"] for f in added} == {"事实A", "事实B"}
    # 仍 in-place 写 state（机制 1 保留）
    assert state["facts"] == added


def test_ingest_facts_still_mutates_hypotheses():
    """守护点 A：保留对 state['hypotheses'] 的就地写"""
    scout = _make_scout()
    state = create_initial_state("q", "sid")
    state["hypotheses"] = [{"id": "h_1", "content": "假设1", "status": "unverified",
                            "evidence_for": [], "evidence_against": []}]
    analysis = {
        "extracted_facts": [
            {"content": "支持证据", "source_url": "http://a.com", "source_name": "A",
             "credibility_score": 0.9, "related_hypothesis": "h_1",
             "hypothesis_support": "supports"},
        ]
    }
    scout._ingest_facts(state, analysis, "sec_1", "q", "follow_up", 1,
                        {"http://a.com": "2026-01-01"})
    assert state["hypotheses"][0]["evidence_for"] == ["支持证据"]


def test_scout_no_longer_emits_data_points():
    """Scout 不再从 analysis 抽 data_point（DataAnalyst 接管）"""
    scout = _make_scout()
    state = create_initial_state("q", "sid")
    analysis = {
        "extracted_facts": [
            {"content": "事实", "source_url": "http://a.com", "source_name": "A",
             "credibility_score": 0.9},
        ],
        "data_points": [{"name": "市场规模", "value": "5000", "unit": "亿元", "year": 2024}],
    }
    scout._ingest_facts(state, analysis, "sec_1", "q", "follow_up", 1,
                        {"http://a.com": "2026-01-01"})
    assert state["data_points"] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_scout_raw_sources.py -v`
Expected: FAIL — `test_ingest_facts_returns_appended_objects`（返回 int 非 list）、`test_scout_no_longer_emits_data_points`（data_points 非空）

- [ ] **Step 3: 改写 `_ingest_facts`**

把 `scout.py` 的 `_ingest_facts` 方法体（签名 `-> int` 起，到 `return added_facts`）整体替换为：

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
    ) -> List[Dict[str, Any]]:
        """把一次分析结果里的 facts 落进 state，并返回本次实际 append 的 fact 对象列表。

        两套机制（见模块/spec 说明）:
          - in-place `state['facts'].append` / hypothesis setdefault: 节点内 step 间数据流，保留。
          - 返回新增对象 list: 供 executor 机制 2 合并（取代旧的切片 diff，修复并发重复计数）。
        data_point 抽取已移交 DataAnalyst，这里不再产出 data_points。
        asyncio 单线程下 append/setdefault 原子，dedup 检查内无 await，可并发安全调用。
        """
        url_date_map = url_date_map or {}
        added: List[Dict[str, Any]] = []
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
                state["facts"].append(fact_entry)   # 机制 1：节点内数据流，保留
                added.append(fact_entry)

                hypothesis_support = fact.get("hypothesis_support")
                if hypothesis_support and fact.get("related_hypothesis"):
                    h_id = fact["related_hypothesis"]
                    for h in state.get("hypotheses", []):
                        if h.get("id") == h_id:
                            if hypothesis_support == "supports":
                                h.setdefault("evidence_for", []).append(content[:100])
                            elif hypothesis_support == "refutes":
                                h.setdefault("evidence_against", []).append(content[:100])

        return added
```

注意：原方法末尾的 `for dp in analysis.get("data_points", []): state["data_points"].append({...})` 整块**删除**（已不在上面新版本里）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_scout_raw_sources.py -v`
Expected: PASS（3 个用例）

> 注：此时 `_process_one_query` 里 `added_facts = self._ingest_facts(...)` 拿到的是 list，日志 `f"+{added_facts} facts"` 会打印 list——不影响功能与现有测试，Task 4 会改掉。

- [ ] **Step 5: 提交**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v3/test_scout_raw_sources.py
git commit -m "feat: _ingest_facts 返回新增 fact 对象并停止抽 data_point"
```

---

## Task 3: `_analyze_deep_search_results` 返回 reranked + 删深搜 prompt 的 data_points

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`（`_analyze_deep_search_results`，约 1284-1365）

**说明:** raw_sources 要存"实际喂给 LLM 的 rerank 后结果"，而 reranked 算在该方法内部。把返回从 `analysis` 改成 `(analysis, reranked)`，供 `_process_one_query` 写 raw_sources。同时删掉深搜 prompt 里的 `data_points` 字段（Scout 不再抽数）。

- [ ] **Step 1: 写失败测试**

在 `test_scout_raw_sources.py` 追加：

```python
@pytest.mark.asyncio
async def test_analyze_deep_search_returns_reranked_tuple(monkeypatch):
    """_analyze_deep_search_results 返回 (analysis, reranked) 二元组"""
    scout = _make_scout()
    docs = [{"url": "http://a.com", "title": "T", "summary": "S",
             "site_name": "A", "date": "2026-01-01", "relevance_score": 0.8}]

    async def fake_rerank(query, results, *a, **k):
        return docs

    async def fake_call_llm(*a, **k):
        return '{"extracted_facts": []}'

    monkeypatch.setattr(scout, "_rerank", fake_rerank)
    monkeypatch.setattr(scout, "call_llm", fake_call_llm)

    result = await scout._analyze_deep_search_results(
        "原始q", "搜索q", docs, "follow_up", [], state=None)
    assert isinstance(result, tuple)
    analysis, reranked = result
    assert reranked == docs
    assert "extracted_facts" in analysis
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_scout_raw_sources.py::test_analyze_deep_search_returns_reranked_tuple -v`
Expected: FAIL —返回的是 dict 而非 tuple（`isinstance(result, tuple)` False）

- [ ] **Step 3: 改返回值 + 删 prompt data_points**

(a) 把 `_analyze_deep_search_results` 的最后一行：

```python
        return self.parse_json_response(response)
```

改为：

```python
        return self.parse_json_response(response), reranked
```

(b) 删掉该方法 prompt JSON 里的 data_points 段（在 `"further_tracing_queries"` 上方）：

```python
    "data_points": [
        {{"name": "指标名", "value": "数值", "unit": "单位", "year": 2024}}
    ],
```

整段删除（连同其上的逗号收尾保持 `"extracted_facts": [...],` 后直接接 `"further_tracing_queries"`）。删除后该段应为：

```python
    "extracted_facts": [
        {{
            "content": "提取的事实陈述（要具体、可验证）",
            "source_name": "来源名称",
            "source_url": "来源URL",
            "source_type": "official/academic/news/report",
            "credibility_score": 0.0-1.0,
            "importance": "high/medium/low",
            "related_hypothesis": "h_1或null",
            "hypothesis_support": "supports/refutes/neutral"
        }}
    ],
    "further_tracing_queries": ["如果发现引用了其他权威来源，建议进一步追溯的查询"],
    "source_reliability": "对本次搜索来源可靠性的评估"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_scout_raw_sources.py::test_analyze_deep_search_returns_reranked_tuple -v`
Expected: PASS

> 注：此处会暂时破坏 `_process_one_query`（它仍按旧的 `analysis = await self._analyze_deep_search_results(...)` 单值接收）。Task 4 紧接着修。**Task 3、4 必须连续完成**，中间不单独跑全量 scout 集成测试。先不提交，直接进 Task 4，合并提交。

---

## Task 4: `_process_one_query` / `_execute_deep_search` / `search_with_queries` 聚合返回 + 写 raw_sources

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`（`_process_one_query` 约 1203-1269、`_execute_deep_search` gather 收尾 约 1271-1282、`search_with_queries` 约 1865-1905）

**说明:** 实现机制 2 的正确 diff（每协程收集自己新增的 facts/sources），并把 reranked 结果按 url 去重写进 `state["raw_sources"]`（机制 1，供同节点内 DataAnalyst 读）同时收进返回 list（机制 2）。删掉 `search_with_queries` 的切片。

- [ ] **Step 1: 写失败测试**

在 `test_scout_raw_sources.py` 追加：

```python
def _fake_search_factory():
    async def fake_execute_search(query, count=6):
        return [{"url": f"http://ex.com/{query}", "title": query, "summary": f"summary {query}",
                 "site_name": "Ex", "date": "2026-01-01", "relevance_score": 0.9}]
    return fake_execute_search


def _fake_analyze_factory():
    async def fake_analyze(original_query, search_query, results, search_type, hypotheses, state=None):
        # 注意：_compute_fact_fingerprint 用 numbers[:3] + CJK关键词[:5] 做指纹。
        # 纯 ASCII / 无数字的 content 会得到相同指纹 → 被误判重复而丢弃。
        # 这里给每个 query 注入一个唯一数字（ord 首字母），保证指纹互异。
        uniq = ord(search_query[0])  # a/b/c/d -> 97/98/99/100
        analysis = {
            "extracted_facts": [
                {"content": f"指标数值 {uniq} 来自查询", "source_url": f"http://ex.com/{search_query}",
                 "source_name": "Ex", "credibility_score": 0.9},
            ],
            "further_tracing_queries": [],
        }
        return analysis, results  # reranked = results
    return fake_analyze


@pytest.mark.asyncio
async def test_search_with_queries_concurrent_no_duplicate(monkeypatch):
    """两个 section 并发跑，返回的 facts/sources 无重复、总数正确（修复并发重复计数）"""
    scout = _make_scout()
    monkeypatch.setattr(scout, "_execute_search", _fake_search_factory())
    monkeypatch.setattr(scout, "_analyze_deep_search_results", _fake_analyze_factory())

    state = create_initial_state("q", "sid")
    res = await asyncio.gather(
        scout.search_with_queries("sec_1", ["a", "b"], state),
        scout.search_with_queries("sec_2", ["c", "d"], state),
    )
    facts = res[0]["facts"] + res[1]["facts"]
    fact_ids = [f["id"] for f in facts]
    assert len(fact_ids) == len(set(fact_ids)), "返回的 fact 不应重复"
    assert len(facts) == 4, "4 个 query 各 1 fact"

    sources = res[0]["sources"] + res[1]["sources"]
    urls = [s["url"] for s in sources]
    assert len(urls) == len(set(urls)), "返回的 source url 不应重复"
    assert len(sources) == 4


@pytest.mark.asyncio
async def test_raw_sources_written_with_relevance(monkeypatch):
    """raw_sources 被写入 state，带 relevance_score / related_sections / text"""
    scout = _make_scout()
    monkeypatch.setattr(scout, "_execute_search", _fake_search_factory())
    monkeypatch.setattr(scout, "_analyze_deep_search_results", _fake_analyze_factory())

    state = create_initial_state("q", "sid")
    await scout.search_with_queries("sec_1", ["a"], state)

    assert len(state["raw_sources"]) == 1
    src = state["raw_sources"][0]
    assert src["url"] == "http://ex.com/a"
    assert src["relevance_score"] == 0.9
    assert src["related_sections"] == ["sec_1"]
    assert src["text"] == "summary a"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_scout_raw_sources.py -v`
Expected: FAIL — 并发用例因切片重叠总数为 8/有重复 id；raw_sources 用例因无写入 `len == 0`；且当前 `_process_one_query` 因 Task 3 的 tuple 改动会抛错（解包不匹配）

- [ ] **Step 3: 改写 `_process_one_query`**

把 `_process_one_query` 内从 `# 分析结果` 注释起、到该内函数结束（递归块结束、`# 并行处理本层所有 query` 之前）替换为：

```python
            # 分析结果（返回 (analysis, reranked)）
            analysis, reranked = await self._analyze_deep_search_results(
                state["query"],
                query,
                results,
                search_type,
                hypotheses,
                state=state,
            )

            if not analysis:
                return {"facts": [], "sources": []}

            # 写 raw_sources：按 url 去重（机制 1，供本节点内 DataAnalyst 读），
            # 同时收进局部 list 返回（机制 2，供 executor 合并）。同步无 await，并发安全。
            local_sources: List[Dict[str, Any]] = []
            existing_by_url = {s.get("url"): s for s in state["raw_sources"] if s.get("url")}
            for r in reranked:
                url = r.get("url", "")
                if not url:
                    continue
                if url in existing_by_url:
                    src = existing_by_url[url]
                    if section_id not in src.get("related_sections", []):
                        src.setdefault("related_sections", []).append(section_id)
                    continue
                src = {
                    "url": url,
                    "title": r.get("title", ""),
                    "site_name": r.get("site_name", ""),
                    "date": r.get("date", ""),
                    "text": r.get("summary", "") or r.get("snippet", ""),
                    "related_sections": [section_id],
                    "relevance_score": r.get("relevance_score", 0.0),
                }
                state["raw_sources"].append(src)   # 机制 1
                existing_by_url[url] = src
                local_sources.append(src)          # 机制 2（同一引用）

            # 提取并添加事实（_ingest_facts 返回本次新增对象）
            url_date_map = {r.get("url", ""): r.get("date", "") for r in results}
            local_facts = self._ingest_facts(
                state, analysis, section_id, query, search_type, depth, url_date_map
            )

            self.logger.info(
                f"Deep search ({search_type}, depth={depth}): "
                f"+{len(local_facts)} facts for query '{query[:30]}...'"
            )

            # 递归更深层线索（深度受 max_depth 控），把更深层新增并入本协程返回
            if depth < max_depth:
                further_tracing = analysis.get("further_tracing_queries", [])
                if further_tracing:
                    self.add_message(state, "thought", {
                        "agent": self.name,
                        "content": f"发现更深层线索 (深度{depth+1}): {', '.join(further_tracing[:2])}",
                    })
                    deeper = await self._execute_deep_search(
                        state, section_id, further_tracing[:2],
                        search_type, hypotheses,
                        depth=depth + 1, max_depth=max_depth,
                    )
                    local_facts.extend(deeper.get("facts", []))
                    local_sources.extend(deeper.get("sources", []))

            return {"facts": local_facts, "sources": local_sources}
```

并把 `_process_one_query` 开头的早退 `if not results: return` 改为：

```python
            results = await self._execute_search(query, count=6)
            if not results:
                return {"facts": [], "sources": []}
```

- [ ] **Step 4: 改写 `_execute_deep_search` 收尾聚合 + 返回**

(a) 把 `_execute_deep_search` 签名 `-> None` 改为 `-> Dict[str, Any]`。

(b) 把开头的 `if depth > max_depth:` 块改为返回空聚合：

```python
        if depth > max_depth:
            self.logger.info(f"Reached max recursion depth ({max_depth})")
            return {"facts": [], "sources": []}
```

(c) 把方法末尾的 gather 收尾段替换为聚合返回：

```python
        # 并行处理本层所有 query（每 query 内部仍按原顺序：search → analyze → ingest）
        results_or_excs = await asyncio.gather(
            *[_process_one_query(q) for q in queries],
            return_exceptions=True,
        )
        agg_facts: List[Dict[str, Any]] = []
        agg_sources: List[Dict[str, Any]] = []
        errs = []
        for r in results_or_excs:
            if isinstance(r, Exception):
                errs.append(r)
                continue
            if r:
                agg_facts.extend(r.get("facts", []))
                agg_sources.extend(r.get("sources", []))
        if errs:
            self.logger.warning(
                f"[Scout._execute_deep_search] {len(errs)}/{len(queries)} "
                f"queries failed (depth={depth}): "
                f"{[(type(e).__name__, str(e)[:80]) for e in errs[:3]]}"
            )
        return {"facts": agg_facts, "sources": agg_sources}
```

- [ ] **Step 5: 改写 `search_with_queries` 去掉切片**

把 `search_with_queries` 方法体（`facts_before = ...` 到 `return {...}`）替换为：

```python
        result = await self._execute_deep_search(
            state=state,
            section_id=section_id,
            queries=queries,
            search_type="follow_up",
            hypotheses=state.get("hypotheses", []),
            depth=1,
            max_depth=2,
        )
        return {
            "facts": result.get("facts", []),
            "sources": result.get("sources", []),
            "section_id": section_id,
        }
```

并把该方法 docstring 里"用 snapshot/diff 方案捕获新增项返回"一句更新为"返回本次新增的 fact/source 对象（每协程收集，避免并发切片重叠）"。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_scout_raw_sources.py test/test_deep_research_v3/test_scout_scoping.py -v`
Expected: PASS（含并发、raw_sources、scoping 既有用例 `state["raw_sources"] == []`）

- [ ] **Step 7: 提交（含 Task 3 改动）**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v3/test_scout_raw_sources.py
git commit -m "feat: Scout 写 raw_sources 并按协程返回新增对象, 修复并发重复计数"
```

---

## Task 5: 清 legacy `_research_section` 抽数 + `SEARCH_ANALYSIS_PROMPT` data_points 字段

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`（`_research_section` 约 990-1000、`SEARCH_ANALYSIS_PROMPT` 约 257-259）

**说明:** `_research_section`/`SEARCH_ANALYSIS_PROMPT` 是未接入 v3 graph 的 legacy 路径，但保持全仓一致也删掉其 data_point 抽取（不删整个 v2 方法）。无独立单测（legacy 不跑），靠"删后既有测试仍绿"验证。

- [ ] **Step 1: 删 `_research_section` 的 data_point 入库块**

删除以下整段（在 `state["facts"].append(fact_entry)` / `added_facts += 1` 之后）：

```python
                # 提取数据点
                for dp in fact.get("data_points", []):
                    data_point = {
                        "id": f"dp_{uuid.uuid4().hex[:8]}",
                        "name": dp.get("name", ""),
                        "value": dp.get("value", ""),
                        "unit": dp.get("unit", ""),
                        "year": dp.get("year"),
                        "source": fact.get("source_name", ""),
                        "confidence": fact.get("credibility_score", 0.5)
                    }
                    state["data_points"].append(data_point)
```

> 同方法稍后用于前端展示的 `extracted_data_points` 收集块保留不动——`data_points` 字段从 prompt 删除后它自然产出空 list，不影响逻辑。

- [ ] **Step 2: 删 `SEARCH_ANALYSIS_PROMPT` 的 data_points 字段**

在 `SEARCH_ANALYSIS_PROMPT` 的 `extracted_facts` 项里删除：

```python
            "data_points": [
                {{"name": "指标名", "value": "数值", "unit": "单位", "year": 2024}}
            ],
```

删除后 `"credibility_score": 0.0-1.0,` 下一行直接接 `"needs_verification": true或false,`。

- [ ] **Step 3: 运行 scout 相关测试确认仍绿**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_scout_raw_sources.py test/test_deep_research_v3/test_scout_scoping.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py
git commit -m "refactor: 清理 legacy _research_section 与 SEARCH_ANALYSIS_PROMPT 的 data_point 抽取"
```

---

## Task 6: executor —— search_section url 去重合并 + analyze_facts 合并 time_series/distributions

**Files:**
- Modify: `backend/app/service/deep_research_v2/executor.py`（约 339-484 `executor_node`，新增模块级 helper）
- Test: `backend/test/test_deep_research_v3/test_executor.py`

- [ ] **Step 1: 写失败测试**

在 `backend/test/test_deep_research_v3/test_executor.py` 末尾追加：

```python
def test_merge_raw_sources_dedup_by_url():
    """_merge_raw_sources 按 url 去重，已存在则累加 related_sections"""
    from app.service.deep_research_v2.executor import _merge_raw_sources
    merged = [{"url": "http://a.com", "related_sections": ["sec_1"]}]
    by_url = {s["url"]: s for s in merged}
    _merge_raw_sources(merged, by_url, [
        {"url": "http://a.com", "related_sections": ["sec_2"]},  # 同 url → 累加
        {"url": "http://b.com", "related_sections": ["sec_3"]},  # 新 url → 追加
    ])
    assert len(merged) == 2
    a = next(s for s in merged if s["url"] == "http://a.com")
    assert a["related_sections"] == ["sec_1", "sec_2"]
    b = next(s for s in merged if s["url"] == "http://b.com")
    assert b["related_sections"] == ["sec_3"]


@pytest.mark.asyncio
async def test_executor_merges_timeseries_distributions(monkeypatch):
    """executor_node 把 analyze_facts 的 time_series/distributions 合并进返回"""
    from app.service.deep_research_v2 import executor as ex
    from app.service.deep_research_v2.state import create_initial_state

    async def fake_analyze(state):
        return {
            "data_points": [{"name": "x", "value": 1}],
            "insights": ["i1"],
            "time_series": [{"id": "ts1", "metric": "m"}],
            "distributions": [{"id": "d1", "name": "n"}],
        }

    monkeypatch.setitem(ex.TOOL_REGISTRY, "analyze_facts", fake_analyze)
    state = create_initial_state("q", "sid")
    state["plan"] = [{"step_id": "s1", "tool": "analyze_facts", "args": {},
                      "depends_on": [], "parallel_group": None}]
    out = await ex.executor_node(state)
    assert out["time_series"] == [{"id": "ts1", "metric": "m"}]
    assert out["distributions"] == [{"id": "d1", "name": "n"}]
    assert out["data_points"][-1]["name"] == "x"
```

确认文件顶部已 `import pytest`（既有测试已导入；若无则加）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_executor.py::test_merge_raw_sources_dedup_by_url test/test_deep_research_v3/test_executor.py::test_executor_merges_timeseries_distributions -v`
Expected: FAIL —`_merge_raw_sources` 不存在（ImportError）；executor_node 返回无 `time_series` 键（KeyError）

- [ ] **Step 3: 加 helper + 改 executor_node**

(a) 在 `executor.py` 模块级（如 `_resolve_callable` 附近）新增：

```python
def _merge_raw_sources(merged_sources, sources_by_url, new_sources):
    """按 url 去重把 new_sources 并进 merged_sources（原地）。

    已存在的 url 累加 related_sections（去重），新 url 追加。覆盖式合并模型下，
    跨章节/跨 tool 的同 url raw_source 必须在此统一去重。
    """
    for src in new_sources:
        url = src.get("url")
        if url and url in sources_by_url:
            existing = sources_by_url[url]
            existing.setdefault("related_sections", [])
            for sid in src.get("related_sections", []):
                if sid not in existing["related_sections"]:
                    existing["related_sections"].append(sid)
        else:
            merged_sources.append(src)
            if url:
                sources_by_url[url] = src
```

(b) 两处插入（不要重写已有行，只新增）：

其一，紧跟在已有的 `merged_sources = list(state.get("raw_sources", []))` 这行**之后**，新增一行：

```python
    _sources_by_url = {s.get("url"): s for s in merged_sources if s.get("url")}
```

其二，紧跟在已有的 `merged_insights = list(state.get("insights", []))` 这行**之后**，新增两行：

```python
    merged_time_series = list(state.get("time_series", []))
    merged_distributions = list(state.get("distributions", []))
```

(c) 把 `search_section` 分支的 sources 合并改为去重：

```python
            if result["tool"] == "search_section":
                merged_facts.extend(output.get("facts", []))
                _merge_raw_sources(merged_sources, _sources_by_url, output.get("sources", []))
            elif result["tool"] == "analyze_facts":
                merged_data_points.extend(output.get("data_points", []))
                merged_insights.extend(output.get("insights", []))
                merged_time_series.extend(output.get("time_series", []))
                merged_distributions.extend(output.get("distributions", []))
```

(d) 在 `executor_node` 的返回 dict 里，紧跟已有的 `"data_points": merged_data_points,` 这行**之后**，新增两行：

```python
        "time_series": merged_time_series,
        "distributions": merged_distributions,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_executor.py -v`
Expected: PASS（含既有 executor 用例）

- [ ] **Step 5: 提交**

```bash
git add backend/app/service/deep_research_v2/executor.py backend/test/test_deep_research_v3/test_executor.py
git commit -m "feat: executor 按 url 去重合并 raw_sources 并合并 time_series/distributions"
```

---

## Task 7: DataAnalyst `_extract_data` 改读 raw_sources（独占抽数 + 超集 schema + 重算可信度 + 存 ts/dist）

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/data_analyst.py`（imports、`DATA_EXTRACTION_PROMPT`、`_extract_data` 约 261-301、`extract_data_points` 约 390-414）
- Test: `backend/test/test_deep_research_v3/test_data_analyst_extract.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/test/test_deep_research_v3/test_data_analyst_extract.py`：

```python
"""DataAnalyst: 改读 raw_sources 抽数 + 超集 schema"""
import json
import pytest

from app.service.deep_research_v2.agents.data_analyst import DataAnalyst
from app.service.deep_research_v2.state import create_initial_state


def _make_analyst():
    return DataAnalyst(llm_api_key="dummy", llm_base_url="http://dummy", model="qwen-max")


@pytest.mark.asyncio
async def test_extract_data_reads_raw_sources(monkeypatch):
    """_extract_data 从 raw_sources 抽数，产出超集 schema，并存 time_series/distributions"""
    analyst = _make_analyst()
    state = create_initial_state("AI 市场", "sid")
    state["raw_sources"] = [
        {"url": "http://gov.cn/r1", "title": "报告1", "site_name": "统计局",
         "date": "2026-01-01", "text": "2024 年市场规模 5000 亿元",
         "related_sections": ["sec_1"], "relevance_score": 0.95},
    ]

    captured = {}

    async def fake_call_llm(*a, **k):
        captured["prompt"] = k.get("user_prompt", "")
        return json.dumps({
            "data_points": [
                {"metric_key": "ai_market_size", "name": "AI市场规模", "value": 5000,
                 "unit": "亿元", "year": 2024, "source_url": "http://gov.cn/r1",
                 "confidence": 0.9},
            ],
            "time_series": [{"id": "ts1", "metric": "AI市场规模", "data": [{"year": 2024, "value": 5000}]}],
            "distributions": [{"id": "d1", "name": "细分占比", "data": []}],
            "insights": ["市场规模快速增长"],
        })

    monkeypatch.setattr(analyst, "call_llm", fake_call_llm)
    result = await analyst._extract_data(state)

    # 原文片段进了 prompt（读 raw_sources 而非压缩 fact）
    assert "5000 亿元" in captured["prompt"]
    # data_point 超集 schema
    dp = state["data_points"][0]
    assert dp["metric_key"] == "ai_market_size"
    assert dp["source_url"] == "http://gov.cn/r1"
    assert "source_name" in dp and "credibility" in dp
    assert dp["source"] == dp["source_name"]       # 旧别名
    assert dp["confidence"] == dp["credibility"]   # 旧别名
    assert dp["related_sections"] == ["sec_1"]     # 取自命中 raw_source
    # time_series / distributions 仅存进 state
    assert state["time_series"] == [{"id": "ts1", "metric": "AI市场规模", "data": [{"year": 2024, "value": 5000}]}]
    assert state["distributions"] == [{"id": "d1", "name": "细分占比", "data": []}]
    # 返回 dict 含四类
    assert set(result.keys()) >= {"data_points", "time_series", "distributions", "insights"}


@pytest.mark.asyncio
async def test_extract_data_drops_below_credibility_floor(monkeypatch):
    """低可信度 data_point 被硬丢弃"""
    analyst = _make_analyst()
    state = create_initial_state("q", "sid")
    state["raw_sources"] = [
        {"url": "http://spam.example/x", "title": "t", "site_name": "自媒体",
         "date": "2020-01-01", "text": "随便一个数 1", "related_sections": ["sec_1"],
         "relevance_score": 0.4},
    ]

    async def fake_call_llm(*a, **k):
        # 极低 confidence + 老日期 + 无权威域名 → final < CREDIBILITY_FLOOR(0.3)
        return json.dumps({"data_points": [
            {"metric_key": "x", "name": "x", "value": 1, "unit": "", "year": 2020,
             "source_url": "http://spam.example/x", "confidence": 0.2}],
            "time_series": [], "distributions": [], "insights": []})

    monkeypatch.setattr(analyst, "call_llm", fake_call_llm)
    await analyst._extract_data(state)
    assert state["data_points"] == []


@pytest.mark.asyncio
async def test_extract_data_points_diff_returns_four_kinds(monkeypatch):
    """v3 入口 extract_data_points 的 diff 返回扩展到四类"""
    analyst = _make_analyst()
    state = create_initial_state("q", "sid")
    state["raw_sources"] = [
        {"url": "http://gov.cn/r1", "title": "t", "site_name": "统计局",
         "date": "2026-01-01", "text": "数据 100", "related_sections": ["sec_1"],
         "relevance_score": 0.9},
    ]

    async def fake_call_llm(*a, **k):
        return json.dumps({"data_points": [
            {"metric_key": "m", "name": "m", "value": 100, "unit": "", "year": 2026,
             "source_url": "http://gov.cn/r1", "confidence": 0.9}],
            "time_series": [{"id": "ts1"}], "distributions": [{"id": "d1"}],
            "insights": ["x"]})

    monkeypatch.setattr(analyst, "call_llm", fake_call_llm)
    diff = await analyst.extract_data_points(state)
    assert len(diff["data_points"]) == 1
    assert diff["time_series"] == [{"id": "ts1"}]
    assert diff["distributions"] == [{"id": "d1"}]
    assert diff["insights"] == ["x"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_data_analyst_extract.py -v`
Expected: FAIL —当前 `_extract_data` 读 facts，prompt 不含原文、data_point 无 metric_key/超集字段

- [ ] **Step 3: 加 imports + 常量**

在 `data_analyst.py` 顶部 import 区（`from ..state import ...` 附近）加：

```python
from ..source_scoring import final_credibility

# data_point 最终可信度低于此值硬丢弃（与 scout.CREDIBILITY_FLOOR 一致）
CREDIBILITY_FLOOR = 0.3
# DataAnalyst 抽数取样上限（控制 token）
RAW_SOURCE_TOP_N = 12
RAW_SOURCE_TEXT_MAXLEN = 1500
```

- [ ] **Step 4: 更新 `DATA_EXTRACTION_PROMPT` 的 data_points 示例（加 metric_key + source_url）**

把 `DATA_EXTRACTION_PROMPT` 里 data_points 的示例对象：

```python
    "data_points": [
        {{
            "id": "dp_001",
            "name": "中国AI市场规模",
            "value": 5000,
            "unit": "亿元",
            "year": 2024,
            "source": "艾瑞咨询",
            "category": "market_size",
            "confidence": 0.9
        }}
    ],
```

改为：

```python
    "data_points": [
        {{
            "id": "dp_001",
            "metric_key": "china_ai_market_size",
            "name": "中国AI市场规模",
            "value": 5000,
            "unit": "亿元",
            "year": 2024,
            "source_url": "https://www.gov.cn/xxx",
            "source": "艾瑞咨询",
            "category": "market_size",
            "confidence": 0.9
        }}
    ],
```

并把该 prompt 末尾"注意:"块（精确匹配）：

```python
注意：
- 只提取有明确来源的数据
- confidence表示数据可信度(0-1)
- 如果没有找到相关数据，返回空数组"""
```

替换为：

```python
注意：
- 只提取有明确来源的数据
- confidence表示数据可信度(0-1)
- metric_key 用英文 snake_case 表示同一指标的归一化键（如 "china_ai_market_size"），同一指标在不同来源/年份用相同 metric_key
- source_url 必须填该数据点所依据来源的 URL（从上方各 [来源N] 标注的 URL 中选）
- 如果没有找到相关数据，返回空数组"""
```

- [ ] **Step 5: 改写 `_extract_data`**

把 `_extract_data` 整个方法体替换为：

```python
    async def _extract_data(self, state: ResearchState) -> Dict[str, Any]:
        """从 raw_sources（未压缩原文）提取结构化数据。DataAnalyst 是唯一抽数 owner。"""
        self.logger.info("Extracting structured data from raw_sources...")

        raw_sources = state.get("raw_sources", [])
        if not raw_sources:
            self.logger.info("No raw_sources to extract data from")
            return {"data_points": [], "time_series": [], "distributions": [], "insights": []}

        # 按 relevance 降序取 top-N，控制 token
        top = sorted(
            raw_sources, key=lambda s: s.get("relevance_score", 0.0), reverse=True
        )[:RAW_SOURCE_TOP_N]

        blocks = []
        url_meta = {}
        for i, s in enumerate(top):
            url = s.get("url", "")
            url_meta[url] = {
                "date": s.get("date", ""),
                "name": s.get("site_name", ""),
                "related_sections": s.get("related_sections", []),
            }
            text = (s.get("text", "") or "")[:RAW_SOURCE_TEXT_MAXLEN]
            blocks.append(
                f"[来源{i+1}] {s.get('title', '')} | {s.get('site_name', '')} | {url}\n{text}"
            )

        prompt = self.DATA_EXTRACTION_PROMPT.format(
            query=state["query"],
            search_results="\n\n".join(blocks),
        )

        response = await self.call_llm(
            system_prompt="你是专业的数据分析师，擅长从原文中提取结构化数据。请输出JSON格式。",
            user_prompt=prompt,
            json_mode=True,
            temperature=0.2,
            state=state,
            action="extract_data",
        )
        result = self.parse_json_response(response)

        # data_points：重算可信度（硬丢弃）+ 超集 schema（含旧别名）
        kept = []
        for dp in result.get("data_points", []):
            source_url = dp.get("source_url", "")
            meta = url_meta.get(source_url, {})
            cred = final_credibility(
                dp.get("confidence", dp.get("credibility", 0.5)),
                source_url,
                meta.get("date", ""),
            )
            if cred < CREDIBILITY_FLOOR:
                continue
            source_name = dp.get("source") or meta.get("name", "")
            entry = {
                "id": dp.get("id") or f"dp_{uuid.uuid4().hex[:8]}",
                "metric_key": dp.get("metric_key", ""),
                "name": dp.get("name", ""),
                "value": dp.get("value"),
                "unit": dp.get("unit", ""),
                "year": dp.get("year"),
                "source_url": source_url,
                "source_name": source_name,
                "credibility": cred,
                "related_sections": meta.get("related_sections", []),
                # 旧别名（下游 Critic/Writer/Wizard 兼容）
                "source": source_name,
                "confidence": cred,
            }
            state["data_points"].append(entry)
            kept.append(entry)

        # time_series / distributions：仅存（下游消费留待后续）
        state.setdefault("time_series", []).extend(result.get("time_series", []))
        state.setdefault("distributions", []).extend(result.get("distributions", []))

        if result.get("insights"):
            state["insights"].extend(result["insights"])

        self.logger.info(
            f"Extracted {len(kept)} data points (kept), "
            f"{len(result.get('time_series', []))} time_series, "
            f"{len(result.get('distributions', []))} distributions"
        )
        return {
            "data_points": kept,
            "time_series": result.get("time_series", []),
            "distributions": result.get("distributions", []),
            "insights": result.get("insights", []),
        }
```

- [ ] **Step 6: 改写 `extract_data_points`（v3 入口 diff 扩展四类）**

把 `extract_data_points` 整个方法体替换为：

```python
    async def extract_data_points(self, state: ResearchState) -> Dict[str, Any]:
        """v3 入口：从 state["raw_sources"] 提取 data_points/time_series/distributions/insights。

        复用 _extract_data（mutates state），用 snapshot/diff 捕获四类新增项返回。
        """
        if not state.get("raw_sources"):
            return {"data_points": [], "time_series": [], "distributions": [], "insights": []}

        dp_before = len(state.get("data_points", []))
        ts_before = len(state.get("time_series", []))
        dist_before = len(state.get("distributions", []))
        insights_before = len(state.get("insights", []))

        await self._extract_data(state)

        return {
            "data_points": state.get("data_points", [])[dp_before:],
            "time_series": state.get("time_series", [])[ts_before:],
            "distributions": state.get("distributions", [])[dist_before:],
            "insights": state.get("insights", [])[insights_before:],
        }
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_data_analyst_extract.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 8: 提交**

```bash
git add backend/app/service/deep_research_v2/agents/data_analyst.py backend/test/test_deep_research_v3/test_data_analyst_extract.py
git commit -m "feat: DataAnalyst 改读 raw_sources 独占抽数, 超集 schema 与重算可信度, 存 time_series/distributions"
```

---

## Task 8: tools.py —— analyze_facts 返回追加 time_series/distributions

**Files:**
- Modify: `backend/app/service/deep_research_v2/tools.py`（`analyze_facts`，约 96-118）
- Test: `backend/test/test_deep_research_v3/test_tools.py`

- [ ] **Step 1: 写失败测试**

在 `backend/test/test_deep_research_v3/test_tools.py` 的 `test_analyze_facts_returns_data_points` 之后追加：

```python
@pytest.mark.asyncio
async def test_analyze_facts_returns_timeseries_distributions(monkeypatch):
    """analyze_facts 返回里含 time_series / distributions"""
    from app.service.deep_research_v2.tools import analyze_facts

    state = create_initial_state(query="测试", session_id="sid_1")
    state["raw_sources"] = [{"url": "http://a.com", "text": "x", "relevance_score": 0.9}]

    mock_analyst = AsyncMock()
    mock_analyst.extract_data_points = AsyncMock(return_value={
        "data_points": [{"name": "m"}],
        "insights": ["i"],
        "time_series": [{"id": "ts1"}],
        "distributions": [{"id": "d1"}],
    })
    monkeypatch.setattr(
        "app.service.deep_research_v2.tools.get_analyst_instance",
        lambda: mock_analyst,
    )

    result = await analyze_facts.ainvoke({"state": state})
    assert result["time_series"] == [{"id": "ts1"}]
    assert result["distributions"] == [{"id": "d1"}]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_tools.py::test_analyze_facts_returns_timeseries_distributions -v`
Expected: FAIL — KeyError `time_series`（tool 未透传）

- [ ] **Step 3: 改 `analyze_facts` 透传四类 + 错误兜底**

把 `tools.py` 的 `analyze_facts` 函数体替换为：

```python
@tool
async def analyze_facts(state: ResearchState) -> Dict[str, Any]:
    """从 raw_sources（未压缩原文）提取 data points + time_series/distributions + insights。

    Args:
        state: 共享 ResearchState，读取 state["raw_sources"]

    Returns:
        {
            "data_points": [...],
            "insights": [str, ...],
            "time_series": [...],
            "distributions": [...],
        }
    """
    analyst = get_analyst_instance()
    try:
        result = await analyst.extract_data_points(state)
        return {
            "data_points": result.get("data_points", []),
            "insights": result.get("insights", []),
            "time_series": result.get("time_series", []),
            "distributions": result.get("distributions", []),
        }
    except Exception as e:
        logger.exception(f"analyze_facts failed: {e}")
        return {
            "data_points": [],
            "insights": [],
            "time_series": [],
            "distributions": [],
            "error": str(e),
        }
```

并把该 tool 的 docstring（原"从已收集的 facts 中提取..."）更新为读 raw_sources（如上）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest test/test_deep_research_v3/test_tools.py -v`
Expected: PASS（含既有 tools 用例）

- [ ] **Step 5: 提交**

```bash
git add backend/app/service/deep_research_v2/tools.py backend/test/test_deep_research_v3/test_tools.py
git commit -m "feat: analyze_facts tool 透传 time_series/distributions"
```

---

## Task 9: 全量回归 + 收尾

**Files:** 无新增改动，仅验证。

- [ ] **Step 1: 跑完整 v3 测试套件**

Run: `cd backend && python -m pytest test/test_deep_research_v3/ -q`
Expected: PASS，数量 = 基线 119 + 本次新增（约 +13）。0 failures。

- [ ] **Step 2: 若有失败，定位修复**

逐一排查失败用例；常见点：
- `test_tools.py::test_analyze_facts_returns_data_points`（既有）——确认仍含 data_points/insights 键（Task 8 保留了）。
- 任何断言 `_analyze_deep_search_results` 返回单值的旧用例——本次无此类既有用例，若有则更新为解包 tuple。

- [ ] **Step 3: 跑一次更广的相关回归（可选但推荐）**

Run: `cd backend && python -m pytest test/test_deep_research_v3/ test/ -k "scout or executor or analyst or tools or state" -q`
Expected: PASS

- [ ] **Step 4: 最终提交（如有零碎修复）**

```bash
git add -A
git commit -m "test: raw_sources/DataAnalyst 重构全量回归通过"
```

---

## 自查清单（实施者收尾确认）

- [ ] Scout 不再写 `state["data_points"]`（grep `data_points` 在 scout.py 应只剩注释/UI 展示用空 list）。
- [ ] `search_with_queries` 已无 `facts_before` / `sources_before` 切片。
- [ ] `_ingest_facts` 仍保留 hypothesis 就地写（`evidence_for`/`evidence_against`）。
- [ ] DataAnalyst data_point 同时含新字段（metric_key/source_url/source_name/credibility/related_sections）与旧别名（source/confidence）。
- [ ] executor 返回 dict 含 `time_series`/`distributions`，search_section 分支用 `_merge_raw_sources` 去重。
- [ ] `test_scout_scoping.py` 的 `state["raw_sources"] == []` 仍绿（scoping 不走 `_execute_deep_search`）。

## 范围外（本次不做）

- Phase 3 纯代码 consolidation（metric_key 分组/指纹去重/单位归一/按 year 组装 series）。`metric_key` 本次只产出不消费。
- CodeWizard 消费 time_series/distributions、按章节取数。
- 删除整个 v2 `process()`/`_analyze_data` legacy 方法。
