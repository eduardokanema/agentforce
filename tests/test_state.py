"""Tests for TaskState deserialization behavior."""
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
