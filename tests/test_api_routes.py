from __future__ import annotations

import json
import os
import threading
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.core.state import MissionState, TaskState
import agentforce.server.handler as handler_mod
from agentforce.server import state_io
from agentforce.server.handler import DashboardHandler
from agentforce.server.routes import providers as providers_mod


def _spec() -> MissionSpec:
    return MissionSpec(
        name="API Mission",
        goal="Exercise API routes",
        definition_of_done=["All routes work"],
        tasks=[
            TaskSpec(
                id="task-1",
                title="Implement API",
                description="Add JSON routes",
                acceptance_criteria=["Return JSON"],
            ),
            TaskSpec(
                id="task-2",
                title="Keep HTML",
                description="Do not break HTML routes",
            ),
        ],
        caps=Caps(max_concurrent_workers=1),
    )


def _state(mission_id: str = "mission-123") -> MissionState:
    spec = _spec()
    return MissionState(
        mission_id=mission_id,
        spec=spec,
        task_states={
            "task-1": TaskState(task_id="task-1", spec_summary="Add JSON routes", status="review_approved"),
            "task-2": TaskState(task_id="task-2", spec_summary="Do not break HTML routes", status="in_progress"),
        },
        started_at="2024-01-01T00:00:00+00:00",
    )


def _make_handler(path: str) -> DashboardHandler:
    handler = object.__new__(DashboardHandler)
    handler.path = path
    handler.headers = {}
    handler.connection = object()
    handler.wfile = BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler._html = MagicMock()
    handler._err = MagicMock()
    return handler


def _response_body(handler: DashboardHandler) -> dict | list:
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def _sse_body(handler: DashboardHandler) -> str:
    return handler.wfile.getvalue().decode("utf-8")


def _set_handler_config(state_dir: Path) -> None:
    DashboardHandler.config = handler_mod.ServerConfig(
        state_dir=Path(state_dir),
        host="localhost",
        port=8080,
    )


def _seed_state(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _state().save(state_dir / "mission-123.json")
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)


