from __future__ import annotations

from pathlib import Path
from io import BytesIO
import json
from unittest.mock import MagicMock

from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.core.state import MissionState, TaskState
from agentforce.server.plan_drafts import PlanDraftStore
from agentforce.server.project_harness import (
    ProjectHarnessView,
    build_project_harness_views,
    canonical_repo_root,
    project_id_for_root,
)
from agentforce.server import handler as handler_mod
from agentforce.server import state_io
from agentforce.telemetry import TelemetryStore
from agentforce.memory import Memory


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
    return home


def _make_handler(path: str, body: dict | None = None):
    handler = object.__new__(handler_mod.DashboardHandler)
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


def _response_body(handler) -> dict | list:
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def _save_mission(home: Path, repo_root: Path, *, mission_id: str, draft_id: str | None = None) -> MissionState:
    spec = MissionSpec(
        name="Harness Mission",
        goal="Exercise projects API",
        definition_of_done=["Works"],
        tasks=[TaskSpec(id="task-1", title="Task", description="Do work")],
        caps=Caps(max_concurrent_workers=1),
        working_dir=str(repo_root),
    )
    state = MissionState(
        mission_id=mission_id,
        spec=spec,
        task_states={"task-1": TaskState(task_id="task-1", spec_summary="Do work", status="in_progress")},
        started_at="2026-04-14T09:00:00+00:00",
        working_dir=str(repo_root),
        source_draft_id=draft_id,
    )
    state.save(home / "state" / f"{mission_id}.json")
    return state


