# Claim-Centered Eval Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `backend/app/eval/` so every report evaluation is built around a shared claim/evidence artifact, with binary claim verification and weighted multi-judge report-quality rubrics.

**Architecture:** The runner will first build an `EvalArtifact` from final `ResearchState`, then calculate grouped metrics from that artifact. Claim-centered metrics cover information fidelity, citation verifiability, relevance coverage, and completeness; weighted multi-judge rubric scoring covers report quality dimensions. Storage and reporting will retain existing top-level score tables while adding artifact and claim-verdict diagnostics.

**Tech Stack:** Python 3.11+, dataclasses, asyncio, pytest, SQLite, OpenAI-compatible async clients, existing `backend/app/eval` framework.

---

## File Structure

Create:

- `backend/app/eval/artifacts.py` - dataclasses for evidence, sections, requirements, claims, verdicts, report-quality scores, and full artifact serialization.
- `backend/app/eval/artifact_builders/__init__.py` - builder package exports.
- `backend/app/eval/artifact_builders/evidence.py` - convert `ResearchState` facts/references/raw sources into deduplicated `EvidenceItem` objects.
- `backend/app/eval/artifact_builders/report_structure.py` - parse Markdown sections and numeric citation ids.
- `backend/app/eval/artifact_builders/json_utils.py` - parse fenced or plain JSON from judge responses.
- `backend/app/eval/artifact_builders/claim_extraction.py` - structured LLM call for query requirements and atomic claims.
- `backend/app/eval/artifact_builders/claim_verification.py` - structured LLM call for binary evidence-grounded verdicts.
- `backend/app/eval/artifact_builders/report_quality.py` - multi-judge quality rubric aggregation.
- `backend/app/eval/artifact_builders/prompts/claim_extraction.md` - claim extraction prompt.
- `backend/app/eval/artifact_builders/prompts/claim_verification.md` - claim verification prompt.
- `backend/app/eval/artifact_builders/prompts/report_quality.md` - report quality rubric prompt.
- `backend/app/eval/artifact_builder.py` - orchestrates all artifact builders.
- `backend/app/eval/metric_calculator.py` - converts `EvalArtifact` into existing `EvalResult` rows.
- `backend/app/eval/tests/test_artifacts.py`
- `backend/app/eval/tests/test_artifact_builder.py`
- `backend/app/eval/tests/test_metric_calculator.py`
- `backend/app/eval/tests/test_artifact_builders/test_evidence.py`
- `backend/app/eval/tests/test_artifact_builders/test_report_structure.py`
- `backend/app/eval/tests/test_artifact_builders/test_json_utils.py`
- `backend/app/eval/tests/test_artifact_builders/test_claim_extraction.py`
- `backend/app/eval/tests/test_artifact_builders/test_claim_verification.py`
- `backend/app/eval/tests/test_artifact_builders/test_report_quality.py`

Modify:

- `backend/app/eval/types.py` - add `StructuredJudgeResult` and optional `artifact` on `CaseResult`.
- `backend/app/eval/settings.py` - add judge weights and artifact limits.
- `backend/app/eval/judges/base.py` - add structured-output LLM call that does not parse numeric scores.
- `backend/app/eval/judges/ensemble.py` - add primary structured generation and all-judge structured generation.
- `backend/app/eval/runner.py` - build artifact before calculating metrics.
- `backend/app/eval/storage.py` - persist `eval_artifacts` and `claim_verdicts`.
- `backend/app/eval/reporter.py` - render grouped metrics and claim diagnostics.
- `backend/app/eval/tests/test_judges/test_base.py`
- `backend/app/eval/tests/test_judges/test_ensemble.py`
- `backend/app/eval/tests/test_runner_smoke.py`
- `backend/app/eval/tests/test_storage.py`
- `backend/app/eval/tests/test_reporter.py`
- `docs/eval-framework-interview-brief.md` - update interview notes after implementation verifies.

---

### Task 1: Artifact Dataclasses

**Files:**
- Create: `backend/app/eval/artifacts.py`
- Create: `backend/app/eval/tests/test_artifacts.py`
- Modify: `backend/app/eval/types.py`
- Test: `backend/app/eval/tests/test_artifacts.py`

- [ ] **Step 1: Write failing artifact serialization tests**

Create `backend/app/eval/tests/test_artifacts.py`:

```python
from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    EvalArtifact,
    EvidenceItem,
    QueryRequirement,
    ReportQualityScores,
    ReportSection,
    artifact_from_dict,
    artifact_to_dict,
)


def test_artifact_round_trips_to_plain_dict():
    artifact = EvalArtifact(
        evidence=[
            EvidenceItem(
                id="f1",
                text="2024 year sales reached 9.5 million vehicles.",
                source_name="CAAM",
                source_url="https://example.com/a",
                source_type="official",
                credibility_score=0.9,
            )
        ],
        sections=[
            ReportSection(
                id="s1",
                title="Market Size",
                text="Sales reached 9.5 million vehicles [1].",
                citation_ids=["1"],
            )
        ],
        requirements=[
            QueryRequirement(id="r1", text="Analyze 2024 market size", importance="high")
        ],
        claims=[
            AtomicClaim(
                id="c1",
                text="2024 year sales reached 9.5 million vehicles.",
                section_id="s1",
                importance="high",
                citation_ids=["1"],
                requirement_ids=["r1"],
            )
        ],
        verdicts=[
            ClaimVerdict(
                claim_id="c1",
                supported=True,
                reason="Evidence f1 states the same number.",
                evidence_ids=["f1"],
                confidence="high",
            )
        ],
        quality=ReportQualityScores(
            coherence=8.0,
            cohesion_structure=7.5,
            analytical_depth=8.2,
            professionalism_readability=8.4,
            decision_usefulness=7.8,
            raw_judge_outputs=[{"judge": "qwen", "coherence": 8.0}],
            std_by_dimension={"coherence": 0.5},
            low_confidence_dimensions=[],
            partial=False,
        ),
    )

    payload = artifact_to_dict(artifact)
    restored = artifact_from_dict(payload)

    assert payload["claims"][0]["id"] == "c1"
    assert restored.claims[0].text == artifact.claims[0].text
    assert restored.quality.coherence == 8.0
    assert restored.errors == []


def test_artifact_defaults_are_empty_lists():
    artifact = EvalArtifact()
    assert artifact.evidence == []
    assert artifact.sections == []
    assert artifact.requirements == []
    assert artifact.claims == []
    assert artifact.verdicts == []
    assert artifact.errors == []
    assert artifact.quality.coherence is None
```

- [ ] **Step 2: Run artifact tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifacts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval.artifacts'`.

- [ ] **Step 3: Implement artifact dataclasses**

Create `backend/app/eval/artifacts.py`:

```python
"""Shared claim-centered eval artifact models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvidenceItem:
    id: str
    text: str
    source_name: str = ""
    source_url: str = ""
    source_type: str = ""
    credibility_score: float | None = None


@dataclass
class ReportSection:
    id: str
    title: str
    text: str
    citation_ids: list[str] = field(default_factory=list)


@dataclass
class QueryRequirement:
    id: str
    text: str
    importance: str = "medium"


@dataclass
class AtomicClaim:
    id: str
    text: str
    section_id: str | None = None
    importance: str = "medium"
    citation_ids: list[str] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)


@dataclass
class ClaimVerdict:
    claim_id: str
    supported: bool
    reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    confidence: str = "medium"


@dataclass
class ReportQualityScores:
    coherence: float | None = None
    cohesion_structure: float | None = None
    analytical_depth: float | None = None
    professionalism_readability: float | None = None
    decision_usefulness: float | None = None
    raw_judge_outputs: list[dict[str, Any]] = field(default_factory=list)
    std_by_dimension: dict[str, float] = field(default_factory=dict)
    low_confidence_dimensions: list[str] = field(default_factory=list)
    partial: bool = False
    error: str | None = None


@dataclass
class EvalArtifact:
    evidence: list[EvidenceItem] = field(default_factory=list)
    sections: list[ReportSection] = field(default_factory=list)
    requirements: list[QueryRequirement] = field(default_factory=list)
    claims: list[AtomicClaim] = field(default_factory=list)
    verdicts: list[ClaimVerdict] = field(default_factory=list)
    quality: ReportQualityScores = field(default_factory=ReportQualityScores)
    errors: list[str] = field(default_factory=list)


def artifact_to_dict(artifact: EvalArtifact) -> dict[str, Any]:
    return asdict(artifact)


def artifact_from_dict(data: dict[str, Any] | None) -> EvalArtifact:
    if not data:
        return EvalArtifact()
    return EvalArtifact(
        evidence=[EvidenceItem(**item) for item in data.get("evidence", [])],
        sections=[ReportSection(**item) for item in data.get("sections", [])],
        requirements=[QueryRequirement(**item) for item in data.get("requirements", [])],
        claims=[AtomicClaim(**item) for item in data.get("claims", [])],
        verdicts=[ClaimVerdict(**item) for item in data.get("verdicts", [])],
        quality=ReportQualityScores(**data.get("quality", {})),
        errors=list(data.get("errors", [])),
    )
```

- [ ] **Step 4: Add structured result and artifact field to eval types**

Modify `backend/app/eval/types.py` by adding this dataclass after `JudgeScore`:

```python
@dataclass
class StructuredJudgeResult:
    """One judge's raw structured-output response."""
    judge_name: str
    content: str
    failed: bool = False
    error: str | None = None
```

Modify `CaseResult` by adding this field:

```python
    artifact: Any | None = None
```

