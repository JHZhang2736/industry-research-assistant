# Eval Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `backend/app/service/deep_research_v2/` 多 agent 工作流构建端到端 + 选择性单 agent 自动化评测框架，7 维 evaluator + 3 家族 ensemble judge，本地 SQLite + LangSmith trace 上报，5 并发，markdown 报表。

**Architecture:** 独立 `backend/app/eval/` 包，作为 `DeepResearchV2Service` 的外部消费者；evaluator 一文件一职责；JudgeClient 全 OpenAI-compatible；`asyncio.Semaphore` 控制并发 + `aiolimiter` 兜底限流；retry + 降级容错。

**Tech Stack:** Python 3.11 / asyncio / `openai` SDK (OpenAI-compatible) / `aiohttp` / `aiolimiter` / `tenacity` / `langsmith` / `sqlite3` / `rich` / `pytest` + `pytest-asyncio` + `aresponses`

---

## File Structure

```
backend/app/eval/
├── __init__.py
├── types.py                            # EvalCase, EvalContext, EvalResult, JudgeScore, EnsembleResult
├── settings.py                         # 配置（env keys + 限流参数 + 单价表）
├── datasets/
│   ├── __init__.py
│   ├── seed_queries.jsonl              # 30 条 query (Task 18 生成)
│   └── generator.py                    # 一次性脚本
├── evaluators/
│   ├── __init__.py                     # registry: list[Evaluator]
│   ├── base.py                         # Evaluator 抽象
│   ├── cost.py
│   ├── latency.py
│   ├── critic_loop.py
│   ├── citation.py
│   ├── relevance.py
│   ├── coherence.py
│   ├── completeness.py
│   └── prompts/
│       ├── __init__.py
│       ├── relevance.md
│       ├── coherence.md
│       └── completeness.md
├── judges/
│   ├── __init__.py
│   ├── base.py                         # JudgeClient + retry + limiter
│   ├── deepseek.py
│   ├── mimo.py
│   ├── qwen.py
│   └── ensemble.py                     # EnsembleJudge
├── runner.py                           # 主跑器
├── reporter.py                         # markdown + csv
├── storage.py                          # SQLite
├── langsmith_adapter.py                # LangSmith 上报
└── cli.py                              # python -m app.eval.cli

backend/app/eval/tests/
├── __init__.py
├── conftest.py                         # fixtures
├── fixtures/
│   ├── sample_state.json
│   └── sample_judge_responses.json
├── test_types.py
├── test_judges/
│   ├── __init__.py
│   ├── test_base.py
│   └── test_ensemble.py
├── test_evaluators/
│   ├── __init__.py
│   ├── test_cost.py
│   ├── test_latency.py
│   ├── test_critic_loop.py
│   ├── test_citation.py
│   ├── test_relevance.py
│   ├── test_coherence.py
│   └── test_completeness.py
├── test_storage.py
├── test_reporter.py
└── test_runner_smoke.py

.github/workflows/eval.yml              # workflow_dispatch + PR unit-tests
docs/eval-results/                      # gitignored
```

