# 意图识别 Eval 框架设计

> 目标：为分层意图识别（Level 1 四类意图 + Level 2 三类研究类型）建立一套可重复、可回归的准确率评测框架，独立于已有的 deep research 报告质量 eval 框架。

---

## 1. 背景与动机

### 1.1 当前状态

项目已上线**分层意图识别**：

- **Level 1（`IntentService`）**：四类意图分类（`deep_research` / `web_search` / `simple_qa` / `out_of_scope`），用 DashScope `qwen-turbo` function calling，失败 fallback 到 `deep_research`。
- **Level 2（`ResearchTypeService`）**：三类研究类型分类（`industry_analysis` / `company_research` / `comparative_analysis`），仅在 Level 1 命中 `deep_research` 时触发，失败 fallback 到 `industry_analysis`。

现有 `backend/test/test_intent_service.py` 是 mock 单元测试 —— 验证「假设 LLM 返回 X，service 是否正确解析」，**完全没有真实准确率评估**。

### 1.2 为什么不复用 `backend/app/eval/`

已有的 eval 框架（`backend/app/eval/`）针对**多 agent 深度研究报告质量**评测：

| 维度 | 报告质量 eval（现有） | 意图识别 eval（本设计） |
|---|---|---|
| 评估范式 | LLM-as-judge（连续分） | reference-based（离散标签） |
| 主要指标 | 7 维 evaluator × 0-10 分 | accuracy / P / R / F1 / confusion matrix |
| 单 case 耗时 | 25-30 min | ~1 秒 |
| 单次 run 成本 | ~30 RMB | ~0.3 RMB |
| 持久化设计 | 3 表 SQLite + LangSmith trace | 2 表 SQLite + markdown 报表 |
| 阻塞流程 | 重型，PG checkpoint 读取 | 轻型，直接调 service |

两套框架在概念上正交（subjective quality vs objective classification），强行复用脚手架会引入概念污染。本框架是独立模块，未来若做"统一 eval dashboard"再做聚合层即可。

### 1.3 用途定位

**单一目标**：开发期验收 + prompt/schema 迭代时的回归保护。

- 改 prompt 描述前后各跑一次，肉眼对比 confusion matrix 和 badcase 表
- 准确率不达标**不阻塞 PR**（接受 LLM ±1-2% 抖动现实）
- 不做模型选型对比、不做 prompt A/B、不做 cron 长跑告警

---

## 2. 非目标（Non-goals）

明确不做：

| 不做 | 理由 |
|---|---|
| PR 级 CI 守门 | LLM 抖动易假阳性 + 每 PR 烧 0.3 RMB 不划算（沿用 deep research eval 的决策） |
| 跨模型对比 dashboard | 当前生产唯一用 `qwen-turbo`，未来需要再扩 |
| Prompt A/B 测试矩阵 | 同上，本期 YAGNI |
| Cost / latency 维度 | `qwen-turbo` 太便宜太快不是瓶颈 |
| 人工标注的 reference report | 意图分类的 ground truth 就是 4 / 3 类 enum，不存在长答案 |
| 引入 sklearn / pandas | confusion matrix 和 P/R/F1 手算 ~50 行，避免依赖膨胀 |
| 实时用户 query 数据集 | v1 是手写数据集，标 selection bias 限制；未来 v2 接 LangSmith trace |
| `validate-dataset` / `history` / `compare` 子命令 | YAGNI，跑时自动校验 schema，历史靠 sqlite3 查、跨 run 比较看 markdown diff |

---

## 3. 架构概览

### 3.1 目录布局

