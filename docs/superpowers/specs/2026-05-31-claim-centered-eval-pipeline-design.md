# Claim-Centered Eval Pipeline Design

> Date: 2026-05-31
> Scope: Redesign `backend/app/eval/` into a claim-centered evaluation pipeline for industry research reports.
> Status: Design approved for implementation planning.

## 1. Resume Target

The implementation should make this resume point truthful:

> Built a claim-centered LLM-as-a-Judge evaluation framework for industry research reports. The pipeline decomposes reports into atomic claims, verifies each claim with binary evidence-grounded verdicts, and uses weighted multi-judge rubrics to quantify information fidelity and report quality, including relevance, coherence, structural cohesion, completeness, analytical depth, professional readability, and decision usefulness.

This means claim decomposition is not a standalone `faithfulness` add-on. It is the shared intermediate layer that powers the whole report evaluation chain.

## 2. Current Problem

The existing eval framework has useful pieces:

- 7 evaluators: relevance, coherence, citation, completeness, critic loop, cost, latency.
- 3 judge families: DeepSeek, MiMo, Qwen.
- SQLite persistence and Markdown/CSV reports.
- A working runner that executes research, loads final state, evaluates, stores, and reports.

But the current design has weak coupling between the metrics:

- `relevance`, `coherence`, and `completeness` are independent subjective LLM scores.
- `citation` checks citation syntax and URL reachability, but not whether a cited source supports the actual claim.
- Report quality is under-specified. `coherence` alone is too narrow for industry research reports.
- There is no shared claim/evidence representation, so the framework cannot explain exactly which statements are unsupported, irrelevant, or insufficiently covered.

## 3. Goal

Redesign the eval chain around a shared `EvalArtifact` built once per case after the research run completes.

The artifact contains:

- normalized evidence from `facts`, `references`, and `raw_sources`
- parsed report sections and citations
- query requirements
- atomic report claims
- binary claim verdicts against evidence
- multi-dimensional report quality judge results

All report metrics should read from this artifact. Cost and latency remain operational metrics and do not need claim inputs.

## 4. Non-Goals

- Do not change the production research workflow under `backend/app/service/deep_research_v2/**`.
- Do not block report generation based on eval output.
- Do not add human-labeled reference answers.
- Do not call a judge once per claim in the first implementation.
- Do not directly use IELTS-like names such as `Lexical Resource` or `Grammatical Range & Accuracy`; adapt them into research-report rubrics.

## 5. High-Level Pipeline

```text
EvalRunner
  -> run research service
  -> load final ResearchState
  -> build EvalArtifact
       -> EvidenceIndex
       -> ReportStructure
       -> QueryRequirements
       -> ClaimSet
       -> ClaimVerdicts
       -> ReportQualityRubricScores
  -> calculate metrics from EvalArtifact
  -> persist scores + artifact details
  -> render Markdown/CSV report
  -> optional LangSmith upload
```

This changes the evaluator model from "independent scorers over raw state" to "artifact builders plus metric calculators".

## 6. EvalArtifact

Add a new artifact model in `backend/app/eval/artifacts.py`.

Recommended dataclasses:

```python
@dataclass
class EvidenceItem:
    id: str
    text: str
    source_name: str
    source_url: str
    source_type: str
    credibility_score: float | None = None

@dataclass
class ReportSection:
    id: str
    title: str
    text: str
    citation_ids: list[str]

@dataclass
class QueryRequirement:
    id: str
    text: str
    importance: str  # high | medium | low

@dataclass
class AtomicClaim:
    id: str
    text: str
    section_id: str | None
    importance: str
    citation_ids: list[str]
    requirement_ids: list[str]

@dataclass
class ClaimVerdict:
    claim_id: str
    supported: bool
    reason: str
    evidence_ids: list[str]
    confidence: str  # high | medium | low

@dataclass
class ReportQualityScores:
    coherence: float | None
    cohesion_structure: float | None
    analytical_depth: float | None
    professionalism_readability: float | None
    decision_usefulness: float | None
    raw_judge_outputs: list[dict]
    std_by_dimension: dict[str, float]
    low_confidence_dimensions: list[str]

@dataclass
class EvalArtifact:
    evidence: list[EvidenceItem]
    sections: list[ReportSection]
    requirements: list[QueryRequirement]
    claims: list[AtomicClaim]
    verdicts: list[ClaimVerdict]
    quality: ReportQualityScores
```

## 7. Artifact Builders

Create a package:

```text
backend/app/eval/artifact_builders/
  __init__.py
  evidence.py
  report_structure.py
  claim_extraction.py
  claim_verification.py
  report_quality.py
```

### EvidenceIndexBuilder

Builds evidence from:

- `state["facts"]`: primary evidence
- `state["references"]`: fallback source metadata
- `state["raw_sources"]`: optional snippets when available

Deduplicate by `(source_url, normalized text prefix)`. Keep the first `MAX_EVIDENCE_ITEMS`.

### ReportStructureParser

Parses the Markdown report into sections and extracts citation ids:

- `##` and `###` headings become section boundaries.
- Citation patterns include `[1]`, `[1,2]`, and `[1-3]`.
- The parser should ignore the final reference list when building factual sections.

### ClaimExtractionBuilder

One structured LLM call extracts:

- query requirements
- atomic claims
- claim-to-requirement mappings when obvious

Input:

- user query
- report sections
- maximum claims

Output JSON:

```json
{
  "requirements": [
    {"id": "r1", "text": "User need", "importance": "high"}
  ],
  "claims": [
    {
      "id": "c1",
      "text": "Atomic factual claim",
      "section_id": "s1",
      "importance": "high",
      "citation_ids": ["1"],
      "requirement_ids": ["r1"]
    }
  ]
}
```

This borrows the Ragas-style claim decomposition idea but adapts it to report evaluation.

### ClaimVerificationBuilder

One structured LLM call verifies all extracted claims against the evidence index.

Input:

- claims
- compact evidence list

Output JSON:

```json
{
  "verdicts": [
    {
      "claim_id": "c1",
      "supported": true,
      "reason": "Short Chinese reason",
      "evidence_ids": ["f1"],
      "confidence": "high"
    }
  ]
}
```

Unsupported includes missing evidence, contradictory evidence, vague support, and unsupported numerical or temporal details.

### ReportQualityJudge

One prompt per judge returns multiple report-quality dimensions in one JSON object. With 3 judge families this is 3 parallel calls per case, not one call per metric.

Dimensions:

- `coherence`: logical consistency and whether conclusions follow from prior analysis.
- `cohesion_structure`: section organization, transitions, and paragraph flow.
- `analytical_depth`: causal explanation, tradeoff analysis, trend interpretation, risks and opportunities.
- `professionalism_readability`: terminology precision, concise professional wording, low grammar/noise burden.
- `decision_usefulness`: whether the report helps a reader make investment, strategy, market-entry, or product decisions.

Output JSON:

```json
{
  "coherence": {"score": 8.0, "reasoning": "..."},
  "cohesion_structure": {"score": 7.5, "reasoning": "..."},
  "analytical_depth": {"score": 8.2, "reasoning": "..."},
  "professionalism_readability": {"score": 8.6, "reasoning": "..."},
  "decision_usefulness": {"score": 7.8, "reasoning": "..."}
}
```

This replaces a narrow single `coherence` judge with a research-report quality rubric.

## 8. LLM Call Budget

Default per case:

- Claim extraction: 1 primary structured call.
- Claim verification: 1 primary structured call.
- Report quality rubric: 3 structured calls, one per judge family, run in parallel.

Total: 5 LLM calls per case.

This is cheaper and more coherent than the old pattern of separately judging relevance, coherence, and completeness with 3 judges each.

Optional future mode:

- Run multi-judge verification only for high-importance unsupported claims or low-confidence cases.

## 9. Weighted Multi-Judge Ensemble

Extend judge support for structured rubric outputs.

Add a weighted aggregator:

```python
weights = {
    "deepseek": 0.4,
    "qwen": 0.4,
    "mimo": 0.2,
}
```

For each report-quality dimension:

- weighted mean is the main score
- median is retained for robustness
- standard deviation marks low confidence
- failed judge outputs are skipped and recorded as `partial=True`

The first implementation should use these configured default weights and keep them overridable in settings. The weights are heuristic, but explicit weighting makes the ensemble behavior real and auditable.

## 10. Metrics Calculated From EvalArtifact

Metrics should be grouped by purpose rather than by implementation mechanism.

### Information Fidelity

Computed from claim verdicts:

```text
claim_support_rate = supported_claims / total_claims * 10
```

This is the core information fidelity score, not a standalone side metric.

### Citation Verifiability

Computed from claims with citations:

- Does the claim cite at least one source?
- Does the cited source id exist?
- Does the verdict evidence overlap with cited source evidence?

Score combines:

- citation presence rate
- known citation id rate
- cited-evidence support rate

This replaces the current citation evaluator's URL/syntax-heavy scoring as the main citation quality signal. URL reachability can remain as metadata.

### Relevance Coverage

Computed from query requirements and claims:

```text
relevance_coverage = covered_high_weight_requirements / total_high_weight_requirements * 10
```

A requirement is covered when at least one supported claim maps to it. If extraction cannot map requirements, use a fallback LLM mapping inside the claim extraction prompt output rather than a separate metric call.