def test_api_missions_returns_summaries_json_and_cors(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    handler = _make_handler("/api/missions")
    handler.do_GET()

    assert handler.send_response.call_args.args == (200,)
    assert handler.send_header.call_args_list[0].args == ("Content-Type", "application/json")
    assert ("Access-Control-Allow-Origin", "*") in [call.args for call in handler.send_header.call_args_list]

    body = _response_body(handler)
    assert isinstance(body, list)
    assert body[0]["mission_id"] == "mission-123"
    assert body[0]["name"] == "API Mission"


def test_api_mission_returns_full_state_json(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    handler = _make_handler("/api/mission/mission-123")
    handler.do_GET()

    body = _response_body(handler)
    assert body["mission_id"] == "mission-123"
    assert body["spec"]["name"] == "API Mission"
    assert body["task_states"]["task-1"]["status"] == "review_approved"
    assert ("Access-Control-Allow-Origin", "*") in [call.args for call in handler.send_header.call_args_list]


def test_api_task_returns_state_merged_with_spec_json(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    handler = _make_handler("/api/mission/mission-123/task/task-1")
    handler.do_GET()

    body = _response_body(handler)
    assert body["task_id"] == "task-1"
    assert body["title"] == "Implement API"
    assert body["description"] == "Add JSON routes"
    assert body["acceptance_criteria"] == ["Return JSON"]
    assert body["status"] == "review_approved"
    assert ("Access-Control-Allow-Origin", "*") in [call.args for call in handler.send_header.call_args_list]


def test_api_unknown_mission_returns_404_json(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    handler = _make_handler("/api/mission/missing")
    handler.do_GET()

    assert handler.send_response.call_args.args == (404,)
    assert _response_body(handler)["error"] == "Mission 'missing' not found"
    assert ("Access-Control-Allow-Origin", "*") in [call.args for call in handler.send_header.call_args_list]


def test_api_unknown_task_returns_404_json(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    handler = _make_handler("/api/mission/mission-123/task/missing")
    handler.do_GET()

    assert handler.send_response.call_args.args == (404,)
    assert _response_body(handler)["error"] == "Task 'missing' not found in mission 'mission-123'"
    assert ("Access-Control-Allow-Origin", "*") in [call.args for call in handler.send_header.call_args_list]


def test_api_task_retry_does_not_bypass_engine_cap_checks(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    spec = MissionSpec(
        name="Retry Mission",
        goal="Exercise retry route",
        definition_of_done=["Retry route is safe"],
        tasks=[
            TaskSpec(
                id="task-1",
                title="Retry task",
                description="Retry without bypassing cap logic",
                max_retries=2,
            )
        ],
        caps=Caps(max_retries_per_task=2, max_concurrent_workers=1),
    )
    state = MissionState(
        mission_id="mission-123",
        spec=spec,
        task_states={
            "task-1": TaskState(
                task_id="task-1",
                spec_summary="Retry without bypassing cap logic",
                status="failed",
                retries=2,
            )
        },
        started_at="2024-01-01T00:00:00+00:00",
        total_retries=3,
    )
    state.save(state_dir / "mission-123.json")
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)

    before_task_retries = state.task_states["task-1"].retries
    before_total_retries = state.total_retries

    handler = _make_handler("/api/mission/mission-123/task/task-1/retry")
    handler.do_POST()

    saved = MissionState.load(state_dir / "mission-123.json")
    task_state = saved.task_states["task-1"]
    assert task_state.retries == before_task_retries
    assert task_state.status in {"retry", "pending"}
    assert saved.total_retries == before_total_retries


def test_api_task_inject_uses_configured_state_dir(tmp_path, monkeypatch):
    home = tmp_path / ".agentforce-home"
    state_dir = tmp_path / "custom-state"
    home.mkdir()
    state_dir.mkdir()

    state = _state()
    state.save(state_dir / "mission-123.json")
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", home)
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.state_io.AGENTFORCE_HOME", home)
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)
    monkeypatch.setattr("agentforce.server.state_io._STATE_DIR_OVERRIDE", None, raising=False)

    payload = json.dumps({"message": "please retry"}).encode("utf-8")
    handler = _make_handler("/api/mission/mission-123/task/task-2/inject")
    handler.rfile = BytesIO(payload)
    handler.headers["Content-Length"] = str(len(payload))
    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)
    assert _response_body(handler) == {"delivered": True}
    assert (state_dir / "mission-123" / "task-2.inject").exists()
    assert not (home / "state" / "mission-123" / "task-2.inject").exists()


def test_api_task_inject_invalid_json_returns_400(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    payload = b"{"
    handler = _make_handler("/api/mission/mission-123/task/task-2/inject")
    handler.rfile = BytesIO(payload)
    handler.headers["Content-Length"] = str(len(payload))
    handler.do_POST()

    assert handler.send_response.call_args.args == (400,)
    assert _response_body(handler) == {"error": "invalid JSON body"}
    assert ("Access-Control-Allow-Origin", "*") in [call.args for call in handler.send_header.call_args_list]


def test_html_routes_still_render_html(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)
    monkeypatch.setattr("agentforce.server.handler._UI_DIST", tmp_path / "missing-ui-dist")

    handler = _make_handler("/mission/mission-123")
    handler.do_GET()

    assert handler.send_response.call_args.args == (200,)
    body = handler.wfile.getvalue().decode("utf-8")
    assert "API Mission" in body
    assert body.lower().startswith("<!doctype html") or body.lower().startswith("<html")


def test_route_modules_are_importable():
    from agentforce.server.routes import filesystem, missions, models, plan, providers, static, tasks

    assert missions.__name__.endswith("missions")
    assert tasks.__name__.endswith("tasks")
    assert providers.__name__.endswith("providers")
    assert models.__name__.endswith("models")
    assert filesystem.__name__.endswith("filesystem")
    assert plan.__name__.endswith("plan")
    assert static.__name__.endswith("static")


def test_model_routes_use_shared_provider_model_helper(monkeypatch):
    helper_calls: list[str] = []

    def fake_get_provider_models(provider_id: str) -> list[dict]:
        helper_calls.append(provider_id)
        return [{"id": f"{provider_id}-model", "name": provider_id, "cost_per_1k_input": 0.0, "cost_per_1k_output": 0.0, "latency_label": "Standard"}]

    monkeypatch.setattr(providers_mod, "_provider_metadata", lambda: {})
    monkeypatch.setattr(providers_mod, "_check_agent_binary", lambda _binary: True)
    monkeypatch.setattr(providers_mod, "_get_provider_models", fake_get_provider_models)

    models = providers_mod._models_list()
    providers = providers_mod._providers_list()

    assert any(model["id"] == "claude-model" for model in models)
    assert any(model["id"] == "codex-model" for model in models)
    assert next(item for item in providers if item["id"] == "claude")["all_models"][0]["id"] == "claude-model"
    assert next(item for item in providers if item["id"] == "codex")["all_models"][0]["id"] == "codex-model"
    assert helper_calls == ["claude", "codex", "claude", "codex"]


def test_get_provider_models_serializes_fetch_and_save(monkeypatch):
    store: dict[str, dict] = {}
    fetch_count = 0
    save_count = 0
    entered_fetch = threading.Event()
    release_fetch = threading.Event()

    def fake_provider_metadata() -> dict[str, dict]:
        return json.loads(json.dumps(store))

    def fake_save_provider_metadata(data: dict[str, dict]) -> None:
        nonlocal save_count
        save_count += 1
        store.clear()
        store.update(json.loads(json.dumps(data)))

    def fake_fetch() -> list[dict]:
        nonlocal fetch_count
        fetch_count += 1
        entered_fetch.set()
        release_fetch.wait(timeout=1)
        return [{"id": "claude-opus-4-5", "name": "Claude Opus 4.5", "cost_per_1k_input": 0.0, "cost_per_1k_output": 0.0, "latency_label": "Powerful"}]

    monkeypatch.setattr(providers_mod, "_provider_metadata", fake_provider_metadata)
    monkeypatch.setattr(providers_mod.state_io, "_save_providers_metadata", fake_save_provider_metadata)
    monkeypatch.setattr(providers_mod, "_fetch_claude_code_models", fake_fetch)

    results: list[list[dict]] = []

    def load_models() -> None:
        results.append(providers_mod._get_provider_models("claude"))

    first = threading.Thread(target=load_models)
    second = threading.Thread(target=load_models)

    first.start()
    assert entered_fetch.wait(timeout=1)
    second.start()
    release_fetch.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert fetch_count == 1
    assert save_count == 1
    assert len(results) == 2
    assert results[0] == results[1]
    assert store["claude"]["cached_models"][0]["id"] == "claude-opus-4-5"


def test_fetch_codex_models_reads_current_cache_schema_and_skips_hidden_models(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-04-10T11:05:37.777990Z",
                "client_version": "0.118.0",
                "models": [
                    {
                        "slug": "gpt-5.4",
                        "display_name": "GPT-5.4",
                        "description": "Latest frontier agentic coding model.",
                        "visibility": "list",
                    },
                    {
                        "slug": "gpt-5.4-mini",
                        "display_name": "GPT-5.4-Mini",
                        "description": "Smaller frontier agentic coding model.",
                        "visibility": "list",
                    },
                    {
                        "slug": "gpt-5.2-codex",
                        "display_name": "gpt-5.2-codex",
                        "visibility": "hide",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(providers_mod.Path, "home", lambda: tmp_path)

    models = providers_mod._fetch_codex_models()

    assert [model["id"] for model in models] == ["gpt-5.4", "gpt-5.4-mini"]
    assert models[0]["name"] == "GPT-5.4"
    assert models[0]["latency_label"] == "Standard"
    assert models[1]["latency_label"] == "Fast"


def test_fetch_codex_models_supports_legacy_cache_shape(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "legacy-model",
                        "name": "Legacy Model",
                        "cost_per_1k_input": 1.25,
                        "cost_per_1k_output": 2.5,
                        "latency_label": "Fast",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(providers_mod.Path, "home", lambda: tmp_path)

    models = providers_mod._fetch_codex_models()

    assert models == [
        {
            "id": "legacy-model",
            "name": "Legacy Model",
            "cost_per_1k_input": 1.25,
            "cost_per_1k_output": 2.5,
            "latency_label": "Fast",
        }
    ]


def test_serve_does_not_mutate_module_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(handler_mod, "_watch_state_dir", lambda **_kwargs: None)

    class _FakeServer:
        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(handler_mod, "ThreadingHTTPServer", lambda *_args, **_kwargs: _FakeServer())

    target_state_dir = tmp_path / "state"

    handler_mod.serve(port=0, state_dir=target_state_dir)

    assert DashboardHandler.config.state_dir == target_state_dir
    assert DashboardHandler.config.host == "localhost"
    assert DashboardHandler.config.port == 0
    assert state_io.STATE_DIR != target_state_dir


def test_handler_module_stays_small():
    handler_path = Path(handler_mod.__file__)
    assert sum(1 for _ in handler_path.open()) < 350


# ── /api/config default_caps tests ────────────────────────────────────────────

def _patch_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path)
    monkeypatch.setattr("agentforce.server.state_io.AGENTFORCE_HOME", tmp_path)


def _json_request(handler: DashboardHandler, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.rfile = BytesIO(body)
    handler.headers["Content-Length"] = str(len(body))


def test_api_plan_drafts_list_empty(tmp_path, monkeypatch):
    _patch_home(monkeypatch, tmp_path)
    
    handler = _make_handler("/api/plan/drafts")
    handler.do_GET()
    
    assert handler.send_response.call_args.args == (200,)
    body = _response_body(handler)
    assert body == []


def test_api_plan_drafts_list_returns_summaries(tmp_path, monkeypatch):
    from agentforce.server.routes import plan as plan_routes
    
    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda _run_id: None)
    
    # Create two drafts
    for i in range(2):
        create_handler = _make_handler("/api/plan/drafts")
        payload = json.dumps({"prompt": f"Draft {i}"}).encode("utf-8")
        create_handler.rfile = BytesIO(payload)
        create_handler.headers["Content-Length"] = str(len(payload))
        create_handler.do_POST()
        assert create_handler.send_response.call_args.args == (200,)

    list_handler = _make_handler("/api/plan/drafts")
    list_handler.do_GET()

    assert list_handler.send_response.call_args.args == (200,)
    body = _response_body(list_handler)
    assert isinstance(body, list)
    assert len(body) == 2
    
    # Sort by name for consistent testing if needed, though list_all sorts by updated_at desc
    body.sort(key=lambda x: x["name"])
    
    for i, item in enumerate(body):
        assert "id" in item
        assert item["name"] == f"Draft {i}"
        assert item["goal"] == f"Draft {i}"
        assert item["status"] == "draft"
        assert "created_at" in item
        assert "updated_at" in item
        # Verify ISO format
        from datetime import datetime
        assert datetime.fromisoformat(item["created_at"])
        assert datetime.fromisoformat(item["updated_at"])


def test_api_plan_drafts_list_filtering(tmp_path, monkeypatch):
    from agentforce.server.routes import plan as plan_routes
    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda _run_id: None)

    # Create one normal draft, one finalized, one cancelled
    statuses = ["draft", "finalized", "cancelled"]
    for status in statuses:
        create_handler = _make_handler("/api/plan/drafts")
        payload = json.dumps({"prompt": f"Mission {status}"}).encode("utf-8")
        create_handler.rfile = BytesIO(payload)
        create_handler.headers["Content-Length"] = str(len(payload))
        create_handler.do_POST()
        created = _response_body(create_handler)
        
        if status != "draft":
            # Manually update status in the filesystem
            draft_path = tmp_path / "drafts" / f"{created['id']}.json"
            data = json.loads(draft_path.read_text())
            data["status"] = status
            draft_path.write_text(json.dumps(data))

    # Default: should only return "draft"
    list_handler = _make_handler("/api/plan/drafts")
    list_handler.do_GET()
    body = _response_body(list_handler)
    assert len(body) == 1
    assert body[0]["status"] == "draft"

    # include_terminal=true: should return all 3
    list_all_handler = _make_handler("/api/plan/drafts?include_terminal=true")
    list_all_handler.do_GET()
    body_all = _response_body(list_all_handler)
    assert len(body_all) == 3
    assert {b["status"] for b in body_all} == {"draft", "finalized", "cancelled"}

    # include_terminal=false: should only return "draft"
    list_none_handler = _make_handler("/api/plan/drafts?include_terminal=false")
    list_none_handler.do_GET()
    body_none = _response_body(list_none_handler)
    assert len(body_none) == 1
    assert body_none[0]["status"] == "draft"


def test_plan_draft_create_and_get_round_trip(tmp_path, monkeypatch):
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda _run_id: None)

    create_payload = {
        "prompt": "Draft a calculator mission",
        "approved_models": ["claude-sonnet"],
        "workspace_paths": ["/workspace/app"],
        "companion_profile": {"id": "planner", "label": "Planner"},
    }
    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, create_payload)

    create_handler.do_POST()

    assert create_handler.send_response.call_args.args == (200,)
    created_body = _response_body(create_handler)
    assert created_body["id"]
    assert created_body["revision"] == 1
    assert created_body["plan_run_id"]

    get_handler = _make_handler(f"/api/plan/drafts/{created_body['id']}")
    get_handler.do_GET()

    assert get_handler.send_response.call_args.args == (200,)
    loaded_body = _response_body(get_handler)
    assert loaded_body["id"] == created_body["id"]
    assert loaded_body["revision"] == 1
    assert loaded_body["draft_spec"]["goal"] == "Draft a calculator mission"
    assert loaded_body["approved_models"] == ["claude-sonnet"]
    assert loaded_body["workspace_paths"] == ["/workspace/app"]
    assert loaded_body["companion_profile"] == {"id": "planner", "label": "Planner"}
    assert len(loaded_body["plan_runs"]) == 1


def test_plan_draft_create_with_preflight_questions_blocks_initial_run(tmp_path, monkeypatch):
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        plan_routes,
        "discover_preflight_questions",
        lambda _draft: [
            {
                "id": "scope_mode",
                "prompt": "Should the first release focus on project selection or project data model changes?",
                "options": ["Selection only", "Both together"],
                "reason": "This changes the task graph and dependencies.",
                "allow_custom": True,
            }
        ],
    )
    enqueued: list[str] = []
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda run_id: enqueued.append(run_id))

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Plan project support"})
    create_handler.do_POST()

    body = _response_body(create_handler)
    assert body["requires_preflight"] is True
    assert "plan_run_id" not in body
    assert enqueued == []

    get_handler = _make_handler(f"/api/plan/drafts/{body['id']}")
    get_handler.do_GET()
    loaded = _response_body(get_handler)
    assert loaded["preflight_status"] == "pending"
    assert len(loaded["preflight_questions"]) == 1


def test_plan_draft_preflight_submission_enqueues_initial_run(tmp_path, monkeypatch):
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        plan_routes,
        "discover_preflight_questions",
        lambda _draft: [
            {
                "id": "scope_mode",
                "prompt": "Should the first release focus on project selection or project data model changes?",
                "options": ["Selection only", "Both together"],
                "reason": "This changes the task graph and dependencies.",
                "allow_custom": True,
            }
        ],
    )
    enqueued: list[str] = []
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda run_id: enqueued.append(run_id))

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Plan project support", "auto_start": True})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    submit_handler = _make_handler(f"/api/plan/drafts/{draft_id}/preflight")
    _json_request(submit_handler, {"answers": {"scope_mode": {"selected_option": "Selection only"}}})
    submit_handler.do_POST()

    body = _response_body(submit_handler)
    assert body["status"] == "queued"
    assert body["plan_run_id"]
    assert enqueued == [body["plan_run_id"]]

    get_handler = _make_handler(f"/api/plan/drafts/{draft_id}")
    get_handler.do_GET()
    loaded = _response_body(get_handler)
    assert loaded["preflight_status"] == "answered"
    assert loaded["preflight_answers"]["scope_mode"]["selected_option"] == "Selection only"
    assert loaded["turns"][-1]["content"].startswith("Preflight answers:")


