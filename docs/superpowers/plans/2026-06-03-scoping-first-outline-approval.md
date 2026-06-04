# Scoping-First Outline Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shallow scoping before planning, pause for editable outline approval, then resume deep research from executor using the approved outline.

**Architecture:** Keep the existing LangGraph plan-and-execute graph, but add a `scoping` node before `planner` and stop the first SSE stream after Planner when approval is pending. Persist the paused state through the existing checkpoint service, add a dedicated continue endpoint that validates the edited outline, updates search steps, and streams executor/critic/replanner from the checkpoint.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, pytest + pytest-asyncio, React + TypeScript + Vite, existing SSE parsing and checkpoint restore code.

---

## File Structure

- Modify `backend/app/service/deep_research_v2/state.py`
  - Add scoping and outline approval fields to `ResearchState` and `create_initial_state()`.

- Modify `backend/app/service/deep_research_v2/agents/scout.py`
  - Add `scope_topic()` as a shallow, non-recursive scoping entrypoint.

- Modify `backend/app/service/deep_research_v2/agents/planner.py`
  - Format and inject `scoping_summary` into Planner's user prompt.
  - Add a helper for refreshing search queries after user edits.

- Modify `backend/app/service/deep_research_v2/graph.py`
  - Add `scoping` node and route it before `planner`.
  - Emit scoping and approval events.
  - Pause after Planner when approval is pending.
  - Add a resume-from-executor streaming method for approved outlines.

- Modify `backend/app/service/deep_research_v2/service.py`
  - Add service method that exposes continue streaming.

- Modify `backend/app/router/research_router.py`
  - Add request model and `POST /research/continue/{session_id}` SSE endpoint.

- Modify `backend/app/service/checkpoint_service.py`
  - Allow saving a checkpoint with status `paused` without immediately overwriting it as `running`.

- Modify backend tests:
  - `backend/test/test_deep_research_v3/test_state.py`
  - `backend/test/test_deep_research_v3/test_scout_scoping.py`
  - `backend/test/test_deep_research_v3/test_planner.py`
  - `backend/test/test_deep_research_v3/test_graph_integration.py`
  - `backend/test/test_deep_research_v3/test_outline_continue.py`

- Modify `frontend/src/api/session.ts`
  - Add continue request types and `continueResearch()` stream call.

- Modify `frontend/src/api/session.type.d.ts`
  - Add approval-related fields to `ChatItem` or related research types if needed.

- Modify `frontend/src/pages/chat/component/research-detail/index.tsx`
  - Add an approval tab/view and props for confirm callbacks.

- Modify `frontend/src/pages/chat/component/research-detail/index.module.scss`
  - Add restrained styles for scoping summary and outline editor.

- Modify `frontend/src/pages/chat/index.tsx`
  - Handle `outline_approval_required`, checkpoint restore for pending approval, and continue stream parsing.

---

### Task 1: Add State Fields For Scoping And Approval

**Files:**
- Modify: `backend/app/service/deep_research_v2/state.py`
- Modify: `backend/test/test_deep_research_v3/test_state.py`

- [ ] **Step 1: Write the failing state test**

Append this test to `backend/test/test_deep_research_v3/test_state.py`:

```python
def test_research_state_scoping_and_outline_approval_defaults():
    state = create_initial_state(query="q", session_id="s")

    assert state["scoping_summary"] == {}
    assert state["outline_approval_status"] == "pending"
    assert state["approved_outline"] == []
```

- [ ] **Step 2: Run the state test to verify it fails**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_state.py::test_research_state_scoping_and_outline_approval_defaults -q
```

Expected: FAIL with `KeyError: 'scoping_summary'`.

- [ ] **Step 3: Add fields to `ResearchState`**

In `backend/app/service/deep_research_v2/state.py`, add these fields after the research type fields and before planning output:

```python
    # Planning scoping and approval
    scoping_summary: Dict[str, Any]          # Shallow search topic map for Planner only
    outline_approval_status: str            # pending | approved | skipped
    approved_outline: List[Dict[str, Any]]   # User-confirmed editable outline copy
```

- [ ] **Step 4: Initialize the fields**

In `create_initial_state()`, add these entries immediately after `research_type="general",`:

```python
        scoping_summary={},
        outline_approval_status="pending",
        approved_outline=[],
```

- [ ] **Step 5: Run state tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_state.py -q
```

Expected: all tests in `test_state.py` pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/app/service/deep_research_v2/state.py backend/test/test_deep_research_v3/test_state.py
git commit -m "feat: add outline approval state"
```

---

### Task 2: Add Shallow Scout Scoping

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/scout.py`
- Create: `backend/test/test_deep_research_v3/test_scout_scoping.py`

- [ ] **Step 1: Write failing Scout scoping tests**

Create `backend/test/test_deep_research_v3/test_scout_scoping.py`:

```python
import pytest

from app.service.deep_research_v2.agents.scout import DeepScout
from app.service.deep_research_v2.state import create_initial_state


@pytest.mark.asyncio
async def test_scope_topic_uses_shallow_search_without_mutating_facts(monkeypatch):
    scout = DeepScout(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
        model="qwen-plus",
    )
    calls = []

    async def fake_execute_search(query, count=10):
        calls.append((query, count))
        return [
            {
                "url": f"https://example.com/{len(calls)}",
                "title": f"{query} market report",
                "summary": "battery storage policy demand supply chain",
                "snippet": "battery storage policy demand supply chain",
                "site_name": "Example Research",
                "date": "2026-01-01",
            }
        ]

    async def forbidden_deep_search(*args, **kwargs):
        raise AssertionError("_execute_deep_search must not run during scoping")

    monkeypatch.setattr(scout, "_execute_search", fake_execute_search)
    monkeypatch.setattr(scout, "_execute_deep_search", forbidden_deep_search)

    state = create_initial_state("battery storage industry", "sid_1")
    summary = await scout.scope_topic(state, "battery storage industry", count=2, max_queries=2)

    assert len(calls) == 2
    assert all(count == 2 for _, count in calls)
    assert state["facts"] == []
    assert state["raw_sources"] == []
    assert summary["queries"][0] == "battery storage industry"
    assert summary["initial_sources"][0]["site_name"] == "Example Research"
    assert "battery" in summary["hot_terms"]


@pytest.mark.asyncio
async def test_scope_topic_returns_warning_on_search_failure(monkeypatch):
    scout = DeepScout(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
        model="qwen-plus",
    )

    async def failing_execute_search(query, count=10):
        raise RuntimeError("search unavailable")

    monkeypatch.setattr(scout, "_execute_search", failing_execute_search)

    state = create_initial_state("robotics", "sid_1")
    summary = await scout.scope_topic(state, "robotics", count=2, max_queries=2)

    assert summary["queries"] == ["robotics"]
    assert summary["initial_sources"] == []
    assert "search unavailable" in summary["warning"]
    assert state["facts"] == []
```