### Completeness

Computed from sections, outline, and supported claims:

- section coverage: each required outline section has enough supported claims
- evidence-backed density: claims per section are supported by evidence
- missing-section penalty: outline sections without report sections or supported claims reduce the score

This makes completeness less subjective and more explainable.

### Report Quality Rubrics

Taken from weighted multi-judge rubric scores:

- coherence
- cohesion_structure
- analytical_depth
- professionalism_readability
- decision_usefulness

These are subjective quality metrics where LLM judge is appropriate.

### Agentic Quality

Critic loop score remains agentic, but should use claim verdicts when available:

- resolved critic feedback rate
- unsupported high-importance claim count
- overlap between critic issues and unsupported/missing claims

If the checkpoint lacks pre-revision claim snapshots, the first implementation uses final-state verdicts plus existing `critic_feedback.resolved`.

### Operational Metrics

Cost and latency remain unchanged:

- cost from `state["logs"]`
- latency from runner timestamps and stage logs

## 11. Score Output

The final report should show score groups:

```text
Information Fidelity
  - claim_support_rate
  - citation_verifiability
  - relevance_coverage
  - completeness

Report Quality
  - coherence
  - cohesion_structure
  - analytical_depth
  - professionalism_readability
  - decision_usefulness

Agentic / Operational
  - critic_loop_effectiveness
  - cost
  - latency
```

This satisfies "information fidelity and report quality" without making faithfulness a bolt-on metric.

## 12. Runner Changes

Replace this shape:

```python
results = await asyncio.gather(
    *[ev.evaluate(ctx, self.judge) for ev in self.evaluators]
)
```

With:

```python
artifact = await self.artifact_builder.build(ctx, self.judge)
results = self.metric_calculator.calculate(ctx, artifact)
```

The metric calculator may still return `list[EvalResult]` so storage and reporter changes stay bounded.

Recommended modules:

```text
backend/app/eval/artifact_builder.py
backend/app/eval/metric_calculator.py
```

Keep old evaluator classes only if they are reused internally. `build_all_evaluators()` should stop being the main orchestration point after this redesign.

## 13. Storage

Keep `evaluator_scores` for top-level metric scores.

Add:

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

This makes unsupported claims inspectable without digging through nested metadata.

## 14. Reporter

Markdown output should add:

- grouped score table
- low-confidence judge dimensions
- top unsupported high-importance claims
- citation support failures
- requirement coverage gaps
- section completeness gaps

CSV output can stay flat, with one column per metric.

## 15. Error Handling

Artifact building must be fail-soft:

- If claim extraction fails, claim-based metrics return `score=None` with errors, but cost/latency can still be recorded.
- If claim verification fails, claim-based metrics return `score=None`.
- If one quality judge fails, weighted rubric uses remaining judges and marks `partial=True`.
- If all quality judges fail, report-quality metrics return `score=None`.

The runner should never fail an entire case solely because one eval stage failed, unless no metrics can be produced.

## 16. Testing Strategy

No test calls real LLM APIs.

Add unit tests for:

- evidence deduplication and formatting
- markdown section/citation parsing
- claim extraction JSON parsing, including fenced JSON
- claim verification parsing and missing verdict handling
- metric formulas for claim support, citation verifiability, relevance coverage, completeness
- weighted multi-judge rubric aggregation, including failed judges and high variance
- artifact storage and claim verdict storage
- reporter diagnostics for unsupported claims and coverage gaps
- runner smoke test: research state -> artifact -> metrics -> storage/report

Regression tests should keep existing cost, latency, and critic-loop behavior working.

## 17. Migration Plan

1. Add artifact dataclasses and pure parsers.
2. Add structured judge call support.
3. Add artifact builder with mocked tests.
4. Add metric calculator that returns existing `EvalResult` objects.
5. Update runner to build artifact before calculating metrics.
6. Update storage for artifacts and claim verdicts.
7. Update reporter grouped output.
8. Keep the old evaluator tests passing where behavior is retained, then replace tests that no longer match the redesigned pipeline.

## 18. Interview Story

The strongest explanation:

"The old eval was a set of independent LLM scores, so it could tell me a report was probably good but not which facts were unsupported. I redesigned it around a claim artifact. Each report is decomposed into atomic claims, those claims are verified against collected evidence with binary verdicts, and then relevance, completeness, citation quality, and information fidelity are calculated from the same evidence-grounded layer. For subjective report quality, I use a multi-judge rubric that scores coherence, structure, analytical depth, professional readability, and decision usefulness in one pass per judge, then aggregates with weights and variance-based low-confidence flags."

That story directly matches the resume point and is defensible in code.
