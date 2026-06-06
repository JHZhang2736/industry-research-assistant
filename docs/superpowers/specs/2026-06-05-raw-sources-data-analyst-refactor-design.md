# 接活 raw_sources 死字段 + 数据点抽取收敛到 DataAnalyst 独占

- **日期**: 2026-06-05
- **分支**: `feat/raw-sources-data-analyst-refactor`
- **范围**: `backend/app/service/deep_research_v2/`(v3 Plan-and-Execute 架构)
- **本次实施**: Phase 1 + Phase 2(Phase 3 consolidation 暂不做)

## 背景

v3 把各专家 Agent 包装成 `@tool` 由 Executor 调度:

- `search_section` tool → DeepScout(`agents/scout.py`):搜索 + 提取 fact
- `analyze_facts` tool → DataAnalyst(`agents/data_analyst.py`):从 fact 提取 data_point + insight
- `generate_charts` tool → CodeWizard:画图
- `write_section` tool → LeadWriter:写作

tool 注册在 `tools.py`,调度在 `executor.py`,state 是被各 tool 共享 mutate 的 `TypedDict`(`state.py`)。

经核实,v3 live 流程只走 `search_section` tool → `DeepScout.search_with_queries` → `_execute_deep_search` → `_ingest_facts`。`DeepScout.process()`/`_research_section` 与 `DataAnalyst.process()`/`_analyze_data` **未接入 v3 graph**(graph 只用到 `scout.scope_topic`),属 legacy 路径。

## 要解决的问题(已核实)

1. **`raw_sources` 是死字段**:`state.py:185` 声明了字段,`executor.py:349/476`、`scout.py:1804/1818` 都只读,全代码无写入。原文文本被 Scout 用完即弃,只有压缩后的 fact 留在 state。
2. **data_point 三处抽取、无去重、schema 不一致**:
   - DeepScout 正常路径 `scout.py:908-919`(legacy)从 `fact["data_points"]` 拆点入库(嵌套 schema)。
   - DeepScout 深搜路径 `scout.py:1070-1080`(live)从顶层 `data_points` 入库(另一套 schema)。
   - DataAnalyst `data_analyst.py:261` `_extract_data` 又从 `fact.content`(已压缩文本)重抽一遍 → lossy。
3. **time_series/distributions 被白白丢弃**:`_extract_data` 让 LLM 抽了这两类,但只回写 data_points/insights,下游拿不到。
4. **并发重复计数 bug**:`search_section` 在 planner 里 `parallel_group="search_batch"` 并行;`search_with_queries`(`scout.py:1782`)用 `state["facts"][facts_before:]` / `raw_sources[sources_before:]` 切片返回新增,并发下多个 tool 切片区间重叠 → facts/sources 被 executor 重复 merge。

## 目标架构

把抽数收敛成"DeepScout 只管 fact + raw_sources、DataAnalyst 独占抽数且读原文":

- Scout 把 rerank 后的原始结果写进 `state["raw_sources"]`,并停止自己抽 data_point。
- DataAnalyst 改从 `raw_sources`(未压缩原文)抽数,成为唯一抽数 owner。
- 顺带修复 time_series/distributions 丢弃 + 并发重复计数两个 bug。

## 关键架构判断:Executor 是覆盖式合并

`executor_node`(`executor.py:339`)的合并语义是**覆盖式**的:

```python
merged_sources = list(state["raw_sources"])   # batch 开始时快照
# ... 各 tool 并发跑、in-place mutate state["raw_sources"] ...
for result: merged_sources.extend(output["sources"])
return {"raw_sources": merged_sources}         # 覆盖 state
```

即 **tool 执行期对 `state["raw_sources"]`/`state["facts"]` 的 in-place 修改最终都会被 `merged_*` 覆盖丢弃**,只有 tool **return** 的东西能存活。两个推论:

1. 并发去重不能靠共享 state(会被覆盖),必须**每协程返回自己实际新增的对象**。
2. 跨章节(跨 tool)的同 url raw_source 去重必须在 **executor 合并处**做,scout 单协程内只能去重本协程内的。

这是本设计相对原始 spec 的主要补充。

## 数据契约

```text
RawSource: {
  url, title, site_name, date,
  text,                 # rerank 后的 summary(本就不长,不存全网页 HTML)
  related_sections[],   # 关联章节 id
  relevance_score,      # rerank 降级路径(scout.py:1502)不挂此字段,写入时缺省 0.0
}

DataPoint(超集 schema,旧字段保留以保下游兼容):{
  id, metric_key, name, value, unit, year,
  source_url, source_name, credibility, related_sections[],
  source,               # = source_name(旧别名,Critic 读)
  confidence,           # = credibility(旧别名)
}
```

下游消费现状(决定为何要超集):Critic 读 `dp["source"]`(`critic.py:462`),Writer/Wizard 读 `name/value/unit/year`(`writer.py:401`、`wizard.py:398`)。保留 `source`/`confidence` 别名 → 下游零改动。