```
backend/app/intent_eval/
├── __init__.py
├── types.py              # EvalCase / CaseResult / RunSummary dataclass
├── dataset.py            # 加载 jsonl + schema 校验
├── datasets/
│   └── intent_eval_v1.jsonl    # 80 条手写 query + 标签（commit）
├── runner.py             # asyncio.gather + Semaphore 并发执行
├── metrics.py            # confusion matrix / P / R / F1 / macro F1
├── reporter.py           # markdown 报表生成
├── storage.py            # SQLite 2 表 + WAL mode
├── run_eval.py           # argparse 入口
└── tests/                # pytest mock 单测
    ├── test_dataset.py
    ├── test_metrics.py
    ├── test_runner.py
    ├── test_reporter.py
    └── test_storage.py

backend/intent_eval_results/    # .gitignore，本地存档
├── intent_eval.db              # 跨 run SQLite
└── <ISO timestamp>-<git_sha>.md   # 每次跑的 markdown 报表

.github/workflows/
└── intent-eval.yml             # workflow_dispatch + upload-artifact
```

### 3.2 数据流

```
run_eval.py
    ↓
dataset.load("intent_eval_v1.jsonl")       → list[EvalCase] (80)
    ↓
runner.run(cases, concurrency=10)
    ├─ for each case:
    │    intent = await IntentService.classify(query)     [Level 1: 全部]
    │    if case.true_intent == "deep_research":
    │        rt = await ResearchTypeService.classify(query) [Level 2: 仅 20]
    │    → CaseResult(case, intent, rt, latency, error)
    │
    └─ asyncio.gather + Semaphore(10) 控制并发
    ↓
metrics.compute(case_results)
    → RunSummary { level1_accuracy, level2_accuracy,
                   level1_per_class, level2_per_class,
                   level1_confusion, level2_confusion }
    ↓
storage.save(run_summary, case_results)    → SQLite
reporter.write_markdown(run_summary, case_results, output_dir)
    ↓
print summary to stdout, exit 0
```

### 3.3 关键设计选择回顾

| 选择 | 决策 | 理由 |
|---|---|---|
| Level 2 评估范围 | 仅 `true_intent==deep_research` 的 20 条 | 与 Level 1 解耦：Level 2 反映自身能力，不受 Level 1 错误污染 |
| 错误处理 | 沿用 production fallback（超时返回 `deep_research, confidence=0.0`），不另算 | eval 反映用户真实体感，不计算"理想模型表现" |
| 结果存储 | 本地 SQLite，**`backend/intent_eval_results/` 加入 .gitignore** | 跨 run 历史在本机累积；CI 用 `--no-db` 只产 markdown artifact |
| Metrics 库 | 手算 P/R/F1 + confusion | 4 类 / 3 类规模手算 50 行，避免引 sklearn |
| 并发 | `asyncio.Semaphore(10)` | qwen-turbo QPM 200，10 并发安全；80 × 2 层 ≈ 100 calls，~2 min |

---

## 4. 数据集设计

### 4.1 文件格式

`backend/app/intent_eval/datasets/intent_eval_v1.jsonl`，每行一条：

```json
{
  "id": "intent-001",
  "query": "分析中国新能源汽车 2024 年市场竞争格局",
  "true_intent": "deep_research",
  "true_research_type": "industry_analysis",
  "subtype": "标准行业分析（直白表达）",
  "is_boundary": false
}
```

**字段规则**：

- `id`：字符串，全局唯一，格式 `intent-NNN`（三位数字）。
- `query`：原始查询文本，中文为主，允许少量中英混合 / 缩写。
- `true_intent`：枚举，必填，取自 `{deep_research, web_search, simple_qa, out_of_scope}`。
- `true_research_type`：枚举或 `null`。**仅当 `true_intent == "deep_research"` 时**为 `{industry_analysis, company_research, comparative_analysis}` 之一，其余情况必须为 `null`。
- `subtype`：人读字符串，记录"为什么这条标了这个意图"以便错误分析切片，不参与准确率计算。
- `is_boundary`：布尔，标记是否是有意设计的边界对抗 case，用于错误分析时单独切片。

### 4.2 分布（80 条）

