"""Project Harness API routes."""
from __future__ import annotations

from agentforce.server.project_harness import (
    canonical_repo_root,
    get_project_harness,
    list_project_summaries,
    project_id_for_root,
)
from agentforce.server.project_records import ProjectRecordStore


def _bool_query(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _store() -> ProjectRecordStore:
    return ProjectRecordStore()


def _seed_record_for_existing_project(project_id: str):
    store = _store()
    existing = store.get(project_id)
    if existing is not None:
        return existing
    view = get_project_harness(project_id)
    if view is None:
        return None
    return store.save_record(
        project_id=view.summary.project_id,
        repo_root=view.summary.repo_root,
        name=view.summary.name,
        goal=view.context.get("goal"),
        working_directories=list(view.context.get("working_directories") or []),
    )


def get(handler, parts: list[str], query: dict[str, str]):
    include_archived = _bool_query(query.get("include_archived"))
    if parts == ["api", "projects"]:
        return 200, list_project_summaries(include_archived=include_archived)
    if len(parts) == 3 and parts[:2] == ["api", "project"]:
        view = get_project_harness(parts[2])
        if view is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        return 200, view.to_dict()
    return 404, {"error": "Not found"}


def post(handler, parts: list[str], query: dict[str, str]):  # noqa: ARG001
    if parts == ["api", "projects"]:
        body = handler._read_json_body()
        repo_root = canonical_repo_root(body.get("repo_root") or "")
        if not repo_root:
            return 400, {"error": "repo_root is required"}
        project_id = project_id_for_root(repo_root)
        store = _store()
        if store.get(project_id) is not None:
            return 409, {"error": f"Project {project_id!r} already exists"}
        store.save_record(
            project_id=project_id,
            repo_root=repo_root,
            name=body.get("name"),
            goal=body.get("goal"),
            working_directories=list(body.get("working_directories") or []),
        )
        view = get_project_harness(project_id)
        if view is None:
            return 500, {"error": "Failed to create project"}
        return 201, view.to_dict()

    if len(parts) == 4 and parts[:2] == ["api", "project"] and parts[3] == "archive":
        record = _seed_record_for_existing_project(parts[2])
        if record is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        _store().archive(record.project_id)
        return 200, {"archived": True}

    if len(parts) == 4 and parts[:2] == ["api", "project"] and parts[3] == "unarchive":
        record = _seed_record_for_existing_project(parts[2])
        if record is None:
            return 404, {"error": f"Project {parts[2]!r} not found"}
        _store().unarchive(record.project_id)
        return 200, {"unarchived": True}

    return 404, {"error": "Not found"}


def patch(handler, parts: list[str], query: dict[str, str]):  # noqa: ARG001
    if len(parts) != 3 or parts[:2] != ["api", "project"]:
        return 404, {"error": "Not found"}
    record = _seed_record_for_existing_project(parts[2])
    if record is None:
        return 404, {"error": f"Project {parts[2]!r} not found"}
    body = handler._read_json_body()
    updated = _store().update(
        record.project_id,
        name=body.get("name") if "name" in body else None,
        goal=body.get("goal") if "goal" in body else None,
        working_directories=list(body.get("working_directories") or []) if "working_directories" in body else None,
    )
    if updated is None:
        return 404, {"error": f"Project {parts[2]!r} not found"}
    view = get_project_harness(updated.project_id)
    if view is None:
        return 500, {"error": "Failed to update project"}
    return 200, view.to_dict()


def delete(handler, parts: list[str], query: dict[str, str]):  # noqa: ARG001
    if len(parts) != 3 or parts[:2] != ["api", "project"]:
        return 404, {"error": "Not found"}
    view = get_project_harness(parts[2])
    if view is None:
        return 404, {"error": f"Project {parts[2]!r} not found"}
    if view.lifecycle.get("has_activity"):
        return 409, {"error": "Project with active history cannot be deleted"}
    if not view.lifecycle.get("archived"):
        return 409, {"error": "Archive project before deleting"}
    deleted = _store().delete(parts[2])
    if not deleted:
        return 404, {"error": f"Project {parts[2]!r} not found"}
    return 200, {"deleted": True}
