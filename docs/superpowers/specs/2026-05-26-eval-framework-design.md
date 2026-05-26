# Eval Framework Design — Industry Research Assistant

> 日期：2026-05-26
> 范围：为 `backend/app/service/deep_research_v2/` 多 agent 工作流构建自动化评测框架
> 状态：✅ 已实施（2026-05-26），见 docs/superpowers/plans/2026-05-26-eval-framework-implementation.md

## 1. 目标与非目标

### 1.1 目标

构建一套可自动化运行的端到端 + 选择性单 agent 评测框架，用于：

- 量化展示 deep research v2 工作流的产出质量（简历素材为主）
- 跨 commit / 模型版本快速回归检测
- 暴露 multi-agent 系统特有的能力：critic-revise 循环有效性

### 1.2 非目标（明确不做）

- **不做 RAG 评估**：本项目以网络搜索为唯一信息来源，不引入 Faithfulness / Context Precision / Context Recall 等 RAGAS 指标。RAG 能力在用户的其他项目中已覆盖。
- **不做人工标注的 reference-based 评估**：无 ground truth 数据集，纯 LLM-as-judge + rule-based。
- **不动 `backend/app/service/` 业务代码**：eval 框架为外部消费者，通过 SSE 流 + PG checkpoint 读取数据。
- **不做 eval-suite PR gate**：PR 跑完整 eval 成本不可控。PR 上只跑 mock 化的单元测试（不联网、不收费），eval suite 本身通过 `workflow_dispatch` 手动触发。

## 2. 关键决策清单

| 项 | 决策 |
|---|---|
| 首要目的 | 简历素材为主（完整度、metric 数量、技术栈丰富度） |
| 数据集策略 | 30 条 query 由 Claude 离线一次性生成 + 5 分钟人工 sanity check；无人工 reference |
| 评估方法 | LLM-as-judge + rule-based + 跨家族 ensemble judge 投票 |
| Judge 三家族 | `deepseek-v3` / `mimo-v2.5-pro` / `qwen-max` |
| 评估范围 | 端到端报告 + 2-3 个选择性单 agent |
| Evaluator 维度 | 4 质量 + 1 agentic + 2 操作型 = 7 个 |
| 数据库 | 本地 SQLite（eval 离线工具，不污染业务 PG） |
| Trace 后端 | LangSmith（仅 trace + dataset 上报，不依赖其 evaluation API） |
| 运行方式 | 本地 CLI + GitHub Actions `workflow_dispatch` 手动触发 |
| 并发模型 | 默认 5 并发，`asyncio.Semaphore` 控制，`--concurrency N` CLI 可调 |
| 限流兜底 | `aiolimiter` 在每个 LLM provider 客户端外 wrap |

## 3. 总体架构

```
backend/app/eval/                          # 新建 eval 包，独立于 service
├── __init__.py
├── datasets/
│   ├── seed_queries.jsonl                 # 30 条 query (Claude 离线生成一次)
│   └── generator.py                       # 生成器（脚本+Claude，幂等）
│
├── evaluators/                            # 7 个 evaluator，一文件一职责
│   ├── base.py                            # Evaluator 抽象基类
│   ├── relevance.py                       # LLM-judge
│   ├── coherence.py                       # LLM-judge
│   ├── citation.py                        # rule-based (URL 200 + ref 完整性)
│   ├── completeness.py                    # LLM-judge
│   ├── critic_loop.py                     # agentic: critic_feedback 解决率
│   ├── cost.py                            # 累加 token 用量
│   ├── latency.py                         # 各阶段耗时
│   └── prompts/                           # LLM-judge 用的 prompt 模板集中放
│       ├── relevance.md
│       ├── coherence.md
│       └── completeness.md
│
├── judges/
│   ├── base.py                            # JudgeClient 抽象
│   ├── deepseek.py                        # OpenAI-compatible
│   ├── mimo.py                            # https://api.xiaomimimo.com/v1
│   ├── qwen.py                            # dashscope OpenAI-compatible
│   └── ensemble.py                        # 多 judge 投票/聚合
│
├── runner.py                              # 主跑器
├── reporter.py                            # markdown + csv 报表
├── storage.py                             # SQLite 本地落库
├── langsmith_adapter.py                   # LangSmith dataset/run 上报
├── cli.py                                 # `python -m app.eval.cli`
└── tests/                                 # 见 §7
    ├── conftest.py
    ├── fixtures/
    ├── test_evaluators/
    ├── test_judges/
    ├── test_storage.py
    ├── test_reporter.py
    └── test_runner_smoke.py

.github/workflows/eval.yml                 # workflow_dispatch 手动触发
docs/eval-results/                         # 报表产出目录 (gitignored)
```

