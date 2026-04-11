"""Task API routes."""
from __future__ import annotations

import json as _jsonlib
from pathlib import Path

from agentforce.core.engine import MissionEngine
from agentforce.memory import Memory
from agentforce.streaming import StreamRecorder, load_stream_events

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

    if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task" and parts[5] == "stream_events":
        mission_id, task_id = parts[2], parts[4]
        state = _load_state(mission_id)
        if not state:
            return 404, {"error": f"Mission {mission_id!r} not found"}
        task_state = state.task_states.get(task_id)
        if not task_state:
            return 404, {"error": f"Task {task_id!r} not found in mission {mission_id!r}"}
        raw_after_seq = query.get("after_seq", "0")
        try:
            after_seq = int(raw_after_seq or 0)
        except (TypeError, ValueError):
            return 400, {"error": "after_seq must be an integer"}
        events = load_stream_events(
            mission_id,
            task_id,
            after_seq=after_seq,
            stream_dir=state_io.get_agentforce_home() / "streams",
        )
        done = state_io._task_status_value(task_state) in {"completed", "review_approved", "review_rejected", "failed", "needs_human", "blocked"}
        last_seq = int(events[-1]["seq"]) if events else after_seq
        return 200, {"events": events, "done": done, "last_seq": last_seq}

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

    from agentforce.server import handler as _handler
    active_daemon = getattr(_handler, "_daemon", None)
    if active_daemon is not None:
        active_daemon.enqueue(mission_id)

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
    recorder = StreamRecorder(mission_id, task_id, provider="operator", stream_dir=state_io.get_agentforce_home() / "streams")
    recorder.user_instruction(message)
    return 200, {"delivered": True}


def _post_task_resolve(mission_id: str, task_id: str, body: dict) -> tuple[int, dict]:
    engine = _load_engine(mission_id)
    if not engine:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    task_state = engine.state.task_states.get(task_id)
    if not task_state:
        return 404, {"error": f"Task {task_id!r} not found in mission {mission_id!r}"}
    if state_io._task_status_value(task_state) != "needs_human":
        return 409, {"error": "task not needs_human"}
    if body.get("failed"):
        engine.resolve_as_failed(task_id)
        _broadcast_mission_refresh(engine.state)
        return 200, {"failed": True}

    choice_id = body.get("choice_id")
    message = body.get("message", "")
    if not isinstance(message, str):
        return 400, {"error": "message is required"}
    if not isinstance(choice_id, str) and getattr(task_state, "human_intervention_kind", "") == "destructive_action":
        return 400, {"error": "choice_id is required"}
    if not isinstance(choice_id, str):
        choice_id = None
    if not message and choice_id is None:
        return 400, {"error": "message is required"}

    try:
        engine.apply_human_resolution(task_id, message, choice_id=choice_id)
    except ValueError as exc:
        return 400, {"error": str(exc)}

    from agentforce.server import handler as _handler
    active_daemon = getattr(_handler, "_daemon", None)
    if active_daemon is not None:
        active_daemon.enqueue(mission_id)

    _broadcast_mission_refresh(engine.state)
    payload = {"resolved": True}
    if choice_id:
        payload["choice_id"] = choice_id
    return 200, payload


def _post_task_change_model(mission_id: str, task_id: str, body: dict) -> tuple[int, dict]:
    legacy_model = body.get("model")
    worker_model = body.get("worker_model")
    reviewer_model = body.get("reviewer_model")
    worker_agent = body.get("worker_agent")
    reviewer_agent = body.get("reviewer_agent")
    worker_thinking = body.get("worker_thinking")
    reviewer_thinking = body.get("reviewer_thinking")
    if not isinstance(worker_model, str) and isinstance(legacy_model, str):
        worker_model = legacy_model
    if not isinstance(worker_model, str):
        worker_model = None
    if not isinstance(reviewer_model, str):
        reviewer_model = None
    if not isinstance(worker_agent, str):
        worker_agent = None
    if not isinstance(reviewer_agent, str):
        reviewer_agent = None
    if not isinstance(worker_thinking, str):
        worker_thinking = None
    if not isinstance(reviewer_thinking, str):
        reviewer_thinking = None
    worker_model = worker_model.strip() if worker_model else None
    reviewer_model = reviewer_model.strip() if reviewer_model else None
    worker_agent = worker_agent.strip() if worker_agent else None
    reviewer_agent = reviewer_agent.strip() if reviewer_agent else None
    worker_thinking = worker_thinking.strip() if worker_thinking else None
    reviewer_thinking = reviewer_thinking.strip() if reviewer_thinking else None
    if not worker_model and not reviewer_model and not worker_agent and not reviewer_agent and not worker_thinking and not reviewer_thinking:
        return 400, {"error": "worker_model, reviewer_model, worker_agent, reviewer_agent, worker_thinking, or reviewer_thinking is required"}

    engine = _load_engine(mission_id)
    if not engine:
        return 404, {"error": f"Mission {mission_id!r} not found"}
    if not engine.state.task_states.get(task_id):
        return 404, {"error": f"Task {task_id!r} not found in mission {mission_id!r}"}

    try:
        retried = engine.change_models(
            task_id,
            worker_model=worker_model,
            reviewer_model=reviewer_model,
            worker_agent=worker_agent,
            reviewer_agent=reviewer_agent,
            worker_thinking=worker_thinking,
            reviewer_thinking=reviewer_thinking,
        )
    except ValueError as exc:
        return 409, {"error": str(exc)}

    if retried:
        from agentforce.server import handler as _handler
        active_daemon = getattr(_handler, "_daemon", None)
        if active_daemon is not None:
            active_daemon.enqueue(mission_id)

    state = _load_state(mission_id)
    if state:
        _broadcast_mission_refresh(state)

    return 200, {
        "worker_agent": worker_agent,
        "worker_model": worker_model,
        "worker_thinking": worker_thinking,
        "reviewer_agent": reviewer_agent,
        "reviewer_model": reviewer_model,
        "reviewer_thinking": reviewer_thinking,
        "retried": retried,
    }


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
        if parts[5] == "change_model":
            return _post_task_change_model(parts[2], parts[4], body)
    return 404, {"error": "Not found"}
