"""Derived Project Harness views built over existing planning and mission stores."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentforce.core.state import MissionState
from agentforce.memory import Memory
from agentforce.telemetry import TelemetryStore

from . import state_io
from .plan_drafts import MissionDraftV1, PlanDraftStore
from .plan_runs import PlanRunStore, PlanRunRecord, PlanVersionRecord
from .project_records import ProjectRecord, ProjectRecordStore


def _iso(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _repo_root_from_git(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            check=True,
            text=True,
        )
    except Exception:
        return None
    output = result.stdout.strip()
    return Path(output).resolve() if output else None


def _existing_probe_path(path: Path) -> Path:
    current = path
    if current.exists():
        return current if current.is_dir() else current.parent
    for parent in current.parents:
        if parent.exists():
            return parent if parent.is_dir() else parent.parent
    return current.parent


def canonical_repo_root(path: str | Path | None) -> str:
    if not path:
        return ""
    resolved = Path(path).expanduser().resolve()
    if resolved.is_file():
        resolved = resolved.parent
    git_root = _repo_root_from_git(_existing_probe_path(resolved))
    return str((git_root or resolved).resolve())


def project_id_for_root(repo_root: str) -> str:
    digest = hashlib.sha1(repo_root.encode("utf-8")).hexdigest()[:12]
    return f"project-{digest}"


@dataclass(frozen=True)
class ProjectEvidenceItem:
    kind: str
    label: str
    status: str
    summary: str
    source_type: str | None = None
    source_id: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectEvidenceSummary:
    status: str
    contract_summary: str | None
    verifier_summary: str | None
    artifact_summary: str | None
    stream_summary: str | None
    items: list[ProjectEvidenceItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload


@dataclass(frozen=True)
class ProjectCycleView:
    cycle_id: str
    title: str
    status: str
    draft_id: str | None
    mission_id: str | None
    latest_plan_run_id: str | None
    latest_plan_version_id: str | None
    predecessor_cycle_id: str | None
    successor_cycle_id: str | None
    blocker: str | None
    next_action: str | None
    created_at: str
    updated_at: str
    evidence: ProjectEvidenceSummary | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.evidence is not None:
            payload["evidence"] = self.evidence.to_dict()
        return payload


@dataclass(frozen=True)
class ProjectSummaryView:
    project_id: str
    name: str
    repo_root: str
    primary_working_directory: str | None
    workspace_count: int
    goal: str | None
    planned_task_count: int
    current_stage: str
    current_plan_id: str | None
    current_mission_id: str | None
    next_action_label: str | None
    mode: str
    status: str
    active_cycle_id: str | None
    blocker: str | None
    next_action: str | None
    active_mission_id: str | None
    archived_at: str | None
    has_activity: bool
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectHarnessView:
    summary: ProjectSummaryView
    context: dict[str, Any]
    cycles: list[ProjectCycleView]
    active_cycle_id: str | None
    active_cycle: ProjectCycleView | None
    evidence: ProjectEvidenceSummary
    docs_status: dict[str, list[str]]
    policy_summary: dict[str, Any]
    lifecycle: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "context": self.context,
            "cycles": [cycle.to_dict() for cycle in self.cycles],
            "active_cycle_id": self.active_cycle_id,
            "active_cycle": self.active_cycle.to_dict() if self.active_cycle is not None else None,
            "evidence": self.evidence.to_dict(),
            "docs_status": self.docs_status,
            "policy_summary": self.policy_summary,
            "lifecycle": self.lifecycle,
        }


def _draft_workspace_root(draft: MissionDraftV1) -> str:
    workspace_candidates = list(draft.workspace_paths or [])
    if not workspace_candidates:
        working_dir = str(draft.draft_spec.get("working_dir") or "").strip()
        if working_dir:
            workspace_candidates.append(working_dir)
    return canonical_repo_root(workspace_candidates[0] if workspace_candidates else "")


def _mission_workspace_root(mission: MissionState) -> str:
    candidate = mission.working_dir or mission.spec.working_dir or ""
    return canonical_repo_root(candidate)


def _mission_cycle_status(mission: MissionState) -> str:
    summary = mission.to_summary_dict()
    status = str(summary.get("status") or "idle")
    if status in {"failed", "needs_human"}:
        return "blocked"
    if status in {"complete", "completed", "finished"}:
        return "completed"
    return "running"


def _draft_cycle_status(draft: MissionDraftV1, runs: list[PlanRunRecord]) -> str:
    validation = dict(draft.validation or {})
    repair_state = dict(validation.get("repair") or {})
    if validation.get("preflight_status") == "pending":
        return "blocked"
    if list(repair_state.get("issues") or []):
        return "blocked"
    if runs:
        latest = runs[0]
        if latest.status in {"failed", "stale"}:
            return "blocked"
        if latest.status in {"queued", "running"}:
            return "planning"
    if validation.get("latest_plan_version_id"):
        return "ready"
    return "planning"


def _cycle_blocker(draft: MissionDraftV1 | None, mission: MissionState | None) -> str | None:
    if mission is not None:
        if mission.caps_hit:
            return "; ".join(str(value) for value in mission.caps_hit.values()) or "Mission cap reached"
        if mission.needs_human():
            return "Human intervention required"
        if mission.is_failed():
            return "Mission has failed tasks"
    if draft is not None:
        repair_state = dict(draft.validation.get("repair") or {})
        issues = list(repair_state.get("issues") or [])
        if issues:
            first = issues[0]
            return str(first.get("reason") or first.get("original_text") or "Draft repair required")
    return None


def _cycle_next_action(draft: MissionDraftV1 | None, mission: MissionState | None, status: str) -> str:
    if mission is not None:
        if status == "blocked":
            return "Inspect evidence and readjust"
        if status == "completed":
            return "Review history"
        return "Open mission"
    if draft is not None and status == "ready":
        return "Launch mission"
    if draft is not None:
        return "Continue planning"
    return "Review project"


def _last_stream_summary(mission: MissionState | None) -> str | None:
    if mission is None or not mission.event_log:
        return None
    latest = mission.event_log[-1]
    details = f": {latest.details}" if latest.details else ""
    return f"{latest.event_type}{details}"


def _artifact_summary(draft: MissionDraftV1 | None, mission: MissionState | None) -> str | None:
    if mission is not None:
        approved = sum(1 for task in mission.task_states.values() if str(task.status) == "review_approved")
        total = len(mission.task_states)
        return f"{approved}/{total} tasks approved"
    if draft is not None:
        task_count = len(list(draft.draft_spec.get("tasks") or []))
        return f"{task_count} planned tasks"
    return None


def _verifier_summary(draft: MissionDraftV1 | None, mission: MissionState | None) -> str | None:
    if mission is not None:
        rejected = [task for task in mission.task_states.values() if str(task.status) == "review_rejected"]
        if rejected:
            return f"{len(rejected)} task reviews rejected"
        if mission.needs_human():
            return "Human intervention pending"
        if mission.is_done():
            return "Mission review path complete"
    if draft is not None and draft.validation.get("latest_plan_version_id"):
        return "Reviewed plan version ready"
    return None


def _contract_summary(draft: MissionDraftV1 | None, mission: MissionState | None) -> str | None:
    if draft is not None:
        if draft.validation.get("latest_plan_version_id"):
            return "Plan draft validated for launch"
        return "Plan draft in progress"
    if mission is not None and mission.source_plan_version_id:
        return f"Mission launched from plan version {mission.source_plan_version_id}"
    return None


def _evidence_status(draft: MissionDraftV1 | None, mission: MissionState | None, blocker: str | None) -> str:
    if blocker:
        return "error"
    if mission is not None and mission.is_done():
        return "ok"
    if draft is not None and draft.validation.get("latest_plan_version_id"):
        return "ok"
    return "pending"


def _telemetry_item(telemetry: TelemetryStore, mission: MissionState | None, updated_at: str) -> ProjectEvidenceItem | None:
    if mission is None:
        return None
    path = telemetry.get_mission_file(mission.mission_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    prompts = list(payload.get("troubleshoot_prompts") or [])
    summary = (
        f"{len(prompts)} troubleshooting prompt(s) recorded"
        if prompts
        else "Telemetry captured for mission"
    )
    return ProjectEvidenceItem(
        kind="telemetry",
        label="Telemetry",
        status="ok",
        summary=summary,
        source_type="telemetry",
        source_id=mission.mission_id,
        updated_at=updated_at,
    )


def _memory_item(memory: Memory, mission: MissionState | None, updated_at: str) -> ProjectEvidenceItem | None:
    if mission is None:
        return None
    path = memory._project_file(mission.mission_id)
    if not path.exists():
        return None
    entries = memory._read_file(path)
    if not entries:
        return None
    return ProjectEvidenceItem(
        kind="memory",
        label="Memory",
        status="ok",
        summary=f"{len(entries)} project memory entr{'y' if len(entries) == 1 else 'ies'} recorded",
        source_type="memory",
        source_id=mission.mission_id,
        updated_at=max((_iso(entry.updated_at) for entry in entries), default=updated_at),
    )


def build_evidence_summary(
    draft: MissionDraftV1 | None,
    mission: MissionState | None,
    blocker: str | None,
    *,
    telemetry: TelemetryStore,
    memory: Memory,
) -> ProjectEvidenceSummary:
    items: list[ProjectEvidenceItem] = []
    contract_summary = _contract_summary(draft, mission)
    verifier_summary = _verifier_summary(draft, mission)
    artifact_summary = _artifact_summary(draft, mission)
    stream_summary = _last_stream_summary(mission)
    status = _evidence_status(draft, mission, blocker)
    updated_at = (
        _iso(mission.finished_at or mission.completed_at or mission.started_at)
        if mission is not None
        else _iso(draft.updated_at.isoformat() if draft is not None else "")
    )

    if contract_summary:
        items.append(ProjectEvidenceItem("contract", "Contract", "ok" if status != "error" else "warning", contract_summary, "draft" if draft else "mission", draft.id if draft else mission.mission_id if mission else None, updated_at))
    if verifier_summary:
        items.append(ProjectEvidenceItem("verifier", "Verifier", "error" if blocker else "ok", verifier_summary, "mission" if mission else "draft", mission.mission_id if mission else draft.id if draft else None, updated_at))
    if artifact_summary:
        items.append(ProjectEvidenceItem("artifact", "Artifacts", "ok" if status != "pending" else "pending", artifact_summary, "mission" if mission else "draft", mission.mission_id if mission else draft.id if draft else None, updated_at))
    if stream_summary:
        items.append(ProjectEvidenceItem("stream", "Latest Event", "ok" if not blocker else "warning", stream_summary, "mission", mission.mission_id if mission else None, updated_at))
    telemetry_item = _telemetry_item(telemetry, mission, updated_at)
    if telemetry_item is not None:
        items.append(telemetry_item)
    memory_item = _memory_item(memory, mission, updated_at)
    if memory_item is not None:
        items.append(memory_item)

    return ProjectEvidenceSummary(
        status=status,
        contract_summary=contract_summary,
        verifier_summary=verifier_summary,
        artifact_summary=artifact_summary,
        stream_summary=stream_summary,
        items=items,
    )


def _project_name(repo_root: str, drafts: list[MissionDraftV1], missions: list[MissionState]) -> str:
    if drafts:
        return drafts[0].name or Path(repo_root).name or "Project"
    if missions:
        return missions[0].spec.name or Path(repo_root).name or "Project"
    return Path(repo_root).name or "Project"


def _normalize_workspace_path(path: str | None) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except Exception:
        return text


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        normalized = _normalize_workspace_path(path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _draft_working_directories(draft: MissionDraftV1) -> list[str]:
    paths = [str(value) for value in list(draft.workspace_paths or [])]
    working_dir = str(draft.draft_spec.get("working_dir") or "").strip()
    if working_dir:
        paths.append(working_dir)
    return _unique_paths(paths)


def _mission_working_directories(mission: MissionState) -> list[str]:
    return _unique_paths([mission.working_dir or "", mission.spec.working_dir or ""])


def _primary_spec_source(
    active_cycle: ProjectCycleView | None,
    drafts_by_id: dict[str, MissionDraftV1],
    missions_by_id: dict[str, MissionState],
    drafts: list[MissionDraftV1],
    missions: list[MissionState],
) -> tuple[MissionDraftV1 | None, MissionState | None]:
    if active_cycle is not None:
        if active_cycle.draft_id and active_cycle.draft_id in drafts_by_id:
            return drafts_by_id[active_cycle.draft_id], None
        if active_cycle.mission_id and active_cycle.mission_id in missions_by_id:
            return None, missions_by_id[active_cycle.mission_id]
    if drafts:
        return drafts[0], None
    if missions:
        return None, missions[0]
    return None, None


def _project_context(
    repo_root: str,
    active_cycle: ProjectCycleView | None,
    drafts: list[MissionDraftV1],
    missions: list[MissionState],
    drafts_by_id: dict[str, MissionDraftV1],
    missions_by_id: dict[str, MissionState],
    record: ProjectRecord | None = None,
) -> dict[str, Any]:
    primary_draft, primary_mission = _primary_spec_source(active_cycle, drafts_by_id, missions_by_id, drafts, missions)
    goal = ""
    definition_of_done: list[str] = []
    task_titles: list[str] = []
    if primary_draft is not None:
        goal = str(primary_draft.draft_spec.get("goal") or "").strip()
        definition_of_done = [str(item).strip() for item in list(primary_draft.draft_spec.get("definition_of_done") or []) if str(item).strip()]
        task_titles = [
            str(task.get("title") or task.get("id") or "").strip()
            for task in list(primary_draft.draft_spec.get("tasks") or [])
            if isinstance(task, dict) and str(task.get("title") or task.get("id") or "").strip()
        ]
    elif primary_mission is not None:
        goal = str(primary_mission.spec.goal or "").strip()
        definition_of_done = [str(item).strip() for item in list(primary_mission.spec.definition_of_done or []) if str(item).strip()]
        task_titles = [str(task.title or task.id).strip() for task in list(primary_mission.spec.tasks or []) if str(task.title or task.id).strip()]

    record_working_directories = list(record.working_directories) if record is not None else []
    working_directories = _unique_paths([
        *record_working_directories,
        *(path for draft in drafts for path in _draft_working_directories(draft)),
        *(path for mission in missions for path in _mission_working_directories(mission)),
    ])
    if not working_directories:
        working_directories = [repo_root]
    primary_working_directory = working_directories[0] if working_directories else repo_root
    return {
        "repo_root": repo_root,
        "primary_working_directory": primary_working_directory,
        "working_directories": working_directories,
        "goal": (record.goal if record is not None and record.goal else goal) or None,
        "definition_of_done": definition_of_done,
        "planned_task_count": len(task_titles),
        "task_titles": task_titles,
        "mission_count": len(missions),
    }


def _find_latest_cycle(cycles: list[ProjectCycleView]) -> ProjectCycleView | None:
    if not cycles:
        return None
    preferred = [cycle for cycle in cycles if cycle.status in {"running", "blocked", "ready", "planning"}]
    pool = preferred or cycles
    return sorted(pool, key=lambda cycle: cycle.updated_at, reverse=True)[0]


def _cycle_from_draft(
    draft: MissionDraftV1,
    mission: MissionState | None,
    runs: list[PlanRunRecord],
    versions: list[PlanVersionRecord],
    *,
    telemetry: TelemetryStore,
    memory: Memory,
) -> ProjectCycleView:
    latest_run = runs[0] if runs else None
    latest_version = versions[0] if versions else None
    status = _mission_cycle_status(mission) if mission is not None else _draft_cycle_status(draft, runs)
    blocker = _cycle_blocker(draft, mission)
    evidence = build_evidence_summary(draft, mission, blocker, telemetry=telemetry, memory=memory)
    mission_updated_at = _iso(mission.finished_at or mission.completed_at or mission.started_at) if mission is not None else ""
    updated_at = max(_iso(draft.updated_at.isoformat()), mission_updated_at)
    return ProjectCycleView(
        cycle_id=draft.id,
        title=draft.name or str(draft.draft_spec.get("name") or "Draft Cycle"),
        status=status,
        draft_id=draft.id,
        mission_id=mission.mission_id if mission is not None else None,
        latest_plan_run_id=latest_run.id if latest_run is not None else str(draft.validation.get("latest_plan_run_id") or "") or None,
        latest_plan_version_id=latest_version.id if latest_version is not None else str(draft.validation.get("latest_plan_version_id") or "") or None,
        predecessor_cycle_id=None,
        successor_cycle_id=None,
        blocker=blocker,
        next_action=_cycle_next_action(draft, mission, status),
        created_at=_iso(draft.created_at.isoformat()),
        updated_at=updated_at,
        evidence=evidence,
    )


def _cycle_from_mission(mission: MissionState, *, telemetry: TelemetryStore, memory: Memory) -> ProjectCycleView:
    status = _mission_cycle_status(mission)
    blocker = _cycle_blocker(None, mission)
    evidence = build_evidence_summary(None, mission, blocker, telemetry=telemetry, memory=memory)
    return ProjectCycleView(
        cycle_id=f"mission:{mission.mission_id}",
        title=mission.spec.name or mission.mission_id,
        status=status,
        draft_id=mission.source_draft_id,
        mission_id=mission.mission_id,
        latest_plan_run_id=mission.source_plan_run_id,
        latest_plan_version_id=mission.source_plan_version_id,
        predecessor_cycle_id=None,
        successor_cycle_id=None,
        blocker=blocker,
        next_action=_cycle_next_action(None, mission, status),
        created_at=_iso(mission.started_at),
        updated_at=_iso(mission.finished_at or mission.completed_at or mission.started_at),
        evidence=evidence,
    )


def _link_readjust_successors(cycles_by_id: dict[str, ProjectCycleView], missions_by_id: dict[str, MissionState], drafts_by_id: dict[str, MissionDraftV1]) -> dict[str, ProjectCycleView]:
    updates: dict[str, dict[str, str | None]] = {}
    for draft in drafts_by_id.values():
        for event in draft.activity_log:
            if not isinstance(event, dict) or event.get("type") != "readjust_trajectory_seeded":
                continue
            mission_id = str(event.get("mission_id") or "").strip()
            if not mission_id:
                continue
            mission = missions_by_id.get(mission_id)
            predecessor_cycle_id = mission.source_draft_id if mission is not None and mission.source_draft_id else f"mission:{mission_id}"
            if predecessor_cycle_id not in cycles_by_id:
                continue
            updates.setdefault(predecessor_cycle_id, {})["successor_cycle_id"] = draft.id
            updates.setdefault(draft.id, {})["predecessor_cycle_id"] = predecessor_cycle_id

    linked: dict[str, ProjectCycleView] = {}
    for cycle_id, cycle in cycles_by_id.items():
        change = updates.get(cycle_id)
        if not change:
            linked[cycle_id] = cycle
            continue
        linked[cycle_id] = ProjectCycleView(
            cycle_id=cycle.cycle_id,
            title=cycle.title,
            status=cycle.status,
            draft_id=cycle.draft_id,
            mission_id=cycle.mission_id,
            latest_plan_run_id=cycle.latest_plan_run_id,
            latest_plan_version_id=cycle.latest_plan_version_id,
            predecessor_cycle_id=change.get("predecessor_cycle_id", cycle.predecessor_cycle_id),
            successor_cycle_id=change.get("successor_cycle_id", cycle.successor_cycle_id),
            blocker=cycle.blocker,
            next_action=cycle.next_action,
            created_at=cycle.created_at,
            updated_at=cycle.updated_at,
            evidence=cycle.evidence,
        )
    return linked


def _draft_mode(draft: MissionDraftV1 | None) -> str:
    validation = dict(draft.validation or {}) if draft is not None else {}
    if validation.get("draft_kind") == "black_hole":
        return "optimize"
    if isinstance(validation.get("black_hole_config"), dict) and validation.get("black_hole_config"):
        return "optimize"
    return "standard"


def _cycle_mode(cycle: ProjectCycleView, drafts_by_id: dict[str, MissionDraftV1]) -> str:
    draft = drafts_by_id.get(str(cycle.draft_id or ""))
    return _draft_mode(draft)


def _build_project_view(
    repo_root: str,
    drafts: list[MissionDraftV1],
    missions: list[MissionState],
    plan_store: PlanRunStore,
    record: ProjectRecord | None = None,
    *,
    telemetry: TelemetryStore,
    memory: Memory,
) -> ProjectHarnessView:
    runs_by_draft = {draft.id: plan_store.list_runs_for_draft(draft.id) for draft in drafts}
    versions_by_draft = {draft.id: plan_store.list_versions_for_draft(draft.id) for draft in drafts}
    mission_by_draft = {
        mission.source_draft_id: mission
        for mission in missions
        if mission.source_draft_id
    }
    cycles_by_id: dict[str, ProjectCycleView] = {}
    drafts_by_id = {draft.id: draft for draft in drafts}
    missions_by_id = {mission.mission_id: mission for mission in missions}

    for draft in drafts:
        cycles_by_id[draft.id] = _cycle_from_draft(
            draft,
            mission_by_draft.get(draft.id),
            runs_by_draft.get(draft.id, []),
            versions_by_draft.get(draft.id, []),
            telemetry=telemetry,
            memory=memory,
        )
    for mission in missions:
        if mission.source_draft_id and mission.source_draft_id in cycles_by_id:
            continue
        cycle = _cycle_from_mission(mission, telemetry=telemetry, memory=memory)
        cycles_by_id[cycle.cycle_id] = cycle

    linked_cycles = _link_readjust_successors(cycles_by_id, missions_by_id, drafts_by_id)
    cycles = sorted(linked_cycles.values(), key=lambda cycle: cycle.updated_at, reverse=True)
    active_cycle = _find_latest_cycle(cycles)
    active_mode = _cycle_mode(active_cycle, drafts_by_id) if active_cycle is not None else "standard"
    context = _project_context(repo_root, active_cycle, drafts, missions, drafts_by_id, missions_by_id, record=record)
    has_activity = bool(cycles)
    archived = record is not None and bool(record.archived_at)
    summary_name = record.name if record is not None and record.name else _project_name(repo_root, drafts, missions)
    effective_status = "archived" if archived else (active_cycle.status if active_cycle is not None else "idle")
    current_stage = (
        "archived"
        if archived else
        "setup" if active_cycle is None else
        "planning" if effective_status == "planning" else
        "ready_to_launch" if effective_status == "ready" else
        "executing" if effective_status == "running" else
        "blocked" if effective_status == "blocked" else
        "completed" if effective_status == "completed" else
        "setup"
    )
    next_action_label = (
        "Unarchive Project"
        if archived
        else "Create Plan"
        if active_cycle is None
        else "Open Mission"
        if active_cycle.mission_id
        else "Continue Planning"
        if active_cycle.draft_id
        else active_cycle.next_action
    )
    summary = ProjectSummaryView(
        project_id=project_id_for_root(repo_root),
        name=summary_name,
        repo_root=repo_root,
        primary_working_directory=context["primary_working_directory"],
        workspace_count=len(context["working_directories"]),
        goal=context["goal"],
        planned_task_count=int(context["planned_task_count"]),
        current_stage=current_stage,
        current_plan_id=active_cycle.draft_id if active_cycle is not None else None,
        current_mission_id=active_cycle.mission_id if active_cycle is not None else None,
        next_action_label=next_action_label,
        mode=active_mode,
        status=effective_status,
        active_cycle_id=active_cycle.cycle_id if active_cycle is not None else None,
        blocker=active_cycle.blocker if active_cycle is not None else None,
        next_action=(
            "Unarchive project"
            if archived
            else active_cycle.next_action if active_cycle is not None
            else "Create project cycle"
        ),
        active_mission_id=active_cycle.mission_id if active_cycle is not None else None,
        archived_at=record.archived_at if record is not None else None,
        has_activity=has_activity,
        updated_at=(
            max(filter(None, [active_cycle.updated_at if active_cycle is not None else "", record.updated_at if record is not None else ""]), default="")
        ),
    )
    evidence = active_cycle.evidence if active_cycle is not None and active_cycle.evidence is not None else ProjectEvidenceSummary(
        status="pending",
        contract_summary=None,
        verifier_summary=None,
        artifact_summary=None,
        stream_summary=None,
        items=[],
    )

    return ProjectHarnessView(
        summary=summary,
        context=context,
        cycles=cycles,
        active_cycle_id=active_cycle.cycle_id if active_cycle is not None else None,
        active_cycle=active_cycle,
        evidence=evidence,
        docs_status={
            "implemented": [
                "docs tree",
                "shared project contract",
                "projects API foundation",
            ],
            "planned": [
                "project cockpit route",
                "evidence drill-downs",
                "optimize mode",
            ],
        },
        policy_summary={
            "mode": active_mode,
            "derived": True,
            "optimize_available": any(_draft_mode(draft) == "optimize" for draft in drafts),
        },
        lifecycle={
            "archived": archived,
            "archived_at": record.archived_at if record is not None else None,
            "can_archive": not archived,
            "can_unarchive": archived,
            "can_delete": archived and not has_activity,
            "can_edit": True,
            "has_activity": has_activity,
        },
    )


def build_project_harness_views(*, include_archived: bool = False) -> list[ProjectHarnessView]:
    draft_store = PlanDraftStore()
    plan_store = PlanRunStore()
    record_store = ProjectRecordStore()
    memory = Memory(state_io.get_agentforce_home() / "memory")
    telemetry = TelemetryStore(state_io.get_agentforce_home() / "telemetry")
    records = record_store.list_all()
    records_by_root = {record.repo_root: record for record in records}

    drafts = [draft for draft in draft_store.list_all(include_terminal=True) if draft.status != "cancelled"]
    missions = state_io._load_all_missions()
    grouped: dict[str, dict[str, list[Any]]] = {}

    for draft in drafts:
        repo_root = _draft_workspace_root(draft)
        if not repo_root:
            continue
        grouped.setdefault(repo_root, {"drafts": [], "missions": []})["drafts"].append(draft)

    for mission in missions:
        repo_root = _mission_workspace_root(mission)
        if not repo_root:
            continue
        grouped.setdefault(repo_root, {"drafts": [], "missions": []})["missions"].append(mission)

    for record in records:
        grouped.setdefault(record.repo_root, {"drafts": [], "missions": []})

    views = [
        _build_project_view(
            repo_root,
            payload["drafts"],
            payload["missions"],
            plan_store,
            record=records_by_root.get(repo_root),
            telemetry=telemetry,
            memory=memory,
        )
        for repo_root, payload in grouped.items()
    ]
    filtered = [view for view in views if include_archived or view.summary.status != "archived"]
    return sorted(filtered, key=lambda view: view.summary.updated_at, reverse=True)


def list_project_summaries(*, include_archived: bool = False) -> list[dict[str, Any]]:
    return [view.summary.to_dict() for view in build_project_harness_views(include_archived=include_archived)]


def get_project_harness(project_id: str) -> ProjectHarnessView | None:
    for view in build_project_harness_views(include_archived=True):
        if view.summary.project_id == project_id:
            return view
    return None


def get_project_harness_for_draft(draft_id: str) -> ProjectHarnessView | None:
    for view in build_project_harness_views(include_archived=True):
        if any(cycle.draft_id == draft_id for cycle in view.cycles):
            return view
    return None


def get_project_harness_for_mission(mission_id: str) -> ProjectHarnessView | None:
    for view in build_project_harness_views(include_archived=True):
        if any(cycle.mission_id == mission_id for cycle in view.cycles):
            return view
    return None
