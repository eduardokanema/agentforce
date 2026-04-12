"""Planning runtime orchestration for daemon-backed plan runs."""
from __future__ import annotations

import json
import hashlib
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentforce.core.spec import MissionSpec
from agentforce.core.token_event import TokenEvent
from agentforce.server.black_hole_analyzers import evaluate_black_hole_analyzer, normalized_progress_delta
from agentforce.server.black_hole_runs import (
    BlackHoleCampaignRecord,
    BlackHoleCampaignStore,
    BlackHoleLoopRecord,
    is_terminal_campaign_status,
)
from agentforce.server import state_io, ws
from agentforce.server import model_catalog
from agentforce.server.plan_drafts import MissionDraftV1, PlanDraftStore
from agentforce.server.plan_runs import PlanRunRecord, PlanRunStore, PlanStepRecord
from agentforce.server.routes import providers


@dataclass(frozen=True)
class PlanningProfile:
    agent: str
    model: str
    thinking: str


def _available_models_for_agent(agent: str) -> list[str]:
    return model_catalog.available_models_for_provider(agent)


def _fallback_model_for_agent(agent: str) -> str:
    available = _available_models_for_agent(agent)
    return available[0] if available else ""


def _default_profile() -> PlanningProfile:
    from agentforce.connectors import claude
    if claude.available():
        return PlanningProfile(
            agent="claude",
            model=_fallback_model_for_agent("claude") or "claude-sonnet-4-6",
            thinking="high",
        )
    return PlanningProfile(
        agent="codex",
        model=_fallback_model_for_agent("codex"),
        thinking="high",
    )


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
    agent = str(configured.get("agent") or default.agent)
    configured_model = str(configured.get("model") or "").strip()
    model = configured_model or default.model
    normalized = model_catalog.normalize_execution_profile(
        model_catalog.parse_profile_id(model_catalog.profile_id(agent, model, str(configured.get("thinking") or default.thinking)))
    )
    if normalized.valid:
        agent = str(normalized.profile.agent or agent)
        model = str(normalized.profile.model or model)
        thinking = str(normalized.profile.thinking or configured.get("thinking") or default.thinking)
    else:
        thinking = str(configured.get("thinking") or default.thinking)
    return PlanningProfile(
        agent=agent,
        model=model,
        thinking=thinking,
    )


def _should_retry_without_model(agent: str, output: str, error: str) -> bool:
    if agent != "codex":
        return False
    text = f"{error}\n{output}".lower()
    return (
        "selected model" in text
        and ("may not exist" in text or "may not have access" in text or "pick a different model" in text)
    )


def _invoke_profile(profile: PlanningProfile, prompt: str, workdir: str | None) -> tuple[str, TokenEvent]:
    workdir_value = workdir or str(state_io.get_agentforce_home())
    if profile.agent == "codex":
        from agentforce.connectors import codex
        success, output, error, _, token_event = codex.run(prompt=prompt, workdir=workdir_value, model=profile.model, timeout=180, variant=profile.thinking)
        if not success and profile.model and _should_retry_without_model(profile.agent, output, error):
            success, output, error, _, token_event = codex.run(
                prompt=prompt,
                workdir=workdir_value,
                model=None,
                timeout=180,
                variant=profile.thinking,
            )
    elif profile.agent == "claude":
        from agentforce.connectors import claude
        success, output, error, _, token_event = claude.run(prompt=prompt, workdir=workdir_value, model=profile.model, timeout=180, variant=profile.thinking)
    elif profile.agent == "opencode":
        from agentforce.connectors import opencode
        success, output, error, _, token_event = opencode.run(prompt=prompt, workdir=workdir_value, model=profile.model, timeout=180, variant=profile.thinking)
    elif profile.agent == "gemini":
        from agentforce.connectors import gemini
        success, output, error, _, token_event = gemini.run(prompt=prompt, workdir=workdir_value, model=profile.model, timeout=180, variant=profile.thinking)
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


def _sum_token_events(*events: TokenEvent | None) -> TokenEvent:
    return TokenEvent(
        sum(event.tokens_in for event in events if event is not None),
        sum(event.tokens_out for event in events if event is not None),
        round(sum(event.cost_usd for event in events if event is not None), 6),
    )


def _stable_issue_id(*parts: str) -> str:
    normalized = "|".join(part.strip() for part in parts)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]


def _build_structured_validation_issues(spec_dict: dict[str, Any]) -> list[dict[str, Any]]:
    mission_spec = MissionSpec.from_dict(spec_dict)
    issues: list[dict[str, Any]] = []

    for raw_issue in mission_spec.validate(stage="draft"):
        issue_text = str(raw_issue).strip()
        if not issue_text:
            continue
        issues.append(
            {
                "issue_id": _stable_issue_id("draft_validation", issue_text),
                "source": "validate",
                "blocking": True,
                "kind": "draft_validation",
                "task_id": None,
                "original_text": issue_text,
                "reason": issue_text,
            }
        )

    quality = mission_spec.validate_quality()
    for item in quality.dod_errors:
        text = str(item).strip()
        issues.append(
            {
                "issue_id": _stable_issue_id("dod_vague", text),
                "source": "validate_quality",
                "blocking": True,
                "kind": "dod_vague",
                "task_id": None,
                "original_text": text,
                "reason": "Definition of Done item is too vague",
            }
        )
    for item in quality.criteria_errors:
        criterion = str(item.criterion or "").strip()
        task_id = str(item.task_id or "").strip() or None
        issues.append(
            {
                "issue_id": _stable_issue_id("criterion_vague", task_id or "", criterion),
                "source": "validate_quality",
                "blocking": True,
                "kind": "criterion_vague",
                "task_id": task_id,
                "original_text": criterion,
                "reason": str(item.reason or "Criterion is too vague"),
            }
        )
    return issues


def _issue_summary(issue: dict[str, Any]) -> str:
    kind = str(issue.get("kind") or "")
    original = str(issue.get("original_text") or "").strip()
    task_id = str(issue.get("task_id") or "").strip()
    if kind == "dod_vague":
        return f"Definition of Done item is too vague: {original}"
    if kind == "criterion_vague" and task_id:
        return f"Task {task_id} acceptance criteria item is too vague: {original}"
    if kind == "criterion_vague":
        return f"Acceptance criteria item is too vague: {original}"
    return str(issue.get("reason") or original or "Validation issue")


def _blank_repair_state() -> dict[str, Any]:
    return {
        "status": "not_needed",
        "repair_round": 0,
        "max_rounds": 2,
        "issues": [],
        "questions": [],
        "answers": {},
        "gate_reason": "",
    }


def _repair_state_from_validation(validation: dict[str, Any]) -> dict[str, Any]:
    raw = validation.get("repair") if isinstance(validation, dict) else None
    if not isinstance(raw, dict):
        return _blank_repair_state()
    state = _blank_repair_state()
    state.update(raw)
    state["issues"] = list(raw.get("issues") or [])
    state["questions"] = list(raw.get("questions") or [])
    state["answers"] = dict(raw.get("answers") or {})
    return state


def _with_updated_repair_state(validation: dict[str, Any], repair: dict[str, Any] | None) -> dict[str, Any]:
    updated = dict(validation or {})
    if repair is None:
        updated.pop("repair", None)
        return updated
    updated["repair"] = repair
    return updated