| `true_intent` | n | 内部拆分 | `is_boundary` 占比 |
|---|---|---|---|
| `deep_research` | 20 | `industry_analysis` 7 + `company_research` 7 + `comparative_analysis` 6 | 4 / 20 |
| `web_search` | 20 | 时效查询 8 + 实时数据 6 + 近期新闻 6 | 4 / 20 |
| `simple_qa` | 20 | 术语定义 8 + 计算公式 4 + 概念辨析 4 + 常识科普 4 | 4 / 20 |
| `out_of_scope` | 20 | 闲聊 5 + 创作（诗 / 文案）4 + 跨领域问答 6 + 工具性请求（翻译 / 算数）5 | 4 / 20 |

**Level 2 评估样本**：20 条 `deep_research` 样本中，`industry_analysis` 7 / `company_research` 7 / `comparative_analysis` 6。

### 4.3 缓解 selection bias 的多样性策略

数据集由开发者（Claude）按预设子类型生成，本身有 selection bias。缓解措施：

1. **句式多样化**：每个子类型至少 3 种句式（直问 / 反问 / 求建议 / 求确认）。
2. **表达风格**：书面正式 + 口语化 + 缩写（"宁王" = 宁德时代）+ 含金融术语。
3. **长度跨度**：5 字短问 → 60 字含背景的长问。
4. **跨意图边界**：每类内 20%（4 条）标记 `is_boundary=true`，刻意写易混淆的句式：
    - `web_search` 边界 → 「最新的市盈率定义」（带"最新"但本质 simple_qa）
    - `deep_research` 边界 → 「茅台和五粮液最近股价对比」（像 comparative_analysis 但偏 web_search 实时数据）
    - `simple_qa` 边界 → 「PE 和 PB 哪个估值方法更准」（像 comparative_analysis 但实际是术语辨析）
    - `out_of_scope` 边界 → 「帮我写段介绍宁德时代的文案」（混入了金融实体）

### 4.4 版本管理

- 文件名含版本号（`_v1.jsonl`），未来扩到 v2 时 v1 保留。
- 数据集修改（包括新增 case、修标签）必须升版本号，避免历史 run 对比因数据集变化而失真。

---

## 5. Runner 与 Metrics

### 5.1 Runner 执行逻辑

```python
async def run_one(case: EvalCase) -> CaseResult:
    started = time.perf_counter()
    error = None
    intent_result = None
    rt_result = None
    try:
        intent_result = await intent_service.classify(case.query)
        if case.true_intent == "deep_research":
            rt_result = await research_type_service.classify(case.query)
    except Exception as e:
        error = str(e)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return CaseResult(case=case, intent=intent_result,
                      research_type=rt_result, latency_ms=latency_ms, error=error)

async def run(cases, concurrency=10):
    sem = asyncio.Semaphore(concurrency)
    async def _bounded(c):
        async with sem:
            return await run_one(c)
    return await asyncio.gather(*[_bounded(c) for c in cases])
```

**错误处理语义**：

- `IntentService` / `ResearchTypeService` 自身有 fallback 逻辑，正常情况下不会抛出 → `intent_result.confidence == 0.0` 时本框架仍把它当作一个真实预测纳入准确率统计。
- 若两个 service 都意外抛出（不应发生），`error` 字段记录，对应预测视为 `None`，准确率分母仍计入（罚分），便于及时暴露异常。

### 5.2 Metrics 实现

`metrics.py` 提供纯函数：

```python
def confusion_matrix(true_labels: list[str], pred_labels: list[str],
                     classes: list[str]) -> dict[str, dict[str, int]]:
    ...

def per_class_prf(cm: dict, classes: list[str]) -> dict[str, dict[str, float]]:
    """返回 {class: {precision, recall, f1, support}}, 0 分母时返回 0.0"""
    ...

def macro_f1(per_class: dict) -> float:
    ...

def overall_accuracy(true_labels, pred_labels) -> float:
    ...
```

