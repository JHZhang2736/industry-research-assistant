# Claim Faithfulness Eval Design

> Date: 2026-05-31
> Scope: Add a lightweight Ragas-style claim decomposition + binary verdict faithfulness evaluator under `backend/app/eval/`.
> Status: Design approved for lightweight implementation.

## 1. Goal

Add an eval-only information faithfulness metric for generated research reports. The metric should decompose the final report into atomic claims, verify each claim against collected evidence, and score the report by the ratio of supported claims.

This feature exists only in the automated eval framework. It must not change the production research workflow, report generation path, or user-facing API behavior.

## 2. Non-Goals

- Do not modify `backend/app/service/deep_research_v2/**`.
- Do not block or revise report generation based on faithfulness scores.
- Do not introduce per-claim multi-judge calls in the first implementation.
- Do not replace the existing 7 evaluators.
- Do not add a reference-answer dataset or human annotation workflow.

## 3. Approach

Implement a new `FaithfulnessEvaluator` as the 8th evaluator in `backend/app/eval/evaluators/`.

The evaluator uses two LLM calls per case:

1. Claim decomposition: report text -> atomic claim list.
2. Batch verification: claims + evidence summary -> one binary verdict per claim.

The score is:

```text
faithfulness = supported_claim_count / total_claim_count * 10
```

If there are no claims, the evaluator returns `score=None` with an explanatory error. If there is no evidence, it returns `score=0` for reports with factual claims, with metadata showing `evidence_count=0`.

## 4. Why Lightweight First

The existing eval suite already runs multiple LLM-judge dimensions. Per-claim multi-judge verification would multiply cost by claim count and make the full suite much slower. The first version should prove the claim-level metric and keep full-suite cost predictable.

The implementation should still make a future multi-judge mode easy by isolating the decomposition and verification prompts from aggregation logic.

## 5. Data Inputs

Use only data already present in the final `ResearchState` checkpoint:

- `state["final_report"]`: report to evaluate.
- `state["facts"]`: primary evidence, using `id`, `content`, `source_name`, `source_url`, `credibility_score`.
- `state["references"]`: fallback evidence, using `id`, `title` or `source`, and `url`.

Evidence formatting should deduplicate obvious duplicate lines by URL plus content prefix. Keep the evidence compact so verification fits in one prompt.

## 6. Components

Add:

- `backend/app/eval/evaluators/faithfulness.py`
- `backend/app/eval/evaluators/claim_utils.py`
- `backend/app/eval/evaluators/prompts/claim_decomposition.md`
- `backend/app/eval/evaluators/prompts/claim_verification.md`
- `backend/app/eval/tests/test_evaluators/test_faithfulness.py`

Extend:

- `backend/app/eval/types.py`: add a small structured-output result dataclass.
- `backend/app/eval/judges/base.py`: add a structured JSON/text call method that does not parse numeric scores.
- `backend/app/eval/judges/ensemble.py`: add a lightweight structured generation method that uses only the primary judge client.

`claim_utils.py` contains pure functions for:

- stripping markdown reference sections from reports before decomposition
- formatting evidence from `facts` and `references`
- parsing JSON from fenced LLM output
- validating claim and verdict payloads

## 7. Prompt Contracts

### Claim Decomposition

Input:

- user query
- report excerpt or full report up to a fixed character limit

Output JSON:

```json
{
  "claims": [
    {
      "id": "c1",
      "text": "A single verifiable factual claim.",
      "section": "section title if known",
      "importance": "high|medium|low"
    }
  ]
}
```

Rules:

- Split compound factual sentences into separate verifiable claims.
- Ignore stylistic statements, headings, disclaimers, and purely forward-looking opinions unless they contain factual assertions.
- Preserve numeric values, years, entity names, and comparisons.
- Cap output to the evaluator's claim limit.

### Claim Verification

Input:

- claim list
- evidence list

Output JSON:

```json
{
  "verdicts": [
    {
      "claim_id": "c1",
      "supported": true,
      "reason": "Short Chinese reason.",
      "evidence_ids": ["f1"]
    }
  ]
}
```

Rules:

- Use binary verdicts only.
- Mark unsupported when evidence is missing, contradictory, too vague, or only partially supports the claim.
- Use `evidence_ids=[]` when unsupported.

## 8. Existing Evaluator Improvements

Existing 7 evaluators should not depend on `FaithfulnessEvaluator` output because the runner executes evaluators concurrently. The first implementation will improve integration in two safe ways:

1. Register `faithfulness` alongside the existing 7 evaluators so aggregate reports show information fidelity next to relevance, coherence, citation, completeness, critic loop, cost, and latency.
2. Expose claim-level metadata in `EvalResult.metadata`, including unsupported claims, so storage and reports can surface the new diagnostic signal without database schema changes.

Do not add extra claim-generation calls inside `relevance`, `coherence`, `citation`, or `completeness` in this first pass. That keeps the suite cost predictable. A later pass can refactor runner execution into two phases if multiple evaluators need shared claims.

The reporter should add a small faithfulness diagnostics section when unsupported claims exist. This improves the existing report artifact without changing the score table or CSV shape.

## 9. Constants

Use conservative limits in `faithfulness.py`:

- `REPORT_CHARS = 8000`
- `MAX_CLAIMS = 40`
- `MAX_EVIDENCE_ITEMS = 60`
- `EVIDENCE_ITEM_CHARS = 300`

These constants keep the two prompts bounded and make tests deterministic.

## 10. Error Handling

The evaluator must never raise to the runner. It returns `EvalResult(error=...)` when:

- judge is missing
- final report is empty
- decomposition JSON cannot be parsed
- verification JSON cannot be parsed
- verification returns no usable verdicts

Partial verdicts are allowed. If verification omits some claim IDs, omitted claims count as unsupported and appear in metadata.

## 11. Metadata

Return:

- `claim_count`
- `supported_count`
- `unsupported_count`
- `evidence_count`
- `unsupported_claims`: capped list of claim text plus reason
- `claims`: capped list for debugging
- `verdicts`: capped list for debugging
- `decomposition_raw`
- `verification_raw`

Store raw structured outputs in metadata and keep `raw_judge_outputs` as a compact audit trail with entries for `decomposition` and `verification`.

The lightweight version must not use `EnsembleJudge.score()` for these two calls because that method expects numeric `{score, reasoning}` output and calls all judge clients. Instead, add a structured generation method:

```python
await judge.generate_structured(prompt, system_prompt=...)
```

This method calls only the primary judge client by default, preserving the 2-call-per-case budget.

## 12. Testing

Add mocked unit tests for:

- happy path: 3 claims, 2 supported -> score `6.67`
- empty report returns error
- no evidence with claims returns score `0`
- fenced JSON parsing works
- invalid decomposition JSON returns error
- missing verdicts count as unsupported
- evaluator registration includes `faithfulness`
- reporter includes unsupported claim diagnostics
- runner smoke still succeeds with the new evaluator

No test should call real LLM APIs.

## 13. Resume Claim After Implementation

After this is implemented and tests pass, the resume wording can truthfully say:

> Implemented an LLM-as-a-Judge eval framework with Ragas-inspired claim decomposition and binary claim verification for faithfulness, plus multi-judge ensemble scoring for report relevance, coherence, and completeness.

This wording separates the lightweight faithfulness verifier from the existing multi-judge quality evaluators while keeping the technical story strong.
