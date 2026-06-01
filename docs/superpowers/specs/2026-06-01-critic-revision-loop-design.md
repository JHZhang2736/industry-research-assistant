# Critic Revision Loop Design

> Date: 2026-06-01
> Scope: Improve runtime Critic loop observability and directed revision behavior in `backend/app/service/deep_research_v2/`.
> Status: Draft for review.

## 1. Goal

Fix the observed failure mode where three Critic reviews all return the same score, for example `4.5`, without visible improvement.

This spec implements two linked improvements:

- **A. Diagnostic observability**: make each Critic loop auditable. We should know whether the report actually changed, whether new evidence was added, which actions ran, and why the score moved or did not move.
- **B. Directed revision loop**: make Critic feedback actionable. Replanner should translate issues into section-level revision contexts, and Writer should revise with those contexts instead of doing generic `write_section` calls.

The design intentionally does not implement the full offline claim-centered evaluator upgrade. That remains separate under `2026-05-31-claim-centered-eval-pipeline-design.md`.

## 2. Current Diagnosis

The current runtime loop is structurally able to repeat without learning:

1. `CriticMaster.process()` reviews the current draft and emits `quality_score`, `verdict`, `critic_feedback`, `unresolved_issues`, and `suggested_actions`.
2. `route_after_critic()` routes to `replanner` when score is below threshold, verdict is not pass, unresolved issues exist, or actions exist.
3. `Replanner.process()` translates action strings such as `retry_search:sec_3` and `rewrite:sec_5` into new plan steps.
4. `executor_node()` runs the new plan and rebuilds `final_report` from `draft_sections`.
5. The next Critic review starts over.

The weak points:

- Critic does not receive prior review history or a diff, so it cannot judge whether previous issues improved.
- Replanner only passes action strings, not issue descriptions, acceptance criteria, or issue ids.
- Writer's v3 `write_one_section()` path uses the normal section writing prompt. It does not receive `critic_feedback`, previous section content, or required fixes.
- `_revise_report()` has feedback-aware behavior, but the Plan-and-Execute graph does not call it in the current v3 path.
- `critic_feedback.resolved` is defaulted to `False` and is not reliably updated by the v3 directed rewrite path.
- Issue ids are generated per Critic output. Without cross-round issue matching, the system cannot tell whether a later issue is a new issue or the same unresolved issue restated.
- There is no structured score history or per-round artifact to distinguish "upstream made no change" from "upstream improved but critic calibration is stuck".
- Pass threshold is split across code paths: `graph.py` uses `QUALITY_PASS_THRESHOLD = 7.0`, while `llm_config.py` has `quality_threshold = 6.0`. The runtime loop should have one authoritative threshold.

Working hypothesis:

> The repeated 4.5 is mainly caused by an incomplete feedback loop. Critic may also be poorly calibrated, but the first root-cause target is that feedback does not become targeted revision instructions.

## 3. Industry Patterns To Borrow

OpenAI's eval guidance emphasizes defining objectives, datasets, metrics, run comparison, and continuous evaluation. It also notes that LLMs are stronger at discriminating between options, so pairwise comparison and scoring against specific criteria are usually more reliable than open-ended judgment.

OpenAI grader docs also warn about grader or reward hacking: a model can learn to score well on an automated grader while doing poorly under expert human evaluation.

LangSmith's evaluator model separates offline and online evaluators, supports LLM-as-judge, code evaluators, feedback schemas, pairwise comparison, and human corrections used as few-shot examples. The useful pattern for this project is to make each feedback key explicit and structured.

Anthropic's evaluation guidance recommends task-specific tests, automated evaluation where possible, clear rubrics, empirical or bounded scales, and asking the judge to reason before outputting the final score.

Research context:

- Self-Refine shows iterative feedback and refinement can improve outputs at test time.
- Reflexion shows language agents can use verbal feedback in memory to improve subsequent trials.
- Reward hacking work warns that iterative self-refinement with an imperfect evaluator can raise evaluator scores while user-perceived quality stagnates or worsens.
- MT-Bench / Chatbot Arena popularized LLM-as-judge for open-ended tasks but also motivated using judge calibration, pairwise comparison, and bias checks.

References:

- OpenAI evaluation best practices: https://developers.openai.com/api/docs/guides/evaluation-best-practices
- OpenAI graders: https://developers.openai.com/api/docs/guides/graders/
- LangSmith LLM-as-judge evaluator: https://docs.langchain.com/langsmith/llm-as-judge
- LangSmith evaluation concepts: https://docs.langchain.com/langsmith/evaluation-concepts
- Anthropic evaluation guidance: https://platform.claude.com/docs/en/test-and-evaluate/develop-tests
- Self-Refine: https://arxiv.org/abs/2303.17651
- Reflexion: https://arxiv.org/abs/2303.11366
- Spontaneous Reward Hacking in Iterative Self-Refinement: https://arxiv.org/abs/2407.04549
- Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena: https://arxiv.org/abs/2306.05685

## 4. Non-Goals

- Do not replace the production Critic with the offline claim-centered eval pipeline.
- Do not introduce a second LLM judge into the runtime loop in this phase.
- Do not add human labeling workflows in this phase.
- Do not redesign Planner or the whole PlanStep schema beyond fields needed for revision context.
- Do not change frontend UI unless existing events are insufficient for debugging.

## 5. Design Overview

Add a small runtime feedback artifact:

```text
executor -> critic
             |
             v
      review_history append
             |
             v
        replanner creates revision_context_by_section
             |
             v
      executor runs search/analyze/write with revision context
             |
             v
      writer returns addressed_issue_ids + section content
             |
             v
      graph marks resolved candidates and records diff
```

The core change is not more loops. It is better information transfer per loop.

## 6. State Additions

Add these optional fields to `ResearchState` for v3 runtime:

```python
review_history: list[dict]
revision_context_by_section: dict[str, dict]
critic_diagnostics: list[dict]
```

They are JSON-serializable and checkpoint-friendly.

### 6.1 Review History

Each Critic run appends:

```json
{
  "review_id": "review_abc123",
  "round": 0,
  "quality_score": 4.5,
  "verdict": "needs_revision",
  "dimension_scores": {
    "factual_support": 4,
    "citation_integrity": 3,
    "coverage": 5,
    "reasoning": 5,
    "freshness": 4,
    "actionability": 6
  },
  "issue_ids": ["issue_1", "issue_2"],
  "suggested_actions": ["retry_search:sec_3", "rewrite:sec_3"],
  "input_snapshot": {
    "final_report_hash": "sha256:...",
    "draft_hash_by_section": {"sec_3": "sha256:..."},
    "facts_count": 120,
    "data_points_count": 10,
    "references_count": 40
  },
  "delta_from_previous": {
    "final_report_changed": true,
    "changed_sections": ["sec_3"],
    "new_facts_count": 8,
    "new_references_count": 3,
    "score_delta": 0.0
  },
  "summary": "..."
}
```

### 6.2 Revision Context

`revision_context_by_section` is produced by Replanner and consumed by Writer:

```json
{
  "sec_3": {
    "section_id": "sec_3",
    "mode": "rewrite_with_feedback",
    "source_review_id": "review_abc123",
    "issues": [
      {
        "id": "issue_1",
        "issue_type": "missing_source",
        "severity": "major",
        "description": "...",
        "suggestion": "...",
        "acceptance_criteria": [
          "Add at least one cited source for the market-size claim",
          "Remove unsupported numeric claim if no source is found"
        ]
      }
    ],
    "required_actions": ["retry_search", "rewrite"],
    "previous_content_hash": "sha256:..."
  }
}
```

The context should be compact. Do not pass the full report into every section rewrite.

## 7. Critic Changes

### 7.1 Structured Scoring

Replace the single free-form score with structured dimensions, then derive `quality_score` deterministically:

| Dimension | Weight | Meaning |
|---|---:|---|
| factual_support | 0.30 | Claims are grounded in facts and evidence |
| citation_integrity | 0.20 | Inline citations exist, point to usable sources, and support the nearby claim |
| coverage | 0.15 | Report covers the outline and user query |
| reasoning | 0.15 | Argument flow is coherent and not contradictory |
| freshness | 0.10 | Time-sensitive claims use current or clearly dated data |
| actionability | 0.10 | Feedback is specific enough for Replanner and Writer |