- [ ] **Step 5: Run artifact tests and existing type tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifacts.py app/eval/tests/test_types.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/eval/artifacts.py backend/app/eval/types.py backend/app/eval/tests/test_artifacts.py
git commit -m "feat(eval): add claim-centered artifact models"
```

---

### Task 2: Evidence and Report Structure Builders

**Files:**
- Create: `backend/app/eval/artifact_builders/__init__.py`
- Create: `backend/app/eval/artifact_builders/evidence.py`
- Create: `backend/app/eval/artifact_builders/report_structure.py`
- Create: `backend/app/eval/tests/test_artifact_builders/test_evidence.py`
- Create: `backend/app/eval/tests/test_artifact_builders/test_report_structure.py`
- Modify: `backend/app/eval/settings.py`
- Test: `backend/app/eval/tests/test_artifact_builders/test_evidence.py`, `backend/app/eval/tests/test_artifact_builders/test_report_structure.py`

- [ ] **Step 1: Write failing evidence builder tests**

Create `backend/app/eval/tests/test_artifact_builders/test_evidence.py`:

```python
from app.eval.artifact_builders.evidence import EvidenceIndexBuilder


def test_evidence_builder_uses_facts_first_and_deduplicates():
    state = {
        "facts": [
            {
                "id": "f1",
                "content": "Sales reached 9.5 million vehicles in 2024.",
                "source_name": "CAAM",
                "source_url": "https://example.com/a",
                "source_type": "official",
                "credibility_score": 0.9,
            },
            {
                "id": "f2",
                "content": "Sales reached 9.5 million vehicles in 2024.",
                "source_name": "CAAM duplicate",
                "source_url": "https://example.com/a",
                "source_type": "official",
                "credibility_score": 0.8,
            },
        ],
        "references": [
            {"id": "1", "title": "Industry report", "url": "https://example.com/ref"}
        ],
    }

    items = EvidenceIndexBuilder(max_items=10).build(state)

    assert [item.id for item in items] == ["f1", "ref_1"]
    assert items[0].source_name == "CAAM"
    assert items[1].text == "Industry report"


def test_evidence_builder_truncates_text_and_limits_count():
    state = {
        "facts": [
            {
                "id": f"f{i}",
                "content": "x" * 500,
                "source_name": "src",
                "source_url": f"https://example.com/{i}",
            }
            for i in range(5)
        ]
    }

    items = EvidenceIndexBuilder(max_items=2, item_chars=100).build(state)

    assert len(items) == 2
    assert len(items[0].text) == 100
```

- [ ] **Step 2: Write failing report structure tests**

Create `backend/app/eval/tests/test_artifact_builders/test_report_structure.py`:

```python
from app.eval.artifact_builders.report_structure import (
    extract_citation_ids,
    parse_report_sections,
)


def test_extract_citation_ids_handles_single_list_and_range():
    text = "Market grew [1], policy helped [2,3], and exports rose [4-6]."
    assert extract_citation_ids(text) == ["1", "2", "3", "4", "5", "6"]


def test_parse_report_sections_ignores_references():
    report = """
## Executive Summary
Summary claim [1].

## 1 Market Size
Sales increased [1,2].

### 1.1 Export
Exports grew [3].

## References
[1] Source A
[2] Source B
"""

    sections = parse_report_sections(report)

    assert [s.id for s in sections] == ["s1", "s2", "s3"]
    assert sections[0].title == "Executive Summary"
    assert sections[1].citation_ids == ["1", "2"]
    assert sections[2].title == "1.1 Export"
```

- [ ] **Step 3: Run builder tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builders/test_evidence.py app/eval/tests/test_artifact_builders/test_report_structure.py -v
```

Expected: FAIL with missing `app.eval.artifact_builders` modules.

- [ ] **Step 4: Add settings constants**

Modify `backend/app/eval/settings.py` by adding:

```python
MAX_EVIDENCE_ITEMS = int(os.getenv("EVAL_MAX_EVIDENCE_ITEMS", "60"))
EVIDENCE_ITEM_CHARS = int(os.getenv("EVAL_EVIDENCE_ITEM_CHARS", "300"))
MAX_CLAIMS = int(os.getenv("EVAL_MAX_CLAIMS", "40"))
REPORT_CHARS = int(os.getenv("EVAL_REPORT_CHARS", "8000"))
```

- [ ] **Step 5: Implement evidence builder**

Create `backend/app/eval/artifact_builders/__init__.py`:

```python
"""Artifact builder package for claim-centered evaluation."""
```

Create `backend/app/eval/artifact_builders/evidence.py`:

```python
"""Build a compact evidence index from ResearchState."""
from __future__ import annotations

from app.eval.artifacts import EvidenceItem
from app.eval.settings import EVIDENCE_ITEM_CHARS, MAX_EVIDENCE_ITEMS


def _norm_key(url: str, text: str) -> tuple[str, str]:
    normalized = " ".join((text or "").split()).lower()
    return (url or "", normalized[:120])


class EvidenceIndexBuilder:
    def __init__(
        self,
        max_items: int = MAX_EVIDENCE_ITEMS,
        item_chars: int = EVIDENCE_ITEM_CHARS,
    ):
        self.max_items = max_items
        self.item_chars = item_chars

    def build(self, state: dict) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        seen: set[tuple[str, str]] = set()

        for fact in state.get("facts") or []:
            text = str(fact.get("content") or "").strip()
            if not text:
                continue
            url = str(fact.get("source_url") or "")
            key = _norm_key(url, text)
            if key in seen:
                continue
            seen.add(key)
            items.append(EvidenceItem(
                id=str(fact.get("id") or f"f{len(items) + 1}"),
                text=text[: self.item_chars],
                source_name=str(fact.get("source_name") or ""),
                source_url=url,
                source_type=str(fact.get("source_type") or ""),
                credibility_score=fact.get("credibility_score"),
            ))
            if len(items) >= self.max_items:
                return items

        for ref in state.get("references") or []:
            title = str(ref.get("title") or ref.get("source") or ref.get("marker") or "").strip()
            url = str(ref.get("url") or "")
            if not title and not url:
                continue
            text = title or url
            key = _norm_key(url, text)
            if key in seen:
                continue
            seen.add(key)
            ref_id = str(ref.get("id") or len(items) + 1)
            items.append(EvidenceItem(
                id=f"ref_{ref_id}",
                text=text[: self.item_chars],
                source_name=title,
                source_url=url,
                source_type="reference",
                credibility_score=None,
            ))
            if len(items) >= self.max_items:
                return items

        for src in state.get("raw_sources") or []:
            text = str(src.get("summary") or src.get("snippet") or src.get("content") or "").strip()
            if not text:
                continue
            url = str(src.get("url") or "")
            key = _norm_key(url, text)
            if key in seen:
                continue
            seen.add(key)
            items.append(EvidenceItem(
                id=str(src.get("id") or f"raw_{len(items) + 1}"),
                text=text[: self.item_chars],
                source_name=str(src.get("title") or src.get("site_name") or ""),
                source_url=url,
                source_type="raw_source",
                credibility_score=None,
            ))
            if len(items) >= self.max_items:
                return items

        return items
```

- [ ] **Step 6: Implement report structure parser**

Create `backend/app/eval/artifact_builders/report_structure.py`:

```python
"""Parse final Markdown reports into sections and citation ids."""
from __future__ import annotations

import re

from app.eval.artifacts import ReportSection

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_CITATION_RE = re.compile(r"\[(\d+(?:\s*[,]\s*\d+|\s*-\s*\d+)*)\]")
_REFERENCE_HEADING_RE = re.compile(r"^(#{2,3})\s*(references|参考文献|引用|来源)\s*$", re.IGNORECASE | re.MULTILINE)


def extract_citation_ids(text: str) -> list[str]:
    ids: list[str] = []
    for match in _CITATION_RE.finditer(text or ""):
        token = match.group(1).replace(" ", "")
        if "-" in token:
            start, end = token.split("-", 1)
            try:
                ids.extend(str(i) for i in range(int(start), int(end) + 1))
            except ValueError:
                continue
        else:
            ids.extend(part for part in token.split(",") if part)
    return ids


def strip_reference_section(report: str) -> str:
    match = _REFERENCE_HEADING_RE.search(report or "")
    if not match:
        return report or ""
    return (report or "")[: match.start()].rstrip()


def parse_report_sections(report: str) -> list[ReportSection]:
    body = strip_reference_section(report)
    headings = list(_HEADING_RE.finditer(body))
    if not headings:
        text = body.strip()
        return [ReportSection(id="s1", title="Report", text=text, citation_ids=extract_citation_ids(text))] if text else []

    sections: list[ReportSection] = []
    for idx, heading in enumerate(headings):
        start = heading.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(body)
        text = body[start:end].strip()
        title = heading.group(2).strip()
        sections.append(ReportSection(
            id=f"s{idx + 1}",
            title=title,
            text=text,
            citation_ids=extract_citation_ids(text),
        ))
    return sections
```

- [ ] **Step 7: Run builder tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builders/test_evidence.py app/eval/tests/test_artifact_builders/test_report_structure.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/eval/settings.py backend/app/eval/artifact_builders backend/app/eval/tests/test_artifact_builders
git commit -m "feat(eval): build evidence and report structure artifacts"
```

---

### Task 3: Structured Judge Calls

**Files:**
- Modify: `backend/app/eval/judges/base.py`
- Modify: `backend/app/eval/judges/ensemble.py`
- Modify: `backend/app/eval/types.py`
- Create/modify: `backend/app/eval/tests/test_judges/test_structured.py`
- Test: `backend/app/eval/tests/test_judges/test_structured.py`, `backend/app/eval/tests/test_judges/test_base.py`, `backend/app/eval/tests/test_judges/test_ensemble.py`

- [ ] **Step 1: Write failing structured judge tests**

Create `backend/app/eval/tests/test_judges/test_structured.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.judges.base import JudgeClient
from app.eval.judges.ensemble import EnsembleJudge
from app.eval.settings import JudgeConfig
from app.eval.types import StructuredJudgeResult
from app.eval.tests.conftest import make_openai_response


