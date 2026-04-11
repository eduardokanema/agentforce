"""Read-only facades over mission state for downstream consumers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agentforce.core.spec import TaskStatus
from agentforce.core.state import MissionState


def _status_value(status: object) -> str:
    return status.value if hasattr(status, "value") else str(status)


@dataclass(frozen=True)
class MissionTaskView:
    task_id: str
    title: str
    status: str
    retries: int
    review_score: int
    started_at: str | None
    completed_at: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    blocking_issues: list[str]
    error_message: str


class MissionStateLifecycle:
    def __init__(self, state: MissionState):
        self._state = state

    @property
    def mission_id(self) -> str:
        return self._state.mission_id

    @property
    def mission_name(self) -> str:
        return self._state.spec.name

    @property
    def mission_goal(self) -> str:
        return self._state.spec.goal

    @property
    def completed_at(self) -> str | None:
        return self._state.completed_at

    @property
    def caps_hit(self) -> dict[str, str]:
        return dict(self._state.caps_hit)

    def event_entries(self, limit: int | None = None) -> list[dict[str, str | None]]:
        entries = self._state.event_log[-limit:] if limit is not None else self._state.event_log
        return [
            {
                "timestamp": entry.timestamp,
                "event_type": entry.event_type,
                "task_id": entry.task_id,
                "details": entry.details,
            }
            for entry in entries
        ]

    def tasks(self) -> list[MissionTaskView]:
        views: list[MissionTaskView] = []
        for task_spec in self._state.spec.tasks:
            task_state = self._state.task_states.get(task_spec.id)
            if task_state is None:
                views.append(
                    MissionTaskView(
                        task_id=task_spec.id,
                        title=task_spec.title,
                        status=TaskStatus.PENDING.value,
                        retries=0,
                        review_score=0,
                        started_at=None,
                        completed_at=None,
                        tokens_in=0,
                        tokens_out=0,
                        cost_usd=0.0,
                        blocking_issues=[],
                        error_message="",
                    )
                )
                continue
            views.append(
                MissionTaskView(
                    task_id=task_spec.id,
                    title=task_spec.title,
                    status=_status_value(task_state.status),
                    retries=task_state.retries,
                    review_score=task_state.review_score,
                    started_at=task_state.started_at,
                    completed_at=task_state.completed_at,
                    tokens_in=task_state.tokens_in,
                    tokens_out=task_state.tokens_out,
                    cost_usd=task_state.cost_usd,
                    blocking_issues=list(task_state.blocking_issues),
                    error_message=task_state.error_message,
                )
            )
        return views


class MissionStateMetrics:
    def __init__(self, state: MissionState):
        self._state = state

    @property
    def total_retries(self) -> int:
        return self._state.total_retries

    @property
    def total_human_interventions(self) -> int:
        return self._state.total_human_interventions

    @property
    def total_cost_usd(self) -> float:
        return self._state.cost_usd

    @property
    def total_tokens_out(self) -> int:
        return self._state.tokens_out

    def task_views(self) -> list[MissionTaskView]:
        return MissionStateLifecycle(self._state).tasks()

    def review_rejection_rate(self) -> float:
        approved = sum(1 for entry in self._state.event_log if entry.event_type == "review_approved")
        rejected = sum(1 for entry in self._state.event_log if entry.event_type == "review_rejected")
        total = approved + rejected
        return rejected / total if total else 0.0

    def tasks_completed(self) -> int:
        return sum(1 for task in self.task_views() if task.status == TaskStatus.REVIEW_APPROVED.value)

    def first_pass_approved(self) -> int:
        return sum(
            1 for task in self.task_views() if task.status == TaskStatus.REVIEW_APPROVED.value and task.retries == 0
        )

    def review_scores(self) -> list[int]:
        return [
            task.review_score
            for task in self.task_views()
            if task.review_score > 0 and task.status in {TaskStatus.REVIEW_APPROVED.value, TaskStatus.FAILED.value}
        ]

    def total_wall_time_s(self) -> tuple[float, int]:
        total = 0.0
        count = 0
        for task in self.task_views():
            if not task.started_at or not task.completed_at:
                continue
            started = datetime.fromisoformat(task.started_at.replace("Z", "+00:00"))
            completed = datetime.fromisoformat(task.completed_at.replace("Z", "+00:00"))
            total += (completed - started).total_seconds()
            count += 1
        return total, count

    def task_costs_total(self) -> float:
        return sum(task.cost_usd for task in self.task_views())

    def task_tokens_total(self) -> int:
        return sum(task.tokens_out for task in self.task_views())

    def total_tasks(self) -> int:
        return len(self.task_views())

