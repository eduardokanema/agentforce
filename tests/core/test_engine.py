"""Tests for the engine state machine."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.core.spec import MissionSpec, TaskSpec, Caps, TDDSpec
from agentforce.core.engine import MissionEngine, WorkerDelegation, ReviewerDelegation
from agentforce.memory import Memory


def make_engine(tmp_path, tasks=None, caps=None):
    """Helper to create an engine."""
    if tasks is None:
        tasks = [
            TaskSpec(id="01", title="Task A", description="Do A", max_retries=2, acceptance_criteria=["assert result == 'ok'"]),
            TaskSpec(id="02", title="Task B", description="Do B", max_retries=2, acceptance_criteria=["assert result == 'ok'"]),
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
            TaskSpec(id="01", title="Task A", description="A", max_retries=2, acceptance_criteria=["assert result == 'ok'"]),
            TaskSpec(id="02", title="Task B", description="B", dependencies=["01"], max_retries=2, acceptance_criteria=["assert result == 'ok'"]),
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
            TaskSpec(id=f"{i:02d}", title=f"Task {i}", description=f"Do {i}", max_retries=2, acceptance_criteria=["assert result == 'ok'"])
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

    def test_logs_review_skipped_when_review_disabled(self, tmp_path):
        caps = Caps(max_retries_global=5, max_concurrent_workers=2, max_wall_time_minutes=60, review="disabled")
        engine = make_engine(tmp_path, caps=caps)

        for tid in ["01", "02"]:
            engine.apply_worker_result(tid, True, "Done")
            engine.apply_reviewer_result(tid, True, "Approved")

        engine.tick()
        event_types = [e.event_type for e in engine.state.event_log]
        assert "mission_completed" in event_types
        assert "review_skipped" in event_types


class TestWorkerLifecycle:
    def test_retry_not_before_defaults_to_zero(self, tmp_path):
        engine = make_engine(tmp_path)

        task_state = engine.state.get_task("01")

        assert task_state.retry_not_before == 0.0

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
        
        with patch("agentforce.core.engine.time.time", return_value=100.0):
            engine.apply_worker_result("01", False, error="Network error")
        ts = engine.state.get_task("01")
        assert ts.status == "retry"
        assert ts.retries == 1
        assert ts.retry_not_before == pytest.approx(105.0)

    def test_retry_backoff_skips_dispatch_until_deadline(self, tmp_path, caplog):
        import logging

        engine = make_engine(tmp_path)

        with patch("agentforce.core.engine.time.time", return_value=100.0):
            engine.tick()
            engine.apply_worker_result("01", False, error="Network error")

        with patch("agentforce.core.engine.time.time", return_value=104.0):
            with caplog.at_level(logging.DEBUG, logger="agentforce.engine"):
                actions = engine.tick()

        worker_actions = [a for a in actions if isinstance(a, WorkerDelegation)]
        assert all(action.task_id != "01" for action in worker_actions)
        assert any("task 01 in backoff" in record.message for record in caplog.records)

        with patch("agentforce.core.engine.time.time", return_value=105.0):
            actions = engine.tick()

        worker_actions = [a for a in actions if isinstance(a, WorkerDelegation)]
        assert any(action.task_id == "01" for action in worker_actions)

    def test_retry_backoff_grows_exponentially_across_failures(self, tmp_path):
        engine = make_engine(
            tmp_path,
            tasks=[TaskSpec(id="01", title="Task A", description="Do A", max_retries=3, acceptance_criteria=["assert result == 'ok'"])],
        )

        with patch("agentforce.core.engine.time.time", return_value=100.0):
            engine.tick()
            engine.apply_worker_result("01", False, error="Fail 1")

        assert engine.state.get_task("01").retry_not_before == pytest.approx(105.0)

        with patch("agentforce.core.engine.time.time", return_value=105.0):
            engine.tick()

        with patch("agentforce.core.engine.time.time", return_value=200.0):
            engine.apply_worker_result("01", False, error="Fail 2")

        assert engine.state.get_task("01").retry_not_before == pytest.approx(210.0)

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

    def test_manual_retry_does_not_increment_retry_counters(self, tmp_path):
        engine = make_engine(tmp_path)
        task_state = engine.state.get_task("01")
        task_state.status = "failed"
        task_state.retries = 2
        task_state.retry_not_before = 999.0
        engine.state.total_retries = 4
        engine._save()

        engine.manual_retry("01")

        task_state = engine.state.get_task("01")
        assert task_state.status == "retry"
        assert task_state.retries == 2
        assert task_state.retry_not_before == 0.0
        assert engine.state.total_retries == 4

    def test_manual_retry_clears_human_intervention_flags(self, tmp_path):
        engine = make_engine(tmp_path)
        task_state = engine.state.get_task("01")
        task_state.status = "needs_human"
        task_state.human_intervention_needed = True
        task_state.human_intervention_message = "Need approval"
        engine._save()

        engine.manual_retry("01")

        task_state = engine.state.get_task("01")
        assert task_state.status == "retry"
        assert task_state.human_intervention_needed is False
        assert task_state.human_intervention_message == ""
        assert engine.state.needs_human() == []


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

    def test_outcome_memory_truncation_uses_2000_chars(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        engine.apply_worker_result("01", True, "Implemented")

        feedback = "x" * 2500

        engine.apply_reviewer_result("01", True, feedback, 9)

        stored_feedback = engine.memory.project_get(
            engine.state.mission_id,
            "task_01_outcome",
        )
        assert stored_feedback == feedback[:2000]

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

    def test_blocking_issues_retry_before_human(self, tmp_path):
        # Blocking issues should trigger a retry so the worker can fix them,
        # not immediately escalate to human intervention.
        engine = make_engine(tmp_path)
        engine.tick()
        engine.apply_worker_result("01", True, "Done")

        engine.tick()
        engine.apply_reviewer_result(
            "01", False, "Missing subscription call", score=3,
            blocking_issues=["wsClient.subscribe() never called"]
        )

        ts = engine.state.get_task("01")
        assert ts.status == "retry"
        assert ts.blocking_issues == ["wsClient.subscribe() never called"]
        assert not ts.needs_human_attention()

    def test_blocking_issues_escalate_after_retries_exhausted(self, tmp_path):
        # After retries are exhausted, blocking issues escalate to human.
        engine = make_engine(tmp_path)
        engine.tick()
        engine.apply_worker_result("01", True, "Done")

        # max_retries=2, so two rejections exhaust retries
        for _ in range(2):
            engine.tick()
            engine.apply_reviewer_result(
                "01", False, "Still broken", score=3, blocking_issues=["Missing subscribe"]
            )

        ts = engine.state.get_task("01")
        assert ts.needs_human_attention()
        assert "Missing subscribe" in ts.human_intervention_message


class TestDependencyOrdering:
    def test_dependent_task_blocked(self, tmp_path):
        tasks = [
            TaskSpec(id="01", title="Base", description="Base", max_retries=2, acceptance_criteria=["assert result == 'ok'"]),
            TaskSpec(id="02", title="Dependent", description="Dep", dependencies=["01"], max_retries=2, acceptance_criteria=["assert result == 'ok'"]),
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

    def test_worker_timeout_fallback_when_wall_time_disabled(self, tmp_path):
        # max_wall_time_minutes=0 means wall-time is disabled (used by --extend-caps).
        # _dispatch_worker must not compute min(600, 0*60)=0; it should use 600.
        caps = Caps(max_wall_time_minutes=0, max_retries_global=10)
        engine = make_engine(tmp_path, caps=caps)
        actions = engine.tick()
        worker_actions = [a for a in actions if isinstance(a, WorkerDelegation)]
        assert worker_actions, "expected at least one worker dispatched"
        for action in worker_actions:
            assert action.timeout == 600, f"expected timeout=600, got {action.timeout}"

    def test_wall_time_disabled_when_zero(self, tmp_path):
        # max_wall_time_minutes=0 must not trigger the wall-time cap.
        caps = Caps(max_wall_time_minutes=0)
        engine = make_engine(tmp_path, caps=caps)
        engine.state.started_at = "2020-01-01T00:00:00+00:00"
        engine._save()

        cap = engine._check_caps()
        assert cap is None
        assert "wall_time" not in engine.state.caps_hit

    def test_extend_caps_raises_limits_without_touching_counters(self, tmp_path):
        # Simulate what run_autonomous does with extend_caps=True:
        # caps are raised in-memory; stored counters are unchanged.
        caps = Caps(max_wall_time_minutes=180, max_retries_global=5, max_human_interventions=3)
        engine = make_engine(tmp_path, caps=caps)
        engine.state.total_retries = 5
        engine.state.total_human_interventions = 3
        engine.state.started_at = "2020-01-01T00:00:00+00:00"
        engine._save()

        # Apply extend_caps logic (mirrors autonomous.py)
        c = engine.state.caps
        c.max_wall_time_minutes = 0
        c.max_retries_global = max(c.max_retries_global, engine.state.total_retries + 100)
        c.max_human_interventions = max(c.max_human_interventions, engine.state.total_human_interventions + 100)

        # No cap should trigger now
        assert engine._check_caps() is None
        # Counters are untouched
        assert engine.state.total_retries == 5
        assert engine.state.total_human_interventions == 3


class TestEventLog:
    def test_logs_are_recorded(self, tmp_path):
        engine = make_engine(tmp_path)
        # Initial tick adds dispatch events
        engine.tick()
        events = engine.event_log_tail()
        assert len(events) >= 2  # At least 2 dispatch events

    def test_tail_limit(self, tmp_path):
        engine = make_engine(tmp_path, tasks=[
            TaskSpec(id=f"task{i:02d}", title=f"T{i}", description=f"Do {i}", max_retries=2, acceptance_criteria=["assert result == 'ok'"])
            for i in range(30)
        ], caps=Caps(max_concurrent_workers=30))
        engine.tick()
        tail = engine.event_log_tail(3)
        assert len(tail) <= 3


class TestAgentContext:
    """Tests for query= parameter passing in agent_context() calls."""

    def test_agent_context_worker_passes_query_from_acceptance_criteria(self, tmp_path):
        """_dispatch_worker must call agent_context with query= from acceptance_criteria."""
        from unittest.mock import MagicMock, patch

        tasks = [
            TaskSpec(
                id="01",
                title="Task A",
                description="Do A",
                acceptance_criteria=["criterion one", "criterion two"],
                max_retries=2,
            )
        ]
        engine = make_engine(tmp_path, tasks=tasks)

        captured = {}

        real_agent_context = engine.memory.agent_context

        def spy_agent_context(project_id, task_id, query=None):
            captured["query"] = query
            return real_agent_context(project_id, task_id, query=query)

        engine.memory.agent_context = spy_agent_context
        engine.tick()

        assert "query" in captured, "agent_context was not called"
        assert captured["query"] == "criterion one\ncriterion two"

    def test_agent_context_worker_falls_back_to_description_when_no_criteria(self, tmp_path):
        """When acceptance_criteria is empty, query= falls back to task.description."""
        tasks = [
            TaskSpec(
                id="01",
                title="Task A",
                description="Do A thoroughly",
                acceptance_criteria=["assert result == 'ok'"],
                max_retries=2,
            )
        ]
        engine = make_engine(tmp_path, tasks=tasks)
        # Clear criteria after engine creation to exercise the fallback code path
        engine.spec.tasks[0].acceptance_criteria = []

        captured = {}

        real_agent_context = engine.memory.agent_context

        def spy_agent_context(project_id, task_id, query=None):
            captured["query"] = query
            return real_agent_context(project_id, task_id, query=query)

        engine.memory.agent_context = spy_agent_context
        engine.tick()

        assert captured.get("query") == "Do A thoroughly"

    def test_agent_context_reviewer_passes_query(self, tmp_path):
        """_dispatch_reviewer must also call agent_context with query=."""
        tasks = [
            TaskSpec(
                id="01",
                title="Task A",
                description="Do A",
                acceptance_criteria=["reviewed criterion"],
                max_retries=2,
            )
        ]
        engine = make_engine(tmp_path, tasks=tasks)

        queries = []

        real_agent_context = engine.memory.agent_context

        def spy_agent_context(project_id, task_id, query=None):
            queries.append(query)
            return real_agent_context(project_id, task_id, query=query)

        engine.memory.agent_context = spy_agent_context

        engine.tick()
        engine.apply_worker_result("01", True, "Done")
        engine.tick()  # triggers reviewer dispatch

        assert len(queries) >= 2, "agent_context should be called for worker and reviewer"
        assert "reviewed criterion" in queries

    def test_agent_context_debug_log_emitted_for_worker(self, tmp_path, caplog):
        """A DEBUG log line 'agent_context query [<id>]: <text>' must be emitted."""
        import logging

        tasks = [
            TaskSpec(
                id="01",
                title="Task A",
                description="Do A",
                acceptance_criteria=["log this criterion"],
                max_retries=2,
            )
        ]
        engine = make_engine(tmp_path, tasks=tasks)

        with caplog.at_level(logging.DEBUG, logger="agentforce.engine"):
            engine.tick()

        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("agent_context query" in m and "01" in m for m in debug_msgs), (
            f"Expected debug log not found in: {debug_msgs}"
        )

    def test_vector_memory_agent_context_with_query(self, tmp_path):
        """Memory.agent_context falls back gracefully when query= provided (no vector DB)."""
        from agentforce.memory import Memory

        mem = Memory(tmp_path / "mem")
        mem.project_set("proj1", "key1", "value1")

        result_with_query = mem.agent_context("proj1", "t1", query="some query")
        result_without_query = mem.agent_context("proj1", "t1")

        # Both should return the same full dump (Memory doesn't do semantic search)
        assert result_with_query == result_without_query


class TestReport:
    def test_report_format(self, tmp_path):
        engine = make_engine(tmp_path)
        engine.tick()
        report = engine.report()
        assert "Test Mission" in report
        assert "Task A" in report
        assert "Task B" in report
