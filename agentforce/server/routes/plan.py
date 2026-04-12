"""Draft-oriented mission planner routes."""
from __future__ import annotations

import os
import threading
import uuid

import yaml

from agentforce.core.spec import Caps, MissionSpec
from agentforce.server.black_hole_runs import BlackHoleCampaignStore, is_terminal_campaign_status
from agentforce.server import state_io, ws
from agentforce.server.plan_drafts import MissionDraftV1, PlanDraftStore
from agentforce.server.plan_runs import PlanRunStore
from . import caps_config
from agentforce.server.planning_runtime import (
    _answered_repair_state,
    _planning_intervention_generation,
    _planning_retry_limit,
    _repair_state_from_validation,
    _reused_steps_for_retry,
    create_plan_run_for_draft,
    discover_preflight_questions,
    enqueue_black_hole_campaign,
)

# Set by the server when a MissionDaemon is active; None means ad-hoc threads.
_active_daemon = None
_SIMPLE_PLAN_KIND = "simple_plan"
_BLACK_HOLE_KIND = "black_hole"

BLACK_HOLE_DISABLED_RESPONSE = {
    "error": "black_hole_disabled",
    "message": "Black Hole is disabled in Labs settings",
}

BLACK_HOLE_ROUTE_INVENTORY: tuple[dict[str, str], ...] = (
    {
        "case_id": "draft_entry",
        "surface": "draft_create",
        "route": "POST /api/plan/drafts",
        "handler": "_create_draft",
        "reason": "Can mint draft_kind=black_hole from incoming validation.",
    },
    {
        "case_id": "draft_entry",
        "surface": "draft_update",
        "route": "PATCH /api/plan/drafts/{draft_id}/spec",
        "handler": "_patch_spec",
        "reason": "Preserves existing black-hole validation when draft spec changes.",
    },
    {
        "case_id": "draft_entry",
        "surface": "draft_import",
        "route": "POST /api/plan/drafts/{draft_id}/import-yaml",
        "handler": "_import_yaml",
        "reason": "Preserves existing black-hole validation when YAML replaces the draft spec.",
    },
    {
        "case_id": "draft_entry",
        "surface": "preflight_submit",
        "route": "POST /api/plan/drafts/{draft_id}/preflight",
        "handler": "_submit_preflight",
        "reason": "Advances black-hole drafts out of preflight without queuing a simple plan run.",
    },
    {
        "case_id": "repair_submission",
        "surface": "repair_submit",
        "route": "POST /api/plan/drafts/{draft_id}/repair",
        "handler": "_submit_repair",
        "reason": "Can resume black-hole campaigns through shared repair submission.",
    },
    {
        "case_id": "campaign_read",
        "surface": "black_hole_read",
        "route": "GET /api/plan/drafts/{draft_id}/black-hole",
        "handler": "_get_black_hole_campaign",
        "reason": "Reads black-hole draft config and campaign state.",
    },
    {
        "case_id": "launch",
        "surface": "black_hole_launch",
        "route": "POST /api/plan/drafts/{draft_id}/black-hole",
        "handler": "_start_black_hole_campaign",
        "reason": "Configures and launches the black-hole campaign for a draft.",
    },
    {
        "case_id": "pause_resume",
        "surface": "black_hole_pause",
        "route": "POST /api/plan/drafts/{draft_id}/black-hole/pause",
        "handler": "_pause_black_hole_campaign",
        "reason": "Pauses an in-flight black-hole campaign.",
    },
    {
        "case_id": "pause_resume",
        "surface": "black_hole_resume",
        "route": "POST /api/plan/drafts/{draft_id}/black-hole/resume",
        "handler": "_resume_black_hole_campaign",
        "reason": "Resumes a paused or waiting black-hole campaign.",
    },
    {
        "case_id": "stop",
        "surface": "black_hole_stop",
        "route": "POST /api/plan/drafts/{draft_id}/black-hole/stop",
        "handler": "_stop_black_hole_campaign",
        "reason": "Stops an active black-hole campaign.",
    },
    {
        "case_id": "repair_submission",
        "surface": "black_hole_repair_submit",
        "route": "POST /api/plan/drafts/{draft_id}/black-hole/repair",
        "handler": "_submit_repair",
        "reason": "Black-hole-specific repair submission path resumes pending campaign state.",
    },
)


def _black_hole_disabled_response() -> tuple[int, dict]:
    return 403, dict(BLACK_HOLE_DISABLED_RESPONSE)


def _black_hole_enabled() -> bool:
    return caps_config.black_hole_enabled()


def _guard_black_hole_access(validation: dict | None) -> tuple[int, dict] | None:
    if _draft_kind_from_validation(validation) == _BLACK_HOLE_KIND and not _black_hole_enabled():
        return _black_hole_disabled_response()
    return None


def _store() -> PlanDraftStore:
    return PlanDraftStore()


def _plan_store() -> PlanRunStore:
    return PlanRunStore()


def _black_hole_store() -> BlackHoleCampaignStore:
    return BlackHoleCampaignStore()


def _effective_daemon():
    if _active_daemon is not None:
        return _active_daemon
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