**数学定义**：

- `accuracy = sum(true == pred) / N`
- `precision[c] = TP[c] / (TP[c] + FP[c])`，分母为 0 时返回 0.0
- `recall[c] = TP[c] / (TP[c] + FN[c])`，分母为 0 时返回 0.0
- `f1[c] = 2 * P[c] * R[c] / (P[c] + R[c])`，分母为 0 时返回 0.0
- `macro_f1 = mean(f1[c] for c in classes)`

**为什么算 macro F1**：80 条按 4 类各 20 设计是平衡的，但 production 真实分布是 `deep_research` 占大头。macro F1 给少数类等权重，避免「整体准确率看着不错但小类全错」的假象。

**`error != null` 预测的处理**：在 case 抛出异常（service fallback 也失败）时，`pred_label` 为占位符 `"<error>"`：

- 该 case 必然计入 accuracy 分母且必然算错。
- 对真实类 `c` 而言：该 case 计为 `FN[c]`（漏召了），但不计入任何类的 `FP` 或 `TP`。
- 等价于 recall 会被拉低、precision 不受影响 —— 这正确反映了「框架挂了 = 召回失败但没误判」的语义。
- Confusion matrix 中额外加一列 `<error>`（仅当存在 error case 时出现），展示哪些真实类落进了 error 桶。

---

## 6. Markdown 报表

每次跑生成 `backend/intent_eval_results/<ISO>-<sha>.md`，结构固定，便于跨 run diff。

```markdown
# Intent Eval Report — 2026-05-30 14:32 @ 7b01c5a

- Dataset: intent_eval_v1.jsonl (80 cases, 4 intents × 20 + 3 research_types × 7/7/6)
- Level 1 model: qwen-turbo
- Level 2 model: qwen-turbo
- Duration: 118 sec
- Concurrency: 10

## Level 1: Intent Classification

**Overall Accuracy: 74/80 = 92.5%   Macro F1: 0.918**

### Per-class
| Intent | Support | Precision | Recall | F1 |
| ... |

### Confusion Matrix (rows=true, cols=pred)
| ... |

## Level 2: Research Type Classification (deep_research subset, n=20)

**Overall Accuracy: 18/20 = 90.0%   Macro F1: 0.889**

### Per-class
| ... |

### Confusion Matrix
| ... |

## Badcases

### Level 1 errors
| id | query | true | predicted | subtype | boundary |
| ... |

### Level 2 errors
| id | query | true | predicted | subtype |
| ... |

## Run Metadata
``json
{ "run_id": "...", "git_commit": "...", "dataset_version": "v1", ... }
``
```

**字段细节**：

- Query 列在 markdown 中**转义 `|`**（`query.replace("|", "\\|")`），避免破坏表格。
- Badcase 按 `is_boundary=true` 优先排在前面，方便先看对抗 case。
- 文件名 `<ISO timestamp>-<git_sha>.md`：ISO 用 `YYYY-MM-DDTHH:MM:SS` 不含时区（本机时间），sha 是当前 worktree HEAD short sha。

---

## 7. SQLite Schema

`backend/intent_eval_results/intent_eval.db`，2 表 + WAL mode + `busy_timeout=5000`：

```sql
CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    git_commit      TEXT,
    dataset_version TEXT NOT NULL,
    level1_model    TEXT NOT NULL,
    level2_model    TEXT NOT NULL,
    level1_n        INTEGER NOT NULL,
    level2_n        INTEGER NOT NULL,
    level1_accuracy REAL NOT NULL,
    level2_accuracy REAL NOT NULL,
    level1_macro_f1 REAL NOT NULL,
    level2_macro_f1 REAL NOT NULL
);

CREATE TABLE case_results (
    run_id                  TEXT NOT NULL,
    case_id                 TEXT NOT NULL,
    query                   TEXT NOT NULL,
    true_intent             TEXT NOT NULL,
    predicted_intent        TEXT,
    intent_correct          INTEGER NOT NULL,
    true_research_type      TEXT,
    predicted_research_type TEXT,
    research_type_correct   INTEGER,
    raw_response_json       TEXT,
    latency_ms              INTEGER NOT NULL,
    error                   TEXT,
    PRIMARY KEY (run_id, case_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX idx_case_results_run_id ON case_results(run_id);
```