### 3.1 边界约束

- `eval/` 不入 `service/`：物理隔离
- evaluator 互不依赖：每个文件可独立 import 测试
- judges 都走 OpenAI-compatible：换 judge 改一行 base_url + model
- 不修改 `backend/app/service/deep_research_v2/**`
- 现有 `backend/app/scripts/test_deep_research_v2.py` 保留作冒烟测试，独立角色

### 3.2 新增依赖

追加到 `backend/requirements.txt`：

```
langsmith>=0.1.0
aiohttp>=3.9
aiolimiter>=1.1
rich>=13.0           # 进度条
```

`openai` / `langgraph` / `asyncpg` / `redis` 复用项目已有。

## 4. 组件设计

### 4.1 Evaluator 抽象

```python
class Evaluator(ABC):
    name: str                              # "relevance" 等
    scale: tuple[float, float]             # (0, 10) 或 (0, 1)
    requires_judge: bool
    requires_network: bool                 # citation 用

    @abstractmethod
    async def evaluate(
        self,
        ctx: EvalContext,                  # case + state + timings
        judge: EnsembleJudge | None
    ) -> EvalResult:
        ...
```

`EvalResult` 字段：`score: float | None`、`raw_judge_outputs: list[dict]`、`metadata: dict`、`error: str | None`、`low_confidence: bool`。

### 4.2 七个 Evaluator

| Evaluator | 抓 state 哪里 | 评分逻辑 |
|---|---|---|
| **Relevance** | `final_report`, `query` | 3 judge × 0-10，问"报告是否回答 query"，取均值 |
| **Coherence** | `final_report` | 3 judge × 0-10，问"行文连贯/段落衔接/术语一致"，取均值 |
| **Citation** | `final_report` + `references` + `facts` | rule-based: ①引用编号在 references 内 ②URL HEAD 200 ③引用覆盖率（引用数/章节数）→ 加权得分 |
| **Completeness** | `outline`, `final_report` | 3 judge × 0-10，问"outline 章节是否都被实质论述（不是占位）" |
| **CriticLoopEffectiveness** | `critic_feedback` + 修订前后 `quality_score` + iteration | rule-based: 主分 = `resolution_rate × 10` (0-10)，无 feedback 时 score=None；metadata 含 `{resolution_rate, score_delta = score_final - score_first_review, total_feedback, iterations}` |
| **Cost** | `logs[].tokens_used` | sum input/output tokens；按 provider 单价折算 RMB |
| **Latency** | start/end timestamp + 阶段日志 | 总耗时 + 每阶段（plan/research/analyze/write/review）耗时 |

LLM-judge 类 evaluator 的 prompt 模板集中放在 `evaluators/prompts/`，便于版本化。

### 4.3 EnsembleJudge

```python
class EnsembleJudge:
    def __init__(self, clients: list[JudgeClient]):
        self.clients = clients

    async def score(self, prompt: str, scale=(0, 10)) -> EnsembleResult:
        individual = await asyncio.gather(
            *[c.call_judge(prompt) for c in self.clients],
            return_exceptions=True
        )
        valid = [r for r in individual if isinstance(r, JudgeScore) and not r.failed]
        if not valid:
            return EnsembleResult(score=None, error="all judges failed")
        scores = [r.score for r in valid]
        return EnsembleResult(
            mean_score=statistics.mean(scores),
            median_score=statistics.median(scores),
            std=statistics.stdev(scores) if len(scores) > 1 else 0,
            individual=individual,
            low_confidence=(statistics.stdev(scores) > 2) if len(scores) > 1 else False,
            partial=len(valid) < len(self.clients)
        )
```