def _enqueue_plan_run(run_id: str) -> None:
    daemon = _effective_daemon()
    if daemon is not None:
        from agentforce.daemon import DaemonJob

        daemon.enqueue_job(DaemonJob(job_id=run_id, job_type="plan_run"))
        return

    def _runner():
        from agentforce.server.planning_runtime import run_plan_run

        try:
            run_plan_run(run_id)
        except Exception:
            pass

    threading.Thread(target=_runner, daemon=True, name=f"agentforce-plan-{run_id}").start()


def _draft_payload(draft: MissionDraftV1) -> dict:
    payload = draft.to_dict()
    payload["draft_kind"] = _draft_kind(draft)
    payload["plan_runs"] = [run.to_dict() for run in _plan_store().list_runs_for_draft(draft.id)]
    payload["plan_versions"] = [version.to_dict() for version in _plan_store().list_versions_for_draft(draft.id)]
    latest_version_id = str(payload.get("validation", {}).get("latest_plan_version_id") or "")
    if latest_version_id:
        version = _plan_store().load_version(latest_version_id)
        if version is not None:
            payload["planning_summary"] = {
                "latest_plan_version_id": version.id,
                "changelog": version.changelog,
                "validation": version.validation,
            }
    payload["preflight_status"] = str(payload.get("validation", {}).get("preflight_status") or "not_needed")
    payload["preflight_questions"] = list(payload.get("validation", {}).get("preflight_questions") or [])
    payload["preflight_answers"] = dict(payload.get("validation", {}).get("preflight_answers") or {})
    repair = _repair_state_from_validation(payload.get("validation", {}))
    payload["repair_status"] = str(repair.get("status") or "not_needed")
    payload["repair_questions"] = list(repair.get("questions") or [])
    payload["repair_answers"] = dict(repair.get("answers") or {})
    payload["repair_issues"] = list(repair.get("issues") or [])
    payload["repair_context"] = {
        "repair_round": int(repair.get("repair_round") or 0),
        "max_rounds": int(repair.get("max_rounds") or 2),
        "mode": repair.get("mode"),
        "loop_no": repair.get("loop_no"),
        "source_run_id": str(repair.get("source_run_id") or ""),
        "source_version_id": str(repair.get("source_version_id") or ""),
        "gate_reason": str(repair.get("gate_reason") or ""),
    }
    return payload


def _black_hole_payload(draft: MissionDraftV1) -> dict:
    summary = _black_hole_store().summarize(draft.id)
    return {
        "draft_id": draft.id,
        "draft_kind": _draft_kind(draft),
        "config": dict(draft.validation.get("black_hole_config") or {}) or None,
        "campaign": summary.get("campaign"),
        "loops": summary.get("loops") or [],
    }


def _draft_kind(draft: MissionDraftV1) -> str:
    return _draft_kind_from_validation(draft.validation)


def _draft_kind_from_validation(validation: dict | None) -> str:
    if isinstance(validation, dict):
        kind = str(validation.get("draft_kind") or "").strip()
        if kind == _BLACK_HOLE_KIND:
            return _BLACK_HOLE_KIND
        if kind == _SIMPLE_PLAN_KIND:
            return _SIMPLE_PLAN_KIND
        if isinstance(validation.get("black_hole_config"), dict) and validation.get("black_hole_config"):
            return _BLACK_HOLE_KIND
    return _SIMPLE_PLAN_KIND


def _bump_planning_retry_generation(validation: dict | None) -> dict:
    payload = dict(validation or {})
    payload["planning_retry_generation"] = _planning_intervention_generation(payload) + 1
    return payload


def _count_workspace_files(workspace_path: str) -> int:
    """Count all files (non-directories) recursively under workspace_path."""
    try:
        count = 0
        for _, _, files in os.walk(workspace_path):
            count += len(files)
        return count
    except OSError:
        return 0


def _caps_for_workspace(workspace_path: str) -> Caps:
    file_count = _count_workspace_files(workspace_path)
    if file_count < 50:
        return Caps(max_concurrent_workers=1)
    if file_count <= 200:
        return Caps(max_concurrent_workers=2)
    return Caps(max_concurrent_workers=3)


def _empty_draft_spec(prompt: str, workspace_paths: list[str] | None = None) -> dict:
    goal = prompt.strip()
    working_dir = workspace_paths[0] if workspace_paths else None
    caps = _caps_for_workspace(working_dir) if working_dir else Caps()
    return {
        "name": _title_from_prompt(goal),
        "goal": goal,
        "working_dir": working_dir,
        "definition_of_done": [],
        "tasks": [],
        "caps": caps.to_dict(),
    }


def _title_from_prompt(prompt: str) -> str:
    words = [part for part in prompt.split() if part]
    if not words:
        return "Untitled Mission"
    return " ".join(words[:6]).strip().title()


_DRAFT_INIT_MESSAGE = (
    "Draft initialized from your prompt. "
    "Here's the starting structure — tell me what to adjust."
)