def test_plan_draft_messages_blocked_while_preflight_pending(tmp_path, monkeypatch):
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        plan_routes,
        "discover_preflight_questions",
        lambda _draft: [
            {
                "id": "scope_mode",
                "prompt": "Should the first release focus on project selection or project data model changes?",
                "options": ["Selection only", "Both together"],
                "reason": "This changes the task graph and dependencies.",
                "allow_custom": True,
            }
        ],
    )

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Plan project support"})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    message_handler = _make_handler(f"/api/plan/drafts/{draft_id}/messages")
    _json_request(message_handler, {"content": "Start now"})
    message_handler.do_POST()

    assert message_handler.send_response.call_args.args == (409,)
    assert "preflight" in _response_body(message_handler)["error"]


def test_plan_draft_messages_enqueue_and_persist_checkpoint(tmp_path, monkeypatch):
    from agentforce.server import planner_adapter as planner_adapter_mod
    from agentforce.server import planning_runtime
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)

    class FakePlanner(planner_adapter_mod.PlannerAdapter):
        def plan_turn(self, draft: dict, user_message: str) -> planner_adapter_mod.PlannerTurnResult:
            updated = dict(draft["draft_spec"])
            updated["name"] = "Calculator Draft"
            updated["tasks"] = [
                {
                    "id": "01",
                    "title": "Add parser",
                    "description": "Parse CLI args",
                    "acceptance_criteria": ["pytest tests/test_cli.py -k parser passes"],
                }
            ]
            return planner_adapter_mod.PlannerTurnResult(
                events=[
                    planner_adapter_mod.PlannerEvent(phase="planning", status="started"),
                    planner_adapter_mod.PlannerEvent(
                        phase="planning",
                        status="completed",
                        content="I updated the draft with an initial task.",
                    ),
                ],
                assistant_message="I updated the draft with an initial task.",
                draft_spec=updated,
            )

    monkeypatch.setattr(planner_adapter_mod, "get_planner_adapter", lambda: FakePlanner())
    monkeypatch.setattr(
        planning_runtime,
        "_invoke_profile",
        lambda *_args, **_kwargs: (
            json.dumps({"summary": "Critic complete", "issues": [], "suggestions": []}),
            planning_runtime.TokenEvent(tokens_in=11, tokens_out=7, cost_usd=0.0),
        ),
    )
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda run_id: planning_runtime.run_plan_run(run_id))

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build a calculator mission", "auto_start": False})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    message_handler = _make_handler(f"/api/plan/drafts/{draft_id}/messages")
    _json_request(message_handler, {"content": "Add a parsing task"})
    message_handler.do_POST()

    assert message_handler.send_response.call_args.args == (200,)
    queued_body = _response_body(message_handler)
    assert queued_body["status"] == "queued"
    assert queued_body["plan_run_id"]

    get_handler = _make_handler(f"/api/plan/drafts/{draft_id}")
    get_handler.do_GET()
    loaded_body = _response_body(get_handler)
    assert loaded_body["revision"] == 3
    assert loaded_body["draft_spec"]["name"] == "Calculator Draft"
    assert loaded_body["turns"][-1]["role"] == "assistant"
    assert loaded_body["planning_summary"]["latest_plan_version_id"]