@pytest.fixture
def cfg() -> JudgeConfig:
    return JudgeConfig(
        name="testjudge",
        base_url="https://example.com/v1",
        model="test-model",
        api_key_env="NO_KEY",
        max_rate_per_min=100,
    )


@pytest.mark.asyncio
async def test_call_structured_returns_raw_content(cfg, monkeypatch):
    client = JudgeClient(cfg)
    fake_create = AsyncMock(return_value=make_openai_response('{"claims": []}'))
    client._client.chat.completions.create = fake_create

    result = await client.call_structured("prompt", system_prompt="system")

    assert result == StructuredJudgeResult(
        judge_name="testjudge",
        content='{"claims": []}',
        failed=False,
        error=None,
    )
    fake_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensemble_generate_structured_uses_primary_client():
    first = AsyncMock()
    second = AsyncMock()
    first.call_structured = AsyncMock(return_value=StructuredJudgeResult("a", '{"ok": true}'))
    second.call_structured = AsyncMock(return_value=StructuredJudgeResult("b", '{"ok": false}'))

    ensemble = EnsembleJudge([first, second])
    result = await ensemble.generate_structured("prompt", system_prompt="system")

    assert result.judge_name == "a"
    first.call_structured.assert_awaited_once()
    second.call_structured.assert_not_called()


@pytest.mark.asyncio
async def test_ensemble_generate_structured_all_calls_all_clients():
    first = AsyncMock()
    second = AsyncMock()
    first.call_structured = AsyncMock(return_value=StructuredJudgeResult("a", '{"score": 8}'))
    second.call_structured = AsyncMock(return_value=StructuredJudgeResult("b", '{"score": 7}'))

    ensemble = EnsembleJudge([first, second])
    results = await ensemble.generate_structured_all("prompt", system_prompt="system")

    assert [r.judge_name for r in results] == ["a", "b"]
```

- [ ] **Step 2: Run structured judge tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_judges/test_structured.py -v
```

Expected: FAIL with missing `call_structured` or missing `generate_structured`.

- [ ] **Step 3: Implement `JudgeClient.call_structured`**

In `backend/app/eval/judges/base.py`, add this method to `JudgeClient`:

```python
    async def call_structured(self, prompt: str, system_prompt: str) -> StructuredJudgeResult:
        """Call judge for raw structured JSON/text output. Always returns a result."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(JUDGE_RETRY_ATTEMPTS),
                wait=wait_exponential(multiplier=1, min=1, max=16),
                retry=retry_if_exception_type((APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)),
                reraise=True,
            ):
                with attempt:
                    async with self._limiter:
                        resp = await self._client.chat.completions.create(
                            model=self.cfg.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": prompt},
                            ],
                            temperature=0.0,
                        )
                    return StructuredJudgeResult(
                        judge_name=self.cfg.name,
                        content=resp.choices[0].message.content or "",
                    )
        except Exception as e:
            logger.warning(f"[{self.cfg.name}] structured call failed after retries: {e}")
            return StructuredJudgeResult(
                judge_name=self.cfg.name,
                content="",
                failed=True,
                error=str(e),
            )
```

Also update the import near the top:

```python
from app.eval.types import JudgeScore, StructuredJudgeResult
```

- [ ] **Step 4: Implement structured methods on `EnsembleJudge`**

In `backend/app/eval/judges/ensemble.py`, update the protocol:

```python
class _JudgeProtocol(Protocol):
    async def call_judge(self, prompt: str) -> JudgeScore:
        pass

    async def call_structured(self, prompt: str, system_prompt: str) -> StructuredJudgeResult:
        pass
```

Update imports:

```python
from app.eval.types import EnsembleResult, JudgeScore, StructuredJudgeResult
```

Add methods inside `EnsembleJudge`:

```python
    async def generate_structured(self, prompt: str, system_prompt: str) -> StructuredJudgeResult:
        """Use the primary judge only for low-cost structured artifact generation."""
        return await self.clients[0].call_structured(prompt, system_prompt)

    async def generate_structured_all(self, prompt: str, system_prompt: str) -> list[StructuredJudgeResult]:
        """Use all judges for multi-judge structured rubric scoring."""
        raw = await asyncio.gather(
            *[c.call_structured(prompt, system_prompt) for c in self.clients],
            return_exceptions=True,
        )
        results: list[StructuredJudgeResult] = []
        for r in raw:
            if isinstance(r, StructuredJudgeResult):
                results.append(r)
            else:
                results.append(StructuredJudgeResult(
                    judge_name="unknown",
                    content="",
                    failed=True,
                    error=str(r),
                ))
        return results
```

- [ ] **Step 5: Run judge tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_judges/test_structured.py app/eval/tests/test_judges/test_base.py app/eval/tests/test_judges/test_ensemble.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/eval/types.py backend/app/eval/judges/base.py backend/app/eval/judges/ensemble.py backend/app/eval/tests/test_judges/test_structured.py
git commit -m "feat(eval): add structured judge calls"
```

---

### Task 4: Claim Extraction and Verification Builders

**Files:**
- Create: `backend/app/eval/artifact_builders/json_utils.py`
- Create: `backend/app/eval/artifact_builders/claim_extraction.py`
- Create: `backend/app/eval/artifact_builders/claim_verification.py`
- Create: `backend/app/eval/artifact_builders/prompts/claim_extraction.md`
- Create: `backend/app/eval/artifact_builders/prompts/claim_verification.md`
- Create: `backend/app/eval/tests/test_artifact_builders/test_json_utils.py`
- Create: `backend/app/eval/tests/test_artifact_builders/test_claim_extraction.py`
- Create: `backend/app/eval/tests/test_artifact_builders/test_claim_verification.py`
- Test: the three new test files

- [ ] **Step 1: Write failing JSON parser tests**

Create `backend/app/eval/tests/test_artifact_builders/test_json_utils.py`:

```python
import pytest

from app.eval.artifact_builders.json_utils import parse_json_object


def test_parse_json_object_plain_json():
    assert parse_json_object('{"claims": []}') == {"claims": []}


def test_parse_json_object_fenced_json():
    raw = '```json\n{"verdicts": [{"claim_id": "c1"}]}\n```'
    assert parse_json_object(raw) == {"verdicts": [{"claim_id": "c1"}]}


def test_parse_json_object_raises_for_non_object():
    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object("[1, 2, 3]")
```

- [ ] **Step 2: Write failing claim extraction tests**

Create `backend/app/eval/tests/test_artifact_builders/test_claim_extraction.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builders.claim_extraction import ClaimExtractionBuilder
from app.eval.artifacts import ReportSection
from app.eval.types import StructuredJudgeResult


@pytest.mark.asyncio
async def test_claim_extraction_builder_parses_requirements_and_claims():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"requirements":[{"id":"r1","text":"market size","importance":"high"}],"claims":[{"id":"c1","text":"Sales reached 9.5 million.","section_id":"s1","importance":"high","citation_ids":["1"],"requirement_ids":["r1"]}]}',
    ))
    sections = [ReportSection(id="s1", title="Market", text="Sales reached 9.5 million [1].", citation_ids=["1"])]

    requirements, claims = await ClaimExtractionBuilder(max_claims=10).build(
        query="Analyze market size",
        sections=sections,
        judge=judge,
    )

    assert requirements[0].id == "r1"
    assert claims[0].citation_ids == ["1"]
    assert claims[0].requirement_ids == ["r1"]


@pytest.mark.asyncio
async def test_claim_extraction_builder_rejects_bad_json():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult("qwen", "not json"))

    with pytest.raises(ValueError, match="could not parse"):
        await ClaimExtractionBuilder().build("query", [], judge)
```

- [ ] **Step 3: Write failing claim verification tests**

Create `backend/app/eval/tests/test_artifact_builders/test_claim_verification.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builders.claim_verification import ClaimVerificationBuilder
from app.eval.artifacts import AtomicClaim, EvidenceItem
from app.eval.types import StructuredJudgeResult


@pytest.mark.asyncio
async def test_claim_verification_builder_parses_verdicts():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"verdicts":[{"claim_id":"c1","supported":true,"reason":"supported","evidence_ids":["f1"],"confidence":"high"}]}',
    ))
    claims = [AtomicClaim(id="c1", text="Sales reached 9.5 million.")]
    evidence = [EvidenceItem(id="f1", text="Sales reached 9.5 million.", source_name="CAAM")]

    verdicts = await ClaimVerificationBuilder().build(claims, evidence, judge)

    assert verdicts[0].claim_id == "c1"
    assert verdicts[0].supported is True
    assert verdicts[0].evidence_ids == ["f1"]


@pytest.mark.asyncio
async def test_claim_verification_builder_marks_missing_verdicts_unsupported():
    judge = AsyncMock()
    judge.generate_structured = AsyncMock(return_value=StructuredJudgeResult(
        judge_name="qwen",
        content='{"verdicts":[]}',
    ))
    claims = [AtomicClaim(id="c1", text="Unsupported claim.")]

    verdicts = await ClaimVerificationBuilder().build(claims, [], judge)

    assert verdicts[0].claim_id == "c1"
    assert verdicts[0].supported is False
    assert verdicts[0].reason == "judge omitted verdict"
