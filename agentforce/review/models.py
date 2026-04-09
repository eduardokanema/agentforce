from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MetricsSnapshot:
    mission_id: str
    computed_at: str = field(default_factory=_now_iso)
    token_efficiency: float = 0.0
    first_pass_rate: float = 0.0
    rework_rate: float = 0.0
    avg_review_score: float = 0.0
    human_escalation_rate: float = 0.0
    wall_time_per_task_s: float = 0.0
    cost_per_task_usd: float = 0.0
    review_rejection_rate: float = 0.0
    quality_score: float = 0.0
    efficiency_gated: Optional[float] = None
    data_quality_warnings: list[str] = field(default_factory=list)
    tasks_completed: int = 0
    tasks_total: int = 0
    total_retries: int = 0
    total_human_interventions: int = 0
    total_cost_usd: float = 0.0
    total_tokens_out: int = 0
    total_wall_time_s: float = 0.0

    def __post_init__(self) -> None:
        self.quality_score = (
            ((self.avg_review_score / 10) * 0.4)
            + (self.first_pass_rate * 0.25)
            + ((1 - self.human_escalation_rate) * 0.3)
        ) * 10
        if self.quality_score >= 7.0 and self.efficiency_gated is None:
            self.efficiency_gated = self.token_efficiency

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MetricsSnapshot) and self.to_dict() == other.to_dict()

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "computed_at": self.computed_at,
            "token_efficiency": self.token_efficiency,
            "first_pass_rate": self.first_pass_rate,
            "rework_rate": self.rework_rate,
            "avg_review_score": self.avg_review_score,
            "human_escalation_rate": self.human_escalation_rate,
            "wall_time_per_task_s": self.wall_time_per_task_s,
            "cost_per_task_usd": self.cost_per_task_usd,
            "review_rejection_rate": self.review_rejection_rate,
            "quality_score": self.quality_score,
            "efficiency_gated": self.efficiency_gated,
            "data_quality_warnings": self.data_quality_warnings,
            "tasks_completed": self.tasks_completed,
            "tasks_total": self.tasks_total,
            "total_retries": self.total_retries,
            "total_human_interventions": self.total_human_interventions,
            "total_cost_usd": self.total_cost_usd,
            "total_tokens_out": self.total_tokens_out,
            "total_wall_time_s": self.total_wall_time_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MetricsSnapshot:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GoodhartWarning:
    metric_name: str
    metric_direction: str
    quality_direction: str
    message: str
    baseline_quality: float = 0.0
    current_quality: float = 0.0
    baseline_metric: float = 0.0
    current_metric: float = 0.0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GoodhartWarning) and self.to_dict() == other.to_dict()

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "metric_direction": self.metric_direction,
            "quality_direction": self.quality_direction,
            "message": self.message,
            "baseline_quality": self.baseline_quality,
            "current_quality": self.current_quality,
            "baseline_metric": self.baseline_metric,
            "current_metric": self.current_metric,
        }


@dataclass
class RetroItem:
    persona: str
    category: str
    insight: str = ""
    supporting_evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RetroItem) and self.to_dict() == other.to_dict()

    def to_dict(self) -> dict:
        return {
            "persona": self.persona,
            "category": self.category,
            "insight": self.insight,
            "supporting_evidence": self.supporting_evidence,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RetroItem:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ActionItem:
    id: str
    action_type: str
    title: str = ""
    description: str = ""
    priority: str = "medium"
    source_personas: list[str] = field(default_factory=list)
    source_insights: list[str] = field(default_factory=list)
    approved: bool = False
    memory_scope: str = ""
    memory_key: str = ""
    memory_value: str = ""
    memory_category: str = ""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ActionItem) and self.to_dict() == other.to_dict()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "source_personas": self.source_personas,
            "source_insights": self.source_insights,
            "approved": self.approved,
            "memory_scope": self.memory_scope,
            "memory_key": self.memory_key,
            "memory_value": self.memory_value,
            "memory_category": self.memory_category,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ActionItem:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ReviewReport:
    mission_id: str
    mission_name: str = ""
    generated_at: str = field(default_factory=_now_iso)
    metrics: Optional[MetricsSnapshot] = None
    goodhart_warnings: list[GoodhartWarning] = field(default_factory=list)
    retro_items: list[RetroItem] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    raw_persona_outputs: dict[str, str] = field(default_factory=dict)
    review_cost_usd: float = 0.0
    skipped: bool = False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ReviewReport) and self.to_dict() == other.to_dict()

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "mission_name": self.mission_name,
            "generated_at": self.generated_at,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "goodhart_warnings": [w.to_dict() for w in self.goodhart_warnings],
            "retro_items": [r.to_dict() for r in self.retro_items],
            "action_items": [a.to_dict() for a in self.action_items],
            "raw_persona_outputs": self.raw_persona_outputs,
            "review_cost_usd": self.review_cost_usd,
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ReviewReport:
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        fields["metrics"] = MetricsSnapshot.from_dict(d["metrics"]) if d.get("metrics") else None
        fields["goodhart_warnings"] = [GoodhartWarning(**w) for w in d.get("goodhart_warnings", [])]
        fields["retro_items"] = [RetroItem.from_dict(r) for r in d.get("retro_items", [])]
        fields["action_items"] = [ActionItem.from_dict(a) for a in d.get("action_items", [])]
        return cls(**fields)

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path | str) -> ReviewReport:
        return cls.from_dict(json.loads(Path(path).read_text()))
