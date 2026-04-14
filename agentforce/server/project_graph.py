"""Project-first DAG storage and derived runtime views."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.core.state import MissionState
from agentforce.server import state_io
from agentforce.server.planner_adapter import (
    DeterministicPlannerAdapter,
    LivePlannerAdapter,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_path(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except Exception:
        return text


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _title_from_goal(goal: str) -> str:
    words = [part for part in goal.replace("-", " ").split() if part]
    if not words:
        return "Untitled Plan"
    return " ".join(word.capitalize() for word in words[:8])


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _status_value(task_state: Any) -> str:
    return str(getattr(task_state.status, "value", task_state.status))


GRAPH_HOME_DIRNAME = "project_graph"


def graph_home() -> Path:
    return state_io.get_agentforce_home() / GRAPH_HOME_DIRNAME


@dataclass(frozen=True)
class PlanNodeRecord:
    node_id: str
    title: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    subtasks: list[str] = field(default_factory=list)
    touch_scope: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    owner_project_id: str = ""
    merged_project_scope: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    working_directory: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanNodeRecord":
        owner_project_id = _normalize_text(payload.get("owner_project_id"))
        merged_project_scope = _dedupe([
            _normalize_text(value) for value in list(payload.get("merged_project_scope") or [])
        ])
        if owner_project_id and owner_project_id not in merged_project_scope:
            merged_project_scope.insert(0, owner_project_id)
        return cls(
            node_id=_normalize_text(payload.get("node_id")) or _slug("node"),
            title=_normalize_text(payload.get("title")) or "Untitled node",
            description=_normalize_text(payload.get("description")),
            dependencies=_dedupe([_normalize_text(value) for value in list(payload.get("dependencies") or [])]),
            subtasks=[_normalize_text(value) for value in list(payload.get("subtasks") or []) if _normalize_text(value)],
            touch_scope=_dedupe([_normalize_text(value) for value in list(payload.get("touch_scope") or [])]),
            outputs=[_normalize_text(value) for value in list(payload.get("outputs") or []) if _normalize_text(value)],
            owner_project_id=owner_project_id,
            merged_project_scope=merged_project_scope,
            evidence=[_normalize_text(value) for value in list(payload.get("evidence") or []) if _normalize_text(value)],
            working_directory=_normalize_path(payload.get("working_directory")) or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    name: str
    repo_root: str
    description: str | None = None
    related_project_ids: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    archived_at: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectRecord":
        repo_root = _normalize_path(payload.get("repo_root"))
        settings = dict(payload.get("settings") or {})
        working_directories = _dedupe([
            _normalize_path(value) for value in list(settings.get("working_directories") or [])
        ])
        if not working_directories and repo_root:
            working_directories = [repo_root]
        settings["working_directories"] = working_directories
        return cls(
            project_id=_normalize_text(payload.get("project_id")) or _slug("project"),
            name=_normalize_text(payload.get("name")) or Path(repo_root or ".").name or "Project",
            repo_root=repo_root,
            description=_normalize_text(payload.get("description")) or None,
            related_project_ids=_dedupe([_normalize_text(value) for value in list(payload.get("related_project_ids") or [])]),
            settings=settings,
            archived_at=_normalize_text(payload.get("archived_at")) or None,
            created_at=_normalize_text(payload.get("created_at")) or _utc_now(),
            updated_at=_normalize_text(payload.get("updated_at")) or _utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanRecord:
    plan_id: str
    project_id: str
    name: str
    objective: str
    status: str
    quick_task: bool
    current_nodes: list[PlanNodeRecord] = field(default_factory=list)
    selected_version_id: str | None = None
    active_mission_run_id: str | None = None
    merged_project_scope: list[str] = field(default_factory=list)
    planner_debug: dict[str, Any] = field(default_factory=dict)
    supersedes_plan_id: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanRecord":
        current_nodes = [
            PlanNodeRecord.from_dict(item)
            for item in list(payload.get("current_nodes") or [])
            if isinstance(item, dict)
        ]
        merged_project_scope = _dedupe([
            _normalize_text(value) for value in list(payload.get("merged_project_scope") or [])
        ])
        project_id = _normalize_text(payload.get("project_id"))
        if project_id and project_id not in merged_project_scope:
            merged_project_scope.insert(0, project_id)
        return cls(
            plan_id=_normalize_text(payload.get("plan_id")) or _slug("plan"),
            project_id=project_id,
            name=_normalize_text(payload.get("name")) or _title_from_goal(_normalize_text(payload.get("objective"))),
            objective=_normalize_text(payload.get("objective")),
            status=_normalize_text(payload.get("status")) or "draft",
            quick_task=bool(payload.get("quick_task")),
            current_nodes=current_nodes,
            selected_version_id=_normalize_text(payload.get("selected_version_id")) or None,
            active_mission_run_id=_normalize_text(payload.get("active_mission_run_id")) or None,
            merged_project_scope=merged_project_scope,
            planner_debug=dict(payload.get("planner_debug") or {}),
            supersedes_plan_id=_normalize_text(payload.get("supersedes_plan_id")) or None,
            created_at=_normalize_text(payload.get("created_at")) or _utc_now(),
            updated_at=_normalize_text(payload.get("updated_at")) or _utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["current_nodes"] = [node.to_dict() for node in self.current_nodes]
        return payload


@dataclass(frozen=True)
class PlanVersionRecord:
    version_id: str
    plan_id: str
    project_id: str
    name: str
    objective: str
    nodes: list[PlanNodeRecord]
    merged_project_scope: list[str] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)
    planner_debug: dict[str, Any] = field(default_factory=dict)
    launched_mission_run_id: str | None = None
    created_at: str = field(default_factory=_utc_now)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanVersionRecord":
        return cls(
            version_id=_normalize_text(payload.get("version_id")) or _slug("version"),
            plan_id=_normalize_text(payload.get("plan_id")),
            project_id=_normalize_text(payload.get("project_id")),
            name=_normalize_text(payload.get("name")) or "Version",
            objective=_normalize_text(payload.get("objective")),
            nodes=[
                PlanNodeRecord.from_dict(item)
                for item in list(payload.get("nodes") or [])
                if isinstance(item, dict)
            ],
            merged_project_scope=_dedupe([
                _normalize_text(value) for value in list(payload.get("merged_project_scope") or [])
            ]),
            changelog=[_normalize_text(value) for value in list(payload.get("changelog") or []) if _normalize_text(value)],
            planner_debug=dict(payload.get("planner_debug") or {}),
            launched_mission_run_id=_normalize_text(payload.get("launched_mission_run_id")) or None,
            created_at=_normalize_text(payload.get("created_at")) or _utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [node.to_dict() for node in self.nodes]
        return payload


@dataclass(frozen=True)
class MissionNodeStateRecord:
    node_id: str
    status: str
    reason: str | None = None
    task_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MissionNodeStateRecord":
        return cls(
            node_id=_normalize_text(payload.get("node_id")),
            status=_normalize_text(payload.get("status")) or "queued",
            reason=_normalize_text(payload.get("reason")) or None,
            task_id=_normalize_text(payload.get("task_id")) or None,
            started_at=_normalize_text(payload.get("started_at")) or None,
            completed_at=_normalize_text(payload.get("completed_at")) or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MissionRunRecord:
    mission_run_id: str
    plan_id: str
    plan_version_id: str
    project_id: str
    mission_id: str | None = None
    status: str = "queued"
    node_states: list[MissionNodeStateRecord] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str = field(default_factory=_utc_now)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MissionRunRecord":
        return cls(
            mission_run_id=_normalize_text(payload.get("mission_run_id")) or _slug("mission-run"),
            plan_id=_normalize_text(payload.get("plan_id")),
            plan_version_id=_normalize_text(payload.get("plan_version_id")),
            project_id=_normalize_text(payload.get("project_id")),
            mission_id=_normalize_text(payload.get("mission_id")) or None,
            status=_normalize_text(payload.get("status")) or "queued",
            node_states=[
                MissionNodeStateRecord.from_dict(item)
                for item in list(payload.get("node_states") or [])
                if isinstance(item, dict)
            ],
            created_at=_normalize_text(payload.get("created_at")) or _utc_now(),
            started_at=_normalize_text(payload.get("started_at")) or None,
            completed_at=_normalize_text(payload.get("completed_at")) or None,
            updated_at=_normalize_text(payload.get("updated_at")) or _utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["node_states"] = [state.to_dict() for state in self.node_states]
        return payload


class ProjectGraphStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or graph_home()
        self.projects_path = self.root / "projects.json"
        self.plans_dir = self.root / "plans"
        self.versions_dir = self.root / "versions"
        self.mission_runs_dir = self.root / "mission_runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.mission_runs_dir.mkdir(parents=True, exist_ok=True)

    def _load_map(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_map(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_entity(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_entity(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_projects(self, *, include_archived: bool = False) -> list[ProjectRecord]:
        records = [
            ProjectRecord.from_dict(value)
            for value in self._load_map(self.projects_path).values()
            if isinstance(value, dict)
        ]
        if not include_archived:
            records = [record for record in records if not record.archived_at]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def get_project(self, project_id: str) -> ProjectRecord | None:
        payload = self._load_map(self.projects_path).get(project_id)
        if not isinstance(payload, dict):
            return None
        return ProjectRecord.from_dict(payload)

    def save_project(self, project: ProjectRecord) -> ProjectRecord:
        payload = self._load_map(self.projects_path)
        now = _utc_now()
        existing = self.get_project(project.project_id)
        saved = ProjectRecord(
            project_id=project.project_id,
            name=project.name,
            repo_root=project.repo_root,
            description=project.description,
            related_project_ids=project.related_project_ids,
            settings=dict(project.settings),
            archived_at=project.archived_at,
            created_at=existing.created_at if existing is not None else project.created_at or now,
            updated_at=now,
        )
        payload[saved.project_id] = saved.to_dict()
        self._save_map(self.projects_path, payload)
        return saved

    def delete_project(self, project_id: str) -> bool:
        payload = self._load_map(self.projects_path)
        if project_id not in payload:
            return False
        payload.pop(project_id, None)
        self._save_map(self.projects_path, payload)
        return True

    def list_plans_for_project(self, project_id: str) -> list[PlanRecord]:
        plans: list[PlanRecord] = []
        for path in sorted(self.plans_dir.glob("*.json")):
            payload = self._load_entity(path)
            if not isinstance(payload, dict):
                continue
            plan = PlanRecord.from_dict(payload)
            if plan.project_id == project_id:
                plans.append(plan)
        return sorted(plans, key=lambda item: item.updated_at, reverse=True)

    def list_all_plans(self) -> list[PlanRecord]:
        plans: list[PlanRecord] = []
        for path in sorted(self.plans_dir.glob("*.json")):
            payload = self._load_entity(path)
            if not isinstance(payload, dict):
                continue
            plans.append(PlanRecord.from_dict(payload))
        return sorted(plans, key=lambda item: item.updated_at, reverse=True)

    def get_plan(self, plan_id: str) -> PlanRecord | None:
        payload = self._load_entity(self.plans_dir / f"{plan_id}.json")
        if not isinstance(payload, dict):
            return None
        return PlanRecord.from_dict(payload)

    def save_plan(self, plan: PlanRecord) -> PlanRecord:
        now = _utc_now()
        existing = self.get_plan(plan.plan_id)
        saved = PlanRecord.from_dict({
            **plan.to_dict(),
            "created_at": existing.created_at if existing is not None else plan.created_at or now,
            "updated_at": now,
        })
        self._save_entity(self.plans_dir / f"{saved.plan_id}.json", saved.to_dict())
        return saved

    def list_versions_for_plan(self, plan_id: str) -> list[PlanVersionRecord]:
        versions: list[PlanVersionRecord] = []
        for path in sorted(self.versions_dir.glob("*.json")):
            payload = self._load_entity(path)
            if not isinstance(payload, dict):
                continue
            version = PlanVersionRecord.from_dict(payload)
            if version.plan_id == plan_id:
                versions.append(version)
        return sorted(versions, key=lambda item: item.created_at, reverse=True)

    def get_version(self, version_id: str) -> PlanVersionRecord | None:
        payload = self._load_entity(self.versions_dir / f"{version_id}.json")
        if not isinstance(payload, dict):
            return None
        return PlanVersionRecord.from_dict(payload)

    def save_version(self, version: PlanVersionRecord) -> PlanVersionRecord:
        saved = PlanVersionRecord.from_dict(version.to_dict())
        self._save_entity(self.versions_dir / f"{saved.version_id}.json", saved.to_dict())
        return saved

    def list_mission_runs_for_plan(self, plan_id: str) -> list[MissionRunRecord]:
        runs: list[MissionRunRecord] = []
        for path in sorted(self.mission_runs_dir.glob("*.json")):
            payload = self._load_entity(path)
            if not isinstance(payload, dict):
                continue
            run = MissionRunRecord.from_dict(payload)
            if run.plan_id == plan_id:
                runs.append(run)
        return sorted(runs, key=lambda item: item.updated_at, reverse=True)

    def list_mission_runs_for_project(self, project_id: str) -> list[MissionRunRecord]:
        runs: list[MissionRunRecord] = []
        for path in sorted(self.mission_runs_dir.glob("*.json")):
            payload = self._load_entity(path)
            if not isinstance(payload, dict):
                continue
            run = MissionRunRecord.from_dict(payload)
            if run.project_id == project_id:
                runs.append(run)
        return sorted(runs, key=lambda item: item.updated_at, reverse=True)

    def get_mission_run(self, mission_run_id: str) -> MissionRunRecord | None:
        payload = self._load_entity(self.mission_runs_dir / f"{mission_run_id}.json")
        if not isinstance(payload, dict):
            return None
        return MissionRunRecord.from_dict(payload)

    def save_mission_run(self, run: MissionRunRecord) -> MissionRunRecord:
        saved = MissionRunRecord.from_dict({
            **run.to_dict(),
            "updated_at": _utc_now(),
        })
        self._save_entity(self.mission_runs_dir / f"{saved.mission_run_id}.json", saved.to_dict())
        return saved


def _default_caps() -> Caps:
    return Caps(
        max_concurrent_workers=1,
        max_retries_per_task=3,
        max_retries_global=3,
        max_wall_time_minutes=120,
        max_human_interventions=2,
    )


def _spec_from_plan(version: PlanVersionRecord, working_directory: str | None = None) -> MissionSpec:
    tasks: list[TaskSpec] = []
    for node in version.nodes:
        tasks.append(
            TaskSpec(
                id=node.node_id,
                title=node.title,
                description=node.description,
                acceptance_criteria=node.subtasks,
                dependencies=node.dependencies,
                working_dir=node.working_directory or working_directory,
                output_artifacts=node.outputs,
            )
        )
    return MissionSpec(
        name=version.name,
        goal=version.objective,
        definition_of_done=["Approved project-first DAG executes cleanly."],
        tasks=tasks,
        caps=_default_caps(),
        working_dir=working_directory,
    )


def _build_touch_scope(node: PlanNodeRecord) -> list[str]:
    if node.touch_scope:
        return node.touch_scope
    fallback = [node.node_id]
    if node.working_directory:
        fallback.append(node.working_directory)
    for output in node.outputs:
        fallback.append(output)
    return _dedupe([value for value in fallback if value])


def _dependencies_satisfied(
    node: PlanNodeRecord,
    node_states: dict[str, MissionNodeStateRecord],
) -> bool:
    return all(
        node_states.get(dep) is not None
        and node_states[dep].status in {"completed", "review_approved"}
        for dep in node.dependencies
        if dep in node_states
    )


def _topological_levels(nodes: list[PlanNodeRecord]) -> dict[str, int]:
    levels: dict[str, int] = {}
    nodes_by_id = {node.node_id: node for node in nodes}

    def _level(node_id: str, seen: set[str] | None = None) -> int:
        if node_id in levels:
            return levels[node_id]
        if node_id not in nodes_by_id:
            return 0
        seen = seen or set()
        if node_id in seen:
            return 0
        seen.add(node_id)
        deps = [dep for dep in nodes_by_id[node_id].dependencies if dep in nodes_by_id]
        level = 0 if not deps else 1 + max(_level(dep, seen.copy()) for dep in deps)
        levels[node_id] = level
        return level

    for node in nodes:
        _level(node.node_id)
    return levels


def _planner_response_to_nodes(
    project_id: str,
    spec_dict: dict[str, Any],
    *,
    working_directory: str | None,
) -> list[PlanNodeRecord]:
    spec = MissionSpec.from_dict(spec_dict)
    nodes: list[PlanNodeRecord] = []
    for task in spec.tasks:
        outputs = list(task.output_artifacts or [])
        touch_scope = _dedupe([*(outputs or []), *([task.working_dir] if task.working_dir else []), task.id])
        nodes.append(
            PlanNodeRecord(
                node_id=task.id,
                title=task.title,
                description=task.description,
                dependencies=list(task.dependencies or []),
                subtasks=list(task.acceptance_criteria or []),
                touch_scope=touch_scope,
                outputs=outputs,
                owner_project_id=project_id,
                merged_project_scope=[project_id],
                evidence=[],
                working_directory=_normalize_path(task.working_dir or working_directory) or None,
            )
        )
    if nodes:
        return nodes
    return [
        PlanNodeRecord(
            node_id=_slug("node"),
            title=_title_from_goal(spec.goal),
            description=spec.goal,
            subtasks=["Refine this plan into executable subtasks."],
            touch_scope=[project_id],
            owner_project_id=project_id,
            merged_project_scope=[project_id],
            working_directory=_normalize_path(working_directory) or None,
        )
    ]


def generate_nodes_from_prompt(project: ProjectRecord, prompt: str, *, quick_task: bool = False) -> tuple[list[PlanNodeRecord], dict[str, Any]]:
    working_directory = ""
    working_directories = list(project.settings.get("working_directories") or [])
    if working_directories:
        working_directory = _normalize_path(working_directories[0])
    if quick_task:
        node = PlanNodeRecord(
            node_id=_slug("node"),
            title=_title_from_goal(prompt),
            description=prompt,
            dependencies=[],
            subtasks=["Complete the requested quick task."],
            touch_scope=[project.project_id],
            outputs=[],
            owner_project_id=project.project_id,
            merged_project_scope=[project.project_id],
            evidence=[],
            working_directory=working_directory or project.repo_root,
        )
        return [node], {
            "assistant_message": "Created a one-node quick-task plan.",
            "provider": "quick-task",
        }

    base_spec = {
        "name": _title_from_goal(prompt),
        "goal": prompt,
        "definition_of_done": ["Planner draft is ready for refinement"],
        "tasks": [],
        "caps": _default_caps().to_dict(),
        "working_dir": working_directory or project.repo_root,
    }
    draft_payload = {
        "draft_spec": base_spec,
        "validation": {},
        "workspace_paths": [working_directory or project.repo_root],
    }
    debug: dict[str, Any] = {"prompt": prompt}
    for adapter_name, adapter in (("live", LivePlannerAdapter()), ("deterministic", DeterministicPlannerAdapter())):
        try:
            turn = adapter.plan_turn(draft_payload, prompt)
            nodes = _planner_response_to_nodes(
                project.project_id,
                turn.draft_spec,
                working_directory=working_directory or project.repo_root,
            )
            debug.update({
                "assistant_message": turn.assistant_message,
                "provider": adapter_name,
                "draft_spec": turn.draft_spec,
            })
            return nodes, debug
        except Exception as exc:
            debug.setdefault("errors", []).append(f"{adapter_name}: {exc}")
            continue
    fallback = PlanNodeRecord(
        node_id=_slug("node"),
        title=_title_from_goal(prompt),
        description=prompt,
        subtasks=["Refine the fallback planner output."],
        touch_scope=[project.project_id],
        owner_project_id=project.project_id,
        merged_project_scope=[project.project_id],
        working_directory=working_directory or project.repo_root,
    )
    debug["assistant_message"] = "Planner fallback created a single-node graph."
    debug["provider"] = "fallback"
    return [fallback], debug


def sync_mission_run(store: ProjectGraphStore, run: MissionRunRecord) -> MissionRunRecord:
    if not run.mission_id:
        return run
    state = state_io._load_state(run.mission_id)
    if state is None:
        return run
    version = store.get_version(run.plan_version_id)
    if version is None:
        return run
    nodes_by_id = {node.node_id: node for node in version.nodes}
    next_states: list[MissionNodeStateRecord] = []
    any_running = False
    any_failed = False
    all_complete = True
    for node in version.nodes:
        task_state = state.task_states.get(node.node_id)
        status = "queued"
        reason = None
        started_at = None
        completed_at = None
        if task_state is not None:
            raw = _status_value(task_state)
            started_at = _normalize_text(getattr(task_state, "started_at", "")) or None
            completed_at = _normalize_text(getattr(task_state, "completed_at", "")) or None
            if raw in {"review_approved", "completed"}:
                status = "completed"
            elif raw in {"in_progress", "spec_writing", "tests_written"}:
                status = "running"
                any_running = True
                all_complete = False
            elif raw in {"reviewing"}:
                status = "reviewing"
                any_running = True
                all_complete = False
            elif raw in {"failed", "blocked", "needs_human", "review_rejected"}:
                status = "blocked"
                any_failed = True
                all_complete = False
                reason = _normalize_text(getattr(task_state, "human_intervention_message", "")) or _normalize_text(getattr(task_state, "error_message", "")) or raw.replace("_", " ")
            else:
                deps_complete = all(
                    _status_value(state.task_states.get(dep)) in {"review_approved", "completed"}
                    for dep in node.dependencies
                    if dep in state.task_states
                )
                status = "queued" if deps_complete else "blocked"
                all_complete = False
                if not deps_complete:
                    reason = "Waiting on dependencies"
        else:
            all_complete = False
        next_states.append(
            MissionNodeStateRecord(
                node_id=node.node_id,
                status=status,
                reason=reason,
                task_id=node.node_id,
                started_at=started_at,
                completed_at=completed_at,
            )
        )
    status = "completed" if all_complete else "blocked" if any_failed else "running" if any_running else "queued"
    updated = MissionRunRecord.from_dict({
        **run.to_dict(),
        "status": status,
        "node_states": [item.to_dict() for item in next_states],
        "started_at": run.started_at or state.started_at,
        "completed_at": run.completed_at or state.finished_at or state.completed_at,
        "updated_at": _utc_now(),
    })
    return store.save_mission_run(updated)


def build_scheduler_state(store: ProjectGraphStore, project_id: str) -> dict[str, Any]:
    project = store.get_project(project_id)
    overrides = dict((project.settings.get("scheduler_overrides") or {}) if project is not None else {})
    plans = store.list_plans_for_project(project_id)
    runs = [sync_mission_run(store, run) for run in store.list_mission_runs_for_project(project_id)]
    runs_by_plan = {run.plan_id: run for run in runs}
    running_scopes: dict[str, str] = {}
    for run in runs:
        plan = store.get_plan(run.plan_id)
        version = store.get_version(run.plan_version_id)
        if plan is None or version is None:
            continue
        nodes = {node.node_id: node for node in version.nodes}
        node_states = {state.node_id: state for state in run.node_states}
        for node_state in run.node_states:
            node = nodes.get(node_state.node_id)
            is_active_reservation = (
                node_state.status in {"running", "reviewing"}
                or (
                    run.status in {"queued", "running"}
                    and node_state.status == "queued"
                    and node is not None
                    and _dependencies_satisfied(node, node_states)
                )
            )
            if not is_active_reservation:
                continue
            if node is None:
                continue
            for scope in _build_touch_scope(node):
                running_scopes.setdefault(scope, node.node_id)

    queue: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    plans_summary: list[dict[str, Any]] = []

    for plan in plans:
        version = store.get_version(plan.selected_version_id) if plan.selected_version_id else None
        nodes = version.nodes if version is not None else plan.current_nodes
        levels = _topological_levels(nodes)
        run = runs_by_plan.get(plan.plan_id)
        node_states = {state.node_id: state for state in (run.node_states if run is not None else [])}
        completed_ids = {node_id for node_id, state in node_states.items() if state.status == "completed"}
        plan_ready = 0
        plan_blocked = 0
        plan_running = 0
        for node in nodes:
            state = node_states.get(node.node_id)
            is_active_reservation = (
                state is not None
                and (
                    state.status in {"running", "reviewing"}
                    or (
                        run is not None
                        and run.status in {"queued", "running"}
                        and state.status == "queued"
                        and _dependencies_satisfied(node, node_states)
                    )
                )
            )
            if is_active_reservation:
                plan_running += 1
                running.append({
                    "plan_id": plan.plan_id,
                    "plan_name": plan.name,
                    "node_id": node.node_id,
                    "title": node.title,
                    "status": state.status,
                    "scheduler_priority": 100 + sum(1 for candidate in nodes if node.node_id in candidate.dependencies),
                    "owning_project_id": node.owner_project_id,
                    "merged_project_scope": node.merged_project_scope,
                })
                continue
            if state is not None and state.status == "completed":
                continue
            missing = [dep for dep in node.dependencies if dep not in completed_ids]
            if missing:
                plan_blocked += 1
                blocked.append({
                    "plan_id": plan.plan_id,
                    "plan_name": plan.name,
                    "node_id": node.node_id,
                    "title": node.title,
                    "status": "blocked",
                    "conflict_reason": f"Waiting on dependencies: {', '.join(missing)}",
                    "scheduler_priority": 0,
                    "owning_project_id": node.owner_project_id,
                    "merged_project_scope": node.merged_project_scope,
                })
                continue
            conflict = next((scope for scope in _build_touch_scope(node) if scope in running_scopes and running_scopes[scope] != node.node_id), None)
            if conflict:
                plan_blocked += 1
                blocked.append({
                    "plan_id": plan.plan_id,
                    "plan_name": plan.name,
                    "node_id": node.node_id,
                    "title": node.title,
                    "status": "blocked",
                    "conflict_reason": f"Touch scope conflict with active node {conflict}",
                    "scheduler_priority": 0,
                    "owning_project_id": node.owner_project_id,
                    "merged_project_scope": node.merged_project_scope,
                })
                continue
            dependents = sum(1 for candidate in nodes if node.node_id in candidate.dependencies)
            override_key = f"{plan.plan_id}:{node.node_id}"
            priority = 100 + (dependents * 10) - levels.get(node.node_id, 0) + int(overrides.get(override_key, 0) or 0)
            plan_ready += 1
            queue.append({
                "plan_id": plan.plan_id,
                "plan_name": plan.name,
                "node_id": node.node_id,
                "title": node.title,
                "status": "ready",
                "scheduler_priority": priority,
                "owning_project_id": node.owner_project_id,
                "merged_project_scope": node.merged_project_scope,
            })

        plans_summary.append({
            "plan_id": plan.plan_id,
            "name": plan.name,
            "status": plan.status,
            "ready_count": plan_ready,
            "blocked_count": plan_blocked,
            "running_count": plan_running,
            "selected_version_id": plan.selected_version_id,
            "active_mission_run_id": plan.active_mission_run_id,
            "merged_project_scope": plan.merged_project_scope,
            "updated_at": plan.updated_at,
        })

    queue.sort(key=lambda item: item["scheduler_priority"], reverse=True)
    blocked.sort(key=lambda item: (item["plan_name"], item["title"]))
    running.sort(key=lambda item: (item["plan_name"], item["title"]))
    return {
        "project_id": project_id,
        "updated_at": _utc_now(),
        "queue": queue,
        "blocked": blocked,
        "running": running,
        "plans": plans_summary,
    }
