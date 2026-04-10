from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

from agentforce.core.spec import Caps, ExecutionConfig, ExecutionProfile, MissionSpec, TaskSpec, TaskStatus
from agentforce.core.state import MissionState, TaskState
from agentforce.server import state_io
from agentforce.server.handler import DashboardHandler


def _set_handler_config(state_dir: Path) -> None:
    DashboardHandler.config = DashboardHandler.config.__class__(
        state_dir=Path(state_dir),
        host="localhost",
        port=8080,
    )


def _spec() -> MissionSpec:
    return MissionSpec(
        name="New Endpoints Mission",
        goal="Exercise dashboard endpoints",
        definition_of_done=["All endpoints work"],
        tasks=[
            TaskSpec(
                id="task-1",
                title="First task",
                description="Primary route coverage",
            ),
            TaskSpec(
                id="task-2",
                title="Second task",
                description="Telemetry coverage",
            ),
        ],
        caps=Caps(max_concurrent_workers=1),
    )


def _state(mission_id: str = "mission-123") -> MissionState:
    return MissionState(
        mission_id=mission_id,
        spec=_spec(),
        task_states={
            "task-1": TaskState(task_id="task-1", spec_summary="Primary route coverage", status=TaskStatus.PENDING),
            "task-2": TaskState(task_id="task-2", spec_summary="Telemetry coverage", status=TaskStatus.IN_PROGRESS),
        },
        started_at="2024-01-01T00:00:00+00:00",
        tokens_in=120,
        tokens_out=80,
        cost_usd=0.42,
    )


def _make_handler(path: str, body: bytes = b"", headers: dict | None = None) -> DashboardHandler:
    handler = object.__new__(DashboardHandler)
    handler.path = path
    handler.headers = headers or {}
    handler.connection = object()
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler._html = MagicMock()
    handler._err = MagicMock()
    return handler


def _response_body(handler: DashboardHandler) -> dict | list:
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def _seed_state(tmp_path: Path, monkeypatch) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _state().save(state_dir / "mission-123.json")
    _set_handler_config(state_dir)
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path / ".agentforce")
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", state_dir)
    monkeypatch.setattr("agentforce.server.state_io.AGENTFORCE_HOME", tmp_path / ".agentforce")
    return state_dir


def test_get_models_returns_three_claude_models(tmp_path, monkeypatch):
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path / ".agentforce")
    monkeypatch.setattr("agentforce.server.state_io.AGENTFORCE_HOME", tmp_path / ".agentforce")
    monkeypatch.setattr("agentforce.server.routes.providers._check_agent_binary", lambda binary: binary == "claude")
    monkeypatch.setattr("agentforce.server.routes.providers._fetch_ollama_models", lambda: [])
    monkeypatch.setattr("keyring.get_password", lambda *_args, **_kwargs: None)

    handler = _make_handler("/api/models")

    handler.do_GET()

    body = _response_body(handler)
    assert [model["id"] for model in body] == [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]


def test_get_connectors_returns_six_connectors(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)
    monkeypatch.setattr("keyring.get_password", lambda *_args, **_kwargs: "token")

    handler = _make_handler("/api/connectors")

    handler.do_GET()

    body = _response_body(handler)
    assert [connector["name"] for connector in body] == [
        "github",
        "slack",
        "linear",
        "sentry",
        "notion",
        "anthropic",
    ]


