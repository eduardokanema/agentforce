from __future__ import annotations

import json
import threading
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

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
    assert sum(1 for _ in handler_path.open()) < 200
