from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agentforce.core.spec import Caps, MissionSpec, TaskSpec, TaskStatus
from agentforce.core.state import EventLogEntry, MissionState, TaskState
from agentforce.review import MetricsSnapshot
from agentforce.review.collector import MetricsCollector
from agentforce.review.schemas import MissionReviewPayloadV1


def _spec(task_count: int = 4) -> MissionSpec:
    tasks = [
        TaskSpec(id=f"task-{i}", title=f"Task {i}", description=f"Task {i} description")
        for i in range(1, task_count + 1)
    ]
    return MissionSpec(
        name="collector-mission",
        goal="Exercise review metrics collection",
        definition_of_done=["All tasks approved"],
        tasks=tasks,
        caps=Caps(),
    )


def _state(task_states: dict[str, TaskState] | None = None, event_log: list[EventLogEntry] | None = None) -> MissionState:
    return MissionState(
        mission_id="mission-collector",
        spec=_spec(len(task_states or {})),
        task_states=task_states or {},
        event_log=event_log or [],
        started_at="2024-01-01T10:00:00+00:00",
    )


def _payload(state: MissionState) -> MissionReviewPayloadV1:
    return MissionReviewPayloadV1.from_state(state)


def _approved_task(
    task_id: str,
    retries: int,
    review_score: int,
    started_at: str,
    completed_at: str,
    tokens_out: int,
    cost_usd: float,
) -> TaskState:
    return TaskState(
        task_id=task_id,
        status=TaskStatus.REVIEW_APPROVED,
        retries=retries,
        review_score=review_score,
        started_at=started_at,
        completed_at=completed_at,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )


def _failed_task(
    task_id: str,
    retries: int,
    review_score: int,
    started_at: str | None,
    completed_at: str | None,
    tokens_out: int,
    cost_usd: float,
) -> TaskState:
    return TaskState(
        task_id=task_id,
        status=TaskStatus.FAILED,
        retries=retries,
        review_score=review_score,
        started_at=started_at,
        completed_at=completed_at,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )


def test_collect_happy_path_computes_all_metrics():
    task_states = {
        "task-1": _approved_task(
            "task-1",
            retries=0,
            review_score=9,
            started_at="2024-01-01T10:00:00+00:00",
            completed_at="2024-01-01T10:01:00+00:00",
            tokens_out=100,
            cost_usd=1.0,
        ),
        "task-2": _approved_task(
            "task-2",
            retries=0,
            review_score=8,
            started_at="2024-01-01T10:02:00+00:00",
            completed_at="2024-01-01T10:04:00+00:00",
            tokens_out=200,
            cost_usd=2.0,
        ),
        "task-3": _approved_task(
            "task-3",
            retries=1,
            review_score=7,
            started_at="2024-01-01T10:05:00+00:00",
            completed_at="2024-01-01T10:05:30+00:00",
            tokens_out=50,
            cost_usd=0.5,
        ),
        "task-4": _failed_task(
            "task-4",
            retries=1,
            review_score=6,
            started_at="2024-01-01T10:06:00+00:00",
            completed_at="2024-01-01T10:07:30+00:00",
            tokens_out=100,
            cost_usd=1.0,
        ),
    }
    state = _state(task_states, event_log=[
        EventLogEntry(timestamp="2024-01-01T10:01:00+00:00", event_type="review_approved", task_id="task-1"),
        EventLogEntry(timestamp="2024-01-01T10:04:00+00:00", event_type="review_approved", task_id="task-2"),
        EventLogEntry(timestamp="2024-01-01T10:05:30+00:00", event_type="review_approved", task_id="task-3"),
        EventLogEntry(timestamp="2024-01-01T10:07:30+00:00", event_type="review_rejected", task_id="task-4"),
    ])
    state.total_retries = 2
    state.total_human_interventions = 0
    state.tokens_out = 450
    state.cost_usd = 4.5

    snapshot = MetricsCollector.collect(_payload(state))

    assert snapshot.tasks_total == 4
    assert snapshot.tasks_completed == 3
    assert snapshot.first_pass_rate == pytest.approx(0.5)
    assert snapshot.rework_rate == pytest.approx(0.5)
    assert snapshot.avg_review_score == pytest.approx(7.5)
    assert snapshot.human_escalation_rate == pytest.approx(0.0)
    assert snapshot.wall_time_per_task_s == pytest.approx(100.0)
    assert snapshot.cost_per_task_usd == pytest.approx(1.5)
    assert snapshot.token_efficiency == pytest.approx(150.0)
    assert snapshot.review_rejection_rate == pytest.approx(0.25)
    assert snapshot.quality_score == pytest.approx(7.25)
    assert snapshot.efficiency_gated == pytest.approx(150.0)
    assert snapshot.data_quality_warnings == []