def _pending_repair_state(
    *,
    run: PlanRunRecord,
    version_id: str,
    issues: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    gate_reason: str,
    repair_round: int,
    max_rounds: int = 2,
    mode: str = "plan",
    loop_no: int | None = None,
    candidate: dict[str, Any] | None = None,
    analyzer_result: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": "pending",
        "mode": mode,
        "source_run_id": run.id,
        "source_version_id": version_id,
        "repair_round": repair_round,
        "max_rounds": max_rounds,
        "issues": issues,
        "questions": questions,
        "answers": {},
        "gate_reason": gate_reason,
        "loop_no": loop_no,
        "candidate": candidate or {},
        "analyzer_result": analyzer_result or {},
        "config_snapshot": config or {},
    }


def _answered_repair_state(state: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    updated["status"] = "answered"
    updated["answers"] = dict(answers)
    return updated


def _cleared_repair_state(validation: dict[str, Any]) -> dict[str, Any]:
    updated = dict(validation or {})
    updated.pop("repair", None)
    return updated


def _mission_plan_validation(spec_dict: dict[str, Any]) -> dict[str, Any]:
    mission_spec = MissionSpec.from_dict(spec_dict)
    structured_issues = _build_structured_validation_issues(spec_dict)
    issues = [_issue_summary(issue) for issue in structured_issues]
    warnings: list[str] = []
    if len(mission_spec.tasks) > 7:
        warnings.append("Task count exceeds mission-plan guidance of 7 tasks.")
    return {
        "issues": issues,
        "warnings": warnings,
        "structured_issues": structured_issues,
        "blocking_issues": [issue for issue in structured_issues if issue.get("blocking")],
    }


def _critic_prompt(name: str, goal: str, spec_dict: dict[str, Any]) -> str:
    return (
        f"You are the {name} critic for an AgentForce mission plan.\n"
        "Return valid JSON only with keys 'summary', 'issues', and 'suggestions'.\n"
        "Each issue must be an object with 'severity', 'title', and 'fix'.\n\n"
        f"Goal:\n{goal}\n\n"
        f"Current draft_spec JSON:\n{json.dumps(spec_dict, indent=2, sort_keys=True)}\n"
    )


def _parse_critic_output(text: str) -> dict[str, Any]:
    text = text.strip()
    # Try direct parse
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    # Try extracting from markdown fence
    if payload is None and "```json" in text:
        try:
            block = text.split("```json", 1)[1].split("```", 1)[0].strip()
            payload = json.loads(block)
        except (json.JSONDecodeError, IndexError):
            pass

    if payload is None:
        payload = _extract_json_object_candidate(
            text,
            required_keys=("summary", "issues", "suggestions"),
        )

    if not isinstance(payload, dict):
        return {"summary": text, "issues": [], "suggestions": []}

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


def _resolver_prompt(goal: str, spec_dict: dict[str, Any], technical: dict[str, Any], practical: dict[str, Any]) -> str:
    return (
        "You are the resolver for an AgentForce mission plan. Your job is to integrate feedback from two critics "
        "into the final mission plan. Ensure all tasks have dependencies, acceptance criteria, and output artifacts "
        "as requested by the critics. If they identified architectural bugs or URL inconsistencies, fix them.\n\n"
        "Return valid JSON only with keys 'assistant_message' and 'draft_spec'.\n"
        "'draft_spec' must be a complete AgentForce MissionSpec-shaped object.\n\n"
        f"Goal:\n{goal}\n\n"
        f"Technical Critic Findings:\n{json.dumps(technical, indent=2)}\n\n"
        f"Practical Critic Findings:\n{json.dumps(practical, indent=2)}\n\n"
        f"Original draft_spec JSON:\n{json.dumps(spec_dict, indent=2, sort_keys=True)}\n"
    )


def _resolve_findings(draft: MissionDraftV1, spec_dict: dict[str, Any], technical: dict[str, Any], practical: dict[str, Any]) -> tuple[dict[str, Any], str, TokenEvent]:
    profile = _resolve_profile(draft, "resolver")
    prompt = _resolver_prompt(draft.draft_spec.get("goal") or "", spec_dict, technical, practical)
    output, usage = _invoke_profile(profile, prompt, draft.draft_spec.get("working_dir"))
    try:
        # Strip markdown fences if any
        text = output.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(line for line in lines if not line.startswith("```")).strip()
        payload = json.loads(text)
        if not isinstance(payload, dict):
            payload = _extract_json_object_candidate(
                text,
                required_keys=("assistant_message", "draft_spec"),
            )
    except Exception:
        payload = _extract_json_object_candidate(
            output.strip(),
            required_keys=("assistant_message", "draft_spec"),
        )
    try:
        if not isinstance(payload, dict):
            raise ValueError("resolver response was not valid JSON")
        resolved_spec = payload.get("draft_spec")
        message = payload.get("assistant_message") or "Resolved critic findings and updated the plan."
        if not isinstance(resolved_spec, dict):
            raise ValueError("resolver response missing draft_spec")
        return resolved_spec, message, usage
    except Exception as exc:
        # Fallback to original spec if resolution fails
        return spec_dict, f"Resolution failed: {str(exc)}. Using original plan.", usage


def _repair_context_lines(draft: MissionDraftV1) -> str:
    repair = _repair_state_from_validation(draft.validation)
    if repair.get("status") != "answered":
        return "No prior repair answers provided."
    lines: list[str] = []
    question_map = {
        str(question.get("id") or ""): question
        for question in repair.get("questions") or []
        if isinstance(question, dict)
    }
    for question_id, answer in dict(repair.get("answers") or {}).items():
        if not isinstance(answer, dict):
            continue
        selected = str(answer.get("selected_option") or "").strip()
        custom = str(answer.get("custom_answer") or "").strip()
        prompt = str(question_map.get(question_id, {}).get("prompt") or question_id)
        if selected or custom:
            lines.append(f"- {prompt}: {custom or selected}")
    return "\n".join(lines) if lines else "No prior repair answers provided."


def _repair_prompt(
    draft: MissionDraftV1,
    spec_dict: dict[str, Any],
    blocking_issues: list[dict[str, Any]],
) -> str:
    return (
        "You are repairing an AgentForce mission plan after validation found blocking issues.\n"
        "Return valid JSON only with keys 'assistant_message' and 'draft_spec'.\n"
        "'draft_spec' must remain a complete MissionSpec-shaped object.\n"
        "Make the smallest possible changes needed to resolve the blocking issues.\n"
        "You may rewrite definition_of_done items and acceptance_criteria items freely.\n"
        "You may propose task description changes only when absolutely necessary to keep the plan coherent.\n"
        "Do not change task ids, dependencies, caps, execution defaults, working_dir, or the number of tasks.\n\n"
        f"Blocking issues:\n{json.dumps(blocking_issues, indent=2)}\n\n"
        f"Prior repair answers:\n{_repair_context_lines(draft)}\n\n"
        f"Current draft_spec JSON:\n{json.dumps(spec_dict, indent=2, sort_keys=True)}\n"
    )


def _parse_repair_output(output: str) -> tuple[dict[str, Any], str]:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    try:
        payload = json.loads(text)
    except Exception:
        payload = _extract_json_object_candidate(text, required_keys=("assistant_message", "draft_spec"))
    if not isinstance(payload, dict):
        raise ValueError("Repair output was not valid JSON")
    spec_dict = payload.get("draft_spec")
    if not isinstance(spec_dict, dict):
        raise ValueError("Repair output missing draft_spec")
    return spec_dict, str(payload.get("assistant_message") or "Updated the mission plan to address validation issues.")


def _diff_spec_fields(before: Any, after: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        diffs: list[tuple[tuple[str, ...], Any, Any]] = []
        for key in sorted(set(before) | set(after)):
            if key not in before or key not in after:
                diffs.append((path + (str(key),), before.get(key), after.get(key)))
                continue
            diffs.extend(_diff_spec_fields(before[key], after[key], path + (str(key),)))
        return diffs
    if isinstance(before, list) and isinstance(after, list):
        diffs: list[tuple[tuple[str, ...], Any, Any]] = []
        max_len = max(len(before), len(after))
        for index in range(max_len):
            left = before[index] if index < len(before) else None
            right = after[index] if index < len(after) else None
            diffs.extend(_diff_spec_fields(left, right, path + (str(index),)))
        return diffs
    if before != after:
        return [(path, before, after)]
    return []


def _repair_diff_analysis(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    description_changes: list[dict[str, Any]] = []
    disallowed_paths: list[str] = []

    for path, old, new in _diff_spec_fields(before, after):
        if not path:
            continue
        if path[0] == "definition_of_done":
            continue
        if len(path) >= 4 and path[0] == "tasks" and path[2] == "acceptance_criteria":
            continue
        if len(path) >= 3 and path[0] == "tasks" and path[2] == "description":
            task_index = int(path[1])
            before_task = (before.get("tasks") or [])[task_index] if task_index < len(before.get("tasks") or []) else {}
            after_task = (after.get("tasks") or [])[task_index] if task_index < len(after.get("tasks") or []) else {}
            description_changes.append(
                {
                    "question_id": f"task_description_{task_index}",
                    "task_id": str(before_task.get("id") or after_task.get("id") or f"task-{task_index}"),
                    "before_text": str(old or ""),
                    "proposed_text": str(new or ""),
                }
            )
            continue
        disallowed_paths.append(".".join(path))

    return {
        "description_changes": description_changes,
        "disallowed_paths": disallowed_paths,
    }


def _repair_issue_question(issue: dict[str, Any], index: int) -> dict[str, Any]:
    original_text = str(issue.get("original_text") or "").strip()
    kind = str(issue.get("kind") or "")
    task_id = str(issue.get("task_id") or "").strip()
    label = f"task {task_id}" if task_id else "this item"
    if kind == "dod_vague":
        prompt = "How should this Definition of Done item be made measurable?"
    else:
        prompt = f"How should the vague acceptance criterion on {label} be made measurable?"
    return {
        "id": str(issue.get("issue_id") or f"repair_{index}"),
        "prompt": prompt,
        "options": [
            "Add an explicit verification command and exit code",
            "Require a concrete output artifact or file path",
            "State an exact value or comparison to verify",
        ],
        "reason": original_text,
        "allow_custom": True,
        "issue_ids": [str(issue.get("issue_id") or "")],
    }


def _description_change_question(change: dict[str, Any]) -> dict[str, Any]:
    task_id = str(change.get("task_id") or "task")
    before_text = str(change.get("before_text") or "")
    proposed_text = str(change.get("proposed_text") or "")
    return {
        "id": str(change.get("question_id") or f"{task_id}_description_change"),
        "prompt": f"Allow the planner to update the description for {task_id}?",
        "options": ["Accept proposed change", "Decline proposed change", "Edit manually"],
        "reason": "Description changes require explicit approval before they can alter plan semantics.",
        "allow_custom": True,
        "issue_ids": [f"{task_id}:description_change"],
        "preview": {
            "before_text": before_text,
            "proposed_text": proposed_text,
            "why_required": "The repair pass could not make the plan coherent with criteria-only changes.",
        },
    }


def _build_repair_questions(
    blocking_issues: list[dict[str, Any]],
    *,
    description_changes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for change in description_changes or []:
        questions.append(_description_change_question(change))
    for index, issue in enumerate(blocking_issues, start=1):
        questions.append(_repair_issue_question(issue, index))
        if len(questions) >= 5:
            break
    return questions[:5]


def _repair_gate_reason(blocking_issues: list[dict[str, Any]], *, description_changes: list[dict[str, Any]] | None = None) -> str:
    if description_changes:
        return "Planner needs explicit approval before changing task descriptions."
    if not blocking_issues:
        return "Repair requires operator input."
    return _issue_summary(blocking_issues[0])


def _attempt_quality_repair(
    draft: MissionDraftV1,
    spec_dict: dict[str, Any],
    blocking_issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], str, TokenEvent, dict[str, Any] | None]:
    if not blocking_issues:
        validation = _mission_plan_validation(spec_dict)
        return spec_dict, validation, "No blocking validation issues remained.", TokenEvent(0, 0, 0.0), None

    profile = _resolve_profile(draft, "resolver")
    attempts = 0
    current_spec = spec_dict
    current_validation = _mission_plan_validation(current_spec)
    latest_message = "Blocking validation issues remained after resolver."
    total_usage = TokenEvent(0, 0, 0.0)

    while attempts < 2 and current_validation.get("blocking_issues"):
        attempts += 1
        output, usage = _invoke_profile(
            profile,
            _repair_prompt(draft, current_spec, list(current_validation.get("blocking_issues") or [])),
            draft.draft_spec.get("working_dir"),
        )
        total_usage = _sum_token_events(total_usage, usage)
        candidate_spec, latest_message = _parse_repair_output(output)
        diff = _repair_diff_analysis(current_spec, candidate_spec)
        if diff["disallowed_paths"]:
            break
        if diff["description_changes"]:
            questions = _build_repair_questions(
                list(current_validation.get("blocking_issues") or []),
                description_changes=diff["description_changes"],
            )
            gate_reason = _repair_gate_reason(list(current_validation.get("blocking_issues") or []), description_changes=diff["description_changes"])
            return current_spec, current_validation, latest_message, total_usage, {
                "questions": questions,
                "gate_reason": gate_reason,
            }
        current_spec = candidate_spec
        current_validation = _mission_plan_validation(current_spec)
        if not current_validation.get("blocking_issues"):
            return current_spec, current_validation, latest_message, total_usage, None

    questions = _build_repair_questions(list(current_validation.get("blocking_issues") or []))
    gate_reason = _repair_gate_reason(list(current_validation.get("blocking_issues") or []))
    return current_spec, current_validation, latest_message, total_usage, {
        "questions": questions,
        "gate_reason": gate_reason,
    }


def _extract_json_object_candidate(text: str, *, required_keys: tuple[str, ...]) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []

    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            candidates.append(candidate)

    for candidate in reversed(candidates):
        if all(key in candidate for key in required_keys):
            return candidate

    for candidate in reversed(candidates):
        return candidate

    return None


def run_plan_run(run_id: str) -> None:
    store = _plan_store()
    run = store.load_run(run_id)
    if run is None:
        raise RuntimeError(f"Plan run {run_id!r} not found")

    try:
        _run_plan_run_internal(run)
    except Exception as exc:
        error_msg = str(exc)
        # Reload to get latest step state
        latest = store.load_run(run_id) or run
        failed = latest.copy_with(
            status="failed",
            error_message=error_msg,
            completed_at=_now_iso(),
        )
        store.save_run(failed)
        _emit("plan_run_failed", {
            "draft_id": failed.draft_id,
            "plan_run_id": failed.id,
            "error": error_msg,
            "message": error_msg,
        })
        raise


def _run_plan_run_internal(run: PlanRunRecord) -> None:
    store = _plan_store()
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
    repair_usage = TokenEvent(0, 0, 0.0)
    repair_gate: dict[str, Any] | None = None

    # Resolve findings if any issues were reported
    if technical.get("issues") or practical.get("issues") or validation.get("issues"):
        spec_dict, assistant_message, resolver_usage = _resolve_findings(draft, spec_dict, technical, practical)
        validation = _mission_plan_validation(spec_dict)
        if validation.get("blocking_issues"):
            spec_dict, validation, repair_message, repair_usage, repair_gate = _attempt_quality_repair(
                draft,
                spec_dict,
                list(validation.get("blocking_issues") or []),
            )
            assistant_message = f"{assistant_message} {repair_message}".strip()
    else:
        assistant_message = "Initial planning pass completed without critic findings."
        resolver_usage = TokenEvent(0, 0, 0.0)

    latest_draft = _draft_store().load(draft.id)
    if latest_draft is None:
        raise RuntimeError(f"Draft {draft.id!r} disappeared during planning")

    prior_repair = _repair_state_from_validation(latest_draft.validation)
    if repair_gate:
        next_round = int(prior_repair.get("repair_round") or 0) + 1
        max_rounds = int(prior_repair.get("max_rounds") or 2)
        if next_round > max_rounds:
            repair_state = {
                **_blank_repair_state(),
                "status": "manual_edit_required",
                "repair_round": max_rounds,
                "max_rounds": max_rounds,
                "issues": list(validation.get("blocking_issues") or []),
                "questions": [],
                "answers": {},
                "gate_reason": "Repair round cap reached. Open edit mode and fix the mission manually.",
            }
            assistant_message = "Repair round cap reached. Open edit mode and fix the mission manually."
        else:
            repair_state = _pending_repair_state(
                run=run,
                version_id="",
                issues=list(validation.get("blocking_issues") or []),
                questions=list(repair_gate.get("questions") or []),
                gate_reason=str(repair_gate.get("gate_reason") or ""),
                repair_round=next_round,
                max_rounds=max_rounds,
                mode="plan",
            )
            assistant_message = str(repair_gate.get("gate_reason") or assistant_message)
    else:
        repair_state = None

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
            "repair": repair_state or _blank_repair_state(),
        },
    )
    if repair_state is not None and repair_state.get("status") == "pending":
        repair_state = {**repair_state, "source_version_id": version.id}
        version = version.copy_with(validation={**version.validation, "repair": repair_state})
        store.save_version(version)
    run = _record_step(
        run,
        name="resolver",
        status="completed",
        message="Reviewed version created",
        summary=" ".join(changelog),
        token_event=_sum_token_events(resolver_usage, repair_usage),
        metadata={"version_id": version.id, "repair_status": (repair_state or {}).get("status", "not_needed")},
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
        turns=list(latest_draft.turns) + [{"role": "assistant", "content": assistant_message}],
        validation={
            **_cleared_repair_state(latest_draft.validation),
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
            **({"repair": repair_state} if repair_state is not None else {}),
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

    ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
    state_io._broadcast_mission_list_refresh()

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


def _black_hole_store() -> BlackHoleCampaignStore:
    return BlackHoleCampaignStore()


def _effective_daemon():
    try:
        from agentforce.server import handler as _handler

        daemon = getattr(_handler, "_daemon", None)
        if daemon is None:
            return None
        try:
            return daemon if daemon.status().get("running") else None
        except Exception:
            return daemon
    except Exception:
        return None


def _emit_black_hole(event_type: str, payload: dict[str, Any]) -> None:
    ws.broadcast({"type": event_type, **payload})


def _broadcast_black_hole_campaign(campaign: BlackHoleCampaignRecord) -> None:
    _emit_black_hole(
        "black_hole_campaign_updated",
        {
            "draft_id": campaign.draft_id,
            "campaign": campaign.to_dict(),
        },
    )


def _broadcast_black_hole_loop(draft_id: str, loop: BlackHoleLoopRecord) -> None:
    _emit_black_hole(
        "black_hole_loop_recorded",
        {
            "draft_id": draft_id,
            "campaign_id": loop.campaign_id,
            "loop": loop.to_dict(),
        },
    )


def enqueue_black_hole_campaign(campaign_id: str, *, draft_id: str | None = None) -> None:
    daemon = _effective_daemon()
    if daemon is not None:
        from agentforce.daemon import DaemonJob

        daemon.enqueue_job(
            DaemonJob(
                job_id=campaign_id,
                job_type="black_hole_campaign",
                payload={"draft_id": draft_id} if draft_id else {},
            )
        )
        return

    def _runner() -> None:
        try:
            run_black_hole_campaign(campaign_id)
        except Exception:
            pass

    threading.Thread(target=_runner, daemon=True, name=f"agentforce-black-hole-{campaign_id}").start()


def handle_black_hole_daemon_completion(event: dict[str, Any]) -> None:
    mission_id = str(event.get("mission_id") or "").strip()
    if not mission_id:
        return
    campaign = _black_hole_store().find_by_active_child_mission(mission_id)
    if campaign is None:
        return
    enqueue_black_hole_campaign(campaign.id, draft_id=campaign.draft_id)


def _fallback_black_hole_spec(draft: MissionDraftV1, config: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate.get("payload") or {})
    threshold = int(dict(config.get("loop_limits") or {}).get("function_line_limit") or 300)
    working_dir = draft.workspace_paths[0] if draft.workspace_paths else draft.draft_spec.get("working_dir")
    function_name = str(payload.get("function_name") or candidate.get("id") or "candidate")
    file_path = str(payload.get("path") or "")
    line_count = int(payload.get("line_count") or 0)
    description = (
        f"Refactor only `{function_name}` in `{file_path}` so it is <= {threshold} lines.\n\n"
        f"Current length: {line_count} lines.\n"
        "Keep the change scoped to the selected candidate, add or update focused tests when feasible, "
        "and avoid public API changes unless they are clearly justified."
    )
    return {
        "name": f"Black Hole Loop {function_name}"[:80],
        "goal": str(config.get("objective") or draft.draft_spec.get("goal") or "").strip() or "Execute one black-hole loop",
        "working_dir": working_dir,
        "definition_of_done": [
            f"The selected candidate is within the configured analyzer limit ({threshold} lines).",
            "Tests that cover the touched behavior are added or updated when feasible.",
            "Any public-surface change is explicitly justified in the worker summary.",
        ],
        "caps": {
            "max_concurrent_workers": 1,
            "max_retries_global": 2,
            "max_retries_per_task": 2,
            "max_wall_time_minutes": 90,
            "max_human_interventions": 2,
            "max_tokens_per_task": 100000,
        },
        "execution_defaults": draft.draft_spec.get("execution_defaults") or {},
        "tasks": [
            {
                "id": "black_hole_loop",
                "title": f"Refactor {function_name}",
                "description": description,
                "acceptance_criteria": [
                    f"`{function_name}` ends at or below {threshold} lines.",
                    f"`{file_path}` is updated only as much as needed for the selected refactor target.",
                    "Tests are added or updated when feasible and their command/outcome is reported.",
                    "The worker summary explicitly states whether any public classes or public APIs changed and why.",
                ],
                "dependencies": [],
                "working_dir": working_dir,
                "max_retries": 2,
                "output_artifacts": [file_path] if file_path else [],
            }
        ],
    }


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_black_hole_child_task(task: dict[str, Any], fallback_task: dict[str, Any], working_dir: str | None) -> dict[str, Any]:
    normalized = dict(fallback_task)
    if isinstance(task.get("id"), str) and task["id"].strip():
        normalized["id"] = task["id"].strip()
    if isinstance(task.get("title"), str) and task["title"].strip():
        normalized["title"] = task["title"].strip()
    if isinstance(task.get("description"), str) and task["description"].strip():
        normalized["description"] = task["description"].strip()

    acceptance_criteria = _normalized_string_list(task.get("acceptance_criteria"))
    if acceptance_criteria:
        normalized["acceptance_criteria"] = acceptance_criteria

    dependencies = _normalized_string_list(task.get("dependencies"))
    normalized["dependencies"] = dependencies

    if isinstance(task.get("working_dir"), str) and task["working_dir"].strip():
        normalized["working_dir"] = task["working_dir"].strip()
    elif working_dir:
        normalized["working_dir"] = working_dir

    try:
        normalized["max_retries"] = max(1, int(task.get("max_retries") or normalized.get("max_retries") or 2))
    except (TypeError, ValueError):
        normalized["max_retries"] = int(fallback_task.get("max_retries") or 2)

    output_artifacts = _normalized_string_list(task.get("output_artifacts"))
    if output_artifacts:
        normalized["output_artifacts"] = output_artifacts

    execution = task.get("execution")
    if isinstance(execution, dict) and execution:
        normalized["execution"] = execution
    model = task.get("model")
    if isinstance(model, str) and model.strip():
        normalized["model"] = model.strip()
    return normalized


def _normalize_black_hole_child_spec(
    draft: MissionDraftV1,
    config: dict[str, Any],
    candidate: dict[str, Any],
    spec_dict: dict[str, Any] | None,
) -> dict[str, Any]:
    fallback = _fallback_black_hole_spec(draft, config, candidate)
    raw_spec = dict(spec_dict or {})
    nested = raw_spec.get("draft_spec")
    if isinstance(nested, dict):
        missing_required = any(key not in raw_spec for key in ("name", "goal", "definition_of_done", "tasks"))
        if missing_required:
            raw_spec = dict(nested)

    normalized = dict(fallback)
    normalized["name"] = str(raw_spec.get("name") or fallback["name"]).strip() or fallback["name"]
    normalized["goal"] = str(raw_spec.get("goal") or fallback["goal"]).strip() or fallback["goal"]

    definition_of_done = _normalized_string_list(raw_spec.get("definition_of_done"))
    normalized["definition_of_done"] = definition_of_done or list(fallback["definition_of_done"])

    working_dir = str(raw_spec.get("working_dir") or fallback.get("working_dir") or "").strip()
    normalized["working_dir"] = working_dir or None

    caps = dict(fallback.get("caps") or {})
    raw_caps = raw_spec.get("caps")
    if isinstance(raw_caps, dict):
        caps.update({key: value for key, value in raw_caps.items() if value is not None})
    caps["max_concurrent_workers"] = 1
    normalized["caps"] = caps

    execution_defaults = raw_spec.get("execution_defaults")
    normalized["execution_defaults"] = execution_defaults if isinstance(execution_defaults, dict) else dict(fallback.get("execution_defaults") or {})

    fallback_task = dict((fallback.get("tasks") or [{}])[0])
    raw_tasks = raw_spec.get("tasks")
    if isinstance(raw_tasks, list):
        candidate_tasks = [dict(task) for task in raw_tasks if isinstance(task, dict)]
    else:
        candidate_tasks = []
    task_source = candidate_tasks[0] if candidate_tasks else fallback_task
    normalized["tasks"] = [_normalize_black_hole_child_task(task_source, fallback_task, normalized["working_dir"])]

    project_memory_file = raw_spec.get("project_memory_file")
    if isinstance(project_memory_file, str) and project_memory_file.strip():
        normalized["project_memory_file"] = project_memory_file.strip()
    return normalized


def _black_hole_planner_prompt(
    draft: MissionDraftV1,
    config: dict[str, Any],
    analyzer_result: dict[str, Any],
    candidate: dict[str, Any],
    loop_no: int,
) -> str:
    return (
        "You are synthesizing one AgentForce mission for a black-hole campaign loop.\n"
        "Return valid JSON only with keys 'assistant_message' and 'draft_spec'.\n"
        "'draft_spec' must be a complete MissionSpec-shaped object with EXACTLY one task and caps.max_concurrent_workers=1.\n"
        "Do not plan the whole repository. Scope the task to the selected candidate only.\n"
        "Make acceptance criteria measurable and include explicit test expectations when feasible.\n"
        "Public classes or APIs should stay unchanged unless absolutely necessary; if a change may be required, say so in the task description.\n\n"
        f"Campaign objective:\n{config.get('objective') or draft.draft_spec.get('goal') or ''}\n\n"
        f"Loop number: {loop_no}\n"
        f"Analyzer summary:\n{json.dumps(analyzer_result, indent=2, sort_keys=True)}\n\n"
        f"Selected candidate:\n{json.dumps(candidate, indent=2, sort_keys=True)}\n\n"
        f"Workspace:\n{json.dumps(draft.workspace_paths, indent=2)}\n\n"
        f"Execution defaults:\n{json.dumps(draft.draft_spec.get('execution_defaults') or {}, indent=2, sort_keys=True)}\n"
    )


def _parse_black_hole_planner_output(output: str) -> tuple[dict[str, Any], str]:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    try:
        payload = json.loads(text)
    except Exception:
        payload = _extract_json_object_candidate(
            text,
            required_keys=("assistant_message", "draft_spec"),
        )
    if not isinstance(payload, dict):
        raise ValueError("Planner output was not valid JSON")
    spec_dict = payload.get("draft_spec")
    if not isinstance(spec_dict, dict):
        raise ValueError("Planner output missing draft_spec")
    return spec_dict, str(payload.get("assistant_message") or "Black-hole child mission synthesized.")


def _safe_profile_invoke(profile: PlanningProfile, prompt: str, workdir: str | None) -> tuple[str, TokenEvent | None, str | None]:
    try:
        output, usage = _invoke_profile(profile, prompt, workdir)
        return output, usage, None
    except Exception as exc:
        return "", None, str(exc)


def _synthesize_black_hole_child_plan(
    campaign: BlackHoleCampaignRecord,
    draft: MissionDraftV1,
    config: dict[str, Any],
    analyzer_result: dict[str, Any],
    candidate: dict[str, Any],
    loop_no: int,
) -> tuple[PlanRunRecord, Any, dict[str, Any], list[str], str, dict[str, Any] | None]:
    store = _plan_store()
    run = store.create_run(
        str(uuid.uuid4()),
        draft_id=draft.id,
        base_revision=draft.revision,
        trigger_kind="black_hole_loop",
        trigger_message=f"Black-hole loop {loop_no}: {candidate.get('summary') or candidate.get('title') or candidate.get('id') or ''}",
    )
    _emit(
        "plan_run_queued",
        {
            "draft_id": draft.id,
            "plan_run_id": run.id,
            "base_revision": run.base_revision,
            "message": run.trigger_message,
        },
    )
    run = run.copy_with(status="running", started_at=run.created_at)
    store.save_run(run)
    _emit("plan_run_started", {"draft_id": draft.id, "plan_run_id": run.id, "base_revision": run.base_revision})

    planner_profile = _resolve_profile(draft, "planner")
    technical_profile = _resolve_profile(draft, "critic_technical")
    practical_profile = _resolve_profile(draft, "critic_practical")

    run = _record_step(run, name="planner_synthesis", status="started", message="Generating black-hole child mission")
    planner_text, planner_usage, planner_error = _safe_profile_invoke(
        planner_profile,
        _black_hole_planner_prompt(draft, config, analyzer_result, candidate, loop_no),
        draft.draft_spec.get("working_dir"),
    )
    try:
        spec_dict, assistant_message = _parse_black_hole_planner_output(planner_text)
    except Exception:
        spec_dict = _fallback_black_hole_spec(draft, config, candidate)
        assistant_message = (
            "Planner output was unavailable; using a deterministic single-task fallback mission scoped to the selected candidate."
            if planner_error
            else "Planner output was invalid; using a deterministic single-task fallback mission scoped to the selected candidate."
        )
    spec_dict = _normalize_black_hole_child_spec(draft, config, candidate, spec_dict)
    run = _record_step(
        run,
        name="planner_synthesis",
        status="completed",
        message=assistant_message,
        summary=assistant_message,
        token_event=planner_usage,
        metadata={"profile": planner_profile.__dict__, "planner_error": planner_error or ""},
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

    technical: dict[str, Any] = {"summary": "", "issues": [], "suggestions": []}
    run = _record_step(run, name="technical_critic", status="started", message="Running technical adversary review")
    technical_text, technical_usage, technical_error = _safe_profile_invoke(
        technical_profile,
        _critic_prompt("technical", str(config.get("objective") or draft.draft_spec.get("goal") or ""), spec_dict),
        draft.draft_spec.get("working_dir"),
    )
    if technical_text:
        technical = _parse_critic_output(technical_text)
    elif technical_error:
        technical = {"summary": technical_error, "issues": [], "suggestions": []}
    run = _record_step(
        run,
        name="technical_critic",
        status="completed",
        message="Technical adversary review complete",
        summary=technical.get("summary") or "Technical review skipped",
        token_event=technical_usage,
        metadata=technical,
    )

    practical: dict[str, Any] = {"summary": "", "issues": [], "suggestions": []}
    run = _record_step(run, name="practical_critic", status="started", message="Running practical adversary review")
    practical_text, practical_usage, practical_error = _safe_profile_invoke(
        practical_profile,
        _critic_prompt("practical", str(config.get("objective") or draft.draft_spec.get("goal") or ""), spec_dict),
        draft.draft_spec.get("working_dir"),
    )
    if practical_text:
        practical = _parse_critic_output(practical_text)
    elif practical_error:
        practical = {"summary": practical_error, "issues": [], "suggestions": []}
    run = _record_step(
        run,
        name="practical_critic",
        status="completed",
        message="Practical adversary review complete",
        summary=practical.get("summary") or "Practical review skipped",
        token_event=practical_usage,
        metadata=practical,
    )

    changelog = _resolver_changelog(validation, technical, practical)
    run = _record_step(run, name="resolver", status="started", message="Resolving critic findings")
    repair_usage = TokenEvent(0, 0, 0.0)
    repair_gate: dict[str, Any] | None = None
    if technical.get("issues") or practical.get("issues") or validation.get("issues"):
        spec_dict, assistant_message, resolver_usage = _resolve_findings(draft, spec_dict, technical, practical)
        spec_dict = _normalize_black_hole_child_spec(draft, config, candidate, spec_dict)
        validation = _mission_plan_validation(spec_dict)
        if validation.get("blocking_issues"):
            spec_dict, validation, repair_message, repair_usage, repair_gate = _attempt_quality_repair(
                draft,
                spec_dict,
                list(validation.get("blocking_issues") or []),
            )
            assistant_message = f"{assistant_message} {repair_message}".strip()
    else:
        resolver_usage = TokenEvent(0, 0, 0.0)

    latest_draft = _draft_store().load(draft.id)
    if latest_draft is None:
        raise RuntimeError(f"Draft {draft.id!r} disappeared during black-hole planning")

    prior_repair = _repair_state_from_validation(latest_draft.validation)
    if repair_gate:
        next_round = int(prior_repair.get("repair_round") or 0) + 1
        max_rounds = int(prior_repair.get("max_rounds") or 2)
        if next_round > max_rounds:
            repair_state = {
                **_blank_repair_state(),
                "status": "manual_edit_required",
                "repair_round": max_rounds,
                "max_rounds": max_rounds,
                "issues": list(validation.get("blocking_issues") or []),
                "questions": [],
                "answers": {},
                "gate_reason": "Repair round cap reached. Open edit mode and fix the child plan manually.",
                "mode": "black_hole",
                "loop_no": loop_no,
                "candidate": candidate,
                "analyzer_result": analyzer_result,
                "config_snapshot": config,
            }
            assistant_message = "Repair round cap reached. Open edit mode and fix the child plan manually."
        else:
            repair_state = _pending_repair_state(
                run=run,
                version_id="",
                issues=list(validation.get("blocking_issues") or []),
                questions=list(repair_gate.get("questions") or []),
                gate_reason=str(repair_gate.get("gate_reason") or ""),
                repair_round=next_round,
                max_rounds=max_rounds,
                mode="black_hole",
                loop_no=loop_no,
                candidate=candidate,
                analyzer_result=analyzer_result,
                config=config,
            )
            assistant_message = str(repair_gate.get("gate_reason") or assistant_message)
    else:
        repair_state = None
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
            "black_hole_campaign_id": campaign.id,
            "black_hole_loop_no": loop_no,
            "repair": repair_state or _blank_repair_state(),
        },
    )
    if repair_state is not None and repair_state.get("status") == "pending":
        repair_state = {**repair_state, "source_version_id": version.id}
        version = version.copy_with(validation={**version.validation, "repair": repair_state})
        store.save_version(version)
    run = _record_step(
        run,
        name="resolver",
        status="completed",
        message="Reviewed version created",
        summary=" ".join(changelog),
        token_event=_sum_token_events(resolver_usage, repair_usage),
        metadata={"version_id": version.id, "repair_status": (repair_state or {}).get("status", "not_needed")},
    )
    run = run.copy_with(
        status="completed",
        completed_at=_now_iso(),
        result_version_id=version.id,
        promoted_version_id=version.id,
        changelog=changelog,
    )
    store.save_run(run)
    _emit(
        "plan_version_created",
        {
            "draft_id": draft.id,
            "plan_run_id": run.id,
            "plan_version_id": version.id,
            "changelog": changelog,
        },
    )
    if repair_state is not None:
        promoted = latest_draft.copy_with(
            turns=list(latest_draft.turns) + [{"role": "assistant", "content": assistant_message}],
            validation={
                **_cleared_repair_state(latest_draft.validation),
                "latest_plan_run_id": run.id,
                "latest_plan_version_id": version.id,
                "plan_validation": version.validation,
                "plan_changelog": changelog,
                "repair": repair_state,
            },
            activity_log=list(latest_draft.activity_log) + [{
                "type": "black_hole_repair_requested",
                "plan_run_id": run.id,
                "plan_version_id": version.id,
                "loop_no": loop_no,
            }],
        )
        save_result = _draft_store().save(promoted, expected_revision=latest_draft.revision)
        if save_result.status == "saved" and save_result.draft is not None:
            ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
            state_io._broadcast_mission_list_refresh()
    return run, version, spec_dict, changelog, assistant_message, repair_state


def _launch_black_hole_mission(
    draft: MissionDraftV1,
    spec_dict: dict[str, Any],
    *,
    loop_no: int,
    plan_run_id: str,
    plan_version_id: str,
) -> str:
    from agentforce.server.routes.missions import _make_mission_state_from_spec
    from agentforce.server.routes.plan import _launch_mission

    spec = MissionSpec.from_dict(spec_dict)
    issues = spec.validate(stage="launch")
    if issues:
        raise RuntimeError(issues[0])
    state = _make_mission_state_from_spec(spec)
    state.source_plan_run_id = plan_run_id
    state.source_plan_version_id = plan_version_id
    state.source_draft_id = draft.id
    state.log_event("mission_started", details=f"Started via black-hole campaign loop {loop_no}")
    state_dir = state_io.get_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    state.save(state_dir / f"{state.mission_id}.json")
    mark_version_launched(plan_version_id, state.mission_id)
    _launch_mission(state.mission_id)
    return state.mission_id


def _recalculate_campaign_totals(store: BlackHoleCampaignStore, campaign: BlackHoleCampaignRecord) -> BlackHoleCampaignRecord:
    loops = store.list_loops(campaign.id)
    return campaign.copy_with(
        tokens_in=sum(loop.tokens_in for loop in loops),
        tokens_out=sum(loop.tokens_out for loop in loops),
        cost_usd=round(sum(loop.cost_usd for loop in loops), 6),
    )


def _mission_review_summary(mission_state) -> str:
    needs_human = mission_state.needs_human()
    if needs_human:
        return f"Child mission is waiting on human input for {', '.join(needs_human)}."
    if mission_state.is_failed():
        return "Child mission finished with failed task state or caps hit."
    if mission_state.is_done():
        return "Child mission completed with all tasks review-approved."
    return "Child mission completed without a terminal success signal."


def _resume_black_hole_repair(
    campaign: BlackHoleCampaignRecord,
    draft: MissionDraftV1,
    repair_state: dict[str, Any],
) -> tuple[BlackHoleLoopRecord | None, PlanRunRecord | None, Any, dict[str, Any] | None]:
    loop_no = int(repair_state.get("loop_no") or 0)
    if loop_no <= 0:
        raise RuntimeError("Repair state is missing loop number.")
    loop = _black_hole_store().load_loop(campaign.id, loop_no)
    if loop is None:
        raise RuntimeError("Repair state references a missing loop.")
    candidate = dict(repair_state.get("candidate") or {})
    analyzer_result = dict(repair_state.get("analyzer_result") or {})
    config = dict(repair_state.get("config_snapshot") or campaign.config_snapshot or {})
    plan_run, version, spec_dict, _changelog, _assistant_message, next_repair = _synthesize_black_hole_child_plan(
        campaign,
        draft,
        config,
        analyzer_result,
        candidate,
        loop_no,
    )
    return loop, plan_run, version, next_repair


def run_black_hole_campaign(campaign_id: str) -> None:
    campaign_store = _black_hole_store()
    draft_store = _draft_store()
    campaign = campaign_store.load_campaign(campaign_id)
    if campaign is None or is_terminal_campaign_status(campaign.status) or campaign.status == "paused":
        return
    draft = draft_store.load(campaign.draft_id)
    if draft is None:
        campaign = campaign.copy_with(status="evaluation_failed", stop_reason="Draft not found")
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return

    config = dict(campaign.config_snapshot or draft.validation.get("black_hole_config") or {})
    if str(draft.validation.get("preflight_status") or "") == "pending":
        campaign = campaign.copy_with(status="preflight_pending", stop_reason="Answer preflight questions before starting the campaign.")
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return
    repair_state = _repair_state_from_validation(draft.validation)
    if repair_state.get("mode") == "black_hole" and repair_state.get("status") == "pending":
        campaign = campaign.copy_with(status="waiting_human", stop_reason=str(repair_state.get("gate_reason") or "Answer repair questions before continuing the campaign."))
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return
    if repair_state.get("mode") == "black_hole" and repair_state.get("status") == "manual_edit_required":
        campaign = campaign.copy_with(status="waiting_human", stop_reason=str(repair_state.get("gate_reason") or "Manual child-plan edits are required before this loop can continue."))
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return
    if repair_state.get("mode") == "black_hole" and repair_state.get("status") == "answered":
        try:
            locked_loop, plan_run, version, next_repair = _resume_black_hole_repair(campaign, draft, repair_state)
            if next_repair is not None:
                campaign = campaign.copy_with(
                    status="waiting_human",
                    stop_reason=str(next_repair.get("gate_reason") or "Repair questions still need answers."),
                    active_plan_run_id=plan_run.id if plan_run is not None else None,
                )
                campaign_store.save_campaign(campaign)
                _broadcast_black_hole_campaign(campaign)
                return
            mission_id = _launch_black_hole_mission(
                draft,
                version.draft_spec_snapshot,
                loop_no=locked_loop.loop_no if locked_loop is not None else int(repair_state.get("loop_no") or 0),
                plan_run_id=plan_run.id,
                plan_version_id=version.id,
            )
        except Exception as exc:
            campaign = campaign.copy_with(status="launch_failed", stop_reason=str(exc))
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return

        if locked_loop is None or plan_run is None:
            raise RuntimeError("Repair resume did not return loop provenance.")
        relaunched_loop = locked_loop.copy_with(
            status="child_mission_running",
            mission_id=mission_id,
            plan_run_id=plan_run.id,
            plan_version_id=version.id,
            review_summary="Child mission relaunched after repair guidance.",
            gate_reason="",
            tokens_in=plan_run.tokens_in,
            tokens_out=plan_run.tokens_out,
            cost_usd=plan_run.cost_usd,
        )
        campaign_store.save_loop(relaunched_loop)
        _broadcast_black_hole_loop(draft.id, relaunched_loop)
        cleared = draft.copy_with(
            validation=_cleared_repair_state(draft.validation),
            activity_log=list(draft.activity_log) + [{
                "type": "black_hole_repair_resumed",
                "plan_run_id": plan_run.id,
                "plan_version_id": version.id,
                "loop_no": relaunched_loop.loop_no,
            }],
        )
        save_result = draft_store.save(cleared, expected_revision=draft.revision)
        if save_result.status == "saved" and save_result.draft is not None:
            draft = save_result.draft
            ws.broadcast_draft_updated(draft.id, draft.status)
            state_io._broadcast_mission_list_refresh()
        campaign = _recalculate_campaign_totals(
            campaign_store,
            campaign.copy_with(
                status="child_mission_running",
                current_loop=relaunched_loop.loop_no,
                active_child_mission_id=mission_id,
                active_plan_run_id=plan_run.id,
                stop_reason="",
            ),
        )
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return

    try:
        analyzer_result = evaluate_black_hole_analyzer(draft.workspace_paths, config)
    except Exception as exc:
        campaign = campaign.copy_with(status="evaluation_failed", stop_reason=str(exc))
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return
    analyzer_payload = analyzer_result.to_dict()

    if campaign.active_child_mission_id:
        mission_state = state_io._load_state(campaign.active_child_mission_id)
        if mission_state is None:
            campaign = campaign.copy_with(status="launch_failed", stop_reason="Active child mission state was not found on disk.")
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return
        if not mission_state.finished_at and not mission_state.completed_at and not mission_state.is_failed() and not mission_state.needs_human():
            campaign = campaign.copy_with(status="child_mission_running", last_metric=analyzer_payload["metric"])
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return

        current_loop = campaign_store.load_loop(campaign.id, campaign.current_loop)
        if current_loop is None:
            campaign = campaign.copy_with(status="evaluation_failed", stop_reason="Active loop provenance is missing.")
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return

        mission_summary = _mission_review_summary(mission_state)
        delta = normalized_progress_delta(current_loop.metric_before, analyzer_payload["metric"], analyzer_result.analyzer)
        run = _plan_store().load_run(current_loop.plan_run_id or "") if current_loop.plan_run_id else None
        updated_loop = current_loop.copy_with(
            status="completed" if analyzer_result.success else ("waiting_human" if mission_state.needs_human() or mission_state.is_failed() else "reviewed"),
            completed_at=_now_iso(),
            metric_after=analyzer_payload["metric"],
            normalized_delta=delta,
            review_summary=mission_summary,
            tokens_in=(run.tokens_in if run is not None else 0) + int(getattr(mission_state, "tokens_in", 0) or 0),
            tokens_out=(run.tokens_out if run is not None else 0) + int(getattr(mission_state, "tokens_out", 0) or 0),
            cost_usd=round((run.cost_usd if run is not None else 0.0) + float(getattr(mission_state, "cost_usd", 0.0) or 0.0), 6),
            gate_reason=mission_summary if mission_state.needs_human() or mission_state.is_failed() else "",
        )
        campaign_store.save_loop(updated_loop)
        _broadcast_black_hole_loop(draft.id, updated_loop)

        if mission_state.needs_human() or mission_state.is_failed():
            campaign = _recalculate_campaign_totals(
                campaign_store,
                campaign.copy_with(
                    status="waiting_human",
                    active_child_mission_id=None,
                    active_plan_run_id=None,
                    last_metric=analyzer_payload["metric"],
                    last_delta=delta,
                    stop_reason=mission_summary,
                    no_progress_count=(campaign.no_progress_count + 1) if delta <= 0 else 0,
                ),
            )
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return

        if analyzer_result.success:
            campaign = _recalculate_campaign_totals(
                campaign_store,
                campaign.copy_with(
                    status="succeeded",
                    active_child_mission_id=None,
                    active_plan_run_id=None,
                    last_metric=analyzer_payload["metric"],
                    last_delta=delta,
                    stop_reason=analyzer_result.summary,
                    no_progress_count=0,
                ),
            )
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return

        no_progress_count = (campaign.no_progress_count + 1) if delta <= 0 else 0
        if no_progress_count >= campaign.max_no_progress:
            campaign = _recalculate_campaign_totals(
                campaign_store,
                campaign.copy_with(
                    status="no_progress_limit",
                    active_child_mission_id=None,
                    active_plan_run_id=None,
                    last_metric=analyzer_payload["metric"],
                    last_delta=delta,
                    stop_reason="Campaign stopped after repeated non-positive progress.",
                    no_progress_count=no_progress_count,
                ),
            )
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return

        campaign = _recalculate_campaign_totals(
            campaign_store,
            campaign.copy_with(
                status="evaluating_workspace",
                active_child_mission_id=None,
                active_plan_run_id=None,
                last_metric=analyzer_payload["metric"],
                last_delta=delta,
                no_progress_count=no_progress_count,
                stop_reason="",
            ),
        )
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)

    else:
        if analyzer_result.success:
            campaign = campaign.copy_with(
                status="succeeded",
                last_metric=analyzer_payload["metric"],
                stop_reason=analyzer_result.summary,
            )
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return

    if campaign.current_loop >= campaign.max_loops:
        campaign = campaign.copy_with(
            status="max_loops_reached",
            stop_reason=f"Maximum loop count reached ({campaign.max_loops}).",
            last_metric=analyzer_payload["metric"],
        )
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return

    if not analyzer_result.candidates:
        campaign = campaign.copy_with(
            status="succeeded",
            stop_reason=analyzer_result.summary,
            last_metric=analyzer_payload["metric"],
        )
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return

    next_loop_no = campaign_store.next_loop_number(campaign.id)
    candidate = analyzer_result.candidates[0].to_dict()
    loop = BlackHoleLoopRecord(
        campaign_id=campaign.id,
        loop_no=next_loop_no,
        status="candidate_locked",
        created_at=_now_iso(),
        candidate_id=str(candidate.get("id") or ""),
        candidate_summary=str(candidate.get("summary") or candidate.get("title") or ""),
        candidate_payload=dict(candidate.get("payload") or {}),
        metric_before=analyzer_payload["metric"],
    )
    campaign_store.save_loop(loop)
    _broadcast_black_hole_loop(draft.id, loop)

    campaign = campaign.copy_with(status="candidate_locked", last_metric=analyzer_payload["metric"])
    campaign_store.save_campaign(campaign)
    _broadcast_black_hole_campaign(campaign)

    try:
        plan_run, version, spec_dict, changelog, _assistant_message, repair_gate = _synthesize_black_hole_child_plan(
            campaign,
            draft,
            config,
            analyzer_payload,
            candidate,
            next_loop_no,
        )
        if repair_gate is not None:
            gated_loop = loop.copy_with(
                status="waiting_human",
                completed_at=_now_iso(),
                plan_run_id=plan_run.id,
                plan_version_id=version.id,
                review_summary=str(repair_gate.get("gate_reason") or "Repair questions are waiting on operator input."),
                gate_reason=str(repair_gate.get("gate_reason") or ""),
                tokens_in=plan_run.tokens_in,
                tokens_out=plan_run.tokens_out,
                cost_usd=plan_run.cost_usd,
            )
            campaign_store.save_loop(gated_loop)
            _broadcast_black_hole_loop(draft.id, gated_loop)
            campaign = _recalculate_campaign_totals(
                campaign_store,
                campaign.copy_with(
                    status="waiting_human",
                    active_child_mission_id=None,
                    active_plan_run_id=plan_run.id,
                    last_metric=analyzer_payload["metric"],
                    stop_reason=str(repair_gate.get("gate_reason") or ""),
                ),
            )
            campaign_store.save_campaign(campaign)
            _broadcast_black_hole_campaign(campaign)
            return
        mission_id = _launch_black_hole_mission(
            draft,
            spec_dict,
            loop_no=next_loop_no,
            plan_run_id=plan_run.id,
            plan_version_id=version.id,
        )
    except Exception as exc:
        failed_loop = loop.copy_with(
            status="launch_failed",
            completed_at=_now_iso(),
            gate_reason=str(exc),
            review_summary=str(exc),
        )
        campaign_store.save_loop(failed_loop)
        _broadcast_black_hole_loop(draft.id, failed_loop)
        campaign = campaign.copy_with(status="launch_failed", stop_reason=str(exc), last_metric=analyzer_payload["metric"])
        campaign_store.save_campaign(campaign)
        _broadcast_black_hole_campaign(campaign)
        return

    launched_loop = loop.copy_with(
        status="child_mission_running",
        mission_id=mission_id,
        plan_run_id=plan_run.id,
        plan_version_id=version.id,
        review_summary="Child mission launched.",
        tokens_in=plan_run.tokens_in,
        tokens_out=plan_run.tokens_out,
        cost_usd=plan_run.cost_usd,
    )
    campaign_store.save_loop(launched_loop)
    _broadcast_black_hole_loop(draft.id, launched_loop)
    campaign = _recalculate_campaign_totals(
        campaign_store,
        campaign.copy_with(
            status="child_mission_running",
            current_loop=next_loop_no,
            active_child_mission_id=mission_id,
            active_plan_run_id=plan_run.id,
            last_metric=analyzer_payload["metric"],
            stop_reason="",
        ),
    )
    campaign_store.save_campaign(campaign)
    _broadcast_black_hole_campaign(campaign)
