"""Task API routes."""
from __future__ import annotations

import json as _jsonlib
from pathlib import Path

from agentforce.core.engine import MissionEngine
from agentforce.memory import Memory

from .. import state_io
from .providers import _now_iso


def _inject_path(handler, mission_id: str, task_id: str) -> Path:
    return handler.config.state_dir / mission_id / f"{task_id}.inject"


def _load_state(mission_id: str):
    return state_io._load_state(mission_id)


def _state_path(mission_id: str) -> Path:
    return state_io._state_path(mission_id)


def _broadcast_mission_refresh(state) -> None:
    state_io._broadcast_mission_refresh(state)


def _load_engine(mission_id: str) -> MissionEngine | None:
    state_path = _state_path(mission_id)
    if not state_path.exists():
        return None
    memory = Memory(state_io.get_agentforce_home() / "memory")
    return MissionEngine.load(state_path, memory)


def get(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
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


def _post_task_stop(mission_id: str, task_id: str) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    task_state = state.task_states.get(task_id)
    if not task_state:
        return 404, {"error": f"Task {task_id!r} not found in mission {mission_id!r}"}
    task_state.status = "blocked"
    state.save(_state_path(mission_id))
    _broadcast_mission_refresh(state)
    return 200, {"stopped": True}


def _post_task_retry(mission_id: str, task_id: str) -> tuple[int, dict]:
    engine = _load_engine(mission_id)
    if not engine:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    if not engine.state.task_states.get(task_id):
        return 404, {"error": f"Task {task_id!r} not found in mission {mission_id!r}"}
    try:
        engine.manual_retry(task_id)
    except ValueError as exc:
        return 409, {"error": str(exc)}
    return 200, {"retrying": True}


def _post_task_inject(handler, mission_id: str, task_id: str, body: dict) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    task_state = state.task_states.get(task_id)
    if not task_state:
        return 404, {"error": f"Task {task_id!r} not found in mission {mission_id!r}"}
    if state_io._task_status_value(task_state) != "in_progress":
        return 409, {"error": "task not in_progress"}
    message = body.get("message")
    if not isinstance(message, str):
        return 400, {"error": "message is required"}
    inject_path = _inject_path(handler, mission_id, task_id)
    inject_path.parent.mkdir(parents=True, exist_ok=True)
    with open(inject_path, "w", encoding="utf-8") as fh:
        _jsonlib.dump({"message": message, "timestamp": _now_iso()}, fh)
    return 200, {"delivered": True}


def _post_task_resolve(mission_id: str, task_id: str, body: dict) -> tuple[int, dict]:
    state = _load_state(mission_id)
    if not state:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    task_state = state.task_states.get(task_id)
    if not task_state:
        return 404, {"error": f"Task {task_id!r} not found in mission {mission_id!r}"}
    if state_io._task_status_value(task_state) != "needs_human":
        return 409, {"error": "task not needs_human"}
    if body.get("failed"):
        task_state.status = "failed"
        task_state.human_intervention_needed = False
        task_state.human_intervention_message = ""
        task_state.bump()
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
        return 200, {"failed": True}
    message = body.get("message")
    if not isinstance(message, str):
        return 400, {"error": "message is required"}
    task_state.status = "pending"
    task_state.worker_output = (task_state.worker_output + "\n" + message).strip()
    state.save(_state_path(mission_id))
    _broadcast_mission_refresh(state)
    return 200, {"resolved": True}


def post(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    body = handler._read_json_body()
    if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task":
        if parts[5] == "stop":
            return _post_task_stop(parts[2], parts[4])
        if parts[5] == "retry":
            return _post_task_retry(parts[2], parts[4])
        if parts[5] == "inject":
            return _post_task_inject(handler, parts[2], parts[4], body)
        if parts[5] == "resolve":
            return _post_task_resolve(parts[2], parts[4], body)
    return 404, {"error": "Not found"}