def test_get_telemetry_returns_total_missions_key(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    handler = _make_handler("/api/telemetry")

    handler.do_GET()

    body = _response_body(handler)
    assert "total_missions" in body


def test_get_telemetry_returns_dashboard_breakdown_fields(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)

    first = _state("mission-a")
    first.started_at = "2024-01-01T00:00:00+00:00"
    first.cost_usd = 1.5
    first.tokens_in = 120
    first.tokens_out = 80
    first.task_states["task-1"].cost_usd = 0.4
    first.task_states["task-1"].retries = 1
    first.task_states["task-2"].cost_usd = 1.1
    first.task_states["task-2"].retries = 2
    first.save(state_dir / "mission-a.json")

    second = _state("mission-b")
    second.started_at = "2024-01-02T00:00:00+00:00"
    second.cost_usd = 2.25
    second.tokens_in = 220
    second.tokens_out = 180
    second.task_states["task-1"].cost_usd = 2.25
    second.task_states["task-1"].retries = 0
    second.save(state_dir / "mission-b.json")

    handler = _make_handler("/api/telemetry")

    handler.do_GET()

    body = _response_body(handler)
    assert body["missions_by_cost"][0]["mission_id"] == "mission-b"
    assert body["missions_by_cost"][0]["duration"]
    assert body["tasks_by_cost"][0]["task"] == "First task"
    assert body["tasks_by_cost"][0]["mission"] == "New Endpoints Mission"
    assert body["tasks_by_cost"][0]["model"] == ""
    assert body["tasks_by_cost"][0]["retries"] == 0
    assert [point["cumulative_cost"] for point in body["cost_over_time"]] == [0.42, 1.92, 4.17]


def test_get_attempts_preserves_zero_score(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)
    state = _state()
    state.task_states["task-1"].review_score = 0
    state.task_states["task-1"].review_feedback = "Looks good"
    state.save(state_dir / "mission-123.json")

    handler = _make_handler("/api/mission/mission-123/task/task-1/attempts")

    handler.do_GET()

    body = _response_body(handler)
    assert body[0]["score"] == 0


def test_post_inject_returns_409_when_task_not_in_progress(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    payload = json.dumps({"message": "hi"}).encode("utf-8")
    handler = _make_handler(
        "/api/mission/mission-123/task/task-1/inject",
        body=payload,
        headers={"Content-Length": str(len(payload))},
    )

    handler.do_POST()

    assert handler.send_response.call_args.args == (409,)
    assert _response_body(handler)["error"] == "task not in_progress"


def test_post_resolve_can_mark_failed(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)
    state = _state()
    state.task_states["task-1"].status = TaskStatus.NEEDS_HUMAN
    state.task_states["task-1"].human_intervention_needed = True
    state.save(state_dir / "mission-123.json")

    payload = json.dumps({"failed": True}).encode("utf-8")
    handler = _make_handler(
        "/api/mission/mission-123/task/task-1/resolve",
        body=payload,
        headers={"Content-Length": str(len(payload))},
    )

    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)
    assert _response_body(handler) == {"failed": True}
    reloaded = MissionState.load(state_dir / "mission-123.json")
    assert reloaded.task_states["task-1"].status == TaskStatus.FAILED


def test_post_resolve_destructive_choice_requeues_and_stores_allow_rule(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)
    state = _state()
    task = state.task_states["task-1"]
    task.status = TaskStatus.NEEDS_HUMAN
    task.human_intervention_needed = True
    task.human_intervention_kind = "destructive_action"
    task.human_intervention_message = "Potential destructive action requested"
    task.human_intervention_context = {
        "type": "destructive_action_request",
        "summary": "Delete stale build output",
        "risk": "Removes generated files from dist.",
        "proposed_action": "rm -rf dist",
        "targets": ["dist"],
        "action_key": "delete:dist",
    }
    task.human_intervention_options = [
        {"id": "approve_once", "label": "Approve once"},
        {"id": "always_allow", "label": "Always allow this exact action"},
        {"id": "deny", "label": "Deny"},
        {"id": "revise", "label": "Revise with instructions"},
    ]
    state.save(state_dir / "mission-123.json")

    payload = json.dumps({"choice_id": "always_allow", "message": "Generated output only."}).encode("utf-8")
    handler = _make_handler(
        "/api/mission/mission-123/task/task-1/resolve",
        body=payload,
        headers={"Content-Length": str(len(payload))},
    )

    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)
    assert _response_body(handler) == {"resolved": True, "choice_id": "always_allow"}
    reloaded = MissionState.load(state_dir / "mission-123.json")
    task = reloaded.task_states["task-1"]
    assert task.status == TaskStatus.RETRY
    assert task.human_intervention_needed is False
    assert task.human_intervention_kind == ""
    assert "delete:dist" in reloaded.destructive_action_allow_rules


