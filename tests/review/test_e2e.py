from __future__ import annotations

from pathlib import Path

import pytest

import agentforce.review as review_pkg
from agentforce.core.spec import Caps, MissionSpec, TaskSpec, TaskStatus
from agentforce.core.state import EventLogEntry, MissionState, TaskState
from agentforce.memory.memory import Memory
from agentforce.review.collector import MetricsCollector
from agentforce.review.memory_writer import ReviewMemoryWriter
from agentforce.review.models import ActionItem, MetricsSnapshot, ReviewReport
from agentforce.review.schemas import MissionReviewPayloadV1


def _mission_state() -> MissionState:
    spec = MissionSpec(
        name="End-to-End Review Mission",
        goal="Exercise the review pipeline end to end",
        definition_of_done=["All tasks approved and reviewed"],
        tasks=[
            TaskSpec(id="task-01", title="Task 01", description="First task"),
            TaskSpec(id="task-02", title="Task 02", description="Second task"),
            TaskSpec(id="task-03", title="Task 03", description="Third task"),
            TaskSpec(id="task-04", title="Task 04", description="Fourth task"),
        ],
        caps=Caps(),
    )

    state = MissionState(
        mission_id="mission-e2e",
        spec=spec,
        task_states={
            "task-01": TaskState(
                task_id="task-01",
                status=TaskStatus.REVIEW_APPROVED,
                retries=0,
                review_score=9,
                tokens_out=5000,
                cost_usd=0.012,
                started_at="2026-04-08T10:00:00Z",
                completed_at="2026-04-08T10:05:00Z",
            ),
            "task-02": TaskState(
                task_id="task-02",
                status=TaskStatus.REVIEW_APPROVED,
                retries=2,
                review_score=7,
                tokens_out=12000,
                cost_usd=0.031,
                started_at="2026-04-08T10:00:00Z",
                completed_at="2026-04-08T10:15:00Z",
            ),
            "task-03": TaskState(
                task_id="task-03",
                status=TaskStatus.FAILED,
                retries=3,
                review_score=0,
                human_intervention_needed=True,
                started_at="2026-04-08T10:00:00Z",
                completed_at=None,
            ),
            "task-04": TaskState(
                task_id="task-04",
                status=TaskStatus.REVIEW_APPROVED,
                retries=0,
                review_score=10,
                tokens_out=3000,
                cost_usd=0.008,
                started_at="2026-04-08T10:00:00Z",
                completed_at="2026-04-08T10:08:00Z",
            ),
        },
        event_log=[
            EventLogEntry(timestamp="2026-04-08T10:00:00Z", event_type="mission_started"),
            EventLogEntry(timestamp="2026-04-08T10:00:10Z", event_type="task_dispatched", task_id="task-01"),
            EventLogEntry(timestamp="2026-04-08T10:00:12Z", event_type="task_dispatched", task_id="task-02"),
            EventLogEntry(timestamp="2026-04-08T10:00:14Z", event_type="task_dispatched", task_id="task-03"),
            EventLogEntry(timestamp="2026-04-08T10:00:16Z", event_type="task_dispatched", task_id="task-04"),
            EventLogEntry(timestamp="2026-04-08T10:05:00Z", event_type="task_completed", task_id="task-01"),
            EventLogEntry(timestamp="2026-04-08T10:05:10Z", event_type="review_approved", task_id="task-01"),
            EventLogEntry(timestamp="2026-04-08T10:06:00Z", event_type="task_completed", task_id="task-02"),
            EventLogEntry(timestamp="2026-04-08T10:06:05Z", event_type="review_rejected", task_id="task-02"),
            EventLogEntry(timestamp="2026-04-08T10:10:00Z", event_type="task_completed", task_id="task-02"),
            EventLogEntry(timestamp="2026-04-08T10:10:05Z", event_type="review_rejected", task_id="task-02"),
            EventLogEntry(timestamp="2026-04-08T10:15:00Z", event_type="task_completed", task_id="task-02"),
            EventLogEntry(timestamp="2026-04-08T10:15:05Z", event_type="review_approved", task_id="task-02"),
            EventLogEntry(timestamp="2026-04-08T10:20:00Z", event_type="human_intervention", task_id="task-03"),
            EventLogEntry(timestamp="2026-04-08T10:25:00Z", event_type="task_completed", task_id="task-04"),
            EventLogEntry(timestamp="2026-04-08T10:25:05Z", event_type="review_approved", task_id="task-04"),
        ],
        started_at="2026-04-08T10:00:00Z",
    )
    state.total_retries = 5
    state.total_human_interventions = 1
    state.tokens_out = 20000
    state.cost_usd = 0.051
    return state