Files-per-responsibility 检查：
- types.py 只放数据类，无逻辑
- judges/*.py 一家族一文件，base 抽象 retry/limiter
- evaluators/*.py 一维度一文件，base 抽象 evaluate 接口
- runner/reporter/storage/cli 单一职责
- 测试文件镜像源码结构

---

## Task 1: 准备目录骨架 + 依赖

**Files:**
- Create: `backend/app/eval/__init__.py`
- Create: `backend/app/eval/datasets/__init__.py`
- Create: `backend/app/eval/evaluators/__init__.py`
- Create: `backend/app/eval/evaluators/prompts/__init__.py`
- Create: `backend/app/eval/judges/__init__.py`
- Create: `backend/app/eval/tests/__init__.py`
- Create: `backend/app/eval/tests/fixtures/.gitkeep`
- Create: `backend/app/eval/tests/test_evaluators/__init__.py`
- Create: `backend/app/eval/tests/test_judges/__init__.py`
- Modify: `backend/requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: 创建 eval 包目录骨架（所有空 `__init__.py`）**

```bash
mkdir -p backend/app/eval/datasets
mkdir -p backend/app/eval/evaluators/prompts
mkdir -p backend/app/eval/judges
mkdir -p backend/app/eval/tests/fixtures
mkdir -p backend/app/eval/tests/test_evaluators
mkdir -p backend/app/eval/tests/test_judges
mkdir -p docs/eval-results

# 所有 __init__.py
for d in \
  backend/app/eval \
  backend/app/eval/datasets \
  backend/app/eval/evaluators \
  backend/app/eval/evaluators/prompts \
  backend/app/eval/judges \
  backend/app/eval/tests \
  backend/app/eval/tests/test_evaluators \
  backend/app/eval/tests/test_judges
do
  touch "$d/__init__.py"
done

touch backend/app/eval/tests/fixtures/.gitkeep
touch docs/eval-results/.gitkeep
```

- [ ] **Step 2: 追加依赖到 `backend/requirements.txt`**

在文件末尾追加：

```
# Eval framework
langsmith>=0.1.0
aiohttp>=3.9
aiolimiter>=1.1
tenacity>=8.2
rich>=13.0
pytest-asyncio>=0.23
aresponses>=3.0
```

- [ ] **Step 3: 追加到 `.gitignore`**

在文件末尾追加：

```
# Eval framework runtime output
docs/eval-results/*
!docs/eval-results/.gitkeep
backend/app/eval/.eval.db
backend/app/eval/.eval.db-*
```

- [ ] **Step 4: 安装依赖**

Run: `cd backend && pip install -r requirements.txt`
Expected: 成功安装 langsmith / aiohttp / aiolimiter / tenacity / rich / pytest-asyncio / aresponses（已有的会跳过）

- [ ] **Step 5: 验证 import 通**

Run:
```bash
cd backend && python -c "import langsmith, aiohttp, aiolimiter, tenacity, rich; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add backend/app/eval/ backend/requirements.txt .gitignore docs/eval-results/
git commit -m "chore(eval): 创建 eval 框架目录骨架与依赖"
```

---

## Task 2: types.py — 数据类定义

**Files:**
- Create: `backend/app/eval/types.py`
- Create: `backend/app/eval/tests/test_types.py`

- [ ] **Step 1: 写测试 `test_types.py`**

```python
"""Test eval types dataclasses."""
from datetime import datetime

from app.eval.types import (
    EvalCase, EvalContext, EvalResult,
    JudgeScore, EnsembleResult, CaseResult,
)


def test_eval_case_required_fields():
    case = EvalCase(id="q001", query="新能源汽车2024年", category="汽车", difficulty="easy")
    assert case.id == "q001"
    assert case.query == "新能源汽车2024年"
    assert case.category == "汽车"
    assert case.difficulty == "easy"


def test_judge_score_default_failed_false():
    s = JudgeScore(judge_name="qwen", score=8.0, reasoning="ok")
    assert s.failed is False
    assert s.error is None


def test_judge_score_failed_when_no_score():
    s = JudgeScore(judge_name="qwen", score=None, reasoning="", failed=True, error="parse error")
    assert s.failed is True
    assert s.score is None


def test_ensemble_result_mean_median_std():
    r = EnsembleResult(
        mean_score=7.5,
        median_score=8.0,
        std=1.0,
        individual=[],
        low_confidence=False,
        partial=False,
    )
    assert r.mean_score == 7.5
    assert r.std == 1.0
    assert r.low_confidence is False


def test_eval_result_default_metadata_is_dict():
    r = EvalResult(evaluator_name="cost", score=1.5, raw_judge_outputs=[])
    assert r.metadata == {}
    assert r.error is None
    assert r.low_confidence is False


def test_eval_context_construction():
    ctx = EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"final_report": "..."},
        started_at=datetime(2026, 5, 26, 14, 0, 0),
        finished_at=datetime(2026, 5, 26, 14, 5, 0),
    )
    assert ctx.duration_sec == 300.0


def test_case_result_ok_default():
    cr = CaseResult(case=EvalCase(id="q001", query="x", category="c", difficulty="easy"))
    assert cr.ok is True
    assert cr.error is None
    assert cr.results == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.eval.types'`

- [ ] **Step 3: 实现 `types.py`**

```python
"""Eval framework dataclasses.

Pure data structures, no logic. Used across runner, evaluators, judges, storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EvalCase:
    """One test query from the dataset."""
    id: str
    query: str
    category: str
    difficulty: str        # "easy" | "medium" | "hard"


@dataclass
class JudgeScore:
    """One judge's scoring of one prompt."""
    judge_name: str
    score: float | None
    reasoning: str
    failed: bool = False
    error: str | None = None


@dataclass
class EnsembleResult:
    """Aggregated score from multiple judges."""
    mean_score: float | None
    median_score: float | None
    std: float
    individual: list[JudgeScore]
    low_confidence: bool   # std > threshold
    partial: bool          # some judges failed
    error: str | None = None


@dataclass
class EvalResult:
    """One evaluator's output for one case."""
    evaluator_name: str
    score: float | None
    raw_judge_outputs: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error: str | None = None
    low_confidence: bool = False


@dataclass
class EvalContext:
    """Data passed to each evaluator."""
    case: EvalCase
    state: dict                          # ResearchState (final, from PG checkpoint)
    started_at: datetime
    finished_at: datetime

    @property
    def duration_sec(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


@dataclass
class CaseResult:
    """All evaluator outputs for one case, plus run-level status."""
    case: EvalCase
    results: list[EvalResult] = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    state: dict | None = None            # final state snapshot
    started_at: datetime | None = None
    finished_at: datetime | None = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_types.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/types.py backend/app/eval/tests/test_types.py
git commit -m "feat(eval): 添加 eval 数据类 (EvalCase/JudgeScore/EnsembleResult/EvalResult/EvalContext/CaseResult)"
```

---

## Task 3: settings.py — 配置中心

**Files:**
- Create: `backend/app/eval/settings.py`

- [ ] **Step 1: 实现 `settings.py`（无测试，纯配置）**

```python
"""Eval framework settings.

Reads from env vars. No dynamic imports. Override via os.environ in tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class JudgeConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str
    max_rate_per_min: int

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


# Three judge families
JUDGES: list[JudgeConfig] = [
    JudgeConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        model=os.getenv("DEEPSEEK_JUDGE_MODEL", "deepseek-chat"),
        api_key_env="DEEPSEEK_API_KEY",
        max_rate_per_min=50,
    ),
    JudgeConfig(
        name="mimo",
        base_url="https://api.xiaomimimo.com/v1",
        model=os.getenv("XIAOMI_JUDGE_MODEL", "mimo-v2.5-pro"),
        api_key_env="XIAOMI_API_KEY",
        max_rate_per_min=30,
    ),
    JudgeConfig(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model=os.getenv("QWEN_JUDGE_MODEL", "qwen-max"),
        api_key_env="DASHSCOPE_API_KEY",
        max_rate_per_min=50,
    ),
]


# Per-1M-tokens cost in RMB (input, output). Update when pricing changes.
PRICING_RMB_PER_M_TOKENS: dict[str, tuple[float, float]] = {
    "qwen-max": (20.0, 60.0),
    "qwen-plus": (4.0, 12.0),
    "qwen-turbo": (2.0, 6.0),
    "deepseek-chat": (1.0, 2.0),
    "deepseek-v3": (1.0, 2.0),
    "deepseek-v3.2": (1.0, 2.0),
    "mimo-v2.5-pro": (3.0, 9.0),  # placeholder, update from official pricing
}


# Eval suite defaults
DEFAULT_CONCURRENCY = 5
DEFAULT_RESEARCH_TIMEOUT_SEC = 600
DEFAULT_JUDGE_TIMEOUT_SEC = 60
JUDGE_RETRY_ATTEMPTS = 3
URL_CHECK_TIMEOUT_SEC = 5
LOW_CONFIDENCE_STD_THRESHOLD = 2.0

# SQLite storage path
SQLITE_PATH = os.getenv("EVAL_SQLITE_PATH", "backend/app/eval/.eval.db")

# LangSmith (optional)
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "industry-research-eval")
LANGSMITH_ENABLED = bool(os.getenv("LANGSMITH_API_KEY"))


def validate_required_keys() -> list[str]:
    """Return list of missing required env vars."""
    missing = []
    for j in JUDGES:
        if not j.api_key:
            missing.append(j.api_key_env)
    # Research itself needs these too
    for required in ("DASHSCOPE_API_KEY", "BOCHA_API_KEY"):
        if not os.getenv(required) and required not in missing:
            missing.append(required)
    return missing
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/eval/settings.py
git commit -m "feat(eval): settings 配置（3 judge + 单价表 + 限流参数 + LangSmith）"
```

---

## Task 4: JudgeClient 基类（含 retry + limiter）

**Files:**
- Create: `backend/app/eval/judges/base.py`
- Create: `backend/app/eval/tests/test_judges/test_base.py`
- Create: `backend/app/eval/tests/conftest.py`

- [ ] **Step 1: 写 conftest.py（共享 fixture）**

```python
"""Shared pytest fixtures for eval tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_state() -> dict:
    """A real ResearchState snapshot. Created on first test, then committed."""
    path = FIXTURES / "sample_state.json"
    if not path.exists():
        # Minimal fallback state so tests can run before Task 22 generates real one
        return {
            "query": "新能源汽车2024年市场现状",
            "session_id": "test-001",
            "phase": "completed",
            "iteration": 1,
            "outline": [
                {"id": "s1", "title": "市场规模", "description": "..."},
                {"id": "s2", "title": "竞争格局", "description": "..."},
            ],
            "facts": [
                {"id": "f1", "content": "2024 年销量 950 万辆",
                 "source_url": "https://example.com/a", "source_name": "中汽协"},
            ],
            "references": [
                {"id": "r1", "url": "https://example.com/a", "title": "中汽协报告"},
            ],
            "draft_sections": {"s1": "...", "s2": "..."},
            "final_report": "# 报告\n\n## 市场规模\n2024 年销量 [1]。\n\n## 竞争格局\n...",
            "critic_feedback": [
                {"id": "c1", "issue_type": "missing_source", "severity": "minor",
                 "description": "...", "resolved": True},
                {"id": "c2", "issue_type": "logic_error", "severity": "major",
                 "description": "...", "resolved": False},
            ],
            "quality_score": 7.5,
            "logs": [
                {"agent": "architect", "tokens_used": 1200, "duration_ms": 5000,
                 "model": "qwen-max"},
                {"agent": "scout", "tokens_used": 3400, "duration_ms": 20000,
                 "model": "qwen-plus"},
                {"agent": "writer", "tokens_used": 8000, "duration_ms": 30000,
                 "model": "deepseek-v3.2"},
            ],
            "errors": [],
            "messages": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def mock_openai_client():
    """Mock for openai.AsyncOpenAI."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


def make_openai_response(content: str) -> Any:
    """Build a fake openai response with given content."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = MagicMock()
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    return resp
```

- [ ] **Step 2: 写测试 `test_judges/test_base.py`**

```python
"""Test JudgeClient base behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.eval.judges.base import JudgeClient, parse_judge_response
from app.eval.tests.conftest import make_openai_response
from app.eval.settings import JudgeConfig


@pytest.fixture
def cfg():
    return JudgeConfig(
        name="testjudge",
        base_url="https://example.com/v1",
        model="test-model",
        api_key_env="TEST_KEY",
        max_rate_per_min=100,
    )


def test_parse_response_clean_json():
    out = parse_judge_response('{"score": 8.0, "reasoning": "good"}')
    assert out == (8.0, "good")


def test_parse_response_with_markdown_fence():
    raw = '```json\n{"score": 7.5, "reasoning": "ok"}\n```'
    out = parse_judge_response(raw)
    assert out == (7.5, "ok")


def test_parse_response_fallback_regex_on_invalid_json():
    raw = "judge thinks score is 6 because reasons"
    out = parse_judge_response(raw)
    # regex fallback: first number 0-10
    assert out[0] == 6.0
    assert out[1] == raw


def test_parse_response_raises_when_no_number():
    with pytest.raises(ValueError):
        parse_judge_response("totally garbage text")


@pytest.mark.asyncio
async def test_call_judge_happy_path(cfg, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "fake-key")
    client = JudgeClient(cfg)

    fake = make_openai_response('{"score": 8.5, "reasoning": "great"}')
    client._client.chat.completions.create = AsyncMock(return_value=fake)

    score = await client.call_judge("prompt")
    assert score.judge_name == "testjudge"
    assert score.score == 8.5
    assert score.failed is False


@pytest.mark.asyncio
async def test_call_judge_parse_failure_marks_failed(cfg, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "fake-key")
    client = JudgeClient(cfg)

    fake = make_openai_response("complete garbage")
    client._client.chat.completions.create = AsyncMock(return_value=fake)

    score = await client.call_judge("prompt")
    assert score.failed is True
    assert score.error is not None


@pytest.mark.asyncio
async def test_call_judge_api_error_retried_then_fails(cfg, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "fake-key")
    client = JudgeClient(cfg)

    client._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    score = await client.call_judge("prompt")
    assert score.failed is True
    assert "boom" in (score.error or "")
    # tenacity should have retried JUDGE_RETRY_ATTEMPTS times
    assert client._client.chat.completions.create.await_count >= 2
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_judges/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 实现 `judges/base.py`**

```python
"""JudgeClient base — OpenAI-compatible LLM judge with retry + rate limit."""
from __future__ import annotations

import json
import logging
import re

from aiolimiter import AsyncLimiter
from openai import AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.eval.settings import (
    DEFAULT_JUDGE_TIMEOUT_SEC,
    JUDGE_RETRY_ATTEMPTS,
    JudgeConfig,
)
from app.eval.types import JudgeScore

logger = logging.getLogger("eval.judge")


def parse_judge_response(raw: str) -> tuple[float, str]:
    """Parse judge raw output into (score, reasoning).

    Strategy: ① strip markdown fences → ② json.loads → ③ regex first 0-10 number.
    Raises ValueError if no usable number found.
    """
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "score" in obj:
            score = float(obj["score"])
            reasoning = str(obj.get("reasoning", ""))
            return score, reasoning
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # regex fallback: find first number that looks like a 0-10 score
    m = re.search(r"\b(?:10|10\.0|[0-9](?:\.\d+)?)\b", raw)
    if m:
        return float(m.group(0)), raw

    raise ValueError(f"could not parse score from judge response: {raw[:200]!r}")


class JudgeClient:
    """One judge family. OpenAI-compatible chat completions."""

    def __init__(self, cfg: JudgeConfig):
        self.cfg = cfg
        self._client = AsyncOpenAI(
            api_key=cfg.api_key or "missing",
            base_url=cfg.base_url,
            timeout=DEFAULT_JUDGE_TIMEOUT_SEC,
        )
        self._limiter = AsyncLimiter(
            max_rate=cfg.max_rate_per_min,
            time_period=60,
        )

    async def call_judge(self, prompt: str) -> JudgeScore:
        """Call the judge with retry + limiter. Always returns JudgeScore (never raises)."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(JUDGE_RETRY_ATTEMPTS),
                wait=wait_exponential(multiplier=1, min=1, max=16),
                retry=retry_if_exception_type((RuntimeError, ConnectionError, TimeoutError)),
                reraise=True,
            ):
                with attempt:
                    async with self._limiter:
                        resp = await self._client.chat.completions.create(
                            model=self.cfg.model,
                            messages=[
                                {"role": "system", "content": "You are an evaluation judge. Respond ONLY with JSON: {\"score\": <0-10 float>, \"reasoning\": <short Chinese explanation>}."},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.0,
                        )
                    content = resp.choices[0].message.content or ""
                    score, reasoning = parse_judge_response(content)
                    return JudgeScore(
                        judge_name=self.cfg.name,
                        score=score,
                        reasoning=reasoning,
                        failed=False,
                    )
        except ValueError as e:
            logger.warning(f"[{self.cfg.name}] parse failed: {e}")
            return JudgeScore(
                judge_name=self.cfg.name,
                score=None,
                reasoning="",
                failed=True,
                error=str(e),
            )
        except Exception as e:
            logger.warning(f"[{self.cfg.name}] api failed after retries: {e}")
            return JudgeScore(
                judge_name=self.cfg.name,
                score=None,
                reasoning="",
                failed=True,
                error=str(e),
            )
        # Should be unreachable
        return JudgeScore(judge_name=self.cfg.name, score=None, reasoning="", failed=True, error="unreachable")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_judges/test_base.py -v`
Expected: 7 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/eval/judges/base.py backend/app/eval/tests/conftest.py backend/app/eval/tests/test_judges/test_base.py
git commit -m "feat(eval): JudgeClient 基类（retry + aiolimiter + 解析容错）"
```

---

## Task 5: 三个具体 JudgeClient

**Files:**
- Create: `backend/app/eval/judges/deepseek.py`
- Create: `backend/app/eval/judges/mimo.py`
- Create: `backend/app/eval/judges/qwen.py`

- [ ] **Step 1: 实现 `judges/qwen.py`**

```python
"""Qwen judge (dashscope OpenAI-compatible)."""
from app.eval.judges.base import JudgeClient
from app.eval.settings import JUDGES


def build_qwen_judge() -> JudgeClient:
    cfg = next(j for j in JUDGES if j.name == "qwen")
    return JudgeClient(cfg)
```

- [ ] **Step 2: 实现 `judges/deepseek.py`**

```python
"""DeepSeek judge."""
from app.eval.judges.base import JudgeClient
from app.eval.settings import JUDGES


def build_deepseek_judge() -> JudgeClient:
    cfg = next(j for j in JUDGES if j.name == "deepseek")
    return JudgeClient(cfg)
```

- [ ] **Step 3: 实现 `judges/mimo.py`**

```python
"""Xiaomi MiMo judge."""
from app.eval.judges.base import JudgeClient
from app.eval.settings import JUDGES


def build_mimo_judge() -> JudgeClient:
    cfg = next(j for j in JUDGES if j.name == "mimo")
    return JudgeClient(cfg)
```

- [ ] **Step 4: 写 import smoke test (验证三个 builder 不报 import 错)**

追加到 `backend/app/eval/tests/test_judges/test_base.py`：

```python
def test_all_three_judge_builders_importable():
    from app.eval.judges.deepseek import build_deepseek_judge
    from app.eval.judges.mimo import build_mimo_judge
    from app.eval.judges.qwen import build_qwen_judge

    # Note: these will read env keys; api_key may be None in test env, OK
    for build in (build_deepseek_judge, build_mimo_judge, build_qwen_judge):
        client = build()
        assert client.cfg.name in {"deepseek", "mimo", "qwen"}
```

Run: `cd backend && pytest app/eval/tests/test_judges/test_base.py::test_all_three_judge_builders_importable -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/judges/deepseek.py backend/app/eval/judges/mimo.py backend/app/eval/judges/qwen.py backend/app/eval/tests/test_judges/test_base.py
git commit -m "feat(eval): 三家族 JudgeClient builder (deepseek/mimo/qwen)"
```

---

## Task 6: EnsembleJudge

**Files:**
- Create: `backend/app/eval/judges/ensemble.py`
- Create: `backend/app/eval/tests/test_judges/test_ensemble.py`

- [ ] **Step 1: 写测试 `test_ensemble.py`**

```python
"""Test EnsembleJudge aggregation + failure handling."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.judges.ensemble import EnsembleJudge
from app.eval.types import JudgeScore


class FakeClient:
    def __init__(self, name: str, score: float | None, failed: bool = False):
        self.cfg_name = name
        self._score = score
        self._failed = failed

    async def call_judge(self, prompt: str) -> JudgeScore:
        return JudgeScore(
            judge_name=self.cfg_name,
            score=self._score,
            reasoning="r",
            failed=self._failed,
            error=("e" if self._failed else None),
        )


@pytest.mark.asyncio
async def test_ensemble_all_succeed_mean_median_std():
    e = EnsembleJudge([FakeClient("a", 6.0), FakeClient("b", 8.0), FakeClient("c", 7.0)])
    r = await e.score("any prompt")
    assert r.mean_score == 7.0
    assert r.median_score == 7.0
    assert r.std == pytest.approx(1.0, abs=0.1)
    assert r.partial is False
    assert r.low_confidence is False
    assert len(r.individual) == 3


@pytest.mark.asyncio
async def test_ensemble_one_judge_fails_partial_true():
    e = EnsembleJudge([
        FakeClient("a", 6.0),
        FakeClient("b", None, failed=True),
        FakeClient("c", 8.0),
    ])
    r = await e.score("p")
    assert r.partial is True
    assert r.mean_score == 7.0
    assert len(r.individual) == 3  # individual still has all three


@pytest.mark.asyncio
async def test_ensemble_all_fail_score_none():
    e = EnsembleJudge([
        FakeClient("a", None, failed=True),
        FakeClient("b", None, failed=True),
        FakeClient("c", None, failed=True),
    ])
    r = await e.score("p")
    assert r.mean_score is None
    assert r.error is not None
    assert r.partial is True


@pytest.mark.asyncio
async def test_ensemble_high_variance_marks_low_confidence():
    e = EnsembleJudge([FakeClient("a", 3.0), FakeClient("b", 9.0), FakeClient("c", 5.0)])
    r = await e.score("p")
    assert r.std > 2.0
    assert r.low_confidence is True


@pytest.mark.asyncio
async def test_ensemble_single_judge_std_zero():
    e = EnsembleJudge([FakeClient("a", 7.0)])
    r = await e.score("p")
    assert r.std == 0
    assert r.low_confidence is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_judges/test_ensemble.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `judges/ensemble.py`**

```python
"""Aggregate scores from multiple judge families."""
from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Protocol

from app.eval.settings import LOW_CONFIDENCE_STD_THRESHOLD
from app.eval.types import EnsembleResult, JudgeScore

logger = logging.getLogger("eval.ensemble")


class _JudgeProtocol(Protocol):
    async def call_judge(self, prompt: str) -> JudgeScore: ...


class EnsembleJudge:
    """Run N judges in parallel, aggregate to a single EnsembleResult."""

    def __init__(self, clients: list[_JudgeProtocol]):
        if not clients:
            raise ValueError("EnsembleJudge needs at least one client")
        self.clients = clients

    async def score(self, prompt: str) -> EnsembleResult:
        raw = await asyncio.gather(
            *[c.call_judge(prompt) for c in self.clients],
            return_exceptions=True,
        )

        individual: list[JudgeScore] = []
        for r in raw:
            if isinstance(r, JudgeScore):
                individual.append(r)
            else:
                # Bare exception slipped through
                individual.append(JudgeScore(
                    judge_name="unknown",
                    score=None,
                    reasoning="",
                    failed=True,
                    error=str(r),
                ))

        valid = [s for s in individual if not s.failed and s.score is not None]

        if not valid:
            return EnsembleResult(
                mean_score=None,
                median_score=None,
                std=0,
                individual=individual,
                low_confidence=False,
                partial=True,
                error="all judges failed",
            )

        scores = [s.score for s in valid]
        mean = statistics.mean(scores)
        median = statistics.median(scores)
        std = statistics.stdev(scores) if len(scores) > 1 else 0
        return EnsembleResult(
            mean_score=mean,
            median_score=median,
            std=std,
            individual=individual,
            low_confidence=std > LOW_CONFIDENCE_STD_THRESHOLD,
            partial=len(valid) < len(self.clients),
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_judges/test_ensemble.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/judges/ensemble.py backend/app/eval/tests/test_judges/test_ensemble.py
git commit -m "feat(eval): EnsembleJudge 聚合 + 容错降级"
```

---

## Task 7: Evaluator 基类 + registry

**Files:**
- Create: `backend/app/eval/evaluators/base.py`
- Modify: `backend/app/eval/evaluators/__init__.py`

- [ ] **Step 1: 实现 `evaluators/base.py`**

```python
"""Evaluator abstract base."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.eval.types import EvalContext, EvalResult

if TYPE_CHECKING:
    from app.eval.judges.ensemble import EnsembleJudge


class Evaluator(ABC):
    """Abstract evaluator. Subclasses set class-level metadata + implement evaluate()."""

    name: str = ""
    scale: tuple[float, float] = (0, 10)
    requires_judge: bool = False
    requires_network: bool = False

    @abstractmethod
    async def evaluate(
        self,
        ctx: EvalContext,
        judge: "EnsembleJudge | None",
    ) -> EvalResult:
        """Evaluate one case, return EvalResult. Must never raise — wrap errors in result.error."""
        ...
```

- [ ] **Step 2: 修改 `evaluators/__init__.py`（暂时为空 registry，后续 task 填充）**

```python
"""Eval registry. Populated by subsequent tasks."""
from __future__ import annotations

from app.eval.evaluators.base import Evaluator


def build_all_evaluators() -> list[Evaluator]:
    """Build the full evaluator list. Lazy imports avoid circular deps."""
    from app.eval.evaluators.cost import CostEvaluator
    from app.eval.evaluators.latency import LatencyEvaluator
    from app.eval.evaluators.critic_loop import CriticLoopEvaluator
    from app.eval.evaluators.citation import CitationEvaluator
    from app.eval.evaluators.relevance import RelevanceEvaluator
    from app.eval.evaluators.coherence import CoherenceEvaluator
    from app.eval.evaluators.completeness import CompletenessEvaluator

    return [
        RelevanceEvaluator(),
        CoherenceEvaluator(),
        CitationEvaluator(),
        CompletenessEvaluator(),
        CriticLoopEvaluator(),
        CostEvaluator(),
        LatencyEvaluator(),
    ]


__all__ = ["Evaluator", "build_all_evaluators"]
```

Note: `build_all_evaluators()` 当前会 ImportError，正常 — 后续 task 8-14 会逐个实现。

- [ ] **Step 3: 提交**

```bash
git add backend/app/eval/evaluators/base.py backend/app/eval/evaluators/__init__.py
git commit -m "feat(eval): Evaluator 抽象基类 + registry 骨架"
```

---

## Task 8: CostEvaluator

**Files:**
- Create: `backend/app/eval/evaluators/cost.py`
- Create: `backend/app/eval/tests/test_evaluators/test_cost.py`

- [ ] **Step 1: 写测试 `test_cost.py`**

```python
"""Test CostEvaluator."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.cost import CostEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(logs: list[dict]) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"logs": logs},
        started_at=datetime(2026, 5, 26, 14, 0, 0),
        finished_at=datetime(2026, 5, 26, 14, 5, 0),
    )


@pytest.mark.asyncio
async def test_cost_zero_when_no_logs():
    ctx = make_ctx([])
    res = await CostEvaluator().evaluate(ctx, judge=None)
    assert res.score == 0.0
    assert res.metadata["total_tokens"] == 0


@pytest.mark.asyncio
async def test_cost_sums_tokens_from_logs():
    ctx = make_ctx([
        {"tokens_used": 1000, "model": "qwen-max"},
        {"tokens_used": 2000, "model": "qwen-plus"},
    ])
    res = await CostEvaluator().evaluate(ctx, judge=None)
    assert res.metadata["total_tokens"] == 3000
    assert res.score > 0  # RMB


@pytest.mark.asyncio
async def test_cost_unknown_model_uses_fallback_pricing():
    ctx = make_ctx([{"tokens_used": 1000, "model": "unknown-model-xyz"}])
    res = await CostEvaluator().evaluate(ctx, judge=None)
    assert res.score >= 0
    assert "unknown-model-xyz" in res.metadata.get("unknown_models", [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_cost.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `evaluators/cost.py`**

```python
"""Cost evaluator: sum tokens from logs, convert to RMB."""
from __future__ import annotations

from app.eval.evaluators.base import Evaluator
from app.eval.settings import PRICING_RMB_PER_M_TOKENS
from app.eval.types import EvalContext, EvalResult

# Fallback pricing when model not in PRICING table
_FALLBACK_INPUT = 2.0
_FALLBACK_OUTPUT = 6.0


class CostEvaluator(Evaluator):
    name = "cost"
    scale = (0, float("inf"))
    requires_judge = False
    requires_network = False

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        logs = ctx.state.get("logs") or []
        total_tokens = 0
        rmb = 0.0
        unknown_models: list[str] = []

        for log in logs:
            t = int(log.get("tokens_used") or 0)
            total_tokens += t
            model = log.get("model") or "unknown"
            pricing = PRICING_RMB_PER_M_TOKENS.get(model)
            if pricing is None:
                if model not in unknown_models:
                    unknown_models.append(model)
                in_price, out_price = _FALLBACK_INPUT, _FALLBACK_OUTPUT
            else:
                in_price, out_price = pricing
            # No input/output split in logs → assume 50/50
            half = t / 2
            rmb += (half * in_price + half * out_price) / 1_000_000

        return EvalResult(
            evaluator_name=self.name,
            score=round(rmb, 4),
            metadata={
                "total_tokens": total_tokens,
                "rmb": round(rmb, 4),
                "unknown_models": unknown_models,
            },
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_cost.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/evaluators/cost.py backend/app/eval/tests/test_evaluators/test_cost.py
git commit -m "feat(eval): CostEvaluator (token 汇总 + RMB 估算)"
```

---

## Task 9: LatencyEvaluator

**Files:**
- Create: `backend/app/eval/evaluators/latency.py`
- Create: `backend/app/eval/tests/test_evaluators/test_latency.py`

- [ ] **Step 1: 写测试 `test_latency.py`**

```python
"""Test LatencyEvaluator."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.latency import LatencyEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(logs: list[dict], duration_min: int = 5) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"logs": logs},
        started_at=datetime(2026, 5, 26, 14, 0, 0),
        finished_at=datetime(2026, 5, 26, 14, duration_min, 0),
    )


@pytest.mark.asyncio
async def test_latency_total_duration():
    res = await LatencyEvaluator().evaluate(make_ctx([], duration_min=3), judge=None)
    assert res.score == 180.0


@pytest.mark.asyncio
async def test_latency_per_agent_breakdown():
    logs = [
        {"agent": "architect", "duration_ms": 5000},
        {"agent": "scout", "duration_ms": 20000},
        {"agent": "scout", "duration_ms": 10000},
        {"agent": "writer", "duration_ms": 30000},
    ]
    res = await LatencyEvaluator().evaluate(make_ctx(logs), judge=None)
    per_agent = res.metadata["per_agent_sec"]
    assert per_agent["architect"] == 5.0
    assert per_agent["scout"] == 30.0
    assert per_agent["writer"] == 30.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_latency.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `evaluators/latency.py`**

```python
"""Latency evaluator: total duration + per-agent breakdown."""
from __future__ import annotations

from collections import defaultdict

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult


class LatencyEvaluator(Evaluator):
    name = "latency"
    scale = (0, float("inf"))
    requires_judge = False
    requires_network = False

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        total = ctx.duration_sec
        per_agent: dict[str, float] = defaultdict(float)
        for log in (ctx.state.get("logs") or []):
            agent = log.get("agent") or "unknown"
            per_agent[agent] += (log.get("duration_ms") or 0) / 1000.0

        return EvalResult(
            evaluator_name=self.name,
            score=round(total, 1),
            metadata={
                "total_sec": round(total, 1),
                "per_agent_sec": {k: round(v, 1) for k, v in per_agent.items()},
            },
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_latency.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/evaluators/latency.py backend/app/eval/tests/test_evaluators/test_latency.py
git commit -m "feat(eval): LatencyEvaluator (总耗时 + 按 agent 拆分)"
```

---

## Task 10: CriticLoopEvaluator

**Files:**
- Create: `backend/app/eval/evaluators/critic_loop.py`
- Create: `backend/app/eval/tests/test_evaluators/test_critic_loop.py`

- [ ] **Step 1: 写测试 `test_critic_loop.py`**

```python
"""Test CriticLoopEvaluator."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.critic_loop import CriticLoopEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(feedback: list[dict], iteration: int = 1, quality: float = 7.5) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={
            "critic_feedback": feedback,
            "iteration": iteration,
            "quality_score": quality,
        },
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )


@pytest.mark.asyncio
async def test_critic_no_feedback_score_none():
    res = await CriticLoopEvaluator().evaluate(make_ctx([]), judge=None)
    assert res.score is None
    assert res.metadata["total_feedback"] == 0


@pytest.mark.asyncio
async def test_critic_resolution_rate_half():
    fb = [
        {"id": "c1", "severity": "minor", "resolved": True},
        {"id": "c2", "severity": "major", "resolved": False},
    ]
    res = await CriticLoopEvaluator().evaluate(make_ctx(fb), judge=None)
    assert res.metadata["resolution_rate"] == 0.5
    assert res.score == 5.0  # 0.5 × 10


@pytest.mark.asyncio
async def test_critic_all_resolved_full_score():
    fb = [
        {"id": "c1", "severity": "minor", "resolved": True},
        {"id": "c2", "severity": "major", "resolved": True},
    ]
    res = await CriticLoopEvaluator().evaluate(make_ctx(fb, iteration=2), judge=None)
    assert res.metadata["resolution_rate"] == 1.0
    assert res.score == 10.0
    assert res.metadata["iterations"] == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_critic_loop.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `evaluators/critic_loop.py`**

```python
"""CriticLoopEffectiveness evaluator: resolution rate × 10."""
from __future__ import annotations

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult


class CriticLoopEvaluator(Evaluator):
    name = "critic_loop"
    scale = (0, 10)
    requires_judge = False
    requires_network = False

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        feedback = ctx.state.get("critic_feedback") or []
        total = len(feedback)
        iterations = int(ctx.state.get("iteration") or 0)
        quality = float(ctx.state.get("quality_score") or 0.0)

        if total == 0:
            return EvalResult(
                evaluator_name=self.name,
                score=None,
                metadata={
                    "total_feedback": 0,
                    "resolution_rate": None,
                    "iterations": iterations,
                    "final_quality_score": quality,
                    "note": "no critic feedback recorded",
                },
            )

        resolved = sum(1 for f in feedback if f.get("resolved") is True)
        rate = resolved / total
        return EvalResult(
            evaluator_name=self.name,
            score=round(rate * 10, 2),
            metadata={
                "total_feedback": total,
                "resolved": resolved,
                "resolution_rate": round(rate, 3),
                "iterations": iterations,
                "final_quality_score": quality,
                "severity_breakdown": {
                    "critical": sum(1 for f in feedback if f.get("severity") == "critical"),
                    "major": sum(1 for f in feedback if f.get("severity") == "major"),
                    "minor": sum(1 for f in feedback if f.get("severity") == "minor"),
                },
            },
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_critic_loop.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/evaluators/critic_loop.py backend/app/eval/tests/test_evaluators/test_critic_loop.py
git commit -m "feat(eval): CriticLoopEvaluator (agentic metric, resolution rate × 10)"
```

---

## Task 11: CitationEvaluator (rule-based + aiohttp)

**Files:**
- Create: `backend/app/eval/evaluators/citation.py`
- Create: `backend/app/eval/tests/test_evaluators/test_citation.py`

- [ ] **Step 1: 写测试 `test_citation.py`**

```python
"""Test CitationEvaluator. URL check is mocked via aresponses."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.evaluators.citation import CitationEvaluator
from app.eval.types import EvalCase, EvalContext


def make_ctx(report: str, refs: list[dict]) -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={
            "final_report": report,
            "references": refs,
            "outline": [{"id": "s1", "title": "A"}, {"id": "s2", "title": "B"}],
        },
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )


@pytest.mark.asyncio
async def test_citation_full_match_high_score(aresponses):
    aresponses.add("example.com", "/a", "HEAD", aresponses.Response(status=200))
    aresponses.add("example.com", "/b", "HEAD", aresponses.Response(status=200))

    report = "段落 [1] 内容\n段落 [2] 内容"
    refs = [
        {"id": "1", "url": "https://example.com/a", "title": "A"},
        {"id": "2", "url": "https://example.com/b", "title": "B"},
    ]
    ev = CitationEvaluator()
    res = await ev.evaluate(make_ctx(report, refs), judge=None)
    assert res.score >= 8.0
    assert res.metadata["broken_urls"] == 0
    assert res.metadata["unknown_ref_ids"] == []


@pytest.mark.asyncio
async def test_citation_broken_url_penalty(aresponses):
    aresponses.add("example.com", "/dead", "HEAD", aresponses.Response(status=404))

    report = "段落 [1] 内容"
    refs = [{"id": "1", "url": "https://example.com/dead", "title": "X"}]
    res = await CitationEvaluator().evaluate(make_ctx(report, refs), judge=None)
    assert res.metadata["broken_urls"] == 1
    assert res.score < 8.0


@pytest.mark.asyncio
async def test_citation_unknown_ref_id_penalty(aresponses):
    aresponses.add("example.com", "/a", "HEAD", aresponses.Response(status=200))

    # report cites [2] but references only has [1]
    report = "段落 [2] 内容"
    refs = [{"id": "1", "url": "https://example.com/a", "title": "A"}]
    res = await CitationEvaluator().evaluate(make_ctx(report, refs), judge=None)
    assert "2" in res.metadata["unknown_ref_ids"]
    assert res.score < 8.0


@pytest.mark.asyncio
async def test_citation_no_citations_low_score():
    report = "段落内容，无任何引用编号"
    refs = []
    res = await CitationEvaluator().evaluate(make_ctx(report, refs), judge=None)
    assert res.score <= 3.0
    assert res.metadata["citation_count"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_citation.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `evaluators/citation.py`**

```python
"""Citation evaluator: rule-based scoring of (1) ref id integrity (2) URL reachability (3) coverage."""
from __future__ import annotations

import asyncio
import logging
import re

import aiohttp

from app.eval.evaluators.base import Evaluator
from app.eval.settings import URL_CHECK_TIMEOUT_SEC
from app.eval.types import EvalContext, EvalResult

logger = logging.getLogger("eval.citation")

# [1], [2], [1,3], [1-3]
_CITATION_PATTERN = re.compile(r"\[(\d+(?:[,\-]\d+)*)\]")


def _extract_cited_ids(report: str) -> list[str]:
    cited: list[str] = []
    for m in _CITATION_PATTERN.finditer(report):
        token = m.group(1)
        # support [1,2] and [1-3]
        if "-" in token:
            a, b = token.split("-", 1)
            try:
                for i in range(int(a), int(b) + 1):
                    cited.append(str(i))
            except ValueError:
                pass
        else:
            cited.extend([p.strip() for p in token.split(",")])
    return cited


async def _check_url(session: aiohttp.ClientSession, url: str) -> int | None:
    try:
        async with session.head(
            url,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=URL_CHECK_TIMEOUT_SEC),
        ) as r:
            return r.status
    except Exception as e:
        logger.debug(f"url check failed for {url}: {e}")
        return None


class CitationEvaluator(Evaluator):
    name = "citation"
    scale = (0, 10)
    requires_judge = False
    requires_network = True

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        report = ctx.state.get("final_report") or ""
        refs: list[dict] = ctx.state.get("references") or []
        outline: list[dict] = ctx.state.get("outline") or []

        ref_ids = {str(r.get("id")) for r in refs if r.get("id") is not None}
        cited = _extract_cited_ids(report)
        citation_count = len(cited)

        unknown_ref_ids = sorted(set(cited) - ref_ids)

        # URL reachability
        urls = [r.get("url") for r in refs if r.get("url")]
        broken = 0
        if urls:
            async with aiohttp.ClientSession() as session:
                statuses = await asyncio.gather(
                    *[_check_url(session, u) for u in urls],
                    return_exceptions=True,
                )
            broken = sum(1 for s in statuses if not (isinstance(s, int) and 200 <= s < 400))

        # Coverage: citations per outline section (rough proxy)
        section_count = max(len(outline), 1)
        coverage_ratio = min(citation_count / section_count, 2.0) / 2.0  # cap at 100%

        # Compose score (0-10)
        if citation_count == 0:
            score = 1.0  # report with zero citations is bad
        else:
            url_ok_ratio = (len(urls) - broken) / max(len(urls), 1)
            unknown_ratio = len(unknown_ref_ids) / max(citation_count, 1)
            score = (
                4.0 * url_ok_ratio
                + 3.0 * (1 - unknown_ratio)
                + 3.0 * coverage_ratio
            )
            score = max(0.0, min(10.0, score))

        return EvalResult(
            evaluator_name=self.name,
            score=round(score, 2),
            metadata={
                "citation_count": citation_count,
                "ref_count": len(refs),
                "broken_urls": broken,
                "unknown_ref_ids": unknown_ref_ids,
                "coverage_ratio": round(coverage_ratio, 3),
            },
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_citation.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/evaluators/citation.py backend/app/eval/tests/test_evaluators/test_citation.py
git commit -m "feat(eval): CitationEvaluator (rule-based, URL+ref+coverage 加权)"
```

---

## Task 12: RelevanceEvaluator (LLM-judge)

**Files:**
- Create: `backend/app/eval/evaluators/prompts/relevance.md`
- Create: `backend/app/eval/evaluators/relevance.py`
- Create: `backend/app/eval/tests/test_evaluators/test_relevance.py`

- [ ] **Step 1: 写 prompt 模板 `evaluators/prompts/relevance.md`**

```markdown
你是一名评测员。请评估下面的研究报告"是否回答了用户的原始查询"。

## 用户查询
{query}

## 研究报告（前 3000 字）
{report_excerpt}

## 评分标准 (0-10)
- 10：完全针对查询，覆盖核心问题，无离题
- 7-9：基本对齐，少量偏离或遗漏
- 4-6：部分对齐，明显偏题或遗漏关键面
- 0-3：严重偏题或答非所问

只输出 JSON：{{"score": <float>, "reasoning": "<中文，1-2 句>"}}
```

- [ ] **Step 2: 写测试 `test_relevance.py`**

```python
"""Test RelevanceEvaluator. Judge is mocked."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.evaluators.relevance import RelevanceEvaluator
from app.eval.types import EnsembleResult, EvalCase, EvalContext, JudgeScore


def make_ctx() -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q001", query="新能源汽车2024年市场", category="汽车", difficulty="easy"),
        state={"final_report": "## 市场规模\n2024 年销量增长 30%..."},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )


@pytest.mark.asyncio
async def test_relevance_happy_path():
    mock_judge = AsyncMock()
    mock_judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=8.0,
        median_score=8.0,
        std=0.5,
        individual=[JudgeScore("a", 8, "ok"), JudgeScore("b", 8, "ok"), JudgeScore("c", 8, "ok")],
        low_confidence=False,
        partial=False,
    ))
    res = await RelevanceEvaluator().evaluate(make_ctx(), mock_judge)
    assert res.score == 8.0
    assert res.low_confidence is False
    mock_judge.score.assert_awaited_once()


@pytest.mark.asyncio
async def test_relevance_no_report_returns_error():
    mock_judge = AsyncMock()
    ctx = EvalContext(
        case=EvalCase(id="q001", query="x", category="c", difficulty="easy"),
        state={"final_report": ""},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await RelevanceEvaluator().evaluate(ctx, mock_judge)
    assert res.score is None
    assert res.error is not None


@pytest.mark.asyncio
async def test_relevance_propagates_low_confidence():
    mock_judge = AsyncMock()
    mock_judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=6.0,
        median_score=6.0,
        std=3.0,
        individual=[JudgeScore("a", 3, ""), JudgeScore("b", 9, ""), JudgeScore("c", 6, "")],
        low_confidence=True,
        partial=False,
    ))
    res = await RelevanceEvaluator().evaluate(make_ctx(), mock_judge)
    assert res.low_confidence is True
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_relevance.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 实现 `evaluators/relevance.py`**

```python
"""Relevance evaluator: LLM-judge whether report answers the query."""
from __future__ import annotations

from pathlib import Path

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult

_PROMPT_PATH = Path(__file__).parent / "prompts" / "relevance.md"
_REPORT_EXCERPT_CHARS = 3000


class RelevanceEvaluator(Evaluator):
    name = "relevance"
    scale = (0, 10)
    requires_judge = True
    requires_network = False

    _template: str | None = None

    @classmethod
    def _load_template(cls) -> str:
        if cls._template is None:
            cls._template = _PROMPT_PATH.read_text(encoding="utf-8")
        return cls._template

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        if judge is None:
            return EvalResult(
                evaluator_name=self.name,
                score=None,
                error="RelevanceEvaluator requires a judge",
            )

        report = ctx.state.get("final_report") or ""
        if not report.strip():
            return EvalResult(
                evaluator_name=self.name,
                score=None,
                error="empty final_report",
            )

        prompt = self._load_template().format(
            query=ctx.case.query,
            report_excerpt=report[:_REPORT_EXCERPT_CHARS],
        )

        result = await judge.score(prompt)
        return EvalResult(
            evaluator_name=self.name,
            score=result.mean_score,
            raw_judge_outputs=[
                {"judge": s.judge_name, "score": s.score, "reasoning": s.reasoning, "failed": s.failed}
                for s in result.individual
            ],
            metadata={
                "median": result.median_score,
                "std": result.std,
                "partial": result.partial,
            },
            low_confidence=result.low_confidence,
            error=result.error,
        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_relevance.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/eval/evaluators/prompts/relevance.md backend/app/eval/evaluators/relevance.py backend/app/eval/tests/test_evaluators/test_relevance.py
git commit -m "feat(eval): RelevanceEvaluator (LLM-judge ensemble)"
```

---

## Task 13: CoherenceEvaluator

**Files:**
- Create: `backend/app/eval/evaluators/prompts/coherence.md`
- Create: `backend/app/eval/evaluators/coherence.py`
- Create: `backend/app/eval/tests/test_evaluators/test_coherence.py`

- [ ] **Step 1: 写 `prompts/coherence.md`**

```markdown
你是一名评测员。请评估下面的研究报告"行文连贯性、段落衔接、术语一致性"。

## 报告（前 3000 字）
{report_excerpt}

## 评分标准 (0-10)
- 10：段落衔接自然，术语统一，无前后矛盾
- 7-9：基本流畅，少量衔接生硬
- 4-6：跳跃感明显，部分段落孤立，术语不一致
- 0-3：完全无组织，前后矛盾或拼接痕迹严重

只输出 JSON：{{"score": <float>, "reasoning": "<中文，1-2 句>"}}
```

- [ ] **Step 2: 写测试 `test_coherence.py`**

```python
"""Test CoherenceEvaluator (mocked judge)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.evaluators.coherence import CoherenceEvaluator
from app.eval.types import EnsembleResult, EvalCase, EvalContext, JudgeScore


@pytest.mark.asyncio
async def test_coherence_happy_path():
    judge = AsyncMock()
    judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=7.5, median_score=7.5, std=0.3,
        individual=[JudgeScore("a", 7.5, "ok"), JudgeScore("b", 7.5, "ok"), JudgeScore("c", 7.5, "ok")],
        low_confidence=False, partial=False,
    ))
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={"final_report": "## 段一\n内容。\n\n## 段二\n内容。"},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CoherenceEvaluator().evaluate(ctx, judge)
    assert res.score == 7.5


@pytest.mark.asyncio
async def test_coherence_empty_report_error():
    judge = AsyncMock()
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={"final_report": ""},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CoherenceEvaluator().evaluate(ctx, judge)
    assert res.score is None
    assert res.error is not None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_coherence.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 `evaluators/coherence.py`**

```python
"""Coherence evaluator: LLM-judge report flow/consistency."""
from __future__ import annotations

from pathlib import Path

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult

_PROMPT_PATH = Path(__file__).parent / "prompts" / "coherence.md"
_REPORT_EXCERPT_CHARS = 3000


class CoherenceEvaluator(Evaluator):
    name = "coherence"
    scale = (0, 10)
    requires_judge = True
    requires_network = False

    _template: str | None = None

    @classmethod
    def _load_template(cls) -> str:
        if cls._template is None:
            cls._template = _PROMPT_PATH.read_text(encoding="utf-8")
        return cls._template

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        if judge is None:
            return EvalResult(evaluator_name=self.name, score=None, error="needs judge")

        report = ctx.state.get("final_report") or ""
        if not report.strip():
            return EvalResult(evaluator_name=self.name, score=None, error="empty final_report")

        prompt = self._load_template().format(report_excerpt=report[:_REPORT_EXCERPT_CHARS])
        result = await judge.score(prompt)

        return EvalResult(
            evaluator_name=self.name,
            score=result.mean_score,
            raw_judge_outputs=[
                {"judge": s.judge_name, "score": s.score, "reasoning": s.reasoning, "failed": s.failed}
                for s in result.individual
            ],
            metadata={"median": result.median_score, "std": result.std, "partial": result.partial},
            low_confidence=result.low_confidence,
            error=result.error,
        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_coherence.py -v`
Expected: 2 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/eval/evaluators/prompts/coherence.md backend/app/eval/evaluators/coherence.py backend/app/eval/tests/test_evaluators/test_coherence.py
git commit -m "feat(eval): CoherenceEvaluator (LLM-judge ensemble)"
```

---

## Task 14: CompletenessEvaluator

**Files:**
- Create: `backend/app/eval/evaluators/prompts/completeness.md`
- Create: `backend/app/eval/evaluators/completeness.py`
- Create: `backend/app/eval/tests/test_evaluators/test_completeness.py`

- [ ] **Step 1: 写 `prompts/completeness.md`**

```markdown
你是一名评测员。请评估"研究报告是否实质性论述了大纲里的每个章节"。

## 大纲
{outline_str}

## 报告（前 4000 字）
{report_excerpt}

## 评分标准 (0-10)
- 10：每个大纲章节在报告里有实质论述（>200 字、有数据/论点）
- 7-9：绝大多数章节充实，少数偏简单
- 4-6：超过一半章节是占位或一句话带过
- 0-3：报告与大纲几乎对不上

只输出 JSON：{{"score": <float>, "reasoning": "<中文>"}}
```

- [ ] **Step 2: 写测试**

```python
"""Test CompletenessEvaluator."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.evaluators.completeness import CompletenessEvaluator
from app.eval.types import EnsembleResult, EvalCase, EvalContext, JudgeScore


@pytest.mark.asyncio
async def test_completeness_happy_path():
    judge = AsyncMock()
    judge.score = AsyncMock(return_value=EnsembleResult(
        mean_score=8.0, median_score=8.0, std=0.5,
        individual=[JudgeScore("a", 8, ""), JudgeScore("b", 8, ""), JudgeScore("c", 8, "")],
        low_confidence=False, partial=False,
    ))
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={
            "outline": [{"id": "s1", "title": "A"}, {"id": "s2", "title": "B"}],
            "final_report": "## A\n内容...\n\n## B\n内容...",
        },
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CompletenessEvaluator().evaluate(ctx, judge)
    assert res.score == 8.0


@pytest.mark.asyncio
async def test_completeness_no_outline_returns_error():
    judge = AsyncMock()
    ctx = EvalContext(
        case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
        state={"outline": [], "final_report": "..."},
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    res = await CompletenessEvaluator().evaluate(ctx, judge)
    assert res.score is None
    assert res.error is not None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_completeness.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 `evaluators/completeness.py`**

```python
"""Completeness evaluator: outline → report coverage via LLM-judge."""
from __future__ import annotations

from pathlib import Path

from app.eval.evaluators.base import Evaluator
from app.eval.types import EvalContext, EvalResult

_PROMPT_PATH = Path(__file__).parent / "prompts" / "completeness.md"
_REPORT_EXCERPT_CHARS = 4000


class CompletenessEvaluator(Evaluator):
    name = "completeness"
    scale = (0, 10)
    requires_judge = True
    requires_network = False

    _template: str | None = None

    @classmethod
    def _load_template(cls) -> str:
        if cls._template is None:
            cls._template = _PROMPT_PATH.read_text(encoding="utf-8")
        return cls._template

    async def evaluate(self, ctx: EvalContext, judge=None) -> EvalResult:
        if judge is None:
            return EvalResult(evaluator_name=self.name, score=None, error="needs judge")

        outline = ctx.state.get("outline") or []
        report = ctx.state.get("final_report") or ""
        if not outline:
            return EvalResult(evaluator_name=self.name, score=None, error="empty outline")
        if not report.strip():
            return EvalResult(evaluator_name=self.name, score=None, error="empty report")

        outline_str = "\n".join(
            f"- {s.get('id', '?')}: {s.get('title', '')} — {s.get('description', '')[:100]}"
            for s in outline
        )

        prompt = self._load_template().format(
            outline_str=outline_str,
            report_excerpt=report[:_REPORT_EXCERPT_CHARS],
        )
        result = await judge.score(prompt)

        return EvalResult(
            evaluator_name=self.name,
            score=result.mean_score,
            raw_judge_outputs=[
                {"judge": s.judge_name, "score": s.score, "reasoning": s.reasoning, "failed": s.failed}
                for s in result.individual
            ],
            metadata={
                "outline_section_count": len(outline),
                "median": result.median_score,
                "std": result.std,
                "partial": result.partial,
            },
            low_confidence=result.low_confidence,
            error=result.error,
        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_evaluators/test_completeness.py -v`
Expected: 2 passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/eval/evaluators/prompts/completeness.md backend/app/eval/evaluators/completeness.py backend/app/eval/tests/test_evaluators/test_completeness.py
git commit -m "feat(eval): CompletenessEvaluator (outline coverage via LLM-judge)"
```

---

## Task 15: Storage (SQLite)

**Files:**
- Create: `backend/app/eval/storage.py`
- Create: `backend/app/eval/tests/test_storage.py`

- [ ] **Step 1: 写测试 `test_storage.py`**

```python
"""Test SQLite storage."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.eval.storage import EvalStorage
from app.eval.types import CaseResult, EvalCase, EvalResult


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_eval.db")


def test_storage_creates_schema(db_path: str):
    s = EvalStorage(db_path)
    s.init_schema()
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"eval_runs", "case_results", "evaluator_scores"}.issubset(tables)
    conn.close()


def test_storage_save_run_and_case(db_path: str):
    s = EvalStorage(db_path)
    s.init_schema()
    s.save_run_start(
        run_id="run-001",
        suite="full",
        started_at=datetime(2026, 5, 26, 14, 0),
        git_commit="abc123",
        config={"concurrency": 5},
    )

    cr = CaseResult(
        case=EvalCase(id="q001", query="新能源", category="汽车", difficulty="easy"),
        results=[
            EvalResult(evaluator_name="relevance", score=8.0,
                       raw_judge_outputs=[{"judge": "a", "score": 8}]),
            EvalResult(evaluator_name="cost", score=0.34,
                       metadata={"total_tokens": 12000}),
        ],
        ok=True,
        state={"final_report": "...", "quality_score": 7.5},
        started_at=datetime(2026, 5, 26, 14, 1),
        finished_at=datetime(2026, 5, 26, 14, 4),
    )
    s.save_case(run_id="run-001", case_result=cr)

    s.save_run_end(run_id="run-001", finished_at=datetime(2026, 5, 26, 14, 5))

    # Read back
    conn = sqlite3.connect(db_path)
    rows = list(conn.execute("SELECT case_id, query FROM case_results WHERE run_id='run-001'"))
    assert rows == [("q001", "新能源")]
    score_rows = list(conn.execute(
        "SELECT evaluator_name, score FROM evaluator_scores WHERE run_id='run-001' ORDER BY evaluator_name"
    ))
    assert score_rows == [("cost", 0.34), ("relevance", 8.0)]
    conn.close()


def test_storage_save_idempotent(db_path: str):
    s = EvalStorage(db_path)
    s.init_schema()
    s.save_run_start("run-2", "full", datetime(2026, 5, 26), "abc", {})
    cr = CaseResult(
        case=EvalCase(id="q002", query="x", category="c", difficulty="easy"),
        results=[EvalResult(evaluator_name="cost", score=1.0)],
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
    )
    s.save_case("run-2", cr)
    s.save_case("run-2", cr)  # second insert should overwrite, not error
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM case_results WHERE run_id='run-2'").fetchone()[0]
    assert n == 1
    conn.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `storage.py`**

```python
"""SQLite storage for eval runs."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.eval.types import CaseResult

logger = logging.getLogger("eval.storage")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    suite TEXT,
    started_at TEXT,
    finished_at TEXT,
    git_commit TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS case_results (
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

CREATE TABLE IF NOT EXISTS evaluator_scores (
    run_id TEXT,
    case_id TEXT,
    evaluator_name TEXT,
    score REAL,
    raw_judge_outputs_json TEXT,
    std REAL,
    low_confidence INTEGER,
    metadata_json TEXT,
    PRIMARY KEY (run_id, case_id, evaluator_name)
);
"""


class EvalStorage:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def save_run_start(
        self,
        run_id: str,
        suite: str,
        started_at: datetime,
        git_commit: str,
        config: dict[str, Any],
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO eval_runs (run_id, suite, started_at, git_commit, config_json) VALUES (?, ?, ?, ?, ?)",
                (run_id, suite, started_at.isoformat(), git_commit, json.dumps(config, ensure_ascii=False)),
            )

    def save_run_end(self, run_id: str, finished_at: datetime) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE eval_runs SET finished_at=? WHERE run_id=?",
                (finished_at.isoformat(), run_id),
            )

    def save_case(self, run_id: str, case_result: CaseResult) -> None:
        c_id = case_result.case.id
        state = case_result.state or {}
        # Find cost/latency from results
        cost = next((r.score for r in case_result.results if r.evaluator_name == "cost"), None)
        latency = next((r.score for r in case_result.results if r.evaluator_name == "latency"), None)
        total_tokens = next(
            (r.metadata.get("total_tokens") for r in case_result.results if r.evaluator_name == "cost"),
            None,
        )

        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO case_results "
                "(run_id, case_id, query, final_report, quality_score, duration_sec, total_tokens, cost_rmb, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, c_id, case_result.case.query,
                    state.get("final_report"),
                    state.get("quality_score"),
                    latency,
                    total_tokens,
                    cost,
                    case_result.error,
                ),
            )
            # Wipe + reinsert evaluator rows (idempotent)
            c.execute(
                "DELETE FROM evaluator_scores WHERE run_id=? AND case_id=?",
                (run_id, c_id),
            )
            for r in case_result.results:
                c.execute(
                    "INSERT INTO evaluator_scores "
                    "(run_id, case_id, evaluator_name, score, raw_judge_outputs_json, std, low_confidence, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id, c_id, r.evaluator_name, r.score,
                        json.dumps(r.raw_judge_outputs, ensure_ascii=False),
                        r.metadata.get("std"),
                        1 if r.low_confidence else 0,
                        json.dumps(r.metadata, ensure_ascii=False),
                    ),
                )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_storage.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/storage.py backend/app/eval/tests/test_storage.py
git commit -m "feat(eval): SQLite storage (eval_runs / case_results / evaluator_scores 三表)"
```

---

## Task 16: Reporter (markdown + csv)

**Files:**
- Create: `backend/app/eval/reporter.py`
- Create: `backend/app/eval/tests/test_reporter.py`

- [ ] **Step 1: 写测试 `test_reporter.py`**

```python
"""Test Reporter markdown + csv generation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.eval.reporter import Reporter
from app.eval.types import CaseResult, EvalCase, EvalResult


def make_case_result(case_id: str, scores: dict[str, float], ok: bool = True, error=None) -> CaseResult:
    return CaseResult(
        case=EvalCase(id=case_id, query=f"q-{case_id}", category="汽车", difficulty="easy"),
        results=[
            EvalResult(evaluator_name=name, score=s) for name, s in scores.items()
        ],
        ok=ok,
        error=error,
        started_at=datetime(2026, 5, 26, 14, 0),
        finished_at=datetime(2026, 5, 26, 14, 5),
    )


def test_reporter_writes_markdown(tmp_path: Path):
    out_dir = tmp_path / "results"
    cases = [
        make_case_result("q001", {"relevance": 8.0, "cost": 0.34}),
        make_case_result("q002", {"relevance": 7.5, "cost": 0.41}),
    ]
    r = Reporter(out_dir=str(out_dir))
    paths = r.write(
        run_id="run-001",
        suite="full",
        git_commit="abc1234",
        started_at=datetime(2026, 5, 26, 14, 0),
        finished_at=datetime(2026, 5, 26, 14, 30),
        case_results=cases,
        langsmith_url=None,
    )
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "run-001" in md
    assert "abc1234" in md
    assert "## Overall Scores" in md
    assert "relevance" in md
    csv_path = Path(paths["csv"])
    assert csv_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "q001" in csv_text and "q002" in csv_text


def test_reporter_marks_failed_cases(tmp_path: Path):
    cases = [
        make_case_result("q001", {"relevance": 7.0}),
        make_case_result("q002", {}, ok=False, error="TimeoutError"),
    ]
    r = Reporter(out_dir=str(tmp_path))
    paths = r.write(
        run_id="run-2",
        suite="mini",
        git_commit="abc",
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
        case_results=cases,
        langsmith_url=None,
    )
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "## Failed Cases" in md
    assert "q002" in md
    assert "TimeoutError" in md
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_reporter.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `reporter.py`**

```python
"""Markdown + CSV reporter."""
from __future__ import annotations

import csv
import statistics
from datetime import datetime
from pathlib import Path

from app.eval.types import CaseResult


class Reporter:
    def __init__(self, out_dir: str):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        run_id: str,
        suite: str,
        git_commit: str,
        started_at: datetime,
        finished_at: datetime,
        case_results: list[CaseResult],
        langsmith_url: str | None,
    ) -> dict[str, str]:
        md_path = self.out_dir / f"{started_at:%Y-%m-%d}-{suite}-{run_id}.md"
        csv_path = self.out_dir / f"{started_at:%Y-%m-%d}-{suite}-{run_id}.csv"

        md_path.write_text(self._render_md(
            run_id, suite, git_commit, started_at, finished_at, case_results, langsmith_url
        ), encoding="utf-8")
        self._write_csv(csv_path, case_results)
        return {"markdown": str(md_path), "csv": str(csv_path)}

    def _render_md(
        self,
        run_id, suite, git_commit, started_at, finished_at, case_results, langsmith_url,
    ) -> str:
        total = len(case_results)
        failed = [c for c in case_results if not c.ok]
        ok_cases = [c for c in case_results if c.ok]
        duration = (finished_at - started_at).total_seconds()

        # Aggregate by evaluator
        evaluator_names = sorted({
            r.evaluator_name for c in ok_cases for r in c.results
        })
        rows = []
        for name in evaluator_names:
            scores = [
                r.score for c in ok_cases for r in c.results
                if r.evaluator_name == name and r.score is not None
            ]
            low_conf = sum(
                1 for c in ok_cases for r in c.results
                if r.evaluator_name == name and r.low_confidence
            )
            if scores:
                rows.append({
                    "name": name,
                    "mean": round(statistics.mean(scores), 2),
                    "median": round(statistics.median(scores), 2),
                    "std": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
                    "low_conf": low_conf,
                    "n": len(scores),
                })

        md = [
            f"# Eval Suite: {suite}",
            f"**Run ID**: `{run_id}`",
            f"**Commit**: `{git_commit}`",
            f"**Started**: {started_at:%Y-%m-%d %H:%M:%S}",
            f"**Duration**: {int(duration)}s",
            f"**Cases**: {total} total, {len(ok_cases)} ok, {len(failed)} failed",
            "",
            "## Overall Scores",
            "",
            "| Evaluator | Mean | Median | Std | Low-confidence | N |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            md.append(f"| {r['name']} | {r['mean']} | {r['median']} | {r['std']} | {r['low_conf']}/{r['n']} | {r['n']} |")
        md.append("")

        # Per-case breakdown
        md.append("## Per-case Breakdown")
        md.append("")
        md.append("| case_id | query | " + " | ".join(evaluator_names) + " |")
        md.append("|" + "---|" * (2 + len(evaluator_names)))
        for c in ok_cases:
            score_map = {r.evaluator_name: r.score for r in c.results}
            cells = " | ".join(
                f"{score_map.get(n):.2f}" if isinstance(score_map.get(n), (int, float)) else "-"
                for n in evaluator_names
            )
            q = c.case.query[:30] + ("…" if len(c.case.query) > 30 else "")
            md.append(f"| `{c.case.id}` | {q} | {cells} |")
        md.append("")

        # Low-confidence cases
        low_conf_rows = []
        for c in ok_cases:
            for r in c.results:
                if r.low_confidence:
                    individual = " / ".join(
                        f"{o.get('judge')}={o.get('score')}" for o in (r.raw_judge_outputs or [])
                    )
                    low_conf_rows.append(f"- `{c.case.id}` / **{r.evaluator_name}** std={r.metadata.get('std', '?'):.2f}: {individual}")
        if low_conf_rows:
            md.append("## Low-confidence Cases (judge variance high — manual review recommended)")
            md.append("")
            md.extend(low_conf_rows)
            md.append("")

        # Failed cases
        if failed:
            md.append("## Failed Cases")
            md.append("")
            for c in failed:
                md.append(f"- `{c.case.id}`: {c.error}")
            md.append("")

        # LangSmith
        if langsmith_url:
            md.append("## LangSmith Dashboard")
            md.append("")
            md.append(f"[{langsmith_url}]({langsmith_url})")

        return "\n".join(md)

    def _write_csv(self, path: Path, case_results: list[CaseResult]) -> None:
        evaluator_names = sorted({
            r.evaluator_name for c in case_results for r in c.results
        })
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["case_id", "query", "ok", "error"] + evaluator_names)
            for c in case_results:
                score_map = {r.evaluator_name: r.score for r in c.results}
                row = [c.case.id, c.case.query, c.ok, c.error or ""]
                for n in evaluator_names:
                    v = score_map.get(n)
                    row.append("" if v is None else v)
                w.writerow(row)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_reporter.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/reporter.py backend/app/eval/tests/test_reporter.py
git commit -m "feat(eval): Reporter (markdown 报表 + csv 导出)"
```

---

## Task 17: LangSmithAdapter

**Files:**
- Create: `backend/app/eval/langsmith_adapter.py`
- Create: `backend/app/eval/tests/test_langsmith_adapter.py`

- [ ] **Step 1: 写测试**

```python
"""Test LangSmithAdapter — only the fail-open behavior. No real network."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.eval.langsmith_adapter import LangSmithAdapter
from app.eval.types import CaseResult, EvalCase, EvalResult


def test_adapter_disabled_when_no_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    a = LangSmithAdapter(project="test")
    assert a.enabled is False
    # upload is a no-op
    a.upload_case_sync(
        run_id="r1",
        case_result=CaseResult(
            case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
            results=[],
            started_at=datetime(2026, 5, 26),
            finished_at=datetime(2026, 5, 26),
        ),
    )


def test_adapter_swallows_exceptions(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake")
    a = LangSmithAdapter(project="test")
    a._client = MagicMock()
    a._client.create_run.side_effect = RuntimeError("network down")

    # Should NOT raise
    a.upload_case_sync(
        run_id="r1",
        case_result=CaseResult(
            case=EvalCase(id="q1", query="x", category="c", difficulty="easy"),
            results=[EvalResult(evaluator_name="cost", score=1.0)],
            started_at=datetime(2026, 5, 26),
            finished_at=datetime(2026, 5, 26),
        ),
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_langsmith_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `langsmith_adapter.py`**

```python
"""LangSmith trace + dataset upload. Best-effort (fail-open)."""
from __future__ import annotations

import logging
import os
from typing import Any

from app.eval.types import CaseResult

logger = logging.getLogger("eval.langsmith")


class LangSmithAdapter:
    """Best-effort uploader. Never raises — logs warnings on any failure."""

    def __init__(self, project: str):
        self.project = project
        self._api_key = os.getenv("LANGSMITH_API_KEY")
        self.enabled = bool(self._api_key)
        self._client = None
        if self.enabled:
            try:
                from langsmith import Client
                self._client = Client(api_key=self._api_key)
            except Exception as e:
                logger.warning(f"LangSmith init failed: {e}, disabling")
                self.enabled = False

    def upload_case_sync(self, run_id: str, case_result: CaseResult) -> None:
        if not self.enabled or self._client is None:
            return
        try:
            self._client.create_run(
                name=f"eval-case-{case_result.case.id}",
                run_type="chain",
                project_name=self.project,
                inputs={"query": case_result.case.query, "case_id": case_result.case.id},
                outputs={
                    "final_report": (case_result.state or {}).get("final_report", "")[:5000],
                    "evaluator_scores": {
                        r.evaluator_name: r.score for r in case_result.results
                    },
                },
                start_time=case_result.started_at,
                end_time=case_result.finished_at,
                extra={"run_id": run_id, "error": case_result.error},
            )
        except Exception as e:
            logger.warning(f"LangSmith upload failed for {case_result.case.id}: {e}")

    def dashboard_url(self) -> str | None:
        if not self.enabled:
            return None
        return f"https://smith.langchain.com/o/-/projects/p/{self.project}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_langsmith_adapter.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/langsmith_adapter.py backend/app/eval/tests/test_langsmith_adapter.py
git commit -m "feat(eval): LangSmithAdapter (fail-open trace 上报)"
```

---

## Task 18: Dataset 生成 + 种子 queries

**Files:**
- Create: `backend/app/eval/datasets/generator.py`
- Create: `backend/app/eval/datasets/seed_queries.jsonl`

- [ ] **Step 1: 实现 `datasets/generator.py`（一次性脚本，可重复运行）**

```python
"""Dataset generator. One-shot script: produces seed_queries.jsonl.

Usage:
    python -m app.eval.datasets.generator > backend/app/eval/datasets/seed_queries.jsonl

The 30 queries below are pre-curated for the resume-grade dataset.
Re-run only if you want to regenerate; otherwise the committed file is authoritative.
"""
from __future__ import annotations

import json
import sys

_QUERIES: list[dict] = [
    # 汽车 (5)
    {"id": "q001", "query": "新能源汽车 2024 年市场现状与发展趋势", "category": "汽车", "difficulty": "easy"},
    {"id": "q002", "query": "中国电动车出口欧洲 2024 年关税政策影响分析", "category": "汽车", "difficulty": "medium"},
    {"id": "q003", "query": "固态电池产业化进展与 2026 年商业化预测", "category": "汽车", "difficulty": "hard"},
    {"id": "q004", "query": "L4 级自动驾驶 2025 年量产现状", "category": "汽车", "difficulty": "medium"},
    {"id": "q005", "query": "新能源汽车售后服务市场规模与机会", "category": "汽车", "difficulty": "medium"},

    # 消费电子 (5)
    {"id": "q006", "query": "AI PC 2025 年市场格局与主要厂商策略", "category": "消费电子", "difficulty": "medium"},
    {"id": "q007", "query": "折叠屏手机 2024 年销量与技术演进", "category": "消费电子", "difficulty": "easy"},
    {"id": "q008", "query": "MR 头显市场 2025 年现状（苹果 Vision Pro vs Meta Quest）", "category": "消费电子", "difficulty": "medium"},
    {"id": "q009", "query": "智能手表健康监测功能演进与医疗合规路径", "category": "消费电子", "difficulty": "hard"},
    {"id": "q010", "query": "TWS 耳机市场饱和后的差异化方向", "category": "消费电子", "difficulty": "medium"},

    # 半导体 (5)
    {"id": "q011", "query": "国产 GPU 替代英伟达 H100 的现状与差距", "category": "半导体", "difficulty": "hard"},
    {"id": "q012", "query": "存储芯片 2024 年价格周期与供需分析", "category": "半导体", "difficulty": "medium"},
    {"id": "q013", "query": "3nm 工艺良率与代工厂产能分布", "category": "半导体", "difficulty": "hard"},
    {"id": "q014", "query": "RISC-V 在 AIoT 领域的应用前景", "category": "半导体", "difficulty": "medium"},
    {"id": "q015", "query": "汽车芯片 2024 年缺货缓解后的库存与价格走势", "category": "半导体", "difficulty": "medium"},

    # AI / 软件 (6)
    {"id": "q016", "query": "中国 SaaS 市场 2024 年增长率与典型公司分析", "category": "AI/软件", "difficulty": "easy"},
    {"id": "q017", "query": "大模型 API 价格战 2024-2025 年的影响与厂商应对", "category": "AI/软件", "difficulty": "medium"},
    {"id": "q018", "query": "AI Agent 平台 2025 年商业化路径", "category": "AI/软件", "difficulty": "hard"},
    {"id": "q019", "query": "RAG 工业落地的主要技术挑战与解决方案", "category": "AI/软件", "difficulty": "medium"},
    {"id": "q020", "query": "开源大模型 2025 年与闭源差距与商业模式", "category": "AI/软件", "difficulty": "medium"},
    {"id": "q021", "query": "国内 AI 编程助手 2025 年市场格局", "category": "AI/软件", "difficulty": "easy"},

    # 新能源 (4)
    {"id": "q022", "query": "光伏组件 2024 年价格与产能利用率", "category": "新能源", "difficulty": "medium"},
    {"id": "q023", "query": "储能行业 2025 年商业模式与盈利情况", "category": "新能源", "difficulty": "medium"},
    {"id": "q024", "query": "海上风电 2025 年装机与降本路径", "category": "新能源", "difficulty": "hard"},
    {"id": "q025", "query": "氢能产业链 2024 年关键环节进展", "category": "新能源", "difficulty": "hard"},

    # 医疗 (3)
    {"id": "q026", "query": "创新药出海 2024 年典型案例与挑战", "category": "医疗", "difficulty": "medium"},
    {"id": "q027", "query": "AI 辅助诊断在三甲医院的渗透率与瓶颈", "category": "医疗", "difficulty": "medium"},
    {"id": "q028", "query": "CGM 连续血糖监测市场 2025 年格局", "category": "医疗", "difficulty": "easy"},

    # 消费 (2)
    {"id": "q029", "query": "即时零售 2024 年市场格局与盈利模型", "category": "消费", "difficulty": "easy"},
    {"id": "q030", "query": "宠物经济 2025 年细分赛道与典型公司", "category": "消费", "difficulty": "easy"},
]


def main() -> None:
    for q in _QUERIES:
        sys.stdout.write(json.dumps(q, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 生成 seed_queries.jsonl**

```bash
cd backend && python -m app.eval.datasets.generator > app/eval/datasets/seed_queries.jsonl
wc -l app/eval/datasets/seed_queries.jsonl
```
Expected: `30 app/eval/datasets/seed_queries.jsonl`

- [ ] **Step 3: 5 分钟人工 sanity check（手动）**

Run: 用编辑器打开 `backend/app/eval/datasets/seed_queries.jsonl`，扫一遍 30 条 query：
- 长度 10-40 字
- 中文流畅
- 行业覆盖 7+
- 没有政治敏感/合规风险话题
- difficulty 标签合理

如有任何条目想改，直接编辑 jsonl 文件（不必重跑 generator）。

- [ ] **Step 4: 写一个 dataset loader test 防止 jsonl 格式坏掉**

追加到 `backend/app/eval/tests/test_types.py` 末尾：

```python
def test_seed_dataset_loads_and_has_30_entries():
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent / "datasets" / "seed_queries.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 30
    for line in lines:
        obj = json.loads(line)
        assert "id" in obj and "query" in obj
        assert obj["difficulty"] in {"easy", "medium", "hard"}
```

Run: `cd backend && pytest app/eval/tests/test_types.py::test_seed_dataset_loads_and_has_30_entries -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/eval/datasets/generator.py backend/app/eval/datasets/seed_queries.jsonl backend/app/eval/tests/test_types.py
git commit -m "feat(eval): dataset 30 条 seed query 覆盖 7 行业"
```

---

## Task 19: Runner

**Files:**
- Create: `backend/app/eval/runner.py`
- Create: `backend/app/eval/tests/test_runner_smoke.py`

- [ ] **Step 1: 写 runner smoke test**

```python
"""Test Runner end-to-end with mocked service + mocked judges."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.eval.runner import EvalRunner
from app.eval.types import EvalCase


@pytest.fixture
def two_cases() -> list[EvalCase]:
    return [
        EvalCase(id="q001", query="测试 query 1", category="汽车", difficulty="easy"),
        EvalCase(id="q002", query="测试 query 2", category="汽车", difficulty="easy"),
    ]


@pytest.mark.asyncio
async def test_runner_executes_all_cases(tmp_path, two_cases, sample_state, monkeypatch):
    """Mock service.research + checkpoint read + all judges."""
    db_path = str(tmp_path / "eval.db")
    out_dir = str(tmp_path / "results")

    # Patch service factory
    fake_service = MagicMock()

    async def fake_research(query, session_id, **kwargs):
        yield "data: {\"type\": \"phase\"}\n\n"
        yield "data: [DONE]\n\n"

    fake_service.research = fake_research

    # Patch checkpoint read to return sample_state
    async def fake_load_state(session_id):
        return sample_state

    # Patch EnsembleJudge.score
    from app.eval.types import EnsembleResult, JudgeScore
    fake_ensemble_result = EnsembleResult(
        mean_score=7.5, median_score=7.5, std=0.5,
        individual=[JudgeScore("a", 7.5, ""), JudgeScore("b", 7.5, ""), JudgeScore("c", 7.5, "")],
        low_confidence=False, partial=False,
    )

    fake_ensemble = MagicMock()
    fake_ensemble.score = AsyncMock(return_value=fake_ensemble_result)

    runner = EvalRunner(
        service=fake_service,
        load_final_state=fake_load_state,
        judge=fake_ensemble,
        db_path=db_path,
        out_dir=out_dir,
        concurrency=2,
        git_commit="testsha",
        langsmith_project="test",
    )

    summary = await runner.run("smoke", two_cases)
    assert summary["total"] == 2
    assert summary["ok"] >= 1

    # Verify markdown produced
    md_files = list(Path(out_dir).glob("*.md"))
    assert len(md_files) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest app/eval/tests/test_runner_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `runner.py`**

```python
"""Main eval runner: orchestrates research execution + evaluation + storage."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from app.eval.evaluators import build_all_evaluators
from app.eval.langsmith_adapter import LangSmithAdapter
from app.eval.reporter import Reporter
from app.eval.settings import DEFAULT_RESEARCH_TIMEOUT_SEC, LANGSMITH_PROJECT
from app.eval.storage import EvalStorage
from app.eval.types import CaseResult, EvalCase, EvalContext

logger = logging.getLogger("eval.runner")


class EvalRunner:
    def __init__(
        self,
        service: Any,
        load_final_state: Callable[[str], Awaitable[dict | None]],
        judge: Any,
        db_path: str,
        out_dir: str,
        concurrency: int = 5,
        git_commit: str = "unknown",
        langsmith_project: str = LANGSMITH_PROJECT,
    ):
        self.service = service
        self.load_final_state = load_final_state
        self.judge = judge
        self.evaluators = build_all_evaluators()
        self.storage = EvalStorage(db_path)
        self.storage.init_schema()
        self.reporter = Reporter(out_dir)
        self.langsmith = LangSmithAdapter(project=langsmith_project)
        self.concurrency = concurrency
        self.git_commit = git_commit

    async def run(self, suite: str, cases: list[EvalCase]) -> dict[str, Any]:
        run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        started_at = datetime.now()
        self.storage.save_run_start(
            run_id=run_id,
            suite=suite,
            started_at=started_at,
            git_commit=self.git_commit,
            config={"concurrency": self.concurrency},
        )

        sem = asyncio.Semaphore(self.concurrency)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            transient=False,
        ) as progress:
            task = progress.add_task("Eval", total=len(cases))

            async def one(case: EvalCase) -> CaseResult:
                async with sem:
                    result = await self._run_one_case(case, run_id)
                    progress.update(task, advance=1)
                    return result

            case_results = await asyncio.gather(*[one(c) for c in cases])

        finished_at = datetime.now()
        self.storage.save_run_end(run_id, finished_at)

        ls_url = self.langsmith.dashboard_url()
        paths = self.reporter.write(
            run_id=run_id,
            suite=suite,
            git_commit=self.git_commit,
            started_at=started_at,
            finished_at=finished_at,
            case_results=case_results,
            langsmith_url=ls_url,
        )

        return {
            "run_id": run_id,
            "total": len(case_results),
            "ok": sum(1 for c in case_results if c.ok),
            "failed": sum(1 for c in case_results if not c.ok),
            "markdown_path": paths["markdown"],
            "csv_path": paths["csv"],
            "langsmith_url": ls_url,
        }

    async def _run_one_case(self, case: EvalCase, run_id: str) -> CaseResult:
        started = datetime.now()
        try:
            # Phase A: run research
            state = await asyncio.wait_for(
                self._execute_research(case),
                timeout=DEFAULT_RESEARCH_TIMEOUT_SEC,
            )
            finished = datetime.now()

            ctx = EvalContext(
                case=case,
                state=state,
                started_at=started,
                finished_at=finished,
            )

            # Phase B: run all evaluators
            results = await asyncio.gather(
                *[ev.evaluate(ctx, self.judge) for ev in self.evaluators],
                return_exceptions=True,
            )

            from app.eval.types import EvalResult
            ev_results: list[EvalResult] = []
            for ev, r in zip(self.evaluators, results):
                if isinstance(r, EvalResult):
                    ev_results.append(r)
                else:
                    ev_results.append(EvalResult(
                        evaluator_name=ev.name,
                        score=None,
                        error=str(r),
                    ))

            cr = CaseResult(
                case=case,
                results=ev_results,
                ok=True,
                state=state,
                started_at=started,
                finished_at=finished,
            )

            # Phase C: persist
            self.storage.save_case(run_id, cr)
            self.langsmith.upload_case_sync(run_id, cr)
            return cr

        except asyncio.TimeoutError:
            cr = CaseResult(case=case, ok=False, error="TimeoutError (>10min)", started_at=started, finished_at=datetime.now())
            self.storage.save_case(run_id, cr)
            return cr
        except Exception as e:
            logger.exception(f"[{case.id}] failed: {e}")
            cr = CaseResult(case=case, ok=False, error=str(e), started_at=started, finished_at=datetime.now())
            self.storage.save_case(run_id, cr)
            return cr

    async def _execute_research(self, case: EvalCase) -> dict:
        """Consume SSE stream, then load final state from checkpoint."""
        async for chunk in self.service.research(
            query=case.query,
            session_id=case.id,
        ):
            if "[DONE]" in chunk:
                break

        # checkpoint write has a small delay; retry once if missing
        state = await self.load_final_state(case.id)
        if state is None:
            await asyncio.sleep(5)
            state = await self.load_final_state(case.id)
        if state is None:
            raise RuntimeError(f"checkpoint not found for session {case.id}")
        return state
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest app/eval/tests/test_runner_smoke.py -v`
Expected: 1 passed

- [ ] **Step 5: 跑全套单测确认无 regression**

Run: `cd backend && pytest app/eval/tests/ -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/eval/runner.py backend/app/eval/tests/test_runner_smoke.py
git commit -m "feat(eval): EvalRunner (asyncio.Semaphore 并发 + rich 进度条 + Phase ABC)"
```

---

## Task 20: CLI

**Files:**
- Create: `backend/app/eval/cli.py`

- [ ] **Step 1: 实现 `cli.py`**

```python
"""Eval CLI. Entry: python -m app.eval.cli"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from app.eval.judges.deepseek import build_deepseek_judge
from app.eval.judges.ensemble import EnsembleJudge
from app.eval.judges.mimo import build_mimo_judge
from app.eval.judges.qwen import build_qwen_judge
from app.eval.runner import EvalRunner
from app.eval.settings import (
    DEFAULT_CONCURRENCY,
    LANGSMITH_PROJECT,
    SQLITE_PATH,
    validate_required_keys,
)
from app.eval.types import EvalCase

logger = logging.getLogger("eval.cli")


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent.parent.parent,
        ).decode().strip()
    except Exception:
        return "unknown"


def _load_dataset(name: str) -> list[EvalCase]:
    base = Path(__file__).parent / "datasets"
    if name == "full":
        path = base / "seed_queries.jsonl"
    elif name == "mini":
        # First 5 of seed for quick iteration
        path = base / "seed_queries.jsonl"
    else:
        # Treat as path
        path = Path(name)

    lines = path.read_text(encoding="utf-8").splitlines()
    cases = [EvalCase(**json.loads(line)) for line in lines if line.strip()]
    if name == "mini":
        cases = cases[:5]
    return cases


async def _load_final_state(session_id: str) -> dict | None:
    """Load final research state from PG checkpoint table."""
    try:
        from service.checkpoint_service import CheckpointService
    except ImportError:
        try:
            from app.service.checkpoint_service import CheckpointService
        except ImportError:
            logger.error("Cannot import CheckpointService")
            return None

    svc = CheckpointService()
    cp = await svc.get_latest(session_id)
    if cp is None:
        return None
    return cp.get("state") if isinstance(cp, dict) else getattr(cp, "state", None)


def _build_service():
    try:
        from service.deep_research_v2.service import DeepResearchV2Service
    except ImportError:
        from app.service.deep_research_v2.service import DeepResearchV2Service
    return DeepResearchV2Service()


async def cmd_run(args: argparse.Namespace) -> int:
    missing = validate_required_keys()
    if missing:
        print(f"❌ Missing required env vars: {missing}", file=sys.stderr)
        return 2

    cases = _load_dataset(args.suite)
    if args.limit:
        cases = cases[: args.limit]
    print(f"Suite: {args.suite}, {len(cases)} cases, concurrency={args.concurrency}")

    judge = EnsembleJudge([
        build_deepseek_judge(),
        build_mimo_judge(),
        build_qwen_judge(),
    ])

    runner = EvalRunner(
        service=_build_service(),
        load_final_state=_load_final_state,
        judge=judge,
        db_path=args.db,
        out_dir=args.out,
        concurrency=args.concurrency,
        git_commit=_git_commit(),
        langsmith_project=args.langsmith_project,
    )

    summary = await runner.run(args.suite, cases)
    print("\n✅ Eval complete")
    print(f"  Run ID: {summary['run_id']}")
    print(f"  OK / Total: {summary['ok']} / {summary['total']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Markdown: {summary['markdown_path']}")
    print(f"  CSV: {summary['csv_path']}")
    if summary["langsmith_url"]:
        print(f"  LangSmith: {summary['langsmith_url']}")
    return 0 if summary["failed"] == 0 else 1


async def cmd_smoke(args: argparse.Namespace) -> int:
    """One-case real run for fast manual verification."""
    cases = [EvalCase(
        id=args.case_id,
        query=args.query,
        category="manual",
        difficulty="easy",
    )]
    args.suite = "smoke"
    args.limit = None
    return await cmd_run(args)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    p = argparse.ArgumentParser(prog="python -m app.eval.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run a full eval suite")
    p_run.add_argument("--suite", default="full", help="full | mini | <jsonl path>")
    p_run.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p_run.add_argument("--db", default=SQLITE_PATH)
    p_run.add_argument("--out", default="docs/eval-results")
    p_run.add_argument("--langsmith-project", default=LANGSMITH_PROJECT)
    p_run.add_argument("--limit", type=int, default=None, help="cap number of cases")

    p_smoke = sub.add_parser("smoke", help="Run 1 case (real LLM/network)")
    p_smoke.add_argument("--query", required=True)
    p_smoke.add_argument("--case-id", default="smoke-001")
    p_smoke.add_argument("--concurrency", type=int, default=1)
    p_smoke.add_argument("--db", default=SQLITE_PATH)
    p_smoke.add_argument("--out", default="docs/eval-results")
    p_smoke.add_argument("--langsmith-project", default=LANGSMITH_PROJECT)

    args = p.parse_args()
    if args.cmd == "run":
        return asyncio.run(cmd_run(args))
    elif args.cmd == "smoke":
        return asyncio.run(cmd_smoke(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 验证 `--help` 可用**

Run: `cd backend && python -m app.eval.cli --help`
Expected: 输出 usage 信息（不需要任何 API key）

Run: `cd backend && python -m app.eval.cli run --help`
Expected: 输出 run 子命令 usage

- [ ] **Step 3: 提交**

```bash
git add backend/app/eval/cli.py
git commit -m "feat(eval): CLI 入口 (run / smoke 子命令)"
```

---

## Task 21: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/eval.yml`

- [ ] **Step 1: 创建 workflow**

```yaml
name: Eval

on:
  pull_request:
    paths:
      - 'backend/app/eval/**'
      - 'backend/requirements.txt'
  workflow_dispatch:
    inputs:
      suite:
        description: 'Suite name (full / mini / <path>)'
        default: 'full'
        required: true
      concurrency:
        description: 'Parallel runs'
        default: '5'
        required: true

jobs:
  unit-tests:
    name: Eval unit tests (mock, no network)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        working-directory: backend
        run: |
          pip install -r requirements.txt
      - name: Run eval unit tests
        working-directory: backend
        run: |
          pytest app/eval/tests/ -v --tb=short

  eval-suite:
    name: Run full eval suite
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
      DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
      XIAOMI_API_KEY: ${{ secrets.XIAOMI_API_KEY }}
      BOCHA_API_KEY: ${{ secrets.BOCHA_API_KEY }}
      LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
      LANGSMITH_PROJECT: industry-research-eval
      POSTGRES_URL: ${{ secrets.POSTGRES_URL }}
      REDIS_URL: ${{ secrets.REDIS_URL }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        working-directory: backend
        run: pip install -r requirements.txt
      - name: Run eval
        working-directory: backend
        run: |
          python -m app.eval.cli run \
            --suite ${{ inputs.suite }} \
            --concurrency ${{ inputs.concurrency }}
      - name: Upload markdown report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: eval-report
          path: docs/eval-results/*
```

- [ ] **Step 2: 验证 yaml 合法**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/eval.yml'))"`
Expected: 无输出（合法）

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/eval.yml
git commit -m "ci(eval): GitHub Actions workflow (PR unit-tests + 手动触发 eval-suite)"
```

---

## Task 22: 端到端 smoke 验证 + 文档收尾

**Files:**
- Modify: `backend/app/eval/tests/fixtures/sample_state.json` (用真跑的 state 替换 conftest 的 fallback)

- [ ] **Step 1: 跑一次单 case smoke（真调 LLM、真访 URL、真上 LangSmith）**

⚠️ 跑这一步需要：
- `DASHSCOPE_API_KEY`、`BOCHA_API_KEY`（研究本身）
- `DEEPSEEK_API_KEY`、`XIAOMI_API_KEY`（额外 judge）
- 可选 `LANGSMITH_API_KEY`
- PostgreSQL 和 Redis 已起来

Run:
```bash
cd backend && python -m app.eval.cli smoke \
  --query "新能源汽车 2024 年市场现状" \
  --case-id smoke-001
```

Expected: 跑完 5-8 分钟，控制台输出 `✅ Eval complete`，产出 `docs/eval-results/YYYY-MM-DD-smoke-*.md`。

如果失败，按报错排查：
- API key 错 → 检查 .env
- timeout → 调 `DEFAULT_RESEARCH_TIMEOUT_SEC`
- judge 全挂 → 检查 mimo API 是否真的可用，必要时改用智谱 GLM-4 作 fallback
- checkpoint 读不到 → 检查 service 是否正常持久化

- [ ] **Step 2: 把 smoke 跑出来的 state 抽取做 fixture（提升后续测试真实度）**

跑完 smoke 后，从 PG checkpoint 表导出一条真实 state 到 `backend/app/eval/tests/fixtures/sample_state.json`：

```bash
cd backend && python -c "
import asyncio, json
from app.eval.cli import _load_final_state
state = asyncio.run(_load_final_state('smoke-001'))
with open('app/eval/tests/fixtures/sample_state.json', 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
print('wrote', len(json.dumps(state)), 'bytes')
"
```

如导出失败（PG 中已被新 session 覆盖等），保留 conftest 里的 fallback state 也可以。

- [ ] **Step 3: 重跑全套单测确认 fixture 替换后无 regression**

Run: `cd backend && pytest app/eval/tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: （可选）跑 mini suite（5 case）做端到端验证**

Run:
```bash
cd backend && python -m app.eval.cli run --suite mini --concurrency 2
```
Expected: 跑完约 15-20 分钟，产出 markdown 报表。

- [ ] **Step 5: 收尾提交**

```bash
git add backend/app/eval/tests/fixtures/
git commit -m "test(eval): 用真跑 state 替换 fixture（提升单测真实度）"
```

- [ ] **Step 6: 更新 spec 状态**

在 `docs/superpowers/specs/2026-05-26-eval-framework-design.md` 顶部 `> 状态` 行改为：

```
> 状态：✅ 已实施（2026-MM-DD），见 docs/superpowers/plans/2026-05-26-eval-framework-implementation.md
```

Run:
```bash
git add docs/superpowers/specs/2026-05-26-eval-framework-design.md
git commit -m "docs(eval): spec 标记为已实施"
```

---

## Self-Review

**Spec coverage check:**

| Spec 章节 | 覆盖 Task |
|---|---|
| §1 目标与非目标 | Plan 头 |
| §2 决策清单 | Task 1-22 全程贯彻 |
| §3 总体架构（目录） | Task 1 骨架 + 各 task 落实 |
| §3.2 依赖 | Task 1 |
| §4.1 Evaluator 基类 | Task 7 |
| §4.2 七个 Evaluator | Task 8-14 |
| §4.3 EnsembleJudge | Task 6 |
| §4.4 JudgeClient 配置（3 judge） | Task 3, 5 |
| §4.5 Runner | Task 19 |
| §4.6 Dataset 生成 | Task 18 |
| §5 数据流（SSE → checkpoint → eval → storage → report） | Task 19, 20 |
| §5.1 SQLite Schema | Task 15 |
| §5.2 Markdown 报表 | Task 16 |
| §6 错误处理（retry / 容错 / 限流） | Task 4 (retry), 6 (ensemble fallback), 19 (TimeoutError) |
| §6.3 aiolimiter | Task 4 |
| §6.4 进度条 + 结构化日志 | Task 19 |
| §7 测试策略 | Task 2-19 每个都 TDD |
| §7.5 CI | Task 21 |
| §8 风险（MiMo fallback） | 标注在 settings.py 注释 + Task 22 smoke 验证 |

**Placeholder scan:** no "TBD"/"TODO"/"implement later" found in any code block.

**Type consistency:**
- `EvalCase`/`JudgeScore`/`EnsembleResult`/`EvalResult`/`EvalContext`/`CaseResult` 在 Task 2 定义，后续 task 一致使用
- `EnsembleJudge.score(prompt) -> EnsembleResult` 接口在 Task 6 定义，evaluators (Task 12-14) 一致调用
- `Evaluator.evaluate(ctx, judge) -> EvalResult` 在 Task 7 定义，所有具体 evaluator 一致实现

**Implementation order rationale:**
- types → settings → judges → evaluators → storage/reporter → LangSmith → dataset → runner → CLI → CI → smoke
- 每层只依赖前层，可逐步验证

Plan 自检无 issue。