def test_post_resolve_destructive_revise_requires_message(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)
    state = _state()
    task = state.task_states["task-1"]
    task.status = TaskStatus.NEEDS_HUMAN
    task.human_intervention_needed = True
    task.human_intervention_kind = "destructive_action"
    task.human_intervention_context = {"action_key": "delete:dist", "proposed_action": "rm -rf dist"}
    task.human_intervention_options = [
        {"id": "approve_once", "label": "Approve once"},
        {"id": "always_allow", "label": "Always allow this exact action"},
        {"id": "deny", "label": "Deny"},
        {"id": "revise", "label": "Revise with instructions"},
    ]
    state.save(state_dir / "mission-123.json")

    payload = json.dumps({"choice_id": "revise"}).encode("utf-8")
    handler = _make_handler(
        "/api/mission/mission-123/task/task-1/resolve",
        body=payload,
        headers={"Content-Length": str(len(payload))},
    )

    handler.do_POST()

    assert handler.send_response.call_args.args == (400,)
    assert _response_body(handler)["error"] == "message is required for revise"


def test_post_restart_requeues_matching_tasks(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)
    state = _state()
    state.task_states["task-1"].status = TaskStatus.FAILED
    state.task_states["task-1"].worker_output = "failed output"
    state.task_states["task-1"].attempt_history = [{"attempt_number": 1, "output": "failed output"}]
    state.task_states["task-2"].status = TaskStatus.BLOCKED
    state.task_states["task-2"].worker_output = "needs reset"
    state.task_states["task-3"] = TaskState(
        task_id="task-3",
        spec_summary="Review issue",
        status=TaskStatus.REVIEW_REJECTED,
        worker_output="old output",
    )
    state.task_states["task-4"] = TaskState(
        task_id="task-4",
        spec_summary="Worker done",
        status=TaskStatus.COMPLETED,
        worker_output="ready for review",
    )
    state.task_states["task-5"] = TaskState(
        task_id="task-5",
        spec_summary="Approved",
        status=TaskStatus.REVIEW_APPROVED,
        worker_output="done",
    )
    state.active_wall_time_seconds = 125
    state.completed_at = "2024-01-01T00:30:00+00:00"
    state.save(state_dir / "mission-123.json")

    handler = _make_handler("/api/mission/mission-123/restart")

    handler.do_POST()

    assert _response_body(handler) == {"requeued": 3}
    reloaded = MissionState.load(state_dir / "mission-123.json")
    assert reloaded.active_wall_time_seconds == 0
    assert reloaded.started_at == "2024-01-01T00:00:00+00:00"
    assert reloaded.completed_at is None
    assert reloaded.task_states["task-1"].status == TaskStatus.RETRY
    assert reloaded.task_states["task-1"].worker_output == "failed output"
    assert reloaded.task_states["task-1"].attempt_history == [{"attempt_number": 1, "output": "failed output"}]
    assert reloaded.task_states["task-2"].status == TaskStatus.RETRY
    assert reloaded.task_states["task-2"].worker_output == "needs reset"
    assert reloaded.task_states["task-3"].status == TaskStatus.RETRY
    assert reloaded.task_states["task-3"].worker_output == "old output"
    assert reloaded.task_states["task-4"].status == TaskStatus.COMPLETED
    assert reloaded.task_states["task-4"].worker_output == "ready for review"
    assert reloaded.task_states["task-5"].status == TaskStatus.REVIEW_APPROVED


def test_post_default_models_updates_pending_defaults_and_preserves_started_tasks(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)
    state = _state()
    state.execution_defaults = ExecutionConfig(
        worker=ExecutionProfile(model="old-worker"),
        reviewer=ExecutionProfile(model="old-reviewer"),
    )
    state.task_states["task-1"].status = TaskStatus.PENDING
    state.task_states["task-1"].started_at = None
    state.task_states["task-2"].status = TaskStatus.IN_PROGRESS
    state.task_states["task-2"].started_at = "2024-01-01T00:01:00+00:00"
    state.save(state_dir / "mission-123.json")

    payload = json.dumps({
        "worker_agent": "codex",
        "worker_model": "new-worker",
        "reviewer_agent": "claude",
        "reviewer_model": "new-reviewer",
    }).encode("utf-8")
    handler = _make_handler(
        "/api/mission/mission-123/default_models",
        body=payload,
        headers={"Content-Length": str(len(payload))},
    )

    handler.do_POST()

    body = _response_body(handler)
    assert body["worker_agent"] == "codex"
    assert body["worker_model"] == "new-worker"
    assert body["reviewer_agent"] == "claude"
    assert body["reviewer_model"] == "new-reviewer"
    assert body["pinned_tasks"] == 1
    reloaded = MissionState.load(state_dir / "mission-123.json")
    assert reloaded.execution_defaults.worker.agent == "codex"
    assert reloaded.execution_defaults.worker.model == "new-worker"
    assert reloaded.execution_defaults.reviewer.agent == "claude"
    assert reloaded.execution_defaults.reviewer.model == "new-reviewer"
    assert reloaded.spec.tasks[0].execution.worker is None
    assert reloaded.spec.tasks[0].execution.reviewer is None
    assert reloaded.spec.tasks[1].execution.worker.model == "old-worker"
    assert reloaded.spec.tasks[1].execution.reviewer.model == "old-reviewer"


