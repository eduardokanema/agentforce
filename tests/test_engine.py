"""Focused tests for per-task worker model selection."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentforce.core.engine import MissionEngine, ReviewerDelegation, WorkerDelegation
from agentforce.core.spec import Caps, ExecutionConfig, ExecutionProfile, MissionSpec, TaskSpec
from agentforce.memory import Memory


def make_engine(tmp_path, task: TaskSpec, worker_model: str = "mission-worker", reviewer_model: str = "mission-reviewer"):
    spec = MissionSpec(
        name="Test Mission",
        goal="Test goal",
        definition_of_done=["All tasks pass"],
        tasks=[task],
        execution_defaults=ExecutionConfig(
            worker=ExecutionProfile(agent="codex"),
            reviewer=ExecutionProfile(agent="codex"),
        ),
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return MissionEngine(
        spec=spec,
        state_dir=state_dir,
        memory=Memory(memory_dir),
        worker_model=worker_model,
        reviewer_model=reviewer_model,
    )


def test_task_model_from_dict_reads_explicit_value():
    task = TaskSpec.from_dict({"id": "1", "title": "t", "description": "d", "model": "haiku"})
    assert task.model == "haiku"


def test_task_model_from_dict_defaults_to_none():
    task = TaskSpec.from_dict({"id": "1", "title": "t", "description": "d"})
    assert task.model is None


def test_per_task_model_overrides_worker_model(tmp_path):
    engine = make_engine(
        tmp_path,
        TaskSpec(id="01", title="Task", description="Do it", model="claude-haiku-4-5", acceptance_criteria=["assert result == 'ok'"]),
    )

    actions = engine.tick()

    worker_actions = [action for action in actions if isinstance(action, WorkerDelegation)]
    assert len(worker_actions) == 1
    assert worker_actions[0].model == "claude-haiku-4-5"


def test_task_model_uses_mission_default_when_not_set(tmp_path):
    engine = make_engine(
        tmp_path,
        TaskSpec(id="01", title="Task", description="Do it", acceptance_criteria=["assert result == 'ok'"]),
        worker_model="mission-default-model",
    )

    actions = engine.tick()

    worker_actions = [action for action in actions if isinstance(action, WorkerDelegation)]
    assert len(worker_actions) == 1
    assert worker_actions[0].model == "mission-default-model"


def test_per_task_model_does_not_override_reviewer_model(tmp_path):
    engine = make_engine(
        tmp_path,
        TaskSpec(id="01", title="Task", description="Do it", model="claude-haiku-4-5", acceptance_criteria=["assert result == 'ok'"]),
        reviewer_model="mission-reviewer-default",
    )

    engine.tick()
    engine.apply_worker_result("01", True, "done")
    actions = engine.tick()

    review_actions = [action for action in actions if isinstance(action, ReviewerDelegation)]
    assert len(review_actions) == 1
    assert review_actions[0].model == "mission-reviewer-default"


def test_outcome_memory_truncation_uses_2000_chars(tmp_path):
    engine = make_engine(
        tmp_path,
        TaskSpec(id="01", title="Task", description="Do it", acceptance_criteria=["assert result == 'ok'"]),
    )

    engine.tick()
    engine.apply_worker_result("01", True, "done")

    feedback = "x" * 2500

    engine.apply_reviewer_result("01", True, feedback)

    stored_feedback = engine.memory.project_get(
        engine.state.mission_id,
        "task_01_outcome",
    )

    assert stored_feedback == feedback[:2000]


def test_launch_rejects_worker_execution_without_model(tmp_path):
    spec = MissionSpec.from_dict({
        "name": "Execution Validation",
        "goal": "Reject invalid execution profiles at launch",
        "definition_of_done": ["pytest tests/ passes with exit code 0"],
        "tasks": [{
            "id": "01",
            "title": "Task",
            "description": "Do it",
            "acceptance_criteria": ['response includes "ok"'],
            "execution": {
                "worker": {
                    "agent": "codex",
                }
            },
        }],
    })
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="worker execution"):
        MissionEngine(
            spec=spec,
            state_dir=state_dir,
            memory=Memory(memory_dir),
        )


def test_worker_and_reviewer_delegations_carry_resolved_execution_settings(tmp_path):
    spec = MissionSpec(
        name="Resolved execution",
        goal="Resolve role settings",
        definition_of_done=["All tasks pass"],
        execution_defaults=ExecutionConfig(
            worker=ExecutionProfile(agent="mission-worker-agent", model="mission-worker-model", thinking="medium"),
            reviewer=ExecutionProfile(agent="mission-reviewer-agent", model="mission-reviewer-model", thinking="low"),
        ),
        tasks=[
            TaskSpec(
                id="01",
                title="Task",
                description="Do it",
                acceptance_criteria=["done"],
                execution=ExecutionConfig(
                    worker=ExecutionProfile(model="task-worker-model", thinking="high"),
                    reviewer=ExecutionProfile(agent="task-reviewer-agent"),
                ),
            )
        ],
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    engine = MissionEngine(spec=spec, state_dir=state_dir, memory=Memory(memory_dir))

    actions = engine.tick()
    worker = next(action for action in actions if isinstance(action, WorkerDelegation))
    assert worker.agent == "mission-worker-agent"
    assert worker.model == "task-worker-model"
    assert worker.thinking == "high"

    engine.apply_worker_result("01", True, "done")
    review_actions = engine.tick()
    reviewer = next(action for action in review_actions if isinstance(action, ReviewerDelegation))
    assert reviewer.agent == "task-reviewer-agent"
    assert reviewer.model == "mission-reviewer-model"
    assert reviewer.thinking == "low"


def test_resume_uses_persisted_execution_settings_not_new_launch_defaults(tmp_path):
    spec = MissionSpec(
        name="Resume execution",
        goal="Persist launch defaults",
        definition_of_done=["All tasks pass"],
        tasks=[
            TaskSpec(id="01", title="Task", description="Do it", acceptance_criteria=["done"]),
        ],
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    engine = MissionEngine(
        spec=spec,
        state_dir=state_dir,
        memory=Memory(memory_dir),
        worker_model="stored-worker-model",
        reviewer_model="stored-reviewer-model",
    )

    state_file = engine.state_file
    resumed = MissionEngine.load(state_file, Memory(memory_dir))

    actions = resumed.tick()
    worker = next(action for action in actions if isinstance(action, WorkerDelegation))
    assert worker.model == "stored-worker-model"
    assert resumed.state.execution_defaults.worker is not None
    assert resumed.state.execution_defaults.worker.model == "stored-worker-model"

    resumed.apply_worker_result("01", True, "done")
    review_actions = resumed.tick()
    reviewer = next(action for action in review_actions if isinstance(action, ReviewerDelegation))
    assert reviewer.model == "stored-reviewer-model"


def test_launch_defaults_fill_explicit_worker_runtime_fallback_fields(tmp_path):
    spec = MissionSpec(
        name="Fallback execution",
        goal="Fill fallback values",
        definition_of_done=["All tasks pass"],
        tasks=[
            TaskSpec(id="01", title="Task", description="Do it", acceptance_criteria=["done"]),
        ],
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    engine = MissionEngine(
        spec=spec,
        state_dir=state_dir,
        memory=Memory(memory_dir),
        worker_model="cli-worker-model",
    )

    actions = engine.tick()
    worker = next(action for action in actions if isinstance(action, WorkerDelegation))

    assert worker.agent == "opencode"
    assert worker.model == "cli-worker-model"
    assert worker.thinking == "high"


def test_runtime_fallback_defaults_match_detected_agent(tmp_path, monkeypatch):
    spec = MissionSpec(
        name="Detected fallback execution",
        goal="Use a provider-compatible fallback",
        definition_of_done=["All tasks pass"],
        tasks=[
            TaskSpec(id="01", title="Task", description="Do it", acceptance_criteria=["done"]),
        ],
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("agentforce.core.engine.detect_runtime_agent", lambda: "gemini")

    engine = MissionEngine(
        spec=spec,
        state_dir=state_dir,
        memory=Memory(memory_dir),
    )

    assert engine.state.execution_defaults.worker is not None
    assert engine.state.execution_defaults.worker.agent == "gemini"
    assert engine.state.execution_defaults.worker.model == "auto"
    assert engine.state.execution_defaults.reviewer is not None
    assert engine.state.execution_defaults.reviewer.agent == "gemini"
    assert engine.state.execution_defaults.reviewer.model == "auto"


def test_change_default_models_pins_started_tasks_and_updates_pending_defaults(tmp_path):
    spec = MissionSpec(
        name="Default model update",
        goal="Update pending task defaults",
        definition_of_done=["All tasks pass"],
        caps=Caps(max_concurrent_workers=1),
        tasks=[
            TaskSpec(id="01", title="Started", description="Already started", acceptance_criteria=["done"]),
            TaskSpec(id="02", title="Pending", description="Not started", acceptance_criteria=["done"]),
        ],
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    engine = MissionEngine(
        spec=spec,
        state_dir=state_dir,
        memory=Memory(memory_dir),
        worker_model="old-worker",
        reviewer_model="old-reviewer",
    )

    engine.tick()
    engine.state.get_task("02").status = "pending"
    engine.state.get_task("02").started_at = None
    engine._save()

    result = engine.change_default_models(
        worker_agent="codex",
        worker_model="new-worker",
        reviewer_agent="claude",
        reviewer_model="new-reviewer",
    )

    assert result["pinned_tasks"] == 1
    assert engine.state.execution_defaults.worker.agent == "codex"
    assert engine.state.execution_defaults.worker.model == "new-worker"
    assert engine.state.execution_defaults.reviewer.agent == "claude"
    assert engine.state.execution_defaults.reviewer.model == "new-reviewer"
    started_task = engine.spec.tasks[0]
    pending_task = engine.spec.tasks[1]
    assert started_task.execution.worker.model == "old-worker"
    assert started_task.execution.reviewer.model == "old-reviewer"
    assert pending_task.execution.worker is None
    assert pending_task.execution.reviewer is None


def test_change_models_updates_worker_agent_with_model_for_started_task(tmp_path):
    task = TaskSpec(id="01", title="Task", description="Do it", acceptance_criteria=["done"])
    engine = make_engine(tmp_path, task, worker_model="old-worker", reviewer_model="old-reviewer")
    engine.state.execution_defaults.worker.agent = "gemini"
    engine.spec.execution_defaults.worker.agent = "gemini"

    engine.tick()

    retried = engine.change_models("01", worker_agent="codex", worker_model="gpt-5.4")

    assert retried is True
    assert task.execution.worker.agent == "codex"
    assert task.execution.worker.model == "gpt-5.4"
    assert engine.state.get_task("01").status.value == "pending"