`quality_score = weighted_mean(dimension_scores)`.

This makes repeated `4.5` explainable. If the final score stays flat, we can inspect which dimension is pinned.

### 7.2 Issue Schema

Extend each feedback item:

```json
{
  "id": "issue_xxx",
  "target_section": "sec_3",
  "issue_type": "missing_source",
  "severity": "major",
  "description": "...",
  "suggestion": "...",
  "acceptance_criteria": ["..."],
  "requires_new_search": true,
  "search_queries": ["..."],
  "resolved": false
}
```

`acceptance_criteria` is required for all `critical` and `major` issues.

### 7.3 Issue Continuity

Critic should receive unresolved issues from the previous review and map them explicitly:

```json
{
  "same_as_issue_id": "issue_old_123",
  "id": "issue_old_123",
  "status": "still_unresolved"
}
```

If the issue is materially the same, keep the same `id`. If the issue is new, generate a new id. If the old issue is resolved, list it under `resolved_issue_ids`.

### 7.4 Review Diff Awareness

Critic receives a compact previous-review summary:

- previous score and dimension scores
- previous unresolved issue ids and summaries
- changed sections since previous review
- facts/references deltas

Critic should output:

```json
{
  "resolved_issue_ids": ["issue_1"],
  "still_unresolved_issue_ids": ["issue_2"],
  "new_issue_ids": ["issue_3"]
}
```

This does not mean Critic blindly trusts Writer's `addressed_issue_ids`. Critic still verifies whether acceptance criteria were actually met.

## 8. Replanner Changes

Replanner remains deterministic and low-cost.

Inputs:

- `critic_feedback`
- `suggested_actions`
- `review_id`
- current `outline`
- current `draft_sections`

Outputs:

- `plan`
- `replan_count`
- `revision_context_by_section`

Mapping rules:

| Issue/action | Plan |
|---|---|
| `missing_source`, `outdated`, `incomplete` | `search_section` then `write_section` for target section |
| `add_data` | `search_section`, `analyze_facts`, then `write_section` |
| `logic_error`, `bias`, `hallucination` | `write_section` with revision context |
| global issue with clear target sections | fan out to those sections |
| global issue without section target | create `rewrite:global` only if a global writer path exists, otherwise split by top issues' sections |

When Critic forgets `suggested_actions`, the existing fallback should derive actions from feedback, but it must also build revision context. The fallback should not silently retry all sections unless there is no targetable issue.

## 9. Writer Changes

`LeadWriter.write_one_section()` should check:

```python
revision_context = state.get("revision_context_by_section", {}).get(section_id)
```

If present, use a new `REVISION_SECTION_PROMPT` instead of the normal `SECTION_WRITING_PROMPT`.

Prompt inputs:

- query
- section title and description
- previous section content
- relevant critic issues
- acceptance criteria
- newly available facts for this section
- existing related facts/data/charts

Output:

```json
{
  "content": "revised section markdown",
  "changes_made": ["..."],
  "addressed_issue_ids": ["issue_1"],
  "unable_to_address": [
    {"issue_id": "issue_2", "reason": "no source found"}
  ],
  "citations": [{"source": "...", "url": "..."}]
}
```

Writer may mark an issue as addressed only when it directly changed content to satisfy an acceptance criterion. It should not mark an issue addressed merely because it rewrote the section.

## 10. Executor And Merge Behavior

`executor_node()` already merges `write_section` outputs into `draft_sections`.

Enhance merge behavior for `write_section` results:

- collect `addressed_issue_ids`
- collect `unable_to_address`
- record per-section before/after content hashes
- append a diagnostic event to `critic_diagnostics`

Do not set `critic_feedback.resolved=True` solely from Writer output. Instead:

- Writer output marks `candidate_addressed=True`.
- Next Critic run confirms and sets `resolved=True` through `resolved_issue_ids`.

This prevents writer optimism from hiding unresolved problems.

## 11. Routing And Stop Conditions

Keep `MAX_REPLAN = 3`, but add loop-progress checks. Also consolidate the pass threshold into one source of truth. Prefer `config.research.quality_threshold`, with default set to `7.0` unless the product decision is to allow a lower bar.