def test_post_task_change_model_updates_agent_and_model(tmp_path, monkeypatch):
    state_dir = _seed_state(tmp_path, monkeypatch)
    state = _state()
    state.task_states["task-1"].status = TaskStatus.IN_PROGRESS
    state.spec.tasks[0].execution.worker = ExecutionProfile(agent="gemini", model="gemini-2.5-pro")
    state.save(state_dir / "mission-123.json")

    payload = json.dumps({
        "worker_agent": "codex",
        "worker_model": "gpt-5.4",
        "reviewer_agent": "claude",
        "reviewer_model": "claude-sonnet-4-6",
    }).encode("utf-8")
    handler = _make_handler(
        "/api/mission/mission-123/task/task-1/change_model",
        body=payload,
        headers={"Content-Length": str(len(payload))},
    )

    handler.do_POST()

    body = _response_body(handler)
    assert body["worker_agent"] == "codex"
    assert body["worker_model"] == "gpt-5.4"
    assert body["reviewer_agent"] == "claude"
    assert body["reviewer_model"] == "claude-sonnet-4-6"
    assert body["retried"] is True
    reloaded = MissionState.load(state_dir / "mission-123.json")
    assert reloaded.spec.tasks[0].execution.worker.agent == "codex"
    assert reloaded.spec.tasks[0].execution.worker.model == "gpt-5.4"
    assert reloaded.spec.tasks[0].execution.reviewer.agent == "claude"
    assert reloaded.spec.tasks[0].execution.reviewer.model == "claude-sonnet-4-6"


def test_post_connectors_configure_persists_token(tmp_path, monkeypatch):
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path / ".agentforce")
    _set_handler_config(tmp_path / "state")
    monkeypatch.setattr("agentforce.server.state_io.AGENTFORCE_HOME", tmp_path / ".agentforce")
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", tmp_path / "state")
    monkeypatch.setattr("keyring.set_password", MagicMock())

    payload = json.dumps({"token": "abc123"}).encode("utf-8")
    handler = _make_handler(
        "/api/connectors/github/configure",
        body=payload,
        headers={"Content-Length": str(len(payload))},
    )

    handler.do_POST()

    assert _response_body(handler) == {"configured": True}


def test_post_connectors_github_test_uses_minimal_request(tmp_path, monkeypatch):
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path / ".agentforce")
    _set_handler_config(tmp_path / "state")
    monkeypatch.setattr("agentforce.server.state_io.AGENTFORCE_HOME", tmp_path / ".agentforce")
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", tmp_path / "state")
    monkeypatch.setattr("keyring.get_password", lambda *_args, **_kwargs: "gh-token")

    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
    monkeypatch.setattr("agentforce.server.routes.providers.urllib_request.urlopen", urlopen)

    handler = _make_handler("/api/connectors/github/test")

    handler.do_POST()

    assert _response_body(handler) == {"ok": True}
    request = urlopen.call_args.args[0]
    assert request.full_url == "https://api.github.com/user"
    assert request.headers["Authorization"] == "Bearer gh-token"


def test_delete_connectors_github_returns_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path / ".agentforce")
    _set_handler_config(tmp_path / "state")
    monkeypatch.setattr("agentforce.server.state_io.AGENTFORCE_HOME", tmp_path / ".agentforce")
    monkeypatch.setattr("agentforce.server.state_io.STATE_DIR", tmp_path / "state")
    monkeypatch.setattr("keyring.delete_password", MagicMock())

    handler = _make_handler("/api/connectors/github")

    handler.do_DELETE()

    assert _response_body(handler) == {"deleted": True}
