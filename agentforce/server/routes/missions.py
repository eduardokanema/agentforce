"""Mission API routes."""
from __future__ import annotations

import json as _jsonlib
import threading
import time as _time
import uuid
from pathlib import Path

import yaml

from agentforce.core.engine import MissionEngine
from agentforce.core.spec import ExecutionProfile, TaskSpec
from agentforce.memory import Memory
from agentforce.telemetry import TelemetryStore

from .. import state_io, ws
from .. import model_catalog
from ..plan_drafts import PlanDraftStore
from ..plan_runs import PlanRunStore


def _now_iso() -> str:
    from .providers import _now_iso as _provider_now_iso

    return _provider_now_iso()


def _make_mission_state_from_spec(spec):
    from agentforce.core.state import MissionState, TaskState

    mission_id = spec.short_id()
    state = MissionState(mission_id=mission_id, spec=spec)
    state.execution_defaults = spec.execution_defaults.__class__.from_dict(spec.execution_defaults.to_dict())
    state.working_dir = str(Path(spec.working_dir or f"./missions-{mission_id}").resolve())
    for task_spec in spec.tasks:
        state.task_states[task_spec.id] = TaskState(
            task_id=task_spec.id,
            spec_summary=f"{task_spec.title}"[:200],
        )
    return state


def _load_mission_flags() -> dict[str, dict]:
    return state_io._load_mission_flags()


def _save_mission_flags(flags: dict[str, dict]) -> None:
    state_io._save_mission_flags(flags)


def _broadcast_mission_list_refresh() -> None:
    state_io._broadcast_mission_list_refresh()


def _broadcast_mission_refresh(state) -> None:
    state_io._broadcast_mission_refresh(state)


def _load_state(mission_id: str):
    return state_io._load_state(mission_id)


def _state_path(mission_id: str) -> Path:
    return state_io._state_path(mission_id)


def _load_engine(mission_id: str) -> MissionEngine | None:
    state_path = _state_path(mission_id)
    if not state_path.exists():
        return None
    return MissionEngine.load(state_path, Memory(state_io.get_agentforce_home() / "memory"))


def _enqueue_mission(mission_id: str) -> None:
    from agentforce.server import handler as _handler

    active_daemon = getattr(_handler, "_daemon", None)
    if active_daemon is not None:
        active_daemon.enqueue(mission_id)


def _draft_troubleshooting_task(engine: MissionEngine, prompt: str) -> TaskSpec:
    clean_prompt = prompt.strip()
    snippet = " ".join(clean_prompt.split())[:80]
    completed_tasks = [
        task.id
        for task in engine.spec.tasks
        if getattr(engine.state.get_task(task.id), "status", None) == "review_approved"
    ]
    dependencies = completed_tasks[-1:] if completed_tasks else []
    task_id = f"troubleshoot_{uuid.uuid4().hex[:8]}"
    return TaskSpec(
        id=task_id,
        title=f"Troubleshooting: {snippet or 'follow-up'}",
        description=(
            "Investigate and resolve the operator-reported follow-up issue after the mission "
            f"completed.\n\nTroubleshooting prompt:\n{clean_prompt}"
        ),
        acceptance_criteria=[
            "Investigate the reported issue using the current mission context.",
            "Implement or document the required follow-up changes.",
            "Summarize the troubleshooting outcome and any remaining risks.",
        ],
        dependencies=dependencies,
        working_dir=engine.spec.working_dir,
    )


def _archive_mission(mission_id: str) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    flags = _load_mission_flags()
    flags[state.mission_id] = {**flags.get(state.mission_id, {}), "archived": True, "archived_at": _now_iso()}
    flags[state.mission_id].pop("deleted", None)
    _save_mission_flags(flags)
    _broadcast_mission_list_refresh()
    return 200, {"archived": True}


def _unarchive_mission(mission_id: str) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    flags = _load_mission_flags()
    entry = flags.get(state.mission_id, {})
    entry.pop("archived", None)
    entry.pop("archived_at", None)
    if entry:
        flags[state.mission_id] = entry
    else:
        flags.pop(state.mission_id, None)
    _save_mission_flags(flags)
    _broadcast_mission_list_refresh()
    return 200, {"unarchived": True}


def _soft_delete_mission(mission_id: str) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    flags = _load_mission_flags()
    flags[state.mission_id] = {**flags.get(state.mission_id, {}), "deleted": True, "deleted_at": _now_iso()}
    _save_mission_flags(flags)
    _broadcast_mission_list_refresh()
    return 200, {"deleted": True}


