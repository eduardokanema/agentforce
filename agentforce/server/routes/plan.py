"""Draft-oriented mission planner routes."""
from __future__ import annotations

import uuid

import yaml

from agentforce.core.spec import Caps, MissionSpec
from agentforce.server import planner_adapter
from agentforce.server.plan_drafts import MissionDraftV1, PlanDraftStore


def _store() -> PlanDraftStore:
    return PlanDraftStore()


def _empty_draft_spec(prompt: str) -> dict:
    goal = prompt.strip()
    return {
        "name": _title_from_prompt(goal),
        "goal": goal,
        "definition_of_done": [],
        "tasks": [],
        "caps": Caps().to_dict(),
    }


def _title_from_prompt(prompt: str) -> str:
    words = [part for part in prompt.split() if part]
    if not words:
        return "Untitled Mission"
    return " ".join(words[:6]).strip().title()


def _create_draft(body: dict) -> tuple[int, dict]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return 400, {"error": "prompt is required"}

    draft = _store().create(
        str(uuid.uuid4()),
        status="draft",
        draft_spec=_empty_draft_spec(prompt),
        turns=[],
        validation={},
        activity_log=[{"type": "draft_created", "prompt": prompt}],
        approved_models=list(body.get("approved_models") or []),
        workspace_paths=list(body.get("workspace_paths") or body.get("workspaces") or []),
        companion_profile=dict(body.get("companion_profile") or {}),
        draft_notes=[],
    )
    return 200, {"id": draft.id, "revision": draft.revision}


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

    expected_revision = body.get("expected_revision")
    if not isinstance(expected_revision, int):
        return 400, {"error": "expected_revision is required"}

    draft_spec = body.get("draft_spec")
    if not isinstance(draft_spec, dict):
        return 400, {"error": "draft_spec must be an object"}

    updated = draft.copy_with(
        draft_spec=dict(draft_spec),
        activity_log=list(draft.activity_log) + [{"type": "draft_spec_patched"}],
    )
    save_result = _store().save(updated, expected_revision=expected_revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }
    return 200, {"id": save_result.draft.id, "revision": save_result.draft.revision}


def _import_yaml(draft_id: str, body: dict) -> tuple[int, dict]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error

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
        activity_log=list(draft.activity_log) + [{"type": "draft_yaml_imported"}],
    )
    save_result = _store().save(updated, expected_revision=expected_revision)
    if save_result.status != "saved" or save_result.draft is None:
        current = save_result.draft
        return 409, {
            "error": "draft revision conflict",
            "revision": current.revision if current is not None else None,
        }
    return 200, {
        "id": save_result.draft.id,
        "revision": save_result.draft.revision,
        "draft_spec": save_result.draft.draft_spec,
    }


def _stream_turn(handler, draft_id: str, body: dict) -> tuple[int, None]:
    draft, error = _load_draft_or_404(draft_id)
    if error is not None:
        return error[0], error[1]

    user_message = str(body.get("content") or body.get("message") or "").strip()
    if not user_message:
        return 400, {"error": "content is required"}

    adapter = planner_adapter.get_planner_adapter()
    turn_result = adapter.plan_turn(draft.to_dict(), user_message)
    status_events = [event for event in turn_result.events if not event.content]
    assistant_events = [event for event in turn_result.events if event.content]

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()

    for payload in planner_adapter.iter_sse_payloads(status_events):
        handler.wfile.write(payload.encode("utf-8"))
        handler.wfile.flush()

    _persist_planner_turn(draft, user_message, turn_result)

    for payload in planner_adapter.iter_sse_payloads(
        assistant_events or [planner_adapter.PlannerEvent(phase="planning", status="completed", content=turn_result.assistant_message)]
    ):
        handler.wfile.write(payload.encode("utf-8"))
        handler.wfile.flush()

    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()
    return 200, None


def _persist_planner_turn(
    base_draft: MissionDraftV1,
    user_message: str,
    turn_result: planner_adapter.PlannerTurnResult,
) -> MissionDraftV1:
    current_draft = base_draft
    store = _store()
    for _ in range(3):
        merged_spec = _merge_draft_spec(
            base_draft.draft_spec,
            current_draft.draft_spec,
            turn_result.draft_spec,
        )
        updated = current_draft.copy_with(
            draft_spec=merged_spec,
            turns=list(current_draft.turns) + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": turn_result.assistant_message},
            ],
            activity_log=list(current_draft.activity_log) + [{"type": "planner_turn_completed"}],
        )
        save_result = store.save(updated, expected_revision=current_draft.revision)
        if save_result.status == "saved" and save_result.draft is not None:
            return save_result.draft
        if save_result.draft is None:
            break
        current_draft = save_result.draft
    raise RuntimeError("failed to persist planner draft checkpoint")


def _merge_draft_spec(base: dict, current: dict, planned: dict) -> dict:
    keys = set(base) | set(current) | set(planned)
    merged: dict = {}
    for key in keys:
        base_value = base.get(key)
        current_value = current.get(key)
        planned_value = planned.get(key)
        if isinstance(base_value, dict) and isinstance(current_value, dict) and isinstance(planned_value, dict):
            merged[key] = _merge_draft_spec(base_value, current_value, planned_value)
            continue
        if planned_value != base_value:
            merged[key] = planned_value
            continue
        merged[key] = current_value
    return merged


def get(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 4 and parts[1] == "plan" and parts[2] == "drafts":
        draft, error = _load_draft_or_404(parts[3])
        if error is not None:
            return error
        return 200, draft.to_dict()
    return 404, {"error": "Not found"}


def post(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 3 and parts[1] == "plan" and parts[2] == "drafts":
        return _create_draft(handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "messages":
        return _stream_turn(handler, parts[3], handler._read_json_body())

    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "import-yaml":
        return _import_yaml(parts[3], handler._read_json_body())

    return 404, {"error": "Not found"}


def patch(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 5 and parts[1] == "plan" and parts[2] == "drafts" and parts[4] == "spec":
        return _patch_spec(parts[3], handler._read_json_body())
    return 404, {"error": "Not found"}