def _build_preflight_validation(questions: list[dict]) -> dict:
    if not questions:
        return {
            "draft_kind": _SIMPLE_PLAN_KIND,
            "preflight_status": "not_needed",
            "preflight_questions": [],
            "preflight_answers": {},
        }
    return {
        "draft_kind": _SIMPLE_PLAN_KIND,
        "preflight_status": "pending",
        "preflight_questions": questions,
        "preflight_answers": {},
    }


def _preflight_prompt(draft: MissionDraftV1) -> str:
    questions = list(draft.validation.get("preflight_questions") or [])
    answers = dict(draft.validation.get("preflight_answers") or {})
    lines: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        answer = answers.get(str(question.get("id") or ""))
        if not isinstance(answer, dict):
            continue
        selected = str(answer.get("selected_option") or "").strip()
        custom = str(answer.get("custom_answer") or "").strip()
        rendered = custom or selected
        if rendered:
            lines.append(f"- {question.get('prompt')}: {rendered}")
    if not lines:
        return str(draft.draft_spec.get("goal") or "")
    return f"{draft.draft_spec.get('goal') or ''}\n\nPreflight clarifications:\n" + "\n".join(lines)


def _repair_prompt(draft: MissionDraftV1) -> str:
    repair = _repair_state_from_validation(draft.validation)
    questions = list(repair.get("questions") or [])
    answers = dict(repair.get("answers") or {})
    lines: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        answer = answers.get(str(question.get("id") or ""))
        if not isinstance(answer, dict):
            continue
        selected = str(answer.get("selected_option") or "").strip()
        custom = str(answer.get("custom_answer") or "").strip()
        rendered = custom or selected
        if rendered:
            lines.append(f"- {question.get('prompt')}: {rendered}")
    if not lines:
        return "Resume planning using the recorded repair guidance."
    return "Repair guidance:\n" + "\n".join(lines)


def _normalize_black_hole_config(draft: MissionDraftV1, body: dict) -> dict:
    existing = dict(draft.validation.get("black_hole_config") or {})
    raw = dict(body.get("config") or body or {})
    loop_limits = {
        **dict(existing.get("loop_limits") or {}),
        **dict(raw.get("loop_limits") or {}),
    }
    gate_policy = {
        **dict(existing.get("gate_policy") or {}),
        **dict(raw.get("gate_policy") or {}),
    }
    config = {
        "mode": "black_hole",
        "objective": str(raw.get("objective") or existing.get("objective") or draft.draft_spec.get("goal") or "").strip(),
        "analyzer": str(raw.get("analyzer") or existing.get("analyzer") or "python_fn_length").strip() or "python_fn_length",
        "scope": str(raw.get("scope") or existing.get("scope") or "repo").strip() or "repo",
        "global_acceptance": list(raw.get("global_acceptance") or existing.get("global_acceptance") or []),
        "loop_limits": {
            "max_loops": max(1, int(loop_limits.get("max_loops") or 8)),
            "max_no_progress": max(1, int(loop_limits.get("max_no_progress") or 2)),
            "function_line_limit": max(50, int(loop_limits.get("function_line_limit") or 300)),
        },
        "gate_policy": {
            "require_test_delta": gate_policy.get("require_test_delta", True) is not False,
            "public_surface_policy": str(gate_policy.get("public_surface_policy") or "justify").strip() or "justify",
        },
        "docs_manifest_path": str(raw.get("docs_manifest_path") or existing.get("docs_manifest_path") or "").strip() or None,
        "notes": str(raw.get("notes") or existing.get("notes") or "").strip(),
    }
    if not config["objective"]:
        raise ValueError("black hole objective is required")
    if config["analyzer"] == "docs_section_coverage" and not config["docs_manifest_path"]:
        raise ValueError("docs_section_coverage requires docs_manifest_path")
    return config


def _black_hole_profile_snapshot(draft: MissionDraftV1, config: dict) -> dict:
    return {
        **config,
        "profile_snapshot": {
            "planning_profiles": dict(draft.validation.get("planning_profiles") or {}),
            "execution_defaults": dict(draft.draft_spec.get("execution_defaults") or {}),
        },
    }