## 分阶段方案

### Phase 1:Scout 写 raw_sources + 停止抽数 + 修并发

**1a. 并发 diff 修复(返回新增对象,不用切片)**

- `_ingest_facts`(`scout.py:1012`)改成**返回它实际 append 的 fact 对象列表**(现在返回 count)。
- `_process_one_query`(`scout.py:1122`)用局部 list 收集本协程的 facts + sources;递归调用 `_execute_deep_search` 的返回并入。
- `_execute_deep_search`(`scout.py:1084`)聚合各 query 协程的局部 list 并返回 `{"facts": [...], "sources": [...]}`。
- `search_with_queries`(`scout.py:1782`)直接返回聚合结果,**删掉 `facts_before:`/`sources_before:` 切片**。

> ⚠️ **保留所有 in-place `state[...]` 写,只改"返回值"。** executor_node 在**一次节点调用内**用 while 循环跑完整个 plan(search → analyze → write),全程共享同一个 `state` 对象,直到节点末尾才 return `merged_*`。因此存在两套并存且都不可少的机制:
> 1. **in-place 写 `state["facts"]` / `state["raw_sources"]` 等** = 节点内 step 间数据流(Writer 读 `state["facts"]`、DataAnalyst 读 `state["raw_sources"]`,都发生在同一次 executor_node 调用内)。**绝不能删**,否则下游 step 在本轮读到空。
> 2. **executor return `merged_*`** = 节点输出 → LangGraph channel → 下个节点 + checkpoint 持久化。**并发重复计数 bug 就出在这里**(切片重叠)。
>
> 所以本次修复**只动机制 2 的"返回值"**:`_ingest_facts` 仍 `state["facts"].append(...)`(机制 1,保留),但额外把它 append 的对象收进局部 list 返回;`search_with_queries` 用这个局部 list 返回,不再用 `state["facts"][facts_before:]` 切片。
> 特别地,`_ingest_facts` 对 `state["hypotheses"]` 的就地写(`scout.py:1060-1068`)更要保留——executor 返回字典(`executor.py:473-484`)**根本不含 `hypotheses`**,in-place 是它**唯一**的持久化路径。

**1b. raw_sources 写入(surface rerank 结果)**

- `_analyze_deep_search_results`(`scout.py:1203`)返回值从 `analysis` 改为 `(analysis, reranked)`。
- `_process_one_query` 拿到 reranked 后,构造 `RawSource`(`text` = `summary`,`related_sections` = `[section_id]`,`relevance_score` = `r.get("relevance_score", 0.0)` 兜底——rerank 失败降级路径 `scout.py:1502` 不挂此字段)。
- **写入既要 in-place 又要返回**(对应上面两套机制):对每个 reranked 结果,若其 url 已在 `state["raw_sources"]` 中(扫描去重,同步无 await 故并发安全),则把 `section_id` 累加进那条已有 source 的 `related_sections`(in-place,不新建);否则新建 source 对象,既 `state["raw_sources"].append(src)`(机制 1,供本节点内 DataAnalyst 读),又把这个**同一引用**收进局部 list。`_process_one_query` 把局部 source list 随 facts 一起返回(机制 2)。返回的是同一对象引用,故后续协程对 `related_sections` 的就地累加也会反映到返回值里。
- legacy `_research_section`/`_analyze_search_results` 不动。
- 注意:scoping 路径被 `test_scout_scoping.py` monkeypatch 掉 `_execute_deep_search`,故 scoping 不写 raw_sources,既有断言 `state["raw_sources"] == []` 仍成立。

**1c. Scout 停止抽 data_point(v3-only + 顺手清 legacy)**

- 删 `_ingest_facts` 的 data_points 入库(`scout.py:1070-1080`)+ 深搜 prompt 的 `data_points` 字段(`scout.py:1266-1268`)。
- 顺手清 legacy:删 `_research_section` 的 data_point 入库(`scout.py:908-919`)+ `SEARCH_ANALYSIS_PROMPT` 的 `data_points` 字段(`scout.py:176-178`)。不删整个 v2 方法。

### Phase 2:DataAnalyst 独占抽数

- `_extract_data`(`data_analyst.py:261`)改读 `state["raw_sources"]`:按 `relevance_score` 降序取 **top-12**(排序用 `s.get("relevance_score", 0.0)`,避免降级源缺字段报错/排错),每源 `text` 截到 **1500 字**,不再读 facts。
- `DATA_EXTRACTION_PROMPT` 加 `metric_key`(语义归一,LLM 在原文上下文做)和 `source_url` 字段。
- 每个 data_point 用 `source_scoring.final_credibility(llm_conf, source_url, date)` 重算可信度(date 从 raw_sources 按 url 映射),低于 `CREDIBILITY_FLOOR` 硬丢弃。
- `related_sections` 取自命中 raw_source 的 `related_sections`。
- 输出超集 schema 的 data_point(含旧别名)。
- `time_series`/`distributions`:**仅存**。`_extract_data` 写入 `state["time_series"]`/`state["distributions"]`,`extract_data_points`(`data_analyst.py:390`)的 diff 返回扩展到这四类。**不改 CodeWizard**(下游消费留待后续)。

