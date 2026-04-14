from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

from agentforce.server import handler as handler_mod
from agentforce.server import state_io
from agentforce.server.handler import DashboardHandler


def _set_agentforce_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / ".agentforce-home"
    home.mkdir()
    state_dir = home / "state"
    state_dir.mkdir()
    monkeypatch.setattr(handler_mod, "AGENTFORCE_HOME", home)
    monkeypatch.setattr(state_io, "AGENTFORCE_HOME", home)
    monkeypatch.setattr(state_io, "STATE_DIR", state_dir)
    monkeypatch.setattr(state_io, "_STATE_DIR_OVERRIDE", state_dir, raising=False)
    handler_mod.DashboardHandler.config = handler_mod.ServerConfig(state_dir=state_dir, host="localhost", port=8080)
    monkeypatch.setattr("agentforce.server.routes.project_graph_routes._launch_mission", lambda mission_id: None)
    return home


def _make_handler(path: str, body: dict | None = None) -> DashboardHandler:
    handler = object.__new__(DashboardHandler)
    handler.path = path
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    handler.headers = {"Content-Length": str(len(raw))}
    handler.connection = object()
    handler.rfile = BytesIO(raw)
    handler.wfile = BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler._html = MagicMock()
    handler._err = MagicMock()
    return handler


def _response_body(handler: DashboardHandler) -> dict | list:
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_project_first_api_creates_project_and_plan_portfolio(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "workspace"
    repo_root.mkdir()
    _set_agentforce_home(tmp_path, monkeypatch)

    create_project = _make_handler("/api/projects", {
        "repo_root": str(repo_root),
        "name": "Project First",
        "description": "Run the redesign through a graph workspace.",
    })
    create_project.do_POST()
    project = _response_body(create_project)
    project_id = project["project"]["project_id"]

    create_plan = _make_handler(f"/api/projects/{project_id}/plans", {
        "name": "Portfolio Plan",
        "objective": "Implement the graph-first workspace and scheduler.",
        "quick_task": True,
    })
    create_plan.do_POST()
    plan = _response_body(create_plan)
    assert plan["plan_id"]
    assert plan["graph"]["nodes"][0]["title"] == "Implement The Graph First Workspace And Scheduler."

    list_projects = _make_handler("/api/projects")
    list_projects.do_GET()
    summaries = _response_body(list_projects)
    assert summaries[0]["project_id"] == project_id
    assert summaries[0]["active_plan_count"] == 1
    assert summaries[0]["planned_task_count"] == 1

    project_detail = _make_handler(f"/api/projects/{project_id}")
    project_detail.do_GET()
    detail = _response_body(project_detail)
    assert detail["summary"]["project_id"] == project_id
    assert detail["plans"][0]["name"] == "Portfolio Plan"
    assert detail["scheduler"]["queue"][0]["plan_id"] == plan["plan_id"]


def test_project_scheduler_blocks_touch_scope_conflicts_across_active_plans(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "workspace"
    repo_root.mkdir()
    _set_agentforce_home(tmp_path, monkeypatch)

    create_project = _make_handler("/api/projects", {"repo_root": str(repo_root), "name": "Scheduler Project"})
    create_project.do_POST()
    project_id = _response_body(create_project)["project"]["project_id"]

    plan_a_create = _make_handler(f"/api/projects/{project_id}/plans", {
        "name": "Plan A",
        "objective": "Patch the shared auth surface.",
        "quick_task": True,
    })
    plan_a_create.do_POST()
    plan_a = _response_body(plan_a_create)
    node_a = plan_a["graph"]["nodes"][0]
    patch_a = _make_handler(f"/api/plans/{plan_a['plan_id']}/nodes/{node_a['node_id']}", {
        "touch_scope": ["shared/auth.ts"],
    })
    patch_a.do_PATCH()
    approve_a = _make_handler(f"/api/plans/{plan_a['plan_id']}/approve-version", {})
    approve_a.do_POST()
    start_a = _make_handler(f"/api/plans/{plan_a['plan_id']}/start", {})
    start_a.do_POST()

    plan_b_create = _make_handler(f"/api/projects/{project_id}/plans", {
        "name": "Plan B",
        "objective": "Update the same auth entry point.",
        "quick_task": True,
    })
    plan_b_create.do_POST()
    plan_b = _response_body(plan_b_create)
    node_b = plan_b["graph"]["nodes"][0]
    patch_b = _make_handler(f"/api/plans/{plan_b['plan_id']}/nodes/{node_b['node_id']}", {
        "touch_scope": ["shared/auth.ts"],
    })
    patch_b.do_PATCH()
    approve_b = _make_handler(f"/api/plans/{plan_b['plan_id']}/approve-version", {})
    approve_b.do_POST()

    scheduler = _make_handler(f"/api/projects/{project_id}/scheduler")
    scheduler.do_GET()
    body = _response_body(scheduler)
    assert any(item["plan_id"] == plan_a["plan_id"] for item in body["running"])
    assert any(item["plan_id"] == plan_b["plan_id"] and "Touch scope conflict" in item["conflict_reason"] for item in body["blocked"])


def test_project_readjust_creates_new_plan_history_without_mutating_previous_plan(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "workspace"
    repo_root.mkdir()
    _set_agentforce_home(tmp_path, monkeypatch)

    create_project = _make_handler("/api/projects", {"repo_root": str(repo_root), "name": "History Project"})
    create_project.do_POST()
    project_id = _response_body(create_project)["project"]["project_id"]

    create_plan = _make_handler(f"/api/projects/{project_id}/plans", {
        "name": "Original Plan",
        "objective": "Ship the first version.",
        "quick_task": True,
    })
    create_plan.do_POST()
    plan = _response_body(create_plan)

    readjust = _make_handler(f"/api/plans/{plan['plan_id']}/readjust", {})
    readjust.do_POST()
    readjusted = _response_body(readjust)

    original_detail = _make_handler(f"/api/plans/{plan['plan_id']}")
    original_detail.do_GET()
    original = _response_body(original_detail)

    assert readjusted["supersedes_plan_id"] == plan["plan_id"]
    assert original["supersedes_plan_id"] is None
    assert readjusted["plan_id"] != plan["plan_id"]