**WAL 设置**：

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

**为何用 SQLite**：

- 单文件、可跨机器分享、不依赖外部数据库
- 支持 SQL 查历史 run（"近 10 次跑 deep_research 类 recall 趋势"一条 SQL 解决）
- WAL + busy_timeout 5s 容纳 10 并发写不撞锁

---

## 8. 入口脚本

`backend/app/intent_eval/run_eval.py`，argparse + asyncio：

```bash
python -m app.intent_eval.run_eval [options]
```

**参数**：

| 参数 | 默认值 | 用途 |
|---|---|---|
| `--dataset PATH` | `app/intent_eval/datasets/intent_eval_v1.jsonl` | 切换数据集 |
| `--concurrency N` | 10 | 并发上限 |
| `--level1-model NAME` | `qwen-turbo` | Level 1 用的模型 |
| `--level2-model NAME` | `qwen-turbo` | Level 2 用的模型 |
| `--output-dir DIR` | `intent_eval_results/` | 报表落盘位置（相对 backend/）|
| `--no-db` | False | 跳过 SQLite 写入（CI 用）|

**退出码**：

- `0`：跑完（不论准确率多少）
- `1`：框架自身错误（数据集解析失败 / SQLite 写不进 / 全部 LLM 调用都挂）

**stdout 输出示例**：

```
=== Intent Eval Run abc12345 ===
Dataset: intent_eval_v1.jsonl (80 cases)
Duration: 118 sec

Level 1 (intent):
  Accuracy: 92.5% (74/80)
  Macro F1: 0.918

Level 2 (research_type, n=20):
  Accuracy: 90.0% (18/20)
  Macro F1: 0.889

Report: backend/intent_eval_results/2026-05-30T14:32:00-7b01c5a.md
```

---

## 9. CI 集成

新增 `.github/workflows/intent-eval.yml`，沿用现有 `eval.yml` 的 `workflow_dispatch` 套路：

```yaml
name: Intent Eval
on:
  workflow_dispatch:
    inputs:
      dataset:
        description: 'Dataset name (without .jsonl)'
        default: 'intent_eval_v1'
      concurrency:
        description: 'Parallel runs'
        default: '10'

jobs:
  intent-eval:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
      LLM_BASE_URL: https://dashscope.aliyuncs.com/compatible-mode/v1
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        working-directory: backend
        run: pip install -r requirements.txt
      - name: Run intent eval
        working-directory: backend
        run: |
          python -m app.intent_eval.run_eval \
            --dataset app/intent_eval/datasets/${{ inputs.dataset }}.jsonl \
            --concurrency ${{ inputs.concurrency }} \
            --no-db
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: intent-eval-report
          path: backend/intent_eval_results/*.md
```

**不集成的事**：

- 不加 PR-level 跑（沿用 deep research eval 的决策）
- 不加 cron 定时跑（当前无生产监控需求）
- 不在 CI 内写 SQLite（runner 是干净环境，DB 即丢即弃）

---

## 10. 测试策略

`backend/app/intent_eval/tests/`，全部 mock LLM 不烧钱：

