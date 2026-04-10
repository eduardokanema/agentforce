"""Tests for TaskState deserialization behavior."""
from datetime import datetime, timezone

from agentforce.core.spec import TaskStatus, MissionSpec, TaskSpec, Caps
from agentforce.core.state import TaskState, MissionState, CapsViolation


def test_taskstate_from_dict_coerces_status_to_enum():
    task_state = TaskState.from_dict({"task_id": "task-1", "status": "pending"})

    assert task_state.status is TaskStatus.PENDING
    assert task_state.can_progress() is True


# ── Budget gate tests ──────────────────────────────────────────────────────────

def _make_state(max_cost_usd=None, task_costs=None):
    caps = Caps(max_cost_usd=max_cost_usd)
    spec = MissionSpec(name="test", goal="test", definition_of_done=[], tasks=[], caps=caps)
    state = MissionState(mission_id="m1", spec=spec)
    for i, cost in enumerate(task_costs or []):
        ts = TaskState(task_id=f"t{i}", cost_usd=cost)
        state.task_states[f"t{i}"] = ts
    return state


def test_check_caps_budget_gate_exceeded():
    state = _make_state(max_cost_usd=1.0, task_costs=[0.5, 0.6])  # 1.1 >= 1.0
    assert state.check_caps() == CapsViolation.BUDGET_EXCEEDED


def test_check_caps_budget_gate_exactly_at_cap():
    state = _make_state(max_cost_usd=1.0, task_costs=[0.5, 0.5])  # 1.0 >= 1.0
    assert state.check_caps() == CapsViolation.BUDGET_EXCEEDED


def test_check_caps_budget_gate_below_cap():
    state = _make_state(max_cost_usd=1.0, task_costs=[0.4, 0.5])  # 0.9 < 1.0
    assert state.check_caps() is None


def test_check_caps_budget_gate_skipped_when_zero():
    state = _make_state(max_cost_usd=0, task_costs=[100.0])  # 0 = unlimited
    assert state.check_caps() is None


def test_check_caps_budget_gate_skipped_when_none():
    state = _make_state(max_cost_usd=None, task_costs=[100.0])  # None = not set
    assert state.check_caps() is None


def test_check_caps_budget_sets_caps_hit():
    state = _make_state(max_cost_usd=1.0, task_costs=[1.5])
    state.check_caps()
    assert "budget" in state.caps_hit


def test_wall_time_uses_accumulated_active_tick_time_not_creation_time():
    state = _make_state()
    state.spec.caps.max_wall_time_minutes = 1
    state.started_at = "2020-01-01T00:00:00+00:00"

    assert state.wall_time_exceeded() is False


def test_wall_time_exceeded_after_accumulated_active_tick_time_reaches_cap():
    state = _make_state()
    state.spec.caps.max_wall_time_minutes = 1

    state.record_active_tick(datetime(2026, 4, 11, 0, 0, 0, tzinfo=timezone.utc))
    state.record_active_tick(datetime(2026, 4, 11, 0, 1, 0, tzinfo=timezone.utc))

    assert state.wall_time_exceeded() is True


def test_active_tick_time_persists_without_counting_resume_gap(tmp_path):
    state = _make_state()
    state.record_active_tick(datetime(2026, 4, 11, 0, 0, 0, tzinfo=timezone.utc))
    state.record_active_tick(datetime(2026, 4, 11, 0, 0, 30, tzinfo=timezone.utc))
    state_file = tmp_path / "state.json"

    state.save(state_file)
    loaded = MissionState.load(state_file)
    loaded.record_active_tick(datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc))

    assert loaded.active_wall_time_seconds == 30


def test_reset_active_tick_clock_prevents_paused_gap_from_counting():
    state = _make_state()
    state.record_active_tick(datetime(2026, 4, 11, 0, 0, 0, tzinfo=timezone.utc))
    state.record_active_tick(datetime(2026, 4, 11, 0, 0, 30, tzinfo=timezone.utc))

    state.reset_active_tick_clock()
    state.record_active_tick(datetime(2026, 4, 11, 12, 0, 0, tzinfo=timezone.utc))

    assert state.active_wall_time_seconds == 30
