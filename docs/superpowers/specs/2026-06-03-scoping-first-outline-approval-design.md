# Scoping-First Outline Approval Design

> Date: 2026-06-03
> Scope: Add evidence-informed planning plus editable outline approval to DeepResearch v2/v3.
> Status: Approved for implementation planning.

## 1. Goal

Improve deep research planning by giving Planner a lightweight evidence map before it creates the outline, then pause for the user to edit and approve the outline before the expensive executor phase starts.

The target user experience is:

1. User starts deep research.
2. System performs a shallow scoping search.
3. Planner generates an outline based on the query, research type, memory, skill template, and scoping result.
4. Frontend shows the scoping summary and editable outline.
5. User edits section titles/descriptions and confirms.
6. Backend resumes from the saved checkpoint and runs executor, critic, and replanner normally.

## 2. Current Diagnosis

The current deep research subgraph is:

```text
research_type_router -> planner -> executor -> critic
                                      |
                                      v
                                  replanner
```

Planner runs before any search evidence exists. It relies on the user query, research type skill YAML, long-term memory, and prompt priors. This can produce plausible but generic outlines. If the outline is wrong, all downstream search/analyze/write work follows the wrong shape.

The codebase already has useful foundations:

- `DeepResearchGraph` owns `self.scout` and can add a `scoping` node before `planner`.
- `DeepScout._execute_search()` can perform low-count search calls without the recursive deep-search path.
- `Planner.process()` already constructs a user prompt and can inject more context.
- Checkpoint persistence already stores backend state and UI state after node updates.
- Frontend already handles deep research SSE events, research steps, search results, outline, checkpoint restore, and resume endpoints.

The missing pieces are a shallow scoping boundary, an approval pause, a continue endpoint that resumes after Planner instead of restarting the whole graph, and a frontend editor for approved outline fields.

## 3. Decisions

- Implement the full interactive flow, not only backend prompt injection.
- Let users edit `title` and `description` only.
- Do not let users edit `id`, `status`, `requires_data`, `requires_chart`, or plan queries in the first version.
- Use a two-stage run instead of keeping the original SSE connection open.
- Save a paused checkpoint after Planner and return `outline_approval_required`.
- Add a dedicated continue endpoint that accepts `session_id` and `approved_outline`.
- Continue from `executor`, not from the outer graph entry point.
- Keep scoping results out of `facts`, `raw_sources`, and `references` so shallow snippets are not treated as verified evidence.

## 4. Non-Goals

- Do not build a full plan editor.
- Do not expose every section search query for editing.
- Do not use LangGraph interrupt in this phase.
- Do not duplicate the whole deep research run after outline confirmation.
- Do not add a new database table.
- Do not make scoping failure block research.

## 5. Backend Design

### 5.1 Subgraph Shape

The deep research subgraph becomes:

```text
research_type_router -> scoping -> planner -> executor -> critic
                                             |            |
                                             |            v
                                             |        replanner
                                             v
                                      approval pause
```

The `planner` node still emits `outline` and `plan`. When outline approval is enabled and `outline_approval_status` is not `approved`, the graph run stops after Planner by returning an `outline_approval_required` event and saving a paused checkpoint. The first implementation can avoid a new LangGraph node for the pause and handle the pause in `_run_with_langgraph()` when the `planner` update arrives. This keeps the compiled graph simple and avoids making `executor` conditionally unreachable.

### 5.2 State Additions

Add JSON-serializable fields to `ResearchState`:

```python
scoping_summary: Dict[str, Any]
outline_approval_status: str
approved_outline: List[Dict[str, Any]]
```

Default values:

```python
scoping_summary={}
outline_approval_status="pending"
approved_outline=[]
```

`outline_approval_status` values:

- `pending`: Planner output needs user approval.
- `approved`: Continue endpoint accepted edited outline and executor can run.
- `skipped`: reserved for future server-side opt-out.

### 5.3 Scoping Node

`scoping` calls a new lightweight Scout method, for example:

```python
async def scope_topic(
    self,
    state: ResearchState,
    query: str,
    *,
    count: int = 3,
    max_queries: int = 3,
) -> Dict[str, Any]:
```

It performs only first-page search calls via `_execute_search(query, count=count)`. It does not call `_execute_deep_search()`, `_analyze_search_results()`, `_ingest_facts()`, `deep_read_url()`, or any recursive follow-up search.

The returned structure should be compact:

```json
{
  "queries": ["..."],
  "key_subdomains": ["..."],
  "initial_sources": [
    {"title": "...", "url": "...", "site_name": "...", "date": "..."}
  ],
  "hot_terms": ["..."],
  "source_notes": ["..."],
  "warning": ""
}
```

The first implementation can derive this deterministically from titles, snippets, and site names. A later version can add an LLM summarizer if deterministic extraction is too weak.

### 5.4 Planner Prompt Injection

`Planner.process()` reads:

```python
scoping_summary = state.get("scoping_summary", {})
```

If present, it adds a scoping section to `user_prompt`:

```text
Initial scoping result:
...

Use this scoping result to generate an outline grounded in current subdomains, sources, and terminology.
Do not treat it as verified evidence for final claims; it is only planning context.
```

Skill outline hints and memory remain in the prompt.

### 5.5 Approval Pause

When Planner completes and approval is required:

- The backend emits `outline` as today for compatibility.
- The backend emits `outline_approval_required` with `session_id`, `outline`, and `scoping_summary`.
- The backend saves checkpoint status as `paused`.
- The stream ends with `[DONE]`.
- Executor does not run.

The checkpoint state must contain:

- `outline`
- `plan`
- `scoping_summary`
- `outline_approval_status="pending"`

### 5.6 Continue Endpoint

Add a new endpoint:

```text
POST /research/continue/{session_id}
```

Request body:

```json
{
  "approved_outline": [
    {"id": "sec_1", "title": "...", "description": "..."}
  ]
}
```

Response is SSE, matching `/research/stream`.

Validation:

- Checkpoint must exist.
- Checkpoint status must be `paused`.
- State `outline_approval_status` must be `pending`.
- Approved outline must have the same number of sections and same ids as saved `outline`.
- Editable fields are normalized to strings and length-limited.
- Non-editable fields are copied from saved outline.

After validation:

- Set `state["approved_outline"]`.
- Set `state["outline"]` to sanitized merged outline.
- Set `state["outline_approval_status"]="approved"`.
- Update or rebuild plan from the edited outline.
- Save checkpoint status as `running`.
- Start execution from the executor phase.

### 5.7 Plan Refresh

Because users can edit titles and descriptions, the existing plan may have search queries derived from old titles. The first implementation should update only `search_section` plan steps:

- Match `search_section` steps by `args.section_id`.
- Replace missing or stale `args.queries` with:
  - user query
  - section title
  - section title plus section description, truncated

This avoids a second Planner LLM call while ensuring executor search follows edited section language. The topology still goes through `Planner._enforce_plan_topology()`.

## 6. Frontend Design

### 6.1 Event Handling

When frontend receives `outline_approval_required`:

- Set current assistant message to deep research mode.
- Set loading to false because the first SSE stream is intentionally done.
- Add or update a research step with type `approval` and status `running`.
- Create a research detail object containing `scopingSummary`, `outlineDraft`, and `approvalStatus`.
- Select the approval detail in the right panel.

### 6.2 Editor

Add a focused approval view inside the existing research detail panel.

The view shows:

- Scoping summary:
  - key subdomains
  - initial sources
  - hot terms
- Editable outline:
  - title input per section
  - description textarea per section
- Actions:
  - `Regenerate outline` reserved or disabled in first implementation if not backed by an endpoint.
  - `Confirm and start research`

The first implementation should wire only `Confirm and start research`. If the regenerate button is displayed, it must be disabled or explicitly shown as unavailable.

### 6.3 Continue Request

On confirm:

- Call `api.session.continueResearch(sessionId, { approved_outline })`.
- Read the returned SSE stream with the same parsing path as `deepsearch()`.
- Continue updating research steps and details as existing events arrive.

### 6.4 Checkpoint Restore

When loading a paused checkpoint with `outline_approval_status="pending"`:

- Restore the approval step.
- Restore scoping summary and outline draft from `state_json`.
- Show the editor so the user can confirm after refresh.

## 7. Error Handling

- Scoping search error: store a warning in `scoping_summary.warning`, emit a warning event, continue to Planner.
- Planner LLM error: existing fallback outline still enters approval flow.
- Continue checkpoint missing: HTTP 400.
- Continue checkpoint not paused or already approved: HTTP 409.
- Invalid approved outline: HTTP 400 with a clear validation message.
- Continue stream error after approval: emit SSE `error` and mark checkpoint failed.

## 8. Observability

LangSmith and logs should make the new boundary visible:

- Add node `scoping`.
- Add LLM/search log action names `scout.scope_topic` if an LLM summarizer is later used.
- Emit `phase` events for `scoping` and `approval`.
- Save checkpoint after scoping/planner pause so state can be inspected.

## 9. Tests

Backend tests:

- State defaults include scoping and approval fields.
- Scout scoping uses `_execute_search()` only and does not mutate facts.
- Planner prompt includes scoping summary when present.
- Graph subgraph contains `scoping` before `planner`.
- Planner pause emits `outline_approval_required` and does not run executor.
- Continue endpoint validates outline ids and resumes from executor.
- Invalid outline returns 400.
- Repeated continue returns 409.

Frontend verification:

- Build succeeds.
- Manual or component-level check confirms `outline_approval_required` creates the approval editor.
- Confirm sends `approved_outline` and consumes continued SSE.
- Paused checkpoint restore shows the editor.

## 10. Acceptance Criteria

The implementation is accepted when:

- Planner receives scoping context before generating an outline.
- Scoping does not pollute final evidence stores.
- The user can edit section title and description before execution.
- The first stream pauses after Planner and ends cleanly.
- Confirmation continues from executor without rerunning scoping/planning.
- Refreshing during approval restores the editor from checkpoint.
- Existing deep research flows still work for normal execution after approval.
