"""Test MissionState summary/detail execution metadata."""
import pytest
from agentforce.core.state import MissionState, TaskState
from agentforce.core.spec import MissionSpec, TaskSpec, Caps, TaskStatus, ExecutionConfig, ExecutionProfile


def test_to_summary_dict_basic():
    # Create a minimal spec
    spec = MissionSpec(
        name="test-mission",
        goal="Test mission",
        definition_of_done=["Done"],
        tasks=[
            TaskSpec(id="task1", title="Task 1", description="First task"),
            TaskSpec(id="task2", title="Task 2", description="Second task"),
        ],
        caps=Caps(
            max_concurrent_workers=2,
            max_retries_global=3,
            max_wall_time_minutes=60,
            max_human_interventions=5,
        ),
    )
    
    # Create mission state
    state = MissionState(
        mission_id="test-123",
        spec=spec,
        worker_agent="opencode",
        worker_model="test-model",
    )
    
    # Add task states
    state.task_states["task1"] = TaskState(task_id="task1", status=TaskStatus.REVIEW_APPROVED)
    state.task_states["task2"] = TaskState(task_id="task2", status=TaskStatus.IN_PROGRESS)
    
    # Call to_summary_dict
    summary = state.to_summary_dict()
    
    # Check all required fields exist
    assert "mission_id" in summary
    assert "name" in summary
    assert "status" in summary
    assert "done_tasks" in summary
    assert "total_tasks" in summary
    assert "pct" in summary
    assert "duration" in summary
    assert "worker_agent" in summary
    assert "worker_model" in summary
    assert "started_at" in summary
    
    # Check values
    assert summary["mission_id"] == "test-123"
    assert summary["name"] == "test-mission"
    assert summary["worker_agent"] == "opencode"
    assert summary["worker_model"] == "test-model"
    assert summary["total_tasks"] == 2
    assert summary["done_tasks"] == 1
    assert summary["pct"] == 50  # 1/2 * 100
    
    # Status should be 'active' (not done, not failed, not needs_human)
    assert summary["status"] == "active"
    
    # Duration should be a string
    assert isinstance(summary["duration"], str)
    assert len(summary["duration"]) > 0


def test_to_summary_dict_complete():
    spec = MissionSpec(
        name="complete-mission",
        goal="Complete mission",
        definition_of_done=["Done"],
        tasks=[
            TaskSpec(id="task1", title="Task 1", description="First task"),
        ],
        caps=Caps(
            max_concurrent_workers=2,
            max_retries_global=3,
            max_wall_time_minutes=60,
            max_human_interventions=5,
        ),
    )
    
    state = MissionState(
        mission_id="complete-123",
        spec=spec,
        worker_agent="claude",
        worker_model="claude-model",
    )
    
    # All tasks review_approved -> complete
    state.task_states["task1"] = TaskState(task_id="task1", status=TaskStatus.REVIEW_APPROVED)
    
    summary = state.to_summary_dict()
    
    assert summary["status"] == "complete"
    assert summary["done_tasks"] == 1
    assert summary["total_tasks"] == 1
    assert summary["pct"] == 100


def test_to_summary_dict_failed():
    spec = MissionSpec(
        name="failed-mission",
        goal="Failed mission",
        definition_of_done=["Done"],
        tasks=[
            TaskSpec(id="task1", title="Task 1", description="First task"),
        ],
        caps=Caps(
            max_concurrent_workers=2,
            max_retries_global=3,
            max_wall_time_minutes=60,
            max_human_interventions=5,
        ),
    )
    
    state = MissionState(
        mission_id="failed-123",
        spec=spec,
        worker_agent="opencode",
        worker_model="test-model",
    )
    
    # One task failed -> mission failed
    state.task_states["task1"] = TaskState(task_id="task1", status=TaskStatus.FAILED)
    
    summary = state.to_summary_dict()
    
    assert summary["status"] == "failed"
    assert summary["done_tasks"] == 0
    assert summary["total_tasks"] == 1
    assert summary["pct"] == 0


def test_to_summary_dict_needs_human():
    spec = MissionSpec(
        name="needs-human-mission",
        goal="Needs human mission",
        definition_of_done=["Done"],
        tasks=[
            TaskSpec(id="task1", title="Task 1", description="First task"),
        ],
        caps=Caps(
            max_concurrent_workers=2,
            max_retries_global=3,
            max_wall_time_minutes=60,
            max_human_interventions=5,
        ),
    )
    
    state = MissionState(
        mission_id="human-123",
        spec=spec,
        worker_agent="claude",
        worker_model="claude-model",
    )
    
    # Task needs human attention
    ts = TaskState(task_id="task1", status=TaskStatus.NEEDS_HUMAN)
    state.task_states["task1"] = ts
    
    summary = state.to_summary_dict()
    
    assert summary["status"] == "needs_human"
    assert summary["done_tasks"] == 0
    assert summary["total_tasks"] == 1
    assert summary["pct"] == 0


