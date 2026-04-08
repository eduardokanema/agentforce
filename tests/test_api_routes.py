from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.core.state import MissionState, TaskState
from agentforce.server.handler import DashboardHandler


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


def _seed_state(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _state().save(state_dir / "mission-123.json")
    monkeypatch.setattr("agentforce.server.handler.STATE_DIR", state_dir)


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


def test_html_routes_still_render_html(tmp_path, monkeypatch):
    _seed_state(tmp_path, monkeypatch)

    handler = _make_handler("/mission/mission-123")
    handler.do_GET()

    handler._html.assert_called_once()