def test_planner_adapter_default_is_live_boundary():
    from agentforce.server import planner_adapter as planner_adapter_mod

    adapter = planner_adapter_mod.get_planner_adapter()

    assert adapter.__class__.__name__ == "LivePlannerAdapter"
    assert not isinstance(adapter, planner_adapter_mod.DeterministicPlannerAdapter)


def test_plan_draft_messages_retries_persistence_on_revision_conflict(tmp_path, monkeypatch):
    from agentforce.server.plan_drafts import PlanDraftStore
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    store = PlanDraftStore()
    monkeypatch.setattr(plan_routes, "_store", lambda: store)
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda _run_id: None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build a calculator mission"})
    create_handler.do_POST()
    created = _response_body(create_handler)
    draft_id = created["id"]

    original_save = store.save
    save_calls = {"count": 0}

    def conflict_then_save(draft, *, expected_revision):
        save_calls["count"] += 1
        if save_calls["count"] == 1:
            concurrent = store.load(draft.id)
            assert concurrent is not None
            original_save(
                concurrent.copy_with(
                    draft_spec={
                        **concurrent.draft_spec,
                        "goal": "Concurrent edit",
                    },
                    activity_log=list(concurrent.activity_log) + [{"type": "concurrent_edit"}],
                ),
                expected_revision=expected_revision,
            )
        return original_save(draft, expected_revision=expected_revision)

    monkeypatch.setattr(store, "save", conflict_then_save)

    patch_handler = _make_handler(f"/api/plan/drafts/{draft_id}/spec")
    _json_request(
        patch_handler,
        {
            "expected_revision": 1,
            "draft_spec": {
                "name": "Retried Calculator Draft",
                "goal": "Refine the draft",
                "definition_of_done": [],
                "tasks": [],
                "caps": {},
            },
        },
    )
    patch_handler.do_PATCH()

    persisted = store.load(draft_id)
    assert persisted is not None
    assert persisted.revision == 2
    assert persisted.draft_spec["goal"] == "Concurrent edit"
    assert persisted.draft_spec["name"] == "Build A Calculator Mission"


def test_plan_draft_spec_patch_rejects_stale_revision(tmp_path, monkeypatch):
    _patch_home(monkeypatch, tmp_path)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build a calculator mission"})
    create_handler.do_POST()
    created = _response_body(create_handler)

    patch_handler = _make_handler(f"/api/plan/drafts/{created['id']}/spec")
    _json_request(
        patch_handler,
        {
            "expected_revision": created["revision"],
            "draft_spec": {
                "name": "Calculator Mission",
                "goal": "Build a calculator mission",
                "definition_of_done": [],
                "tasks": [],
                "caps": {},
            },
        },
    )
    patch_handler.do_PATCH()
    assert patch_handler.send_response.call_args.args == (200,)

    stale_handler = _make_handler(f"/api/plan/drafts/{created['id']}/spec")
    _json_request(
        stale_handler,
        {
            "expected_revision": created["revision"],
            "draft_spec": {
                "name": "Stale Write",
                "goal": "Should conflict",
                "definition_of_done": [],
                "tasks": [],
                "caps": {},
            },
        },
    )
    stale_handler.do_PATCH()

    assert stale_handler.send_response.call_args.args == (409,)
    assert _response_body(stale_handler)["error"] == "draft revision conflict"


def test_plan_draft_import_yaml_replaces_spec_only_when_valid(tmp_path, monkeypatch):
    _patch_home(monkeypatch, tmp_path)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build a calculator mission"})
    create_handler.do_POST()
    created = _response_body(create_handler)

    invalid_handler = _make_handler(f"/api/plan/drafts/{created['id']}/import-yaml")
    _json_request(
        invalid_handler,
        {"expected_revision": created["revision"], "yaml": "name: Broken\n"},
    )
    invalid_handler.do_POST()

    assert invalid_handler.send_response.call_args.args == (400,)
    invalid_body = _response_body(invalid_handler)
    assert invalid_body["error"].startswith("invalid mission yaml:")

    unchanged_handler = _make_handler(f"/api/plan/drafts/{created['id']}")
    unchanged_handler.do_GET()
    unchanged_body = _response_body(unchanged_handler)
    assert unchanged_body["revision"] == 1
    assert unchanged_body["draft_spec"]["goal"] == "Build a calculator mission"

    valid_yaml = """
name: Calculator Mission
goal: Build a Rust CLI calculator
definition_of_done:
  - cargo test passes
tasks:
  - id: "01"
    title: Parse args
    description: Parse CLI args
    acceptance_criteria:
      - cargo test --test cli passes
caps:
  max_concurrent_workers: 1
"""
    valid_handler = _make_handler(f"/api/plan/drafts/{created['id']}/import-yaml")
    _json_request(
        valid_handler,
        {"expected_revision": created["revision"], "yaml": valid_yaml},
    )
    valid_handler.do_POST()

    assert valid_handler.send_response.call_args.args == (200,)
    valid_body = _response_body(valid_handler)
    assert valid_body["revision"] == 2
    assert valid_body["draft_spec"]["name"] == "Calculator Mission"
    assert valid_body["draft_spec"]["tasks"][0]["id"] == "01"