### state + executor + tools 连线

- `state.py`:`ResearchState` 加 `time_series: List[Dict]`、`distributions: List[Dict]`;`create_initial_state` 加 `time_series=[]`、`distributions=[]`。可选同步更新 `DataPoint` dataclass 文档(实际入库用 plain dict)。
- `tools.py`:`analyze_facts` 返回追加 `time_series`/`distributions`。
- `executor.py`:
  - `analyze_facts` 分支 merge `time_series`/`distributions`(新增 `merged_*` list + 返回字段)。
  - **`search_section` 分支改 url 去重合并**:已有 url 则累加 `related_sections`(不重复 append),否则 append。
  - 返回 dict 加 `time_series`/`distributions` 字段。

## 测试(TDD,先写后改)

新增到 `backend/test/test_deep_research_v3/`:

1. `test_ingest_facts_returns_appended_objects` — `_ingest_facts` 返回它 append 的 fact 列表(不再是 count)。
1b. `test_ingest_facts_still_mutates_hypotheses` — 传入带 `hypothesis_support`/`related_hypothesis` 的 analysis,断言 `state["hypotheses"]` 的 `evidence_for`/`evidence_against` 被就地累加(守护点 A,防重构误删)。
2. `test_search_with_queries_concurrent_no_duplicate` — mock `_execute_search` + `_analyze_deep_search_results`,两个 `search_with_queries` 并发跑共享 state,断言各自返回的 facts/sources 无重叠、总数正确。
3. `test_raw_sources_written_with_relevance` — 断言 raw_sources 被写入且带 `relevance_score`/`related_sections`/`text`。
4. `test_scout_no_longer_emits_data_points` — Scout 路径跑完 `state["data_points"]` 不增长。
5. `test_data_analyst_reads_raw_sources` — mock raw_sources + LLM,断言 `_extract_data` 从 raw_sources 取样、产出超集 schema 的 data_point、time_series/distributions 落进 state。
6. `test_executor_merges_timeseries_distributions` — executor 合并这两类新增字段。
7. `test_executor_dedup_raw_sources_by_url` — 跨 tool 同 url 合并去重、累加 related_sections。

约束:全程保持 `backend/test/test_deep_research_v3/` 既有测试绿。

## 验证

1. 单测:facts/sources 并发无重复;raw_sources 被正确写入;executor url 去重。
2. (可选)召回:建小 gold set,比改造前(读 fact)vs 改造后(读 raw)data_point 召回率。
3. 端到端跑一个真实 query,确认报告/图表正常产出,data_points 无重复。

## 约束与注意

- 成本:改造后原文被 LLM 过两遍(Scout 抽 fact + DataAnalyst 抽数),DataAnalyst 已用 top-12 / 每源 1500 字限流。
- raw_sources 只存 rerank 后 top-N 的 summary(本就不长),不存全网页 HTML。
- Windows 环境:优先用 Bash 工具跑命令;中文路径;CRLF 警告忽略。
- git 提交:中文 commit 信息,不附 co-author;已在 `feat/raw-sources-data-analyst-refactor` 分支。

## 决策记录(本次 brainstorming 拍板)

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| time_series/distributions 接入深度 | 仅建字段 + executor 合并(不改 CodeWizard) | 先存起来,下游消费留待后续 |
| DataPoint schema 兼容 | 超集:新字段 + 保留 source/confidence 旧别名 | 下游零改动,符合"新 schema 是旧的超集" |
| legacy `_research_section`/v2 process | v3-only + 顺手清 legacy 抽数(不删整个方法) | 主改 v3 路径,顺手保持全仓一致,不扩大重构 |
| DataAnalyst 取样上限 | top-12 源 / 每源 1500 字 | 召回与成本折中,后续可调 |
| 跨章节 raw_source 去重 | executor 按 url 合并去重 + 累加 related_sections | 覆盖式合并模型下唯一正确的去重位置 |
| `metric_key` | 本次**只产出、不消费** | 消费它的 consolidation 是 Phase 3(本次不做)。本轮 metric_key 抽了暂无下游,白费少量 token 且归一质量无法验证,属前瞻预留——实施者勿误以为漏接下游。质量验证留待 Phase 3。 |

## 不做(本次范围外)

- Phase 3 纯代码 consolidation(按 metric_key 分组 → 指纹去重 → 冲突取高 → 单位归一 → 按 year 组装 series)。
- CodeWizard 消费 time_series/distributions / 按章节取数。
- 删除整个 v2 `process()`/`_analyze_data` legacy 方法。
