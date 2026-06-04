import json
import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.service.deep_research_v2.graph import DeepResearchGraph
from app.service.deep_research_v2.agents.planner import Planner
from app.service.deep_research_v2.service import DeepResearchV2Service
from app.service.deep_research_v2.state import create_initial_state


def make_graph():
    graph = DeepResearchGraph.__new__(DeepResearchGraph)
    graph.planner = Planner.__new__(Planner)
    graph.checkpoint_service = None
    return graph


def import_research_router():
    app_dir = Path(__file__).resolve().parents[2] / "app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    return importlib.import_module("router.research_router")


def test_validate_approved_outline_merges_only_editable_fields():
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{
        "id": "sec_1",
        "title": "Old",
        "description": "Old desc",
        "section_type": "mixed",
        "status": "pending",
        "requires_data": True,
        "requires_chart": False,
    }]
    approved = [{
        "id": "sec_1",
        "title": "New",
        "description": "New desc",
        "status": "completed",
    }]

    merged = graph._validate_approved_outline(state, approved)

    assert merged[0]["title"] == "New"
    assert merged[0]["description"] == "New desc"
    assert merged[0]["status"] == "pending"
    assert merged[0]["requires_data"] is True


def test_validate_approved_outline_rejects_changed_count():
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]

    with pytest.raises(ValueError, match="section count"):
        graph._validate_approved_outline(state, [])


def test_validate_approved_outline_rejects_changed_ids():
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]

    with pytest.raises(ValueError, match="section ids"):
        graph._validate_approved_outline(
            state,
            [{"id": "sec_2", "title": "New"}],
        )


def test_validate_approved_outline_rejects_empty_title():
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]

    with pytest.raises(ValueError, match="title"):
        graph._validate_approved_outline(
            state,
            [{"id": "sec_1", "title": "   "}],
        )


def test_validate_approved_outline_caps_editable_fields():
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]

    merged = graph._validate_approved_outline(
        state,
        [{"id": "sec_1", "title": "T" * 130, "description": "D" * 1010}],
    )

    assert len(merged[0]["title"]) == 120
    assert len(merged[0]["description"]) == 1000


def test_preflight_continue_rejects_invalid_outline_before_stream(monkeypatch):
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]
    state["outline_approval_status"] = "pending"
    monkeypatch.setattr(graph, "_load_checkpoint", lambda session_id: dict(state))

    with pytest.raises(ValueError, match="title"):
        graph.preflight_continue_with_approved_outline(
            "s",
            [{"id": "sec_1", "title": " "}],
        )


def test_prepare_continue_claims_paused_session_once():
    graph = make_graph()
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

    class CheckpointStub:
        def __init__(self):
            self.claims = 0
            self.saved = []

        def load_checkpoint(self, session_id):
            return dict(state)

        def claim_paused_checkpoint(self, session_id):
            self.claims += 1
            return self.claims == 1

        def save_checkpoint(self, session_id, state, **kwargs):
            self.saved.append((session_id, dict(state), kwargs))
            return "checkpoint-id"

    checkpoint = CheckpointStub()
    graph.checkpoint_service = checkpoint

    prepared = graph.prepare_continue_with_approved_outline(
        "s",
        [{"id": "sec_1", "title": "New", "description": "New desc"}],
        user_id="u1",
    )

    assert prepared["outline_approval_status"] == "approved"
    assert prepared["outline"][0]["title"] == "New"
    assert checkpoint.saved[0][2]["status"] == "running"

    with pytest.raises(RuntimeError, match="Outline approval is not pending"):
        graph.prepare_continue_with_approved_outline(
            "s",
            [{"id": "sec_1", "title": "Newer"}],
        )