def test_planner_readjust_trajectory_seeds_new_draft_from_mission_spec(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)
    _patch_home(monkeypatch, tmp_path)

    readjust_handler = _make_handler("/api/mission/mission-123/readjust-trajectory")
    readjust_handler.do_POST()

    assert readjust_handler.send_response.call_args.args == (200,)
    readjusted = _response_body(readjust_handler)
    assert readjusted["id"]
    assert readjusted["revision"] == 1

    get_handler = _make_handler(f"/api/plan/drafts/{readjusted['id']}")
    get_handler.do_GET()
    draft_body = _response_body(get_handler)
    assert draft_body["draft_spec"]["name"] == "API Mission"
    assert draft_body["draft_spec"]["goal"] == "Exercise API routes"
    assert draft_body["draft_spec"]["tasks"][0]["id"] == "task-1"


def test_plan_draft_launch_rust_calculator_flow_with_fake_planner(tmp_path, monkeypatch):
    from agentforce.server import planner_adapter as planner_adapter_mod
    from agentforce.server import planning_runtime
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    state_dir = tmp_path / "state"
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)
    monkeypatch.setattr("agentforce.autonomous.run_autonomous", lambda *_args, **_kwargs: None)

    class FakePlanner(planner_adapter_mod.PlannerAdapter):
        def plan_turn(self, draft: dict, user_message: str) -> planner_adapter_mod.PlannerTurnResult:
            if "second task" not in user_message.lower():
                draft_spec = {
                    "name": "Rust Calculator Draft",
                    "goal": "Draft a Rust CLI calculator mission",
                    "definition_of_done": [
                        "cargo test passes",
                        "cargo run -- --help prints usage text",
                    ],
                    "tasks": [
                        {
                            "id": "01",
                            "title": "Parse CLI arguments",
                            "description": "Parse calculator operands and flags from the command line.",
                            "acceptance_criteria": [
                                "cargo test --test cli passes",
                            ],
                            "execution": {
                                "worker": {
                                    "agent": "codex",
                                    "model": "rust-calculator-worker-v1",
                                    "thinking": "medium",
                                }
                            },
                        }
                    ],
                    "execution_defaults": {
                        "worker": {
                            "agent": "codex",
                            "model": "rust-calculator-worker-default",
                            "thinking": "high",
                        },
                        "reviewer": {
                            "agent": "codex",
                            "model": "rust-calculator-reviewer-default",
                            "thinking": "low",
                        },
                    },
                    "caps": {"max_concurrent_workers": 1},
                }
                message = f"Seeded a Rust calculator draft from: {user_message}"
            else:
                draft_spec = {
                    "name": "Rust Calculator Draft",
                    "goal": "Draft a Rust CLI calculator mission",
                    "definition_of_done": [
                        "cargo test passes",
                        "cargo run -- --help prints usage text",
                    ],
                    "tasks": [
                        {
                            "id": "01",
                            "title": "Parse CLI arguments",
                            "description": "Parse calculator operands and flags from the command line.",
                            "acceptance_criteria": [
                                "cargo test --test cli passes",
                            ],
                            "execution": {
                                "worker": {
                                    "agent": "codex",
                                    "model": "rust-calculator-worker-v2",
                                    "thinking": "high",
                                }
                            },
                        },
                        {
                            "id": "02",
                            "title": "Implement arithmetic operations",
                            "description": "Add add, subtract, multiply, and divide operations.",
                            "acceptance_criteria": [
                                "cargo test --test calculator passes",
                                "cargo run -- 2 + 2 prints 4",
                            ],
                            "execution": {
                                "reviewer": {
                                    "agent": "codex",
                                    "model": "rust-calculator-reviewer-v2",
                                    "thinking": "medium",
                                }
                            },
                        },
                    ],
                    "execution_defaults": {
                        "worker": {
                            "agent": "codex",
                            "model": "rust-calculator-worker-default",
                            "thinking": "high",
                        },
                        "reviewer": {
                            "agent": "codex",
                            "model": "rust-calculator-reviewer-default",
                            "thinking": "low",
                        },
                    },
                    "caps": {"max_concurrent_workers": 1},
                }
                message = f"Refined the Rust calculator draft from: {user_message}"

            return planner_adapter_mod.PlannerTurnResult(
                events=[
                    planner_adapter_mod.PlannerEvent(phase="planning", status="started"),
                    planner_adapter_mod.PlannerEvent(
                        phase="planning",
                        status="completed",
                        content=message,
                    ),
                ],
                assistant_message=message,
                draft_spec=draft_spec,
            )

    monkeypatch.setattr(planner_adapter_mod, "get_planner_adapter", lambda: FakePlanner())
    monkeypatch.setattr(
        planning_runtime,
        "_invoke_profile",
        lambda *_args, **_kwargs: (
            json.dumps({"summary": "Critic complete", "issues": [], "suggestions": []}),
            planning_runtime.TokenEvent(tokens_in=9, tokens_out=5, cost_usd=0.0),
        ),
    )
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda run_id: planning_runtime.run_plan_run(run_id))
    monkeypatch.setattr("agentforce.autonomous.run_autonomous", lambda *_args, **_kwargs: None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Draft a Rust CLI calculator mission", "auto_start": False})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    first_turn_handler = _make_handler(f"/api/plan/drafts/{draft_id}/messages")
    _json_request(first_turn_handler, {"content": "Seed the calculator with a parser task"})
    first_turn_handler.do_POST()
    assert first_turn_handler.send_response.call_args.args == (200,)

    second_turn_handler = _make_handler(f"/api/plan/drafts/{draft_id}/messages")
    _json_request(second_turn_handler, {"content": "Add a second task and execution details"})
    second_turn_handler.do_POST()

    assert second_turn_handler.send_response.call_args.args == (200,)
    get_handler = _make_handler(f"/api/plan/drafts/{draft_id}")
    get_handler.do_GET()
    revised_draft = _response_body(get_handler)

    assert revised_draft["revision"] == 5
    assert len(revised_draft["draft_spec"]["tasks"]) >= 2
    assert all(task["acceptance_criteria"] for task in revised_draft["draft_spec"]["tasks"])

    launch_handler = _make_handler(f"/api/plan/drafts/{draft_id}/start")
    launch_handler.do_POST()

    assert launch_handler.send_response.call_args.args == (200,)
    launch_body = _response_body(launch_handler)
    mission_id = launch_body["mission_id"]
    state_path = state_dir / f"{mission_id}.json"
    assert state_path.exists()

    mission_state = MissionState.load(state_path)
    mission_dict = mission_state.to_dict()

    assert mission_dict["spec"]["goal"] == "Draft a Rust CLI calculator mission"
    assert len(mission_dict["spec"]["tasks"]) >= 2
    assert all(task["acceptance_criteria"] for task in mission_dict["spec"]["tasks"])
    assert mission_dict["spec"]["definition_of_done"] == [
        "cargo test passes",
        "cargo run -- --help prints usage text",
    ]
    assert mission_dict["execution_defaults"]["worker"]["model"] == "rust-calculator-worker-default"
    assert mission_dict["execution_defaults"]["reviewer"]["model"] == "rust-calculator-reviewer-default"
    assert mission_dict["execution"]["defaults"]["worker"]["model"] == "rust-calculator-worker-default"
    assert mission_dict["execution"]["defaults"]["reviewer"]["model"] == "rust-calculator-reviewer-default"
    assert mission_dict["execution"]["tasks"]["01"]["worker"]["model"] == "rust-calculator-worker-v2"
    assert mission_dict["execution"]["tasks"]["02"]["reviewer"]["model"] == "rust-calculator-reviewer-v2"
    assert mission_dict["execution"]["task_overrides"] == {"worker": 1, "reviewer": 1}
    assert mission_dict["source_draft_id"] == draft_id
    assert mission_dict["source_plan_version_id"] == revised_draft["validation"]["latest_plan_version_id"]

    readjust_handler = _make_handler(f"/api/mission/{mission_id}/readjust-trajectory")
    readjust_handler.do_POST()
    assert readjust_handler.send_response.call_args.args == (200,)
    readjusted = _response_body(readjust_handler)

    seeded_handler = _make_handler(f"/api/plan/drafts/{readjusted['id']}")
    seeded_handler.do_GET()
    seeded_draft = _response_body(seeded_handler)

    assert seeded_draft["revision"] == 1
    assert seeded_draft["draft_spec"] == mission_dict["spec"]


def test_plan_draft_launch_rust_calculator_real_companion_smoke_manual_only():
    """Opt-in manual smoke for a real companion model; not part of CI."""
    if os.environ.get("AGENTFORCE_REAL_COMPANION_SMOKE") != "1":
        pytest.skip("Set AGENTFORCE_REAL_COMPANION_SMOKE=1 to run the manual smoke.")
    pytest.skip("Manual smoke placeholder: run the same launch flow locally with a live companion adapter.")


def test_get_config_returns_default_caps(tmp_path, monkeypatch):
    _patch_home(monkeypatch, tmp_path)

    handler = _make_handler("/api/config")
    handler.do_GET()

    assert handler.send_response.call_args.args == (200,)
    body = _response_body(handler)
    assert "default_caps" in body
    caps = body["default_caps"]
    assert caps["max_concurrent_workers"] == 2
    assert caps["max_retries_per_task"] == 2
    assert caps["max_wall_time_minutes"] == 60
    assert caps["max_cost_usd"] == 0


def test_get_config_creates_file_if_missing(tmp_path, monkeypatch):
    _patch_home(monkeypatch, tmp_path)
    assert not (tmp_path / "config.json").exists()

    handler = _make_handler("/api/config")
    handler.do_GET()

    assert handler.send_response.call_args.args == (200,)
    assert (tmp_path / "config.json").exists()


def test_post_config_valid_updates_caps(tmp_path, monkeypatch):
    _patch_home(monkeypatch, tmp_path)

    new_caps = {
        "max_concurrent_workers": 4,
        "max_retries_per_task": 3,
        "max_wall_time_minutes": 120,
        "max_cost_usd": 10.0,
    }
    payload = json.dumps({"default_caps": new_caps}).encode("utf-8")
    handler = _make_handler("/api/config")
    handler.rfile = BytesIO(payload)
    handler.headers["Content-Length"] = str(len(payload))
    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)
    body = _response_body(handler)
    assert body["default_caps"]["max_concurrent_workers"] == 4

    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["default_caps"]["max_concurrent_workers"] == 4