- [ ] **Step 2: Run Scout scoping tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_scout_scoping.py -q
```

Expected: FAIL with `AttributeError: 'DeepScout' object has no attribute 'scope_topic'`.

- [ ] **Step 3: Add deterministic scoping helpers**

In `backend/app/service/deep_research_v2/agents/scout.py`, add this helper near `_ensure_str()`:

```python
def _tokenize_scope_text(text: str) -> List[str]:
    separators = " ,.;:!?()[]{}<>|/\\\n\r\t\"'"
    value = text.lower()
    for sep in separators:
        value = value.replace(sep, " ")
    stopwords = {
        "and", "or", "the", "a", "an", "of", "for", "to", "in", "on", "with",
        "by", "from", "is", "are", "was", "were", "market", "report",
        "analysis", "industry", "research", "2024", "2025", "2026",
    }
    terms = []
    for raw in value.split():
        term = raw.strip("-_")
        if len(term) < 3 or term in stopwords:
            continue
        if term.isdigit():
            continue
        terms.append(term)
    return terms
```

- [ ] **Step 4: Add `scope_topic()` to `DeepScout`**

Inside class `DeepScout`, add this method after `process()` and before `_supplementary_research()`:

```python
    async def scope_topic(
        self,
        state: ResearchState,
        query: str,
        *,
        count: int = 3,
        max_queries: int = 3,
    ) -> Dict[str, Any]:
        """Run one shallow search pass for Planner context only.

        This method intentionally does not ingest facts, read URLs, analyze
        results with an LLM, or recurse into follow-up searches.
        """
        base_query = (query or state.get("query", "") or "").strip()
        queries = [base_query] if base_query else []
        research_type = state.get("research_type", "")
        if research_type and research_type != "general" and base_query:
            queries.append(f"{base_query} {research_type}")
        if base_query:
            queries.append(f"{base_query} latest report")
        queries = queries[:max_queries]

        summary = {
            "queries": queries,
            "key_subdomains": [],
            "initial_sources": [],
            "hot_terms": [],
            "source_notes": [],
            "warning": "",
        }

        all_results: List[Dict[str, Any]] = []
        try:
            for scope_query in queries:
                results = await self._execute_search(scope_query, count=count)
                all_results.extend(results[:count])
        except Exception as e:
            summary["warning"] = str(e)
            return summary

        seen_urls = set()
        term_counts: Dict[str, int] = {}
        site_counts: Dict[str, int] = {}
        for result in all_results:
            url = _ensure_str(result.get("url"))
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            title = _ensure_str(result.get("title"))
            site_name = _ensure_str(result.get("site_name"))
            snippet = _ensure_str(result.get("summary") or result.get("snippet"))
            if site_name:
                site_counts[site_name] = site_counts.get(site_name, 0) + 1
            for term in _tokenize_scope_text(f"{title} {snippet}"):
                term_counts[term] = term_counts.get(term, 0) + 1
            summary["initial_sources"].append({
                "title": title[:120],
                "url": url,
                "site_name": site_name,
                "date": _ensure_str(result.get("date")),
                "snippet": snippet[:240],
            })

        summary["hot_terms"] = [
            term for term, _ in sorted(term_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
        ]
        summary["key_subdomains"] = summary["hot_terms"][:6]
        summary["source_notes"] = [
            f"{site}: {n} result(s)"
            for site, n in sorted(site_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
        ]
        return summary
```

- [ ] **Step 5: Run Scout scoping tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_scout_scoping.py -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add backend/app/service/deep_research_v2/agents/scout.py backend/test/test_deep_research_v3/test_scout_scoping.py
git commit -m "feat: add shallow scoping search"
```

---

### Task 3: Inject Scoping Summary Into Planner And Refresh Search Queries

**Files:**
- Modify: `backend/app/service/deep_research_v2/agents/planner.py`
- Modify: `backend/test/test_deep_research_v3/test_planner.py`

- [ ] **Step 1: Add failing Planner tests**

Append these tests to `backend/test/test_deep_research_v3/test_planner.py`:

```python
@pytest.mark.asyncio
async def test_planner_injects_scoping_summary(planner, monkeypatch):
    mock_response = json.dumps({
        "outline": [
            {
                "id": "sec_1",
                "title": "Demand",
                "description": "Demand drivers",
                "section_type": "mixed",
                "status": "pending",
                "requires_data": True,
                "requires_chart": False,
            }
        ],
        "plan": [
            {
                "step_id": "step_search_sec_1",
                "tool": "search_section",
                "args": {"section_id": "sec_1", "queries": ["old"]},
                "depends_on": [],
                "parallel_group": "search_batch",
            }
        ],
    })
    captured = {}

    async def fake_call_llm(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return mock_response

    monkeypatch.setattr(planner, "call_llm", fake_call_llm)

    state = create_initial_state(query="energy storage", session_id="sid_1")
    state["scoping_summary"] = {
        "key_subdomains": ["grid storage", "industrial storage"],
        "hot_terms": ["lithium", "capacity"],
        "initial_sources": [
            {"title": "Storage outlook", "url": "https://example.com", "site_name": "Example"}
        ],
        "source_notes": ["Example: 1 result(s)"],
    }

    await planner.process(state)

    assert "Initial scoping result" in captured["user_prompt"]
    assert "grid storage" in captured["user_prompt"]
    assert "Storage outlook" in captured["user_prompt"]


def test_refresh_plan_queries_uses_edited_outline(planner):
    outline = [
        {"id": "sec_1", "title": "Edited Demand", "description": "New demand framing"},
        {"id": "sec_2", "title": "Edited Supply", "description": ""},
    ]
    plan = [
        {
            "step_id": "step_search_sec_1",
            "tool": "search_section",
            "args": {"section_id": "sec_1", "queries": ["old demand"]},
            "depends_on": [],
            "parallel_group": "search_batch",
        },
        {
            "step_id": "step_search_sec_2",
            "tool": "search_section",
            "args": {"section_id": "sec_2", "queries": ["old supply"]},
            "depends_on": [],
            "parallel_group": "search_batch",
        },
    ]

    refreshed = planner.refresh_plan_queries("energy storage", outline, plan)

    assert refreshed[0]["args"]["queries"] == [
        "energy storage",
        "Edited Demand",
        "Edited Demand New demand framing",
    ]
    assert refreshed[1]["args"]["queries"] == [
        "energy storage",
        "Edited Supply",
    ]
```

- [ ] **Step 2: Run Planner tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_planner.py::test_planner_injects_scoping_summary test/test_deep_research_v3/test_planner.py::test_refresh_plan_queries_uses_edited_outline -q
```

Expected: first test fails because no scoping text is injected; second fails because `refresh_plan_queries` does not exist.

- [ ] **Step 3: Add scoping formatter**

In `backend/app/service/deep_research_v2/agents/planner.py`, add this helper after `_format_outline_hint()`:

```python
def _format_scoping_summary(scoping_summary: dict) -> str:
    if not scoping_summary:
        return ""
    lines = [
        "Initial scoping result (planning context only; not verified report evidence):"
    ]
    key_subdomains = scoping_summary.get("key_subdomains") or []
    hot_terms = scoping_summary.get("hot_terms") or []
    source_notes = scoping_summary.get("source_notes") or []
    initial_sources = scoping_summary.get("initial_sources") or []
    warning = scoping_summary.get("warning") or ""
    if key_subdomains:
        lines.append("Key subdomains: " + ", ".join(map(str, key_subdomains[:8])))
    if hot_terms:
        lines.append("Hot terms: " + ", ".join(map(str, hot_terms[:12])))
    if source_notes:
        lines.append("Source notes: " + "; ".join(map(str, source_notes[:6])))
    if initial_sources:
        lines.append("Initial sources:")
        for source in initial_sources[:8]:
            title = source.get("title", "")
            site = source.get("site_name", "")
            url = source.get("url", "")
            lines.append(f"- {title} ({site}) {url}")
    if warning:
        lines.append(f"Scoping warning: {warning}")
    lines.append("Generate the outline based on this scoping map and the user's query.")
    return "\n".join(lines)
```

- [ ] **Step 4: Inject scoping formatter in `Planner.process()`**

In `Planner.process()`, after:

```python
            user_prompt = f"研究问题：{query}"
            if outline_hint:
                user_prompt += f"\n\n{outline_hint}"
```

add:

```python
            scoping_hint = _format_scoping_summary(state.get("scoping_summary", {}))
            if scoping_hint:
                user_prompt += f"\n\n{scoping_hint}"
```

- [ ] **Step 5: Add `refresh_plan_queries()`**

Inside class `Planner`, above `_fallback_template()`, add:

```python
    def refresh_plan_queries(
        self,
        query: str,
        outline: list,
        plan: list,
    ) -> list:
        sections_by_id = {
            section.get("id"): section
            for section in outline
            if section.get("id")
        }
        refreshed = []
        for step in plan:
            new_step = dict(step)
            new_step["args"] = dict(step.get("args", {}) or {})
            if step.get("tool") == "search_section":
                section_id = new_step["args"].get("section_id")
                section = sections_by_id.get(section_id)
                if section:
                    title = str(section.get("title", "")).strip()
                    description = str(section.get("description", "")).strip()
                    queries = [str(query).strip()]
                    if title:
                        queries.append(title)
                    if title and description:
                        queries.append(f"{title} {description}"[:160])
                    deduped = []
                    for item in queries:
                        if item and item not in deduped:
                            deduped.append(item)
                    new_step["args"]["queries"] = deduped
            refreshed.append(new_step)
        return self._enforce_plan_topology(refreshed)
```

- [ ] **Step 6: Run Planner tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_planner.py -q
```

Expected: all Planner tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/service/deep_research_v2/agents/planner.py backend/test/test_deep_research_v3/test_planner.py
git commit -m "feat: plan with scoping context"
```

---

### Task 4: Add Scoping Node And Planner Approval Pause

**Files:**
- Modify: `backend/app/service/deep_research_v2/graph.py`
- Modify: `backend/app/service/checkpoint_service.py`
- Modify: `backend/test/test_deep_research_v3/test_graph_integration.py`

- [ ] **Step 1: Add failing graph tests**

Append these tests to `backend/test/test_deep_research_v3/test_graph_integration.py`:

```python
def test_graph_compiled_has_scoping_before_planner(graph):
    subgraph = graph._build_deep_research_subgraph()
    inner = subgraph.get_graph()
    inner_names = set(inner.nodes.keys())

    assert "scoping" in inner_names


@pytest.mark.asyncio
async def test_scoping_node_returns_summary(graph, monkeypatch):
    state = create_initial_state(query="energy storage", session_id="s")
    state["research_type"] = "industry_analysis"

    async def fake_scope_topic(state, query, count=3, max_queries=3):
        return {"queries": [query], "key_subdomains": ["grid"], "initial_sources": []}

    monkeypatch.setattr(graph.scout, "scope_topic", fake_scope_topic)

    result = await graph._scoping_node(state)

    assert result["scoping_summary"]["key_subdomains"] == ["grid"]


@pytest.mark.asyncio
async def test_run_pauses_after_planner_when_approval_pending(graph, monkeypatch):
    state = create_initial_state(query="energy storage", session_id="s")
    state["intent"] = "deep_research"
    state["research_type"] = "industry_analysis"

    async def fake_astream(*args, **kwargs):
        yield ((), "updates", {
            "planner": {
                "outline": [{"id": "sec_1", "title": "Demand", "description": "D"}],
                "plan": [{
                    "step_id": "step_search_sec_1",
                    "tool": "search_section",
                    "args": {"section_id": "sec_1", "queries": ["Demand"]},
                    "depends_on": [],
                    "parallel_group": "search_batch",
                }],
            }
        })
        raise AssertionError("executor must not run after approval pause")

    saved = {}

    def fake_save_checkpoint(state, user_id=None, ui_state=None, status=None):
        saved["state"] = dict(state)
        saved["status"] = status
        return True

    monkeypatch.setattr(graph.graph, "astream", fake_astream)
    monkeypatch.setattr(graph, "_save_checkpoint", fake_save_checkpoint)

    events = [event async for event in graph._run_with_langgraph(state)]

    approval_events = [e for e in events if e.get("type") == "outline_approval_required"]
    assert approval_events
    assert approval_events[0]["outline"][0]["title"] == "Demand"
    assert saved["status"] == "paused"
```

- [ ] **Step 2: Run graph tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_graph_integration.py::test_graph_compiled_has_scoping_before_planner test/test_deep_research_v3/test_graph_integration.py::test_scoping_node_returns_summary test/test_deep_research_v3/test_graph_integration.py::test_run_pauses_after_planner_when_approval_pending -q
```

Expected: FAIL because `scoping` and approval pause do not exist.

- [ ] **Step 3: Allow checkpoint status override**

In `backend/app/service/checkpoint_service.py`, change the signature of `save_checkpoint()` to:

```python
    def save_checkpoint(
        self,
        session_id: str,
        state: Dict[str, Any],
        user_id: Optional[str] = None,
        ui_state: Optional[Dict[str, Any]] = None,
        final_report: Optional[str] = None,
        status: str = "running",
    ) -> Optional[str]:
```

Replace both assignments of checkpoint status:

```python
                existing.status = "running"
```

and:

```python
                    status="running",
```

with:

```python
                existing.status = status
```

and:

```python
                    status=status,
```

- [ ] **Step 4: Pass status through graph checkpoint save**

In `backend/app/service/deep_research_v2/graph.py`, change `_save_checkpoint()` signature to:

```python
    def _save_checkpoint(
        self,
        state: Dict[str, Any],
        user_id: str = None,
        ui_state: Dict[str, Any] = None,
        status: str = "running",
    ) -> bool:
```

Inside the `save_checkpoint()` call, add:

```python
                status=status,
```

- [ ] **Step 5: Add scoping node to graph**

In `_build_deep_research_subgraph()`, add the node:

```python
        sub.add_node("scoping", self._scoping_node)
```

Change the first edge from:

```python
        sub.add_edge("research_type_router", "planner")
```

to:

```python
        sub.add_edge("research_type_router", "scoping")
        sub.add_edge("scoping", "planner")
```

Update the topology docstring to include `scoping`.

- [ ] **Step 6: Add `_scoping_node()`**

In `DeepResearchGraph`, add this method before `_planner_node()`:

```python
    async def _scoping_node(self, state: ResearchState) -> Dict[str, Any]:
        self._maybe_cancel(state)
        self._emit_phase_start("scoping", "Starting shallow topic scoping...")
        self._emit_event("research_step", {
            "step_type": "scoping",
            "title": "Topic scoping",
            "subtitle": "Running shallow search before planning",
            "status": "running",
        })
        try:
            summary = await self.scout.scope_topic(
                state,
                state.get("query", ""),
                count=3,
                max_queries=3,
            )
        except Exception as e:
            summary = {
                "queries": [state.get("query", "")],
                "key_subdomains": [],
                "initial_sources": [],
                "hot_terms": [],
                "source_notes": [],
                "warning": str(e),
            }
        self._emit_event("scoping_completed", {
            "scoping_summary": summary,
        })
        self._emit_event("research_step", {
            "step_type": "scoping",
            "title": "Topic scoping",
            "subtitle": "Shallow scoping complete",
            "status": "completed",
            "stats": {
                "sources_count": len(summary.get("initial_sources", []) or []),
                "terms_count": len(summary.get("hot_terms", []) or []),
            },
        })
        return {"scoping_summary": summary}
```

- [ ] **Step 7: Add scoping and approval mappings**

In `_run_with_langgraph()`, add `"scoping"` and `"approval"` support.

Change `SILENT_NODES` to keep `scoping` visible:

```python
        SILENT_NODES = {
            "intent_router", "research_type_router", "web_search", "simple_qa",
            "out_of_scope", "deep_research",
        }
```

Add:

```python
            "scoping": ("scoping", "Scoping complete"),
```

to `node_to_phase_info`.

In `_build_checkpoint_event()`, add to `step_type_map`:

```python
            "scoping": "scoping",
```

Add stats branch:

```python
        if step_type == "scoping":
            scoping = state.get("scoping_summary", {}) or {}
            stats = {
                "sources": len(scoping.get("initial_sources", []) or []),
                "terms": len(scoping.get("hot_terms", []) or []),
            }
        elif step_type == "planning":
            stats = {"sections": len(state.get("outline", []))}
```

- [ ] **Step 8: Pause after Planner update**

In `_run_with_langgraph()`, after `last_state.update(node_diff)` and after checkpoint event generation for `planner`, add:

```python
                        if (
                            node_name == "planner"
                            and last_state.get("outline_approval_status", "pending") == "pending"
                        ):
                            outline = last_state.get("outline", []) or []
                            approval_event = {
                                "type": "outline_approval_required",
                                "session_id": session_id,
                                "outline": outline,
                                "scoping_summary": last_state.get("scoping_summary", {}) or {},
                            }
                            ui_state["research_steps"].append({
                                "type": "approval",
                                "status": "running",
                                "stats": {"sections": len(outline)},
                            })
                            self._save_checkpoint(
                                last_state,
                                user_id,
                                ui_state,
                                status="paused",
                            )
                            yield approval_event
                            return
```

Keep the existing `outline` event emitted by `_planner_node()` unchanged.

- [ ] **Step 9: Run graph tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_graph_integration.py -q
```

Expected: all graph integration tests pass.

- [ ] **Step 10: Commit Task 4**

```bash
git add backend/app/service/deep_research_v2/graph.py backend/app/service/checkpoint_service.py backend/test/test_deep_research_v3/test_graph_integration.py
git commit -m "feat: pause for outline approval"
```

---

### Task 5: Add Continue Endpoint And Resume From Executor

**Files:**
- Modify: `backend/app/service/deep_research_v2/graph.py`
- Modify: `backend/app/service/deep_research_v2/service.py`
- Modify: `backend/app/router/research_router.py`
- Create: `backend/test/test_deep_research_v3/test_outline_continue.py`

- [ ] **Step 1: Write failing continue validation tests**

Create `backend/test/test_deep_research_v3/test_outline_continue.py`:

```python
import pytest

from app.service.deep_research_v2.graph import DeepResearchGraph
from app.service.deep_research_v2.state import create_initial_state


def test_validate_approved_outline_merges_only_editable_fields(monkeypatch):
    graph = DeepResearchGraph(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
    )
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [
        {
            "id": "sec_1",
            "title": "Old",
            "description": "Old desc",
            "section_type": "mixed",
            "status": "pending",
            "requires_data": True,
            "requires_chart": False,
        }
    ]
    approved = [{"id": "sec_1", "title": "New", "description": "New desc", "status": "completed"}]

    merged = graph._validate_approved_outline(state, approved)

    assert merged[0]["title"] == "New"
    assert merged[0]["description"] == "New desc"
    assert merged[0]["status"] == "pending"
    assert merged[0]["requires_data"] is True


def test_validate_approved_outline_rejects_changed_ids(monkeypatch):
    graph = DeepResearchGraph(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
    )
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]

    with pytest.raises(ValueError, match="section ids"):
        graph._validate_approved_outline(state, [{"id": "sec_2", "title": "New"}])


@pytest.mark.asyncio
async def test_continue_with_approved_outline_updates_state_and_streams(monkeypatch):
    graph = DeepResearchGraph(
        llm_api_key="dummy",
        llm_base_url="http://dummy",
        search_api_key="dummy",
    )
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]
    state["plan"] = [{
        "step_id": "step_search_sec_1",
        "tool": "search_section",
        "args": {"section_id": "sec_1", "queries": ["Old"]},
        "depends_on": [],
        "parallel_group": "search_batch",
    }]
    state["outline_approval_status"] = "pending"

    monkeypatch.setattr(graph, "_load_checkpoint", lambda session_id: dict(state))
    monkeypatch.setattr(graph, "_save_checkpoint", lambda *args, **kwargs: True)

    async def fake_run_executor_graph(state):
        yield {"type": "phase", "phase": "executing", "content": "Execution started"}

    monkeypatch.setattr(graph, "_run_from_executor", fake_run_executor_graph)

    events = [
        event async for event in graph.continue_with_approved_outline(
            "s",
            [{"id": "sec_1", "title": "New", "description": "New desc"}],
        )
    ]

    assert events[0]["type"] == "outline_approved"
    assert events[0]["outline"][0]["title"] == "New"
    assert events[1]["phase"] == "executing"