def test_canonical_repo_root_falls_back_to_resolved_workspace(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr("agentforce.server.project_harness._repo_root_from_git", lambda path: None)

    assert canonical_repo_root(workspace) == str(workspace.resolve())


def test_project_id_stable_for_same_root() -> None:
    root = "/tmp/example-repo"
    assert project_id_for_root(root) == project_id_for_root(root)


def test_build_project_harness_groups_draft_and_mission(monkeypatch, tmp_path) -> None:
    home = _set_agentforce_home(tmp_path, monkeypatch)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    drafts = PlanDraftStore(home / "drafts")
    draft = drafts.create(
        "draft-1",
        status="finalized",
        draft_spec={"name": "Harness Project", "goal": "Goal", "tasks": [], "working_dir": str(repo_root)},
        turns=[],
        validation={"latest_plan_version_id": "version-1", "latest_plan_run_id": "run-1"},
        activity_log=[],
        approved_models=[],
        workspace_paths=[str(repo_root)],
        companion_profile={},
        draft_notes=[],
    )
    _save_mission(home, repo_root, mission_id="mission-1", draft_id=draft.id)
    TelemetryStore(home / "telemetry").record_troubleshooting("mission-1", "Adjust rollout")
    Memory(home / "memory").project_set("mission-1", "lesson", "Prefer repo-root grouping", category="lesson")
    monkeypatch.setattr("agentforce.server.project_harness._repo_root_from_git", lambda path: path.resolve())

    views = build_project_harness_views()

    assert len(views) == 1
    view = views[0]
    assert isinstance(view, ProjectHarnessView)
    assert view.summary.name == "Harness Project"
    assert view.summary.active_mission_id == "mission-1"
    assert view.summary.primary_working_directory == str(repo_root.resolve())
    assert view.summary.workspace_count == 1
    assert view.summary.goal == "Goal"
    assert view.cycles[0].draft_id == "draft-1"
    assert view.cycles[0].mission_id == "mission-1"
    assert view.context["working_directories"] == [str(repo_root.resolve())]
    assert view.context["goal"] == "Goal"
    evidence_kinds = {item.kind for item in view.cycles[0].evidence.items}
    assert "telemetry" in evidence_kinds
    assert "memory" in evidence_kinds


def test_build_project_harness_links_readjusted_successor(monkeypatch, tmp_path) -> None:
    home = _set_agentforce_home(tmp_path, monkeypatch)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    drafts = PlanDraftStore(home / "drafts")
    original = drafts.create(
        "draft-1",
        status="finalized",
        draft_spec={"name": "Harness Project", "goal": "Goal", "tasks": [], "working_dir": str(repo_root)},
        turns=[],
        validation={},
        activity_log=[],
        approved_models=[],
        workspace_paths=[str(repo_root)],
        companion_profile={},
        draft_notes=[],
    )
    _save_mission(home, repo_root, mission_id="mission-1", draft_id=original.id)
    drafts.create(
        "draft-2",
        status="draft",
        draft_spec={"name": "Harness Project V2", "goal": "Goal", "tasks": [], "working_dir": str(repo_root)},
        turns=[],
        validation={},
        activity_log=[{"type": "readjust_trajectory_seeded", "mission_id": "mission-1"}],
        approved_models=[],
        workspace_paths=[str(repo_root)],
        companion_profile={},
        draft_notes=[],
    )
    monkeypatch.setattr("agentforce.server.project_harness._repo_root_from_git", lambda path: path.resolve())

    views = build_project_harness_views()
    cycles = {cycle.cycle_id: cycle for cycle in views[0].cycles}

    assert cycles["draft-1"].successor_cycle_id == "draft-2"
    assert cycles["draft-2"].predecessor_cycle_id == "draft-1"


def test_projects_routes_return_derived_payload(monkeypatch, tmp_path) -> None:
    home = _set_agentforce_home(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace" / "nested"
    drafts = PlanDraftStore(home / "drafts")
    draft = drafts.create(
        "draft-1",
        status="draft",
        draft_spec={"name": "Harness Project", "goal": "Goal", "tasks": [], "working_dir": str(workspace)},
        turns=[],
        validation={},
        activity_log=[],
        approved_models=[],
        workspace_paths=[str(workspace)],
        companion_profile={},
        draft_notes=[],
    )
    monkeypatch.setattr("agentforce.server.project_harness._repo_root_from_git", lambda path: None)

    list_handler = _make_handler("/api/projects")
    list_handler.do_GET()
    assert list_handler.send_response.call_args.args == (200,)
    summaries = _response_body(list_handler)
    assert len(summaries) == 1
    assert summaries[0]["repo_root"] == str(workspace.resolve())
    assert summaries[0]["primary_working_directory"] == str(workspace.resolve())
    assert summaries[0]["goal"] == "Goal"
    assert summaries[0]["planned_task_count"] == 0

    detail_handler = _make_handler(f"/api/project/{summaries[0]['project_id']}")
    detail_handler.do_GET()
    assert detail_handler.send_response.call_args.args == (200,)
    detail = _response_body(detail_handler)
    assert detail["summary"]["active_cycle_id"] == draft.id
    assert detail["cycles"][0]["draft_id"] == draft.id
    assert detail["context"]["working_directories"] == [str(workspace.resolve())]

    missing_handler = _make_handler("/api/project/missing-project")
    missing_handler.do_GET()
    assert missing_handler.send_response.call_args.args == (404,)
    assert _response_body(missing_handler) == {"error": "Project 'missing-project' not found"}


def test_projects_crud_archive_and_safe_delete(monkeypatch, tmp_path) -> None:
    home = _set_agentforce_home(tmp_path, monkeypatch)
    repo_root = tmp_path / "repo"
    work_a = repo_root / "apps" / "core"
    work_b = repo_root / "tests"
    work_a.mkdir(parents=True)
    work_b.mkdir(parents=True)
    monkeypatch.setattr("agentforce.server.project_harness._repo_root_from_git", lambda path: path.resolve())

    create_handler = _make_handler(
        "/api/projects",
        {
            "repo_root": str(repo_root),
            "name": "Harness CRUD",
            "goal": "Keep project lifecycle explicit",
            "working_directories": [str(work_a), str(work_b)],
        },
    )
    create_handler.do_POST()
    assert create_handler.send_response.call_args.args == (201,)
    created = _response_body(create_handler)
    project_id = created["summary"]["project_id"]
    assert created["summary"]["status"] == "idle"
    assert created["summary"]["workspace_count"] == 2

    patch_handler = _make_handler(
        f"/api/project/{project_id}",
        {
            "name": "Harness CRUD Updated",
            "goal": "Updated goal",
            "working_directories": [str(work_a)],
        },
    )
    patch_handler.do_PATCH()
    assert patch_handler.send_response.call_args.args == (200,)
    updated = _response_body(patch_handler)
    assert updated["summary"]["name"] == "Harness CRUD Updated"
    assert updated["context"]["goal"] == "Updated goal"
    assert updated["context"]["working_directories"] == [str(work_a.resolve())]

    archive_handler = _make_handler(f"/api/project/{project_id}/archive", {})
    archive_handler.do_POST()
    assert archive_handler.send_response.call_args.args == (200,)
    assert _response_body(archive_handler) == {"archived": True}

    list_handler = _make_handler("/api/projects")
    list_handler.do_GET()
    assert _response_body(list_handler) == []

    archived_list_handler = _make_handler("/api/projects?include_archived=1")
    archived_list_handler.do_GET()
    archived_summaries = _response_body(archived_list_handler)
    assert archived_summaries[0]["status"] == "archived"

    delete_handler = _make_handler(f"/api/project/{project_id}")
    delete_handler.do_DELETE()
    assert delete_handler.send_response.call_args.args == (200,)
    assert _response_body(delete_handler) == {"deleted": True}


def test_project_delete_rejected_when_history_exists(monkeypatch, tmp_path) -> None:
    home = _set_agentforce_home(tmp_path, monkeypatch)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    drafts = PlanDraftStore(home / "drafts")
    drafts.create(
        "draft-1",
        status="draft",
        draft_spec={"name": "Harness Project", "goal": "Goal", "tasks": [], "working_dir": str(repo_root)},
        turns=[],
        validation={},
        activity_log=[],
        approved_models=[],
        workspace_paths=[str(repo_root)],
        companion_profile={},
        draft_notes=[],
    )
    monkeypatch.setattr("agentforce.server.project_harness._repo_root_from_git", lambda path: path.resolve())

    list_handler = _make_handler("/api/projects")
    list_handler.do_GET()
    project_id = _response_body(list_handler)[0]["project_id"]

    delete_handler = _make_handler(f"/api/project/{project_id}")
    delete_handler.do_DELETE()
    assert delete_handler.send_response.call_args.args == (409,)
    assert _response_body(delete_handler)["error"] == "Project with active history cannot be deleted"