| 测试文件 | 覆盖 |
|---|---|
| `test_dataset.py` | jsonl 加载 + schema 校验：`true_research_type` 仅在 `deep_research` 时存在；不合法枚举值报错 |
| `test_metrics.py` | 手工构造 (true, pred) 列表 → 验证 accuracy / P / R / F1 / macro F1；含「某类 0 召回」/「某类 0 预测」的除零保护 |
| `test_runner.py` | mock IntentService / ResearchTypeService → 断言 Level 2 只在 `case.true_intent == "deep_research"` 时被调用；并发数受 Semaphore 限制 |
| `test_reporter.py` | mock CaseResult 列表 → 验证 markdown 报表结构（包含 confusion matrix / badcase 表 / metadata）；query 含 `|` 时正确转义 |
| `test_storage.py` | tmp SQLite → 写一个 run → 读回来一致；schema 自动建表 |

**不做**：跑真实 LLM 的端到端集成测试（那是 `run_eval` 本身的事，开发者本地跑一次即验证）。

---

## 11. Known Limitations

诚实标出，写进未来 v2 的 backlog：

1. **数据集是开发者手写 → 风格 bias**：80 条 query 由 Claude 按预设子类型生成，缺少真实用户句式覆盖的统计代表性。后续可接 LangSmith trace 里真实 query 做 v2 数据集（脱敏后）。
2. **Level 2 样本量小（20 条 / 每类 7/7/6）**：每类 P/R/F1 有 ±5% 噪声，单次跑的小波动不要过度解读。判断"是否真的退化"建议同一 prompt 连跑 3 次取均值。
3. **Ground truth 单标注者**：没有 inter-rater agreement 校验，边界 case 标签可能是开发者"觉得 X"而非"客观 X"。
4. **Eval 用的判别器和 production 是同一个**：没法发现"prompt 写得自己理解自己"的盲区。要解决得做 paired comparison 或换 judge 模型。
5. **不评 cost / latency**：`qwen-turbo` 当前足够便宜快，未来换贵模型需要补这两个维度。
6. **没有 PR-level 守门**：依赖开发者改 prompt / schema 时自觉手动触发 workflow_dispatch；忘了跑就没有保护。后续若意图识别准确率成为生产关键指标，再考虑做按需 PR 检查。

---

## 12. 验收清单

第一版完成的判定标准：

- [ ] `backend/app/intent_eval/` 全部模块实现 + 单测通过
- [ ] `intent_eval_v1.jsonl` 80 条手写完成，schema 校验通过
- [ ] `python -m app.intent_eval.run_eval` 本地跑通，产出 SQLite + markdown 报表
- [ ] `backend/intent_eval_results/` 加入 `.gitignore`
- [ ] `.github/workflows/intent-eval.yml` 注册 + 至少手动触发一次成功
- [ ] 跑一次真实 eval 得到基线 accuracy 数字（写进 commit 信息备查）
- [ ] 准确率明显异常的类（< 70%）做一轮 prompt / tool schema 调整再跑

---

## 附录 A：与现有 deep research eval 框架的边界

| 项 | Deep Research Eval（已有） | Intent Eval（本设计） |
|---|---|---|
| 目录 | `backend/app/eval/` | `backend/app/intent_eval/` |
| 数据集格式 | `seed_queries.jsonl`（30 条，无标签） | `intent_eval_v1.jsonl`（80 条，带标签） |
| 评估对象 | 多 agent 报告 | 意图分类器输出 |
| Judge 模型 | 3 家族 ensemble | 无（reference-based） |
| 主要指标 | 7 维 evaluator × 0-10 分 | accuracy / P / R / F1 / confusion matrix |
| 单 case 耗时 | ~25 min | ~1 sec |
| Run 总耗时 | ~30 min (5 并发) | ~2 min (10 并发) |
| 单 run 成本 | ~30 RMB | ~0.3 RMB |
| 持久化 | SQLite 3 表 + LangSmith trace | SQLite 2 表 + markdown |
| CI | `.github/workflows/eval.yml` | `.github/workflows/intent-eval.yml` |
| 共享代码 | 无（独立模块） | 无（独立模块） |

两套框架完全解耦，未来若做"统一 eval dashboard"再做聚合层。