def test_collect_zero_tasks_returns_zero_metrics():
    state = _state({})

    snapshot = MetricsCollector.collect(_payload(state))

    assert snapshot.tasks_total == 0
    assert snapshot.tasks_completed == 0
    assert snapshot.first_pass_rate == 0.0
    assert snapshot.rework_rate == 0.0
    assert snapshot.avg_review_score == 0.0
    assert snapshot.human_escalation_rate == 0.0
    assert snapshot.wall_time_per_task_s == 0.0
    assert snapshot.cost_per_task_usd == 0.0
    assert snapshot.token_efficiency == 0.0
    assert snapshot.review_rejection_rate == 0.0
    assert snapshot.quality_score == 0.0
    assert snapshot.efficiency_gated is None


def test_collect_zero_completed_tasks_returns_zero_metrics():
    task_states = {
        "task-1": TaskState(task_id="task-1", status=TaskStatus.PENDING),
        "task-2": TaskState(task_id="task-2", status=TaskStatus.IN_PROGRESS),
    }
    state = _state(task_states)

    snapshot = MetricsCollector.collect(_payload(state))

    assert snapshot.tasks_total == 2
    assert snapshot.tasks_completed == 0
    assert snapshot.first_pass_rate == 0.0
    assert snapshot.rework_rate == 0.0
    assert snapshot.avg_review_score == 0.0
    assert snapshot.human_escalation_rate == 0.0
    assert snapshot.wall_time_per_task_s == 0.0
    assert snapshot.cost_per_task_usd == 0.0
    assert snapshot.token_efficiency == 0.0
    assert snapshot.quality_score == 0.0
    assert snapshot.efficiency_gated is None


def test_collect_skips_tasks_with_missing_timestamps_for_wall_time():
    task_states = {
        "task-1": _approved_task(
            "task-1",
            retries=0,
            review_score=8,
            started_at="2024-01-01T10:00:00+00:00",
            completed_at="2024-01-01T10:02:00+00:00",
            tokens_out=100,
            cost_usd=1.0,
        ),
        "task-2": _approved_task(
            "task-2",
            retries=0,
            review_score=8,
            started_at=None,
            completed_at="2024-01-01T10:03:30+00:00",
            tokens_out=100,
            cost_usd=1.0,
        ),
        "task-3": _approved_task(
            "task-3",
            retries=0,
            review_score=8,
            started_at="2024-01-01T10:04:00+00:00",
            completed_at=None,
            tokens_out=100,
            cost_usd=1.0,
        ),
    }
    state = _state(task_states)

    snapshot = MetricsCollector.collect(_payload(state))

    assert snapshot.tasks_completed == 3
    assert snapshot.wall_time_per_task_s == pytest.approx(40.0)


def test_collect_zero_task_token_fields_uses_mission_fallback_and_warns():
    task_states = {
        "task-1": _approved_task(
            "task-1",
            retries=0,
            review_score=9,
            started_at="2024-01-01T10:00:00+00:00",
            completed_at="2024-01-01T10:01:00+00:00",
            tokens_out=0,
            cost_usd=0.5,
        ),
        "task-2": _approved_task(
            "task-2",
            retries=0,
            review_score=9,
            started_at="2024-01-01T10:02:00+00:00",
            completed_at="2024-01-01T10:03:00+00:00",
            tokens_out=0,
            cost_usd=0.5,
        ),
    }
    state = _state(task_states)
    state.tokens_out = 600

    snapshot = MetricsCollector.collect(_payload(state))

    assert snapshot.token_efficiency == pytest.approx(300.0)
    assert "per-task token fields are zero; using mission-level fallback" in snapshot.data_quality_warnings


