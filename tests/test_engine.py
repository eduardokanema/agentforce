"""Focused tests for per-task worker model selection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentforce.core.engine import MissionEngine, ReviewerDelegation, WorkerDelegation
from agentforce.core.spec import MissionSpec, TaskSpec
from agentforce.memory import Memory


def make_engine(tmp_path, task: TaskSpec, worker_model: str = "mission-worker", reviewer_model: str = "mission-reviewer"):
    spec = MissionSpec(
        name="Test Mission",
        goal="Test goal",
        definition_of_done=["All tasks pass"],
        tasks=[task],
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
        TaskSpec(id="01", title="Task", description="Do it", model="claude-haiku-4-5"),
    )

    actions = engine.tick()

    worker_actions = [action for action in actions if isinstance(action, WorkerDelegation)]
    assert len(worker_actions) == 1
    assert worker_actions[0].model == "claude-haiku-4-5"


def test_task_model_uses_mission_default_when_not_set(tmp_path):
    engine = make_engine(
        tmp_path,
        TaskSpec(id="01", title="Task", description="Do it"),
        worker_model="mission-default-model",
    )

    actions = engine.tick()

    worker_actions = [action for action in actions if isinstance(action, WorkerDelegation)]
    assert len(worker_actions) == 1
    assert worker_actions[0].model == "mission-default-model"


def test_per_task_model_does_not_override_reviewer_model(tmp_path):
    engine = make_engine(
        tmp_path,
        TaskSpec(id="01", title="Task", description="Do it", model="claude-haiku-4-5"),
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
        TaskSpec(id="01", title="Task", description="Do it"),
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
