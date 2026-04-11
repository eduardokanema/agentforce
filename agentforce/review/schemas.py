from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentforce.core.state import MissionState
from agentforce.core.state_facades import MissionStateLifecycle, MissionStateMetrics


@dataclass(frozen=True)
class MissionReviewTaskV1:
    task_id: str
    title: str
    status: str
    retries: int = 0
    review_score: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    blocking_issues: list[str] = field(default_factory=list)
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "status": self.status,
            "retries": self.retries,
            "review_score": self.review_score,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "blocking_issues": list(self.blocking_issues),
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MissionReviewTaskV1":
        return cls(**{key: payload.get(key) for key in cls.__dataclass_fields__})


@dataclass(frozen=True)
class MissionReviewEventV1:
    timestamp: str
    event_type: str
    task_id: str | None = None
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "task_id": self.task_id,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MissionReviewEventV1":
        return cls(**{key: payload.get(key) for key in cls.__dataclass_fields__})


@dataclass(frozen=True)
class MissionReviewPayloadV1:
    schema_version: str
    mission_id: str
    mission_name: str
    mission_goal: str
    completed_at: str | None = None
    total_retries: int = 0
    total_human_interventions: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    caps_hit: dict[str, str] = field(default_factory=dict)
    tasks: list[MissionReviewTaskV1] = field(default_factory=list)
    event_log: list[MissionReviewEventV1] = field(default_factory=list)

    @classmethod
    def from_state(cls, state: MissionState) -> "MissionReviewPayloadV1":
        lifecycle = MissionStateLifecycle(state)
        metrics = MissionStateMetrics(state)
        return cls(
            schema_version="mission_review_payload.v1",
            mission_id=lifecycle.mission_id,
            mission_name=lifecycle.mission_name,
            mission_goal=lifecycle.mission_goal,
            completed_at=lifecycle.completed_at,
            total_retries=metrics.total_retries,
            total_human_interventions=metrics.total_human_interventions,
            total_tokens_out=metrics.total_tokens_out,
            total_cost_usd=metrics.total_cost_usd,
            caps_hit=lifecycle.caps_hit,
            tasks=[
                MissionReviewTaskV1(
                    task_id=task.task_id,
                    title=task.title,
                    status=task.status,
                    retries=task.retries,
                    review_score=task.review_score,
                    started_at=task.started_at,
                    completed_at=task.completed_at,
                    tokens_in=task.tokens_in,
                    tokens_out=task.tokens_out,
                    cost_usd=task.cost_usd,
                    blocking_issues=list(task.blocking_issues),
                    error_message=task.error_message,
                )
                for task in lifecycle.tasks()
            ],
            event_log=[MissionReviewEventV1.from_dict(entry) for entry in lifecycle.event_entries()],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "mission_name": self.mission_name,
            "mission_goal": self.mission_goal,
            "completed_at": self.completed_at,
            "total_retries": self.total_retries,
            "total_human_interventions": self.total_human_interventions,
            "total_tokens_out": self.total_tokens_out,
            "total_cost_usd": self.total_cost_usd,
            "caps_hit": dict(self.caps_hit),
            "tasks": [task.to_dict() for task in self.tasks],
            "event_log": [entry.to_dict() for entry in self.event_log],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MissionReviewPayloadV1":
        return cls(
            schema_version=str(payload.get("schema_version", "mission_review_payload.v1")),
            mission_id=str(payload.get("mission_id", "")),
            mission_name=str(payload.get("mission_name", "")),
            mission_goal=str(payload.get("mission_goal", "")),
            completed_at=payload.get("completed_at"),
            total_retries=int(payload.get("total_retries", 0) or 0),
            total_human_interventions=int(payload.get("total_human_interventions", 0) or 0),
            total_tokens_out=int(payload.get("total_tokens_out", 0) or 0),
            total_cost_usd=float(payload.get("total_cost_usd", 0.0) or 0.0),
            caps_hit={str(key): str(value) for key, value in dict(payload.get("caps_hit", {})).items()},
            tasks=[MissionReviewTaskV1.from_dict(item) for item in payload.get("tasks", [])],
            event_log=[MissionReviewEventV1.from_dict(item) for item in payload.get("event_log", [])],
        )