def _create_draft(body: dict) -> tuple[int, dict]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return 400, {"error": "prompt is required"}

    workspace_paths = list(body.get("workspace_paths") or body.get("workspaces") or [])
    validation = body.get("validation")
    if not isinstance(validation, dict):
        validation = {}
    draft_kind = _draft_kind_from_validation(validation)
    black_hole_error = _guard_black_hole_access(validation)
    if black_hole_error is not None:
        return black_hole_error
    validation = {
        **validation,
        "draft_kind": draft_kind,
        "planning_retry_generation": _planning_intervention_generation(validation),
    }

    draft = _store().create(
        str(uuid.uuid4()),
        status="draft",
        draft_spec=_empty_draft_spec(prompt, workspace_paths),
        turns=[{"role": "assistant", "content": _DRAFT_INIT_MESSAGE}],
        validation=validation,
        activity_log=[{"type": "draft_created", "prompt": prompt}],
        approved_models=list(body.get("approved_models") or []),
        workspace_paths=workspace_paths,
        companion_profile=dict(body.get("companion_profile") or {}),
        draft_notes=[],
    )
    questions = discover_preflight_questions(draft)
    if questions:
        preflight_validation = _build_preflight_validation(questions)
        preflight_validation = {
            **validation,
            **preflight_validation,
            "draft_kind": draft_kind,
        }
        save_result = _store().save(
            draft.copy_with(
                validation=preflight_validation,
                activity_log=list(draft.activity_log) + [{"type": "preflight_questions_generated", "count": len(questions)}],
            ),
            expected_revision=draft.revision,
        )
        if save_result.status == "saved" and save_result.draft is not None:
            draft = save_result.draft
    response = {"id": draft.id, "revision": draft.revision}
    if body.get("auto_start", True) is not False and draft.validation.get("preflight_status") != "pending":
        run = create_plan_run_for_draft(
            draft,
            trigger_kind="auto",
            trigger_message=prompt,
        )
        _enqueue_plan_run(run.id)
        response["plan_run_id"] = run.id
    response["requires_preflight"] = draft.validation.get("preflight_status") == "pending"
    ws.broadcast_draft_updated(draft.id, draft.status)
    state_io._broadcast_mission_list_refresh()
    return 200, response


def _load_draft(draft_id: str) -> MissionDraftV1 | None:
    return _store().load(draft_id)


def _load_draft_or_404(draft_id: str) -> tuple[MissionDraftV1 | None, tuple[int, dict] | None]:
    draft = _load_draft(draft_id)
    if draft is None:
        return None, (404, {"error": f"Draft {draft_id!r} not found"})
    return draft, None


