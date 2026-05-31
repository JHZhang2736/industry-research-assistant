# Eval Framework Interview Brief

> Purpose: interview notes for the claim-centered evaluation framework in `backend/app/eval/`.
> Status: implemented on branch `codex/claim-centered-eval-pipeline`.
> Scope: eval-only. The production research flow under `backend/app/service/deep_research_v2/**` is not changed.

---

## TL;DR

I redesigned the eval framework for the deep-research multi-agent system around a claim-centered artifact. Each generated report is decomposed into atomic claims, claims are verified against the collected evidence index with binary supported/unsupported verdicts, and the same claim layer powers information fidelity, citation verifiability, relevance coverage, and completeness. Subjective report quality is scored with a weighted multi-judge rubric across coherence, structural cohesion, analytical depth, professional readability, and decision usefulness. The framework stores claim verdicts for auditability and marks high-variance judge dimensions as low confidence.

---

## Why This Exists

The original smoke tests only answered whether the multi-agent research flow finished. They did not answer whether the report was grounded, complete, useful, or internally coherent.

The redesign turns each finished research run into an auditable eval artifact:

1. Normalize collected evidence from facts, references, and raw sources.
2. Parse the final report into sections and citations.
3. Extract query requirements and atomic report claims.
4. Verify each claim against evidence with a binary verdict.
5. Score report quality with a weighted multi-judge rubric.
6. Calculate final metrics from the artifact.
7. Persist both top-level scores and claim-level diagnostics.

The key design choice is that claim decomposition is the shared intermediate representation for the core report-evaluation chain.

---

## Current Pipeline

```text
EvalRunner
  -> run research service
  -> load final ResearchState
  -> EvalArtifactBuilder.build(ctx, judge)
       -> EvidenceIndexBuilder
       -> parse_report_sections
       -> ClaimExtractionBuilder
       -> ClaimVerificationBuilder
       -> ReportQualityBuilder
  -> MetricCalculator.calculate(ctx, artifact)
  -> EvalStorage.save_case(..., artifact=artifact)
  -> Reporter.write(...) with score groups and claim diagnostics
  -> LangSmithAdapter upload, fail-open
```

The runner now evaluates through `EvalArtifactBuilder` and `MetricCalculator`, not through independent scorer classes as the main path.

---

## Metrics

Information fidelity:

| Metric | Source | Meaning |
|---|---|---|
| `claim_support_rate` | claim verdicts | Share of high-confidence claims supported by evidence |
| `citation_verifiability` | claims, citations, verdict evidence IDs | Whether cited claims use known citations and overlap with supporting evidence |
| `relevance_coverage` | claim requirement IDs | Query requirements covered by extracted claims |
| `completeness` | supported claims and high-importance requirements | Important requirements covered by supported claims |

Report quality:

| Metric | Source | Meaning |
|---|---|---|
| `coherence` | weighted multi-judge rubric | Logical consistency and flow |
| `cohesion_structure` | weighted multi-judge rubric | Section structure and transitions |
| `analytical_depth` | weighted multi-judge rubric | Quality of reasoning and synthesis |
| `professionalism_readability` | weighted multi-judge rubric | Business-report tone and readability |
| `decision_usefulness` | weighted multi-judge rubric | Practical value for decisions |

Agentic and operational:

| Metric | Source | Meaning |
|---|---|---|
| `critic_loop` / `critic_loop_effectiveness` | critic feedback | Resolution rate of critic feedback |
| `cost` | model logs | Estimated RMB cost from token usage |
| `latency` | eval context duration and logs | Total latency and per-agent timing |

`critic_loop` is preserved as a backward-compatible score name; `critic_loop_effectiveness` is the clearer framework-facing name.

---

## Judge Strategy

The framework keeps the multi-judge setup to reduce single-model bias:

- Structured claim extraction and verification use judge structured-output calls.
- Report quality uses weighted outputs from multiple judge families.
- High standard deviation across judges marks a dimension as low confidence.
- Partial failures are preserved instead of crashing the whole eval case.

The implementation stores raw judge outputs and low-confidence flags so an interviewer can see both the aggregate score and why it may need review.

---

## Persistence And Auditability

SQLite keeps the existing top-level score tables and adds artifact-level diagnostics:

```sql
eval_runs(run_id, suite, started_at, finished_at, git_commit, config_json)
case_results(run_id, case_id, query, final_report, quality_score, duration_sec, total_tokens, cost_rmb, error)
evaluator_scores(run_id, case_id, evaluator_name, score, raw_judge_outputs_json, std, low_confidence, metadata_json)
eval_artifacts(run_id, case_id, artifact_json)
claim_verdicts(run_id, case_id, claim_id, section_id, claim_text, supported, reason, evidence_ids_json, citation_ids_json, requirement_ids_json, importance)
```

This matters for interviews because the framework can explain a score with concrete unsupported claims and the evidence IDs used to judge them.

---

## Reporter Output

Markdown reports now include:

- Overall score table.
- Score groups: information fidelity, report quality, and agentic/operational metrics.
- Per-case metric table.
- Low-confidence judge dimensions.
- Claim diagnostics for unsupported claims, capped for readability.

CSV output remains compatible with existing score aggregation.

---

## Pre-Redesign Baseline

Before this redesign, the framework had useful standalone evaluators for relevance, coherence, citation syntax, completeness, critic loop, cost, and latency. That baseline was enough to catch early production issues:

- Writer reports lacked numeric citations.
- Critic feedback was not being resolved because the revision loop was too short.
- Token logs were missing, so cost looked like zero.

Those findings are still a good engineering story, but the current resume claim should focus on the shipped claim-centered pipeline rather than the earlier baseline design.

---

## What To Say In Interviews

**Q: Why claim decomposition?**

A: It turns a long report into auditable atomic units. Once claims exist, the framework can score support, citation verifiability, relevance, and completeness from one shared layer instead of asking unrelated judges to score the whole report independently.

**Q: Why binary verdicts?**

A: Binary supported/unsupported verdicts are easier to audit and aggregate than vague hallucination scores. The confidence and reason fields still preserve nuance, but the metric layer gets a stable decision.

**Q: Why not just use Ragas?**

A: The claim decomposition idea is inspired by Ragas-style faithfulness checks, but this project is not a single-turn RAG pipeline. It is a multi-agent research workflow with facts, references, report sections, critic feedback, cost, and latency. I reused the useful idea and adapted the architecture around the project data model.

**Q: Why multiple report-quality dimensions?**

A: Coherence alone is too narrow for an industry research report. Structural cohesion, analytical depth, professional readability, and decision usefulness capture whether the report is actually useful to a business reader.

**Q: How do you handle judge disagreement?**

A: I aggregate weighted judge scores, keep raw outputs, compute variance, and mark high-variance dimensions as low confidence instead of hiding disagreement behind one average.

**Q: What proves the system is auditable?**

A: Every run stores the full `EvalArtifact` and a flattened `claim_verdicts` table. If a score drops, I can inspect unsupported claims, cited evidence IDs, matched requirements, judge outputs, and reporter diagnostics.

---

## Current Verification Snapshot

- Full eval suite: `105 passed`.
- Key integration test: runner smoke builds artifacts, calls structured judges, calculates metrics, stores cases, and emits grouped reports.
- Production research code path: unchanged by this eval redesign.

---

## Resume Bullet

Built a claim-centered LLM-as-a-Judge evaluation framework for industry research reports, decomposing reports into atomic claims, verifying evidence support with binary verdicts, and aggregating weighted multi-judge rubrics for information fidelity, citation verifiability, requirement coverage, completeness, and report-quality dimensions; persisted claim verdicts for auditability and surfaced low-confidence judge disagreement in reports.