```

- [ ] **Step 2: Run continue tests to verify they fail**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_outline_continue.py -q
```

Expected: FAIL because validation and continue methods do not exist.

- [ ] **Step 3: Add outline validation helper**

In `backend/app/service/deep_research_v2/graph.py`, add this method to `DeepResearchGraph`:

```python
    def _validate_approved_outline(
        self,
        state: ResearchState,
        approved_outline: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        saved_outline = state.get("outline", []) or []
        if len(saved_outline) != len(approved_outline or []):
            raise ValueError("approved outline must keep the same section count")

        saved_ids = [section.get("id") for section in saved_outline]
        approved_ids = [section.get("id") for section in approved_outline or []]
        if saved_ids != approved_ids:
            raise ValueError("approved outline must keep the same section ids")

        merged = []
        for saved, approved in zip(saved_outline, approved_outline):
            title = str(approved.get("title", saved.get("title", ""))).strip()
            description = str(approved.get("description", saved.get("description", ""))).strip()
            if not title:
                raise ValueError("section title cannot be empty")
            item = dict(saved)
            item["title"] = title[:120]
            item["description"] = description[:1000]
            merged.append(item)
        return merged
```

- [ ] **Step 4: Add executor-only runner**

In `DeepResearchGraph`, add this method near `_run_with_langgraph()`:

```python
    async def _run_from_executor(
        self,
        state: ResearchState,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        executor_result = await executor_node(state)
        state.update(executor_result)
        yield {"type": "phase", "phase": "executing", "content": "Execution complete"}
        critic_result = await self._critic_node(state)
        state.update(critic_result)
        yield {"type": "phase", "phase": "reviewing", "content": "Review complete"}
        route = route_after_critic(state)
        while route == "replanner":
            replanner_result = await self._replanner_node(state)
            state.update(replanner_result)
            yield {"type": "phase", "phase": "replanning", "content": "Replanning complete"}
            executor_result = await executor_node(state)
            state.update(executor_result)
            yield {"type": "phase", "phase": "executing", "content": "Execution complete"}
            critic_result = await self._critic_node(state)
            state.update(critic_result)
            yield {"type": "phase", "phase": "reviewing", "content": "Review complete"}
            route = route_after_critic(state)

        if self.checkpoint_service and state.get("session_id"):
            self.checkpoint_service.update_status(state["session_id"], "completed")
        yield self._build_completion_event(state)
```

This direct executor runner intentionally uses existing node wrappers and `executor_node()` to avoid re-entering `intent_router`, `research_type_router`, `scoping`, or `planner`.

- [ ] **Step 5: Add `continue_with_approved_outline()`**

