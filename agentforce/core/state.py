"""Mission state machine — persistent state with event log."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..utils import fmt_duration
from .spec import MissionSpec, TaskStatus, Caps


@dataclass
class TaskState:
    """Runtime state for a single task."""
    task_id: str
    spec_summary: str = ""              # title + first 200 chars of description
    status: TaskStatus = TaskStatus.PENDING
    retries: int = 0
    worker_output: str = ""
    review_feedback: str = ""
    review_score: int = 0                # 0-10 from reviewer
    blocking_issues: list[str] = field(default_factory=list)
    human_intervention_needed: bool = False
    human_intervention_message: str = ""
    error_message: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def can_progress(self) -> bool:
        return self.status in (TaskStatus.PENDING, TaskStatus.RETRY,
                               TaskStatus.SPEC_WRITING, TaskStatus.TESTS_WRITTEN)

    def can_review(self) -> bool:
        return self.status == TaskStatus.COMPLETED

    def needs_human_attention(self) -> bool:
        return self.human_intervention_needed or self.status == TaskStatus.NEEDS_HUMAN

    def bump(self):
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        # Serialize status enum to string for JSON
        status_value = self.status.value if isinstance(self.status, TaskStatus) else self.status
        return {k: v for k, v in {
            "task_id": self.task_id,
            "spec_summary": self.spec_summary,
            "status": status_value,
            "retries": self.retries,
            "worker_output": self.worker_output,
            "review_feedback": self.review_feedback,
            "review_score": self.review_score,
            "blocking_issues": self.blocking_issues,
            "human_intervention_needed": self.human_intervention_needed,
            "human_intervention_message": self.human_intervention_message,
            "error_message": self.error_message,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "last_updated": self.last_updated,
        }.items() if v or v == 0 or v is False or k == "blocking_issues"}

    @classmethod
    def from_dict(cls, d: dict) -> TaskState:
        defaults = {
            "task_id": "",
            "spec_summary": "",
            "status": TaskStatus.PENDING,
            "retries": 0,
            "worker_output": "",
            "review_feedback": "",
            "review_score": 0,
            "blocking_issues": [],
            "human_intervention_needed": False,
            "human_intervention_message": "",
            "error_message": "",
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "started_at": None,
            "completed_at": None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        defaults.update(d)
        defaults["status"] = TaskStatus(d.get("status", "pending"))
        return cls(**defaults)


@dataclass
class EventLogEntry:
    """An entry in the mission event log."""
    timestamp: str
    event_type: str           # task_dispatched, task_completed, review_approved, review_rejected, 
                              # human_intervention, mission_started, mission_completed, mission_failed, task_failed
    task_id: Optional[str] = None
    details: str = ""
    
    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v or v == 0 or v is False or v == ""}

    @classmethod
    def from_dict(cls, d: dict) -> EventLogEntry:
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class MissionState:
    """Persistent state for a running mission."""
    mission_id: str
    spec: MissionSpec
    task_states: dict[str, TaskState] = field(default_factory=dict)
    event_log: list[EventLogEntry] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    total_retries: int = 0
    total_human_interventions: int = 0
    total_tokens_used: int = 0
    estimated_cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    caps_hit: dict[str, str] = field(default_factory=dict)  # cap_name -> description
    
    # Derived from spec but we store snapshot
    working_dir: str = ""
    worker_agent: str = ""   # agent CLI used: "claude", "opencode"
    worker_model: str = ""   # model ID passed to the agent
    daemon_pid: Optional[int] = None
    daemon_started_at: Optional[str] = None

    @property
    def caps(self) -> Caps:
        return self.spec.caps

    def log_event(self, event_type: str, task_id: str = None, details: str = ""):
        self.event_log.append(EventLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            task_id=task_id,
            details=details,
        ))

    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self.task_states.get(task_id)

    def _status_counts(self) -> dict[str, int]:
        counts = {}
        for ts in self.task_states.values():
            counts[ts.status] = counts.get(ts.status, 0) + 1
        return counts

    def is_done(self) -> bool:
        """All tasks review_approved."""
        return all(ts.status == TaskStatus.REVIEW_APPROVED for ts in self.task_states.values())

    def is_failed(self) -> bool:
        """Any task permanently failed or caps hit."""
        if self.caps_hit:
            return True
        return any(ts.status == TaskStatus.FAILED for ts in self.task_states.values())

    def needs_human(self) -> list[str]:
        """Task IDs that need human attention."""
        return [tid for tid, ts in self.task_states.items() if ts.needs_human_attention()]

    def dispatchable_tasks(self) -> list[str]:
        """Tasks ready to be dispatched to workers."""
        result = []
        completed_ids = {
            tid for tid, ts in self.task_states.items() 
            if ts.status == TaskStatus.REVIEW_APPROVED
        }
        for task_spec in self.spec.tasks:
            ts = self.task_states.get(task_spec.id)
            if not ts or not ts.can_progress():
                continue
            # Check dependencies
            deps_met = all(dep in completed_ids for dep in task_spec.dependencies)
            if deps_met:
                result.append(task_spec.id)
        return result

    def reviewable_tasks(self) -> list[str]:
        """Tasks waiting for review."""
        return [
            tid for tid, ts in self.task_states.items()
            if ts.can_review()
        ]

    def worker_count(self) -> int:
        """Currently running workers."""
        return sum(
            1 for ts in self.task_states.values()
            if ts.status in (TaskStatus.IN_PROGRESS, TaskStatus.SPEC_WRITING, TaskStatus.TESTS_WRITTEN)
        )

    def workers_available(self) -> bool:
        return self.worker_count() < self.caps.max_concurrent_workers

    def retry_budget_exhausted(self) -> bool:
        return self.total_retries >= self.caps.max_retries_global

    def wall_time_exceeded(self) -> bool:
        if not self.caps.max_wall_time_minutes:
            return False
        started = datetime.fromisoformat(self.started_at)
        if self.completed_at:
            ended = datetime.fromisoformat(self.completed_at)
        else:
            ended = datetime.now(timezone.utc)
        elapsed = (ended - started).total_seconds() / 60.0
        return elapsed >= self.caps.max_wall_time_minutes

    def interventions_exhausted(self) -> bool:
        return self.total_human_interventions >= self.caps.max_human_interventions

    def check_caps(self) -> str | None:
        """Check if any caps have been hit. Returns cap description or None."""
        cap_checks = {
            "retry_budget": ("Retry budget exhausted", self.retry_budget_exhausted()),
            "wall_time": ("Wall time limit exceeded", self.wall_time_exceeded()),
            "interventions": ("Human intervention limit reached", self.interventions_exhausted()),
        }
        for cap_name, (msg, hit) in cap_checks.items():
            if hit:
                self.caps_hit[cap_name] = msg
                return msg
        return None

    def summary(self) -> str:
        counts = self._status_counts()
        total = len(self.task_states)
        done = counts.get(TaskStatus.REVIEW_APPROVED, 0)
        parts = [
            f"Mission: {self.spec.name} [{self.mission_id}]"
            f"Progress: {done}/{total} tasks approved",
            f"Status breakdown: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
            f"Retries: {self.total_retries}, Interventions: {self.total_human_interventions}",
        ]
        if self.caps_hit:
            parts.append(f"CAPS HIT: {', '.join(f'{k}: {v}' for k, v in self.caps_hit.items())}")
        if self.needs_human():
            parts.append(f"HUMAN ATTENTION: {', '.join(self.needs_human())}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "spec": self.spec.to_dict(),
            "task_states": {k: v.to_dict() for k, v in self.task_states.items()},
            "event_log": [e.to_dict() for e in self.event_log[-200:]],  # Keep last 200 events
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_retries": self.total_retries,
            "total_human_interventions": self.total_human_interventions,
            "caps_hit": self.caps_hit,
            "working_dir": self.working_dir,
            "worker_agent": self.worker_agent,
            "worker_model": self.worker_model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
        }

    def to_summary_dict(self) -> dict:
        done_tasks = sum(1 for ts in self.task_states.values() if ts.status == TaskStatus.REVIEW_APPROVED)
        total_tasks = len(self.spec.tasks)
        pct = int(done_tasks / total_tasks * 100) if total_tasks else 0
        if self.is_done():
            status = "complete"
        elif self.is_failed():
            status = "failed"
        elif self.needs_human():
            status = "needs_human"
        else:
            status = "active"

        return {
            "mission_id": self.mission_id,
            "name": self.spec.name,
            "status": status,
            "done_tasks": done_tasks,
            "total_tasks": total_tasks,
            "pct": pct,
            "duration": fmt_duration(self.started_at, self.completed_at),
            "worker_agent": self.worker_agent,
            "worker_model": self.worker_model,
            "started_at": self.started_at,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MissionState:
        spec = MissionSpec.from_dict(d["spec"])
        task_states = {k: TaskState.from_dict(v) for k, v in d.get("task_states", {}).items()}
        event_log = [EventLogEntry.from_dict(e) for e in d.get("event_log", [])]
        return cls(
            mission_id=d["mission_id"],
            spec=spec,
            task_states=task_states,
            event_log=event_log,
            started_at=d.get("started_at", datetime.now(timezone.utc).isoformat()),
            completed_at=d.get("completed_at"),
            total_retries=d.get("total_retries", 0),
            total_human_interventions=d.get("total_human_interventions", 0),
            tokens_in=d.get("tokens_in", 0),
            tokens_out=d.get("tokens_out", 0),
            cost_usd=d.get("cost_usd", 0.0),
            caps_hit=d.get("caps_hit", {}),
            working_dir=d.get("working_dir", ""),
            worker_agent=d.get("worker_agent", ""),
            worker_model=d.get("worker_model", ""),
        )

    def save(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path | str) -> MissionState:
        with open(path) as f:
            d = json.load(f)
        return cls.from_dict(d)