@pytest.mark.asyncio
async def test_continue_with_approved_outline_updates_state_and_streams(monkeypatch):
    graph = make_graph()
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

    saved = {}
    monkeypatch.setattr(graph, "_load_checkpoint", lambda session_id: dict(state))

    def fake_save_checkpoint(next_state, user_id=None, ui_state=None, status="running"):
        saved["state"] = dict(next_state)
        saved["user_id"] = user_id
        saved["status"] = status
        return True

    monkeypatch.setattr(graph, "_save_checkpoint", fake_save_checkpoint)

    async def fake_run_executor_graph(next_state):
        yield {"type": "phase", "phase": "executing", "content": "Execution started"}

    monkeypatch.setattr(graph, "_run_from_executor", fake_run_executor_graph)

    events = [
        event async for event in graph.continue_with_approved_outline(
            "s",
            [{"id": "sec_1", "title": "New", "description": "New desc"}],
            user_id="u1",
        )
    ]

    assert events[0]["type"] == "outline_approved"
    assert events[0]["outline"][0]["title"] == "New"
    assert events[1]["phase"] == "executing"
    assert saved["status"] == "running"
    assert saved["user_id"] == "u1"
    assert saved["state"]["outline_approval_status"] == "approved"
    assert saved["state"]["approved_outline"][0]["description"] == "New desc"
    assert saved["state"]["plan"][0]["args"]["queries"] == ["q", "q New", "q New New desc"]


@pytest.mark.asyncio
async def test_run_from_executor_yields_custom_stream_events(monkeypatch):
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline_approval_status"] = "approved"

    async def fake_executor(_state):
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer({"type": "custom_probe", "content": {"ok": True}})
        return {"final_report": "draft"}

    async def fake_critic(_state):
        return {
            "verdict": "pass",
            "quality_score": 8.0,
            "unresolved_issues": 0,
            "suggested_actions": [],
        }

    monkeypatch.setattr("app.service.deep_research_v2.graph.executor_node", fake_executor)
    monkeypatch.setattr(graph, "_critic_node", fake_critic)

    events = [event async for event in graph._run_from_executor(state)]

    assert any(event.get("type") == "custom_probe" for event in events)
    assert events[-1]["type"] == "research_complete"


@pytest.mark.asyncio
async def test_continue_with_approved_outline_requires_pending(monkeypatch):
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]
    state["outline_approval_status"] = "approved"
    monkeypatch.setattr(graph, "_load_checkpoint", lambda session_id: dict(state))

    with pytest.raises(RuntimeError, match="Outline approval is not pending"):
        events = graph.continue_with_approved_outline(
            "s",
            [{"id": "sec_1", "title": "New"}],
        )
        await anext(events)


@pytest.mark.asyncio
async def test_run_from_executor_completes_without_prior_nodes(monkeypatch):
    graph = make_graph()
    state = create_initial_state(query="q", session_id="s")
    state["outline_approval_status"] = "approved"

    async def fail_prior_node(_state):
        raise AssertionError("pre-executor nodes must not run")

    async def fake_executor(_state):
        return {"final_report": "draft", "facts": [{"id": "fact_1"}]}

    async def fake_critic(_state):
        return {
            "verdict": "pass",
            "quality_score": 8.0,
            "unresolved_issues": 0,
            "suggested_actions": [],
        }

    status_updates = []
    monkeypatch.setattr(graph, "_intent_router_node", fail_prior_node)
    monkeypatch.setattr(graph, "_research_type_router_node", fail_prior_node)
    monkeypatch.setattr(graph, "_scoping_node", fail_prior_node)
    monkeypatch.setattr(graph, "_planner_node", fail_prior_node)
    monkeypatch.setattr("app.service.deep_research_v2.graph.executor_node", fake_executor)
    monkeypatch.setattr(graph, "_critic_node", fake_critic)
    monkeypatch.setattr(graph, "_save_checkpoint", lambda *args, **kwargs: True)
    graph.checkpoint_service = type(
        "CheckpointStub",
        (),
        {"update_status": lambda self, session_id, status, *args: status_updates.append((session_id, status))},
    )()

    events = [event async for event in graph._run_from_executor(state)]

    assert [event["phase"] for event in events if event.get("type") == "phase"] == [
        "executing",
        "reviewing",
    ]
    assert events[-1]["type"] == "research_complete"
    assert events[-1]["final_report"] == "draft"
    assert ("s", "completed") in status_updates