def test_post_config_invalid_concurrent_workers_returns_400(tmp_path, monkeypatch):
    _patch_home(monkeypatch, tmp_path)

    payload = json.dumps({"default_caps": {"max_concurrent_workers": 0}}).encode("utf-8")
    handler = _make_handler("/api/config")
    handler.rfile = BytesIO(payload)
    handler.headers["Content-Length"] = str(len(payload))
    handler.do_POST()

    assert handler.send_response.call_args.args == (400,)
    body = _response_body(handler)
    assert "error" in body


# ---------------------------------------------------------------------------
# Task 05 — Auto-draft workspace context
# ---------------------------------------------------------------------------

def test_auto_draft_working_dir_from_workspace_paths(tmp_path, monkeypatch):
    """draft_spec['working_dir'] should equal workspace_paths[0] when provided."""
    _patch_home(monkeypatch, tmp_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {
        "prompt": "Build something",
        "workspace_paths": [str(workspace)],
    })
    create_handler.do_POST()

    assert create_handler.send_response.call_args.args == (200,)
    created = _response_body(create_handler)

    get_handler = _make_handler(f"/api/plan/drafts/{created['id']}")
    get_handler.do_GET()
    loaded = _response_body(get_handler)

    assert loaded["draft_spec"]["working_dir"] == str(workspace)


def test_auto_draft_no_workspace_paths_working_dir_is_none(tmp_path, monkeypatch):
    """draft_spec['working_dir'] should be None when workspace_paths is absent."""
    _patch_home(monkeypatch, tmp_path)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build something"})
    create_handler.do_POST()

    assert create_handler.send_response.call_args.args == (200,)
    created = _response_body(create_handler)

    get_handler = _make_handler(f"/api/plan/drafts/{created['id']}")
    get_handler.do_GET()
    loaded = _response_body(get_handler)

    assert loaded["draft_spec"]["working_dir"] is None


def test_auto_draft_caps_small_workspace(tmp_path, monkeypatch):
    """max_concurrent_workers == 1 for a workspace with fewer than 50 files."""
    _patch_home(monkeypatch, tmp_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for i in range(10):
        (workspace / f"file_{i}.py").write_text("# placeholder")

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {
        "prompt": "Build something small",
        "workspace_paths": [str(workspace)],
    })
    create_handler.do_POST()

    created = _response_body(create_handler)
    get_handler = _make_handler(f"/api/plan/drafts/{created['id']}")
    get_handler.do_GET()
    loaded = _response_body(get_handler)

    assert loaded["draft_spec"]["caps"]["max_concurrent_workers"] == 1


def test_auto_draft_caps_medium_workspace(tmp_path, monkeypatch):
    """max_concurrent_workers == 2 for a workspace with >= 50 files."""
    _patch_home(monkeypatch, tmp_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for i in range(60):
        (workspace / f"file_{i}.py").write_text("# placeholder")

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {
        "prompt": "Build something medium",
        "workspace_paths": [str(workspace)],
    })
    create_handler.do_POST()

    created = _response_body(create_handler)
    get_handler = _make_handler(f"/api/plan/drafts/{created['id']}")
    get_handler.do_GET()
    loaded = _response_body(get_handler)

    assert loaded["draft_spec"]["caps"]["max_concurrent_workers"] == 2


