"""Telemetry system — persistent metrics across missions."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TaskMetrics:
    """Per-task execution metrics."""
    task_id: str
    task_title: str
    mission_id: str
    
    # Timing
    worker_started: Optional[str] = None
    worker_finished: Optional[str] = None
    worker_duration_s: float = 0.0
    reviewer_started: Optional[str] = None
    reviewer_finished: Optional[str] = None
    reviewer_duration_s: float = 0.0
    total_duration_s: float = 0.0
    
    # Attempts
    worker_attempts: int = 0
    review_attempts: int = 0
    retries: int = 0
    human_interventions: int = 0
    
    # Quality
    review_score: int = 0
    review_approved: bool = False
    review_issues_count: int = 0
    
    # Token usage (from delegate_task metadata)
    worker_input_tokens: int = 0
    worker_output_tokens: int = 0
    reviewer_input_tokens: int = 0
    reviewer_output_tokens: int = 0
    
    # Test results
    test_count: int = 0
    test_pass_count: int = 0
    coverage_percent: float = 0.0

    @property
    def total_input_tokens(self) -> int:
        return self.worker_input_tokens + self.reviewer_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self.worker_output_tokens + self.reviewer_output_tokens

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "TaskMetrics":
        return cls(**{k: d.get(k) for k, v in cls.__dict__.items() if not callable(v)})


@dataclass
class MissionMetrics:
    """Aggregate mission metrics."""
    mission_id: str
    mission_name: str
    started_at: str
    completed_at: str
    total_duration_s: float = 0.0
    
    # Task counts
    total_tasks: int = 0
    approved_on_first_try: int = 0
    approved_with_retries: int = 0
    failed: int = 0
    
    # Aggregates
    total_retries: int = 0
    total_human_interventions: int = 0
    worker_tasks: int = 0
    reviewer_tasks: int = 0
    
    # Quality
    avg_review_score: float = 0.0
    min_review_score: int = 10
    max_review_score: int = 0
    
    # Tokens
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    
    # Tests
    total_test_count: int = 0
    total_test_pass_count: int = 0
    avg_coverage: float = 0.0
    
    # Issues encountered
    issues: list = field(default_factory=list)
    
    # Per-task breakdown
    task_metrics: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "MissionMetrics":
        return cls(**{k: d.get(k, []) if isinstance(v, list) else d.get(k) for k, v in cls.__dict__.items() if not callable(v)})


class TelemetryStore:
    """Persistent metrics store at ~/.agentforce/telemetry/."""

    def __init__(self, base_dir: str | Path = None):
        self.base = Path(base_dir or os.path.expanduser("~/.agentforce/telemetry"))
        self.base.mkdir(parents=True, exist_ok=True)

    def get_mission_file(self, mission_id: str) -> Path:
        return self.base / f"{mission_id}.json"

    def save_mission(self, metrics: MissionMetrics):
        path = self.get_mission_file(metrics.mission_id)
        with open(path, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)

    def load_mission(self, mission_id: str) -> MissionMetrics | None:
        path = self.get_mission_file(mission_id)
        if not path.exists():
            return None
        with open(path) as f:
            return MissionMetrics.from_dict(json.load(f))

    def list_missions(self) -> list[dict]:
        """List all missions with summary metrics."""
        results = []
        for f in sorted(self.base.glob("*.json")):
            try:
                with open(f) as fh:
                    d = json.load(fh)
                results.append({
                    "mission_id": d.get("mission_id", f.stem),
                    "mission_name": d.get("mission_name", ""),
                    "total_tasks": d.get("total_tasks", 0),
                    "total_duration_s": d.get("total_duration_s", 0),
                    "avg_review_score": d.get("avg_review_score", 0),
                    "approved_on_first_try": d.get("approved_on_first_try", 0),
                    "total_retries": d.get("total_retries", 0),
                    "started_at": d.get("started_at", ""),
                })
            except Exception:
                results.append({"mission_id": f.stem, "error": "corrupt"})
        return results

    def append_issue(self, mission_id: str, issue: str):
        path = self.get_mission_file(mission_id)
        if path.exists():
            with open(path) as f:
                d = json.load(f)
            d.setdefault("issues", []).append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": issue,
            })
            with open(path, "w") as f:
                json.dump(d, f, indent=2)