def _post_mission_stop(mission_id: str) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    changed = False
    for task_state in state.task_states.values():
        if state_io._task_status_value(task_state) == "in_progress":
            task_state.status = "blocked"
            changed = True
    if changed:
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
    return 200, {"stopped": True}


def _post_mission_restart(mission_id: str) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    requeued = 0
    restartable = {
        "failed",
        "blocked",
        "review_rejected",
        "in_progress",
        "reviewing",
        "retry",
        "needs_human",
        "spec_writing",
        "tests_written",
    }
    for task_state in state.task_states.values():
        if state_io._task_status_value(task_state) in restartable:
            task_state.status = "retry"
            task_state.retries = 0  # Reset individual task budget
            task_state.retry_not_before = 0.0
            task_state.human_intervention_needed = False
            task_state.human_intervention_message = ""
            task_state.human_intervention_kind = ""
            task_state.human_intervention_options = []
            task_state.human_intervention_context = {}
            task_state.bump()
            requeued += 1
    state.active_wall_time_seconds = 0.0
    state.reset_active_tick_clock()
    state.total_retries = 0  # Reset global mission retry budget
    state.total_human_interventions = 0 # Reset global mission intervention budget
    state.caps_hit = {}
    state.completed_at = None
    state.finished_at = None
    state.log_event("mission_restarted", details=f"Restarted mission; requeued {requeued} active task(s)")
    state.save(_state_path(mission_id))
    _broadcast_mission_refresh(state)
    _broadcast_mission_list_refresh()
    _enqueue_mission(mission_id)

    return 200, {"requeued": requeued}


def _post_mission_troubleshoot(mission_id: str, body: dict) -> tuple[int, dict]:
    engine = _load_engine(mission_id)
    if not engine:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    if engine.state.finished_at:
        return 409, {"error": "Mission already finished"}
    if not engine.state.is_done():
        return 409, {"error": "Mission is not complete"}

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return 400, {"error": "prompt is required"}

    task_spec = _draft_troubleshooting_task(engine, prompt)
    engine.append_task(task_spec)
    engine.state.completed_at = None
    engine.state.log_event("mission_troubleshoot_requested", task_spec.id, prompt.strip())
    engine._save()
    TelemetryStore(state_io.get_agentforce_home() / "telemetry").record_troubleshooting(mission_id, prompt.strip())

    _broadcast_mission_refresh(engine.state)
    _broadcast_mission_list_refresh()
    _enqueue_mission(mission_id)

    return 200, {"task_id": task_spec.id, "status": "active"}


def _post_mission_finish(mission_id: str) -> tuple[int, dict]:
    engine = _load_engine(mission_id)
    if not engine:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    if not engine.state.is_done():
        return 409, {"error": "Mission is not complete"}

    engine.finish_mission()
    _broadcast_mission_refresh(engine.state)
    _broadcast_mission_list_refresh()
    return 200, {"finished": True}


def _post_mission_default_models(mission_id: str, body: dict) -> tuple[int, dict]:
    engine = _load_engine(mission_id)
    if not engine:
        return 404, {"error": f"Mission {mission_id!r} not found"}

    try:
        worker_profile = _normalized_role_profile(body.get("worker_profile"), role="worker")
        reviewer_profile = _normalized_role_profile(body.get("reviewer_profile"), role="reviewer")
        if worker_profile is None:
            worker_profile = _normalized_legacy_role_profile(body, role="worker")
        if reviewer_profile is None:
            reviewer_profile = _normalized_legacy_role_profile(body, role="reviewer")
        result = engine.change_default_models(
            worker_model=worker_profile.model if worker_profile else None,
            reviewer_model=reviewer_profile.model if reviewer_profile else None,
            worker_agent=worker_profile.agent if worker_profile else None,
            reviewer_agent=reviewer_profile.agent if reviewer_profile else None,
            worker_thinking=worker_profile.thinking if worker_profile else None,
            reviewer_thinking=reviewer_profile.thinking if reviewer_profile else None,
        )
    except ValueError as exc:
        return 400, {"error": str(exc)}

    _broadcast_mission_refresh(engine.state)
    _broadcast_mission_list_refresh()
    return 200, result