In `DeepResearchGraph`, add:

```python
    async def continue_with_approved_outline(
        self,
        session_id: str,
        approved_outline: List[Dict[str, Any]],
        user_id: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        state = self._load_checkpoint(session_id)
        if not state:
            raise ValueError("No checkpoint found for this session")
        if state.get("outline_approval_status") != "pending":
            raise RuntimeError("Outline approval is not pending")

        merged_outline = self._validate_approved_outline(state, approved_outline)
        refreshed_plan = self.planner.refresh_plan_queries(
            state.get("query", ""),
            merged_outline,
            state.get("plan", []) or [],
        )
        state["outline"] = merged_outline
        state["approved_outline"] = merged_outline
        state["outline_approval_status"] = "approved"
        state["plan"] = refreshed_plan
        if user_id:
            state["_user_id"] = user_id

        self._save_checkpoint(state, user_id, status="running")
        yield {
            "type": "outline_approved",
            "session_id": session_id,
            "outline": merged_outline,
        }

        async for event in self._run_from_executor(state):
            yield event
```

- [ ] **Step 6: Add service method**

In `backend/app/service/deep_research_v2/service.py`, add this method to `DeepResearchV2Service` before `_format_sse()`:

```python
    async def continue_research(
        self,
        session_id: str,
        approved_outline: list[dict],
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        try:
            async for event in self.graph.continue_with_approved_outline(
                session_id=session_id,
                approved_outline=approved_outline,
                user_id=user_id,
            ):
                yield self._format_sse(event)
        except Exception as e:
            logger.error(f"Continue research error: {e}")
            yield self._format_sse({"type": "error", "content": str(e)})
        yield "data: [DONE]\n\n"
```

- [ ] **Step 7: Add router model and endpoint**

In `backend/app/router/research_router.py`, add this model after `ResearchRequest`:

```python
class ContinueResearchRequest(BaseModel):
    approved_outline: list[dict]
```

Add this endpoint before the checkpoint API section:

```python
@router.post("/continue/{session_id}", status_code=HTTP_200_OK)
async def continue_research(session_id: str, request: ContinueResearchRequest):
    try:
        from service.checkpoint_service import get_checkpoint_service
        checkpoint_service = get_checkpoint_service()
        info = checkpoint_service.get_checkpoint_info(session_id)
        if not info:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="No checkpoint found for this session",
            )
        if info.get("status") != "paused":
            raise HTTPException(
                status_code=409,
                detail="Research is not waiting for outline approval",
            )

        service_v2 = get_research_service_v2()

        async def generate_sse():
            async for event in service_v2.continue_research(
                session_id=session_id,
                approved_outline=request.approved_outline,
            ):
                yield event

        return StreamingResponse(generate_sse(), media_type="text/event-stream")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to continue research: {e}")
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
```

