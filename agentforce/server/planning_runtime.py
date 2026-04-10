"""Planning runtime orchestration for daemon-backed plan runs."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from agentforce.core.spec import MissionSpec
from agentforce.core.token_event import TokenEvent
from agentforce.server import state_io, ws
from agentforce.server.plan_drafts import MissionDraftV1, PlanDraftStore
from agentforce.server.plan_runs import PlanRunRecord, PlanRunStore, PlanStepRecord
from agentforce.server.routes import providers


@dataclass(frozen=True)
class PlanningProfile:
    agent: str
    model: str
    thinking: str


def _default_profile() -> PlanningProfile:
    return PlanningProfile(agent="codex", model="gpt-5.4", thinking="high")


def _now_iso() -> str:
    return providers._now_iso()


def _emit(event_type: str, payload: dict[str, Any]) -> None:
    ws.broadcast({"type": event_type, **payload})


def _plan_store() -> PlanRunStore:
    return PlanRunStore()


def _draft_store() -> PlanDraftStore:
    return PlanDraftStore()


def _normalize_preflight_questions(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw_question in enumerate(payload[:5]):
        if not isinstance(raw_question, dict):
            continue
        prompt = str(raw_question.get("prompt") or raw_question.get("question") or "").strip()
        if not prompt:
            continue
        raw_options = raw_question.get("options") or []
        options = [
            str(option).strip()
            for option in raw_options
            if isinstance(option, str) and str(option).strip()
        ][:5]
        if len(options) < 2:
            continue
        normalized.append(
            {
                "id": str(raw_question.get("id") or f"preflight_{index + 1}"),
                "prompt": prompt,
                "options": options,
                "reason": str(raw_question.get("reason") or "").strip(),
                "allow_custom": bool(raw_question.get("allow_custom", True)),
            }
        )
    return normalized


def discover_preflight_questions(draft: MissionDraftV1) -> list[dict[str, Any]]:
    profile = _resolve_profile(draft, "planner")
    workspaces = ", ".join(draft.workspace_paths) if draft.workspace_paths else "not provided"
    prompt = (
        "You are preparing an AgentForce mission-planning preflight.\n"
        "Return valid JSON only with key 'questions'.\n"
        "Ask zero to five questions only if the answer materially changes task structure, dependencies, execution defaults, "
        "or acceptance criteria. Prefer zero questions when the prompt is already actionable.\n"
        "Each question must be an object with keys: id, prompt, options, reason, allow_custom.\n"
        "Each options array must have 2 to 5 short mutually exclusive choices. allow_custom should usually be true.\n\n"
        f"Goal: {draft.draft_spec.get('goal') or ''}\n"
        f"Workspace paths: {workspaces}\n"
        f"Current draft spec: {json.dumps(draft.draft_spec, indent=2, sort_keys=True)}\n"
    )
    try:
        output, _ = _invoke_profile(profile, prompt, draft.draft_spec.get("working_dir"))
        parsed = json.loads(output)
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    return _normalize_preflight_questions(parsed.get("questions"))


def create_plan_run_for_draft(
    draft: MissionDraftV1,
    *,
    trigger_kind: str,
    trigger_message: str,
) -> PlanRunRecord:
    run = _plan_store().create_run(
        str(uuid.uuid4()),
        draft_id=draft.id,
        base_revision=draft.revision,
        trigger_kind=trigger_kind,
        trigger_message=trigger_message,
    )
    _emit("plan_run_queued", {
        "draft_id": draft.id,
        "plan_run_id": run.id,
        "base_revision": run.base_revision,
        "message": trigger_message,
    })
    return run


def _resolve_profile(draft: MissionDraftV1, key: str) -> PlanningProfile:
    planning_profiles = dict(draft.validation.get("planning_profiles") or {})
    configured = dict(planning_profiles.get(key) or {})
    default = _default_profile()
    return PlanningProfile(
        agent=str(configured.get("agent") or default.agent),
        model=str(configured.get("model") or default.model),
        thinking=str(configured.get("thinking") or default.thinking),
    )


def _invoke_profile(profile: PlanningProfile, prompt: str, workdir: str | None) -> tuple[str, TokenEvent]:
    workdir_value = workdir or str(state_io.get_agentforce_home())
    if profile.agent == "codex":
        from agentforce.connectors import codex
        success, output, error, _, token_event = codex.run(prompt=prompt, workdir=workdir_value, model=profile.model, timeout=180)
    elif profile.agent == "claude":
        from agentforce.connectors import claude
        success, output, error, _, token_event = claude.run(prompt=prompt, workdir=workdir_value, model=profile.model, timeout=180)
    elif profile.agent == "opencode":
        from agentforce.connectors import opencode
        success, output, error, _, token_event = opencode.run(prompt=prompt, workdir=workdir_value, model=profile.model, timeout=180)
    else:
        raise RuntimeError(f"Unsupported planning agent: {profile.agent}")
    if not success:
        raise RuntimeError(error or f"{profile.agent} planning step failed")
    return output, token_event


def _record_step(
    run: PlanRunRecord,
    *,
    name: str,
    status: str,
    message: str = "",
    summary: str = "",
    token_event: TokenEvent | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlanRunRecord:
    existing = [step for step in run.steps if step.name != name]
    current = next((step for step in run.steps if step.name == name), None)
    started_at = current.started_at if current else None
    if status == "started" and not started_at:
        started_at = _now_iso()
    step = PlanStepRecord(
        name=name,
        status=status,
        started_at=started_at or run.started_at,
        completed_at=_now_iso() if status in {"completed", "failed", "stale"} else None,
        message=message,
        summary=summary,
        tokens_in=token_event.tokens_in if token_event else 0,
        tokens_out=token_event.tokens_out if token_event else 0,
        cost_usd=token_event.cost_usd if token_event else 0.0,
        metadata=metadata or {},
    )
    updated_steps = existing + [step]
    updated = run.copy_with(
        current_step=name,
        steps=updated_steps,
        tokens_in=run.tokens_in + step.tokens_in,
        tokens_out=run.tokens_out + step.tokens_out,
        cost_usd=round(run.cost_usd + step.cost_usd, 6),
    )
    _plan_store().save_run(updated)
    _emit(
        "plan_step_completed" if status != "started" else "plan_step_started",
        {
            "draft_id": updated.draft_id,
            "plan_run_id": updated.id,
            "step": name,
            "status": status,
            "message": message,
            "summary": summary,
            "tokens_in": updated.tokens_in,
            "tokens_out": updated.tokens_out,
            "cost_usd": updated.cost_usd,
        },
    )
    _emit(
        "plan_cost_update",
        {
            "draft_id": updated.draft_id,
            "plan_run_id": updated.id,
            "tokens_in": updated.tokens_in,
            "tokens_out": updated.tokens_out,
            "cost_usd": updated.cost_usd,
        },
    )
    return updated


def _mission_plan_validation(spec_dict: dict[str, Any]) -> dict[str, Any]:
    mission_spec = MissionSpec.from_dict(spec_dict)
    issues = mission_spec.validate(stage="draft")
    warnings: list[str] = []
    if len(mission_spec.tasks) > 7:
        warnings.append("Task count exceeds mission-plan guidance of 7 tasks.")
    return {"issues": issues, "warnings": warnings}


def _critic_prompt(name: str, goal: str, spec_dict: dict[str, Any]) -> str:
    return (
        f"You are the {name} critic for an AgentForce mission plan.\n"
        "Return valid JSON only with keys 'summary', 'issues', and 'suggestions'.\n"
        "Each issue must be an object with 'severity', 'title', and 'fix'.\n\n"
        f"Goal:\n{goal}\n\n"
        f"Current draft_spec JSON:\n{json.dumps(spec_dict, indent=2, sort_keys=True)}\n"
    )


def _parse_critic_output(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"summary": text.strip(), "issues": [], "suggestions": []}
    if not isinstance(payload, dict):
        return {"summary": text.strip(), "issues": [], "suggestions": []}
    return {
        "summary": str(payload.get("summary") or ""),
        "issues": list(payload.get("issues") or []),
        "suggestions": list(payload.get("suggestions") or []),
    }


def _resolver_changelog(validation: dict[str, Any], technical: dict[str, Any], practical: dict[str, Any]) -> list[str]:
    changelog: list[str] = []
    if validation.get("issues"):
        changelog.append(f"Mission-plan checks flagged {len(validation['issues'])} advisory issue(s).")
    if technical.get("issues"):
        changelog.append(f"Technical adversary flagged {len(technical['issues'])} issue(s).")
    if practical.get("issues"):
        changelog.append(f"Practical adversary flagged {len(practical['issues'])} issue(s).")
    if not changelog:
        changelog.append("Initial planning pass completed without critic findings.")
    return changelog


def run_plan_run(run_id: str) -> None:
    store = _plan_store()
    run = store.load_run(run_id)
    if run is None:
        raise RuntimeError(f"Plan run {run_id!r} not found")

    draft = _draft_store().load(run.draft_id)
    if draft is None:
        raise RuntimeError(f"Draft {run.draft_id!r} not found")

    started = run.copy_with(status="running", started_at=run.created_at)
    store.save_run(started)
    _emit("plan_run_started", {"draft_id": started.draft_id, "plan_run_id": started.id, "base_revision": started.base_revision})
    run = started

    synthesis_profile = _resolve_profile(draft, "planner")
    critic_technical_profile = _resolve_profile(draft, "critic_technical")
    critic_practical_profile = _resolve_profile(draft, "critic_practical")

    from agentforce.server import planner_adapter

    run = _record_step(run, name="planner_synthesis", status="started", message="Generating initial plan")
    adapter = planner_adapter.get_planner_adapter()
    turn = adapter.plan_turn(draft.to_dict(), run.trigger_message or draft.draft_spec.get("goal") or "")
    spec_dict = turn.draft_spec
    run = _record_step(
        run,
        name="planner_synthesis",
        status="completed",
        message=turn.assistant_message,
        summary=turn.assistant_message,
        metadata={"profile": synthesis_profile.__dict__},
    )

    run = _record_step(run, name="mission_plan_pass", status="started", message="Applying mission-plan checks")
    validation = _mission_plan_validation(spec_dict)
    run = _record_step(
        run,
        name="mission_plan_pass",
        status="completed",
        message="Mission-plan checks complete",
        summary="; ".join(validation.get("issues") or validation.get("warnings") or ["No issues"]),
        metadata=validation,
    )

    run = _record_step(run, name="technical_critic", status="started", message="Running technical adversary review")
    technical_text, technical_usage = _invoke_profile(
        critic_technical_profile,
        _critic_prompt("technical", draft.draft_spec.get("goal") or "", spec_dict),
        draft.draft_spec.get("working_dir"),
    )
    technical = _parse_critic_output(technical_text)
    run = _record_step(
        run,
        name="technical_critic",
        status="completed",
        message="Technical adversary review complete",
        summary=technical.get("summary") or "Technical review stored",
        token_event=technical_usage,
        metadata=technical,
    )

    run = _record_step(run, name="practical_critic", status="started", message="Running practical adversary review")
    practical_text, practical_usage = _invoke_profile(
        critic_practical_profile,
        _critic_prompt("practical", draft.draft_spec.get("goal") or "", spec_dict),
        draft.draft_spec.get("working_dir"),
    )
    practical = _parse_critic_output(practical_text)
    run = _record_step(
        run,
        name="practical_critic",
        status="completed",
        message="Practical adversary review complete",
        summary=practical.get("summary") or "Practical review stored",
        token_event=practical_usage,
        metadata=practical,
    )

    run = _record_step(run, name="resolver", status="started", message="Resolving critic findings")
    changelog = _resolver_changelog(validation, technical, practical)
    version = store.create_version(
        str(uuid.uuid4()),
        draft_id=draft.id,
        source_run_id=run.id,
        revision_base=draft.revision,
        draft_spec_snapshot=spec_dict,
        changelog=changelog,
        validation={
            "mission_plan": validation,
            "technical": technical,
            "practical": practical,
        },
    )
    run = _record_step(
        run,
        name="resolver",
        status="completed",
        message="Reviewed version created",
        summary=" ".join(changelog),
        metadata={"version_id": version.id},
    )
    _emit(
        "plan_version_created",
        {
            "draft_id": draft.id,
            "plan_run_id": run.id,
            "plan_version_id": version.id,
            "changelog": changelog,
        },
    )

    latest_draft = _draft_store().load(draft.id)
    if latest_draft is None:
        raise RuntimeError(f"Draft {draft.id!r} disappeared during planning")
    if latest_draft.revision != run.base_revision:
        stale = run.copy_with(
            status="stale",
            stale=True,
            completed_at=run.created_at,
            result_version_id=version.id,
            changelog=changelog,
        )
        store.save_run(stale)
        _emit("plan_run_stale", {"draft_id": draft.id, "plan_run_id": stale.id, "plan_version_id": version.id})
        return

    promoted = latest_draft.copy_with(
        draft_spec=spec_dict,
        turns=list(latest_draft.turns) + [{"role": "assistant", "content": turn.assistant_message}],
        validation={
            **latest_draft.validation,
            "latest_plan_run_id": run.id,
            "latest_plan_version_id": version.id,
            "plan_validation": version.validation,
            "plan_changelog": changelog,
            "planning_profiles": {
                "planner": synthesis_profile.__dict__,
                "critic_technical": critic_technical_profile.__dict__,
                "critic_practical": critic_practical_profile.__dict__,
                "resolver": synthesis_profile.__dict__,
            },
        },
        activity_log=list(latest_draft.activity_log) + [{
            "type": "plan_head_promoted",
            "plan_run_id": run.id,
            "plan_version_id": version.id,
        }],
    )
    save_result = _draft_store().save(promoted, expected_revision=latest_draft.revision)
    if save_result.status != "saved" or save_result.draft is None:
        stale = run.copy_with(
            status="stale",
            stale=True,
            completed_at=run.created_at,
            result_version_id=version.id,
            changelog=changelog,
        )
        store.save_run(stale)
        _emit("plan_run_stale", {"draft_id": draft.id, "plan_run_id": stale.id, "plan_version_id": version.id})
        return

    completed = run.copy_with(
        status="completed",
        completed_at=save_result.draft.activity_log[-1].get("timestamp") if save_result.draft.activity_log and isinstance(save_result.draft.activity_log[-1], dict) else run.created_at,
        result_version_id=version.id,
        promoted_version_id=version.id,
        head_revision_seen=save_result.draft.revision,
        changelog=changelog,
    )
    store.save_run(completed)
    _emit(
        "plan_head_promoted",
        {
            "draft_id": draft.id,
            "plan_run_id": completed.id,
            "plan_version_id": version.id,
            "revision": save_result.draft.revision,
        },
    )


def mark_version_launched(version_id: str, mission_id: str) -> None:
    store = _plan_store()
    version = store.load_version(version_id)
    if version is None:
        return
    store.save_version(version.copy_with(launched_mission_id=mission_id))
    run = store.load_run(version.source_run_id)
    if run is not None:
        store.save_run(run.copy_with(launched_mission_id=mission_id))