def test_auto_draft_has_initial_assistant_turn(tmp_path, monkeypatch):
    """Draft should have at least one turn with role='assistant' after creation."""
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(plan_routes, "_enqueue_plan_run", lambda _run_id: None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build something"})
    create_handler.do_POST()

    assert create_handler.send_response.call_args.args == (200,)
    created = _response_body(create_handler)

    get_handler = _make_handler(f"/api/plan/drafts/{created['id']}")
    get_handler.do_GET()
    loaded = _response_body(get_handler)

    assert len(loaded["turns"]) >= 1
    assert loaded["turns"][0]["role"] == "assistant"


def test_draft_init_live_planner_system_prompt_contains_draft_spec(tmp_path, monkeypatch):
    """LivePlannerAdapter.plan_turn() should include the draft_spec in the system prompt."""
    from agentforce.server import planner_adapter as planner_adapter_mod
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)

    captured_system_prompts: list[str] = []

    original_build = planner_adapter_mod._build_system_prompt

    def capturing_build_system_prompt(draft: dict) -> str:
        result = original_build(draft)
        captured_system_prompts.append(result)
        return result

    monkeypatch.setattr(planner_adapter_mod, "_build_system_prompt", capturing_build_system_prompt)

    # Stub out the actual HTTP completion so no real API call is made
    def fake_openrouter(api_key, model, system_prompt, prompt):
        return json.dumps({
            "assistant_message": "Draft reviewed.",
            "draft_spec": {
                "name": "Test Mission",
                "goal": "Build something",
                "definition_of_done": [],
                "tasks": [],
                "caps": {},
            },
        })

    def fake_anthropic(api_key, model, system_prompt, prompt):
        return fake_openrouter(api_key, model, system_prompt, prompt)

    def fake_claude_cli(model, system_prompt, prompt):
        return fake_openrouter(None, model, system_prompt, prompt)

    monkeypatch.setattr(planner_adapter_mod, "_openrouter_completion", fake_openrouter)
    monkeypatch.setattr(planner_adapter_mod, "_anthropic_completion", fake_anthropic)
    monkeypatch.setattr(planner_adapter_mod, "_claude_cli_completion", fake_claude_cli)

    # Ensure the live adapter is used
    monkeypatch.setattr(
        plan_routes.planner_adapter,
        "get_planner_adapter",
        lambda: planner_adapter_mod.LivePlannerAdapter(),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    # Create a draft then send a message to trigger plan_turn
    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build something"})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    message_handler = _make_handler(f"/api/plan/drafts/{draft_id}/messages")
    _json_request(message_handler, {"content": "Refine the plan"})
    message_handler.do_POST()

    assert message_handler.send_response.call_args.args == (200,)
    assert captured_system_prompts, "expected _build_system_prompt to be called"
    assert "draft_spec" in captured_system_prompts[0]


# ---------------------------------------------------------------------------
# Task 06 — Plan start endpoint: draft → mission transition
# ---------------------------------------------------------------------------

_VALID_DRAFT_SPEC = {
    "name": "Calculator Mission",
    "goal": "Build a CLI calculator",
    "definition_of_done": ["All tests pass"],
    "tasks": [
        {
            "id": "t1",
            "title": "Implement add",
            "description": "Implement the add function",
            "acceptance_criteria": ["add(1,2) == 3"],
        }
    ],
}


def _make_started_draft(tmp_path, monkeypatch):
    """Create a draft with a valid spec and start it; return (draft_id, response_body)."""
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)
    monkeypatch.setattr("agentforce.autonomous.run_autonomous", lambda *a, **k: None)
    monkeypatch.setattr(plan_routes, "_active_daemon", None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build a CLI calculator"})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    patch_handler = _make_handler(f"/api/plan/drafts/{draft_id}/spec")
    _json_request(patch_handler, {"expected_revision": 1, "draft_spec": _VALID_DRAFT_SPEC})
    patch_handler.do_PATCH()
    assert patch_handler.send_response.call_args.args == (200,)

    start_handler = _make_handler(f"/api/plan/drafts/{draft_id}/start")
    start_handler.do_POST()
    return draft_id, _response_body(start_handler), start_handler, state_dir


def test_plan_start_returns_200_with_mission_id(tmp_path, monkeypatch):
    """Valid draft → 200 with {mission_id, draft_id, status: started}."""
    draft_id, body, handler, _ = _make_started_draft(tmp_path, monkeypatch)

    assert handler.send_response.call_args.args == (200,)
    assert body["draft_id"] == draft_id
    assert body["status"] == "started"
    assert body["mission_id"]


def test_plan_start_state_file_saved(tmp_path, monkeypatch):
    """State file at ~/.agentforce/state/{mission_id}.json must exist after start."""
    _, body, handler, state_dir = _make_started_draft(tmp_path, monkeypatch)

    assert handler.send_response.call_args.args == (200,)
    assert (state_dir / f"{body['mission_id']}.json").exists()


def test_plan_start_draft_status_finalized(tmp_path, monkeypatch):
    """Draft status must be 'finalized' after a successful start."""
    draft_id, _, handler, _ = _make_started_draft(tmp_path, monkeypatch)

    assert handler.send_response.call_args.args == (200,)

    get_handler = _make_handler(f"/api/plan/drafts/{draft_id}")
    get_handler.do_GET()
    assert _response_body(get_handler)["status"] == "finalized"


def test_plan_start_returns_422_when_tasks_empty(tmp_path, monkeypatch):
    """Draft with empty tasks list → 422 with errors."""
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(plan_routes, "_active_daemon", None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Empty tasks mission"})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    bad_spec = {**_VALID_DRAFT_SPEC, "tasks": []}
    patch_handler = _make_handler(f"/api/plan/drafts/{draft_id}/spec")
    _json_request(patch_handler, {"expected_revision": 1, "draft_spec": bad_spec})
    patch_handler.do_PATCH()

    start_handler = _make_handler(f"/api/plan/drafts/{draft_id}/start")
    start_handler.do_POST()

    assert start_handler.send_response.call_args.args == (422,)
    body = _response_body(start_handler)
    assert "errors" in body
    assert body["errors"]


def test_plan_start_returns_422_when_dod_empty(tmp_path, monkeypatch):
    """Draft with empty definition_of_done → 422 with errors."""
    from agentforce.server.routes import plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(plan_routes, "_active_daemon", None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "No dod mission"})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    bad_spec = {**_VALID_DRAFT_SPEC, "definition_of_done": []}
    patch_handler = _make_handler(f"/api/plan/drafts/{draft_id}/spec")
    _json_request(patch_handler, {"expected_revision": 1, "draft_spec": bad_spec})
    patch_handler.do_PATCH()

    start_handler = _make_handler(f"/api/plan/drafts/{draft_id}/start")
    start_handler.do_POST()

    assert start_handler.send_response.call_args.args == (422,)
    body = _response_body(start_handler)
    assert "errors" in body
    assert body["errors"]


def test_plan_start_with_daemon_enqueues_mission(tmp_path, monkeypatch):
    """When daemon is active, mission_id appears in daemon.status()['queue']."""
    from agentforce.daemon import MissionDaemon
    from agentforce.server.routes import plan as plan_routes
    from unittest.mock import patch as mock_patch

    _patch_home(monkeypatch, tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)

    daemon = MissionDaemon(state_dir=tmp_path / "daemon", poll_interval=60.0)
    monkeypatch.setattr(plan_routes, "_active_daemon", daemon)
    monkeypatch.setattr("agentforce.autonomous.run_autonomous", lambda *a, **k: None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build a CLI calculator"})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    patch_handler = _make_handler(f"/api/plan/drafts/{draft_id}/spec")
    _json_request(patch_handler, {"expected_revision": 1, "draft_spec": _VALID_DRAFT_SPEC})
    patch_handler.do_PATCH()

    start_handler = _make_handler(f"/api/plan/drafts/{draft_id}/start")
    start_handler.do_POST()

    assert start_handler.send_response.call_args.args == (200,)
    mission_id = _response_body(start_handler)["mission_id"]
    assert mission_id in daemon.status()["queue"]


def test_plan_start_without_daemon_spawns_thread(tmp_path, monkeypatch):
    """When no daemon, a thread named 'agentforce-mission-...' is started."""
    import agentforce.server.routes.plan as plan_routes

    _patch_home(monkeypatch, tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)
    monkeypatch.setattr("agentforce.autonomous.run_autonomous", lambda *a, **k: None)
    monkeypatch.setattr(plan_routes, "_active_daemon", None)

    create_handler = _make_handler("/api/plan/drafts")
    _json_request(create_handler, {"prompt": "Build a CLI calculator"})
    create_handler.do_POST()
    draft_id = _response_body(create_handler)["id"]

    patch_handler = _make_handler(f"/api/plan/drafts/{draft_id}/spec")
    _json_request(patch_handler, {"expected_revision": 1, "draft_spec": _VALID_DRAFT_SPEC})
    patch_handler.do_PATCH()

    # Capture thread names at construction time (thread may finish before enumerate).
    spawned: list[str] = []
    _orig_thread = threading.Thread

    class _CapturingThread(_orig_thread):
        def start(self):
            spawned.append(self.name)
            super().start()

    monkeypatch.setattr(plan_routes.threading, "Thread", _CapturingThread)

    start_handler = _make_handler(f"/api/plan/drafts/{draft_id}/start")
    start_handler.do_POST()

    assert start_handler.send_response.call_args.args == (200,)
    mission_id = _response_body(start_handler)["mission_id"]
    assert any(name == f"agentforce-mission-{mission_id}" for name in spawned)


# ── /api/daemon/* tests ────────────────────────────────────────────────────────

def _make_mock_daemon(queue=None, active=None):
    from unittest.mock import MagicMock
    daemon = MagicMock()
    daemon.status.return_value = {
        "running": True,
        "queue": {mid: {"state": "queued"} for mid in (queue or [])},
        "active": {mid: {"state": "running"} for mid in (active or [])},
        "last_heartbeat": "2026-04-10T00:00:00+00:00",
    }
    return daemon


def test_daemon_status_no_daemon_returns_503(monkeypatch):
    monkeypatch.setattr("agentforce.server.handler._daemon", None)

    handler = _make_handler("/api/daemon/status")
    handler.do_GET()

    assert handler.send_response.call_args.args == (503,)
    assert _response_body(handler) == {"error": "daemon not active"}


def test_daemon_status_returns_200_with_queue_and_active(monkeypatch):
    monkeypatch.setattr("agentforce.server.handler._daemon", _make_mock_daemon(queue=["m1"], active=["m2"]))

    handler = _make_handler("/api/daemon/status")
    handler.do_GET()

    assert handler.send_response.call_args.args == (200,)
    body = _response_body(handler)
    assert body["running"] is True
    assert "m1" in body["queue"]
    assert "m2" in body["active"]
    assert "last_heartbeat" in body


def test_daemon_enqueue_adds_to_queue(monkeypatch):
    daemon = _make_mock_daemon()
    monkeypatch.setattr("agentforce.server.handler._daemon", daemon)

    handler = _make_handler("/api/daemon/enqueue")
    _json_request(handler, {"mission_id": "mission-abc"})
    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)
    body = _response_body(handler)
    assert body == {"enqueued": True, "mission_id": "mission-abc"}
    daemon.enqueue.assert_called_once_with("mission-abc")


def test_daemon_dequeue_active_mission_returns_409(monkeypatch):
    daemon = _make_mock_daemon(active=["mission-running"])
    monkeypatch.setattr("agentforce.server.handler._daemon", daemon)

    handler = _make_handler("/api/daemon/dequeue")
    _json_request(handler, {"mission_id": "mission-running"})
    handler.do_POST()

    assert handler.send_response.call_args.args == (409,)
    assert _response_body(handler) == {"error": "mission is running"}
    daemon.dequeue.assert_not_called()


def test_daemon_dequeue_queued_mission_returns_200(monkeypatch):
    daemon = _make_mock_daemon(queue=["mission-waiting"])
    monkeypatch.setattr("agentforce.server.handler._daemon", daemon)

    handler = _make_handler("/api/daemon/dequeue")
    _json_request(handler, {"mission_id": "mission-waiting"})
    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)
    body = _response_body(handler)
    assert body["dequeued"] is True
    daemon.dequeue.assert_called_once_with("mission-waiting")