- [ ] **Step 8: Run continue tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_outline_continue.py -q
```

Expected: all continue tests pass.

- [ ] **Step 9: Run backend focused tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3/test_state.py test/test_deep_research_v3/test_scout_scoping.py test/test_deep_research_v3/test_planner.py test/test_deep_research_v3/test_graph_integration.py test/test_deep_research_v3/test_outline_continue.py -q
```

Expected: all selected tests pass.

- [ ] **Step 10: Commit Task 5**

```bash
git add backend/app/service/deep_research_v2/graph.py backend/app/service/deep_research_v2/service.py backend/app/router/research_router.py backend/test/test_deep_research_v3/test_outline_continue.py
git commit -m "feat: continue research after outline approval"
```

---

### Task 6: Add Frontend API And Approval Types

**Files:**
- Modify: `frontend/src/api/session.ts`
- Modify: `frontend/src/pages/chat/component/research-detail/index.tsx`

- [ ] **Step 1: Add API types and function**

In `frontend/src/api/session.ts`, after `deepsearch()`, add:

```typescript
export interface ApprovedOutlineSection {
  id: string
  title: string
  description?: string
}

export interface ContinueResearchParams {
  approved_outline: ApprovedOutlineSection[]
}

export function continueResearch(
  sessionId: string,
  params: ContinueResearchParams,
  options?: AxiosRequestConfig,
) {
  return request.post<ReadableStream>(`/research/continue/${sessionId}`, params, {
    headers: {
      Accept: 'text/event-stream',
    },
    responseType: 'stream',
    adapter: 'fetch',
    loading: false,
    ...options,
  })
}
```

- [ ] **Step 2: Extend research detail types**

In `frontend/src/pages/chat/component/research-detail/index.tsx`, add these interfaces near `ChartConfig`:

```typescript
export interface ScopingSummary {
  queries?: string[]
  key_subdomains?: string[]
  initial_sources?: Array<{
    title?: string
    url?: string
    site_name?: string
    date?: string
    snippet?: string
  }>
  hot_terms?: string[]
  source_notes?: string[]
  warning?: string
}

export interface OutlineDraftSection {
  id: string
  title: string
  description?: string
}
```

Extend `ResearchDetailData`:

```typescript
  scopingSummary?: ScopingSummary
  outlineDraft?: OutlineDraftSection[]
  approvalStatus?: 'pending' | 'approved'
```

Extend `ResearchStep['type']` union by adding `scoping` and `approval`:

```typescript
  type: 'scoping' | 'planning' | 'approval' | 'searching' | 'analyzing' | 'generating' | 'writing' | 'reviewing' | 're_researching' | 'revising'
```

Extend `ResearchDetailProps`:

```typescript
  onApproveOutline?: (outline: OutlineDraftSection[]) => void
```

Add step labels:

```typescript
  scoping: '主题勘察',
  approval: '确认大纲',
```

- [ ] **Step 3: Run frontend build to see type errors**

Run:

```bash
cd frontend
npm run build
```

Expected: build may fail until Task 7 wires the new required prop usage. Type errors should point to `ResearchDetail` prop and `ResearchStep['type']` usage.

- [ ] **Step 4: Commit Task 6 only if build has no unrelated failures**

If the build fails only because Task 7 is not implemented yet, do not commit. Continue to Task 7 and commit frontend changes together.

If the build passes, commit:

```bash
git add frontend/src/api/session.ts frontend/src/pages/chat/component/research-detail/index.tsx
git commit -m "feat: add outline approval frontend types"
```

---

### Task 7: Add Frontend Approval Editor

**Files:**
- Modify: `frontend/src/pages/chat/component/research-detail/index.tsx`
- Modify: `frontend/src/pages/chat/component/research-detail/index.module.scss`

- [ ] **Step 1: Add React imports**

In `frontend/src/pages/chat/component/research-detail/index.tsx`, change:

```typescript
import { useState } from 'react'
```

to:

```typescript
import { useEffect, useState } from 'react'
```

- [ ] **Step 2: Add approval editor state**

Inside `ResearchDetail()`, after `activeTab` state, add:

```typescript
  const [outlineDraft, setOutlineDraft] = useState<OutlineDraftSection[]>(data?.outlineDraft || [])

  useEffect(() => {
    setOutlineDraft(data?.outlineDraft || [])
  }, [data?.outlineDraft])
```

- [ ] **Step 3: Add approval view before the normal tabs**

Before the `return (` line, add:

```typescript
  const isApproval = data?.approvalStatus === 'pending' && data?.outlineDraft
```

In the JSX, after the stepper block and before the tab block, add:

```tsx
      {isApproval && (
        <div className={styles.approvalBody}>
          <div className={styles.approvalSection}>
            <div className={styles.approvalEyebrow}>Scoping result</div>
            <div className={styles.scopeGrid}>
              <div>
                <div className={styles.scopeLabel}>Key areas</div>
                <div className={styles.tagList}>
                  {(data?.scopingSummary?.key_subdomains || []).map(item => (
                    <span key={item} className={styles.tag}>{item}</span>
                  ))}
                </div>
              </div>
              <div>
                <div className={styles.scopeLabel}>Hot terms</div>
                <div className={styles.tagList}>
                  {(data?.scopingSummary?.hot_terms || []).slice(0, 12).map(item => (
                    <span key={item} className={styles.tag}>{item}</span>
                  ))}
                </div>
              </div>
            </div>
            {(data?.scopingSummary?.initial_sources || []).length > 0 && (
              <div className={styles.sourceList}>
                {(data?.scopingSummary?.initial_sources || []).slice(0, 5).map((source, index) => (
                  <div key={`${source.url || source.title || index}`} className={styles.sourceItem}>
                    <div className={styles.sourceTitle}>{source.title || 'Untitled source'}</div>
                    <div className={styles.sourceMeta}>{source.site_name || 'Unknown source'}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className={styles.approvalSection}>
            <div className={styles.approvalEyebrow}>Research outline</div>
            <div className={styles.outlineEditor}>
              {outlineDraft.map((section, index) => (
                <div key={section.id} className={styles.outlineItem}>
                  <div className={styles.outlineNumber}>{index + 1}</div>
                  <div className={styles.outlineFields}>
                    <input
                      className={styles.outlineInput}
                      value={section.title}
                      onChange={(event) => {
                        const value = event.target.value
                        setOutlineDraft(prev => prev.map(item =>
                          item.id === section.id ? { ...item, title: value } : item,
                        ))
                      }}
                    />
                    <textarea
                      className={styles.outlineTextarea}
                      value={section.description || ''}
                      onChange={(event) => {
                        const value = event.target.value
                        setOutlineDraft(prev => prev.map(item =>
                          item.id === section.id ? { ...item, description: value } : item,
                        ))
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <div className={styles.approvalActions}>
              <button className={styles.secondaryAction} type="button" disabled>
                Regenerate outline
              </button>
              <button
                className={styles.primaryAction}
                type="button"
                onClick={() => onApproveOutline?.(outlineDraft)}
                disabled={outlineDraft.some(section => !section.title.trim())}
              >
                Confirm and start research
              </button>
            </div>
          </div>
        </div>
      )}
```

