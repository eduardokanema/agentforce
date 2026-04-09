"""Tests for TaskState deserialization behavior."""
from agentforce.core.spec import TaskStatus
from agentforce.core.state import TaskState


def test_taskstate_from_dict_coerces_status_to_enum():
    task_state = TaskState.from_dict({"task_id": "task-1", "status": "pending"})

    assert task_state.status is TaskStatus.PENDING
    assert task_state.can_progress() is True