def _post_mission_review(mission_id: str, body: dict) -> tuple[int, dict]:
    from agentforce.review.config import is_review_enabled

    if not is_review_enabled():
        return 403, {"error": "Review disabled globally"}

    home = state_io.get_agentforce_home()
    review_file = home / "reviews" / f"{mission_id}_review.json"
    if review_file.exists():
        age_s = _time.time() - review_file.stat().st_mtime
        if age_s < 300:
            return 429, {"error": f"Review too recent ({age_s:.0f}s ago). Wait 5 minutes."}

    if body.get("skip"):
        skip_file = home / "reviews" / f"{mission_id}_skipped"
        skip_file.parent.mkdir(parents=True, exist_ok=True)
        skip_file.touch()
        return 200, {"skipped": True}

    sf = state_io._state_path(mission_id)
    if not sf.exists():
        return 404, {"error": f"Mission {mission_id!r} not found"}

    from agentforce.memory.memory import Memory
    from agentforce.review.reviewer import MissionReviewer

    memory = Memory(state_io.get_agentforce_home() / "memory")
    reviewer = MissionReviewer(memory=memory)
    model = body.get("model") or None
    try:
        report = reviewer.review(mission_id, model=model)
        return 200, report.to_dict()
    except Exception as exc:
        return 500, {"error": str(exc)}


def _post_missions(body: dict) -> tuple[int, dict]:
    yaml_text = body.get("yaml")
    if not isinstance(yaml_text, str) or not yaml_text.strip():
        return 400, {"error": "yaml is required"}
    try:
        from agentforce.core.spec import MissionSpec

        spec = MissionSpec.from_dict(yaml.safe_load(yaml_text))
    except Exception as exc:
        return 400, {"error": f"invalid mission yaml: {str(exc)}"}

    state = _make_mission_state_from_spec(spec)
    state.log_event("mission_started", details="Started via API")
    _state_path(state.mission_id).parent.mkdir(parents=True, exist_ok=True)
    state.save(_state_path(state.mission_id))
    _broadcast_mission_refresh(state)

    # Late import avoids circular dependency (handler imports missions at module level).
    from agentforce.server import handler as _handler
    active_daemon = getattr(_handler, "_daemon", None)

    if active_daemon is not None:
        active_daemon.enqueue(state.mission_id)
        return 200, {"id": state.mission_id, "status": "started"}

    def _runner():
        try:
            from agentforce.autonomous import run_autonomous

            run_autonomous(state.mission_id)
        except SystemExit:
            pass
        except Exception:
            pass

    threading.Thread(target=_runner, daemon=True, name=f"agentforce-mission-{state.mission_id}").start()
    return 200, {"id": state.mission_id, "status": "started"}


def _post_readjust_trajectory(mission_id: str) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}

    draft = PlanDraftStore().create(
        str(uuid.uuid4()),
        status="draft",
        draft_spec=state.spec.to_dict(),
        turns=[],
        validation={
            "planning_profiles": {
                "planner": _planning_profile_payload(state.execution_defaults.worker),
                "critic_technical": _planning_profile_payload(state.execution_defaults.reviewer),
                "critic_practical": _planning_profile_payload(state.execution_defaults.reviewer),
                "resolver": _planning_profile_payload(state.execution_defaults.worker),
            },
        },
        activity_log=[{"type": "readjust_trajectory_seeded", "mission_id": mission_id}],
        approved_models=[],
        workspace_paths=[path for path in [state.working_dir or state.spec.working_dir] if path],
        companion_profile={},
        draft_notes=[],
    )
    return 200, {"id": draft.id, "revision": draft.revision}


def _normalized_role_profile(value: object, *, role: str) -> ExecutionProfile | None:
    if isinstance(value, dict):
        normalized = model_catalog.normalize_profile_dict(value)
        if not normalized.valid:
            raise ValueError(f"{role}_profile is not selectable: {normalized.reason}")
        return normalized.profile
    return None


def _normalized_legacy_role_profile(body: dict, *, role: str) -> ExecutionProfile | None:
    legacy = ExecutionProfile(
        agent=body.get(f"{role}_agent") if isinstance(body.get(f"{role}_agent"), str) else None,
        model=body.get(f"{role}_model") if isinstance(body.get(f"{role}_model"), str) else None,
        thinking=body.get(f"{role}_thinking") if isinstance(body.get(f"{role}_thinking"), str) else None,
    )
    if not legacy.configured():
        return None
    normalized = model_catalog.normalize_execution_profile(legacy)
    if not normalized.valid:
        raise ValueError(f"{role}_profile is not selectable: {normalized.reason}")
    return normalized.profile


def _planning_profile_payload(profile: ExecutionProfile | None) -> dict[str, str]:
    normalized = model_catalog.normalize_execution_profile(profile)
    effective = normalized.profile if normalized.valid else profile
    if not effective or not effective.configured():
        return {}
    return {
        "agent": str(effective.agent or ""),
        "model": str(effective.model or ""),
        "thinking": str(effective.thinking or "medium"),
    }