- If `quality_score` does not improve by at least `0.3` across two consecutive Critic runs and changed sections are empty, stop and return diagnostic `no_effective_revision`.
- If Critic asks for new search but no new facts were added in the last round, prefer `rewrite_without_claim` or remove unsupported claims rather than repeating the same search.
- If all remaining issues are `minor` and score is within `0.2` of the configured pass threshold, allow pass with warnings.
- If score is below threshold but no targetable issue exists, fail closed with a diagnostic rather than retrying all sections blindly.

`research_complete` should include:

```json
{
  "quality_score": 6.9,
  "iterations": 2,
  "critic_loop_status": "passed_with_minor_warnings",
  "unresolved_issues": 1
}
```

## 12. Diagnostics To Add First

Before changing behavior, add enough diagnostics to answer:

1. Did `final_report` change between reviews?
2. Which section changed?
3. Did new facts or references arrive?
4. Did suggested actions produce any executable plan steps?
5. Did `write_section` output new content or the same content?
6. Which dimension score stayed flat?

Minimal implementation:

- helper `_hash_text(text: str) -> str`
- helper `_build_review_input_snapshot(state) -> dict`
- helper `_build_review_delta(previous, current) -> dict`
- append `review_history`
- include `review_id` in logs and LangSmith metadata where possible

This is Phase A and should land before Phase B behavior changes.

## 13. Tests

Add focused tests before implementation.

### 13.1 State tests

- `create_initial_state()` includes `review_history`, `revision_context_by_section`, and `critic_diagnostics`.

### 13.2 Critic tests

- mocked Critic response with `dimension_scores` produces deterministic weighted `quality_score`.
- Critic fills ids and `resolved=False` for new feedback.
- Critic preserves ids for repeated unresolved issues when previous issue context is provided.
- Critic appends a `review_history` entry with hashes and deltas.
- Critic rejects or repairs inconsistent output where `verdict != pass` but no action or issue exists.

### 13.3 Replanner tests

- `missing_source` feedback creates `search_section` then `write_section`, with `write_section` depending on search.
- `logic_error` feedback creates `write_section` only.
- empty `suggested_actions` but targetable feedback still creates revision context.
- unknown target section is logged and skipped.

### 13.4 Writer tests

- normal section with no revision context uses normal prompt.
- section with revision context uses revision prompt and includes acceptance criteria.
- returned `addressed_issue_ids` are propagated in tool output.

### 13.5 Executor/Graph tests

- write output with `addressed_issue_ids` records candidate addressed diagnostics.
- next Critic run can confirm resolved issue ids and update feedback.
- repeated no-change rounds stop with `no_effective_revision`.

## 14. Rollout Plan

1. Add state fields and diagnostics only.
2. Run a mocked graph test to confirm history and deltas are recorded.
3. Add Replanner revision context generation.
4. Add Writer revision prompt and output propagation.
5. Add Critic dimension scoring and resolved issue confirmation.
6. Run targeted tests.
7. Run one manual/smoke research case and inspect review history:
   - score should move, or diagnostics should explain why it did not.
   - changed sections should match target sections.
   - unsupported claims should be removed or cited, not looped forever.

## 15. Acceptance Criteria

The implementation is accepted when:

- Each Critic loop has a `review_history` entry with score, dimensions, snapshot, and delta.
- A low-score Critic result creates targetable revision contexts for affected sections.
- Writer receives Critic issue context during rewrite and returns `addressed_issue_ids`.
- Resolved status is confirmed by Critic, not blindly trusted from Writer.
- A repeated score, such as `4.5 -> 4.5 -> 4.5`, produces a clear diagnostic explaining whether the report changed, whether evidence changed, and which score dimensions were stuck.
- Existing mock tests remain offline and do not require LLM or search network calls.

## 16. Expected Impact

This design should make the Critic loop a real control loop rather than a repeated reviewer:

- Debuggability improves immediately through review history and hash deltas.
- Revisions become targeted to concrete issue ids and acceptance criteria.
- Scores become decomposable by dimension.
- Empty or ineffective replans stop early instead of spending all iterations.
- The project becomes easier to explain in interviews: "Critic emits structured, testable feedback; Replanner turns it into deterministic repair plans; Writer performs issue-aware edits; Critic confirms resolution."