```

- [ ] **Step 4: Run tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builders/test_json_utils.py app/eval/tests/test_artifact_builders/test_claim_extraction.py app/eval/tests/test_artifact_builders/test_claim_verification.py -v
```

Expected: FAIL with missing modules.

- [ ] **Step 5: Implement JSON parser**

Create `backend/app/eval/artifact_builders/json_utils.py`:

```python
"""JSON parsing helpers for structured judge output."""
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"could not parse structured JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("structured judge output must be a JSON object")
    return obj
```

- [ ] **Step 6: Add claim extraction prompt**

Create `backend/app/eval/artifact_builders/prompts/claim_extraction.md`:

```markdown
You are building an evaluation artifact for an industry research report.

Extract query requirements and atomic factual claims from the report sections.

Rules:
- Split compound statements into separate verifiable claims.
- Keep numeric values, years, entities, and comparisons intact.
- Ignore purely stylistic text, headings, and generic transitions.
- Map claims to requirements when the relationship is clear.
- Preserve citation ids already found in each section.
- Return at most {max_claims} claims.

User query:
{query}

Report sections:
{sections_json}

Return ONLY JSON:
{
  "requirements": [
    {"id": "r1", "text": "requirement text", "importance": "high|medium|low"}
  ],
  "claims": [
    {
      "id": "c1",
      "text": "single verifiable factual claim",
      "section_id": "s1",
      "importance": "high|medium|low",
      "citation_ids": ["1"],
      "requirement_ids": ["r1"]
    }
  ]
}
```

- [ ] **Step 7: Implement claim extraction builder**

Create `backend/app/eval/artifact_builders/claim_extraction.py`:

```python
"""LLM-backed query requirement and claim extraction."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.eval.artifact_builders.json_utils import parse_json_object
from app.eval.artifacts import AtomicClaim, QueryRequirement, ReportSection
from app.eval.settings import MAX_CLAIMS

_PROMPT_PATH = Path(__file__).parent / "prompts" / "claim_extraction.md"
_SYSTEM_PROMPT = "You extract structured evaluation artifacts. Respond only with valid JSON."


class ClaimExtractionBuilder:
    def __init__(self, max_claims: int = MAX_CLAIMS):
        self.max_claims = max_claims

    async def build(
        self,
        query: str,
        sections: list[ReportSection],
        judge: Any,
    ) -> tuple[list[QueryRequirement], list[AtomicClaim]]:
        sections_json = json.dumps([
            {
                "id": s.id,
                "title": s.title,
                "text": s.text,
                "citation_ids": s.citation_ids,
            }
            for s in sections
        ], ensure_ascii=False)
        prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
            query=query,
            sections_json=sections_json,
            max_claims=self.max_claims,
        )
        result = await judge.generate_structured(prompt, system_prompt=_SYSTEM_PROMPT)
        if result.failed:
            raise ValueError(result.error or "claim extraction judge failed")
        payload = parse_json_object(result.content)
        requirements = [
            QueryRequirement(
                id=str(item.get("id") or f"r{idx + 1}"),
                text=str(item.get("text") or "").strip(),
                importance=str(item.get("importance") or "medium"),
            )
            for idx, item in enumerate(payload.get("requirements") or [])
            if str(item.get("text") or "").strip()
        ]
        claims = [
            AtomicClaim(
                id=str(item.get("id") or f"c{idx + 1}"),
                text=str(item.get("text") or "").strip(),
                section_id=item.get("section_id"),
                importance=str(item.get("importance") or "medium"),
                citation_ids=[str(x) for x in item.get("citation_ids") or []],
                requirement_ids=[str(x) for x in item.get("requirement_ids") or []],
            )
            for idx, item in enumerate(payload.get("claims") or [])
            if str(item.get("text") or "").strip()
        ][: self.max_claims]
        return requirements, claims
```

- [ ] **Step 8: Add claim verification prompt**

Create `backend/app/eval/artifact_builders/prompts/claim_verification.md`:

```markdown
You are verifying report claims against evidence.

For each claim, decide whether the evidence supports the claim.

Rules:
- Use binary supported true or false.
- Mark false when evidence is missing, vague, contradictory, or does not support numeric or time-specific details.
- Only use evidence in the evidence list.
- Return one verdict for every claim id.

Claims:
{claims_json}

Evidence:
{evidence_json}

Return ONLY JSON:
{
  "verdicts": [
    {
      "claim_id": "c1",
      "supported": true,
      "reason": "short Chinese reason",
      "evidence_ids": ["f1"],
      "confidence": "high|medium|low"
    }
  ]
}
```

- [ ] **Step 9: Implement claim verification builder**

Create `backend/app/eval/artifact_builders/claim_verification.py`:

```python
"""LLM-backed binary verification of claims against evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.eval.artifact_builders.json_utils import parse_json_object
from app.eval.artifacts import AtomicClaim, ClaimVerdict, EvidenceItem

_PROMPT_PATH = Path(__file__).parent / "prompts" / "claim_verification.md"
_SYSTEM_PROMPT = "You verify claims against evidence. Respond only with valid JSON."


class ClaimVerificationBuilder:
    async def build(
        self,
        claims: list[AtomicClaim],
        evidence: list[EvidenceItem],
        judge: Any,
    ) -> list[ClaimVerdict]:
        if not claims:
            return []
        claims_json = json.dumps([claim.__dict__ for claim in claims], ensure_ascii=False)
        evidence_json = json.dumps([item.__dict__ for item in evidence], ensure_ascii=False)
        prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
            claims_json=claims_json,
            evidence_json=evidence_json,
        )
        result = await judge.generate_structured(prompt, system_prompt=_SYSTEM_PROMPT)
        if result.failed:
            raise ValueError(result.error or "claim verification judge failed")
        payload = parse_json_object(result.content)
        by_claim: dict[str, ClaimVerdict] = {}
        for item in payload.get("verdicts") or []:
            claim_id = str(item.get("claim_id") or "")
            if not claim_id:
                continue
            by_claim[claim_id] = ClaimVerdict(
                claim_id=claim_id,
                supported=bool(item.get("supported")),
                reason=str(item.get("reason") or ""),
                evidence_ids=[str(x) for x in item.get("evidence_ids") or []],
                confidence=str(item.get("confidence") or "medium"),
            )
        verdicts: list[ClaimVerdict] = []
        for claim in claims:
            verdicts.append(by_claim.get(claim.id, ClaimVerdict(
                claim_id=claim.id,
                supported=False,
                reason="judge omitted verdict",
                evidence_ids=[],
                confidence="low",
            )))
        return verdicts
```

- [ ] **Step 10: Run claim builder tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builders/test_json_utils.py app/eval/tests/test_artifact_builders/test_claim_extraction.py app/eval/tests/test_artifact_builders/test_claim_verification.py -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```powershell
git add backend/app/eval/artifact_builders backend/app/eval/tests/test_artifact_builders
git commit -m "feat(eval): extract and verify report claims"
```

---

### Task 5: Report Quality Weighted Multi-Judge Rubric

**Files:**
- Create: `backend/app/eval/artifact_builders/report_quality.py`
- Create: `backend/app/eval/artifact_builders/prompts/report_quality.md`
- Create: `backend/app/eval/tests/test_artifact_builders/test_report_quality.py`
- Modify: `backend/app/eval/settings.py`
- Test: `backend/app/eval/tests/test_artifact_builders/test_report_quality.py`

- [ ] **Step 1: Write failing report quality tests**

Create `backend/app/eval/tests/test_artifact_builders/test_report_quality.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builders.report_quality import ReportQualityBuilder
from app.eval.artifacts import AtomicClaim, ClaimVerdict, ReportSection
from app.eval.types import StructuredJudgeResult


@pytest.mark.asyncio
async def test_report_quality_builder_aggregates_weighted_scores():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(return_value=[
        StructuredJudgeResult("deepseek", '{"coherence":{"score":8,"reasoning":"ok"},"cohesion_structure":{"score":7,"reasoning":"ok"},"analytical_depth":{"score":8,"reasoning":"ok"},"professionalism_readability":{"score":9,"reasoning":"ok"},"decision_usefulness":{"score":7,"reasoning":"ok"}}'),
        StructuredJudgeResult("qwen", '{"coherence":{"score":9,"reasoning":"ok"},"cohesion_structure":{"score":8,"reasoning":"ok"},"analytical_depth":{"score":8,"reasoning":"ok"},"professionalism_readability":{"score":8,"reasoning":"ok"},"decision_usefulness":{"score":8,"reasoning":"ok"}}'),
        StructuredJudgeResult("mimo", '{"coherence":{"score":6,"reasoning":"ok"},"cohesion_structure":{"score":6,"reasoning":"ok"},"analytical_depth":{"score":7,"reasoning":"ok"},"professionalism_readability":{"score":7,"reasoning":"ok"},"decision_usefulness":{"score":6,"reasoning":"ok"}}'),
    ])

    quality = await ReportQualityBuilder(weights={"deepseek": 0.4, "qwen": 0.4, "mimo": 0.2}).build(
        query="Analyze market",
        sections=[ReportSection("s1", "Market", "Text", [])],
        claims=[AtomicClaim("c1", "Claim")],
        verdicts=[ClaimVerdict("c1", True)],
        judge=judge,
    )

    assert quality.coherence == pytest.approx(8.2)
    assert quality.cohesion_structure == pytest.approx(7.2)
    assert quality.partial is False
    assert quality.raw_judge_outputs[0]["judge"] == "deepseek"


@pytest.mark.asyncio
async def test_report_quality_builder_skips_failed_judge():
    judge = AsyncMock()
    judge.generate_structured_all = AsyncMock(return_value=[
        StructuredJudgeResult("deepseek", "", failed=True, error="timeout"),
        StructuredJudgeResult("qwen", '{"coherence":{"score":8,"reasoning":"ok"}}'),
    ])

    quality = await ReportQualityBuilder(weights={"deepseek": 0.5, "qwen": 0.5}).build(
        query="q",
        sections=[],
        claims=[],
        verdicts=[],
        judge=judge,
    )

    assert quality.coherence == 8.0
    assert quality.partial is True
```