def get(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 2 and parts[1] == "missions":
        missions = state_io._load_all_missions()
        return 200, [mission.to_summary_dict() for mission in missions]

    if len(parts) == 3 and parts[1] == "mission":
        state = _load_state(parts[2])
        if not state:
            return 404, {"error": f"Mission {parts[2]!r} not found"}
        payload = state.to_dict()
        planning_summary = PlanRunStore().summarize_for_mission(state.mission_id)
        if planning_summary is not None:
            payload["planning"] = planning_summary
        return 200, payload

    if len(parts) == 5 and parts[1] == "mission" and parts[3] == "task":
        state = _load_state(parts[2])
        if not state:
            return 404, {"error": f"Mission {parts[2]!r} not found"}
        task_state = state.task_states.get(parts[4])
        if not task_state:
            return 404, {"error": f"Task {parts[4]!r} not found in mission {parts[2]!r}"}
        task_spec = next((task for task in state.spec.tasks if task.id == parts[4]), None)
        payload = task_state.to_dict()
        if task_spec:
            payload.update(task_spec.to_dict())
        return 200, payload

    if len(parts) == 4 and parts[0] == "api" and parts[1] == "mission" and parts[3] == "review":
        mission_id = parts[2]
        home = state_io.get_agentforce_home()
        review_file = home / "reviews" / f"{mission_id}_review.json"
        skip_file = home / "reviews" / f"{mission_id}_skipped"
        if skip_file.exists():
            return 200, {"skipped": True, "mission_id": mission_id}
        if not review_file.exists():
            return 404, {"error": "No review found. POST to /api/mission/{id}/review to generate."}
        return 200, _jsonlib.loads(review_file.read_text())

    if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task" and parts[5] == "output":
        mission_id, task_id = parts[2], parts[4]
        stream_file = state_io.get_agentforce_home() / "streams" / f"{mission_id}_{task_id}.log"
        if not stream_file.exists():
            return 200, {"lines": []}
        try:
            content = stream_file.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
        except OSError:
            lines = []
        return 200, {"lines": lines}

    if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task" and parts[5] == "attempts":
        state = _load_state(parts[2])
        if not state:
            return 404, {"error": f"Mission {parts[2]!r} not found"}
        task_state = state.task_states.get(parts[4])
        if not task_state:
            return 404, {"error": f"Task {parts[4]!r} not found in mission {parts[2]!r}"}
        history = getattr(task_state, "attempt_history", None) or getattr(task_state, "attempts", None)
        if not history:
            return 200, [{
                "attempt_number": 1,
                "output": task_state.worker_output,
                "review": task_state.review_feedback or None,
                "score": task_state.review_score,
                "tokens_in": task_state.tokens_in,
                "tokens_out": task_state.tokens_out,
                "cost_usd": task_state.cost_usd,
            }]
        records = []
        for idx, attempt in enumerate(history, start=1):
            if isinstance(attempt, dict):
                records.append({
                    "attempt_number": attempt.get("attempt_number", attempt.get("attempt", idx)),
                    "output": attempt.get("output", ""),
                    "review": attempt.get("review"),
                    "score": attempt.get("score"),
                    "tokens_in": attempt.get("tokens_in"),
                    "tokens_out": attempt.get("tokens_out"),
                    "cost_usd": attempt.get("cost_usd"),
                })
            else:
                records.append({
                    "attempt_number": idx,
                    "output": str(attempt),
                    "review": None,
                    "score": None,
                    "tokens_in": None,
                    "tokens_out": None,
                    "cost_usd": None,
                })
        return 200, records

    return 404, {"error": "Not found"}


def post(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 2 and parts[1] == "missions":
        return _post_missions(handler._read_json_body())

    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "stop":
        return _post_mission_stop(parts[2])
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "restart":
        return _post_mission_restart(parts[2])
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "default_models":
        return _post_mission_default_models(parts[2], handler._read_json_body())
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "archive":
        return _archive_mission(parts[2])
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "unarchive":
        return _unarchive_mission(parts[2])
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "review":
        return _post_mission_review(parts[2], handler._read_json_body())
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "readjust-trajectory":
        return _post_readjust_trajectory(parts[2])
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "troubleshoot":
        return _post_mission_troubleshoot(parts[2], handler._read_json_body())
    if len(parts) == 4 and parts[1] == "mission" and parts[3] == "finish":
        return _post_mission_finish(parts[2])

    return 404, {"error": "Not found"}


def delete(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 3 and parts[1] == "mission":
        return _soft_delete_mission(parts[2])
    return 404, {"error": "Not found"}