Wrap the existing tabs and content in:

```tsx
      {!isApproval && (
        <>
          ...existing tabs and content...
        </>
      )}
```

- [ ] **Step 4: Add approval styles**

Append to `frontend/src/pages/chat/component/research-detail/index.module.scss`:

```scss
.approvalBody {
  flex: 1;
  overflow: auto;
  padding: 20px 24px 28px;
  background: #fff;
}

.approvalSection {
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  padding-bottom: 20px;
  margin-bottom: 20px;
}

.approvalEyebrow {
  font-size: 12px;
  color: #666;
  font-weight: 600;
  margin-bottom: 12px;
}

.scopeGrid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.scopeLabel {
  font-size: 12px;
  color: #888;
  margin-bottom: 8px;
}

.tagList {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 6px;
  padding: 4px 7px;
  font-size: 12px;
  color: #333;
  background: #fafafa;
}

.sourceList {
  margin-top: 14px;
  display: grid;
  gap: 8px;
}

.sourceItem {
  border: 1px solid rgba(0, 0, 0, 0.06);
  border-radius: 6px;
  padding: 10px 12px;
}

.sourceTitle {
  font-size: 13px;
  color: #222;
  line-height: 1.4;
}

.sourceMeta {
  margin-top: 4px;
  font-size: 12px;
  color: #888;
}

.outlineEditor {
  display: grid;
  gap: 12px;
}

.outlineItem {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
}

.outlineNumber {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #1a1a1a;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  margin-top: 2px;
}

.outlineFields {
  display: grid;
  gap: 8px;
}

.outlineInput,
.outlineTextarea {
  width: 100%;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 6px;
  padding: 9px 10px;
  font-size: 13px;
  color: #222;
  outline: none;

  &:focus {
    border-color: #1a1a1a;
  }
}

.outlineTextarea {
  min-height: 64px;
  resize: vertical;
  line-height: 1.5;
}

.approvalActions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.secondaryAction,
.primaryAction {
  border: none;
  border-radius: 6px;
  height: 34px;
  padding: 0 14px;
  font-size: 13px;
  cursor: pointer;

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }
}

.secondaryAction {
  background: #f2f2f2;
  color: #444;
}

.primaryAction {
  background: #1a1a1a;
  color: #fff;
}
```

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: build may still fail until `onApproveOutline` is passed from chat page in Task 8.

- [ ] **Step 6: Do not commit yet if Task 8 is required**

If build fails because the chat page does not pass `onApproveOutline`, continue to Task 8 and commit both tasks together.

---

### Task 8: Wire Frontend SSE Approval Flow

**Files:**
- Modify: `frontend/src/pages/chat/index.tsx`
- Modify: `frontend/src/pages/chat/component/research-detail/index.tsx`
- Modify: `frontend/src/pages/chat/component/research-detail/index.module.scss`
- Modify: `frontend/src/api/session.ts`

- [ ] **Step 1: Add approval event handling helper**

In `frontend/src/pages/chat/index.tsx`, near other local helper types or above `sendChat`, add:

```typescript
type OutlineApprovalEvent = {
  type: 'outline_approval_required'
  session_id: string
  outline: Array<{ id: string; title: string; description?: string }>
  scoping_summary?: any
}
```

- [ ] **Step 2: Handle `outline_approval_required` in `parseData()`**

Inside `parseData()`, in the `target.type === ChatType.Deepsearch` block before `research_complete`, add:

```typescript
            if (json.type === 'outline_approval_required') {
              const approval = json as OutlineApprovalEvent
              target.loading = false
              const stepType = 'approval' as ResearchStep['type']
              const step: ResearchStep = {
                id: stepType,
                type: stepType,
                title: '确认研究大纲',
                subtitle: '编辑章节标题和描述后开始研究',
                status: 'running',
                stats: { sectionsCount: approval.outline.length },
              }
              setResearchSteps(prev => {
                const existing = prev.find(s => s.type === stepType)
                const next = existing
                  ? prev.map(s => s.type === stepType ? step : s)
                  : [...prev, step]
                researchStepsRef.current = next
                return next
              })

              const detail: ResearchDetailData = {
                stepId: stepType,
                stepType,
                title: '确认研究大纲',
                subtitle: '编辑章节标题和描述后开始研究',
                searchResults: [],
                charts: [],
                scopingSummary: approval.scoping_summary,
                outlineDraft: approval.outline,
                approvalStatus: 'pending',
              }
              researchDetailsRef.current.set(stepType, detail)
              setSelectedResearchDetail({ ...detail })
              setResearchDataVersion(v => v + 1)
              return
            }
```

- [ ] **Step 3: Extract stream reading into a reusable callback**

Inside `sendChat`, the existing `read(reader)` and `parseData(slice)` functions are nested. Keep them in place for this task, but add a new callback below `sendChat` that can read the continue stream by using a small parser for the continued events:

```typescript
  const continueApprovedOutline = useCallback(async (outline: Array<{ id: string; title: string; description?: string }>) => {
    if (!id) return
    const res = await api.session.continueResearch(id, { approved_outline: outline })
    const reader = res.data.getReader()
    if (!reader) return
    currentSessionIdRef.current = id
    readerRef.current = reader

    const decoder = new TextDecoder('utf-8')
    let temp = ''
    while (true) {
      const { value, done } = await reader.read()
      temp += decoder.decode(value)
      while (true) {
        const index = temp.indexOf('\n')
        if (index === -1) break
        const slice = temp.slice(0, index)
        temp = temp.slice(index + 1)
        if (!slice.startsWith('data: ')) continue
        const str = slice.trim().replace(/^data\: /, '').trim()
        if (!str || str === '[DONE]') continue
        const json = JSON.parse(str)
        if (json.type === 'outline_approved') {
          setResearchSteps(prev => {
            const next = prev.map(s => s.type === 'approval' ? { ...s, status: 'completed' as const } : s)
            researchStepsRef.current = next
            return next
          })
          const detail = researchDetailsRef.current.get('approval')
          if (detail) {
            detail.approvalStatus = 'approved'
            setSelectedResearchDetail({ ...detail })
          }
          continue
        }
        if (json.type === 'phase') {
          const phaseToStepType: Record<string, ResearchStep['type']> = {
            executing: 'searching',
            reviewing: 'reviewing',
            replanning: 'revising',
          }
          const stepType = phaseToStepType[json.phase]
          if (stepType && !researchStepsRef.current.find(s => s.type === stepType)) {
            const step: ResearchStep = {
              id: stepType,
              type: stepType,
              title: json.phase,
              subtitle: String(json.content || ''),
              status: 'running',
            }
            const next = [...researchStepsRef.current, step]
            researchStepsRef.current = next
            setResearchSteps(next)
            researchDetailsRef.current.set(stepType, {
              stepId: stepType,
              stepType,
              title: json.phase,
              subtitle: String(json.content || ''),
              searchResults: [],
              charts: [],
            })
          }
          continue
        }
        if (json.type === 'research_complete') {
          const writingDetail = researchDetailsRef.current.get('writing') || {
            stepId: 'writing',
            stepType: 'writing',
            title: '撰写报告',
            searchResults: [],
            charts: [],
          }
          writingDetail.streamingReport = json.final_report || ''
          researchDetailsRef.current.set('writing', writingDetail)
          setSelectedResearchDetail({ ...writingDetail })
          setResearchDataVersion(v => v + 1)
        }
      }
      if (done) break
    }
    readerRef.current = null
  }, [id])
```

