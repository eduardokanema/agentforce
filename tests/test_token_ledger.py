"""Tests for token usage tracking and state token fields."""
import json

from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.core.state import MissionState, TaskState


def _mission_spec() -> MissionSpec:
    return MissionSpec(
        name="token-mission",
        goal="Track token usage",
        definition_of_done=["Done"],
        tasks=[TaskSpec(id="task-1", title="Task 1", description="First task")],
        caps=Caps(
            max_concurrent_workers=1,
            max_retries_global=1,
            max_wall_time_minutes=10,
            max_human_interventions=1,
        ),
    )


def test_token_ledger_parse_usage_line_and_totals():
    from agentforce.core.token_ledger import TokenLedger

    ledger = TokenLedger()

    assert ledger.parse_usage_line("not json") is None
    assert ledger.parse_usage_line(json.dumps({"type": "info", "message": "skip"})) is None

    usage = ledger.parse_usage_line(
        json.dumps({"type": "usage", "input_tokens": 12, "output_tokens": 34, "cost_usd": 0.56})
    )

    assert usage == {"input_tokens": 12, "output_tokens": 34, "cost_usd": 0.56}

    ledger.add("task-1", 12, 34, 0.56)
    ledger.add("task-2", 5, 6, 0.1)

    assert ledger.task_totals("task-1") == {"tokens_in": 12, "tokens_out": 34, "cost_usd": 0.56}
    assert ledger.task_totals("missing") == {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    assert ledger.mission_totals() == {"tokens_in": 17, "tokens_out": 40, "cost_usd": 0.66}

    ledger.reset_task("task-1")
    assert ledger.task_totals("task-1") == {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}


def test_task_and_mission_state_token_roundtrip(tmp_path):
    state = MissionState(
        mission_id="mission-1",
        spec=_mission_spec(),
    )
    state.task_states["task-1"] = TaskState(
        task_id="task-1",
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.25,
    )
    state.tokens_in = 10
    state.tokens_out = 20
    state.cost_usd = 0.25

    payload = state.to_dict()
    assert payload["task_states"]["task-1"]["tokens_in"] == 10
    assert payload["task_states"]["task-1"]["tokens_out"] == 20
    assert payload["task_states"]["task-1"]["cost_usd"] == 0.25
    assert payload["tokens_in"] == 10
    assert payload["tokens_out"] == 20
    assert payload["cost_usd"] == 0.25
    summary = state.to_summary_dict()
    assert summary["tokens_in"] == 10
    assert summary["tokens_out"] == 20
    assert summary["cost_usd"] == 0.25

    restored = MissionState.from_dict(payload)
    assert restored.task_states["task-1"].tokens_in == 10
    assert restored.task_states["task-1"].tokens_out == 20
    assert restored.task_states["task-1"].cost_usd == 0.25
    assert restored.tokens_in == 10
    assert restored.tokens_out == 20
    assert restored.cost_usd == 0.25

    old_payload = {
        "mission_id": "mission-old",
        "spec": _mission_spec().to_dict(),
        "task_states": {
            "task-1": {"task_id": "task-1"},
        },
        "event_log": [],
    }
    old_state = MissionState.from_dict(old_payload)
    assert old_state.tokens_in == 0
    assert old_state.tokens_out == 0
    assert old_state.cost_usd == 0.0
    assert old_state.task_states["task-1"].tokens_in == 0
    assert old_state.task_states["task-1"].tokens_out == 0
    assert old_state.task_states["task-1"].cost_usd == 0.0

    old_path = tmp_path / "mission.json"
    old_path.write_text(json.dumps(old_payload))
    loaded = MissionState.load(old_path)
    assert loaded.tokens_in == 0
    assert loaded.tokens_out == 0
    assert loaded.cost_usd == 0.0
