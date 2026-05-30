# 意图识别 Eval 框架实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为分层意图识别（Level 1 四类 + Level 2 三类）建立一套基于 reference dataset 的准确率评测框架，与现有 deep research eval 完全解耦。

**Architecture:** 新建 `backend/app/intent_eval/` 独立模块。Runner 用 `asyncio.gather + Semaphore(10)` 并发调用 `IntentService` / `ResearchTypeService`，把预测与 jsonl 标签对比，算 confusion matrix / per-class P/R/F1 / macro F1，落 SQLite + 生成 markdown 报表。CI 沿用现有 `eval.yml` 的 `workflow_dispatch` 套路。

**Tech Stack:** Python 3.11、`asyncio`、`argparse`、`sqlite3`（标准库）、`pytest` + `pytest-asyncio`、`unittest.mock`。**不引** sklearn / pandas / matplotlib。

**Spec:** `docs/superpowers/specs/2026-05-30-intent-recognition-eval-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/intent_eval/__init__.py` | 模块标识 |
| `backend/app/intent_eval/types.py` | 所有 dataclass + 类常量 |
| `backend/app/intent_eval/dataset.py` | jsonl 加载 + schema 校验 |
| `backend/app/intent_eval/datasets/intent_eval_v1.jsonl` | 80 条手写 query + 标签 |
| `backend/app/intent_eval/metrics.py` | confusion / P / R / F1 / macro / accuracy |
| `backend/app/intent_eval/storage.py` | SQLite 持久化（2 表 + WAL） |
| `backend/app/intent_eval/runner.py` | async 并发跑 intent + research_type service |
| `backend/app/intent_eval/reporter.py` | markdown 报表生成 |
| `backend/app/intent_eval/run_eval.py` | argparse 入口 + 总装 |
| `backend/app/intent_eval/tests/__init__.py` | 测试包标识 |
| `backend/app/intent_eval/tests/test_dataset.py` | 数据集加载测试 |
| `backend/app/intent_eval/tests/test_metrics.py` | 指标计算测试 |
| `backend/app/intent_eval/tests/test_storage.py` | SQLite 持久化测试 |
| `backend/app/intent_eval/tests/test_runner.py` | Runner 并发与调用条件测试 |
| `backend/app/intent_eval/tests/test_reporter.py` | Markdown 报表测试 |
| `.gitignore` (modify) | 加入 `backend/intent_eval_results/` |
| `.github/workflows/intent-eval.yml` | workflow_dispatch 触发 + artifact 上传 |

`backend/test/` 是项目历史的 mock 单测目录（继续保留 `test_intent_service.py`），新模块的单测就近放 `backend/app/intent_eval/tests/`，沿用 `backend/app/eval/tests/` 的约定。

---

## Task 1: Foundation — types + gitignore + 目录骨架

**Files:**
- Create: `backend/app/intent_eval/__init__.py`
- Create: `backend/app/intent_eval/types.py`
- Create: `backend/app/intent_eval/tests/__init__.py`
- Create: `backend/app/intent_eval/datasets/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: 在根 `.gitignore` 末尾添加 intent_eval 结果目录**

Append to `.gitignore`:

```
# Intent eval results (local-only)
backend/intent_eval_results/
```

- [ ] **Step 2: 创建空目录占位文件**

```bash
mkdir -p backend/app/intent_eval/datasets backend/app/intent_eval/tests
touch backend/app/intent_eval/__init__.py
touch backend/app/intent_eval/tests/__init__.py
touch backend/app/intent_eval/datasets/.gitkeep
```

- [ ] **Step 3: 写 `backend/app/intent_eval/types.py`**

```python
"""Intent eval 框架的所有 dataclass + 类常量定义。"""
from dataclasses import dataclass, field
from typing import Optional, Literal

INTENT_CLASSES: list[str] = ["deep_research", "web_search", "simple_qa", "out_of_scope"]
RESEARCH_TYPE_CLASSES: list[str] = ["industry_analysis", "company_research", "comparative_analysis"]
ERROR_LABEL: str = "<error>"

Intent = Literal["deep_research", "web_search", "simple_qa", "out_of_scope"]
ResearchType = Literal["industry_analysis", "company_research", "comparative_analysis"]


@dataclass(frozen=True)
class EvalCase:
    id: str
    query: str
    true_intent: str
    true_research_type: Optional[str]
    subtype: str
    is_boundary: bool


@dataclass
class CaseResult:
    case: EvalCase
    predicted_intent: Optional[str]
    predicted_research_type: Optional[str]
    intent_confidence: float
    research_type_confidence: Optional[float]
    intent_raw: dict
    research_type_raw: Optional[dict]
    latency_ms: int
    error: Optional[str]

    @property
    def intent_correct(self) -> bool:
        return self.predicted_intent == self.case.true_intent

    @property
    def research_type_correct(self) -> Optional[bool]:
        if self.case.true_research_type is None:
            return None
        return self.predicted_research_type == self.case.true_research_type


@dataclass
class PerClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class LevelMetrics:
    accuracy: float
    macro_f1: float
    per_class: dict[str, PerClassMetrics]
    confusion: dict[str, dict[str, int]]  # cm[true][pred] = count
    n: int


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    finished_at: str
    git_commit: str
    dataset_version: str
    level1_model: str
    level2_model: str
    concurrency: int
    duration_sec: float
    level1: LevelMetrics
    level2: LevelMetrics
```

- [ ] **Step 4: 写一个 smoke 测试 `tests/test_types_smoke.py`** *(顺便验证 conftest 把 backend/ 加到 sys.path 的链路通畅)*

Create `backend/app/intent_eval/tests/test_types_smoke.py`:

```python
"""Smoke test: 验证 types 模块可加载，dataclass 字段对得上。"""
from app.intent_eval.types import (
    EvalCase, CaseResult, PerClassMetrics, LevelMetrics, RunSummary,
    INTENT_CLASSES, RESEARCH_TYPE_CLASSES, ERROR_LABEL,
)


def test_intent_classes_correct():
    assert INTENT_CLASSES == ["deep_research", "web_search", "simple_qa", "out_of_scope"]


def test_research_type_classes_correct():
    assert RESEARCH_TYPE_CLASSES == ["industry_analysis", "company_research", "comparative_analysis"]


def test_eval_case_construct():
    c = EvalCase(
        id="intent-001", query="分析新能源汽车行业",
        true_intent="deep_research", true_research_type="industry_analysis",
        subtype="标准行业分析", is_boundary=False,
    )
    assert c.id == "intent-001"
    assert c.true_research_type == "industry_analysis"


def test_case_result_intent_correct():
    case = EvalCase(id="x", query="q", true_intent="simple_qa",
                    true_research_type=None, subtype="", is_boundary=False)
    cr = CaseResult(case=case, predicted_intent="simple_qa",
                    predicted_research_type=None, intent_confidence=1.0,
                    research_type_confidence=None, intent_raw={}, research_type_raw=None,
                    latency_ms=500, error=None)
    assert cr.intent_correct is True
    assert cr.research_type_correct is None


def test_case_result_research_type_correct():
    case = EvalCase(id="x", query="q", true_intent="deep_research",
                    true_research_type="company_research", subtype="", is_boundary=False)
    cr = CaseResult(case=case, predicted_intent="deep_research",
                    predicted_research_type="industry_analysis",
                    intent_confidence=1.0, research_type_confidence=1.0,
                    intent_raw={}, research_type_raw={}, latency_ms=500, error=None)
    assert cr.intent_correct is True
    assert cr.research_type_correct is False
```

- [ ] **Step 5: 运行测试验证通过**

Run from `backend/`:

```bash
pytest app/intent_eval/tests/test_types_smoke.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add .gitignore backend/app/intent_eval/
git commit -m "feat(intent-eval): 初始化模块骨架与 types 定义"
```

---

## Task 2: Metrics 模块（confusion matrix / P / R / F1 / macro）

**Files:**
- Create: `backend/app/intent_eval/metrics.py`
- Create: `backend/app/intent_eval/tests/test_metrics.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/app/intent_eval/tests/test_metrics.py`:

```python
"""Metrics 计算单测：构造已知 (true, pred) 对，验证 confusion / P / R / F1 / macro。"""
import pytest
from app.intent_eval.metrics import (
    confusion_matrix, per_class_metrics, accuracy, macro_f1, compute_level_metrics,
)
from app.intent_eval.types import ERROR_LABEL