def test_daemon_enqueue_without_token_returns_401_when_token_set(monkeypatch):
    monkeypatch.setenv("AGENTFORCE_TOKEN", "secret-token")
    monkeypatch.setattr("agentforce.server.handler._daemon", _make_mock_daemon())

    handler = _make_handler("/api/daemon/enqueue")
    _json_request(handler, {"mission_id": "mission-abc"})
    handler.do_POST()

    assert handler.send_response.call_args.args == (401,)
    assert _response_body(handler) == {"error": "unauthorized"}


def test_daemon_enqueue_with_valid_token_succeeds(monkeypatch):
    monkeypatch.setenv("AGENTFORCE_TOKEN", "secret-token")
    monkeypatch.setattr("agentforce.server.handler._daemon", _make_mock_daemon())

    handler = _make_handler("/api/daemon/enqueue")
    handler.headers["X-Agentforce-Token"] = "secret-token"
    _json_request(handler, {"mission_id": "mission-abc"})
    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)


# ── Integration / backward-compat tests (matched by -k 'integration or e2e') ──

_INTEGRATION_YAML = """\
name: Integration Test Mission
goal: Verify YAML-based mission launch still works
definition_of_done:
  - done
tasks:
  - id: task-01
    title: Only task
    description: placeholder
    acceptance_criteria:
      - works
"""


def test_integration_post_missions_yaml_backward_compat(tmp_path, monkeypatch):
    """POST /api/missions with {yaml: '...'} returns 200 with {id, status: 'started'}.

    Verifies the YAML-based mission launch path still works (backward compat).
    Uses no daemon — spawns a thread instead. No HTTP calls to any LLM provider.
    DeterministicPlannerAdapter is not needed here (missions route bypasses the planner).
    """
    from unittest.mock import patch
    import agentforce.server.routes.missions as m_routes

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_io, "_STATE_DIR_OVERRIDE", state_dir)
    monkeypatch.setattr(handler_mod, "_daemon", None)  # no daemon → spawns thread

    with patch("agentforce.autonomous.run_autonomous", return_value=None):
        code, body = m_routes._post_missions({"yaml": _INTEGRATION_YAML})

    assert code == 200, f"Expected 200, got {code}: {body}"
    assert body.get("status") == "started", f"Expected status='started': {body}"
    assert isinstance(body.get("id"), str) and body["id"], "id must be a non-empty string"