@pytest.mark.asyncio
async def test_service_continue_research_formats_sse_and_done(monkeypatch):
    service = DeepResearchV2Service.__new__(DeepResearchV2Service)
    service.graph = type(
        "GraphStub",
        (),
        {"continue_with_approved_outline": lambda self, *args, **kwargs: None},
    )()

    async def fake_continue_with_approved_outline(session_id, approved_outline, user_id=None):
        yield {
            "type": "outline_approved",
            "session_id": session_id,
            "outline": approved_outline,
        }

    monkeypatch.setattr(
        service.graph,
        "continue_with_approved_outline",
        fake_continue_with_approved_outline,
    )

    chunks = [
        chunk async for chunk in service.continue_research(
            "s",
            [{"id": "sec_1", "title": "New"}],
            user_id="u1",
        )
    ]

    assert json.loads(chunks[0].removeprefix("data: ").strip())["type"] == "outline_approved"
    assert chunks[-1] == "data: [DONE]\n\n"


def test_router_continue_rejects_missing_checkpoint(monkeypatch):
    research_router = import_research_router()

    class CheckpointStub:
        def get_checkpoint_info(self, session_id):
            return None

    monkeypatch.setattr(
        "service.checkpoint_service.get_checkpoint_service",
        lambda: CheckpointStub(),
    )

    with pytest.raises(HTTPException) as exc:
        import anyio
        anyio.run(
            research_router.continue_research,
            "missing",
            research_router.ContinueResearchRequest(approved_outline=[]),
        )

    assert exc.value.status_code == 400