`low_confidence`（方差 > 2）在报表中红色标注。

### 4.4 JudgeClient 配置

| Judge | base_url | model | env key |
|---|---|---|---|
| deepseek | `https://api.deepseek.com/v1` | `deepseek-chat`（DeepSeek 平台通用入口，自动路由最新版本；可改为具体版本如 `deepseek-v3.2`） | `DEEPSEEK_API_KEY` |
| mimo | `https://api.xiaomimimo.com/v1` | `mimo-v2.5-pro` | `XIAOMI_API_KEY` |
| qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-max` | `DASHSCOPE_API_KEY` |

每个 client 实现 `JudgeClient.call(prompt) -> JudgeScore`，内部：
- `openai.AsyncOpenAI` 走 OpenAI-compatible 接口
- `@retry(max_attempts=3, backoff=ExponentialBackoff(1, 16))` 重试 429/5xx/timeout
- `asyncio.wait_for(..., timeout=60)`
- 解析 JSON `{score: float, reasoning: str}`；解析失败 regex 兜底；仍失败标 `JudgeScore.failed=True`

### 4.5 Runner

```python
sem = asyncio.Semaphore(args.concurrency)

async def run_one(case):
    async with sem:
        try:
            state = await asyncio.wait_for(
                run_research_capturing_state(service, case),
                timeout=600
            )
            results = await asyncio.gather(*[
                ev.evaluate(EvalContext(case, state), judges)
                for ev in evaluators
            ])
            await storage.save_case(case, state, results)
            await langsmith_adapter.upload(case, results)
            return CaseResult(case=case, results=results, ok=True)
        except Exception as e:
            return CaseResult(case=case, error=str(e), ok=False)

results = await asyncio.gather(*[run_one(c) for c in cases])
```

**state 捕获策略**：消费 SSE event 至 `[DONE]`，然后从 PG `research_checkpoints` 表 SELECT 最终 state（service 已自带持久化）。retry 一次缓解写入延迟。

### 4.6 数据集生成

`generator.py`（一次性脚本）：

- 给 Claude 一个 meta-prompt，要求"生成 30 条中文行业研究 query，覆盖 5+ 行业，长度 10-40 字"
- 自动加 `id` / `category` / `difficulty`（按长度+冷热度启发式）
- 输出 `seed_queries.jsonl`
- 5 分钟人工 sanity check 后 commit

格式：
```json
{"id": "q001", "query": "新能源汽车2024年市场现状与发展趋势", "category": "汽车", "difficulty": "easy"}
```

## 5. 数据流

```
CLI: python -m app.eval.cli run --suite=full --concurrency=5
    ↓
runner.py
    ├─ load_dataset("full") → 30 个 EvalCase
    ├─ build_judges() → EnsembleJudge([deepseek, mimo, qwen])
    └─ Semaphore(5) 包住 30 个 run_one(case)
         │
         ▼
    run_one(case):
       Phase A 执行研究 (5 路并发，每路 3-5 min)
         service.research(query, session_id=case.id)
         消费 SSE event 流 + 记录 start/end timestamp
         研究完成后从 PG checkpoint 表 SELECT 最终 state
         构造 EvalContext

       Phase B 跑 7 个 evaluator（路内 asyncio.gather）
         Relevance / Coherence / Completeness    → ensemble judge × 3 并发
         Citation                                → aiohttp URL HEAD × N 并发
         CriticLoop / Cost / Latency             → 纯计算

       Phase C 落库 + 上报
         storage.save_run(case, state, results)  → SQLite
         langsmith_adapter.upload(...)            → LangSmith Dataset/Run
    ↓
全部完成后
    ↓
reporter.py
    ├─ aggregate(all_results) → suite_summary
    ├─ markdown → docs/eval-results/YYYY-MM-DD-{suite}.md
    ├─ csv      → docs/eval-results/YYYY-MM-DD-{suite}.csv
    └─ LangSmith dashboard 链接