def test_to_summary_dict_pct_calculation():
    spec = MissionSpec(
        name="pct-mission",
        goal="PCT calculation mission",
        definition_of_done=["Done"],
        tasks=[
            TaskSpec(id="task1", title="Task 1", description="First task"),
            TaskSpec(id="task2", title="Task 2", description="Second task"),
            TaskSpec(id="task3", title="Task 3", description="Third task"),
            TaskSpec(id="task4", title="Task 4", description="Fourth task"),
        ],
        caps=Caps(
            max_concurrent_workers=2,
            max_retries_global=3,
            max_wall_time_minutes=60,
            max_human_interventions=5,
        ),
    )
    
    state = MissionState(
        mission_id="pct-123",
        spec=spec,
        worker_agent="opencode",
        worker_model="test-model",
    )
    
    # 2 out of 4 tasks approved
    state.task_states["task1"] = TaskState(task_id="task1", status=TaskStatus.REVIEW_APPROVED)
    state.task_states["task2"] = TaskState(task_id="task2", status=TaskStatus.REVIEW_APPROVED)
    state.task_states["task3"] = TaskState(task_id="task3", status=TaskStatus.PENDING)
    state.task_states["task4"] = TaskState(task_id="task4", status=TaskStatus.IN_PROGRESS)
    
    summary = state.to_summary_dict()
    
    assert summary["done_tasks"] == 2
    assert summary["total_tasks"] == 4
    assert summary["pct"] == 50  # 2/4 * 100 = 50


def test_summary_and_detail_include_execution_metadata_for_mixed_profiles(monkeypatch):
    from agentforce.server import model_catalog
    from agentforce.server.model_catalog import ProfileNormalizationResult
    monkeypatch.setattr(
        model_catalog,
        "normalize_execution_profile",
        lambda profile: ProfileNormalizationResult(profile=profile, valid=True, repaired=False)
    )
    spec = MissionSpec(
        name="mixed-execution",
        goal="Mixed execution metadata mission",
        definition_of_done=["Done"],
        execution_defaults=ExecutionConfig(
            worker=ExecutionProfile(agent="codex", model="worker-default", thinking="medium"),
            reviewer=ExecutionProfile(agent="codex", model="reviewer-default", thinking="low"),
        ),
        tasks=[
            TaskSpec(
                id="task1",
                title="Task 1",
                description="First task",
                execution=ExecutionConfig(
                    worker=ExecutionProfile(model="worker-override"),
                ),
            ),
            TaskSpec(
                id="task2",
                title="Task 2",
                description="Second task",
                execution=ExecutionConfig(
                    reviewer=ExecutionProfile(model="reviewer-override", thinking="high"),
                ),
            ),
        ],
        caps=Caps(
            max_concurrent_workers=2,
            max_retries_global=3,
            max_wall_time_minutes=60,
            max_human_interventions=5,
        ),
    )

    state = MissionState(
        mission_id="mixed-123",
        spec=spec,
        execution_defaults=ExecutionConfig(
            worker=ExecutionProfile(agent="codex", model="worker-launch", thinking="medium"),
            reviewer=ExecutionProfile(agent="codex", model="reviewer-launch", thinking="low"),
        ),
    )
    state.task_states["task1"] = TaskState(task_id="task1", status=TaskStatus.REVIEW_APPROVED)
    state.task_states["task2"] = TaskState(task_id="task2", status=TaskStatus.IN_PROGRESS)

    summary = state.to_summary_dict()
    detail = state.to_dict()

    assert summary["execution"]["defaults"]["worker"]["model"] == "worker-launch"
    assert summary["execution"]["defaults"]["reviewer"]["model"] == "reviewer-launch"
    assert set(summary["execution"]["mixed_roles"]) == {"worker", "reviewer"}
    assert summary["execution"]["task_overrides"] == {"worker": 1, "reviewer": 1}

    assert detail["execution"]["tasks"]["task1"]["worker"]["model"] == "worker-override"
    assert detail["execution"]["tasks"]["task1"]["reviewer"]["model"] == "reviewer-launch"
    assert detail["execution"]["tasks"]["task2"]["worker"]["model"] == "worker-launch"
    assert detail["execution"]["tasks"]["task2"]["reviewer"]["model"] == "reviewer-override"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