def test_router_continue_rejects_non_paused_checkpoint(monkeypatch):
    research_router = import_research_router()

    class CheckpointStub:
        def get_checkpoint_info(self, session_id):
            return {"status": "running"}

    monkeypatch.setattr(
        "service.checkpoint_service.get_checkpoint_service",
        lambda: CheckpointStub(),
    )

    with pytest.raises(HTTPException) as exc:
        import anyio
        anyio.run(
            research_router.continue_research,
            "s",
            research_router.ContinueResearchRequest(approved_outline=[]),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Research is not waiting for outline approval"


def test_router_continue_streams_when_paused(monkeypatch):
    research_router = import_research_router()

    class CheckpointStub:
        def get_checkpoint_info(self, session_id):
            return {"status": "paused"}

    class ServiceStub:
        graph = type(
            "GraphStub",
            (),
            {
                "prepare_continue_with_approved_outline": (
                    lambda self, session_id, approved_outline, user_id=None: {
                        "session_id": session_id,
                        "outline": approved_outline,
                    }
                )
            },
        )()

        async def continue_research(
            self,
            session_id,
            approved_outline,
            user_id=None,
            prepared_state=None,
        ):
            assert prepared_state["session_id"] == session_id
            yield 'data: {"type": "outline_approved"}\n\n'
            yield "data: [DONE]\n\n"

    monkeypatch.setattr(
        "service.checkpoint_service.get_checkpoint_service",
        lambda: CheckpointStub(),
    )
    monkeypatch.setattr(research_router, "get_research_service_v2", lambda: ServiceStub())

    app = FastAPI()
    app.include_router(research_router.router)
    client = TestClient(app)

    response = client.post(
        "/research/continue/s",
        json={"approved_outline": [{"id": "sec_1", "title": "New"}]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"outline_approved"' in response.text


def test_router_continue_claim_failure_returns_409_before_stream(monkeypatch):
    research_router = import_research_router()

    class CheckpointStub:
        def get_checkpoint_info(self, session_id):
            return {"status": "paused"}

    class GraphStub:
        def prepare_continue_with_approved_outline(self, *args, **kwargs):
            raise RuntimeError("Outline approval is not pending")

    class ServiceStub:
        graph = GraphStub()

        async def continue_research(self, *args, **kwargs):
            raise AssertionError("stream must not start when claim fails")
            yield "data: [DONE]\n\n"

    monkeypatch.setattr(
        "service.checkpoint_service.get_checkpoint_service",
        lambda: CheckpointStub(),
    )
    monkeypatch.setattr(research_router, "get_research_service_v2", lambda: ServiceStub())

    app = FastAPI()
    app.include_router(research_router.router)
    client = TestClient(app)

    response = client.post(
        "/research/continue/s",
        json={"approved_outline": [{"id": "sec_1", "title": "New"}]},
    )

    assert response.status_code == 409
    assert "Outline approval is not pending" in response.text


def test_router_continue_invalid_outline_returns_400_before_stream(monkeypatch):
    research_router = import_research_router()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]
    state["outline_approval_status"] = "pending"
    graph = make_graph()
    monkeypatch.setattr(graph, "_load_checkpoint", lambda session_id: dict(state))

    class CheckpointStub:
        def get_checkpoint_info(self, session_id):
            return {"status": "paused"}

    class ServiceStub:
        def __init__(self):
            self.graph = graph

        async def continue_research(self, session_id, approved_outline, user_id=None, prepared_state=None):
            raise AssertionError("stream must not start for invalid outline")
            yield "data: [DONE]\n\n"

    monkeypatch.setattr(
        "service.checkpoint_service.get_checkpoint_service",
        lambda: CheckpointStub(),
    )
    monkeypatch.setattr(research_router, "get_research_service_v2", lambda: ServiceStub())

    app = FastAPI()
    app.include_router(research_router.router)
    client = TestClient(app)

    response = client.post(
        "/research/continue/s",
        json={"approved_outline": [{"id": "sec_1", "title": " "}]},
    )

    assert response.status_code == 400
    assert "title" in response.text


def test_router_continue_not_pending_state_returns_409_before_stream(monkeypatch):
    research_router = import_research_router()
    state = create_initial_state(query="q", session_id="s")
    state["outline"] = [{"id": "sec_1", "title": "Old", "description": ""}]
    state["outline_approval_status"] = "approved"
    graph = make_graph()
    monkeypatch.setattr(graph, "_load_checkpoint", lambda session_id: dict(state))

    class CheckpointStub:
        def get_checkpoint_info(self, session_id):
            return {"status": "paused"}

    class ServiceStub:
        def __init__(self):
            self.graph = graph

        async def continue_research(self, session_id, approved_outline, user_id=None, prepared_state=None):
            raise AssertionError("stream must not start when approval is not pending")
            yield "data: [DONE]\n\n"

    monkeypatch.setattr(
        "service.checkpoint_service.get_checkpoint_service",
        lambda: CheckpointStub(),
    )
    monkeypatch.setattr(research_router, "get_research_service_v2", lambda: ServiceStub())

    app = FastAPI()
    app.include_router(research_router.router)
    client = TestClient(app)

    response = client.post(
        "/research/continue/s",
        json={"approved_outline": [{"id": "sec_1", "title": "New"}]},
    )

    assert response.status_code == 409
    assert "Outline approval is not pending" in response.text


def test_router_resume_rejects_paused_outline_approval(monkeypatch):
    research_router = import_research_router()

    class CheckpointStub:
        def get_checkpoint_info(self, session_id):
            return {
                "status": "paused",
                "query": "q",
            }

    class ServiceStub:
        async def research(self, *args, **kwargs):
            raise AssertionError("paused approval checkpoints must not resume the graph")
            yield "data: [DONE]\n\n"

    monkeypatch.setattr(
        "service.checkpoint_service.get_checkpoint_service",
        lambda: CheckpointStub(),
    )
    monkeypatch.setattr(research_router, "get_research_service_v2", lambda: ServiceStub())

    app = FastAPI()
    app.include_router(research_router.router)
    client = TestClient(app)

    response = client.post("/research/resume/s")

    assert response.status_code == 409
    assert "outline approval" in response.text