def _patch_spec(draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error

    expected_revision = body.get("expected_revision")
    if not isinstance(expected_revision, int):
        return 400, {"error": "expected_revision is required"}

    draft_spec = body.get("draft_spec")
    if not isinstance(draft_spec, dict):
        return 400, {"error": "draft_spec must be an object"}
    validation = body.get("validation")
    if validation is not None and not isinstance(validation, dict):
        return 400, {"error": "validation must be an object"}

    updated = draft.copy_with(
        draft_spec=dict(draft_spec),
        validation=_bump_planning_retry_generation(dict(validation) if isinstance(validation, dict) else draft.validation),
        activity_log=list(draft.activity_log) + [{"type": "draft_spec_patched"}],
    )
    save_result = _store().save(updated, expected_revision=expected_revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }
    ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
    state_io._broadcast_mission_list_refresh()
    return 200, {"id": save_result.draft.id, "revision": save_result.draft.revision}


def _import_yaml(draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error

    expected_revision = body.get("expected_revision")
    if not isinstance(expected_revision, int):
        return 400, {"error": "expected_revision is required"}

    yaml_text = body.get("yaml")
    if not isinstance(yaml_text, str) or not yaml_text.strip():
        return 400, {"error": "yaml is required"}

    try:
        parsed = yaml.safe_load(yaml_text)
        mission_spec = MissionSpec.from_dict(parsed)
        issues = mission_spec.validate()
        if issues:
            return 400, {"error": f"invalid mission yaml: {issues[0]}"}
    except Exception as exc:
        return 400, {"error": f"invalid mission yaml: {str(exc)}"}

    updated = draft.copy_with(
        draft_spec=mission_spec.to_dict(),
        validation=_bump_planning_retry_generation(draft.validation),
        activity_log=list(draft.activity_log) + [{"type": "draft_yaml_imported"}],
    )
    save_result = _store().save(updated, expected_revision=expected_revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }
    ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
    state_io._broadcast_mission_list_refresh()
    return 200, {
        "id": save_result.draft.id,
        "revision": save_result.draft.revision,
        "draft_spec": save_result.draft.draft_spec,
    }


def _stream_turn(handler, draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    if _draft_kind(draft) != _SIMPLE_PLAN_KIND:
        return 409, {"error": "black hole drafts do not accept manual planning messages"}
    if str(draft.validation.get("preflight_status") or "") == "pending":
        return 409, {"error": "preflight questions must be answered before planning starts"}

    user_message = str(body.get("content") or body.get("message") or "").strip()
    if not user_message:
        return 400, {"error": "content is required"}

    updated = draft.copy_with(
        turns=list(draft.turns) + [{"role": "user", "content": user_message}],
        validation=_bump_planning_retry_generation(draft.validation),
        activity_log=list(draft.activity_log) + [{"type": "plan_follow_up_requested"}],
    )
    save_result = _store().save(updated, expected_revision=draft.revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }
    run = create_plan_run_for_draft(
        save_result.draft,
        trigger_kind="follow_up",
        trigger_message=user_message,
    )
    _enqueue_plan_run(run.id)
    ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
    state_io._broadcast_mission_list_refresh()
    return 200, {"draft_id": draft.id, "plan_run_id": run.id, "status": "queued"}


def _submit_preflight(draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error

    if str(draft.validation.get("preflight_status") or "") != "pending":
        return 409, {"error": "preflight is not pending for this draft"}

    skip = body.get("skip") is True
    raw_answers = body.get("answers") or {}
    if not skip and not isinstance(raw_answers, dict):
        return 400, {"error": "answers must be an object"}

    questions = list(draft.validation.get("preflight_questions") or [])
    normalized_answers: dict[str, dict] = {}
    summary_lines: list[str] = []
    if not skip:
        for question in questions:
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("id") or "")
            prompt = str(question.get("prompt") or "").strip()
            raw_answer = raw_answers.get(question_id)
            if not isinstance(raw_answer, dict):
                continue
            selected_option = str(raw_answer.get("selected_option") or "").strip()
            custom_answer = str(raw_answer.get("custom_answer") or "").strip()
            if not selected_option and not custom_answer:
                continue
            normalized_answers[question_id] = {
                "selected_option": selected_option,
                "custom_answer": custom_answer,
            }
            summary_lines.append(f"- {prompt}: {custom_answer or selected_option}")

    updated = draft.copy_with(
        validation={
            **_bump_planning_retry_generation(draft.validation),
            "draft_kind": _draft_kind(draft),
            "preflight_status": "skipped" if skip else "answered",
            "preflight_answers": normalized_answers,
        },
        turns=list(draft.turns) + (
            [{"role": "user", "content": "Preflight skipped. Proceed with the best available assumptions."}]
            if skip
            else ([{"role": "user", "content": "Preflight answers:\n" + "\n".join(summary_lines)}] if summary_lines else [])
        ),
        activity_log=list(draft.activity_log) + [{"type": "preflight_submitted", "skip": skip}],
    )
    save_result = _store().save(updated, expected_revision=draft.revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }

    if _draft_kind(save_result.draft) == _BLACK_HOLE_KIND:
        ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
        state_io._broadcast_mission_list_refresh()
        return 200, {
            "draft_id": save_result.draft.id,
            "revision": save_result.draft.revision,
            "status": "ready",
        }

    run = create_plan_run_for_draft(
        save_result.draft,
        trigger_kind="auto",
        trigger_message=_preflight_prompt(save_result.draft),
    )
    _enqueue_plan_run(run.id)
    ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
    state_io._broadcast_mission_list_refresh()
    return 200, {
        "draft_id": save_result.draft.id,
        "revision": save_result.draft.revision,
        "plan_run_id": run.id,
        "status": "queued",
    }


def _submit_repair(draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error

    expected_revision = body.get("expected_revision")
    if not isinstance(expected_revision, int):
        return 400, {"error": "expected_revision is required"}

    repair = _repair_state_from_validation(draft.validation)
    if str(repair.get("status") or "") != "pending":
        return 409, {"error": "repair is not pending for this draft"}

    raw_answers = body.get("answers") or {}
    if not isinstance(raw_answers, dict):
        return 400, {"error": "answers must be an object"}

    if body.get("loop_no") is not None and int(body.get("loop_no")) != int(repair.get("loop_no") or 0):
        return 409, {"error": "repair loop does not match the current pending state"}
    if body.get("repair_round") is not None and int(body.get("repair_round")) != int(repair.get("repair_round") or 0):
        return 409, {"error": "repair round does not match the current pending state"}
    source_version_id = str(body.get("source_version_id") or "").strip()
    if source_version_id and source_version_id != str(repair.get("source_version_id") or ""):
        return 409, {"error": "repair source version does not match the current pending state"}

    normalized_answers: dict[str, dict[str, str]] = {}
    summary_lines: list[str] = []
    for question in list(repair.get("questions") or []):
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id") or "")
        answer = raw_answers.get(question_id)
        if not isinstance(answer, dict):
            continue
        selected_option = str(answer.get("selected_option") or "").strip()
        custom_answer = str(answer.get("custom_answer") or "").strip()
        if not selected_option and not custom_answer:
            continue
        normalized_answers[question_id] = {
            "selected_option": selected_option,
            "custom_answer": custom_answer,
        }
        summary_lines.append(f"- {question.get('prompt')}: {custom_answer or selected_option}")

    updated = draft.copy_with(
        validation={
            **_bump_planning_retry_generation(draft.validation),
            "repair": _answered_repair_state(repair, normalized_answers),
        },
        turns=list(draft.turns) + (
            [{"role": "user", "content": "Repair answers:\n" + "\n".join(summary_lines)}] if summary_lines else []
        ),
        activity_log=list(draft.activity_log) + [{"type": "repair_submitted", "repair_round": int(repair.get("repair_round") or 0)}],
    )
    save_result = _store().save(updated, expected_revision=expected_revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }

    if _draft_kind(save_result.draft) == _BLACK_HOLE_KIND:
        campaign = _black_hole_store().latest_for_draft(draft_id)
        if campaign is None:
            return 404, {"error": "black-hole campaign not found"}
        enqueue_black_hole_campaign(campaign.id, draft_id=draft_id)
        ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
        state_io._broadcast_mission_list_refresh()
        return 200, {
            "draft_id": save_result.draft.id,
            "revision": save_result.draft.revision,
            "status": "queued",
            "campaign_id": campaign.id,
        }

    run = create_plan_run_for_draft(
        save_result.draft,
        trigger_kind="repair_answers",
        trigger_message=_repair_prompt(save_result.draft),
    )
    _enqueue_plan_run(run.id)
    ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
    state_io._broadcast_mission_list_refresh()
    return 200, {
        "draft_id": save_result.draft.id,
        "revision": save_result.draft.revision,
        "plan_run_id": run.id,
        "status": "queued",
    }


def _start_draft(draft_id: str) -> tuple[int, dict]:
    from agentforce.server.routes.missions import _make_mission_state_from_spec

    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error

    if draft.status != "draft":
        return 409, {"error": f"Draft status is {draft.status!r}, expected 'draft'"}
    if _draft_kind(draft) != _SIMPLE_PLAN_KIND:
        return 409, {"error": "black hole drafts cannot launch missions directly"}
    if str(draft.validation.get("preflight_status") or "") == "pending":
        return 409, {"error": "preflight questions must be answered before launch"}

    try:
        spec = MissionSpec.from_dict(draft.draft_spec)
        issues = spec.validate(stage="launch")
    except Exception as exc:
        return 422, {"errors": [str(exc)]}

    if issues:
        return 422, {"errors": issues}

    # Crash recovery: if mission_id was already assigned and state file exists, skip re-creation.
    existing_mid = draft.validation.get("mission_id")
    s_dir = state_io.get_state_dir()
    if existing_mid and (s_dir / f"{existing_mid}.json").exists():
        _finalize_draft(draft, existing_mid)
        _launch_mission(existing_mid)
        return 200, {"mission_id": existing_mid, "draft_id": draft_id, "status": "started"}

    # Build mission state.
    state = _make_mission_state_from_spec(spec)
    mission_id = state.mission_id
    latest_plan_version_id = str(draft.validation.get("latest_plan_version_id") or "")
    latest_plan_run_id = str(draft.validation.get("latest_plan_run_id") or "")
    state.source_plan_version_id = latest_plan_version_id or None
    state.source_plan_run_id = latest_plan_run_id or None
    state.source_draft_id = draft.id

    # Checkpoint: record mission_id in draft before saving state (crash safety).
    checkpoint = draft.copy_with(
        validation={**draft.validation, "mission_id": mission_id},
        activity_log=list(draft.activity_log) + [{"type": "start_initiated", "mission_id": mission_id}],
    )
    save1 = _store().save(checkpoint, expected_revision=draft.revision)
    if save1.status != "saved" or save1.draft is None:
        return 409, {"error": "draft conflict during start"}

    # Save mission state to disk.
    state.log_event("mission_started", details="Started via plan draft")
    s_dir.mkdir(parents=True, exist_ok=True)
    state.save(s_dir / f"{mission_id}.json")
    if latest_plan_version_id:
        from agentforce.server.planning_runtime import mark_version_launched

        mark_version_launched(latest_plan_version_id, mission_id)

    # Finalize draft.
    _finalize_draft(save1.draft, mission_id)

    _launch_mission(mission_id)
    return 200, {"mission_id": mission_id, "draft_id": draft_id, "status": "started"}


def _start_black_hole_campaign(draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error
    if _draft_kind(draft) != _BLACK_HOLE_KIND:
        return 409, {"error": "draft is not a black hole plan"}
    if draft.status != "draft":
        return 409, {"error": f"Draft status is {draft.status!r}, expected 'draft'"}
    if str(draft.validation.get("preflight_status") or "") == "pending":
        return 409, {"error": "preflight questions must be answered before black-hole launch"}

    expected_revision = body.get("expected_revision")
    if expected_revision is not None and not isinstance(expected_revision, int):
        return 400, {"error": "expected_revision must be an integer when provided"}

    try:
        config = _normalize_black_hole_config(draft, body)
    except ValueError as exc:
        return 400, {"error": str(exc)}

    snapshot = _black_hole_profile_snapshot(draft, config)
    updated = draft.copy_with(
        validation={**draft.validation, "draft_kind": _BLACK_HOLE_KIND, "black_hole_config": config},
        activity_log=list(draft.activity_log) + [{"type": "black_hole_configured"}],
    )
    revision = draft.revision if expected_revision is None else expected_revision
    save_result = _store().save(updated, expected_revision=revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }

    try:
        campaign = _black_hole_store().create_campaign(
            str(uuid.uuid4()),
            draft_id=draft_id,
            max_loops=int(config["loop_limits"]["max_loops"]),
            max_no_progress=int(config["loop_limits"]["max_no_progress"]),
            config_snapshot=snapshot,
        )
    except ValueError as exc:
        return 409, {"error": str(exc)}

    enqueue_black_hole_campaign(campaign.id, draft_id=draft_id)
    ws.broadcast({"type": "black_hole_campaign_updated", "draft_id": draft_id, "campaign": campaign.to_dict()})
    ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
    state_io._broadcast_mission_list_refresh()
    return 200, {
        "draft_id": draft_id,
        "campaign_id": campaign.id,
        "status": campaign.status,
        "revision": save_result.draft.revision,
    }


def _get_black_hole_campaign(draft_id: str) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error
    if _draft_kind(draft) != _BLACK_HOLE_KIND:
        return 409, {"error": "draft is not a black hole plan"}
    return 200, _black_hole_payload(draft)


def _pause_black_hole_campaign(draft_id: str) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error
    if _draft_kind(draft) != _BLACK_HOLE_KIND:
        return 409, {"error": "draft is not a black hole plan"}
    campaign = _black_hole_store().latest_for_draft(draft_id)
    if campaign is None:
        return 404, {"error": "black-hole campaign not found"}
    if is_terminal_campaign_status(campaign.status):
        return 409, {"error": f"campaign already ended with status {campaign.status!r}"}
    campaign = campaign.copy_with(status="paused", stop_reason="Paused by operator.")
    _black_hole_store().save_campaign(campaign)
    ws.broadcast({"type": "black_hole_campaign_updated", "draft_id": draft_id, "campaign": campaign.to_dict()})
    return 200, {"draft_id": draft_id, "campaign_id": campaign.id, "status": campaign.status}


def _resume_black_hole_campaign(draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error
    if _draft_kind(draft) != _BLACK_HOLE_KIND:
        return 409, {"error": "draft is not a black hole plan"}
    campaign = _black_hole_store().latest_for_draft(draft_id)
    if campaign is None:
        return 404, {"error": "black-hole campaign not found"}
    if is_terminal_campaign_status(campaign.status):
        return 409, {"error": f"campaign already ended with status {campaign.status!r}"}
    try:
        config = _normalize_black_hole_config(draft, body) if body else dict(draft.validation.get("black_hole_config") or {})
    except ValueError as exc:
        return 400, {"error": str(exc)}
    updated_draft = draft
    if config:
        updated_draft = draft.copy_with(
            validation={**draft.validation, "draft_kind": _BLACK_HOLE_KIND, "black_hole_config": config},
            activity_log=list(draft.activity_log) + [{"type": "black_hole_resumed"}],
        )
        save_result = _store().save(updated_draft, expected_revision=draft.revision)
        if save_result.status == "saved" and save_result.draft is not None:
            updated_draft = save_result.draft
    campaign = campaign.copy_with(
        status="evaluating_workspace",
        stop_reason="",
        config_snapshot=_black_hole_profile_snapshot(updated_draft, dict(updated_draft.validation.get("black_hole_config") or {})),
    )
    _black_hole_store().save_campaign(campaign)
    ws.broadcast({"type": "black_hole_campaign_updated", "draft_id": draft_id, "campaign": campaign.to_dict()})
    enqueue_black_hole_campaign(campaign.id, draft_id=draft_id)
    return 200, {"draft_id": draft_id, "campaign_id": campaign.id, "status": campaign.status}


def _stop_black_hole_campaign(draft_id: str) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error
    black_hole_error = _guard_black_hole_access(draft.validation)
    if black_hole_error is not None:
        return black_hole_error
    if _draft_kind(draft) != _BLACK_HOLE_KIND:
        return 409, {"error": "draft is not a black hole plan"}
    campaign = _black_hole_store().latest_for_draft(draft_id)
    if campaign is None:
        return 404, {"error": "black-hole campaign not found"}
    if is_terminal_campaign_status(campaign.status):
        return 200, {"draft_id": draft_id, "campaign_id": campaign.id, "status": campaign.status}
    campaign = campaign.copy_with(status="cancelled", stop_reason="Stopped by operator.")
    _black_hole_store().save_campaign(campaign)
    ws.broadcast({"type": "black_hole_campaign_updated", "draft_id": draft_id, "campaign": campaign.to_dict()})
    return 200, {"draft_id": draft_id, "campaign_id": campaign.id, "status": campaign.status}


def _retry_plan_run(run_id: str) -> tuple[int, dict]:
    run = _plan_store().load_run(run_id)
    if run is None:
        return 404, {"error": f"Plan run {run_id!r} not found"}

    draft, error = _load_draft_or_404(run.draft_id)
    if error is not None:
        return error

    if run.status not in {"failed", "stale"}:
        return 409, {"error": f"Plan run {run_id!r} is not retryable"}

    if run.status == "stale":
        retry = create_plan_run_for_draft(
            draft,
            trigger_kind="retry",
            trigger_message=f"Retry of run {run_id}",
        )
        _enqueue_plan_run(retry.id)
        return 200, {"draft_id": draft.id, "plan_run_id": retry.id, "status": "queued"}

    current_generation = _planning_intervention_generation(draft.validation)
    retry_limit = _planning_retry_limit()
    next_attempt = int(run.retry_attempt or 0) + 1
    if run.intervention_generation == current_generation and next_attempt > retry_limit:
        locked = run.copy_with(retry_limit=retry_limit, retry_locked=True)
        _plan_store().save_run(locked)
        return 409, {
            "error": "Planning retry limit reached. Provide new guidance or edit the draft before retrying again.",
            "retry_limit": retry_limit,
            "retry_attempt": int(run.retry_attempt or 0),
            "failed_step": run.failed_step or run.current_step,
            "intervention_required": True,
        }

    retry = create_plan_run_for_draft(
        draft,
        trigger_kind="retry",
        trigger_message=f"Retry of run {run_id}",
        retry_group_id=run.retry_group_id or run.id,
        retry_of_run_id=run.id,
        retry_attempt=1 if run.intervention_generation != current_generation else next_attempt,
        retry_limit=retry_limit,
        retry_locked=False,
        failed_step=run.failed_step or run.current_step,
        intervention_generation=current_generation,
        resume_state=dict(run.resume_state or {}),
        reused_steps=_reused_steps_for_retry(run),
    )
    _enqueue_plan_run(retry.id)
    return 200, {"draft_id": draft.id, "plan_run_id": retry.id, "status": "queued"}


def _delete_draft(draft_id: str) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error

    if draft.status != "draft":
        return 409, {"error": f"Draft status is {draft.status!r}, expected 'draft'"}

    deleted = _store().delete(draft_id)
    if not deleted:
        return 404, {"error": f"Draft {draft_id!r} not found"}

    ws.broadcast_draft_updated(draft_id, "discarded")
    state_io._broadcast_mission_list_refresh()
    return 200, {"id": draft_id, "status": "discarded"}


def _finalize_draft(draft: MissionDraftV1, mission_id: str) -> None:
    finalized = draft.copy_with(
        status="finalized",
        activity_log=list(draft.activity_log) + [{"type": "draft_finalized", "mission_id": mission_id}],
    )
    save_result = _store().save(finalized, expected_revision=draft.revision)
    if save_result.status == "saved" and save_result.draft is not None:
        ws.broadcast_draft_updated(save_result.draft.id, save_result.draft.status)
        state_io._broadcast_mission_list_refresh()


def _launch_mission(mission_id: str) -> None:
    daemon = _effective_daemon()
    if daemon is not None:
        daemon.enqueue(mission_id)
        return

    def _runner():
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
        name=f"agentforce-mission-{mission_id}",
    ).start()


def get(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 3 and parts[1] == "plan" and parts[2] == "drafts":
        include_terminal = query.get("include_terminal", "false").lower() == "true"
        drafts = _store().list_all(include_terminal=include_terminal)
        return 200, [
            {
                "id": d.id,
                "name": d.name,
                "goal": d.goal,
                "status": d.status,
                "draft_kind": _draft_kind(d),
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in drafts
        ]
    if len(parts) == 4 and parts[1] == "plan" and parts[2] == "drafts":
        draft, error = _load_draft_or_404(parts[3])
        if error is not None:
            return error
        black_hole_error = _guard_black_hole_access(draft.validation)
        if black_hole_error is not None:
            return black_hole_error
        return 200, _draft_payload(draft)
    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "runs":
        draft, error = _load_draft_or_404(parts[3])
        if error is not None:
            return error
        black_hole_error = _guard_black_hole_access(draft.validation)
        if black_hole_error is not None:
            return black_hole_error
        return 200, {"draft_id": draft.id, "plan_runs": [run.to_dict() for run in _plan_store().list_runs_for_draft(draft.id)]}
    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "black-hole":
        return _get_black_hole_campaign(parts[3])
    if len(parts) == 4 and parts[1] == "plan" and parts[2] == "runs":
        run = _plan_store().load_run(parts[3])
        if run is None:
            return 404, {"error": f"Plan run {parts[3]!r} not found"}
        return 200, run.to_dict()
    if len(parts) == 4 and parts[1] == "plan" and parts[2] == "versions":
        version = _plan_store().load_version(parts[3])
        if version is None:
            return 404, {"error": f"Plan version {parts[3]!r} not found"}
        return 200, version.to_dict()
    return 404, {"error": "Not found"}


def post(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 3 and parts[1] == "plan" and parts[2] == "drafts":
        return _create_draft(handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "black-hole":
        return _start_black_hole_campaign(parts[3], handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "messages":
        return _stream_turn(handler, parts[3], handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "preflight":
        return _submit_preflight(parts[3], handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "repair":
        return _submit_repair(parts[3], handler._read_json_body())

    if len(parts) == 6 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "black-hole" and parts[5] == "repair":
        return _submit_repair(parts[3], handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "import-yaml":
        return _import_yaml(parts[3], handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "start":
        return _start_draft(parts[3])
    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "runs" and parts[4] == "retry":
        return _retry_plan_run(parts[3])
    if len(parts) == 6 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "black-hole" and parts[5] == "pause":
        return _pause_black_hole_campaign(parts[3])
    if len(parts) == 6 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "black-hole" and parts[5] == "resume":
        return _resume_black_hole_campaign(parts[3], handler._read_json_body())
    if len(parts) == 6 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "black-hole" and parts[5] == "stop":
        return _stop_black_hole_campaign(parts[3])

    return 404, {"error": "Not found"}


def patch(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "spec":
        return _patch_spec(parts[3], handler._read_json_body())
    return 404, {"error": "Not found"}


def delete(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 4 and parts[1] == "plan" and parts[2] == "drafts":
        return _delete_draft(parts[3])
    return 404, {"error": "Not found"}
