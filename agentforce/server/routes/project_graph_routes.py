"""Project-first DAG API routes."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from agentforce.server import state_io
from agentforce.server.project_graph import (
    MissionRunRecord,
    PlanNodeRecord,
    PlanRecord,
    PlanVersionRecord,
    ProjectGraphStore,
    ProjectRecord,
    _slug,
    _spec_from_plan,
    _title_from_goal,
    _utc_now,
    build_scheduler_state,
    generate_nodes_from_prompt,
    sync_mission_run,
)


def _store() -> ProjectGraphStore:
    return ProjectGraphStore()


def _normalize_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _launch_mission(mission_id: str) -> None:
    try:
        from agentforce.server import handler as _handler

        daemon = getattr(_handler, "_daemon", None)
        if daemon is not None:
            daemon.enqueue(mission_id)
            return
    except Exception:
        pass

    def _runner() -> None:
        try:
            from agentforce.autonomous import run_autonomous

            run_autonomous(mission_id)
        except SystemExit:
            pass
        except Exception:
            pass

    threading.Thread(
        target=_runner,
        daemon=True,
        name=f"agentforce-project-graph-{mission_id}",
    ).start()


def _project_summary(store: ProjectGraphStore, project: ProjectRecord) -> dict[str, Any]:
    plans = store.list_plans_for_project(project.project_id)
    scheduler = build_scheduler_state(store, project.project_id)
    active_plan = next((plan for plan in plans if plan.status in {"running", "blocked", "ready", "draft"}), plans[0] if plans else None)
    active_run = store.get_mission_run(active_plan.active_mission_run_id) if active_plan and active_plan.active_mission_run_id else None
    status = "archived" if project.archived_at else (
        "running"
        if scheduler["running"]
        else "blocked"
        if scheduler["blocked"]
        else "ready"
        if scheduler["queue"]
        else "completed"
        if plans and all(plan.status == "completed" for plan in plans)
        else "idle"
    )
    current_stage = (
        "archived"
        if project.archived_at
        else "executing"
        if status == "running"
        else "blocked"
        if status == "blocked"
        else "ready_to_launch"
        if status == "ready"
        else "completed"
        if status == "completed"
        else "planning"
        if plans
        else "setup"
    )
    working_directories = list(project.settings.get("working_directories") or []) or [project.repo_root]
    return {
        "project_id": project.project_id,
        "name": project.name,
        "repo_root": project.repo_root,
        "primary_working_directory": working_directories[0] if working_directories else project.repo_root,
        "workspace_count": len(working_directories),
        "goal": project.description,
        "planned_task_count": sum(len(plan.current_nodes) for plan in plans),
        "current_stage": current_stage,
        "current_plan_id": active_plan.plan_id if active_plan else None,
        "current_mission_id": active_run.mission_id if active_run else None,
        "next_action_label": "Open workspace" if active_plan else "Create plan",
        "mode": "standard",
        "status": status,
        "active_cycle_id": active_plan.plan_id if active_plan else None,
        "blocker": scheduler["blocked"][0]["conflict_reason"] if scheduler["blocked"] else None,
        "next_action": "Open workspace" if active_plan else "Create plan",
        "active_mission_id": active_run.mission_id if active_run else None,
        "archived_at": project.archived_at,
        "has_activity": bool(plans),
        "updated_at": max([project.updated_at, *[plan.updated_at for plan in plans]], default=project.updated_at),
        "active_plan_count": len([plan for plan in plans if plan.status in {"running", "blocked", "ready", "draft"}]),
        "running_plan_count": len([plan for plan in plans if plan.status == "running"]),
        "blocked_node_count": len(scheduler["blocked"]),
        "related_project_ids": list(project.related_project_ids),
    }


def _plan_summary(store: ProjectGraphStore, plan: PlanRecord) -> dict[str, Any]:
    run = store.get_mission_run(plan.active_mission_run_id) if plan.active_mission_run_id else None
    if run is not None:
        run = sync_mission_run(store, run)
    return {
        "plan_id": plan.plan_id,
        "project_id": plan.project_id,
        "name": plan.name,
        "objective": plan.objective,
        "status": plan.status,
        "quick_task": plan.quick_task,
        "node_count": len(plan.current_nodes),
        "selected_version_id": plan.selected_version_id,
        "active_mission_run_id": plan.active_mission_run_id,
        "mission_id": run.mission_id if run is not None else None,
        "merged_project_scope": list(plan.merged_project_scope),
        "planner_debug": dict(plan.planner_debug),
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "supersedes_plan_id": plan.supersedes_plan_id,
    }


def _node_runtime_map(store: ProjectGraphStore, plan: PlanRecord) -> dict[str, dict[str, Any]]:
    scheduler = build_scheduler_state(store, plan.project_id)
    ready_by_id = {f"{item['plan_id']}:{item['node_id']}": item for item in scheduler["queue"]}
    blocked_by_id = {f"{item['plan_id']}:{item['node_id']}": item for item in scheduler["blocked"]}
    running_by_id = {f"{item['plan_id']}:{item['node_id']}": item for item in scheduler["running"]}
    runtime: dict[str, dict[str, Any]] = {}
    run = store.get_mission_run(plan.active_mission_run_id) if plan.active_mission_run_id else None
    if run is not None:
        run = sync_mission_run(store, run)
        for node_state in run.node_states:
            runtime[node_state.node_id] = {
                "status": node_state.status,
                "reason": node_state.reason,
                "started_at": node_state.started_at,
                "completed_at": node_state.completed_at,
            }
    for node in plan.current_nodes:
        key = f"{plan.plan_id}:{node.node_id}"
        runtime.setdefault(node.node_id, {
            "status": "blocked" if key in blocked_by_id else "running" if key in running_by_id else "ready" if key in ready_by_id else "draft",
            "reason": blocked_by_id.get(key, {}).get("conflict_reason"),
            "scheduler_priority": ready_by_id.get(key, {}).get("scheduler_priority"),
        })
    return runtime


def _plan_detail(store: ProjectGraphStore, plan: PlanRecord) -> dict[str, Any]:
    versions = store.list_versions_for_plan(plan.plan_id)
    mission_runs = [sync_mission_run(store, run) for run in store.list_mission_runs_for_plan(plan.plan_id)]
    runtime_map = _node_runtime_map(store, plan)
    graph_nodes = [
        {
            **node.to_dict(),
            "runtime": runtime_map.get(node.node_id, {"status": "draft"}),
        }
        for node in plan.current_nodes
    ]
    history = {
        "versions": [version.to_dict() for version in versions],
        "mission_runs": [run.to_dict() for run in mission_runs],
        "planner": dict(plan.planner_debug),
    }
    return {
        **_plan_summary(store, plan),
        "graph": {
            "plan_id": plan.plan_id,
            "nodes": graph_nodes,
            "selected_version_id": plan.selected_version_id,
            "active_mission_run_id": plan.active_mission_run_id,
        },
        "history": history,
    }


def _project_detail(store: ProjectGraphStore, project: ProjectRecord, *, selected_plan_id: str | None = None) -> dict[str, Any]:
    plans = store.list_plans_for_project(project.project_id)
    selected_plan = (
        next((plan for plan in plans if plan.plan_id == selected_plan_id), None)
        if selected_plan_id
        else (plans[0] if plans else None)
    )
    scheduler = build_scheduler_state(store, project.project_id)
    summary = _project_summary(store, project)
    detail = {
        "project": project.to_dict(),
        "summary": summary,
        "plans": [_plan_summary(store, plan) for plan in plans],
        "selected_plan_id": selected_plan.plan_id if selected_plan is not None else None,
        "selected_plan": _plan_detail(store, selected_plan) if selected_plan is not None else None,
        "scheduler": scheduler,
        "history": {
            "plan_versions": [version.to_dict() for plan in plans for version in store.list_versions_for_plan(plan.plan_id)],
            "mission_runs": [run.to_dict() for run in store.list_mission_runs_for_project(project.project_id)],
        },
        # Compatibility fields for legacy screens/tests.
        "context": {
            "repo_root": project.repo_root,
            "primary_working_directory": summary["primary_working_directory"],
            "working_directories": list(project.settings.get("working_directories") or [project.repo_root]),
            "goal": project.description,
            "definition_of_done": [],
            "planned_task_count": summary["planned_task_count"],
            "task_titles": [node.title for plan in plans for node in plan.current_nodes][:12],
            "mission_count": len(store.list_mission_runs_for_project(project.project_id)),
        },
        "cycles": [
            {
                "cycle_id": plan.plan_id,
                "title": plan.name,
                "status": plan.status if plan.status != "draft" else "planning",
                "draft_id": None,
                "mission_id": store.get_mission_run(plan.active_mission_run_id).mission_id if plan.active_mission_run_id and store.get_mission_run(plan.active_mission_run_id) else None,
                "latest_plan_run_id": None,
                "latest_plan_version_id": plan.selected_version_id,
                "predecessor_cycle_id": plan.supersedes_plan_id,
                "successor_cycle_id": None,
                "blocker": None,
                "next_action": "Open workspace",
                "created_at": plan.created_at,
                "updated_at": plan.updated_at,
                "evidence": {
                    "status": "pending",
                    "contract_summary": "Project-first DAG",
                    "verifier_summary": None,
                    "artifact_summary": None,
                    "stream_summary": None,
                    "items": [],
                },
            }
            for plan in plans
        ],
        "active_cycle_id": selected_plan.plan_id if selected_plan is not None else None,
        "active_cycle": {
            "cycle_id": selected_plan.plan_id,
            "title": selected_plan.name,
            "status": selected_plan.status if selected_plan.status != "draft" else "planning",
            "draft_id": None,
            "mission_id": store.get_mission_run(selected_plan.active_mission_run_id).mission_id if selected_plan.active_mission_run_id and store.get_mission_run(selected_plan.active_mission_run_id) else None,
            "latest_plan_run_id": None,
            "latest_plan_version_id": selected_plan.selected_version_id,
            "predecessor_cycle_id": selected_plan.supersedes_plan_id,
            "successor_cycle_id": None,
            "blocker": None,
            "next_action": "Open workspace",
            "created_at": selected_plan.created_at,
            "updated_at": selected_plan.updated_at,
            "evidence": {
                "status": "pending",
                "contract_summary": "Project-first DAG",
                "verifier_summary": None,
                "artifact_summary": None,
                "stream_summary": None,
                "items": [],
            },
        } if selected_plan is not None else None,
        "evidence": {
            "status": "pending",
            "contract_summary": "Project-first DAG",
            "verifier_summary": None,
            "artifact_summary": None,
            "stream_summary": None,
            "items": [],
        },
        "docs_status": {
            "implemented": ["project-first DAG store", "project scheduler", "graph workspace"],
            "planned": ["planner transcript deep links"],
        },
        "policy_summary": {
            "mode": "standard",
            "derived": False,
            "optimize_available": False,
        },
        "lifecycle": {
            "archived": bool(project.archived_at),
            "archived_at": project.archived_at,
            "can_archive": not project.archived_at,
            "can_unarchive": bool(project.archived_at),
            "can_delete": not plans,
            "can_edit": True,
            "has_activity": bool(plans),
        },
    }
    return detail


def _start_plan(store: ProjectGraphStore, plan: PlanRecord) -> tuple[int, dict[str, Any]]:
    from agentforce.server.routes.missions import _make_mission_state_from_spec

    if not plan.selected_version_id:
        return 409, {"error": "plan does not have an approved version"}
    version = store.get_version(plan.selected_version_id)
    project = store.get_project(plan.project_id)
    if version is None or project is None:
        return 404, {"error": "plan version or project not found"}

    spec = _spec_from_plan(version, working_directory=project.repo_root)
    state = _make_mission_state_from_spec(spec)
    state.source_plan_version_id = version.version_id
    state.source_plan_run_id = None
    state.source_draft_id = None
    state.log_event("mission_started", details="Started via project-first DAG")
    state_dir = state_io.get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    state.save(state_dir / f"{state.mission_id}.json")

    run = store.save_mission_run(
        MissionRunRecord(
            mission_run_id=_slug("mission-run"),
            plan_id=plan.plan_id,
            plan_version_id=version.version_id,
            project_id=plan.project_id,
            mission_id=state.mission_id,
            status="queued",
        )
    )
    version = store.save_version(PlanVersionRecord.from_dict({
        **version.to_dict(),
        "launched_mission_run_id": run.mission_run_id,
    }))
    plan = store.save_plan(PlanRecord.from_dict({
        **plan.to_dict(),
        "status": "running",
        "active_mission_run_id": run.mission_run_id,
    }))
    _launch_mission(state.mission_id)
    state_io._broadcast_mission_list_refresh()
    return 200, {
        "mission_run_id": run.mission_run_id,
        "mission_id": state.mission_id,
        "plan_id": plan.plan_id,
        "version_id": version.version_id,
        "status": "started",
    }


def get(handler, parts: list[str], query: dict[str, str]):
    store = _store()
    include_archived = _normalize_bool(query.get("include_archived"))
    if parts == ["api", "projects"]:
        return 200, [_project_summary(store, project) for project in store.list_projects(include_archived=include_archived)]
    if parts == ["api", "project", "lookup"]:
        mission_id = str(query.get("mission_id") or "").strip()
        if mission_id:
            for project in store.list_projects(include_archived=True):
                for run in store.list_mission_runs_for_project(project.project_id):
                    if run.mission_id == mission_id:
                        return 200, {"project_id": project.project_id}
        return 404, {"error": "Project lookup failed"}
    if len(parts) == 3 and parts[:2] == ["api", "project"]:
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        return 200, _project_detail(store, project, selected_plan_id=query.get("plan_id"))
    if len(parts) == 3 and parts[:2] == ["api", "projects"]:
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        return 200, _project_detail(store, project, selected_plan_id=query.get("plan_id"))
    if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "plans":
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        return 200, [_plan_summary(store, plan) for plan in store.list_plans_for_project(project.project_id)]
    if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "scheduler":
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        return 200, build_scheduler_state(store, project.project_id)
    if len(parts) == 3 and parts[:2] == ["api", "plans"]:
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        return 200, _plan_detail(store, plan)
    if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "graph":
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        return 200, _plan_detail(store, plan)["graph"]
    if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "history":
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        return 200, _plan_detail(store, plan)["history"]
    return 404, {"error": "Not found"}


def post(handler, parts: list[str], query: dict[str, str]):  # noqa: ARG001
    store = _store()
    if parts == ["api", "projects"]:
        body = handler._read_json_body()
        repo_root = str(Path(body.get("repo_root") or "").expanduser().resolve()) if body.get("repo_root") else ""
        if not repo_root:
            return 400, {"error": "repo_root is required"}
        project = store.save_project(ProjectRecord.from_dict({
            "project_id": body.get("project_id") or _slug("project"),
            "name": body.get("name") or Path(repo_root).name or "Project",
            "repo_root": repo_root,
            "description": body.get("description") or body.get("goal"),
            "related_project_ids": body.get("related_project_ids") or [],
            "settings": {
                "working_directories": body.get("working_directories") or [repo_root],
                **dict(body.get("settings") or {}),
            },
        }))
        return 201, _project_detail(store, project)
    if len(parts) == 4 and parts[:2] == ["api", "project"] and parts[3] in {"archive", "unarchive"}:
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        saved = store.save_project(ProjectRecord.from_dict({
            **project.to_dict(),
            "archived_at": _utc_now() if parts[3] == "archive" else None,
        }))
        return 200, {"archived": bool(saved.archived_at)}
    if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "plans":
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        body = handler._read_json_body()
        objective = str(body.get("objective") or body.get("prompt") or "").strip()
        if not objective:
            return 400, {"error": "objective is required"}
        quick_task = body.get("quick_task") is True
        nodes, planner_debug = generate_nodes_from_prompt(project, objective, quick_task=quick_task)
        plan = store.save_plan(PlanRecord(
            plan_id=_slug("plan"),
            project_id=project.project_id,
            name=str(body.get("name") or _title_from_goal(objective)),
            objective=objective,
            status="draft",
            quick_task=quick_task,
            current_nodes=nodes,
            merged_project_scope=sorted({project.project_id, *[owner for node in nodes for owner in node.merged_project_scope]}),
            planner_debug=planner_debug,
            supersedes_plan_id=str(body.get("supersedes_plan_id") or "").strip() or None,
        ))
        return 201, _plan_detail(store, plan)
    if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "generate-dag":
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        project = store.get_project(plan.project_id)
        if project is None:
            return 404, {"error": "owning project not found"}
        body = handler._read_json_body()
        objective = str(body.get("objective") or plan.objective).strip()
        quick_task = body.get("quick_task") is True or plan.quick_task
        nodes, planner_debug = generate_nodes_from_prompt(project, objective, quick_task=quick_task)
        saved = store.save_plan(PlanRecord.from_dict({
            **plan.to_dict(),
            "name": str(body.get("name") or plan.name),
            "objective": objective,
            "quick_task": quick_task,
            "current_nodes": [node.to_dict() for node in nodes],
            "planner_debug": planner_debug,
            "status": "draft",
        }))
        return 200, _plan_detail(store, saved)
    if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "approve-version":
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        version = store.save_version(PlanVersionRecord(
            version_id=_slug("version"),
            plan_id=plan.plan_id,
            project_id=plan.project_id,
            name=plan.name,
            objective=plan.objective,
            nodes=plan.current_nodes,
            merged_project_scope=plan.merged_project_scope,
            changelog=[f"Approved from current graph with {len(plan.current_nodes)} node(s)."],
            planner_debug=plan.planner_debug,
        ))
        saved = store.save_plan(PlanRecord.from_dict({
            **plan.to_dict(),
            "selected_version_id": version.version_id,
            "status": "ready",
        }))
        return 200, {
            "plan_id": saved.plan_id,
            "selected_version_id": version.version_id,
            "version": version.to_dict(),
        }
    if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "start":
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        return _start_plan(store, plan)
    if len(parts) == 4 and parts[:2] == ["api", "plans"] and parts[3] == "readjust":
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        cloned = store.save_plan(PlanRecord.from_dict({
            **plan.to_dict(),
            "plan_id": _slug("plan"),
            "name": f"{plan.name} Readjusted",
            "selected_version_id": None,
            "active_mission_run_id": None,
            "status": "draft",
            "supersedes_plan_id": plan.plan_id,
        }))
        return 201, _plan_detail(store, cloned)
    if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "scheduler" and parts[4] == "reprioritize":
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        body = handler._read_json_body()
        updates = dict(body.get("overrides") or {})
        settings = dict(project.settings)
        settings["scheduler_overrides"] = {
            **dict(settings.get("scheduler_overrides") or {}),
            **{str(key): int(value) for key, value in updates.items()},
        }
        project = store.save_project(ProjectRecord.from_dict({
            **project.to_dict(),
            "settings": settings,
        }))
        return 200, build_scheduler_state(store, project.project_id)
    return 404, {"error": "Not found"}


def patch(handler, parts: list[str], query: dict[str, str]):  # noqa: ARG001
    store = _store()
    if len(parts) == 3 and (parts[:2] == ["api", "projects"] or parts[:2] == ["api", "project"]):
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        body = handler._read_json_body()
        settings = dict(project.settings)
        if "working_directories" in body:
            settings["working_directories"] = body.get("working_directories") or [project.repo_root]
        saved = store.save_project(ProjectRecord.from_dict({
            **project.to_dict(),
            "name": body.get("name") or project.name,
            "description": body.get("description") or body.get("goal") or project.description,
            "related_project_ids": body.get("related_project_ids") or project.related_project_ids,
            "settings": settings,
        }))
        return 200, _project_detail(store, saved)
    if len(parts) == 5 and parts[:2] == ["api", "plans"] and parts[3] == "nodes":
        plan = store.get_plan(parts[2])
        if plan is None:
            return 404, {"error": f"Plan {parts[2]!r} not found"}
        node_id = parts[4]
        body = handler._read_json_body()
        next_nodes: list[PlanNodeRecord] = []
        found = False
        for node in plan.current_nodes:
            if node.node_id != node_id:
                next_nodes.append(node)
                continue
            found = True
            next_nodes.append(PlanNodeRecord.from_dict({
                **node.to_dict(),
                "title": body.get("title") if "title" in body else node.title,
                "description": body.get("description") if "description" in body else node.description,
                "dependencies": body.get("dependencies") if "dependencies" in body else node.dependencies,
                "subtasks": body.get("subtasks") if "subtasks" in body else node.subtasks,
                "touch_scope": body.get("touch_scope") if "touch_scope" in body else node.touch_scope,
                "outputs": body.get("outputs") if "outputs" in body else node.outputs,
                "owner_project_id": body.get("owner_project_id") if "owner_project_id" in body else node.owner_project_id,
                "merged_project_scope": body.get("merged_project_scope") if "merged_project_scope" in body else node.merged_project_scope,
                "evidence": body.get("evidence") if "evidence" in body else node.evidence,
                "working_directory": body.get("working_directory") if "working_directory" in body else node.working_directory,
            }))
        if not found:
            return 404, {"error": f"Node {node_id!r} not found"}
        saved = store.save_plan(PlanRecord.from_dict({
            **plan.to_dict(),
            "current_nodes": [node.to_dict() for node in next_nodes],
            "merged_project_scope": sorted({plan.project_id, *[scope for node in next_nodes for scope in node.merged_project_scope or [node.owner_project_id]]}),
        }))
        return 200, _plan_detail(store, saved)
    return 404, {"error": "Not found"}


def delete(handler, parts: list[str], query: dict[str, str]):  # noqa: ARG001
    store = _store()
    if len(parts) == 3 and (parts[:2] == ["api", "projects"] or parts[:2] == ["api", "project"]):
        project = store.get_project(parts[2])
        if project is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        if store.list_plans_for_project(project.project_id):
            return 409, {"error": "Project with plans cannot be deleted"}
        store.delete_project(project.project_id)
        return 200, {"deleted": True}
    return 404, {"error": "Not found"}