- [ ] **Step 2: Run report quality tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builders/test_report_quality.py -v
```

Expected: FAIL with missing `report_quality` module.

- [ ] **Step 3: Add judge weights to settings**

Modify `backend/app/eval/settings.py`:

```python
JUDGE_WEIGHTS: dict[str, float] = {
    "deepseek": float(os.getenv("EVAL_JUDGE_WEIGHT_DEEPSEEK", "0.4")),
    "qwen": float(os.getenv("EVAL_JUDGE_WEIGHT_QWEN", "0.4")),
    "mimo": float(os.getenv("EVAL_JUDGE_WEIGHT_MIMO", "0.2")),
}

REPORT_QUALITY_DIMENSIONS = (
    "coherence",
    "cohesion_structure",
    "analytical_depth",
    "professionalism_readability",
    "decision_usefulness",
)
```

- [ ] **Step 4: Add report quality prompt**

Create `backend/app/eval/artifact_builders/prompts/report_quality.md`:

```markdown
You are evaluating an industry research report.

Score each dimension from 0 to 10:
- coherence: logical consistency and whether conclusions follow from prior analysis
- cohesion_structure: section organization, transitions, and paragraph flow
- analytical_depth: causal explanation, tradeoff analysis, trend interpretation, risks and opportunities
- professionalism_readability: terminology precision, concise professional wording, and low grammar/noise burden
- decision_usefulness: whether the report helps decisions such as investment, strategy, market entry, or product planning

User query:
{query}

Report sections:
{sections_json}

Claim support summary:
{claim_summary_json}

Return ONLY JSON:
{
  "coherence": {"score": 8.0, "reasoning": "short Chinese reason"},
  "cohesion_structure": {"score": 8.0, "reasoning": "short Chinese reason"},
  "analytical_depth": {"score": 8.0, "reasoning": "short Chinese reason"},
  "professionalism_readability": {"score": 8.0, "reasoning": "short Chinese reason"},
  "decision_usefulness": {"score": 8.0, "reasoning": "short Chinese reason"}
}
```

- [ ] **Step 5: Implement report quality builder**

Create `backend/app/eval/artifact_builders/report_quality.py`:

```python
"""Weighted multi-judge report quality rubric."""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from app.eval.artifact_builders.json_utils import parse_json_object
from app.eval.artifacts import AtomicClaim, ClaimVerdict, ReportQualityScores, ReportSection
from app.eval.settings import JUDGE_WEIGHTS, LOW_CONFIDENCE_STD_THRESHOLD, REPORT_QUALITY_DIMENSIONS

_PROMPT_PATH = Path(__file__).parent / "prompts" / "report_quality.md"
_SYSTEM_PROMPT = "You are a strict industry research report evaluator. Respond only with valid JSON."


def _extract_dimension_scores(raw_payload: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for dim in REPORT_QUALITY_DIMENSIONS:
        item = raw_payload.get(dim)
        if isinstance(item, dict) and item.get("score") is not None:
            score = float(item["score"])
            scores[dim] = max(0.0, min(10.0, score))
    return scores


def _weighted_mean(values: list[tuple[str, float]], weights: dict[str, float]) -> float:
    numerator = sum(weights.get(name, 1.0) * score for name, score in values)
    denominator = sum(weights.get(name, 1.0) for name, _ in values)
    return numerator / denominator if denominator else 0.0


class ReportQualityBuilder:
    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or JUDGE_WEIGHTS

    async def build(
        self,
        query: str,
        sections: list[ReportSection],
        claims: list[AtomicClaim],
        verdicts: list[ClaimVerdict],
        judge: Any,
    ) -> ReportQualityScores:
        sections_json = json.dumps([s.__dict__ for s in sections], ensure_ascii=False)
        verdict_by_claim = {v.claim_id: v for v in verdicts}
        claim_summary_json = json.dumps([
            {
                "id": c.id,
                "text": c.text,
                "supported": verdict_by_claim.get(c.id).supported if c.id in verdict_by_claim else None,
            }
            for c in claims[:40]
        ], ensure_ascii=False)
        prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
            query=query,
            sections_json=sections_json,
            claim_summary_json=claim_summary_json,
        )
        raw_results = await judge.generate_structured_all(prompt, system_prompt=_SYSTEM_PROMPT)

        raw_outputs: list[dict[str, Any]] = []
        scores_by_dim: dict[str, list[tuple[str, float]]] = {dim: [] for dim in REPORT_QUALITY_DIMENSIONS}
        partial = False
        for result in raw_results:
            if result.failed:
                partial = True
                raw_outputs.append({"judge": result.judge_name, "failed": True, "error": result.error})
                continue
            try:
                payload = parse_json_object(result.content)
                scores = _extract_dimension_scores(payload)
            except ValueError as e:
                partial = True
                raw_outputs.append({"judge": result.judge_name, "failed": True, "error": str(e)})
                continue
            raw_outputs.append({"judge": result.judge_name, "failed": False, "scores": scores})
            for dim, score in scores.items():
                scores_by_dim[dim].append((result.judge_name, score))

        aggregated: dict[str, float | None] = {}
        std_by_dimension: dict[str, float] = {}
        low_confidence_dimensions: list[str] = []
        for dim, values in scores_by_dim.items():
            if not values:
                aggregated[dim] = None
                continue
            scores = [score for _, score in values]
            aggregated[dim] = round(_weighted_mean(values, self.weights), 2)
            std = statistics.stdev(scores) if len(scores) > 1 else 0.0
            std_by_dimension[dim] = round(std, 3)
            if std > LOW_CONFIDENCE_STD_THRESHOLD:
                low_confidence_dimensions.append(dim)

        return ReportQualityScores(
            coherence=aggregated.get("coherence"),
            cohesion_structure=aggregated.get("cohesion_structure"),
            analytical_depth=aggregated.get("analytical_depth"),
            professionalism_readability=aggregated.get("professionalism_readability"),
            decision_usefulness=aggregated.get("decision_usefulness"),
            raw_judge_outputs=raw_outputs,
            std_by_dimension=std_by_dimension,
            low_confidence_dimensions=low_confidence_dimensions,
            partial=partial,
        )
```

- [ ] **Step 6: Run report quality tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builders/test_report_quality.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/eval/settings.py backend/app/eval/artifact_builders/report_quality.py backend/app/eval/artifact_builders/prompts/report_quality.md backend/app/eval/tests/test_artifact_builders/test_report_quality.py
git commit -m "feat(eval): score report quality with weighted judges"
```

---

### Task 6: EvalArtifact Builder Orchestration

**Files:**
- Create: `backend/app/eval/artifact_builder.py`
- Create: `backend/app/eval/tests/test_artifact_builder.py`
- Test: `backend/app/eval/tests/test_artifact_builder.py`

- [ ] **Step 1: Write failing artifact builder test**

Create `backend/app/eval/tests/test_artifact_builder.py`:

```python
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.eval.artifact_builder import EvalArtifactBuilder
from app.eval.artifacts import ReportQualityScores
from app.eval.types import EvalCase, EvalContext


@pytest.mark.asyncio
async def test_artifact_builder_builds_claim_centered_artifact(monkeypatch):
    builder = EvalArtifactBuilder()
    builder.claim_extractor.build = AsyncMock(return_value=(
        [{"id": "r1", "text": "market size", "importance": "high"}],
        [{"id": "c1", "text": "Sales reached 9.5 million.", "section_id": "s1", "importance": "high", "citation_ids": ["1"], "requirement_ids": ["r1"]}],
    ))
    builder.claim_verifier.build = AsyncMock(return_value=[
        {"claim_id": "c1", "supported": True, "reason": "supported", "evidence_ids": ["f1"], "confidence": "high"}
    ])
    builder.report_quality.build = AsyncMock(return_value=ReportQualityScores(coherence=8.0))

    ctx = EvalContext(
        case=EvalCase(id="q1", query="Analyze market size", category="auto", difficulty="easy"),
        state={
            "final_report": "## Market\nSales reached 9.5 million [1].",
            "facts": [{"id": "f1", "content": "Sales reached 9.5 million.", "source_url": "https://example.com"}],
        },
        started_at=datetime(2026, 5, 31),
        finished_at=datetime(2026, 5, 31),
    )

    artifact = await builder.build(ctx, judge=AsyncMock())

    assert artifact.evidence[0].id == "f1"
    assert artifact.sections[0].id == "s1"
    assert artifact.claims[0].id == "c1"
    assert artifact.verdicts[0].supported is True
    assert artifact.quality.coherence == 8.0
```

- [ ] **Step 2: Run artifact builder test and verify it fails**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builder.py -v
```

Expected: FAIL with missing `app.eval.artifact_builder`.

- [ ] **Step 3: Implement artifact builder**

Create `backend/app/eval/artifact_builder.py`:

```python
"""Orchestrate claim-centered eval artifact construction."""
from __future__ import annotations

from typing import Any