```

### 5.1 SQLite Schema

```sql
CREATE TABLE eval_runs (
    run_id TEXT PRIMARY KEY,
    suite TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    git_commit TEXT,
    config_json TEXT
);

CREATE TABLE case_results (
    run_id TEXT,
    case_id TEXT,
    query TEXT,
    final_report TEXT,
    quality_score REAL,
    duration_sec REAL,
    total_tokens INTEGER,
    cost_rmb REAL,
    error TEXT,
    PRIMARY KEY (run_id, case_id)
);

CREATE TABLE evaluator_scores (
    run_id TEXT,
    case_id TEXT,
    evaluator_name TEXT,
    score REAL,
    raw_judge_outputs_json TEXT,
    std REAL,
    low_confidence BOOLEAN,
    metadata_json TEXT,
    PRIMARY KEY (run_id, case_id, evaluator_name)
);
```

### 5.2 Markdown 报表骨架

```markdown
# Eval Suite: full
**Run ID**: 20260526-143022-a3f8
**Commit**: <git sha>
**Suite**: 30 cases, concurrency=5, total <duration>

## Overall Scores
| Evaluator | Mean | Median | Std | Low-confidence cases |
| ...

## Per-case Breakdown
[折叠表格]

## Low-confidence Cases
- q003: Citation std=3.1, deepseek=4 / mimo=8 / qwen=7
...

## Failed Cases
- q017: TimeoutError after 600s
...

## LangSmith Dashboard
<link>
```

## 6. 错误处理与边界

### 6.1 分级

| 失败类型 | 等级 | 处理 |
|---|---|---|
| 配置缺失 / 无 API key | Suite-fatal | 启动前校验，立即退出 |
| 数据集文件不存在 | Suite-fatal | 立即退出 |
| 研究 service 抛异常 | Case-fatal | 标 case failed，继续下一个 |
| 研究超时 (>10min) | Case-fatal | `asyncio.wait_for(timeout=600)`，标 failed |
| 所有 judge 全挂 | Partial | 该维度 score=None，case 其他维度继续 |
| 单个 judge 挂 | Partial | 剩余 judge 聚合 + `partial=True` |
| URL HEAD timeout | Cosmetic | 计入 broken_count，不重试 |
| LangSmith 上报失败 | Cosmetic | catch all，log warning，不影响主流程 |
| SQLite 写失败 | Cosmetic | fallback 到 jsonl，警告用户，主流程继续 |

### 6.2 重试与限流

| 类型 | 策略 |
|---|---|
| LLM API 429 / 5xx | exponential backoff 重试 3 次：1s → 4s → 16s |
| LLM API 超时 | 60s timeout，重试 2 次 |
| LLM 返回非 JSON / 非数字 | regex 抽数字兜底，再失败标 failed |
| PG checkpoint 读不到 | sleep 5s 重读一次，仍读不到标 partial |
| URL HEAD 失败 | 5s timeout，失败计 broken_count |

### 6.3 限流自适应

```python
qwen_limiter = AsyncLimiter(max_rate=50, time_period=60)
deepseek_limiter = AsyncLimiter(max_rate=50, time_period=60)
mimo_limiter = AsyncLimiter(max_rate=30, time_period=60)
bocha_limiter = AsyncLimiter(max_rate=8, time_period=1)

async with qwen_limiter:
    await client.chat.completions.create(...)