This initial callback handles the approval boundary and common completion events. In the implementation pass, prefer extracting the existing full `parseData()` logic so both initial and continue streams share all event handling. If extraction is too large for one step, land this minimal version and immediately add a follow-up refactor before manual testing.

- [ ] **Step 4: Pass approval callback into `ResearchDetail`**

In the `rightPanelContent` render, change:

```tsx
        <ResearchDetail
          data={aggregatedResearchData}
          steps={researchSteps}
          onStepClick={handleResearchStepClick}
          onClose={() => setSelectedResearchDetail(null)}
        />
```

to:

```tsx
        <ResearchDetail
          data={aggregatedResearchData}
          steps={researchSteps}
          onStepClick={handleResearchStepClick}
          onClose={() => setSelectedResearchDetail(null)}
          onApproveOutline={continueApprovedOutline}
        />
```

Add `continueApprovedOutline` to the `useMemo` dependency list for `rightPanelContent`.

- [ ] **Step 5: Restore paused approval checkpoint**

In the checkpoint restore block after `const stateJson = checkpoint.state_json as any`, add:

```typescript
            if (checkpoint.status === 'paused' && stateJson?.outline_approval_status === 'pending') {
              const approvalStep: ResearchStep = {
                id: 'approval',
                type: 'approval',
                title: '确认研究大纲',
                subtitle: '编辑章节标题和描述后开始研究',
                status: 'running',
                stats: { sectionsCount: (stateJson.outline || []).length },
              }
              steps = [...steps.filter(step => step.type !== 'approval'), approvalStep]
            }
```

After details are initialized, add:

```typescript
              if (checkpoint.status === 'paused' && stateJson?.outline_approval_status === 'pending') {
                const approvalDetail: ResearchDetailData = {
                  stepId: 'approval',
                  stepType: 'approval',
                  title: '确认研究大纲',
                  subtitle: '编辑章节标题和描述后开始研究',
                  searchResults: [],
                  charts: [],
                  scopingSummary: stateJson.scoping_summary,
                  outlineDraft: stateJson.outline || [],
                  approvalStatus: 'pending',
                }
                researchDetailsRef.current.set('approval', approvalDetail)
                setSelectedResearchDetail({ ...approvalDetail })
              }
```

- [ ] **Step 6: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: build succeeds. If there are TypeScript errors, fix the exact union or prop typing mismatch and rerun.

- [ ] **Step 7: Commit frontend approval flow**

```bash
git add frontend/src/api/session.ts frontend/src/pages/chat/index.tsx frontend/src/pages/chat/component/research-detail/index.tsx frontend/src/pages/chat/component/research-detail/index.module.scss
git commit -m "feat: approve research outline before execution"
```

---

### Task 9: Focused Verification

**Files:**
- No source changes unless verification exposes a defect.

- [ ] **Step 1: Run deep research backend tests**

Run:

```bash
cd backend
pytest test/test_deep_research_v3 -q
```

Expected: all `test_deep_research_v3` tests pass.

- [ ] **Step 2: Run security tests that protect search and prompt boundaries**

Run:

```bash
cd backend
pytest test/test_security/test_scout_injection.py test/test_security/test_prompt_guard.py -q
```

Expected: all selected security tests pass.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 4: Manual smoke test**

Start backend and frontend using the repo's normal local commands. If no local environment is configured, skip this step and record the reason in the final handoff.

Use the UI to start a deep research query with web search enabled. Expected sequence:

1. `intent_detected` switches the message to deep research.
2. Scoping step appears.
3. Planning step appears.
4. Approval editor appears with scoping summary and outline.
5. Edit one section title.
6. Click confirm.
7. Search/analyze/write/review proceeds without rerunning scoping or planning.
8. Final report arrives.

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short
```

Expected: empty output.

- [ ] **Step 6: Commit verification fixes if needed**

If verification required code or test changes, commit them:

```bash
git add backend frontend
git commit -m "test: verify outline approval flow"
```

If no changes were needed, do not create an empty commit.

---

## Self-Review Notes

Spec coverage:

- Scoping-first planning is covered by Tasks 2, 3, and 4.
- Planner prompt injection is covered by Task 3.
- Paused approval checkpoint is covered by Task 4.
- Dedicated continue endpoint is covered by Task 5.
- Editable title/description only is covered by Task 5 validation and Task 7 UI.
- Frontend approval and checkpoint restore are covered by Tasks 6, 7, and 8.
- Verification is covered by Task 9.

Placeholder scan:

- No task uses open-ended language without concrete code.
- Regenerate outline is explicitly disabled in the first implementation.
- Manual smoke test has concrete expected events and a permitted skip condition.

Type consistency:

- Backend state fields are `scoping_summary`, `outline_approval_status`, and `approved_outline`.
- Frontend event uses backend payload keys `scoping_summary` and `outline`.
- Frontend detail fields use camelCase `scopingSummary` and `outlineDraft`.
- Continue request uses backend key `approved_outline`.

Risk notes:

- The direct `_run_from_executor()` runner should be reviewed carefully because it bypasses `graph.astream()` updates. If preserving identical checkpoint cadence is required, add checkpoint saves after each node inside `_run_from_executor()`.
- The frontend continue stream parser should ideally be refactored to reuse the existing initial stream parser. The plan lands a minimal version first to keep the approval feature testable, then flags the refactor as the next cleanup if event drift appears.