from app.eval.artifact_builders.claim_extraction import ClaimExtractionBuilder
from app.eval.artifact_builders.claim_verification import ClaimVerificationBuilder
from app.eval.artifact_builders.evidence import EvidenceIndexBuilder
from app.eval.artifact_builders.report_quality import ReportQualityBuilder
from app.eval.artifact_builders.report_structure import parse_report_sections
from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    EvalArtifact,
    QueryRequirement,
)
from app.eval.types import EvalContext


def _coerce_requirement(item: Any) -> QueryRequirement:
    if isinstance(item, QueryRequirement):
        return item
    return QueryRequirement(
        id=str(item.get("id")),
        text=str(item.get("text")),
        importance=str(item.get("importance", "medium")),
    )


def _coerce_claim(item: Any) -> AtomicClaim:
    if isinstance(item, AtomicClaim):
        return item
    return AtomicClaim(
        id=str(item.get("id")),
        text=str(item.get("text")),
        section_id=item.get("section_id"),
        importance=str(item.get("importance", "medium")),
        citation_ids=[str(x) for x in item.get("citation_ids", [])],
        requirement_ids=[str(x) for x in item.get("requirement_ids", [])],
    )


def _coerce_verdict(item: Any) -> ClaimVerdict:
    if isinstance(item, ClaimVerdict):
        return item
    return ClaimVerdict(
        claim_id=str(item.get("claim_id")),
        supported=bool(item.get("supported")),
        reason=str(item.get("reason", "")),
        evidence_ids=[str(x) for x in item.get("evidence_ids", [])],
        confidence=str(item.get("confidence", "medium")),
    )


class EvalArtifactBuilder:
    def __init__(self):
        self.evidence_builder = EvidenceIndexBuilder()
        self.claim_extractor = ClaimExtractionBuilder()
        self.claim_verifier = ClaimVerificationBuilder()
        self.report_quality = ReportQualityBuilder()

    async def build(self, ctx: EvalContext, judge: Any) -> EvalArtifact:
        errors: list[str] = []
        evidence = self.evidence_builder.build(ctx.state)
        sections = parse_report_sections(ctx.state.get("final_report") or "")

        requirements: list[QueryRequirement] = []
        claims: list[AtomicClaim] = []
        try:
            raw_requirements, raw_claims = await self.claim_extractor.build(ctx.case.query, sections, judge)
            requirements = [_coerce_requirement(item) for item in raw_requirements]
            claims = [_coerce_claim(item) for item in raw_claims]
        except Exception as e:
            errors.append(f"claim_extraction: {e}")

        verdicts: list[ClaimVerdict] = []
        if claims:
            try:
                raw_verdicts = await self.claim_verifier.build(claims, evidence, judge)
                verdicts = [_coerce_verdict(item) for item in raw_verdicts]
            except Exception as e:
                errors.append(f"claim_verification: {e}")

        try:
            quality = await self.report_quality.build(ctx.case.query, sections, claims, verdicts, judge)
        except Exception as e:
            errors.append(f"report_quality: {e}")
            from app.eval.artifacts import ReportQualityScores
            quality = ReportQualityScores(error=str(e), partial=True)

        return EvalArtifact(
            evidence=evidence,
            sections=sections,
            requirements=requirements,
            claims=claims,
            verdicts=verdicts,
            quality=quality,
            errors=errors,
        )
```

- [ ] **Step 4: Run artifact builder test**

Run:

```powershell
cd backend
pytest app/eval/tests/test_artifact_builder.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/eval/artifact_builder.py backend/app/eval/tests/test_artifact_builder.py
git commit -m "feat(eval): build unified eval artifacts"
```

---

### Task 7: Claim-Centered Metric Calculator

**Files:**
- Create: `backend/app/eval/metric_calculator.py`
- Create: `backend/app/eval/tests/test_metric_calculator.py`
- Test: `backend/app/eval/tests/test_metric_calculator.py`

- [ ] **Step 1: Write failing metric tests**

Create `backend/app/eval/tests/test_metric_calculator.py`:

```python
from __future__ import annotations

from datetime import datetime

import pytest

from app.eval.artifacts import (
    AtomicClaim,
    ClaimVerdict,
    EvalArtifact,
    EvidenceItem,
    QueryRequirement,
    ReportQualityScores,
    ReportSection,
)
from app.eval.metric_calculator import MetricCalculator
from app.eval.types import EvalCase, EvalContext


def make_ctx() -> EvalContext:
    return EvalContext(
        case=EvalCase(id="q1", query="Analyze market size and risks", category="auto", difficulty="easy"),
        state={
            "outline": [{"id": "s1", "title": "Market"}, {"id": "s2", "title": "Risks"}],
            "logs": [{"tokens_used": 1000, "model": "qwen-max"}],
            "critic_feedback": [{"id": "cf1", "resolved": True}],
        },
        started_at=datetime(2026, 5, 31, 10, 0),
        finished_at=datetime(2026, 5, 31, 10, 5),
    )


def test_metric_calculator_computes_claim_metrics():
    artifact = EvalArtifact(
        evidence=[EvidenceItem(id="ref_1", text="Market size grew.", source_url="https://example.com/a")],
        sections=[ReportSection("s1", "Market", "Text", ["1"]), ReportSection("s2", "Risks", "Text", [])],
        requirements=[
            QueryRequirement("r1", "market size", "high"),
            QueryRequirement("r2", "risks", "high"),
        ],
        claims=[
            AtomicClaim("c1", "Market size grew.", "s1", "high", ["1"], ["r1"]),
            AtomicClaim("c2", "Risk is low.", "s2", "high", [], ["r2"]),
        ],
        verdicts=[
            ClaimVerdict("c1", True, evidence_ids=["ref_1"]),
            ClaimVerdict("c2", False, reason="missing evidence"),
        ],
        quality=ReportQualityScores(coherence=8.0, cohesion_structure=7.0),
    )

    results = MetricCalculator().calculate(make_ctx(), artifact)
    scores = {r.evaluator_name: r.score for r in results}

    assert scores["claim_support_rate"] == 5.0
    assert scores["citation_verifiability"] == pytest.approx(10.0)
    assert scores["relevance_coverage"] == 5.0
    assert scores["completeness"] == 5.0
    assert scores["coherence"] == 8.0
    assert scores["cohesion_structure"] == 7.0


def test_metric_calculator_records_artifact_errors():
    artifact = EvalArtifact(errors=["claim_extraction: bad json"])
    results = MetricCalculator().calculate(make_ctx(), artifact)
    by_name = {r.evaluator_name: r for r in results}
    assert by_name["claim_support_rate"].score is None
    assert "claim_extraction" in by_name["claim_support_rate"].error
```

- [ ] **Step 2: Run metric tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_metric_calculator.py -v
```

Expected: FAIL with missing `app.eval.metric_calculator`.

- [ ] **Step 3: Implement metric calculator**

Create `backend/app/eval/metric_calculator.py`:

```python
"""Calculate eval scores from a claim-centered EvalArtifact."""
from __future__ import annotations

from app.eval.artifacts import EvalArtifact
from app.eval.types import EvalContext, EvalResult


def _round_score(value: float) -> float:
    return round(max(0.0, min(10.0, value)), 2)


def _artifact_error(artifact: EvalArtifact) -> str | None:
    return "; ".join(artifact.errors) if artifact.errors else None


class MetricCalculator:
    def calculate(self, ctx: EvalContext, artifact: EvalArtifact) -> list[EvalResult]:
        results: list[EvalResult] = []
        results.extend(self._claim_metrics(artifact))
        results.extend(self._quality_metrics(artifact))
        results.extend(self._operational_metrics(ctx))
        return results

    def _claim_metrics(self, artifact: EvalArtifact) -> list[EvalResult]:
        error = _artifact_error(artifact)
        verdict_by_claim = {v.claim_id: v for v in artifact.verdicts}
        total_claims = len(artifact.claims)
        supported_claims = sum(1 for v in artifact.verdicts if v.supported)
        unsupported_claims = [
            {"claim_id": c.id, "text": c.text, "reason": verdict_by_claim.get(c.id).reason if c.id in verdict_by_claim else "missing verdict"}
            for c in artifact.claims
            if not (c.id in verdict_by_claim and verdict_by_claim[c.id].supported)
        ]

        claim_support = None if total_claims == 0 else _round_score(supported_claims / total_claims * 10)

        cited_claims = [c for c in artifact.claims if c.citation_ids]
        citation_score = None
        if cited_claims:
            known_citation_ids = set()
            for item in artifact.evidence:
                known_citation_ids.add(item.id)
                if item.id.startswith("ref_"):
                    known_citation_ids.add(item.id.removeprefix("ref_"))
            known_cited = 0
            supported_cited = 0
            evidence_overlap = 0
            for claim in cited_claims:
                verdict = verdict_by_claim.get(claim.id)
                claim_ref_ids = set(claim.citation_ids)
                expanded_ref_ids = claim_ref_ids | {f"ref_{ref_id}" for ref_id in claim_ref_ids}
                if claim_ref_ids and claim_ref_ids.issubset(known_citation_ids):
                    known_cited += 1
                if verdict and verdict.supported:
                    supported_cited += 1
                    if expanded_ref_ids & set(verdict.evidence_ids):
                        evidence_overlap += 1
            citation_score = _round_score(
                (
                    known_cited / len(cited_claims)
                    + supported_cited / len(cited_claims)
                    + evidence_overlap / len(cited_claims)
                ) / 3 * 10
            )

        high_requirements = [r for r in artifact.requirements if r.importance == "high"]
        covered_requirements = set()
        for claim in artifact.claims:
            verdict = verdict_by_claim.get(claim.id)
            if verdict and verdict.supported:
                covered_requirements.update(claim.requirement_ids)
        relevance_score = None
        if high_requirements:
            relevance_score = _round_score(
                sum(1 for req in high_requirements if req.id in covered_requirements) / len(high_requirements) * 10
            )

        section_ids = {s.id for s in artifact.sections}
        supported_sections = {
            claim.section_id
            for claim in artifact.claims
            if claim.section_id and claim.id in verdict_by_claim and verdict_by_claim[claim.id].supported
        }
        completeness_score = None
        if section_ids:
            completeness_score = _round_score(len(supported_sections & section_ids) / len(section_ids) * 10)

        return [
            EvalResult(
                evaluator_name="claim_support_rate",
                score=claim_support,
                metadata={
                    "claim_count": total_claims,
                    "supported_count": supported_claims,
                    "unsupported_claims": unsupported_claims[:10],
                },
                error=error if claim_support is None else None,
            ),
            EvalResult(
                evaluator_name="citation_verifiability",
                score=citation_score,
                metadata={
                    "cited_claim_count": len(cited_claims),
                    "known_cited_claim_count": known_cited if cited_claims else 0,
                    "supported_cited_claim_count": supported_cited if cited_claims else 0,
                    "evidence_overlap_count": evidence_overlap if cited_claims else 0,
                },
                error=error if citation_score is None else None,
            ),
            EvalResult(
                evaluator_name="relevance_coverage",
                score=relevance_score,
                metadata={
                    "requirement_count": len(artifact.requirements),
                    "high_requirement_count": len(high_requirements),
                    "covered_requirement_ids": sorted(covered_requirements),
                },
                error=error if relevance_score is None else None,
            ),
            EvalResult(
                evaluator_name="completeness",
                score=completeness_score,
                metadata={
                    "section_count": len(section_ids),
                    "supported_section_count": len(supported_sections & section_ids),
                },
                error=error if completeness_score is None else None,
            ),
        ]

    def _quality_metrics(self, artifact: EvalArtifact) -> list[EvalResult]:
        quality = artifact.quality
        names = [
            "coherence",
            "cohesion_structure",
            "analytical_depth",
            "professionalism_readability",
            "decision_usefulness",
        ]
        return [
            EvalResult(
                evaluator_name=name,
                score=getattr(quality, name),
                raw_judge_outputs=quality.raw_judge_outputs,
                metadata={
                    "std": quality.std_by_dimension.get(name),
                    "partial": quality.partial,
                },
                low_confidence=name in quality.low_confidence_dimensions,
                error=quality.error if getattr(quality, name) is None else None,
            )
            for name in names
        ]

    def _operational_metrics(self, ctx: EvalContext) -> list[EvalResult]:
        feedback = ctx.state.get("critic_feedback") or []
        if feedback:
            resolved = sum(1 for item in feedback if item.get("resolved"))
            critic_score = _round_score(resolved / len(feedback) * 10)
        else:
            resolved = 0
            critic_score = None

        total_tokens = sum(int(log.get("tokens_used") or 0) for log in (ctx.state.get("logs") or []))
        cost_score = 0.0 if total_tokens == 0 else round(total_tokens / 1_000_000, 4)

        return [
            EvalResult(
                evaluator_name="critic_loop_effectiveness",
                score=critic_score,
                metadata={"resolved": resolved, "total_feedback": len(feedback)},
            ),
            EvalResult(
                evaluator_name="cost",
                score=cost_score,
                metadata={"total_tokens": total_tokens},
            ),
            EvalResult(
                evaluator_name="latency",
                score=round(ctx.duration_sec / 60, 2),
                metadata={"duration_sec": ctx.duration_sec},
            ),
        ]
```

- [ ] **Step 4: Run metric tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_metric_calculator.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/eval/metric_calculator.py backend/app/eval/tests/test_metric_calculator.py
git commit -m "feat(eval): calculate metrics from claim artifacts"
```

---

### Task 8: Runner Integration

**Files:**
- Modify: `backend/app/eval/runner.py`
- Modify: `backend/app/eval/tests/test_runner_smoke.py`
- Test: `backend/app/eval/tests/test_runner_smoke.py`

- [ ] **Step 1: Update runner smoke test to expect artifact path**

Modify the fake judge setup in `backend/app/eval/tests/test_runner_smoke.py` so it includes structured outputs:

```python
    from app.eval.types import StructuredJudgeResult

    fake_ensemble.generate_structured = AsyncMock(side_effect=[
        StructuredJudgeResult(
            "qwen",
            '{"requirements":[{"id":"r1","text":"market","importance":"high"}],"claims":[{"id":"c1","text":"2024 sales grew.","section_id":"s1","importance":"high","citation_ids":["1"],"requirement_ids":["r1"]}]}',
        ),
        StructuredJudgeResult(
            "qwen",
            '{"verdicts":[{"claim_id":"c1","supported":true,"reason":"supported","evidence_ids":["f1"],"confidence":"high"}]}',
        ),
    ])
    fake_ensemble.generate_structured_all = AsyncMock(return_value=[
        StructuredJudgeResult(
            "deepseek",
            '{"coherence":{"score":8,"reasoning":"ok"},"cohesion_structure":{"score":8,"reasoning":"ok"},"analytical_depth":{"score":8,"reasoning":"ok"},"professionalism_readability":{"score":8,"reasoning":"ok"},"decision_usefulness":{"score":8,"reasoning":"ok"}}',
        )
    ])
```

Add assertions after summary:

```python
    assert fake_ensemble.generate_structured.await_count == 4
    assert fake_ensemble.generate_structured_all.await_count == 2
```

There are two cases, so claim extraction and verification run twice each.

- [ ] **Step 2: Run runner smoke test and verify it fails**

Run:

```powershell
cd backend
pytest app/eval/tests/test_runner_smoke.py -v
```

Expected: FAIL because current runner still uses independent evaluators and never calls structured artifact builders.

- [ ] **Step 3: Modify runner to use artifact builder and metric calculator**

In `backend/app/eval/runner.py`, add imports:

```python
from app.eval.artifact_builder import EvalArtifactBuilder
from app.eval.metric_calculator import MetricCalculator
```

In `EvalRunner.__init__`, replace evaluator setup:

```python
        self.artifact_builder = EvalArtifactBuilder()
        self.metric_calculator = MetricCalculator()
```

Remove:

```python
        self.evaluators = build_all_evaluators()
```

In `_run_one_case`, replace Phase B:

```python
            artifact = await self.artifact_builder.build(ctx, self.judge)
            ev_results = self.metric_calculator.calculate(ctx, artifact)
```

Set artifact on the `CaseResult`:

```python
                artifact=artifact,
```

Remove the `asyncio.gather` evaluator loop and the local import of `EvalResult`.

- [ ] **Step 4: Run runner smoke test**

Run:

```powershell
cd backend
pytest app/eval/tests/test_runner_smoke.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/eval/runner.py backend/app/eval/tests/test_runner_smoke.py
git commit -m "feat(eval): run claim-centered artifact pipeline"
```

---

### Task 9: Artifact and Claim Verdict Storage

**Files:**
- Modify: `backend/app/eval/storage.py`
- Modify: `backend/app/eval/tests/test_storage.py`
- Test: `backend/app/eval/tests/test_storage.py`

- [ ] **Step 1: Add failing storage assertions**

Modify `backend/app/eval/tests/test_storage.py` imports:

```python
from app.eval.artifacts import AtomicClaim, ClaimVerdict, EvalArtifact, EvidenceItem
```

In `test_storage_creates_schema`, update the expected tables:

```python
    assert {"eval_runs", "case_results", "evaluator_scores", "eval_artifacts", "claim_verdicts"}.issubset(tables)
```

In `test_storage_save_run_and_case`, add an artifact to `CaseResult`:

```python
        artifact=EvalArtifact(
            evidence=[EvidenceItem(id="f1", text="Sales grew.")],
            claims=[AtomicClaim(id="c1", text="Sales grew.", section_id="s1", citation_ids=["1"], requirement_ids=["r1"])],
            verdicts=[ClaimVerdict(claim_id="c1", supported=True, reason="supported", evidence_ids=["f1"])],
        ),
```

After reading `score_rows`, add:

```python
    artifact_rows = list(conn.execute(
        "SELECT case_id, artifact_json FROM eval_artifacts WHERE run_id='run-001'"
    ))
    assert artifact_rows[0][0] == "q001"
    claim_rows = list(conn.execute(
        "SELECT claim_id, supported, reason FROM claim_verdicts WHERE run_id='run-001' AND case_id='q001'"
    ))
    assert claim_rows == [("c1", 1, "supported")]
```

- [ ] **Step 2: Run storage tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_storage.py -v
```

Expected: FAIL because the new tables do not exist.

- [ ] **Step 3: Extend storage schema**

In `backend/app/eval/storage.py`, add to `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS eval_artifacts (
    run_id TEXT,
    case_id TEXT,
    artifact_json TEXT,
    PRIMARY KEY (run_id, case_id)
);

CREATE TABLE IF NOT EXISTS claim_verdicts (
    run_id TEXT,
    case_id TEXT,
    claim_id TEXT,
    section_id TEXT,
    claim_text TEXT,
    supported INTEGER,
    reason TEXT,
    evidence_ids_json TEXT,
    citation_ids_json TEXT,
    requirement_ids_json TEXT,
    importance TEXT,
    PRIMARY KEY (run_id, case_id, claim_id)
);
```

Add import:

```python
from app.eval.artifacts import artifact_to_dict
```

- [ ] **Step 4: Persist artifact and claim rows**

At the end of `save_case`, after evaluator rows are inserted, add:

```python
            artifact = case_result.artifact
            if artifact is not None:
                c.execute(
                    "INSERT OR REPLACE INTO eval_artifacts (run_id, case_id, artifact_json) VALUES (?, ?, ?)",
                    (run_id, c_id, json.dumps(artifact_to_dict(artifact), ensure_ascii=False)),
                )
                c.execute(
                    "DELETE FROM claim_verdicts WHERE run_id=? AND case_id=?",
                    (run_id, c_id),
                )
                verdict_by_claim = {v.claim_id: v for v in artifact.verdicts}
                for claim in artifact.claims:
                    verdict = verdict_by_claim.get(claim.id)
                    c.execute(
                        "INSERT INTO claim_verdicts "
                        "(run_id, case_id, claim_id, section_id, claim_text, supported, reason, evidence_ids_json, citation_ids_json, requirement_ids_json, importance) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            c_id,
                            claim.id,
                            claim.section_id,
                            claim.text,
                            1 if verdict and verdict.supported else 0,
                            verdict.reason if verdict else "missing verdict",
                            json.dumps(verdict.evidence_ids if verdict else [], ensure_ascii=False),
                            json.dumps(claim.citation_ids, ensure_ascii=False),
                            json.dumps(claim.requirement_ids, ensure_ascii=False),
                            claim.importance,
                        ),
                    )
```

- [ ] **Step 5: Run storage tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_storage.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/eval/storage.py backend/app/eval/tests/test_storage.py
git commit -m "feat(eval): persist artifacts and claim verdicts"
```

---

### Task 10: Grouped Reporter Diagnostics

**Files:**
- Modify: `backend/app/eval/reporter.py`
- Modify: `backend/app/eval/tests/test_reporter.py`
- Test: `backend/app/eval/tests/test_reporter.py`

- [ ] **Step 1: Write failing reporter diagnostic test**

Add to `backend/app/eval/tests/test_reporter.py`:

```python
from app.eval.artifacts import AtomicClaim, ClaimVerdict, EvalArtifact
```

Add test:

```python
def test_reporter_includes_claim_diagnostics(tmp_path: Path):
    case = make_case_result("q001", {"claim_support_rate": 5.0, "coherence": 8.0})
    case.artifact = EvalArtifact(
        claims=[
            AtomicClaim(id="c1", text="Unsupported market claim.", importance="high", citation_ids=["1"]),
            AtomicClaim(id="c2", text="Supported claim.", importance="medium", citation_ids=["2"]),
        ],
        verdicts=[
            ClaimVerdict(claim_id="c1", supported=False, reason="No matching evidence.", evidence_ids=[]),
            ClaimVerdict(claim_id="c2", supported=True, reason="Supported.", evidence_ids=["f1"]),
        ],
        errors=[],
    )
    r = Reporter(out_dir=str(tmp_path))
    paths = r.write(
        run_id="run-claim",
        suite="full",
        git_commit="abc",
        started_at=datetime(2026, 5, 26),
        finished_at=datetime(2026, 5, 26),
        case_results=[case],
        langsmith_url=None,
    )

    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "## Claim Diagnostics" in md
    assert "Unsupported market claim." in md
    assert "No matching evidence." in md
```

- [ ] **Step 2: Run reporter tests and verify they fail**

Run:

```powershell
cd backend
pytest app/eval/tests/test_reporter.py -v
```

Expected: FAIL because reporter has no claim diagnostics section.

- [ ] **Step 3: Add grouped score display**

In `backend/app/eval/reporter.py`, add near the top:

```python
_SCORE_GROUPS = {
    "Information Fidelity": [
        "claim_support_rate",
        "citation_verifiability",
        "relevance_coverage",
        "completeness",
    ],
    "Report Quality": [
        "coherence",
        "cohesion_structure",
        "analytical_depth",
        "professionalism_readability",
        "decision_usefulness",
    ],
    "Agentic / Operational": [
        "critic_loop_effectiveness",
        "cost",
        "latency",
    ],
}
```

Inside `_render_md`, after the existing `Overall Scores` table, append grouped summary tables:

```python
        md.append("## Score Groups")
        md.append("")
        rows_by_name = {r["name"]: r for r in rows}
        for group, names in _SCORE_GROUPS.items():
            md.append(f"### {group}")
            md.append("")
            md.append("| Metric | Mean | Median | Std | N |")
            md.append("|---|---|---|---|---|")
            for name in names:
                row = rows_by_name.get(name)
                if row:
                    md.append(f"| {name} | {row['mean']} | {row['median']} | {row['std']} | {row['n']} |")
            md.append("")
```

- [ ] **Step 4: Add claim diagnostics section**

Still inside `_render_md`, before failed cases, add:

```python
        claim_lines = []
        for c in ok_cases:
            artifact = c.artifact
            if artifact is None:
                continue
            verdict_by_claim = {v.claim_id: v for v in artifact.verdicts}
            for claim in artifact.claims:
                verdict = verdict_by_claim.get(claim.id)
                if verdict and not verdict.supported:
                    claim_lines.append(
                        f"- `{c.case.id}` / `{claim.id}` ({claim.importance}): {claim.text} Reason: {verdict.reason}"
                    )
        if claim_lines:
            md.append("## Claim Diagnostics")
            md.append("")
            md.extend(claim_lines[:20])
            md.append("")
```

- [ ] **Step 5: Run reporter tests**

Run:

```powershell
cd backend
pytest app/eval/tests/test_reporter.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/eval/reporter.py backend/app/eval/tests/test_reporter.py
git commit -m "feat(eval): report grouped scores and claim diagnostics"
```

---

### Task 11: Full Eval Test Sweep and Compatibility Cleanup

**Files:**
- Test: all `backend/app/eval/tests`

- [ ] **Step 1: Run the full eval test suite**

Run:

```powershell
cd backend
pytest app/eval/tests -v
```

Expected: PASS.

- [ ] **Step 2: Commit test-alignment changes from previous tasks**

```powershell
git add backend/app/eval backend/app/eval/tests
git commit -m "test(eval): align suite with claim-centered pipeline"
```

---

### Task 12: Documentation and Interview Brief Update

**Files:**
- Modify: `docs/eval-framework-interview-brief.md`
- Modify: `docs/superpowers/specs/2026-05-31-claim-centered-eval-pipeline-design.md`
- Test: documentation grep and full eval tests

- [ ] **Step 1: Update interview brief wording**

In `docs/eval-framework-interview-brief.md`, update the TL;DR to this content:

```markdown
I redesigned the eval framework for the deep-research multi-agent system around a claim-centered artifact. Each generated report is decomposed into atomic claims, claims are verified against the collected evidence index with binary supported/unsupported verdicts, and the same claim layer powers information fidelity, citation verifiability, relevance coverage, and completeness. Subjective report quality is scored with a weighted multi-judge rubric across coherence, structural cohesion, analytical depth, professional readability, and decision usefulness. The framework stores claim verdicts for auditability and marks high-variance judge dimensions as low confidence.
```

- [ ] **Step 2: Add implementation status to the spec**

In `docs/superpowers/specs/2026-05-31-claim-centered-eval-pipeline-design.md`, change status to:

```markdown
> Status: Implemented.
```

Add a short implementation note after the status block:

```markdown
> Implementation note: The shipped pipeline preserves the existing SQLite score tables and adds artifact/claim-verdict persistence for auditability.
```

- [ ] **Step 3: Verify docs no longer describe claim verification as a separate faithfulness score**

Run:

```powershell
rg -n "8th-evaluator|faithfulness-evaluator|separate-faithfulness-score" docs backend/app/eval
```

Expected: no matches.

- [ ] **Step 4: Run full eval tests**

Run:

```powershell
cd backend
pytest app/eval/tests -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add docs/eval-framework-interview-brief.md docs/superpowers/specs/2026-05-31-claim-centered-eval-pipeline-design.md
git commit -m "docs: update eval framework interview story"
```

---

## Final Verification

- [ ] Run eval tests:

```powershell
cd backend
pytest app/eval/tests -v
```

Expected: PASS.

- [ ] Run broader backend tests that are likely affected:

```powershell
cd backend
pytest app/eval/tests app/intent_eval/tests test/test_deep_research_v3 -v
```

Expected: PASS or only pre-existing unrelated failures. Record any unrelated failures with exact test names.

- [ ] Inspect git status:

```powershell
git status --short
```

Expected: clean worktree after final commit.

---

## Self-Review Notes

Spec coverage:

- EvalArtifact: Tasks 1, 2, 4, 5, 6.
- Claim extraction and binary verdicts: Task 4.
- Weighted multi-judge report rubrics: Tasks 3 and 5.
- Claim-centered metrics: Task 7.
- Runner migration: Task 8.
- Storage and auditability: Task 9.
- Reporter diagnostics: Task 10.
- Test coverage and documentation: Tasks 11 and 12.

Type consistency:

- `StructuredJudgeResult` is defined in `types.py` and used by judge clients and tests.
- `EvalArtifact` is defined in `artifacts.py` and attached to `CaseResult.artifact`.
- `MetricCalculator.calculate(ctx, artifact)` returns `list[EvalResult]`, preserving storage and reporter compatibility.

Execution order:

- Tasks 1-5 build independent units.
- Task 6 composes them.
- Task 7 calculates scores.
- Tasks 8-10 integrate with runner, storage, and reporter.
- Tasks 11-12 verify and document the shipped behavior.