def test_accuracy_basic():
    assert accuracy(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert accuracy(["a", "b", "c"], ["a", "b", "x"]) == pytest.approx(2 / 3)
    assert accuracy([], []) == 0.0


def test_confusion_matrix_basic():
    cm = confusion_matrix(
        true=["a", "a", "b", "b", "c"],
        pred=["a", "b", "b", "a", "c"],
        classes=["a", "b", "c"],
    )
    assert cm["a"]["a"] == 1
    assert cm["a"]["b"] == 1
    assert cm["a"]["c"] == 0
    assert cm["b"]["a"] == 1
    assert cm["b"]["b"] == 1
    assert cm["c"]["c"] == 1


def test_confusion_matrix_with_error_label():
    """error 预测进入 <error> 桶，不属于任何真实类。"""
    cm = confusion_matrix(
        true=["a", "b"],
        pred=[ERROR_LABEL, "b"],
        classes=["a", "b"],
    )
    assert cm["a"][ERROR_LABEL] == 1
    assert cm["a"]["a"] == 0
    assert cm["b"]["b"] == 1


def test_per_class_metrics_perfect():
    cm = confusion_matrix(
        true=["a", "a", "b", "b"],
        pred=["a", "a", "b", "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    assert metrics["a"].precision == 1.0
    assert metrics["a"].recall == 1.0
    assert metrics["a"].f1 == 1.0
    assert metrics["a"].support == 2


def test_per_class_metrics_mixed():
    # true:  a a a b b
    # pred:  a a b a b
    # class a: TP=2, FP=1, FN=1 → P=2/3, R=2/3, F1=2/3
    # class b: TP=1, FP=1, FN=1 → P=1/2, R=1/2, F1=1/2
    cm = confusion_matrix(
        true=["a", "a", "a", "b", "b"],
        pred=["a", "a", "b", "a", "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    assert metrics["a"].precision == pytest.approx(2 / 3)
    assert metrics["a"].recall == pytest.approx(2 / 3)
    assert metrics["a"].f1 == pytest.approx(2 / 3)
    assert metrics["a"].support == 3
    assert metrics["b"].precision == pytest.approx(0.5)
    assert metrics["b"].recall == pytest.approx(0.5)
    assert metrics["b"].f1 == pytest.approx(0.5)
    assert metrics["b"].support == 2


def test_per_class_metrics_zero_prediction():
    """某类从未被预测 → precision 分母 0，返回 0.0。"""
    cm = confusion_matrix(
        true=["a", "b"],
        pred=["a", "a"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    assert metrics["b"].precision == 0.0
    assert metrics["b"].recall == 0.0
    assert metrics["b"].f1 == 0.0
    assert metrics["b"].support == 1


def test_per_class_metrics_error_counts_as_fn():
    """error 预测对真实类是 FN，不影响别人的 FP/TP。"""
    cm = confusion_matrix(
        true=["a", "a", "b"],
        pred=["a", ERROR_LABEL, "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    # class a: TP=1, FP=0, FN=1 → P=1.0, R=0.5
    assert metrics["a"].precision == 1.0
    assert metrics["a"].recall == 0.5
    # class b: TP=1, FP=0, FN=0
    assert metrics["b"].precision == 1.0
    assert metrics["b"].recall == 1.0


def test_macro_f1():
    cm = confusion_matrix(
        true=["a", "a", "b", "b"],
        pred=["a", "b", "b", "b"],
        classes=["a", "b"],
    )
    metrics = per_class_metrics(cm, classes=["a", "b"])
    # a: P=1.0, R=0.5, F1=0.667
    # b: P=2/3, R=1.0, F1=0.8
    # macro = (0.667 + 0.8) / 2 ≈ 0.733
    assert macro_f1(metrics) == pytest.approx((2 / 3 + 0.8) / 2)


def test_compute_level_metrics_integration():
    """端到端：从原始 true/pred 列表算出完整 LevelMetrics。"""
    lm = compute_level_metrics(
        true_labels=["a", "a", "b", "b", "c"],
        pred_labels=["a", "b", "b", "a", "c"],
        classes=["a", "b", "c"],
    )
    assert lm.n == 5
    assert lm.accuracy == pytest.approx(3 / 5)
    assert "a" in lm.per_class
    assert lm.confusion["a"]["a"] == 1
```

- [ ] **Step 2: 运行测试验证 FAIL**

Run from `backend/`:

```bash
pytest app/intent_eval/tests/test_metrics.py -v
```

Expected: ImportError or ModuleNotFoundError on `app.intent_eval.metrics`.

- [ ] **Step 3: 写实现 `backend/app/intent_eval/metrics.py`**

```python
"""Confusion matrix + per-class P/R/F1 + macro F1 + overall accuracy。

设计：纯函数，不依赖外部 IO。所有除零情况返回 0.0 不抛异常，便于报表渲染。
"""
from typing import Iterable
from app.intent_eval.types import PerClassMetrics, LevelMetrics, ERROR_LABEL


def accuracy(true_labels: list[str], pred_labels: list[str]) -> float:
    if not true_labels:
        return 0.0
    correct = sum(1 for t, p in zip(true_labels, pred_labels) if t == p)
    return correct / len(true_labels)


def confusion_matrix(
    true: list[str], pred: list[str], classes: list[str]
) -> dict[str, dict[str, int]]:
    """rows=true label, cols=pred label。预测列含 ERROR_LABEL 桶以容纳异常 case。"""
    cols = list(classes) + [ERROR_LABEL]
    cm = {t: {p: 0 for p in cols} for t in classes}
    for t, p in zip(true, pred):
        if t not in cm:
            continue
        if p in cm[t]:
            cm[t][p] += 1
        else:
            # pred 不在已知集合（不应发生，但兜底）
            cm[t][ERROR_LABEL] = cm[t].get(ERROR_LABEL, 0) + 1
    return cm


def per_class_metrics(
    cm: dict[str, dict[str, int]], classes: list[str]
) -> dict[str, PerClassMetrics]:
    """从 confusion matrix 算 per-class P / R / F1 / support。

    Precision[c] = TP[c] / sum over true rows where pred=c
    Recall[c]    = TP[c] / sum of row c
    """
    out: dict[str, PerClassMetrics] = {}
    for c in classes:
        tp = cm.get(c, {}).get(c, 0)
        # FP = 所有真实类(≠c)预测为 c 的 → 跨行 cm[t][c] for t in classes if t != c
        fp = sum(cm.get(t, {}).get(c, 0) for t in classes if t != c)
        # FN = c 行除 c 列以外的所有列（含 ERROR_LABEL）
        fn = sum(v for col, v in cm.get(c, {}).items() if col != c)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        out[c] = PerClassMetrics(precision=precision, recall=recall, f1=f1, support=support)
    return out


def macro_f1(per_class: dict[str, PerClassMetrics]) -> float:
    if not per_class:
        return 0.0
    return sum(m.f1 for m in per_class.values()) / len(per_class)


def compute_level_metrics(
    true_labels: list[str], pred_labels: list[str], classes: list[str]
) -> LevelMetrics:
    cm = confusion_matrix(true_labels, pred_labels, classes)
    pc = per_class_metrics(cm, classes)
    return LevelMetrics(
        accuracy=accuracy(true_labels, pred_labels),
        macro_f1=macro_f1(pc),
        per_class=pc,
        confusion=cm,
        n=len(true_labels),
    )
```

- [ ] **Step 4: 运行测试验证 PASS**

```bash
pytest app/intent_eval/tests/test_metrics.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/intent_eval/metrics.py backend/app/intent_eval/tests/test_metrics.py
git commit -m "feat(intent-eval): 实现 confusion matrix 与 P/R/F1/macro 指标"
```

---

## Task 3: Dataset 加载与 schema 校验

**Files:**
- Create: `backend/app/intent_eval/dataset.py`
- Create: `backend/app/intent_eval/tests/test_dataset.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/app/intent_eval/tests/test_dataset.py`:

```python
"""Dataset 加载与 schema 校验测试。"""
import json
import pytest
from pathlib import Path
from app.intent_eval.dataset import load, DatasetError


def _write_jsonl(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "ds.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def test_load_valid(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q1", "true_intent": "simple_qa",
         "true_research_type": None, "subtype": "x", "is_boundary": False},
        {"id": "intent-002", "query": "q2", "true_intent": "deep_research",
         "true_research_type": "industry_analysis", "subtype": "y", "is_boundary": True},
    ])
    cases = load(p)
    assert len(cases) == 2
    assert cases[0].true_intent == "simple_qa"
    assert cases[0].true_research_type is None
    assert cases[1].true_research_type == "industry_analysis"
    assert cases[1].is_boundary is True


def test_load_invalid_intent_enum(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "nonsense",
         "true_research_type": None, "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="invalid true_intent"):
        load(p)


def test_load_invalid_research_type_enum(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "deep_research",
         "true_research_type": "wrong_type", "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="invalid true_research_type"):
        load(p)


def test_load_research_type_missing_on_deep_research(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "deep_research",
         "true_research_type": None, "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="true_research_type required"):
        load(p)


def test_load_research_type_set_on_non_deep_research(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "simple_qa",
         "true_research_type": "industry_analysis", "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="true_research_type must be null"):
        load(p)


def test_load_missing_field(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q", "true_intent": "simple_qa"},
    ])
    with pytest.raises(DatasetError, match="missing field"):
        load(p)


def test_load_duplicate_id(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"id": "intent-001", "query": "q1", "true_intent": "simple_qa",
         "true_research_type": None, "subtype": "", "is_boundary": False},
        {"id": "intent-001", "query": "q2", "true_intent": "simple_qa",
         "true_research_type": None, "subtype": "", "is_boundary": False},
    ])
    with pytest.raises(DatasetError, match="duplicate id"):
        load(p)


def test_load_file_not_found(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load(tmp_path / "missing.jsonl")
```

- [ ] **Step 2: 运行测试验证 FAIL**

```bash
pytest app/intent_eval/tests/test_dataset.py -v
```

Expected: ImportError on `app.intent_eval.dataset`.

- [ ] **Step 3: 写实现 `backend/app/intent_eval/dataset.py`**

```python
"""加载 intent eval jsonl 数据集并做 schema 校验。"""
import json
from pathlib import Path
from app.intent_eval.types import EvalCase, INTENT_CLASSES, RESEARCH_TYPE_CLASSES

REQUIRED_FIELDS = ["id", "query", "true_intent", "true_research_type", "subtype", "is_boundary"]


class DatasetError(ValueError):
    """数据集校验失败。"""


def _validate_row(row: dict, line_no: int) -> EvalCase:
    for field in REQUIRED_FIELDS:
        if field not in row:
            raise DatasetError(f"line {line_no}: missing field '{field}'")
    if row["true_intent"] not in INTENT_CLASSES:
        raise DatasetError(
            f"line {line_no}: invalid true_intent {row['true_intent']!r}, "
            f"expected one of {INTENT_CLASSES}"
        )
    if row["true_intent"] == "deep_research":
        if row["true_research_type"] is None:
            raise DatasetError(
                f"line {line_no}: true_research_type required when true_intent='deep_research'"
            )
        if row["true_research_type"] not in RESEARCH_TYPE_CLASSES:
            raise DatasetError(
                f"line {line_no}: invalid true_research_type {row['true_research_type']!r}, "
                f"expected one of {RESEARCH_TYPE_CLASSES}"
            )
    else:
        if row["true_research_type"] is not None:
            raise DatasetError(
                f"line {line_no}: true_research_type must be null when true_intent != 'deep_research'"
            )
    return EvalCase(
        id=row["id"],
        query=row["query"],
        true_intent=row["true_intent"],
        true_research_type=row["true_research_type"],
        subtype=row["subtype"],
        is_boundary=bool(row["is_boundary"]),
    )


def load(path: Path) -> list[EvalCase]:
    path = Path(path)
    if not path.exists():
        raise DatasetError(f"dataset file not found: {path}")
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise DatasetError(f"line {line_no}: invalid JSON ({e})")
            case = _validate_row(row, line_no)
            if case.id in seen_ids:
                raise DatasetError(f"line {line_no}: duplicate id {case.id!r}")
            seen_ids.add(case.id)
            cases.append(case)
    return cases
```

- [ ] **Step 4: 运行测试验证 PASS**

```bash
pytest app/intent_eval/tests/test_dataset.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/intent_eval/dataset.py backend/app/intent_eval/tests/test_dataset.py
git commit -m "feat(intent-eval): 实现 jsonl 数据集加载与 schema 校验"
```

---

## Task 4: 手写 80 条数据集 `intent_eval_v1.jsonl`

**Files:**
- Create: `backend/app/intent_eval/datasets/intent_eval_v1.jsonl`
- Create: `backend/app/intent_eval/tests/test_dataset_v1.py`

**分布要求**（必须严格满足）：

| true_intent | n | 子类型细分 | is_boundary 数量 |
|---|---|---|---|
| `deep_research` | 20 | `industry_analysis` 7 + `company_research` 7 + `comparative_analysis` 6 | 4 |
| `web_search` | 20 | 时效查询 8 + 实时数据 6 + 近期新闻 6 | 4 |
| `simple_qa` | 20 | 术语定义 8 + 计算公式 4 + 概念辨析 4 + 常识科普 4 | 4 |
| `out_of_scope` | 20 | 闲聊 5 + 创作 4 + 跨领域问答 6 + 工具性请求 5 | 4 |

**多样性要求**：

- 句式：直问 / 反问 / 求建议 / 求确认，至少 3 种
- 风格：书面正式 + 口语化 + 含缩写（"宁王"、"茅五泸"）+ 含金融术语
- 长度：5-60 字跨度
- 每类至少 1 条中英混合
- 4 条 `is_boundary=true` 必须是有意设计的对抗 case，subtype 字段要写明对抗点

- [ ] **Step 1: 写自检测试**

Create `backend/app/intent_eval/tests/test_dataset_v1.py`:

```python
"""V1 数据集的分布与 schema 自检 —— 改数据集时立即捕捉漂移。"""
from pathlib import Path
from collections import Counter
from app.intent_eval.dataset import load

DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "intent_eval_v1.jsonl"


def test_total_count_is_80():
    cases = load(DATASET_PATH)
    assert len(cases) == 80


def test_intent_distribution():
    cases = load(DATASET_PATH)
    intent_counts = Counter(c.true_intent for c in cases)
    assert intent_counts == {
        "deep_research": 20,
        "web_search": 20,
        "simple_qa": 20,
        "out_of_scope": 20,
    }


def test_research_type_distribution():
    cases = load(DATASET_PATH)
    rt_counts = Counter(c.true_research_type for c in cases if c.true_research_type is not None)
    assert rt_counts == {
        "industry_analysis": 7,
        "company_research": 7,
        "comparative_analysis": 6,
    }


def test_boundary_count_per_intent():
    cases = load(DATASET_PATH)
    boundary_counts = Counter(c.true_intent for c in cases if c.is_boundary)
    assert boundary_counts == {
        "deep_research": 4,
        "web_search": 4,
        "simple_qa": 4,
        "out_of_scope": 4,
    }


def test_ids_are_sequential():
    cases = load(DATASET_PATH)
    ids = [c.id for c in cases]
    expected = [f"intent-{i:03d}" for i in range(1, 81)]
    assert sorted(ids) == sorted(expected)


def test_query_length_range():
    cases = load(DATASET_PATH)
    lengths = [len(c.query) for c in cases]
    assert min(lengths) >= 4
    assert max(lengths) <= 80
```

- [ ] **Step 2: 运行测试验证 FAIL**

```bash
pytest app/intent_eval/tests/test_dataset_v1.py -v
```

Expected: FAIL — 文件还不存在。

- [ ] **Step 3: 生成 80 条 jsonl**

Write `backend/app/intent_eval/datasets/intent_eval_v1.jsonl` —— 一行一条 JSON。**实施时请遵守以下生成准则**：

1. **按类别分批写**，每类 20 条，编号连续：
    - `intent-001` ~ `intent-020` = `deep_research`
    - `intent-021` ~ `intent-040` = `web_search`
    - `intent-041` ~ `intent-060` = `simple_qa`
    - `intent-061` ~ `intent-080` = `out_of_scope`

2. **每类内 4 条 `is_boundary=true`**（占 20%），故意设计混淆点；其余 16 条覆盖标准子类型。

3. **subtype 字段**用中文短语描述子类型（用于错误分析切片），如「标准行业分析」、「公司缩写指代」、「术语定义（口语化）」、「时效查询带'最新'」等。

4. **示例样本**（每类各列出 1-2 条边界 case + 1 条标准 case 作为风格参考）：

```jsonl
{"id": "intent-001", "query": "分析中国新能源汽车 2024 年的市场竞争格局", "true_intent": "deep_research", "true_research_type": "industry_analysis", "subtype": "标准行业分析（直白）", "is_boundary": false}
{"id": "intent-002", "query": "茅台和五粮液最近股价表现对比", "true_intent": "deep_research", "true_research_type": "comparative_analysis", "subtype": "对比分析（含'最近'易误判 web_search）", "is_boundary": true}
{"id": "intent-021", "query": "今天黄金价格多少", "true_intent": "web_search", "true_research_type": null, "subtype": "实时数据（标准）", "is_boundary": false}
{"id": "intent-022", "query": "最新的市盈率 PE 是什么意思", "true_intent": "web_search", "true_research_type": null, "subtype": "时效词混术语定义（易误判 simple_qa）", "is_boundary": true}
{"id": "intent-041", "query": "什么是 ROE", "true_intent": "simple_qa", "true_research_type": null, "subtype": "术语定义（标准）", "is_boundary": false}
{"id": "intent-042", "query": "PE 和 PB 哪个估值方法更准", "true_intent": "simple_qa", "true_research_type": null, "subtype": "术语辨析（像 comparative_analysis）", "is_boundary": true}
{"id": "intent-061", "query": "帮我写首关于春天的诗", "true_intent": "out_of_scope", "true_research_type": null, "subtype": "创作（标准）", "is_boundary": false}
{"id": "intent-062", "query": "帮我写段介绍宁德时代的市场推广文案", "true_intent": "out_of_scope", "true_research_type": null, "subtype": "创作（含金融实体易误判 deep_research）", "is_boundary": true}
```

5. **多样性硬性要求清单**：
    - [x] 每类至少 1 条中英混合（如「ROE 是什么意思」、「A 股 IPO 怎么算估值」）
    - [x] 每类至少 1 条带缩写（"宁王"、"茅五泸"、"光伏一哥"、"PE/PB"）
    - [x] 每类至少 1 条带口语化（"咋样"、"啥"、"行不行"）
    - [x] 长度跨度从 4-5 字（"什么是 PE"）到 60 字含背景（"我看新闻说光伏行业近期有政策调整，能不能帮我分析下..."）

6. **deep_research 子类型分布**：`industry_analysis` 7 条 + `company_research` 7 条 + `comparative_analysis` 6 条。每个 research_type 内的 4 条 is_boundary 平均分布。

7. **不写**：`industry_analysis` / `company_research` 之间的 boundary case 可以混在 deep_research 的 4 条 boundary 里（Level 2 错误分析需要）。

- [ ] **Step 4: 运行 v1 自检测试验证 PASS**

```bash
pytest app/intent_eval/tests/test_dataset_v1.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/intent_eval/datasets/intent_eval_v1.jsonl backend/app/intent_eval/tests/test_dataset_v1.py
git commit -m "feat(intent-eval): 添加 v1 数据集 80 条手写 query"
```

---

## Task 5: Storage 模块（SQLite + WAL）

**Files:**
- Create: `backend/app/intent_eval/storage.py`
- Create: `backend/app/intent_eval/tests/test_storage.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/app/intent_eval/tests/test_storage.py`:

```python
"""SQLite 持久化单测：写一个 run + cases，读回来字段一致。"""
import sqlite3
from pathlib import Path
from app.intent_eval.storage import Storage
from app.intent_eval.types import (
    EvalCase, CaseResult, PerClassMetrics, LevelMetrics, RunSummary,
)


def _sample_summary(run_id: str = "run-001") -> RunSummary:
    pc1 = {c: PerClassMetrics(1.0, 1.0, 1.0, 5) for c in
           ["deep_research", "web_search", "simple_qa", "out_of_scope"]}
    cm1 = {c: {} for c in pc1}
    pc2 = {c: PerClassMetrics(1.0, 1.0, 1.0, 5) for c in
           ["industry_analysis", "company_research", "comparative_analysis"]}
    cm2 = {c: {} for c in pc2}
    return RunSummary(
        run_id=run_id,
        started_at="2026-05-30T14:00:00",
        finished_at="2026-05-30T14:02:00",
        git_commit="abc1234",
        dataset_version="v1",
        level1_model="qwen-turbo",
        level2_model="qwen-turbo",
        concurrency=10,
        duration_sec=120.0,
        level1=LevelMetrics(accuracy=0.95, macro_f1=0.94, per_class=pc1, confusion=cm1, n=80),
        level2=LevelMetrics(accuracy=0.9, macro_f1=0.89, per_class=pc2, confusion=cm2, n=20),
    )


def _sample_case_result(case_id: str = "intent-001") -> CaseResult:
    case = EvalCase(id=case_id, query="q", true_intent="simple_qa",
                    true_research_type=None, subtype="", is_boundary=False)
    return CaseResult(
        case=case, predicted_intent="simple_qa", predicted_research_type=None,
        intent_confidence=1.0, research_type_confidence=None,
        intent_raw={"name": "simple_qa"}, research_type_raw=None,
        latency_ms=512, error=None,
    )


def test_storage_creates_schema(tmp_path):
    db = tmp_path / "test.db"
    Storage(db).init_schema()
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"runs", "case_results"}
    conn.close()


def test_storage_wal_mode_enabled(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(db)
    s.init_schema()
    with s._conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_save_run_roundtrip(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(db)
    s.init_schema()
    summary = _sample_summary()
    cr = _sample_case_result()
    s.save_run(summary, [cr])
    conn = sqlite3.connect(db)
    runs = conn.execute("SELECT run_id, level1_accuracy, level2_macro_f1 FROM runs").fetchall()
    assert runs == [("run-001", 0.95, 0.89)]
    cases = conn.execute(
        "SELECT case_id, true_intent, predicted_intent, intent_correct FROM case_results"
    ).fetchall()
    assert cases == [("intent-001", "simple_qa", "simple_qa", 1)]
    conn.close()


def test_save_multiple_runs_independent(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(db)
    s.init_schema()
    s.save_run(_sample_summary("run-001"), [_sample_case_result("intent-001")])
    s.save_run(_sample_summary("run-002"), [_sample_case_result("intent-001")])
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert n == 2
    n_cases = conn.execute("SELECT COUNT(*) FROM case_results").fetchone()[0]
    assert n_cases == 2
    conn.close()


def test_init_schema_idempotent(tmp_path):
    db = tmp_path / "test.db"
    Storage(db).init_schema()
    Storage(db).init_schema()   # 二次调用不报错
```

- [ ] **Step 2: 运行测试验证 FAIL**

```bash
pytest app/intent_eval/tests/test_storage.py -v
```

Expected: ImportError on `app.intent_eval.storage`.

- [ ] **Step 3: 写实现 `backend/app/intent_eval/storage.py`**

```python
"""SQLite 持久化：2 表 + WAL mode + busy_timeout 5s。"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from app.intent_eval.types import CaseResult, RunSummary


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    git_commit      TEXT,
    dataset_version TEXT NOT NULL,
    level1_model    TEXT NOT NULL,
    level2_model    TEXT NOT NULL,
    concurrency     INTEGER NOT NULL,
    duration_sec    REAL NOT NULL,
    level1_n        INTEGER NOT NULL,
    level2_n        INTEGER NOT NULL,
    level1_accuracy REAL NOT NULL,
    level2_accuracy REAL NOT NULL,
    level1_macro_f1 REAL NOT NULL,
    level2_macro_f1 REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS case_results (
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

CREATE INDEX IF NOT EXISTS idx_case_results_run_id ON case_results(run_id);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def save_run(self, summary: RunSummary, case_results: list[CaseResult]) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO runs (
                    run_id, started_at, finished_at, git_commit, dataset_version,
                    level1_model, level2_model, concurrency, duration_sec,
                    level1_n, level2_n, level1_accuracy, level2_accuracy,
                    level1_macro_f1, level2_macro_f1
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    summary.run_id, summary.started_at, summary.finished_at,
                    summary.git_commit, summary.dataset_version,
                    summary.level1_model, summary.level2_model,
                    summary.concurrency, summary.duration_sec,
                    summary.level1.n, summary.level2.n,
                    summary.level1.accuracy, summary.level2.accuracy,
                    summary.level1.macro_f1, summary.level2.macro_f1,
                ),
            )
            rows = []
            for cr in case_results:
                raw = {
                    "intent": cr.intent_raw,
                    "research_type": cr.research_type_raw,
                }
                rt_correct = (
                    None if cr.research_type_correct is None
                    else int(cr.research_type_correct)
                )
                rows.append((
                    summary.run_id, cr.case.id, cr.case.query,
                    cr.case.true_intent, cr.predicted_intent,
                    int(cr.intent_correct),
                    cr.case.true_research_type, cr.predicted_research_type,
                    rt_correct,
                    json.dumps(raw, ensure_ascii=False),
                    cr.latency_ms, cr.error,
                ))
            conn.executemany(
                """INSERT INTO case_results (
                    run_id, case_id, query, true_intent, predicted_intent, intent_correct,
                    true_research_type, predicted_research_type, research_type_correct,
                    raw_response_json, latency_ms, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
```

- [ ] **Step 4: 运行测试验证 PASS**

```bash
pytest app/intent_eval/tests/test_storage.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/intent_eval/storage.py backend/app/intent_eval/tests/test_storage.py
git commit -m "feat(intent-eval): 实现 SQLite 持久化（2 表 + WAL）"
```

---

## Task 6: Runner 模块（async 并发）

**Files:**
- Create: `backend/app/intent_eval/runner.py`
- Create: `backend/app/intent_eval/tests/test_runner.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/app/intent_eval/tests/test_runner.py`:

```python
"""Runner 并发与调用条件测试。Mock service，不烧 LLM 钱。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.intent_eval.runner import run
from app.intent_eval.types import EvalCase


def _make_intent_result(name: str, confidence: float = 1.0, research_type: str = ""):
    """模拟 IntentService.classify 的返回 (IntentResult 鸭子类型)。"""
    return MagicMock(intent=name, research_type=research_type, confidence=confidence)


def _make_rt_result(name: str, confidence: float = 1.0):
    return MagicMock(research_type=name, confidence=confidence)


@pytest.fixture
def cases() -> list[EvalCase]:
    return [
        EvalCase(id="c1", query="q1", true_intent="deep_research",
                 true_research_type="industry_analysis", subtype="", is_boundary=False),
        EvalCase(id="c2", query="q2", true_intent="simple_qa",
                 true_research_type=None, subtype="", is_boundary=False),
        EvalCase(id="c3", query="q3", true_intent="web_search",
                 true_research_type=None, subtype="", is_boundary=False),
    ]


async def test_run_all_cases(cases):
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(side_effect=[
        _make_intent_result("deep_research", research_type="general"),
        _make_intent_result("simple_qa"),
        _make_intent_result("web_search"),
    ])
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    results = await run(cases, intent_svc, rt_svc, concurrency=2)
    assert len(results) == 3
    assert {r.case.id for r in results} == {"c1", "c2", "c3"}


async def test_level2_only_called_on_true_deep_research(cases):
    """Level 2 只在 true_intent == 'deep_research' 时调用，不管 Level 1 预测对错。"""
    intent_svc = MagicMock()
    # 故意让所有预测都是 simple_qa，验证 Level 2 是否仍在 c1 上跑
    intent_svc.classify = AsyncMock(return_value=_make_intent_result("simple_qa"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    await run(cases, intent_svc, rt_svc, concurrency=1)
    assert rt_svc.classify.call_count == 1   # 仅 c1
    rt_svc.classify.assert_called_with("q1")


async def test_level2_not_called_when_no_deep_research():
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(return_value=_make_intent_result("simple_qa"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock()

    cases = [
        EvalCase(id="c1", query="q1", true_intent="simple_qa",
                 true_research_type=None, subtype="", is_boundary=False),
        EvalCase(id="c2", query="q2", true_intent="web_search",
                 true_research_type=None, subtype="", is_boundary=False),
    ]
    await run(cases, intent_svc, rt_svc, concurrency=1)
    assert rt_svc.classify.call_count == 0


async def test_results_preserve_input_order(cases):
    """结果列表与输入 cases 同序，方便后续 metrics 对齐。"""
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(return_value=_make_intent_result("simple_qa"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    results = await run(cases, intent_svc, rt_svc, concurrency=2)
    assert [r.case.id for r in results] == ["c1", "c2", "c3"]


async def test_latency_recorded(cases):
    intent_svc = MagicMock()

    async def slow_classify(_):
        await asyncio.sleep(0.05)
        return _make_intent_result("simple_qa")

    intent_svc.classify = slow_classify
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock(return_value=_make_rt_result("industry_analysis"))

    results = await run(cases[:1], intent_svc, rt_svc, concurrency=1)
    assert results[0].latency_ms >= 50


async def test_service_exception_recorded_as_error(cases):
    """Service 直接抛异常 → CaseResult.error 记录，predicted_intent = None。"""
    intent_svc = MagicMock()
    intent_svc.classify = AsyncMock(side_effect=RuntimeError("boom"))
    rt_svc = MagicMock()
    rt_svc.classify = AsyncMock()

    results = await run(cases[:1], intent_svc, rt_svc, concurrency=1)
    assert results[0].predicted_intent is None
    assert results[0].error == "boom"


async def test_concurrency_limit_respected():
    """同时运行的协程不超过 concurrency 限制。"""
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def tracking_classify(_):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        return _make_intent_result("simple_qa")

    cases = [
        EvalCase(id=f"c{i}", query=f"q{i}", true_intent="simple_qa",
                 true_research_type=None, subtype="", is_boundary=False)
        for i in range(10)
    ]
    intent_svc = MagicMock(); intent_svc.classify = tracking_classify
    rt_svc = MagicMock(); rt_svc.classify = AsyncMock()

    await run(cases, intent_svc, rt_svc, concurrency=3)
    assert max_in_flight <= 3
```

- [ ] **Step 2: 运行测试验证 FAIL**

```bash
pytest app/intent_eval/tests/test_runner.py -v
```

Expected: ImportError on `app.intent_eval.runner`.

- [ ] **Step 3: 写实现 `backend/app/intent_eval/runner.py`**

```python
"""异步 runner：并发跑 IntentService + ResearchTypeService 并收集 CaseResult。

设计：依赖注入 service 实例，便于 mock 测试。结果列表与输入 cases 同序。
"""
import asyncio
import time
from dataclasses import asdict
from typing import Any
from app.intent_eval.types import EvalCase, CaseResult


def _to_dict_safely(obj: Any) -> dict:
    """把 IntentResult / ResearchTypeResult（dataclass 或 Mock）转 dict 落档。"""
    if obj is None:
        return {}
    try:
        return asdict(obj)
    except TypeError:
        # 非 dataclass（如 Mock），只取已知字段
        return {
            k: getattr(obj, k, None)
            for k in ("intent", "research_type", "confidence")
            if hasattr(obj, k)
        }


async def _run_one(
    case: EvalCase, intent_svc, research_type_svc
) -> CaseResult:
    started = time.perf_counter()
    error = None
    predicted_intent = None
    intent_confidence = 0.0
    intent_raw: dict = {}
    predicted_rt = None
    rt_confidence: float | None = None
    rt_raw: dict | None = None

    try:
        intent_result = await intent_svc.classify(case.query)
        predicted_intent = intent_result.intent
        intent_confidence = intent_result.confidence
        intent_raw = _to_dict_safely(intent_result)
        if case.true_intent == "deep_research":
            rt_result = await research_type_svc.classify(case.query)
            predicted_rt = rt_result.research_type
            rt_confidence = rt_result.confidence
            rt_raw = _to_dict_safely(rt_result)
    except Exception as e:
        error = str(e)

    latency_ms = int((time.perf_counter() - started) * 1000)
    return CaseResult(
        case=case,
        predicted_intent=predicted_intent,
        predicted_research_type=predicted_rt,
        intent_confidence=intent_confidence,
        research_type_confidence=rt_confidence,
        intent_raw=intent_raw,
        research_type_raw=rt_raw,
        latency_ms=latency_ms,
        error=error,
    )


async def run(
    cases: list[EvalCase],
    intent_svc,
    research_type_svc,
    concurrency: int = 10,
) -> list[CaseResult]:
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(case: EvalCase) -> CaseResult:
        async with sem:
            return await _run_one(case, intent_svc, research_type_svc)

    return await asyncio.gather(*[_bounded(c) for c in cases])
```

- [ ] **Step 4: 运行测试验证 PASS**

```bash
pytest app/intent_eval/tests/test_runner.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/intent_eval/runner.py backend/app/intent_eval/tests/test_runner.py
git commit -m "feat(intent-eval): 实现 async 并发 runner"
```

---

## Task 7: Reporter 模块（markdown 报表）

**Files:**
- Create: `backend/app/intent_eval/reporter.py`
- Create: `backend/app/intent_eval/tests/test_reporter.py`

- [ ] **Step 1: 写失败的测试**

Create `backend/app/intent_eval/tests/test_reporter.py`:

```python
"""Markdown 报表生成测试。"""
from pathlib import Path
from app.intent_eval.reporter import write_markdown, _escape_pipe
from app.intent_eval.types import (
    EvalCase, CaseResult, PerClassMetrics, LevelMetrics, RunSummary, ERROR_LABEL,
)
from app.intent_eval.metrics import compute_level_metrics


def _make_summary_and_results():
    cases = [
        EvalCase(id="intent-001", query="什么是 PE", true_intent="simple_qa",
                 true_research_type=None, subtype="术语定义", is_boundary=False),
        EvalCase(id="intent-002", query="茅台 | 五粮液 对比", true_intent="deep_research",
                 true_research_type="comparative_analysis", subtype="对比", is_boundary=True),
        EvalCase(id="intent-003", query="新能源行业现状", true_intent="deep_research",
                 true_research_type="industry_analysis", subtype="行业", is_boundary=False),
    ]
    results = [
        CaseResult(case=cases[0], predicted_intent="simple_qa", predicted_research_type=None,
                   intent_confidence=1.0, research_type_confidence=None,
                   intent_raw={}, research_type_raw=None, latency_ms=100, error=None),
        CaseResult(case=cases[1], predicted_intent="deep_research",
                   predicted_research_type="industry_analysis",
                   intent_confidence=1.0, research_type_confidence=1.0,
                   intent_raw={}, research_type_raw={}, latency_ms=200, error=None),
        CaseResult(case=cases[2], predicted_intent="deep_research",
                   predicted_research_type="industry_analysis",
                   intent_confidence=1.0, research_type_confidence=1.0,
                   intent_raw={}, research_type_raw={}, latency_ms=300, error=None),
    ]
    l1 = compute_level_metrics(
        [c.true_intent for c in cases],
        [r.predicted_intent for r in results],
        ["deep_research", "web_search", "simple_qa", "out_of_scope"],
    )
    l2_pairs = [(c.true_research_type, r.predicted_research_type)
                for c, r in zip(cases, results) if c.true_research_type]
    l2 = compute_level_metrics(
        [t for t, _ in l2_pairs], [p for _, p in l2_pairs],
        ["industry_analysis", "company_research", "comparative_analysis"],
    )
    summary = RunSummary(
        run_id="run-test",
        started_at="2026-05-30T14:00:00", finished_at="2026-05-30T14:02:00",
        git_commit="abc1234", dataset_version="v1",
        level1_model="qwen-turbo", level2_model="qwen-turbo",
        concurrency=10, duration_sec=120.0,
        level1=l1, level2=l2,
    )
    return summary, results


def test_escape_pipe():
    assert _escape_pipe("a|b") == "a\\|b"
    assert _escape_pipe("no pipe") == "no pipe"


def test_write_markdown_creates_file(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    assert out.exists()
    assert out.suffix == ".md"


def test_filename_format(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    # 文件名包含 finished_at 时间戳与 git_commit short sha
    assert "abc1234" in out.name


def test_report_contains_required_sections(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    md = out.read_text(encoding="utf-8")
    assert "# Intent Eval Report" in md
    assert "Level 1: Intent Classification" in md
    assert "Level 2: Research Type Classification" in md
    assert "Confusion Matrix" in md
    assert "Badcases" in md
    assert "Run Metadata" in md


def test_report_escapes_pipe_in_query(tmp_path):
    summary, results = _make_summary_and_results()
    out = write_markdown(summary, results, output_dir=tmp_path)
    md = out.read_text(encoding="utf-8")
    # badcase 表里 intent-002 query 含 |，必须转义
    assert "茅台 \\| 五粮液 对比" in md


def test_boundary_badcases_first(tmp_path):
    """is_boundary=true 的 badcase 应排在非 boundary 之前。"""
    summary, results = _make_summary_and_results()
    # 把 intent-001 改成预测错的非 boundary case
    results[0] = CaseResult(
        case=results[0].case, predicted_intent="web_search",
        predicted_research_type=None, intent_confidence=1.0,
        research_type_confidence=None, intent_raw={}, research_type_raw=None,
        latency_ms=100, error=None,
    )
    # intent-002 也错（是 boundary）
    results[1] = CaseResult(
        case=results[1].case, predicted_intent="simple_qa",
        predicted_research_type=None, intent_confidence=1.0,
        research_type_confidence=None, intent_raw={}, research_type_raw=None,
        latency_ms=200, error=None,
    )
    out = write_markdown(summary, results, output_dir=tmp_path)
    md = out.read_text(encoding="utf-8")
    idx_002 = md.find("intent-002")
    idx_001 = md.find("intent-001")
    assert 0 <= idx_002 < idx_001
```

- [ ] **Step 2: 运行测试验证 FAIL**

```bash
pytest app/intent_eval/tests/test_reporter.py -v
```

Expected: ImportError on `app.intent_eval.reporter`.

- [ ] **Step 3: 写实现 `backend/app/intent_eval/reporter.py`**

```python
"""生成 markdown 报表 + JSON 存档。

设计：纯函数，从 RunSummary + list[CaseResult] 渲染成单个 markdown 文件。
"""
import json
from pathlib import Path
from app.intent_eval.types import (
    CaseResult, LevelMetrics, RunSummary,
    INTENT_CLASSES, RESEARCH_TYPE_CLASSES, ERROR_LABEL,
)


def _escape_pipe(text: str) -> str:
    return text.replace("|", "\\|")


def _truncate(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n] + "…"


def _render_per_class_table(metrics: LevelMetrics, classes: list[str]) -> list[str]:
    lines = ["| Class | Support | Precision | Recall | F1 |",
             "|---|---:|---:|---:|---:|"]
    for c in classes:
        m = metrics.per_class[c]
        lines.append(f"| {c} | {m.support} | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} |")
    return lines


def _render_confusion_matrix(metrics: LevelMetrics, classes: list[str]) -> list[str]:
    has_error_col = any(metrics.confusion.get(t, {}).get(ERROR_LABEL, 0) > 0 for t in classes)
    cols = list(classes) + ([ERROR_LABEL] if has_error_col else [])
    header = "| true \\\\ pred | " + " | ".join(cols) + " |"
    sep = "|---|" + "|".join(["---:"] * len(cols)) + "|"
    lines = [header, sep]
    for t in classes:
        row_vals = []
        for c in cols:
            v = metrics.confusion.get(t, {}).get(c, 0)
            cell = f"**{v}**" if t == c else str(v)
            row_vals.append(cell)
        lines.append(f"| {t} | " + " | ".join(row_vals) + " |")
    return lines


def _render_badcases(case_results: list[CaseResult], for_level: int) -> list[str]:
    if for_level == 1:
        bad = [cr for cr in case_results if not cr.intent_correct]
        if not bad:
            return ["(no Level 1 errors)"]
        bad.sort(key=lambda cr: (not cr.case.is_boundary, cr.case.id))
        lines = ["| id | query | true | predicted | subtype | boundary |",
                 "|---|---|---|---|---|---|"]
        for cr in bad:
            lines.append(
                f"| {cr.case.id} | {_escape_pipe(_truncate(cr.case.query))} "
                f"| {cr.case.true_intent} | {cr.predicted_intent or ERROR_LABEL} "
                f"| {_escape_pipe(cr.case.subtype)} | {'✓' if cr.case.is_boundary else '✗'} |"
            )
        return lines
    # Level 2
    bad = [cr for cr in case_results
           if cr.case.true_research_type is not None and cr.research_type_correct is False]
    if not bad:
        return ["(no Level 2 errors)"]
    bad.sort(key=lambda cr: (not cr.case.is_boundary, cr.case.id))
    lines = ["| id | query | true | predicted | subtype |",
             "|---|---|---|---|---|"]
    for cr in bad:
        lines.append(
            f"| {cr.case.id} | {_escape_pipe(_truncate(cr.case.query))} "
            f"| {cr.case.true_research_type} | {cr.predicted_research_type or ERROR_LABEL} "
            f"| {_escape_pipe(cr.case.subtype)} |"
        )
    return lines


def write_markdown(
    summary: RunSummary, case_results: list[CaseResult], output_dir: Path
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = summary.finished_at.replace(":", "-")
    filename = f"{safe_ts}-{summary.git_commit[:7]}.md"
    out_path = output_dir / filename

    lines: list[str] = []
    lines.append(f"# Intent Eval Report — {summary.finished_at} @ {summary.git_commit[:7]}")
    lines.append("")
    lines.append(f"- Dataset version: {summary.dataset_version}")
    lines.append(f"- Level 1 model: {summary.level1_model}")
    lines.append(f"- Level 2 model: {summary.level2_model}")
    lines.append(f"- Duration: {summary.duration_sec:.1f} sec")
    lines.append(f"- Concurrency: {summary.concurrency}")
    lines.append("")

    # Level 1
    l1 = summary.level1
    lines.append("## Level 1: Intent Classification")
    lines.append("")
    lines.append(f"**Overall Accuracy: {int(l1.accuracy * l1.n)}/{l1.n} = "
                 f"{l1.accuracy * 100:.1f}%   Macro F1: {l1.macro_f1:.3f}**")
    lines.append("")
    lines.append("### Per-class")
    lines.extend(_render_per_class_table(l1, INTENT_CLASSES))
    lines.append("")
    lines.append("### Confusion Matrix (rows=true, cols=pred)")
    lines.extend(_render_confusion_matrix(l1, INTENT_CLASSES))
    lines.append("")

    # Level 2
    l2 = summary.level2
    lines.append(f"## Level 2: Research Type Classification (deep_research subset, n={l2.n})")
    lines.append("")
    lines.append(f"**Overall Accuracy: {int(l2.accuracy * l2.n)}/{l2.n} = "
                 f"{l2.accuracy * 100:.1f}%   Macro F1: {l2.macro_f1:.3f}**")
    lines.append("")
    lines.append("### Per-class")
    lines.extend(_render_per_class_table(l2, RESEARCH_TYPE_CLASSES))
    lines.append("")
    lines.append("### Confusion Matrix")
    lines.extend(_render_confusion_matrix(l2, RESEARCH_TYPE_CLASSES))
    lines.append("")

    # Badcases
    lines.append("## Badcases")
    lines.append("")
    lines.append("### Level 1 errors")
    lines.extend(_render_badcases(case_results, for_level=1))
    lines.append("")
    lines.append("### Level 2 errors")
    lines.extend(_render_badcases(case_results, for_level=2))
    lines.append("")

    # Metadata
    lines.append("## Run Metadata")
    lines.append("")
    meta = {
        "run_id": summary.run_id,
        "git_commit": summary.git_commit,
        "dataset_version": summary.dataset_version,
        "level1_model": summary.level1_model,
        "level2_model": summary.level2_model,
        "started_at": summary.started_at,
        "finished_at": summary.finished_at,
        "concurrency": summary.concurrency,
        "duration_sec": summary.duration_sec,
    }
    lines.append("```json")
    lines.append(json.dumps(meta, ensure_ascii=False, indent=2))
    lines.append("```")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
```

- [ ] **Step 4: 运行测试验证 PASS**

```bash
pytest app/intent_eval/tests/test_reporter.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/intent_eval/reporter.py backend/app/intent_eval/tests/test_reporter.py
git commit -m "feat(intent-eval): 实现 markdown 报表生成器"
```

---

## Task 8: 入口脚本 `run_eval.py`（argparse + 总装）

**Files:**
- Create: `backend/app/intent_eval/run_eval.py`

不写单测：这是组装层，靠 `dry run` 验证。

- [ ] **Step 1: 写实现 `backend/app/intent_eval/run_eval.py`**

```python
"""Intent eval 入口：argparse 参数 + 总装 dataset/runner/metrics/storage/reporter。

用法（CWD = backend/）：
    python -m app.intent_eval.run_eval --help
    python -m app.intent_eval.run_eval                          # 默认参数
    python -m app.intent_eval.run_eval --no-db                  # 跳过 SQLite
    python -m app.intent_eval.run_eval --concurrency 5
"""
import argparse
import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from app.intent_eval.dataset import load as load_dataset
from app.intent_eval.metrics import compute_level_metrics
from app.intent_eval.reporter import write_markdown
from app.intent_eval.runner import run as run_eval
from app.intent_eval.storage import Storage
from app.intent_eval.types import (
    RunSummary, INTENT_CLASSES, RESEARCH_TYPE_CLASSES,
)
from app.service.intent_service import IntentService
from app.service.research_type_service import ResearchTypeService


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m app.intent_eval.run_eval",
        description="Run intent recognition eval against current production model.",
    )
    default_ds = Path("app/intent_eval/datasets/intent_eval_v1.jsonl")
    p.add_argument("--dataset", type=Path, default=default_ds,
                   help="Path to jsonl dataset (default: %(default)s)")
    p.add_argument("--concurrency", type=int, default=10,
                   help="Max concurrent LLM calls (default: %(default)s)")
    p.add_argument("--level1-model", type=str, default="qwen-turbo",
                   help="Model for Level 1 intent (default: %(default)s)")
    p.add_argument("--level2-model", type=str, default="qwen-turbo",
                   help="Model for Level 2 research_type (default: %(default)s)")
    p.add_argument("--output-dir", type=Path, default=Path("intent_eval_results"),
                   help="Where to write markdown report (default: %(default)s)")
    p.add_argument("--no-db", action="store_true",
                   help="Skip SQLite persistence (use in CI)")
    return p.parse_args()


async def _main_async(args: argparse.Namespace) -> int:
    cases = load_dataset(args.dataset)
    print(f"Loaded {len(cases)} cases from {args.dataset}", file=sys.stderr)

    intent_svc = IntentService(model=args.level1_model)
    rt_svc = ResearchTypeService(model=args.level2_model)

    started_at = datetime.now().replace(microsecond=0).isoformat()
    import time as _t
    t0 = _t.perf_counter()
    results = await run_eval(cases, intent_svc, rt_svc, concurrency=args.concurrency)
    duration_sec = _t.perf_counter() - t0
    finished_at = datetime.now().replace(microsecond=0).isoformat()

    # Level 1 metrics: all cases
    true1 = [c.true_intent for c in cases]
    pred1 = [(r.predicted_intent or "<error>") for r in results]
    level1 = compute_level_metrics(true1, pred1, INTENT_CLASSES)

    # Level 2 metrics: only deep_research cases
    l2_pairs = [(c.true_research_type, (r.predicted_research_type or "<error>"))
                for c, r in zip(cases, results) if c.true_research_type is not None]
    if l2_pairs:
        true2 = [t for t, _ in l2_pairs]
        pred2 = [p for _, p in l2_pairs]
        level2 = compute_level_metrics(true2, pred2, RESEARCH_TYPE_CLASSES)
    else:
        # 防御：dataset 里没有 deep_research
        from app.intent_eval.types import LevelMetrics
        level2 = LevelMetrics(accuracy=0.0, macro_f1=0.0, per_class={}, confusion={}, n=0)

    summary = RunSummary(
        run_id=uuid.uuid4().hex[:12],
        started_at=started_at,
        finished_at=finished_at,
        git_commit=_git_commit(),
        dataset_version=args.dataset.stem.split("_")[-1] if "_" in args.dataset.stem else "v1",
        level1_model=args.level1_model,
        level2_model=args.level2_model,
        concurrency=args.concurrency,
        duration_sec=duration_sec,
        level1=level1,
        level2=level2,
    )

    report_path = write_markdown(summary, results, args.output_dir)

    if not args.no_db:
        db_path = args.output_dir / "intent_eval.db"
        storage = Storage(db_path)
        storage.init_schema()
        storage.save_run(summary, results)

    # stdout summary
    print()
    print(f"=== Intent Eval Run {summary.run_id} ===")
    print(f"Dataset: {args.dataset.name} ({len(cases)} cases)")
    print(f"Duration: {duration_sec:.0f} sec")
    print()
    print("Level 1 (intent):")
    print(f"  Accuracy: {level1.accuracy * 100:.1f}% "
          f"({int(level1.accuracy * level1.n)}/{level1.n})")
    print(f"  Macro F1: {level1.macro_f1:.3f}")
    print()
    print(f"Level 2 (research_type, n={level2.n}):")
    print(f"  Accuracy: {level2.accuracy * 100:.1f}% "
          f"({int(level2.accuracy * level2.n)}/{level2.n})")
    print(f"  Macro F1: {level2.macro_f1:.3f}")
    print()
    print(f"Report: {report_path}")
    return 0


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_main_async(args))
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行 `--help` 烟测**

```bash
cd backend
python -m app.intent_eval.run_eval --help
```

Expected: 打印 argparse help，列出 6 个参数，退出码 0。

- [ ] **Step 3: Commit**

```bash
git add backend/app/intent_eval/run_eval.py
git commit -m "feat(intent-eval): 实现 run_eval 入口脚本"
```

---

## Task 9: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/intent-eval.yml`

- [ ] **Step 1: 写 workflow**

```yaml
name: Intent Eval

on:
  workflow_dispatch:
    inputs:
      dataset:
        description: 'Dataset name (without .jsonl)'
        default: 'intent_eval_v1'
        required: true
      concurrency:
        description: 'Parallel runs'
        default: '10'
        required: true

jobs:
  intent-eval:
    name: Run intent eval
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
      - name: Upload markdown report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: intent-eval-report
          path: backend/intent_eval_results/*.md
```

- [ ] **Step 2: YAML lint 烟测**（CI yml 没有专属 lint runner，先看本地 git 能 commit）

```bash
git add .github/workflows/intent-eval.yml
```

- [ ] **Step 3: Commit**

```bash
git commit -m "ci: 添加 intent eval workflow_dispatch"
```

---

## Task 10: 跑一次真实 eval 建立 baseline

**Files:**
- Use existing: `backend/app/intent_eval/run_eval.py`
- Output: `backend/intent_eval_results/<ts>-<sha>.md`（本地）

不写代码，验证整条链路真的能跑通 + 记录基线数字。

- [ ] **Step 1: 确认 `.env` 里有 `DASHSCOPE_API_KEY`**

```bash
cd backend
grep -q "^DASHSCOPE_API_KEY=" ../.env && echo "key present" || echo "MISSING"
```

如缺失 → 让用户填 `.env`，stop。

- [ ] **Step 2: 跑全套测试**

```bash
pytest app/intent_eval/ -v
```

Expected: 全 pass（约 36+ 个测试，含 v1 数据集自检 6 个）。

- [ ] **Step 3: 跑真实 eval**

```bash
python -m app.intent_eval.run_eval
```

Expected: 终端打印 Level 1 / Level 2 accuracy 与 macro F1；`backend/intent_eval_results/` 产出 markdown 报表 + `intent_eval.db`。耗时 < 5 min。

- [ ] **Step 4: 读 markdown 报表，检查异常**

```bash
ls -lt backend/intent_eval_results/*.md | head -1
```

打开最新的 md 检查：
- [ ] 任一类 accuracy < 70%（应当考虑是 prompt 问题还是数据集标签问题）
- [ ] confusion matrix 里 `<error>` 列是否为 0（非 0 说明 service 抛了未被 fallback 拦住的异常）
- [ ] badcase 表里 boundary case 错的占比（应当 > 非 boundary，否则数据集 boundary 设计不到位）

- [ ] **Step 5: 把基线数字写进 commit 信息**

```bash
git commit --allow-empty -m "$(cat <<'EOF'
chore(intent-eval): 记录首次真实跑 baseline

Level 1 accuracy: NN.N% (XX/80), macro F1: 0.NNN
Level 2 accuracy: NN.N% (XX/20), macro F1: 0.NNN

Duration: NN sec @ qwen-turbo, concurrency=10

具体报表见 backend/intent_eval_results/<file>.md
EOF
)"
```

把 `NN.N` / `XX` 替换为真实数字。

---

## Self-Review

### Spec 覆盖核对

| Spec 节 | 对应 Task |
|---|---|
| §3.1 目录布局 | Task 1 + Task 5/6/7/8 各自的 file |
| §3.2 数据流 | Task 8 run_eval.py 串起来 |
| §3.3 关键设计选择 | Task 6（Level 2 只在 true_intent==deep_research 时跑）+ Task 6（error 沿用 production fallback）+ Task 1（.gitignore） |
| §4.1 数据集 jsonl 字段 | Task 3 schema 校验 + Task 4 数据 |
| §4.2 分布表 | Task 4 自检测试 |
| §4.3 多样性策略 | Task 4 生成准则清单 |
| §4.4 版本管理 | Task 4 文件名 `_v1.jsonl` |
| §5.1 Runner 执行逻辑 | Task 6 |
| §5.2 Metrics + error 处理（FN[c]） | Task 2 含 `test_per_class_metrics_error_counts_as_fn` |
| §6 Markdown 报表 | Task 7 |
| §7 SQLite Schema | Task 5 |
| §8 入口脚本 argparse | Task 8 |
| §9 CI workflow | Task 9 |
| §10 测试策略（5 个测试文件） | Task 1-7 各自 test_ 文件 |
| §11 Known Limitations | 无对应 Task（写进 spec 已足够） |
| §12 验收清单 | Task 10 整体验收 |

所有节都有 task 对应，无遗漏。

### Placeholder 扫描

- 无 TBD / TODO 字样
- 所有 step 都有完整代码或具体命令
- 数据集 80 条没写完整 jsonl 但给了详细生成准则与 4 个示范样本，自检测试覆盖关键约束 → 这是「内容创作」而非「代码占位」，可接受。

### Type 一致性

- `EvalCase` 字段：所有用到的地方都按 `id/query/true_intent/true_research_type/subtype/is_boundary` 顺序
- `CaseResult.intent_correct` / `research_type_correct` 是 `@property`，所有用到的地方都按属性访问（Task 5 storage 用 `int(cr.intent_correct)`、Task 7 reporter 用 `not cr.intent_correct`）
- `LevelMetrics` 在 Task 1/2/5/7 中字段一致：`accuracy / macro_f1 / per_class / confusion / n`
- `RunSummary` 字段在 Task 1/5/7/8 一致
- `INTENT_CLASSES` / `RESEARCH_TYPE_CLASSES` / `ERROR_LABEL` 跨模块统一从 `types.py` 导入

无类型漂移。

---

## Execution Handoff

Plan 写完。