def test_collect_review_rejection_rate_uses_event_log():
    task_states = {
        "task-1": _approved_task("task-1", 0, 9, "2024-01-01T10:00:00+00:00", "2024-01-01T10:01:00+00:00", 10, 0.1),
        "task-2": _approved_task("task-2", 0, 8, "2024-01-01T10:02:00+00:00", "2024-01-01T10:03:00+00:00", 10, 0.1),
    }
    state = _state(task_states, event_log=[
        EventLogEntry(timestamp="2024-01-01T10:01:00+00:00", event_type="review_approved", task_id="task-1"),
        EventLogEntry(timestamp="2024-01-01T10:03:00+00:00", event_type="review_approved", task_id="task-2"),
        EventLogEntry(timestamp="2024-01-01T10:03:30+00:00", event_type="review_approved", task_id="task-2"),
        EventLogEntry(timestamp="2024-01-01T10:04:00+00:00", event_type="review_rejected", task_id="task-2"),
    ])

    snapshot = MetricsCollector.collect(_payload(state))

    assert snapshot.review_rejection_rate == pytest.approx(0.25)


def test_compute_quality_score_formula():
    expected = ((7.5 / 10) * 0.4 + 0.5 * 0.25 + (1 - 0.2) * 0.3) * 10

    assert MetricsCollector.compute_quality_score(7.5, 0.5, 0.2) == pytest.approx(expected)


def test_gate_efficiency_respects_quality_threshold():
    assert MetricsCollector.gate_efficiency(123.4, 6.99) is None
    assert MetricsCollector.gate_efficiency(123.4, 7.0) == pytest.approx(123.4)


def test_detect_goodhart_warns_when_efficiency_improves_and_quality_drops():
    baseline = MetricsSnapshot(
        mission_id="baseline",
        token_efficiency=100.0,
        cost_per_task_usd=10.0,
        first_pass_rate=0.7,
        human_escalation_rate=0.1,
        wall_time_per_task_s=50.0,
        avg_review_score=8.0,
        review_rejection_rate=0.1,
    )
    current = MetricsSnapshot(
        mission_id="current",
        token_efficiency=90.0,
        cost_per_task_usd=10.0,
        first_pass_rate=0.7,
        human_escalation_rate=0.1,
        wall_time_per_task_s=50.0,
        avg_review_score=7.4,
        review_rejection_rate=0.1,
    )

    warnings = MetricsCollector.detect_goodhart(current, baseline)

    assert len(warnings) == 1
    assert warnings[0].metric_name == "token_efficiency"


def test_detect_goodhart_ignores_exactly_two_percent_boundary():
    baseline = MetricsSnapshot(
        mission_id="baseline",
        token_efficiency=100.0,
        cost_per_task_usd=10.0,
        first_pass_rate=0.6,
        human_escalation_rate=0.2,
        wall_time_per_task_s=50.0,
        avg_review_score=8.0,
        review_rejection_rate=0.1,
    )
    current = MetricsSnapshot(
        mission_id="current",
        token_efficiency=98.0,
        cost_per_task_usd=10.0,
        first_pass_rate=0.6,
        human_escalation_rate=0.2,
        wall_time_per_task_s=50.0,
        avg_review_score=7.6,
        review_rejection_rate=0.1,
    )

    assert MetricsCollector.detect_goodhart(current, baseline) == []


def test_detect_goodhart_does_not_warn_when_both_improve():
    baseline = MetricsSnapshot(
        mission_id="baseline",
        token_efficiency=100.0,
        cost_per_task_usd=10.0,
        first_pass_rate=0.5,
        human_escalation_rate=0.3,
        wall_time_per_task_s=100.0,
        avg_review_score=7.0,
        review_rejection_rate=0.3,
    )
    current = MetricsSnapshot(
        mission_id="current",
        token_efficiency=80.0,
        cost_per_task_usd=8.0,
        first_pass_rate=0.6,
        human_escalation_rate=0.2,
        wall_time_per_task_s=80.0,
        avg_review_score=8.0,
        review_rejection_rate=0.2,
    )

    assert MetricsCollector.detect_goodhart(current, baseline) == []