def test_package_exports_match_review_contract():
    assert review_pkg.__all__ == [
        "ReviewReport",
        "RetroItem",
        "ActionItem",
        "MetricsSnapshot",
        "GoodhartWarning",
        "MissionReviewPayloadV1",
        "MetricsCollector",
        "MissionReviewer",
        "ReviewMemoryWriter",
    ]


def test_metrics_collector_end_to_end_and_memory_round_trip(tmp_path: Path):
    state = _mission_state()

    metrics = MetricsCollector.collect(MissionReviewPayloadV1.from_state(state))

    assert metrics.tasks_completed == 3
    assert metrics.tasks_total == 4
    assert metrics.first_pass_rate == pytest.approx(0.5)
    assert metrics.rework_rate == pytest.approx(1.25)
    assert metrics.avg_review_score == pytest.approx((9 + 7 + 10) / 3)
    assert metrics.human_escalation_rate == pytest.approx(0.25)
    assert metrics.token_efficiency == pytest.approx((5000 + 12000 + 3000) / 3)
    assert metrics.review_rejection_rate == pytest.approx(2 / 5)
    assert metrics.quality_score == pytest.approx(
        ((8.6666666667 / 10) * 0.4 + 0.5 * 0.25 + (1 - 0.25) * 0.3) * 10,
        abs=0.01,
    )
    assert metrics.efficiency_gated is None

    baseline = MetricsSnapshot(
        mission_id="base",
        avg_review_score=8.5,
        token_efficiency=8000.0,
        first_pass_rate=0.5,
        human_escalation_rate=0.2,
    )
    baseline.quality_score = 8.0
    current = MetricsSnapshot(
        mission_id="curr",
        avg_review_score=6.5,
        token_efficiency=5000.0,
        first_pass_rate=0.4,
        human_escalation_rate=0.3,
    )
    current.quality_score = 6.5

    warnings = MetricsCollector.detect_goodhart(current, baseline)
    assert len(warnings) >= 1
    assert any(w.metric_name == "token_efficiency" for w in warnings)

    zero_tokens_state = _mission_state()
    for task_state in zero_tokens_state.task_states.values():
        task_state.tokens_out = 0
    zero_tokens_state.tokens_out = 20000

    fallback_metrics = MetricsCollector.collect(MissionReviewPayloadV1.from_state(zero_tokens_state))
    assert "per-task token fields are zero" in " ".join(fallback_metrics.data_quality_warnings)
    assert fallback_metrics.token_efficiency == pytest.approx(20000 / 3)

    report = ReviewReport(mission_id="test-01", mission_name="Test", metrics=metrics)
    report.action_items = [
        ActionItem(
            id="memory-1",
            action_type="memory_entry",
            approved=True,
            memory_scope="project",
            memory_key="review:test:lesson1",
            memory_value="Use TDD",
            memory_category="lesson",
        ),
        ActionItem(
            id="process-1",
            action_type="process_improvement",
            approved=True,
            description="Strengthen review checklists",
        ),
    ]

    report_path = tmp_path / "test_review.json"
    report.save(report_path)
    loaded = ReviewReport.load(report_path)
    assert loaded == report

    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)

    written = writer.write_approved_items(report)

    assert written == 2
    assert memory.project_get("test-01", "review:test:lesson1") == "Use TDD"