```

数值在 spec 标"可调"，跑一次后看 metrics 调整。

### 6.4 可观测性

- 结构化日志：每个 case 全程 `[case_id] phase=... duration=... tokens=...`
- 进度条（`rich`）：`Eval Progress: 23/30 [████░░] 76% | 4 failed | ETA 5m12s`
- 报表底部专节列 Failed / Low-confidence cases

## 7. 测试策略（Meta-Eval）

### 7.1 原则

- 单测全 mock，**不烧 LLM 钱**
- 不测 service / agent / graph 内部（黑盒消费）
- 不真打 dashscope/deepseek/mimo API
- 目标覆盖率 70%+，重点在分支逻辑（retry、降级、聚合）

### 7.2 覆盖矩阵

| 模块 | 单测要点 |
|---|---|
| 每个 Evaluator | ①fixture state 跑出预期 score ②judge 异常时降级正确 ③score 范围合法 |
| Citation | ①引用编号合法性 ②mock URL 200/404/timeout ③加权得分 |
| CriticLoop | ①resolution_rate 计算 ②0 feedback → score=N/A |
| JudgeClient | ①正常返回 ②429 重试 ③解析非数字 fallback ④全失败标 failed |
| EnsembleJudge | ①3 judge 全成功 → mean ②1 挂 → 用剩 2 + partial ③全挂 → score=None |
| Storage | ①schema 创建 ②写入读出对称 ③重复写入幂等 |
| Reporter | ①30 case 全成功 → 完整表 ②含 failed/partial → 报告分节 |
| Runner smoke | mock service + mock judge → 验证完整链路产出报表 |

### 7.3 关键 fixture

- `tests/fixtures/sample_state.json` — 一个真实跑完的 ResearchState 快照，commit 进仓库
- `tests/fixtures/sample_judge_responses.json` — 各种 judge 返回（含异常）
- `conftest.py` 提供 `mock_judge` / `mock_aiohttp` / `sample_state`

### 7.4 手动联调

`python -m app.eval.cli smoke --query "..."`：
- 1 条 query 真跑完整流程
- 真调 LLM judge / 真访 URL / 真上 LangSmith
- 用于：新部署环境冒烟 / API key 检查 / 改完代码人工抽查

### 7.5 CI 集成

```yaml
# .github/workflows/eval.yml
on:
  pull_request:
    paths: ['backend/app/eval/**']
  workflow_dispatch:
    inputs:
      suite:
        default: "full"
      concurrency:
        default: "5"

jobs:
  unit-tests:        # PR 必跑，不联网
    - pytest backend/app/eval/tests/

  eval-suite:        # workflow_dispatch 手动触发
    - python -m app.eval.cli run --suite=${{ inputs.suite }}
    - 上传 markdown/csv artifact
```

## 8. 风险与开放问题

| 风险 | 缓解 |
|---|---|
| 小米 MiMo API 实际不稳定 / model name 与文档不符 | 启动前 smoke 一次；不通则 fallback 到智谱 GLM-4 或月之暗面 Kimi 保持三家族 |
| LangSmith 免费额度（5k traces/月）超限 | 设置 sampling rate，eval 跑全量，开发期采样上报 |
| dashscope/deepseek 限流变更 | aiolimiter 数值留可调；retry 失败次数累计警报 |
| LLM judge 对中文行业报告评分不稳定 | ensemble 三家族 + 方差监控；方差 > 2 标 low_confidence 红色标注 |
| 30 case 真跑约 30-40min × ~3-5 RMB judge 调用 | 调优时用 `--suite=mini`（5 case）；正式 run 才用 full |
| eval 自己引入 bug 导致评分错误 | meta-eval 测试覆盖 ≥ 70%；smoke 命令人工抽查 |

## 9. 简历叙事（设计意图）

实施完成后，对外可讲：

- 自建 multi-agent eval 框架，7 维 evaluator + 3-家族 ensemble judge
- 实现自适应限流 + exponential backoff + judge 容错降级，5 并发跑 30 query
- LangSmith trace 集成，run-level 可观测
- pytest 覆盖率 70%+，CI workflow_dispatch 手动触发
- 量化展示 critic-revise 循环有效性（multi-agent 系统差异化 metric）

## 10. 不在本 spec 范围内的后续工作

由后续 ADR 决定：

- 是否扩到 100+ case
- 是否做 reference-based eval（需人工标注预算）
- 是否引入 HTML/plotly dashboard（替代 markdown 报表）
- 是否做 PR gate（需评估成本）
- 多轮 eval 趋势分析、跨 model 对比的可视化

---

**实施计划由 writing-plans skill 后续生成。**
