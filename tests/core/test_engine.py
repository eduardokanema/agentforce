"""Tests for the engine state machine."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.core.spec import MissionSpec, TaskSpec, Caps, TDDSpec
from agentforce.core.engine import MissionEngine, WorkerDelegation, ReviewerDelegation
from agentforce.memory import Memory


def make_engine(tmp_path, tasks=None, caps=None):
    """Helper to create an engine."""
    if tasks is None:
        tasks = [
            TaskSpec(id="01", title="Task A", description="Do A", max_retries=2),
            TaskSpec(id="02", title="Task B", description="Do B", max_retries=2),
        ]
    if caps is None:
        caps = Caps(max_retries_global=5, max_concurrent_workers=2, max_wall_time_minutes=60)

    spec = MissionSpec(
        name="Test Mission",
        goal="Test goal",
        definition_of_done=["All tasks pass"],
        tasks=tasks,
        caps=caps,
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return MissionEngine(
        spec=spec,
        state_dir=state_dir,
        memory=Memory(memory_dir),
    )


class TestEngineInitialization:
    def test_creates_state_file(self, tmp_path):
        engine = make_engine(tmp_path)
        assert engine.state_file.exists()

    def test_all_tasks_pending(self, tmp_path):
        engine = make_engine(tmp_path)
        assert not engine.is_done()
        assert not engine.is_failed()
        assert len(engine.state.task_states) == 2
        for ts in engine.state.task_states.values():
            assert ts.status == "pending"

    def test_dispatchable_has_no_deps(self, tmp_path):
        engine = make_engine(tmp_path)
        dispatchable = engine.state.dispatchable_tasks()
        assert set(dispatchable) == {"01", "02"}  # Both have no deps

    def test_dispatchable_respects_deps(self, tmp_path):
        tasks = [
            TaskSpec(id="01", title="Task A", description="A", max_retries=2),
            TaskSpec(id="02", title="Task B", description="B", dependencies=["01"], max_retries=2),
        ]
        engine = make_engine(tmp_path, tasks=tasks)
        dispatchable = engine.state.dispatchable_tasks()
        assert dispatchable == ["01"]


class TestTick:
    def test_dispatches_workers(self, tmp_path):
        engine = make_engine(tmp_path)
        actions = engine.tick()
        worker_actions = [a for a in actions if isinstance(a, WorkerDelegation)]
        assert len(worker_actions) == 2  # Both tasks dispatched (max_workers=2)

    def test_respects_worker_limit(self, tmp_path):
        caps = Caps(max_concurrent_workers=1, max_retries_global=10)
        tasks = [
            TaskSpec(id=f"{i:02d}", title=f"Task {i}", description=f"Do {i}", max_retries=2)
            for i in range(1, 6)
        ]
        engine = make_engine(tmp_path, tasks=tasks, caps=caps)
        actions = engine.tick()
        worker_actions = [a for a in actions if isinstance(a, WorkerDelegation)]
        assert len(worker_actions) == 1

    def test_stops_when_done(self, tmp_path):
        engine = make_engine(tmp_path)
        # Complete both tasks manually
        for tid in ["01", "02"]:
            engine.apply_worker_result(tid, True, "Done")
            engine.apply_reviewer_result(tid, True, "Approved")
        
        assert engine.is_done()
        actions = engine.tick()
        assert len(actions) == 0


class TestWorkerLifecycle:
    def test_successful_worker(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        ts = engine.state.get_task("01")
        assert ts.status == "in_progress"
        
        engine.apply_worker_result("01", True, "All done")
        ts = engine.state.get_task("01")
        assert ts.status == "completed"
        assert ts.worker_output == "All done"

    def test_failed_worker_retries(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        
        engine.apply_worker_result("01", False, error="Network error")
        ts = engine.state.get_task("01")
        assert ts.status == "retry"
        assert ts.retries == 1

    def test_max_retries_marks_failed(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        
        # First failure
        engine.apply_worker_result("01", False, error="Fail 1")
        assert engine.state.get_task("01").status == "retry"
        
        # Tick again to re-dispatch
        engine.tick()
        
        # Second failure (max_retries=2)
        engine.apply_worker_result("01", False, error="Fail 2")
        assert engine.state.get_task("01").status == "failed"


class TestReviewerLifecycle:
    def test_approved_review(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        engine.apply_worker_result("01", True, "Implemented")
        
        actions = engine.tick()
        review_actions = [a for a in actions if isinstance(a, ReviewerDelegation)]
        assert len(review_actions) == 1
        
        engine.apply_reviewer_result("01", True, "Looks good", 9)
        assert engine.state.get_task("01").status == "review_approved"

    def test_rejected_review_retries(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        engine.apply_worker_result("01", True, "Done but messy")
        
        engine.tick()
        engine.apply_reviewer_result("01", False, "Bad code quality", score=2, blocking_issues=[])
        
        ts = engine.state.get_task("01")
        assert ts.status == "retry"
        assert ts.retries == 1
        assert "bad code quality" in ts.review_feedback.lower()

    def test_blocking_issues_flag_human(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        engine.apply_worker_result("01", True, "Done")
        
        engine.tick()
        engine.apply_reviewer_result(
            "01", False, "Spec is ambiguous", score=3,
            blocking_issues=["Requirement contradicts API spec"]
        )
        
        ts = engine.state.get_task("01")
        assert ts.needs_human_attention()


class TestDependencyOrdering:
    def test_dependent_task_blocked(self, tmp_path):
        tasks = [
            TaskSpec(id="01", title="Base", description="Base", max_retries=2),
            TaskSpec(id="02", title="Dependent", description="Dep", dependencies=["01"], max_retries=2),
        ]
        engine = make_engine(tmp_path, tasks=tasks)
        engine.tick()  # Dispatch task 01
        
        # Task 02 should NOT be dispatchedable yet
        assert "02" not in engine.state.dispatchable_tasks()
        
        # Complete task 01
        engine.apply_worker_result("01", True, "Base done")
        engine.apply_reviewer_result("01", True, "OK")
        
        # Now task 02 should be dispatchable
        actions = engine.tick()
        worker_actions = [a for a in actions if isinstance(a, WorkerDelegation)]
        assert len(worker_actions) == 1
        assert worker_actions[0].task_id == "02"


class TestCaps:
    def test_wall_time_exceeded(self, tmp_path):
        caps = Caps(max_wall_time_minutes=1)
        engine = make_engine(tmp_path, caps=caps)
        engine.state.started_at = "2020-01-01T00:00:00+00:00"
        engine._save()
        
        cap = engine._check_caps()
        assert cap is not None
        assert "wall_time" in engine.state.caps_hit


class TestEventLog:
    def test_logs_are_recorded(self, tmp_path):
        engine = make_engine(tmp_path)
        # Initial tick adds dispatch events
        engine.tick()
        events = engine.event_log_tail()
        assert len(events) >= 2  # At least 2 dispatch events

    def test_tail_limit(self, tmp_path):
        engine = make_engine(tmp_path, tasks=[
            TaskSpec(id=f"task{i:02d}", title=f"T{i}", description=f"Do {i}", max_retries=2)
            for i in range(30)
        ], caps=Caps(max_concurrent_workers=30))
        engine.tick()
        tail = engine.event_log_tail(3)
        assert len(tail) <= 3


class TestReport:
    def test_report_format(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        report = engine.report()
        assert "Test Mission" in report
        assert "Task A" in report
        assert "Task B" in report
